"""Focused transactional Streamlines workload-switch contracts."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from digital_twin_runtime_suite.app.airflow_dataset import (
    AirflowDataset,
    AirflowDatasetManifest,
    AirflowDatasetSelector,
)
from digital_twin_runtime_suite.app.airflow_state.runtime import AirflowStateRuntime
from digital_twin_runtime_suite.app.airflow_state.temporal import (
    temporal_samples_from_airflow_dataset,
)
from digital_twin_runtime_suite.app.commands import RuntimeController
from digital_twin_runtime_suite.app.streamlines.playback import (
    CachedPlaybackContract,
)
from digital_twin_runtime_suite.app.streamlines.workload_transition import (
    StreamlinesWorkloadTransitionMixin,
)
from digital_twin_runtime_suite.app.visualization_mode.model import (
    VisualizationMode,
)
from digital_twin_runtime_suite.app.workload_binding.runtime import (
    WorkloadBindingRuntime,
)


class _Runtime(StreamlinesWorkloadTransitionMixin):
    def __init__(self, *, unequal: bool = False) -> None:
        self.clock = [100.0]
        self.semantic_workload = "Nominal"
        self.datasets = _datasets(unequal=unequal)
        self._airflow_state = AirflowStateRuntime(
            WorkloadBindingRuntime(_Cache(), lambda: self.semantic_workload),
            tuple(self.datasets.values()),
            monotonic=lambda: self.clock[0],
        )
        baseline = self._airflow_state.begin_for_workload("Nominal")
        assert baseline is not None and self._airflow_state.commit(
            baseline.transition_id
        )
        self._visualization_committed = VisualizationMode.STREAMLINES
        self._visualization_pending = None
        self._visualization_mode_lock = asyncio.Lock()
        self._streamlines_cache_playback_contract = self._contract("Nominal")
        self._streamlines_cache_active_sample_index = 0
        self.reference_asset = "load_normal/streamlines_cache.usdc"
        self.reference_history = [self.reference_asset]
        self.visible = True
        self.scheduler_tasks = 1
        self.snapshot_roots = ("/DTRS_StreamlinesSnapshots/Nominal",)
        self.material_bindings = {
            self.snapshot_roots[0]: "/DTRS_Looks/StreamlinesVelocity"
        }
        self._xray_override_owner = None
        self.classifications = {workload: "VALID" for workload in self.datasets}
        self.prepare_count = 0
        self.cleanup_count = 0
        self.scheduler_start_count = 0
        self.flow_attach_calls = 0
        self.cache_builds = 0
        self.recomputes = 0
        self.kit_cae_executions = 0
        self.vti_imports = 0
        self.target_advances = True
        self.rollback_advances = True
        self.commit_seen_before_proof = False
        self.prepared_sample_index = None
        self.validation_started = None
        self.validation_release = None
        self.blocked_workload = None
        self.proof_started = None
        self.proof_release = None
        self.blocked_proof_workload = None
        self.reset_streamlines_workload_transition_state()

    def visualization_snapshot(self):
        return SimpleNamespace(
            committed=self._visualization_committed,
            pending=self._visualization_pending,
        )

    async def ensure_streamlines_cache_validation_in_background(
        self,
        binding,
        _dataset,
    ):
        if binding.workload_mode == self.blocked_workload:
            self.validation_started.set()
            await self.validation_release.wait()
        classification = self.classifications[binding.workload_mode]
        return SimpleNamespace(
            inspection=SimpleNamespace(
                classification=classification,
                message=f"Cache is {classification}.",
            )
        )

    async def prepare_streamlines_cached_target_in_kit(
        self,
        binding,
        _dataset,
        _phase_seconds,
        *,
        expected_sample_index,
        expected_source_vti,
        cancellation_requested=None,
        **_kwargs,
    ):
        if cancellation_requested and cancellation_requested():
            raise RuntimeError("candidate superseded before preparation")
        self.prepare_count += 1
        self.scheduler_tasks = 0
        self.visible = False
        self._streamlines_cache_playback_contract = self._contract(
            binding.workload_mode
        )
        self.reference_asset = f"{binding.dataset_identity}/streamlines_cache.usdc"
        self.reference_history.append(self.reference_asset)
        root = f"/DTRS_StreamlinesSnapshots/{binding.workload_mode}"
        self.snapshot_roots = (root,)
        self.material_bindings = {root: "/DTRS_Looks/StreamlinesVelocity"}
        self._streamlines_cache_active_sample_index = expected_sample_index
        sample = self._streamlines_cache_playback_contract.samples[
            expected_sample_index
        ]
        assert sample.source_vti == expected_source_vti
        self.prepared_sample_index = sample.sample_index
        return SimpleNamespace(sample=sample)

    async def start_streamlines_cached_contract_playback_in_kit(
        self,
        _contract,
        *,
        authorization,
        **_kwargs,
    ) -> None:
        assert authorization()
        self.scheduler_start_count += 1
        self.scheduler_tasks = 1
        self._authorization = authorization

    async def start_streamlines_cached_playback_in_kit(self, **_kwargs) -> None:
        self.scheduler_start_count += 1
        self.scheduler_tasks = 1

    async def await_streamlines_cached_playback_advancement_in_kit(
        self,
        initial_sample,
        *,
        cancellation_requested=None,
    ):
        target_workload = self._streamlines_cache_playback_contract.workload
        if target_workload == self.blocked_proof_workload:
            self.proof_started.set()
            await self.proof_release.wait()
        if cancellation_requested and cancellation_requested():
            raise RuntimeError("candidate superseded during playback proof")
        contract = self._streamlines_cache_playback_contract
        committed = self._airflow_state.committed
        if committed and committed.workload_mode == target_workload:
            advances = self.rollback_advances
        else:
            advances = self.target_advances
            self.commit_seen_before_proof = bool(
                committed and committed.workload_mode == target_workload
            )
        later_index = (initial_sample.sample_index + 1) % len(contract.samples)
        later = contract.samples[later_index]
        initial_identity = self._streamlines_cached_sample_identity(initial_sample)
        advanced_identity = (
            self._streamlines_cached_sample_identity(later) if advances else None
        )
        return SimpleNamespace(
            initial_sample_identity=initial_identity,
            advanced_sample_identity=advanced_identity,
            scheduler_tasks=self.scheduler_tasks,
            scheduler_tick_count=(2 if advances else 1),
            sample_advanced=advances,
        )

    async def cleanup_streamlines_cached_presentation_in_kit(self) -> None:
        self.cleanup_count += 1
        self.scheduler_tasks = 0
        self.visible = False
        self._streamlines_cache_playback_contract = None
        self.reference_asset = None

    def set_streamlines_cached_presentation_visible_in_kit(self, visible):
        self.visible = visible
        return True

    def streamlines_cached_presentation_is_visible_in_kit(self):
        return self.visible

    def _active_streamlines_playback_task_count(self):
        return self.scheduler_tasks

    def streamlines_cached_playback_advanced_in_kit(self):
        return self.scheduler_tasks == 1

    def visualization_flow_attach_call_count(self):
        return self.flow_attach_calls

    def xray_target_snapshot(self):
        return SimpleNamespace(override_owner=self._xray_override_owner)

    @staticmethod
    def _streamlines_cached_sample_identity(sample) -> str:
        return f"index={sample.sample_index}; source={sample.source_vti.name}"

    def _contract(self, workload: str) -> CachedPlaybackContract:
        dataset = self.datasets[workload]
        return CachedPlaybackContract(
            workload=workload,
            dataset_identity=(f"{dataset.manifest.scope}/{dataset.manifest.state}"),
            sample_interval_seconds=dataset.sample_interval_seconds,
            samples=temporal_samples_from_airflow_dataset(dataset),
        )


def test_target_commits_only_after_identity_visibility_and_advancement_proof():
    runtime = _Runtime()
    runtime.clock[0] = 103.1

    result = asyncio.run(
        runtime.request_streamlines_workload_transition_in_kit("Critical")
    )

    assert result.success
    assert runtime.commit_seen_before_proof is False
    assert runtime._airflow_state.committed.workload_mode == "Critical"
    assert runtime._airflow_state.pending is None
    assert runtime._streamlines_cache_playback_contract.workload == "Critical"
    assert runtime.visible is True
    assert runtime.scheduler_tasks == 1
    assert runtime.cache_builds == runtime.recomputes == 0
    assert runtime.kit_cae_executions == runtime.vti_imports == 0
    assert runtime.flow_attach_calls == 0


def test_all_four_workloads_switch_through_independent_persisted_caches():
    runtime = _Runtime()

    for workload in ("Idle", "Surge", "Critical", "Nominal"):
        runtime.semantic_workload = workload
        result = asyncio.run(
            runtime.request_streamlines_workload_transition_in_kit(workload)
        )
        assert result.success
        assert runtime._airflow_state.committed.workload_mode == workload
        assert runtime._streamlines_cache_playback_contract.workload == workload
        assert runtime.scheduler_tasks == 1
        assert runtime.reference_asset == (
            f"server/{_Cache.states[workload]}/streamlines_cache.usdc"
        )


def test_streamlines_xray_workload_switch_keeps_one_snapshot_and_material():
    runtime = _Runtime()
    runtime._visualization_committed = VisualizationMode.STREAMLINES_XRAY
    runtime._xray_override_owner = "streamlines_xray"

    for workload in ("Idle", "Surge", "Critical", "Nominal"):
        result = asyncio.run(
            runtime.request_streamlines_workload_transition_in_kit(workload)
        )

        root = f"/DTRS_StreamlinesSnapshots/{workload}"
        assert result.success is True
        assert runtime.visualization_snapshot().committed is (
            VisualizationMode.STREAMLINES_XRAY
        )
        assert runtime.xray_target_snapshot().override_owner == "streamlines_xray"
        assert runtime._airflow_state.committed.workload_mode == workload
        assert runtime._streamlines_cache_playback_contract.workload == workload
        assert runtime.snapshot_roots == (root,)
        assert runtime.material_bindings == {root: "/DTRS_Looks/StreamlinesVelocity"}
        assert runtime.scheduler_tasks == 1
        assert runtime.cache_builds == runtime.kit_cae_executions == 0
        assert runtime.vti_imports == 0


@pytest.mark.parametrize("classification", ("MISSING", "STALE", "INCOMPATIBLE"))
def test_bad_target_cache_leaves_previous_presentation_untouched(classification):
    runtime = _Runtime()
    runtime.classifications["Critical"] = classification
    previous_contract = runtime._streamlines_cache_playback_contract

    result = asyncio.run(
        runtime.request_streamlines_workload_transition_in_kit("Critical")
    )

    assert result.success is False
    assert runtime._airflow_state.committed.workload_mode == "Nominal"
    assert runtime._airflow_state.pending is None
    assert runtime._streamlines_cache_playback_contract is previous_contract
    assert runtime.prepare_count == 0
    assert runtime.scheduler_tasks == 1
    assert runtime.cache_builds == runtime.recomputes == runtime.vti_imports == 0


def test_failed_target_liveness_restores_previous_cache_and_one_scheduler():
    runtime = _Runtime()
    runtime.target_advances = False

    result = asyncio.run(
        runtime.request_streamlines_workload_transition_in_kit("Critical")
    )

    assert result.success is False
    assert result.rolled_back is True
    assert runtime._airflow_state.committed.workload_mode == "Nominal"
    assert runtime._airflow_state.pending is None
    assert runtime._streamlines_cache_playback_contract.workload == "Nominal"
    assert runtime.visible is True
    assert runtime.scheduler_tasks == 1
    assert runtime.prepare_count == 2
    assert runtime.reference_asset == ("server/load_normal/streamlines_cache.usdc")


def test_rapid_workload_supersession_rejects_stale_candidate_without_orphan():
    runtime = _Runtime()
    runtime.blocked_proof_workload = "Idle"
    runtime.proof_started = asyncio.Event()
    runtime.proof_release = asyncio.Event()

    async def switch():
        idle = asyncio.create_task(
            runtime.request_streamlines_workload_transition_in_kit("Idle")
        )
        await runtime.proof_started.wait()
        critical = asyncio.create_task(
            runtime.request_streamlines_workload_transition_in_kit("Critical")
        )
        runtime.proof_release.set()
        return await idle, await critical

    idle, critical = asyncio.run(switch())

    assert idle.success is False
    assert critical.success is True
    assert runtime._airflow_state.committed.workload_mode == "Critical"
    assert runtime._streamlines_cache_playback_contract.workload == "Critical"
    assert runtime.scheduler_tasks == 1
    assert runtime.prepare_count == 3
    assert runtime.reference_asset == ("server/load_critical/streamlines_cache.usdc")
    assert runtime.reference_history[-1] == runtime.reference_asset


def test_visualization_mode_race_prevents_stale_workload_mutation_or_commit():
    runtime = _Runtime()
    runtime.blocked_proof_workload = "Critical"
    runtime.proof_started = asyncio.Event()
    runtime.proof_release = asyncio.Event()

    async def race():
        request = asyncio.create_task(
            runtime.request_streamlines_workload_transition_in_kit("Critical")
        )
        await runtime.proof_started.wait()
        runtime._visualization_pending = SimpleNamespace(target=VisualizationMode.SMOKE)
        runtime.proof_release.set()
        return await request

    result = asyncio.run(race())

    assert result.success is False
    assert runtime._airflow_state.committed.workload_mode == "Nominal"
    assert runtime._airflow_state.pending is None
    assert runtime.prepare_count == 2
    assert runtime._streamlines_cache_playback_contract.workload == "Nominal"
    assert runtime.scheduler_tasks == 1


def test_unequal_datasets_resolve_target_from_shared_phase_not_source_index():
    runtime = _Runtime(unequal=True)
    runtime.clock[0] = 109.1

    result = asyncio.run(
        runtime.request_streamlines_workload_transition_in_kit("Critical")
    )

    assert result.success
    assert runtime.prepared_sample_index == 22
    assert runtime.prepared_sample_index != 45


def test_same_healthy_workload_is_a_true_no_op():
    runtime = _Runtime()

    result = asyncio.run(
        runtime.request_streamlines_workload_transition_in_kit("Nominal")
    )

    assert result.success
    assert runtime.prepare_count == 0
    assert runtime.scheduler_start_count == 0
    assert runtime._airflow_state.generation == 1


@pytest.mark.parametrize(
    ("mode", "expected_owner"),
    (
        (VisualizationMode.STREAMLINES, "streamlines"),
        (VisualizationMode.STREAMLINES_XRAY, "streamlines"),
        (VisualizationMode.SMOKE, "flow"),
        (VisualizationMode.NORMAL, "flow"),
    ),
)
def test_product_workload_request_routes_only_to_the_active_consumer(
    mode,
    expected_owner,
):
    calls = []

    class _Controller:
        def visualization_snapshot(self):
            return SimpleNamespace(committed=mode)

        async def request_streamlines_workload_transition_in_kit(
            self,
            workload_mode,
            status_callback=None,
        ):
            calls.append(("streamlines", workload_mode, status_callback))
            return SimpleNamespace(success=True, message="streamlines")

        async def request_attached_workload_transition_in_kit(
            self,
            workload_mode,
            status_callback=None,
        ):
            calls.append(("flow", workload_mode, status_callback))
            return SimpleNamespace(success=True, message="flow")

    controller = _Controller()
    result = asyncio.run(
        RuntimeController.request_workload_transition_in_kit(
            controller,
            "Critical",
        )
    )

    assert result.success
    assert calls == [(expected_owner, "Critical", None)]


class _Cache:
    states = {
        "Idle": "load_idle",
        "Nominal": "load_normal",
        "Surge": "load_surge",
        "Critical": "load_critical",
    }

    def airflow_dataset_selector_for_workload(self, workload: str):
        return AirflowDatasetSelector(
            "datasets",
            "server",
            self.states[workload],
        )


def _datasets(*, unequal: bool) -> dict[str, AirflowDataset]:
    datasets = {}
    for workload, state in _Cache.states.items():
        count = 40 if unequal and workload == "Critical" else 80
        interval = 0.4 if unequal and workload == "Critical" else 0.2
        paths = tuple(Path(f"{state}_{index:04d}.vti") for index in range(count))
        manifest = AirflowDatasetManifest(
            scope="server",
            state=state,
            source_fps=10.0,
            sample_step_frames=int(interval * 10.0),
            sample_rate_hz=1.0 / interval,
            sample_count=count,
            grid=(2, 2, 2),
        )
        datasets[workload] = AirflowDataset(
            root=Path("datasets"),
            directory=Path(state),
            manifest_path=Path(state) / "manifest.toml",
            manifest=manifest,
            velocity_vti_sequence_paths=paths,
            source_frames=tuple(range(count)),
        )
    return datasets
