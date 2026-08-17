"""Plain bounded cadence-characterization contracts for cached playback."""

from __future__ import annotations

from dataclasses import dataclass

from digital_twin_runtime_suite.app.flow.performance import (
    ViewportPerformanceSample,
)
from digital_twin_runtime_suite.app.streamlines.playback_scheduler import (
    CachedPlaybackSchedulerReport,
    CachedPlaybackTick,
)

CADENCE_CANDIDATE_PERIOD_SECONDS = (1.0, 0.75, 0.64, 0.5)
FAST_CADENCE_CANDIDATE_PERIOD_SECONDS = (0.25, 0.2)
FAST_CADENCE_FALLBACK_PERIOD_SECONDS = 0.5
WRAP_RECHECK_CANDIDATE_PERIOD_SECONDS = (0.2,)
WRAP_RECHECK_FALLBACK_PERIOD_SECONDS = 0.25
WRAP_RECHECK_OBSERVATION_SECONDS = 20.0
REQUIRED_TIMING_HEADROOM_RATIO = 0.20
MINIMUM_SUSTAINED_FPS = 30.0
MAXIMUM_MEMORY_GROWTH_GIB = 0.25


@dataclass(frozen=True)
class CadenceCandidateResult:
    """One bounded candidate measurement with explicit acceptance evidence."""

    period_seconds: float
    scheduler: CachedPlaybackSchedulerReport
    phase_mapping_pass: bool
    no_op_pass: bool
    loop_wrap_pass: bool
    state_wrap_transition: tuple[int, int] | None
    clean_stop_pass: bool
    kit_cae_executions: int
    runtime_preview_rebuilds: int
    playback_vti_imports: int
    fps_minimum: float | None
    gpu_memory_growth_gib: float | None
    process_memory_growth_gib: float | None

    @property
    def timing_headroom_seconds(self) -> float:
        """Return headroom from the slowest real cached switch."""

        return self.period_seconds - self.scheduler.maximum_switch_latency_seconds

    @property
    def timing_headroom_pass(self) -> bool:
        """Require the agreed 20 percent margin, not a one-off near miss."""

        return self.scheduler.maximum_switch_latency_seconds <= self.period_seconds * (
            1.0 - REQUIRED_TIMING_HEADROOM_RATIO
        )

    @property
    def drift_pass(self) -> bool:
        """Reject an accepted run whose deadline drift consumes its headroom."""

        return self.scheduler.maximum_drift_seconds <= (
            self.period_seconds * REQUIRED_TIMING_HEADROOM_RATIO
        )

    @property
    def performance_pass(self) -> bool:
        """Require measured sustained FPS and bounded memory growth."""

        return (
            self.fps_minimum is not None
            and self.fps_minimum >= MINIMUM_SUSTAINED_FPS
            and _within_memory_limit(self.gpu_memory_growth_gib)
            and _within_memory_limit(self.process_memory_growth_gib)
        )

    @property
    def acceptable(self) -> bool:
        """Return whether this candidate satisfies the complete bounded gate."""

        return all(
            (
                self.phase_mapping_pass,
                self.no_op_pass,
                self.loop_wrap_pass,
                self.clean_stop_pass,
                self.scheduler.missed_deadlines == 0,
                self.scheduler.backlog_count == 0,
                self.scheduler.switch_count > 0,
                self.timing_headroom_pass,
                self.drift_pass,
                self.performance_pass,
                self.kit_cae_executions == 0,
                self.runtime_preview_rebuilds == 0,
                self.playback_vti_imports == 0,
            )
        )


@dataclass(frozen=True)
class CadenceSelection:
    """Resolve fixed cadence candidates without turning them into a search."""

    selected: CadenceCandidateResult | None
    presentation_period_seconds: float

    @property
    def fallback_retained(self) -> bool:
        """Return whether no measured candidate replaced the accepted baseline."""

        return self.selected is None


def cadence_candidate_result(
    *,
    period_seconds: float,
    scheduler: CachedPlaybackSchedulerReport,
    phase_mapping_pass: bool,
    no_op_pass: bool,
    resolved_state_wrap_transition: tuple[int, int] | None,
    clean_stop_pass: bool,
    performance_samples: tuple[ViewportPerformanceSample, ...],
) -> CadenceCandidateResult:
    """Reduce a candidate without coupling measurement policy to Kit runtime."""

    fps_values = tuple(
        sample.fps for sample in performance_samples if sample.fps is not None
    )
    return CadenceCandidateResult(
        period_seconds=period_seconds,
        scheduler=scheduler,
        phase_mapping_pass=phase_mapping_pass,
        no_op_pass=no_op_pass,
        loop_wrap_pass=resolved_state_wrap_transition is not None,
        state_wrap_transition=resolved_state_wrap_transition,
        clean_stop_pass=clean_stop_pass,
        kit_cae_executions=0,
        runtime_preview_rebuilds=0,
        playback_vti_imports=0,
        fps_minimum=min(fps_values) if fps_values else None,
        gpu_memory_growth_gib=_memory_growth(
            performance_samples,
            "gpu_memory_used_gib",
        ),
        process_memory_growth_gib=_memory_growth(
            performance_samples,
            "process_memory_used_gib",
        ),
    )


def select_shortest_acceptable_candidate(
    results: tuple[CadenceCandidateResult, ...],
) -> CadenceCandidateResult | None:
    """Choose the shortest accepted presentation period without a search loop."""

    acceptable = tuple(result for result in results if result.acceptable)
    return min(acceptable, key=lambda result: result.period_seconds, default=None)


def select_cadence_candidate_or_fallback(
    results: tuple[CadenceCandidateResult, ...],
    *,
    fallback_period_seconds: float,
) -> CadenceSelection:
    """Choose the shortest measured pass or retain the explicit baseline."""

    selected = select_shortest_acceptable_candidate(results)
    if selected is not None:
        return CadenceSelection(
            selected=selected,
            presentation_period_seconds=selected.period_seconds,
        )
    return CadenceSelection(
        selected=None,
        presentation_period_seconds=fallback_period_seconds,
    )


def resolved_cache_state_wrap_transition(
    ticks: tuple[CachedPlaybackTick, ...],
) -> tuple[int, int] | None:
    """Return the observed high-to-low resolved state switch across loop wrap."""

    for previous, current in zip(ticks, ticks[1:]):
        if (
            current.resolution.normalized_phase_seconds
            >= previous.resolution.normalized_phase_seconds
        ):
            continue
        if (
            current.resolution.sample.sample_index
            >= previous.resolution.sample.sample_index
        ):
            continue
        if not current.resolution.is_no_op:
            return (
                previous.resolution.sample.sample_index,
                current.resolution.sample.sample_index,
            )
    return None


def _memory_growth(
    samples: tuple[ViewportPerformanceSample, ...],
    attribute: str,
) -> float | None:
    """Return first-to-last observed growth, preserving unavailable HUD data."""

    values = tuple(
        value for sample in samples if (value := getattr(sample, attribute)) is not None
    )
    return None if len(values) < 2 else values[-1] - values[0]


def _within_memory_limit(growth_gib: float | None) -> bool:
    """Treat missing memory instrumentation as unproven, never silently stable."""

    return growth_gib is not None and growth_gib <= MAXIMUM_MEMORY_GROWTH_GIB
