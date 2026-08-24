# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""Focused Kit-facing contracts for persisted Streamlines state switching."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from digital_twin_runtime_suite.app.streamlines import playback_runtime
from digital_twin_runtime_suite.app.streamlines.playback import (
    CachedPlaybackContract,
)
from digital_twin_runtime_suite.app.streamlines.playback_runtime import (
    StreamlinesPlaybackRuntimeMixin,
    streamlines_phase_aligned_initial_delay_seconds,
    wait_for_streamlines_kit_frame_deadline,
)
from digital_twin_runtime_suite.app.streamlines.temporal import (
    TemporalSourceSample,
)


def test_cached_playback_switches_persisted_geometry_without_cae_or_vti() -> None:
    runtime = _PlaybackRuntime(_contract())

    resolution = asyncio.run(runtime.select_streamlines_cache_state_in_kit(0.21))

    assert resolution.sample.sample_index == 1
    assert runtime.snapshot_selections == [1]
    assert runtime._streamlines_cache_active_sample_index == 1
    assert runtime.streamlines_snapshot_visible_count_in_kit() == 1


def test_cached_playback_same_state_is_no_op_without_snapshot_selection() -> None:
    runtime = _PlaybackRuntime(_contract())
    runtime._streamlines_cache_active_sample_index = 1
    runtime._visible_snapshot_count = 1

    resolution = asyncio.run(runtime.select_streamlines_cache_state_in_kit(0.39))

    assert resolution.is_no_op is True
    assert runtime.snapshot_selections == []


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


def test_playback_runtime_has_no_mesh_selector_or_timeline_backend() -> None:
    source = Path(playback_runtime.__file__).read_text(encoding="utf-8")

    assert "select_streamlines_mesh_state_in_kit" not in source
    assert "import omni.timeline" not in source
    assert ".set_current_time(" not in source


def test_contract_explicit_selection_does_not_require_committed_target_identity() -> (
    None
):
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
    assert runtime.snapshot_selections == [1]
    assert runtime.mesh_selector_calls == 0


def test_pending_contract_scheduler_mutates_only_while_exactly_authorized() -> None:
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
    assert runtime.snapshot_selections == [1]
    assert runtime.mesh_selector_calls == 0


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
    assert captured["initial_delay_seconds"] == pytest.approx(0.151)
    assert callable(captured["sleep"])


def test_phase_aligned_scheduler_delay_waits_for_the_next_real_cache_state() -> None:
    assert streamlines_phase_aligned_initial_delay_seconds(
        3.25,
        sample_interval_seconds=0.2,
    ) == pytest.approx(0.151)
    assert streamlines_phase_aligned_initial_delay_seconds(
        3.2,
        sample_interval_seconds=0.2,
    ) == pytest.approx(0.201)


def test_kit_frame_deadline_waits_without_an_asyncio_timer() -> None:
    clock = SimpleNamespace(value=0.0)

    async def next_update() -> None:
        clock.value += 0.05

    asyncio.run(
        wait_for_streamlines_kit_frame_deadline(
            0.13,
            next_update=next_update,
            monotonic=lambda: clock.value,
        )
    )

    assert clock.value == pytest.approx(0.15)


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


def test_failed_snapshot_selection_preserves_the_previous_visible_state() -> None:
    runtime = _PlaybackRuntime(_contract())
    runtime._streamlines_cache_active_sample_index = 0
    runtime._visible_snapshot_count = 1
    runtime.fail_snapshot_indices.add(1)

    with pytest.raises(RuntimeError, match="snapshot target rejected"):
        asyncio.run(runtime.select_streamlines_cache_state_in_kit(0.21))

    assert runtime.snapshot_selections == []
    assert runtime._streamlines_cache_active_sample_index == 0
    assert runtime.streamlines_snapshot_visible_count_in_kit() == 1
    assert runtime.mesh_selector_calls == 0


def test_snapshot_ownership_mismatch_is_rejected_before_selection() -> None:
    runtime = _PlaybackRuntime(_contract())
    mismatched_contract = _contract(profile_id="line_detail")

    with pytest.raises(RuntimeError, match="do not match the cached playback"):
        asyncio.run(
            runtime.select_streamlines_cached_contract_state_in_kit(
                mismatched_contract,
                0.21,
            )
        )

    assert runtime.snapshot_selections == []
    assert runtime.mesh_selector_calls == 0


def test_snapshot_cache_identity_mismatch_is_rejected_before_selection() -> None:
    contract = _contract(cache_identity="cache-a")
    runtime = _PlaybackRuntime(contract)
    runtime._streamlines_snapshot_set_ownership.cache_identity = "cache-b"

    with pytest.raises(RuntimeError, match="do not match the cached playback"):
        asyncio.run(
            runtime.select_streamlines_cached_contract_state_in_kit(
                contract,
                0.21,
            )
        )

    assert runtime.snapshot_selections == []
    assert runtime.mesh_selector_calls == 0


def test_scheduler_start_rejects_missing_snapshots_before_creating_a_task() -> None:
    runtime = _PlaybackRuntime(_contract(), presentation_period_seconds=0.2)
    runtime._streamlines_snapshot_set_ownership = None

    with pytest.raises(RuntimeError, match="do not match the cached playback"):
        asyncio.run(runtime.start_streamlines_cached_playback_in_kit())

    assert runtime._active_streamlines_playback_task_count() == 0
    assert runtime.mesh_selector_calls == 0


def test_scheduler_restart_retains_exactly_one_owned_task(monkeypatch) -> None:
    schedulers = []

    class _Scheduler:
        def __init__(self, **_kwargs) -> None:
            self.active = False
            schedulers.append(self)

        async def start(self) -> None:
            self.active = True

        async def stop(self):
            self.active = False
            return None

        @property
        def active_task_count(self) -> int:
            return int(self.active)

    monkeypatch.setattr(playback_runtime, "CachedPlaybackScheduler", _Scheduler)
    runtime = _PlaybackRuntime(_contract(), presentation_period_seconds=0.2)

    async def exercise() -> tuple[int, int, int]:
        await runtime.start_streamlines_cached_playback_in_kit()
        first = runtime._active_streamlines_playback_task_count()
        await runtime.start_streamlines_cached_playback_in_kit()
        restarted = runtime._active_streamlines_playback_task_count()
        await runtime.stop_streamlines_cached_playback_in_kit()
        return first, restarted, runtime._active_streamlines_playback_task_count()

    assert asyncio.run(exercise()) == (1, 1, 0)
    assert len(schedulers) == 2


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
        self._streamlines_snapshot_set_ownership = _snapshot_ownership(contract)
        self._visible_snapshot_count = 0
        self.snapshot_selections: list[int] = []
        self.fail_snapshot_indices: set[int] = set()
        self.mesh_selector_calls = 0

    def select_streamlines_snapshot_state_in_kit(self, sample_index: int) -> bool:
        if sample_index in self.fail_snapshot_indices:
            raise RuntimeError("snapshot target rejected")
        self.snapshot_selections.append(sample_index)
        self._visible_snapshot_count = 1
        self._streamlines_cache_active_sample_index = sample_index
        return True

    def streamlines_snapshot_visible_count_in_kit(self) -> int:
        return self._visible_snapshot_count

    async def select_streamlines_mesh_state_in_kit(self, _sample) -> None:
        self.mesh_selector_calls += 1
        raise AssertionError("Mesh selector must not be called by playback_runtime.")

    def _streamlines_carb_logger(self):
        return None


def _snapshot_ownership(
    contract: CachedPlaybackContract | None,
) -> SimpleNamespace | None:
    if contract is None:
        return None
    return SimpleNamespace(
        workload=contract.workload,
        dataset_identity=contract.dataset_identity,
        profile_id=contract.profile_id,
        cache_identity=contract.cache_identity,
    )


def _contract(
    *,
    profile_id: str = "volume_coverage",
    cache_identity: str = "cache-a",
) -> CachedPlaybackContract:
    return CachedPlaybackContract(
        workload="Nominal",
        dataset_identity="server/load_normal",
        sample_interval_seconds=0.2,
        samples=(
            _sample(0, 0.0),
            _sample(1, 0.2),
            _sample(2, 0.4),
        ),
        profile_id=profile_id,
        cache_identity=cache_identity,
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
