"""Focused Kit-facing contracts for persisted Streamlines state switching."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from digital_twin_runtime_suite.app.streamlines import playback_runtime
from digital_twin_runtime_suite.app.streamlines.playback import (
    CachedPlaybackContract,
)
from digital_twin_runtime_suite.app.streamlines.playback_runtime import (
    PRODUCTION_CACHE_SANITY_PERIOD_SECONDS,
    StreamlinesPlaybackRuntimeMixin,
)
from digital_twin_runtime_suite.app.streamlines.playback_scheduler import (
    CachedPlaybackSchedulerReport,
)
from digital_twin_runtime_suite.app.streamlines.temporal import (
    TemporalSourceSample,
)


def test_cached_playback_switches_persisted_geometry_without_cae_or_vti(
    monkeypatch,
) -> None:
    timeline = _Timeline()
    app = _App()
    _install_playback_modules(monkeypatch, timeline, app)
    runtime = _PlaybackRuntime(_contract())

    resolution = asyncio.run(runtime.select_streamlines_cache_state_in_kit(0.21))

    assert resolution.sample.sample_index == 1
    assert timeline.pauses == 0
    assert timeline.current_time is None
    assert app.update_count == 0
    assert runtime.applied_samples == [1]
    assert runtime._streamlines_cache_active_sample_index == 1
    assert runtime.streamlines_controls_timeline_in_kit() is False

    asyncio.run(runtime.release_streamlines_timeline_control_in_kit())

    assert runtime.streamlines_controls_timeline_in_kit() is False
    assert timeline.pauses == 0


def test_cached_playback_same_state_is_no_op_without_kit_updates(
    monkeypatch,
) -> None:
    timeline = _Timeline()
    app = _App()
    _install_playback_modules(monkeypatch, timeline, app)
    runtime = _PlaybackRuntime(_contract())
    runtime._streamlines_cache_active_sample_index = 1

    resolution = asyncio.run(runtime.select_streamlines_cache_state_in_kit(0.39))

    assert resolution.is_no_op is True
    assert timeline.pauses == 0
    assert app.update_count == 0


def test_cached_playback_rejects_unloaded_cache_before_importing_kit() -> None:
    runtime = _PlaybackRuntime(None)

    with pytest.raises(RuntimeError, match="Load a valid Streamlines cache"):
        asyncio.run(runtime.select_streamlines_cache_state_in_kit(0.0))


def test_cached_playback_rejects_a_cache_outside_shared_airflow_identity() -> None:
    runtime = _PlaybackRuntime(_contract())
    runtime._airflow_state = _airflow_state(
        workload_mode="Critical",
        dataset_identity="server/load_critical",
    )

    with pytest.raises(RuntimeError, match="does not match shared airflow state"):
        asyncio.run(runtime.select_streamlines_cache_state_in_kit(0.0))


def test_contract_explicit_selection_does_not_require_committed_target_identity(
    monkeypatch,
) -> None:
    timeline = _Timeline()
    app = _App()
    _install_playback_modules(monkeypatch, timeline, app)
    contract = _contract()
    runtime = _PlaybackRuntime(contract)
    runtime._airflow_state = _airflow_state(
        workload_mode="Critical",
        dataset_identity="server/load_critical",
    )

    resolution = asyncio.run(
        runtime.select_streamlines_cached_contract_state_in_kit(contract, 0.21)
    )

    assert resolution.sample.sample_index == 1
    assert timeline.current_time is None
    assert app.update_count == 0
    assert runtime.applied_samples == [1]


def test_pending_contract_scheduler_mutates_only_while_exactly_authorized(
    monkeypatch,
) -> None:
    timeline = _Timeline()
    app = _App()
    _install_playback_modules(monkeypatch, timeline, app)
    contract = _contract()
    runtime = _PlaybackRuntime(contract, presentation_period_seconds=0.2)
    runtime._streamlines_cache_active_sample_index = 0
    authorized = False
    selected = {}

    async def capture_scheduler(*, state_selector, **_kwargs):
        selected["selector"] = state_selector

    runtime._start_streamlines_playback_scheduler_in_kit = capture_scheduler

    async def exercise():
        nonlocal authorized
        await runtime.start_streamlines_cached_contract_playback_in_kit(
            contract,
            authorization=lambda: authorized,
        )
        blocked = await selected["selector"](0.21)
        authorized = True
        allowed = await selected["selector"](0.21)
        return blocked, allowed

    blocked, allowed = asyncio.run(exercise())

    assert blocked.is_no_op is True
    assert allowed.sample.sample_index == 1
    assert timeline.pauses == 0
    assert app.update_count == 0
    assert runtime.applied_samples == [1]


def test_production_scheduler_reads_phase_from_shared_airflow_state(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    class _Scheduler:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

        async def start(self) -> None:
            return None

        async def stop(self):
            return None

    monkeypatch.setattr(playback_runtime, "CachedPlaybackScheduler", _Scheduler)
    runtime = _PlaybackRuntime(_contract(), presentation_period_seconds=0.2)
    runtime._airflow_state = _airflow_state(phase_seconds=lambda: 3.25)

    asyncio.run(runtime.start_streamlines_cached_playback_in_kit())

    assert captured["phase_source"]() == 3.25


def test_failed_tick_keeps_previous_state_and_scheduler_selector_alive(
    monkeypatch,
) -> None:
    captured = {}

    class _Scheduler:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

        async def start(self) -> None:
            return None

        async def stop(self):
            return None

    monkeypatch.setattr(playback_runtime, "CachedPlaybackScheduler", _Scheduler)
    runtime = _PlaybackRuntime(_contract(), presentation_period_seconds=0.2)
    runtime._streamlines_cache_active_sample_index = 0

    async def fail_state(_phase_seconds):
        raise RuntimeError("bad point count")

    asyncio.run(
        runtime._start_streamlines_playback_scheduler_in_kit(
            state_selector=fail_state,
            period_seconds=0.2,
            status_callback=None,
        )
    )
    first = asyncio.run(captured["state_selector"](0.21))
    second = asyncio.run(captured["state_selector"](0.41))

    assert first.is_no_op is True
    assert second.is_no_op is True
    assert runtime._streamlines_cache_active_sample_index == 0


def test_production_cache_sanity_uses_only_the_accepted_200_ms_scheduler(
    monkeypatch,
) -> None:
    report = CachedPlaybackSchedulerReport(
        period_seconds=0.2,
        tick_count=20,
        switch_count=10,
        no_op_count=10,
        missed_deadlines=0,
        backlog_count=0,
        maximum_drift_seconds=0.01,
        maximum_switch_latency_seconds=0.03,
        median_switch_latency_seconds=0.02,
        loop_wrap_count=0,
        cancelled=True,
    )

    class _Scheduler:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs
            self.active = False

        async def start(self) -> None:
            self.active = True

        async def stop(self):
            self.active = False
            return report

        @property
        def active_task_count(self) -> int:
            return int(self.active)

    async def _no_wait(_duration: float) -> None:
        return None

    monkeypatch.setattr(playback_runtime, "CachedPlaybackScheduler", _Scheduler)
    monkeypatch.setattr(playback_runtime.asyncio, "sleep", _no_wait)
    runtime = _PlaybackRuntime(_contract(), presentation_period_seconds=0.2)

    async def _warm_up(_phase_seconds: float):
        return SimpleNamespace(is_no_op=False)

    runtime.select_streamlines_cache_state_in_kit = _warm_up

    result = asyncio.run(runtime.run_streamlines_production_cache_sanity_in_kit())

    assert result.scheduler == report
    assert result.passed is True
    assert report.period_seconds == PRODUCTION_CACHE_SANITY_PERIOD_SECONDS
    assert result.maximum_active_playback_task_count == 1
    assert result.active_playback_task_count_after_stop == 0


def test_production_cache_sanity_rejects_deadline_or_backlog_failure(
    monkeypatch,
) -> None:
    report = CachedPlaybackSchedulerReport(
        period_seconds=0.2,
        tick_count=1,
        switch_count=1,
        no_op_count=0,
        missed_deadlines=1,
        backlog_count=0,
        maximum_drift_seconds=0.21,
        maximum_switch_latency_seconds=0.03,
        median_switch_latency_seconds=0.03,
        loop_wrap_count=0,
        cancelled=True,
    )

    class _Scheduler:
        def __init__(self, **_kwargs) -> None:
            self.active = False

        async def start(self) -> None:
            self.active = True

        async def stop(self):
            self.active = False
            return report

        @property
        def active_task_count(self) -> int:
            return int(self.active)

    async def _no_wait(_duration: float) -> None:
        return None

    monkeypatch.setattr(playback_runtime, "CachedPlaybackScheduler", _Scheduler)
    monkeypatch.setattr(playback_runtime.asyncio, "sleep", _no_wait)
    runtime = _PlaybackRuntime(_contract(), presentation_period_seconds=0.2)

    async def _warm_up(_phase_seconds: float):
        return SimpleNamespace(is_no_op=False)

    runtime.select_streamlines_cache_state_in_kit = _warm_up

    with pytest.raises(RuntimeError, match="missed_deadlines=1"):
        asyncio.run(runtime.run_streamlines_production_cache_sanity_in_kit())


def test_production_cache_sanity_loads_without_autostart_and_measures_one_task(
    monkeypatch,
) -> None:
    report = CachedPlaybackSchedulerReport(
        period_seconds=0.2,
        tick_count=20,
        switch_count=10,
        no_op_count=10,
        missed_deadlines=0,
        backlog_count=0,
        maximum_drift_seconds=0.01,
        maximum_switch_latency_seconds=0.04,
        median_switch_latency_seconds=0.02,
        loop_wrap_count=0,
        cancelled=True,
    )
    starts: list[object] = []
    loads: list[dict[str, object]] = []

    class _Scheduler:
        def __init__(self, **_kwargs) -> None:
            self.active = False
            starts.append(self)

        async def start(self) -> None:
            self.active = True

        async def stop(self):
            self.active = False
            return report

        @property
        def active_task_count(self) -> int:
            return int(self.active)

    async def _no_wait(_duration: float) -> None:
        return None

    async def _load(**kwargs) -> None:
        loads.append(kwargs)
        runtime._streamlines_cache_playback_contract = _contract()

    async def _warm_up(_phase_seconds: float):
        return SimpleNamespace(is_no_op=False)

    monkeypatch.setattr(playback_runtime, "CachedPlaybackScheduler", _Scheduler)
    monkeypatch.setattr(playback_runtime.asyncio, "sleep", _no_wait)
    runtime = _PlaybackRuntime(None, presentation_period_seconds=0.2)
    runtime.load_streamlines_cache_in_kit = _load
    runtime.select_streamlines_cache_state_in_kit = _warm_up

    result = asyncio.run(runtime.run_streamlines_production_cache_sanity_in_kit())

    assert loads == [{"status_callback": None, "start_playback": False}]
    assert len(starts) == 1
    assert result.maximum_active_playback_task_count == 1
    assert result.active_playback_task_count_after_stop == 0


def test_cadence_action_is_ready_only_after_validated_cache_load() -> None:
    ready = _PlaybackRuntime(_contract())
    ready._flow_lifecycle_state = "DETACHED"
    blocked = _PlaybackRuntime(None)
    blocked._flow_lifecycle_state = "DETACHED"

    assert ready.is_streamlines_cadence_characterization_ready() is True
    assert ready.announce_streamlines_cadence_characterization_ready() == (
        'Ready — Press "Run Cadence Characterization".'
    )
    assert blocked.is_streamlines_cadence_characterization_ready() is False
    assert blocked.announce_streamlines_cadence_characterization_ready() == (
        "Load Streamlines Cache before cadence characterization."
    )


def test_fast_cadence_action_requires_the_accepted_500_ms_baseline() -> None:
    ready = _PlaybackRuntime(_contract(), presentation_period_seconds=0.5)
    ready._flow_lifecycle_state = "DETACHED"
    unproven = _PlaybackRuntime(_contract(), presentation_period_seconds=0.25)
    unproven._flow_lifecycle_state = "DETACHED"

    assert ready.is_streamlines_fast_cadence_check_ready() is True
    assert ready.announce_streamlines_fast_cadence_check_ready() == (
        'Ready — Press "Run Fast Cadence Check".'
    )
    assert unproven.is_streamlines_fast_cadence_check_ready() is False
    assert unproven.announce_streamlines_fast_cadence_check_ready() == (
        "Run Cadence Characterization before the fast cadence check."
    )


def test_200_ms_wrap_recheck_requires_the_accepted_250_ms_fallback() -> None:
    ready = _PlaybackRuntime(_contract(), presentation_period_seconds=0.25)
    ready._flow_lifecycle_state = "DETACHED"
    unproven = _PlaybackRuntime(_contract(), presentation_period_seconds=0.2)
    unproven._flow_lifecycle_state = "DETACHED"

    assert ready.is_streamlines_200ms_wrap_recheck_ready() is True
    assert ready.announce_streamlines_200ms_wrap_recheck_ready() == (
        'Ready — Press "Recheck 200 ms Wrap".'
    )
    assert unproven.is_streamlines_200ms_wrap_recheck_ready() is False
    assert unproven.announce_streamlines_200ms_wrap_recheck_ready() == (
        "A confirmed 250 ms Streamlines period is required for recheck."
    )


class _PlaybackRuntime(StreamlinesPlaybackRuntimeMixin):
    def __init__(
        self,
        contract: CachedPlaybackContract | None,
        presentation_period_seconds: float | None = None,
    ) -> None:
        self._flow_lifecycle_state = "DETACHED"
        self._streamlines_cache_playback_contract = contract
        self._streamlines_cache_active_sample_index: int | None = None
        self.config = SimpleNamespace(
            simulation_cache=SimpleNamespace(
                streamlines_presentation_period_seconds=(presentation_period_seconds)
            )
        )
        self._airflow_state = _airflow_state()
        self.applied_samples: list[int] = []

    async def apply_streamlines_cached_state_in_kit(self, sample) -> None:
        self.applied_samples.append(sample.sample_index)
        self._streamlines_cache_active_sample_index = sample.sample_index

    async def select_streamlines_mesh_state_in_kit(self, sample) -> None:
        await self.apply_streamlines_cached_state_in_kit(sample)

    def acquire_streamlines_timeline_control_in_kit(self) -> None:
        return None

    def _streamlines_carb_logger(self):
        return None


class _Timeline:
    def __init__(self) -> None:
        self.pauses = 0
        self.current_time: float | None = None
        self.playing = True

    def is_playing(self) -> bool:
        return self.playing

    def get_current_time(self) -> float:
        return 7.25

    def pause(self) -> None:
        self.pauses += 1
        self.playing = False

    def set_current_time(self, value: float) -> None:
        self.current_time = value


class _App:
    def __init__(self) -> None:
        self.update_count = 0

    async def next_update_async(self) -> None:
        self.update_count += 1


class _Prim:
    def IsValid(self) -> bool:
        return True


class _Stage:
    def GetPrimAtPath(self, _path: str) -> _Prim:
        return _Prim()


def _install_playback_modules(monkeypatch, timeline: _Timeline, app: _App) -> None:
    omni = _package("omni")
    kit = _package("omni.kit")
    kit_app = ModuleType("omni.kit.app")
    kit_app.get_app = lambda: app
    timeline_module = ModuleType("omni.timeline")
    timeline_module.get_timeline_interface = lambda: timeline
    usd = ModuleType("omni.usd")
    usd.get_context = lambda: SimpleNamespace(get_stage=lambda: _Stage())

    omni.kit = kit
    omni.timeline = timeline_module
    omni.usd = usd
    kit.app = kit_app
    for module in (omni, kit, kit_app, timeline_module, usd):
        monkeypatch.setitem(sys.modules, module.__name__, module)


def _contract() -> CachedPlaybackContract:
    return CachedPlaybackContract(
        workload="Nominal",
        dataset_identity="server/load_normal",
        sample_interval_seconds=0.2,
        samples=(
            _sample(0, 0.0),
            _sample(1, 0.2),
            _sample(2, 0.4),
        ),
    )


def _sample(index: int, source_time_seconds: float) -> TemporalSourceSample:
    return TemporalSourceSample(
        ordinal=index + 1,
        total=3,
        sample_index=index,
        source_vti=Path(f"sample_{index}.vti"),
        source_time_seconds=source_time_seconds,
        time_code=source_time_seconds * 60.0,
    )


def _airflow_state(
    *,
    workload_mode: str = "Nominal",
    dataset_identity: str = "server/load_normal",
    phase_seconds=lambda: 0.0,
) -> SimpleNamespace:
    binding = SimpleNamespace(dataset_identity=dataset_identity)
    target = SimpleNamespace(workload_mode=workload_mode, binding=binding)
    return SimpleNamespace(
        committed=target,
        phase_seconds=phase_seconds,
        resolve_current=lambda: target,
    )


def _package(name: str) -> ModuleType:
    package = ModuleType(name)
    package.__path__ = []
    return package
