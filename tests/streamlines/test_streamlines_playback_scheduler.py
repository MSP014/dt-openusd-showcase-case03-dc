"""Focused deadline and no-backlog contracts for Streamlines cached playback."""

from __future__ import annotations

import asyncio

from digital_twin_runtime_suite.app.flow.performance import (
    ViewportPerformanceSample,
)
from digital_twin_runtime_suite.app.streamlines.cadence_probe import (
    FAST_CADENCE_CANDIDATE_PERIOD_SECONDS,
    FAST_CADENCE_FALLBACK_PERIOD_SECONDS,
    WRAP_RECHECK_CANDIDATE_PERIOD_SECONDS,
    WRAP_RECHECK_FALLBACK_PERIOD_SECONDS,
    WRAP_RECHECK_OBSERVATION_SECONDS,
    cadence_candidate_result,
    resolved_cache_state_wrap_transition,
    select_cadence_candidate_or_fallback,
    select_shortest_acceptable_candidate,
)
from digital_twin_runtime_suite.app.streamlines.playback_scheduler import (
    CachedPlaybackScheduler,
    CachedPlaybackSchedulerReport,
    CachedPlaybackTick,
)
from digital_twin_runtime_suite.app.streamlines.temporal import (
    TemporalSampleResolution,
    TemporalSourceSample,
    resolve_manifest_sample,
)


def test_scheduler_uses_immutable_deadlines_without_drift() -> None:
    clock = _Clock()
    phases: list[float] = []
    scheduler = _scheduler(clock, phases, target_ticks=3, period_seconds=0.5)

    asyncio.run(_start_and_stop(scheduler))

    report = scheduler.report()
    assert phases == [0.0, 0.5, 1.0]
    assert report.tick_count == 3
    assert report.maximum_drift_seconds == 0.0
    assert report.missed_deadlines == 0
    assert report.backlog_count == 0


def test_scheduler_counts_repeated_no_ops_without_queueing() -> None:
    clock = _Clock()
    phases: list[float] = []
    scheduler = _scheduler(
        clock,
        phases,
        target_ticks=4,
        period_seconds=0.1,
    )

    asyncio.run(_start_and_stop(scheduler))

    report = scheduler.report()
    assert report.switch_count == 1
    assert report.no_op_count == 3
    assert report.backlog_count == 0


def test_scheduler_skips_expired_deadlines_and_reads_current_phase() -> None:
    clock = _Clock()
    phases: list[float] = []
    scheduler = _scheduler(
        clock,
        phases,
        target_ticks=2,
        period_seconds=1.0,
        first_switch_delay_seconds=2.5,
    )

    asyncio.run(_start_and_stop(scheduler))

    report = scheduler.report()
    assert phases == [0.0, 3.0]
    assert report.missed_deadlines == 2
    assert report.backlog_count == 0


def test_scheduler_observes_loop_wrap_from_current_phase() -> None:
    clock = _Clock()
    phases: list[float] = []
    scheduler = _scheduler(
        clock,
        phases,
        target_ticks=4,
        period_seconds=0.75,
        sample_count=2,
    )

    asyncio.run(_start_and_stop(scheduler))

    assert phases == [0.0, 0.75, 1.5, 2.25]
    assert scheduler.report().loop_wrap_count == 1


def test_scheduler_cancels_and_restarts_without_residue() -> None:
    clock = _Clock()
    phases: list[float] = []
    scheduler = _scheduler(clock, phases, target_ticks=1, period_seconds=1.0)

    async def exercise_restart() -> None:
        await scheduler.start()
        await scheduler.stop()
        assert scheduler.active is False
        await scheduler.restart()
        await scheduler.stop()

    asyncio.run(exercise_restart())

    assert scheduler.active is False
    assert scheduler.report().cancelled is True
    assert scheduler.report().backlog_count == 0


def test_cadence_probe_accepts_only_measured_headroom_and_stable_memory() -> None:
    scheduler = CachedPlaybackSchedulerReport(
        period_seconds=0.5,
        tick_count=33,
        switch_count=32,
        no_op_count=1,
        missed_deadlines=0,
        backlog_count=0,
        maximum_drift_seconds=0.01,
        maximum_switch_latency_seconds=0.1,
        median_switch_latency_seconds=0.05,
        loop_wrap_count=1,
        cancelled=True,
    )
    samples = (
        ViewportPerformanceSample(0.0, 60.0, 16.7, 1.0, 2.0),
        ViewportPerformanceSample(1.0, 58.0, 17.2, 1.1, 2.1),
    )
    accepted = cadence_candidate_result(
        period_seconds=0.5,
        scheduler=scheduler,
        phase_mapping_pass=True,
        no_op_pass=True,
        resolved_state_wrap_transition=(79, 0),
        clean_stop_pass=True,
        performance_samples=samples,
    )
    rejected = cadence_candidate_result(
        period_seconds=0.64,
        scheduler=scheduler,
        phase_mapping_pass=True,
        no_op_pass=True,
        resolved_state_wrap_transition=(79, 0),
        clean_stop_pass=True,
        performance_samples=(ViewportPerformanceSample(0.0, None, None, None, None),),
    )

    assert accepted.acceptable is True
    assert rejected.acceptable is False
    assert select_shortest_acceptable_candidate((rejected, accepted)) == accepted


def test_fast_cadence_selection_prefers_200_then_250_then_baseline() -> None:
    accepted_250 = _cadence_candidate(0.25, acceptable=True)
    accepted_200 = _cadence_candidate(0.2, acceptable=True)
    rejected_200 = _cadence_candidate(0.2, acceptable=False)
    rejected_250 = _cadence_candidate(0.25, acceptable=False)

    fastest = select_cadence_candidate_or_fallback(
        (accepted_250, accepted_200),
        fallback_period_seconds=FAST_CADENCE_FALLBACK_PERIOD_SECONDS,
    )
    middle = select_cadence_candidate_or_fallback(
        (accepted_250, rejected_200),
        fallback_period_seconds=FAST_CADENCE_FALLBACK_PERIOD_SECONDS,
    )
    fallback = select_cadence_candidate_or_fallback(
        (rejected_250, rejected_200),
        fallback_period_seconds=FAST_CADENCE_FALLBACK_PERIOD_SECONDS,
    )
    recheck = select_cadence_candidate_or_fallback(
        (rejected_200,),
        fallback_period_seconds=WRAP_RECHECK_FALLBACK_PERIOD_SECONDS,
    )

    assert FAST_CADENCE_CANDIDATE_PERIOD_SECONDS == (0.25, 0.2)
    assert fastest.presentation_period_seconds == 0.2
    assert fastest.selected == accepted_200
    assert middle.presentation_period_seconds == 0.25
    assert middle.selected == accepted_250
    assert fallback.presentation_period_seconds == FAST_CADENCE_FALLBACK_PERIOD_SECONDS
    assert fallback.selected is None
    assert fallback.fallback_retained is True
    assert WRAP_RECHECK_CANDIDATE_PERIOD_SECONDS == (0.2,)
    assert WRAP_RECHECK_OBSERVATION_SECONDS == 20.0
    assert recheck.presentation_period_seconds == 0.25
    assert recheck.fallback_retained is True


def test_resolved_cache_state_wrap_requires_a_high_to_low_select() -> None:
    high_manifest_state = _tick(
        sample_index=79,
        phase_seconds=15.8,
        decision="SELECT",
    )
    low_manifest_state = _tick(
        sample_index=0,
        phase_seconds=0.0,
        decision="SELECT",
    )
    low_manifest_no_op = _tick(
        sample_index=0,
        phase_seconds=0.0,
        decision="NO_OP",
    )

    assert resolved_cache_state_wrap_transition(
        (high_manifest_state, low_manifest_state)
    ) == (79, 0)
    assert (
        resolved_cache_state_wrap_transition((high_manifest_state, low_manifest_no_op))
        is None
    )


async def _start_and_stop(scheduler: CachedPlaybackScheduler) -> None:
    await scheduler.start()
    for _ in range(100):
        if not scheduler.active:
            break
        await asyncio.sleep(0)
    await scheduler.stop()


def _cadence_candidate(
    period_seconds: float,
    *,
    acceptable: bool,
):
    maximum_switch_latency_seconds = period_seconds * (0.79 if acceptable else 0.81)
    scheduler = CachedPlaybackSchedulerReport(
        period_seconds=period_seconds,
        tick_count=65,
        switch_count=64,
        no_op_count=1,
        missed_deadlines=0,
        backlog_count=0,
        maximum_drift_seconds=period_seconds * 0.1,
        maximum_switch_latency_seconds=maximum_switch_latency_seconds,
        median_switch_latency_seconds=maximum_switch_latency_seconds / 2.0,
        loop_wrap_count=1,
        cancelled=True,
    )
    return cadence_candidate_result(
        period_seconds=period_seconds,
        scheduler=scheduler,
        phase_mapping_pass=True,
        no_op_pass=True,
        resolved_state_wrap_transition=(79, 0),
        clean_stop_pass=True,
        performance_samples=(
            ViewportPerformanceSample(0.0, 60.0, 16.7, 1.0, 2.0),
            ViewportPerformanceSample(1.0, 58.0, 17.2, 1.1, 2.1),
        ),
    )


def _tick(
    *,
    sample_index: int,
    phase_seconds: float,
    decision: str,
) -> CachedPlaybackTick:
    sample = TemporalSourceSample(
        ordinal=sample_index + 1,
        total=80,
        sample_index=sample_index,
        source_vti=None,  # This test proves resolver evidence, not source IO.
        source_time_seconds=sample_index * 0.2,
        time_code=sample_index * 12.0,
    )
    resolution = TemporalSampleResolution(
        phase_seconds=phase_seconds,
        normalized_phase_seconds=phase_seconds,
        loop_duration_seconds=16.0,
        sample=sample,
        decision=decision,
    )
    return CachedPlaybackTick(
        deadline_seconds=phase_seconds,
        phase_seconds=phase_seconds,
        resolution=resolution,
        started_at_seconds=phase_seconds,
        completed_at_seconds=phase_seconds,
    )


def _scheduler(
    clock: "_Clock",
    phases: list[float],
    *,
    target_ticks: int,
    period_seconds: float,
    sample_count: int = 3,
    first_switch_delay_seconds: float = 0.0,
) -> CachedPlaybackScheduler:
    samples = tuple(
        TemporalSourceSample(
            ordinal=index + 1,
            total=sample_count,
            sample_index=index,
            source_vti=None,  # The scheduler owns phases, not source files.
            source_time_seconds=float(index),
            time_code=float(index),
        )
        for index in range(sample_count)
    )
    active_sample_index: int | None = None
    scheduler: CachedPlaybackScheduler

    async def select(phase_seconds: float):
        nonlocal active_sample_index
        phases.append(phase_seconds)
        resolution = resolve_manifest_sample(
            samples,
            sample_interval_seconds=1.0,
            phase_seconds=phase_seconds,
            active_sample_index=active_sample_index,
        )
        active_sample_index = resolution.sample.sample_index
        if len(phases) == 1 and first_switch_delay_seconds:
            clock.advance(first_switch_delay_seconds)
        if len(phases) >= target_ticks:
            scheduler.cancel()
        return resolution

    scheduler = CachedPlaybackScheduler(
        period_seconds=period_seconds,
        phase_source=lambda: clock.now,
        state_selector=select,
        monotonic=lambda: clock.now,
        sleep=clock.sleep,
    )
    return scheduler


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def advance(self, seconds: float) -> None:
        self.now += seconds

    async def sleep(self, seconds: float) -> None:
        self.advance(seconds)
        await asyncio.sleep(0)
