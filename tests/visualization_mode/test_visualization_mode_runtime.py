"""Focused visualization-mode transaction and independent-target contracts."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from digital_twin_runtime_suite.app.commands import RuntimeController
from digital_twin_runtime_suite.app.flow.progress import (
    TemporalProofProgress,
    TemporalProofState,
)
from digital_twin_runtime_suite.app.smoke.runtime import (
    SmokeRuntimeMixin,
    SmokeTemporalAdvanceProof,
)
from digital_twin_runtime_suite.app.streamlines.cache_discovery import (
    StreamlinesCacheInspection,
)
from digital_twin_runtime_suite.app.visualization_mode.model import VisualizationMode
from digital_twin_runtime_suite.app.visualization_mode.runtime import (
    VisualizationModeResult,
    VisualizationModeRuntimeMixin,
)


def test_streamlines_xray_mode_follows_streamlines_in_selector_order():
    assert tuple(mode.value for mode in VisualizationMode) == (
        "Normal",
        "Smoke",
        "Streamlines",
        "Streamlines + X-Ray",
        "Heatmap",
    )


class _Runtime(VisualizationModeRuntimeMixin):
    def __init__(self) -> None:
        self._flow_lifecycle_state = "DETACHED"
        self._airflow_state = _AirflowState()
        self._workload = "Nominal"
        self._dataset = SimpleNamespace(manifest=SimpleNamespace(state="load_normal"))
        self._flow_validation_cache = _ValidationCache(ready=True)
        self.config = SimpleNamespace(
            simulation_cache=SimpleNamespace(velocity_field_name="vel"),
            chassis_presentation=SimpleNamespace(
                materials=SimpleNamespace(xray=object()),
                xray_target_groups=(
                    SimpleNamespace(group_id="chassis"),
                    SimpleNamespace(group_id="fans"),
                ),
            ),
        )
        self._cache_classification = "VALID"
        self._cache_mutations = 0
        self._vti_imports = 0
        self._kit_cae_executions = 0
        self._runtime_preview_rebuilds = 0
        self._streamlines_scheduler_count = 0
        self._streamlines_prepare_count = 0
        self._streamlines_start_count = 0
        self._streamlines_contract_start_count = 0
        self._streamlines_playback_authorization = None
        self._streamlines_snapshot_prepare_count = 0
        self._streamlines_snapshot_selected_count = 0
        self._mesh_selector_calls = 0
        self._timeline_set_current_time_calls = 0
        self._streamlines_visible = False
        self._streamlines_advances = True
        self._streamlines_later_tick = True
        self._streamlines_scheduler_tick_count = 0
        self._streamlines_advancement_proved = False
        self._streamlines_root_count = 0
        self._maximum_streamlines_root_count = 0
        self._streamlines_material_release_count = 0
        self._streamlines_material_binding_count = 0
        self._streamlines_callback_count = 0
        self._maximum_streamlines_callback_count = 0
        self._xray_session_binding_spec_count = 0
        self._maximum_xray_session_binding_spec_count = 0
        self._smoke_visible = False
        self._detach_leaves_smoke_visible = False
        self._flow_detach_count = 0
        self._smoke_resumes = True
        self._smoke_resume_advancement_count = 3
        self._smoke_resume_advanced = False
        self._smoke_resume_proof = None
        self._timeline_playing = True
        self._streamlines_controls_timeline = False
        self._lifecycle_events = []
        self._pause_timeline_during_smoke_visibility_settle = False
        self._hide_smoke_but_remains_visible = False
        self._flow_incompatible = False
        self._live_flow_dataset_state = None
        self._prepare_failure = False
        self._attach_failure = False
        self._streamlines_release_failure = False
        self._prepare_started = None
        self._prepare_release = None
        self._temporal_progress = TemporalProofProgress()
        self._temporal_proof_cancellations = 0
        self._manual_targets = frozenset({"chassis"})
        self._override_owner = None
        self._override_targets = frozenset()
        self._heatmap_visible = False
        self._heatmap_activation_failure = False
        self._heatmap_preparation_failure = False
        self._heatmap_prepare_count = 0
        self._heatmap_prepared_activation_count = 0
        self.reset_visualization_mode_state()

    def resolve_current_airflow_dataset(self):
        state = self._dataset.manifest.state
        return (
            SimpleNamespace(
                workload_mode=self._workload,
                dataset_identity=f"server/{state}",
            ),
            self._dataset,
        )

    def streamlines_cache_readiness_snapshot(self):
        return StreamlinesCacheInspection(
            ownership=SimpleNamespace(),
            paths=SimpleNamespace(),
            classification=self._cache_classification,
            message=f"Cache is {self._cache_classification}.",
        )

    async def attach_simulation_cache_in_kit(self):
        if self._attach_failure:
            return VisualizationModeResult(
                False,
                "Flow reconstruction failed.",
                VisualizationMode.STREAMLINES,
            )
        self._flow_lifecycle_state = "ATTACHED"
        self._smoke_visible = True
        self._live_flow_dataset_state = self._dataset.manifest.state
        return VisualizationModeResult(True, "Flow attached.", VisualizationMode.NORMAL)

    async def detach_simulation_cache_in_kit(self):
        self._flow_detach_count += 1
        self._flow_lifecycle_state = "DETACHED"
        self._live_flow_dataset_state = None
        if not self._detach_leaves_smoke_visible:
            self._smoke_visible = False
        return VisualizationModeResult(True, "Flow detached.", VisualizationMode.NORMAL)

    async def request_attached_workload_transition_in_kit(
        self,
        _workload_mode,
        status_callback=None,
    ):
        del status_callback
        self._live_flow_dataset_state = self._dataset.manifest.state
        self._flow_incompatible = False
        return VisualizationModeResult(
            True,
            "Flow workload reconciled.",
            VisualizationMode.STREAMLINES,
        )

    def apply_heatmap_xray_override_in_kit(self):
        self._override_owner = "heatmap_preview"
        self._override_targets = frozenset({"chassis", "fans"})
        return VisualizationModeResult(
            True,
            "X-Ray override applied.",
            VisualizationMode.NORMAL,
        )

    def heatmap_production_active(self):
        return self._heatmap_visible

    def prepare_heatmap_production_plan_in_kit(self):
        self._heatmap_prepare_count += 1
        if self._heatmap_preparation_failure:
            return VisualizationModeResult(
                False,
                "Heatmap candidate is invalid.",
                VisualizationMode.NORMAL,
            )
        return SimpleNamespace(
            success=True,
            message="Heatmap candidate is ready.",
            prepared=object(),
        )

    def activate_prepared_heatmap_production_in_kit(self, _prepared):
        self._heatmap_prepared_activation_count += 1
        if self._heatmap_activation_failure:
            return VisualizationModeResult(
                False,
                "Heatmap presentation failed.",
                VisualizationMode.NORMAL,
            )
        applied = self.apply_heatmap_xray_override_in_kit()
        if applied.success:
            self._heatmap_visible = True
        return applied

    def activate_heatmap_production_in_kit(self):
        prepared = self.prepare_heatmap_production_plan_in_kit()
        if not prepared.success:
            return prepared
        return self.activate_prepared_heatmap_production_in_kit(prepared.prepared)

    def deactivate_heatmap_production_in_kit(self):
        released = self.release_heatmap_xray_override_in_kit()
        if released.success:
            self._heatmap_visible = False
        return released

    def release_heatmap_xray_override_in_kit(self):
        self._override_owner = None
        self._override_targets = frozenset()
        return VisualizationModeResult(
            True,
            "X-Ray override released.",
            VisualizationMode.NORMAL,
        )

    def restore_heatmap_xray_override_in_kit(self):
        self._override_owner = "heatmap_preview"
        self._override_targets = frozenset({"chassis", "fans"})
        return VisualizationModeResult(
            True,
            "X-Ray override restored.",
            VisualizationMode.NORMAL,
        )

    def apply_streamlines_xray_override_in_kit(self):
        self._override_owner = "streamlines_xray"
        self._override_targets = frozenset({"chassis", "fans"})
        self._xray_session_binding_spec_count = len(self._override_targets)
        self._maximum_xray_session_binding_spec_count = max(
            self._maximum_xray_session_binding_spec_count,
            self._xray_session_binding_spec_count,
        )
        return VisualizationModeResult(
            True,
            "Streamlines + X-Ray override applied.",
            VisualizationMode.STREAMLINES,
        )

    def release_streamlines_xray_override_in_kit(self):
        if self._override_owner != "streamlines_xray":
            return VisualizationModeResult(
                False,
                "A different X-Ray target override is active.",
                VisualizationMode.STREAMLINES,
            )
        self._override_owner = None
        self._override_targets = frozenset()
        self._xray_session_binding_spec_count = 0
        return VisualizationModeResult(
            True,
            "Streamlines + X-Ray override released.",
            VisualizationMode.STREAMLINES,
        )

    def restore_streamlines_xray_override_in_kit(self):
        self._override_owner = "streamlines_xray"
        self._override_targets = frozenset({"chassis", "fans"})
        self._xray_session_binding_spec_count = len(self._override_targets)
        self._maximum_xray_session_binding_spec_count = max(
            self._maximum_xray_session_binding_spec_count,
            self._xray_session_binding_spec_count,
        )
        return VisualizationModeResult(
            True,
            "Streamlines + X-Ray override restored.",
            VisualizationMode.STREAMLINES,
        )

    def xray_target_snapshot(self):
        return SimpleNamespace(
            manual_target_ids=self._manual_targets,
            override_owner=self._override_owner,
            effective_target_ids=(
                self._override_targets if self._override_owner else self._manual_targets
            ),
        )

    async def prepare_streamlines_cached_target_in_kit(
        self,
        binding,
        airflow_dataset,
        phase_seconds,
        *,
        expected_sample_index=None,
        expected_source_vti=None,
        **_kwargs,
    ):
        self._streamlines_prepare_count += 1
        if self._prepare_started is not None:
            self._prepare_started.set()
            await self._prepare_release.wait()
        if self._prepare_failure:
            raise RuntimeError("Prepared cache visibility proof failed.")
        if self._cache_classification != "VALID":
            raise RuntimeError(f"Cache is {self._cache_classification}.")
        self._streamlines_cache_playback_contract = SimpleNamespace(
            workload=binding.workload_mode,
            dataset_identity=binding.dataset_identity,
        )
        self._streamlines_root_count = 1
        self._streamlines_material_binding_count = 1
        self._streamlines_callback_count = 1
        self._maximum_streamlines_callback_count = max(
            self._maximum_streamlines_callback_count,
            self._streamlines_callback_count,
        )
        self._streamlines_snapshot_prepare_count += 1
        self._streamlines_snapshot_selected_count = 1
        self._maximum_streamlines_root_count = max(
            self._maximum_streamlines_root_count,
            self._streamlines_root_count,
        )
        self._prepared_context = SimpleNamespace(
            workload=binding.workload_mode,
            dataset_identity=binding.dataset_identity,
            logical_phase_seconds=phase_seconds,
            normalized_phase_seconds=7.25,
            source_sample_index=expected_sample_index,
            source_vti=expected_source_vti,
            airflow_dataset=airflow_dataset,
        )
        self._temporal_proof_state_at_prepare = self._temporal_progress.state
        return self._airflow_state.resolve_phase(self._dataset)

    async def cleanup_streamlines_cached_presentation_in_kit(self):
        await self.stop_streamlines_cached_playback_in_kit()
        self._streamlines_visible = False
        self._streamlines_root_count = 0
        self._streamlines_snapshot_selected_count = 0
        self._streamlines_material_binding_count = 0
        self._streamlines_callback_count = 0

    def release_streamlines_presentation_material_in_kit(self):
        self._streamlines_material_release_count += 1
        self._streamlines_material_binding_count = 0

    async def start_streamlines_cached_playback_in_kit(self, **_kwargs):
        self._lifecycle_events.append("streamlines_start")
        self._streamlines_start_count += 1
        self._streamlines_scheduler_count = 1
        self._streamlines_scheduler_tick_count = 1
        self._streamlines_controls_timeline = False

    async def start_streamlines_cached_contract_playback_in_kit(
        self,
        contract,
        *,
        authorization,
        **kwargs,
    ):
        assert contract is self._streamlines_cache_playback_contract
        assert authorization()
        self._streamlines_contract_start_count += 1
        self._streamlines_playback_authorization = authorization
        await self.start_streamlines_cached_playback_in_kit(**kwargs)

    async def await_streamlines_cached_playback_advancement_in_kit(
        self,
        initial_sample,
    ):
        if self._streamlines_later_tick:
            self._streamlines_scheduler_tick_count = 2
        advanced = (
            self._streamlines_advances and self._streamlines_scheduler_tick_count >= 2
        )
        self._streamlines_advancement_proved = advanced
        return SimpleNamespace(
            initial_sample_identity=(
                f"index={initial_sample.sample_index}; "
                f"source={initial_sample.source_vti.name}"
            ),
            advanced_sample_identity=(
                "index=37; source=nominal_1038.vti" if advanced else None
            ),
            scheduler_tasks=self._streamlines_scheduler_count,
            scheduler_tick_count=self._streamlines_scheduler_tick_count,
            sample_advanced=advanced,
        )

    def streamlines_cached_playback_advanced_in_kit(self):
        return self._streamlines_advancement_proved

    async def stop_streamlines_cached_playback_in_kit(self):
        self._lifecycle_events.append("streamlines_stop")
        self._streamlines_scheduler_count = 0

    def _active_streamlines_playback_task_count(self):
        return self._streamlines_scheduler_count

    def set_streamlines_cached_presentation_visible_in_kit(self, visible):
        self._streamlines_visible = visible
        return True

    def streamlines_cached_presentation_is_visible_in_kit(self):
        return self._streamlines_visible

    def set_smoke_presentation_visible_in_kit(self, visible):
        if not (not visible and self._hide_smoke_but_remains_visible):
            self._smoke_visible = visible
        return VisualizationModeResult(
            True,
            "Smoke visibility changed.",
            VisualizationMode.NORMAL,
        )

    def smoke_presentation_is_visible_in_kit(self):
        return self._smoke_visible

    async def await_smoke_presentation_visibility_in_kit(self, visible):
        if visible and self._pause_timeline_during_smoke_visibility_settle:
            self._timeline_playing = False
        return self._smoke_visible is visible

    def flow_source_is_prepared_in_kit(self):
        return self._flow_lifecycle_state == "ATTACHED"

    def streamlines_cached_presentation_is_prepared_in_kit(self):
        return self._streamlines_root_count > 0

    async def resume_smoke_presentation_in_kit(self, *, show_presentation=True):
        self._lifecycle_events.append("flow_resume_proof")
        if show_presentation:
            self._smoke_visible = True
        self._timeline_playing = True
        count = self._smoke_resume_advancement_count if self._smoke_resumes else 0
        sources = (
            "nominal_1037.vti",
            "nominal_1038.vti" if count >= 1 else None,
            "nominal_1039.vti" if count >= 2 else None,
            "nominal_1040.vti" if count >= 3 else None,
        )
        self._smoke_resume_proof = SmokeTemporalAdvanceProof(
            source_0=sources[0],
            source_1=sources[1],
            source_2=sources[2],
            stability_source=sources[3],
            timeline_playing=self._timeline_playing,
        )
        self._smoke_resume_advanced = self._smoke_resume_proof.sustained_flow_playback
        return VisualizationModeResult(
            self._smoke_resume_advanced,
            (
                "Flow Smoke resumed."
                if self._smoke_resume_advanced
                else "Retained Flow source did not sustain playback after Smoke resume."
            ),
            VisualizationMode.NORMAL,
        )

    def smoke_resume_advance_proof_in_kit(self):
        return self._smoke_resume_proof

    def smoke_resume_source_advanced_in_kit(self):
        return self._smoke_resume_advanced

    def flow_timeline_is_playing_in_kit(self):
        return self._timeline_playing

    def _live_flow_consumer_matches_dataset(self, dataset):
        matches = (
            not self._flow_incompatible
            and dataset.manifest.state == self._live_flow_dataset_state
        )
        return matches, self._live_flow_dataset_state or "unavailable"

    def temporal_proof_progress(self):
        return self._temporal_progress

    def _cancel_kit_cae_temporal_proof(self, *, reason):
        self._temporal_proof_cancellations += 1
        self._temporal_progress = TemporalProofProgress(
            state=TemporalProofState.CANCELLED,
            cancellation_reason=reason,
        )
        return True


class _NativeFlowLayerRuntime(SmokeRuntimeMixin):
    def __init__(self) -> None:
        self._flow_lifecycle_state = "ATTACHED"
        self._flow_airflow_simulate_path = "/Flow/flowSimulate"
        self._smoke_presentation_visible = True
        self.stage = _NativeFlowStage()


class _NativeFlowStage:
    def __init__(self) -> None:
        self._session_layer = object()
        self._edit_target = object()
        self.simulate_layer = _NativeFlowAttribute(0)
        self.render_layer = _NativeFlowAttribute(0)
        self.simulate = _NativeFlowPrim("FlowSimulate", self.simulate_layer)
        self.render = _NativeFlowPrim("FlowRender", self.render_layer)

    def GetPrimAtPath(self, path: str):
        if path == "/Flow/flowSimulate":
            return self.simulate
        if path == "/Flow/flowRender":
            return self.render
        return _NativeFlowPrim("", None, valid=False)

    def Traverse(self):
        return (self.simulate, self.render)

    def GetEditTarget(self):
        return self._edit_target

    def SetEditTarget(self, target) -> None:
        self._edit_target = target

    def GetSessionLayer(self):
        return self._session_layer


class _NativeFlowPrim:
    def __init__(self, type_name: str, layer, *, valid: bool = True) -> None:
        self._type_name = type_name
        self._layer = layer
        self._valid = valid

    def IsValid(self) -> bool:
        return self._valid

    def GetTypeName(self) -> str:
        return self._type_name

    def GetAttribute(self, name: str):
        return self._layer if name == "layer" else None


class _NativeFlowAttribute:
    def __init__(self, value: int) -> None:
        self.value = value

    def IsValid(self) -> bool:
        return True

    def Get(self) -> int:
        return self.value

    def Set(self, value: int) -> None:
        self.value = value


def _install_native_flow_modules(monkeypatch, stage) -> None:
    omni = ModuleType("omni")
    omni.__path__ = []
    omni_usd = ModuleType("omni.usd")
    omni_usd.get_context = lambda: SimpleNamespace(get_stage=lambda: stage)
    omni.usd = omni_usd
    monkeypatch.setitem(sys.modules, "omni", omni)
    monkeypatch.setitem(sys.modules, "omni.usd", omni_usd)


class _SustainedSmokeRuntime(SmokeRuntimeMixin):
    def __init__(self, sources: tuple[str, ...]) -> None:
        self.sources = sources
        self.source_index = 0
        self.timeline = _FakeTimeline()
        self._smoke_resume_source_advanced = False
        self._smoke_resume_advance_proof = None

    def _kit_cae_current_temporal_source_name(self):
        return self.sources[self.source_index]

    def resolve_current_airflow_dataset(self):
        return SimpleNamespace(), SimpleNamespace(
            velocity_vti_sequence_paths=tuple(Path(source) for source in self.sources)
        )

    def play_simulation_cache_in_kit(self):
        self.timeline.playing = True
        return SimpleNamespace(success=True, message="Flow timeline playing.")

    def advance_one_update(self) -> None:
        if self.source_index < len(self.sources) - 1:
            self.source_index += 1


class _FakeTimeline:
    def __init__(self) -> None:
        self.playing = False

    def is_playing(self) -> bool:
        return self.playing


class _AdvancingKitApp:
    def __init__(self, runtime: _SustainedSmokeRuntime) -> None:
        self.runtime = runtime

    async def next_update_async(self):
        self.runtime.advance_one_update()


def _install_smoke_resume_modules(monkeypatch, runtime) -> None:
    omni = ModuleType("omni")
    omni.__path__ = []
    omni_kit = ModuleType("omni.kit")
    omni_kit.__path__ = []
    omni_kit_app = ModuleType("omni.kit.app")
    omni_kit_app.get_app = lambda: _AdvancingKitApp(runtime)
    omni_timeline = ModuleType("omni.timeline")
    omni_timeline.get_timeline_interface = lambda: runtime.timeline
    omni.kit = omni_kit
    omni.timeline = omni_timeline
    omni_kit.app = omni_kit_app
    monkeypatch.setitem(sys.modules, "omni", omni)
    monkeypatch.setitem(sys.modules, "omni.kit", omni_kit)
    monkeypatch.setitem(sys.modules, "omni.kit.app", omni_kit_app)
    monkeypatch.setitem(sys.modules, "omni.timeline", omni_timeline)


class _AirflowState:
    def __init__(self) -> None:
        self._phase = 107.25
        self.committed = None
        self.pending = None

    def phase_seconds(self):
        return self._phase

    def resolve_phase(self, _dataset):
        return SimpleNamespace(
            phase_seconds=self._phase,
            normalized_phase_seconds=7.25,
            sample=SimpleNamespace(
                sample_index=36,
                source_time_seconds=7.2,
                source_vti=Path("nominal_1037.vti"),
            ),
        )

    def resolve_binding(self, workload):
        state = {
            "Idle": "load_idle",
            "Nominal": "load_normal",
            "Surge": "load_surge",
            "Critical": "load_critical",
        }[workload]
        return SimpleNamespace(
            workload_mode=workload,
            dataset_identity=f"server/{state}",
        )

    def resolve_target(self, binding):
        return SimpleNamespace(
            workload_mode=binding.workload_mode,
            binding=binding,
            dataset=SimpleNamespace(
                manifest=SimpleNamespace(
                    state=binding.dataset_identity.split("/", 1)[1]
                )
            ),
        )

    def commit_target(self, target):
        if self.pending is not None and self.pending.target != target:
            return False
        self.committed = target
        self.pending = None
        return True


class _ValidationCache:
    def __init__(
        self,
        *,
        ready: bool,
        ready_selectors: frozenset[str] = frozenset(),
    ) -> None:
        self.ready = ready
        self.ready_selectors = ready_selectors

    def lookup(self, signature):
        ready = self.ready or signature in self.ready_selectors
        return SimpleNamespace(preflight=(object() if ready else None))


def test_mode_changes_leave_shared_workload_and_nonzero_phase_unchanged(monkeypatch):
    runtime = _Runtime()
    monkeypatch.setattr(
        "digital_twin_runtime_suite.app.visualization_mode.runtime."
        "build_dataset_validation_signature",
        lambda *_args: object(),
    )
    before = (
        runtime._workload,
        runtime._dataset,
        runtime._airflow_state.phase_seconds(),
    )

    result = asyncio.run(runtime.request_visualization_mode_in_kit("Smoke"))

    assert result.success is True
    assert runtime.visualization_snapshot().committed is VisualizationMode.SMOKE
    assert (
        runtime._workload,
        runtime._dataset,
        runtime._airflow_state.phase_seconds(),
    ) == before


def test_readiness_uses_only_current_workload_receipt_and_read_only_cache(monkeypatch):
    runtime = _Runtime()
    runtime._flow_validation_cache = _ValidationCache(ready=False)
    runtime._cache_classification = "STALE"
    monkeypatch.setattr(
        "digital_twin_runtime_suite.app.visualization_mode.runtime."
        "build_dataset_validation_signature",
        lambda *_args: object(),
    )

    readiness = runtime.visualization_readiness()

    assert readiness.for_mode(VisualizationMode.SMOKE).state == "VALIDATING"
    assert readiness.for_mode(VisualizationMode.STREAMLINES).state == "STALE"
    assert readiness.for_mode(VisualizationMode.STREAMLINES_XRAY).state == "STALE"
    assert runtime._cache_mutations == 0


def test_repeated_readiness_never_calls_strong_streamlines_inspection(monkeypatch):
    runtime = _Runtime()
    monkeypatch.setattr(
        runtime,
        "inspect_current_streamlines_cache",
        lambda: (_ for _ in ()).throw(AssertionError("strong inspection called")),
        raising=False,
    )
    monkeypatch.setattr(
        "digital_twin_runtime_suite.app.visualization_mode.runtime."
        "build_dataset_validation_signature",
        lambda *_args: object(),
    )
    monkeypatch.setattr(
        Path,
        "open",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("readiness opened a cache resource")
        ),
    )

    for _ in range(5):
        readiness = runtime.visualization_readiness()
        assert readiness.for_mode(VisualizationMode.STREAMLINES).state == "VALID"


def test_checking_streamlines_receipt_remains_selectable_for_validation(
    monkeypatch,
):
    runtime = _Runtime()
    runtime._cache_classification = "CHECKING"
    monkeypatch.setattr(
        "digital_twin_runtime_suite.app.visualization_mode.runtime."
        "build_dataset_validation_signature",
        lambda *_args: object(),
    )

    readiness = runtime.visualization_readiness().for_mode(
        VisualizationMode.STREAMLINES
    )

    assert readiness.state == "CHECKING"
    assert readiness.activation_available is True


def test_other_workload_receipt_does_not_make_current_smoke_ready(monkeypatch):
    runtime = _Runtime()
    runtime._flow_validation_cache = _ValidationCache(
        ready=False,
        ready_selectors=frozenset({"load_idle"}),
    )
    monkeypatch.setattr(
        "digital_twin_runtime_suite.app.visualization_mode.runtime."
        "build_dataset_validation_signature",
        lambda dataset, _field: dataset.manifest.state,
    )

    readiness = runtime.visualization_readiness()

    assert readiness.for_mode(VisualizationMode.SMOKE).state == "VALIDATING"


@pytest.mark.parametrize(
    "classification",
    ("MISSING", "STALE", "INCOMPATIBLE", "INCOMPLETE", "UNREADABLE"),
)
def test_cache_failure_readiness_never_mutates_streamlines_runtime(
    monkeypatch,
    classification,
):
    runtime = _Runtime()
    runtime._cache_classification = classification
    monkeypatch.setattr(
        "digital_twin_runtime_suite.app.visualization_mode.runtime."
        "build_dataset_validation_signature",
        lambda *_args: object(),
    )

    readiness = runtime.visualization_readiness()

    assert readiness.for_mode(VisualizationMode.STREAMLINES).state == classification
    assert runtime._cache_mutations == 0


def test_normal_to_smoke_preserves_independent_manual_xray_selection():
    runtime = _Runtime()

    result = asyncio.run(runtime.request_visualization_mode_in_kit("Smoke"))

    assert result.success is True
    assert runtime.xray_target_snapshot().manual_target_ids == frozenset({"chassis"})
    assert runtime.xray_target_snapshot().override_owner is None


def test_heatmap_preserves_manual_xray_selection_and_uses_all_configured_targets():
    runtime = _Runtime()

    result = asyncio.run(runtime.request_visualization_mode_in_kit("Heatmap"))

    assert result.success is True
    assert runtime.visualization_snapshot().committed is VisualizationMode.HEATMAP
    assert runtime.xray_target_snapshot().manual_target_ids == frozenset({"chassis"})
    assert runtime.xray_target_snapshot().effective_target_ids == frozenset(
        {"chassis", "fans"}
    )
    assert runtime.xray_target_snapshot().override_owner == "heatmap_preview"


def test_heatmap_is_the_only_primary_presentation_until_normal_restores_it():
    runtime = _Runtime()

    applied = asyncio.run(runtime.request_visualization_mode_in_kit("Heatmap"))

    assert applied.success
    snapshot = runtime.primary_visualization_presentation_snapshot_in_kit()
    assert snapshot.heatmap_presentation_active
    assert not snapshot.smoke_presentation_visible
    assert not snapshot.streamlines_presentation_visible

    restored = asyncio.run(runtime.request_visualization_mode_in_kit("Normal"))

    assert restored.success
    snapshot = runtime.primary_visualization_presentation_snapshot_in_kit()
    assert not snapshot.primary_presentation_active


def test_failed_heatmap_activation_restores_streamlines_xray_composition():
    runtime = _Runtime()

    assert asyncio.run(
        runtime.request_visualization_mode_in_kit("Streamlines + X-Ray")
    ).success
    runtime._heatmap_activation_failure = True

    result = asyncio.run(runtime.request_visualization_mode_in_kit("Heatmap"))

    assert not result.success
    assert (
        runtime.visualization_snapshot().committed is VisualizationMode.STREAMLINES_XRAY
    )
    assert runtime.streamlines_cached_presentation_is_visible_in_kit()
    assert runtime._active_streamlines_playback_task_count() == 1
    assert runtime.xray_target_snapshot().override_owner == "streamlines_xray"


def test_invalid_heatmap_candidate_leaves_smoke_presentation_untouched():
    runtime = _Runtime()

    assert asyncio.run(runtime.request_visualization_mode_in_kit("Smoke")).success
    runtime._heatmap_preparation_failure = True

    result = asyncio.run(runtime.request_visualization_mode_in_kit("Heatmap"))

    assert not result.success
    assert runtime.visualization_snapshot().committed is VisualizationMode.SMOKE
    assert runtime._flow_lifecycle_state == "ATTACHED"
    assert runtime._smoke_visible
    assert runtime._heatmap_prepared_activation_count == 0


def test_invalid_heatmap_candidate_leaves_streamlines_presentation_untouched():
    runtime = _Runtime()

    assert asyncio.run(runtime.request_visualization_mode_in_kit("Streamlines")).success
    runtime._heatmap_preparation_failure = True
    scheduler_before = runtime._streamlines_scheduler_count

    result = asyncio.run(runtime.request_visualization_mode_in_kit("Heatmap"))

    assert not result.success
    assert runtime.visualization_snapshot().committed is VisualizationMode.STREAMLINES
    assert runtime._streamlines_visible
    assert runtime._streamlines_scheduler_count == scheduler_before == 1
    assert runtime._flow_lifecycle_state == "DETACHED"
    assert runtime._heatmap_prepared_activation_count == 0


def test_valid_heatmap_candidate_is_prepared_once_before_activation():
    runtime = _Runtime()

    result = asyncio.run(runtime.request_visualization_mode_in_kit("Heatmap"))

    assert result.success
    assert runtime._heatmap_prepare_count == 1
    assert runtime._heatmap_prepared_activation_count == 1


@pytest.mark.parametrize(
    ("source", "target"),
    (
        ("Normal", "Smoke"),
        ("Smoke", "Normal"),
        ("Normal", "Streamlines"),
        ("Streamlines", "Normal"),
        ("Normal", "Streamlines + X-Ray"),
        ("Streamlines + X-Ray", "Normal"),
        ("Normal", "Heatmap"),
        ("Heatmap", "Normal"),
        ("Smoke", "Streamlines"),
        ("Streamlines", "Smoke"),
        ("Smoke", "Streamlines + X-Ray"),
        ("Streamlines + X-Ray", "Smoke"),
        ("Smoke", "Heatmap"),
        ("Heatmap", "Smoke"),
        ("Streamlines", "Heatmap"),
        ("Heatmap", "Streamlines"),
        ("Streamlines", "Streamlines + X-Ray"),
        ("Streamlines + X-Ray", "Streamlines"),
        ("Streamlines + X-Ray", "Heatmap"),
        ("Heatmap", "Streamlines + X-Ray"),
    ),
)
def test_supported_mode_graph_activates_target_independently(source, target):
    runtime = _Runtime()

    async def _transition():
        if source != "Normal":
            source_result = await runtime.request_visualization_mode_in_kit(source)
            assert source_result.success
        return await runtime.request_visualization_mode_in_kit(target)

    result = asyncio.run(_transition())

    assert result.success
    assert runtime.visualization_snapshot().committed is VisualizationMode(target)
    assert runtime.visualization_snapshot().pending is None
    visible = {
        "Normal": (False, False, None, 0),
        "Smoke": (True, False, None, 0),
        "Streamlines": (False, True, None, 1),
        "Streamlines + X-Ray": (False, True, "streamlines_xray", 1),
        "Heatmap": (False, False, "heatmap_preview", 0),
    }
    expected = visible[target]
    assert runtime._smoke_visible is expected[0]
    assert runtime._streamlines_visible is expected[1]
    assert runtime._override_owner == expected[2]
    assert runtime._streamlines_scheduler_count == expected[3]


def test_normal_releases_velocity_material_after_streamlines_cleanup():
    runtime = _Runtime()
    assert asyncio.run(runtime.request_visualization_mode_in_kit("Streamlines")).success

    result = asyncio.run(runtime.request_visualization_mode_in_kit("Normal"))

    assert result.success is True
    assert runtime._streamlines_scheduler_count == 0
    assert runtime._streamlines_root_count == 0
    assert runtime._streamlines_material_release_count == 1


def test_streamlines_xray_toggle_preserves_existing_cached_playback():
    runtime = _Runtime()
    assert asyncio.run(runtime.request_visualization_mode_in_kit("Streamlines")).success
    before = (
        runtime._streamlines_prepare_count,
        runtime._streamlines_start_count,
        runtime._streamlines_scheduler_count,
    )

    enabled = asyncio.run(
        runtime.request_visualization_mode_in_kit("Streamlines + X-Ray")
    )
    disabled = asyncio.run(runtime.request_visualization_mode_in_kit("Streamlines"))

    assert enabled.success and disabled.success
    assert runtime.visualization_snapshot().committed is VisualizationMode.STREAMLINES
    assert runtime._override_owner is None
    assert (
        runtime._streamlines_prepare_count,
        runtime._streamlines_start_count,
        runtime._streamlines_scheduler_count,
    ) == before


def test_direct_normal_to_streamlines_uses_only_persisted_cache_playback():
    runtime = _Runtime()

    result = asyncio.run(runtime.request_visualization_mode_in_kit("Streamlines"))

    assert result.success
    assert runtime.visualization_snapshot().committed is VisualizationMode.STREAMLINES
    assert runtime._flow_lifecycle_state == "DETACHED"
    assert runtime.visualization_flow_attach_call_count() == 0
    assert runtime._streamlines_prepare_count == 1
    assert runtime._streamlines_contract_start_count == 1
    assert runtime._streamlines_scheduler_count == 1
    assert runtime._streamlines_snapshot_prepare_count == 1
    assert runtime._streamlines_snapshot_selected_count == 1
    assert runtime._streamlines_advancement_proved is True
    assert runtime._streamlines_playback_authorization is not None
    assert runtime._streamlines_playback_authorization() is True
    assert runtime._cache_mutations == 0
    assert runtime._kit_cae_executions == 0
    assert runtime._runtime_preview_rebuilds == 0
    assert runtime._vti_imports == 0
    assert runtime._mesh_selector_calls == 0
    assert runtime._timeline_set_current_time_calls == 0
    assert runtime._streamlines_controls_timeline is False


def test_smoke_streamlines_round_trip_returns_to_normal_cleanly():
    runtime = _Runtime()

    async def _run_sequence():
        return [
            await runtime.request_visualization_mode_in_kit(mode)
            for mode in (
                "Smoke",
                "Streamlines",
                "Smoke",
                "Streamlines",
                "Smoke",
                "Normal",
            )
        ]

    results = asyncio.run(_run_sequence())

    assert all(result.success for result in results)
    assert runtime.visualization_snapshot().committed is VisualizationMode.NORMAL
    assert runtime.visualization_snapshot().pending is None
    assert runtime._flow_lifecycle_state == "DETACHED"
    assert runtime.xray_target_snapshot().override_owner is None
    assert runtime.xray_target_snapshot().effective_target_ids == frozenset({"chassis"})
    assert runtime._streamlines_scheduler_count == 0
    assert runtime._streamlines_visible is False
    assert runtime._smoke_visible is False
    presentation = runtime.primary_visualization_presentation_snapshot_in_kit()
    assert not presentation.primary_presentation_active
    assert runtime._kit_cae_executions == 0
    assert runtime._runtime_preview_rebuilds == 0
    assert runtime._vti_imports == 0
    assert runtime._streamlines_root_count == 0
    assert runtime._maximum_streamlines_root_count == 1
    assert runtime._prepared_context.logical_phase_seconds == pytest.approx(107.25)
    assert runtime._prepared_context.normalized_phase_seconds == pytest.approx(7.25)
    assert runtime._prepared_context.source_sample_index == 36
    assert runtime._streamlines_advancement_proved is True
    assert runtime._smoke_resume_advanced is True
    assert "reused=False; reconstructed=True" in results[2].message
    assert "reused=False; reconstructed=True" in results[4].message


def test_normal_streamlines_normal_reentry_retains_one_snapshot_owner():
    runtime = _Runtime()

    async def _run_sequence():
        return [
            await runtime.request_visualization_mode_in_kit(mode)
            for mode in ("Streamlines", "Normal", "Streamlines")
        ]

    results = asyncio.run(_run_sequence())

    assert all(result.success for result in results)
    assert runtime.visualization_snapshot().committed is VisualizationMode.STREAMLINES
    assert runtime._streamlines_root_count == 1
    assert runtime._maximum_streamlines_root_count == 1
    assert runtime._streamlines_scheduler_count == 1
    assert runtime._streamlines_snapshot_selected_count == 1
    assert runtime._mesh_selector_calls == 0
    assert runtime._timeline_set_current_time_calls == 0


def test_hidden_prepared_streamlines_root_is_not_a_primary_presentation():
    runtime = _Runtime()
    runtime._flow_lifecycle_state = "DETACHED"
    runtime._smoke_visible = False
    runtime._streamlines_root_count = 1
    runtime._streamlines_visible = False

    snapshot = runtime.primary_visualization_presentation_snapshot_in_kit()

    assert snapshot.streamlines_root_prepared is True
    assert snapshot.primary_presentation_active is False
    assert snapshot.normal_failure_reason() is None


def test_normal_rejects_a_genuinely_visible_smoke_presentation():
    runtime = _Runtime()
    assert asyncio.run(runtime.request_visualization_mode_in_kit("Smoke")).success
    runtime._detach_leaves_smoke_visible = True

    result = asyncio.run(runtime.request_visualization_mode_in_kit("Normal"))

    assert result.success is False
    assert runtime.visualization_snapshot().committed is VisualizationMode.SMOKE
    assert "native Flow Smoke renderer remains visible" in result.message


def test_streamlines_prepare_failure_preserves_visible_smoke():
    runtime = _Runtime()
    assert asyncio.run(runtime.request_visualization_mode_in_kit("Smoke")).success
    runtime._prepare_failure = True

    result = asyncio.run(runtime.request_visualization_mode_in_kit("Streamlines"))

    assert result.success is False
    assert runtime.visualization_snapshot().committed is VisualizationMode.SMOKE
    assert runtime._smoke_visible is True
    assert runtime._flow_lifecycle_state == "ATTACHED"
    assert runtime._flow_detach_count == 0
    assert runtime._streamlines_scheduler_count == 0
    assert runtime._streamlines_visible is False


def test_failed_flow_detach_does_not_retry_streamlines_without_another_request():
    runtime = _Runtime()
    assert asyncio.run(runtime.request_visualization_mode_in_kit("Smoke")).success
    runtime._detach_leaves_smoke_visible = True

    result = asyncio.run(runtime.request_visualization_mode_in_kit("Streamlines"))
    prepares_after_failure = runtime._streamlines_prepare_count
    starts_after_failure = runtime._streamlines_start_count
    asyncio.run(_yield_update_cycles())

    assert result.success is False
    assert runtime.visualization_snapshot().committed is VisualizationMode.SMOKE
    assert runtime._streamlines_scheduler_count == 0
    assert runtime._streamlines_root_count == 0
    assert runtime._streamlines_prepare_count == prepares_after_failure
    assert runtime._streamlines_start_count == starts_after_failure


def test_new_streamlines_request_may_prepare_after_a_failed_flow_detach():
    runtime = _Runtime()
    assert asyncio.run(runtime.request_visualization_mode_in_kit("Smoke")).success
    runtime._detach_leaves_smoke_visible = True
    failed = asyncio.run(runtime.request_visualization_mode_in_kit("Streamlines"))
    prepare_count = runtime._streamlines_prepare_count
    runtime._detach_leaves_smoke_visible = False

    retried = asyncio.run(runtime.request_visualization_mode_in_kit("Streamlines"))

    assert failed.success is False
    assert retried.success is True
    assert runtime._streamlines_prepare_count == prepare_count + 1


def test_visible_smoke_after_detach_cannot_commit_streamlines():
    runtime = _Runtime()
    assert asyncio.run(runtime.request_visualization_mode_in_kit("Smoke")).success
    runtime._detach_leaves_smoke_visible = True

    result = asyncio.run(runtime.request_visualization_mode_in_kit("Streamlines"))

    assert result.success is False
    assert runtime.visualization_snapshot().committed is VisualizationMode.SMOKE
    assert runtime._streamlines_scheduler_count == 0
    assert runtime._streamlines_visible is False


def test_smoke_visibility_uses_the_native_flow_render_layer(monkeypatch):
    """Renderer-only layer routing leaves FlowSimulate prepared and untouched."""

    runtime = _NativeFlowLayerRuntime()
    _install_native_flow_modules(monkeypatch, runtime.stage)

    hidden = runtime.set_smoke_presentation_visible_in_kit(False)

    assert hidden.success is True
    assert runtime.flow_source_is_prepared_in_kit() is True
    assert runtime.stage.render_layer.value == 1
    assert runtime.stage.simulate_layer.value == 0
    assert runtime.smoke_presentation_is_visible_in_kit() is False

    shown = runtime.set_smoke_presentation_visible_in_kit(True)

    assert shown.success is True
    assert runtime.stage.render_layer.value == 0
    assert runtime.smoke_presentation_is_visible_in_kit() is True


def test_streamlines_target_does_not_require_visible_source_smoke():
    runtime = _Runtime()
    assert asyncio.run(runtime.request_visualization_mode_in_kit("Smoke")).success
    runtime._smoke_visible = False

    result = asyncio.run(runtime.request_visualization_mode_in_kit("Streamlines"))

    assert result.success is True
    assert runtime.visualization_snapshot().committed is VisualizationMode.STREAMLINES
    assert runtime._streamlines_scheduler_count == 1
    assert runtime._streamlines_visible is True


def test_nonadvancing_streamlines_scheduler_cannot_commit():
    runtime = _Runtime()
    assert asyncio.run(runtime.request_visualization_mode_in_kit("Smoke")).success
    runtime._streamlines_advances = False

    result = asyncio.run(runtime.request_visualization_mode_in_kit("Streamlines"))

    assert result.success is False
    assert runtime.visualization_snapshot().committed is VisualizationMode.SMOKE
    assert runtime._smoke_visible is True
    assert runtime._streamlines_scheduler_count == 0


def test_scheduler_creation_without_a_later_tick_cannot_commit_streamlines():
    runtime = _Runtime()
    assert asyncio.run(runtime.request_visualization_mode_in_kit("Smoke")).success
    runtime._streamlines_later_tick = False

    result = asyncio.run(runtime.request_visualization_mode_in_kit("Streamlines"))

    assert result.success is False
    assert runtime.visualization_snapshot().committed is VisualizationMode.SMOKE
    assert runtime._streamlines_scheduler_tick_count == 1
    assert runtime._streamlines_scheduler_count == 0


def test_retained_nonadvancing_flow_cannot_commit_smoke():
    runtime = _Runtime()
    assert asyncio.run(runtime.request_visualization_mode_in_kit("Smoke")).success
    assert asyncio.run(runtime.request_visualization_mode_in_kit("Streamlines")).success
    runtime._smoke_resumes = False

    result = asyncio.run(runtime.request_visualization_mode_in_kit("Smoke"))

    assert result.success is False
    assert runtime.visualization_snapshot().committed is VisualizationMode.STREAMLINES
    assert runtime._streamlines_scheduler_count == 1
    assert runtime._streamlines_visible is True
    assert runtime._smoke_visible is False


def test_one_flow_source_advancement_is_not_sustained_smoke_liveness():
    runtime = _Runtime()
    assert asyncio.run(runtime.request_visualization_mode_in_kit("Smoke")).success
    assert asyncio.run(runtime.request_visualization_mode_in_kit("Streamlines")).success
    runtime._smoke_resume_advancement_count = 1

    result = asyncio.run(runtime.request_visualization_mode_in_kit("Smoke"))

    assert result.success is False
    assert runtime.visualization_snapshot().committed is VisualizationMode.STREAMLINES
    assert runtime._streamlines_scheduler_count == 1
    assert runtime._streamlines_controls_timeline is False
    assert runtime._streamlines_visible is True
    assert runtime._smoke_visible is False


def test_streamlines_stops_its_scheduler_before_sustained_flow_proof():
    runtime = _Runtime()
    assert asyncio.run(runtime.request_visualization_mode_in_kit("Smoke")).success
    assert asyncio.run(runtime.request_visualization_mode_in_kit("Streamlines")).success
    runtime._lifecycle_events.clear()

    result = asyncio.run(runtime.request_visualization_mode_in_kit("Smoke"))

    assert result.success is True
    assert runtime._lifecycle_events.index("streamlines_stop") < (
        runtime._lifecycle_events.index("flow_resume_proof")
    )
    assert runtime._streamlines_scheduler_count == 0
    assert runtime._streamlines_controls_timeline is False
    assert runtime._timeline_playing is True


def test_smoke_reconstructs_from_current_consumer_after_streamlines_detach():
    runtime = _Runtime()
    assert asyncio.run(runtime.request_visualization_mode_in_kit("Smoke")).success
    assert asyncio.run(runtime.request_visualization_mode_in_kit("Streamlines")).success
    runtime._workload = "Critical"
    runtime._dataset = SimpleNamespace(manifest=SimpleNamespace(state="load_critical"))
    critical = runtime._airflow_state.resolve_target(
        runtime._airflow_state.resolve_binding("Critical")
    )
    runtime._airflow_state.commit_target(critical)

    result = asyncio.run(runtime.request_visualization_mode_in_kit("Smoke"))

    assert result.success is True
    assert "reused=False; reconstructed=True; reconciled=False" in result.message
    assert runtime._live_flow_dataset_state == "load_critical"
    assert runtime.visualization_snapshot().committed is VisualizationMode.SMOKE


def test_late_streamlines_cleanup_cannot_pause_resumed_smoke():
    runtime = _Runtime()
    assert asyncio.run(runtime.request_visualization_mode_in_kit("Smoke")).success
    assert asyncio.run(runtime.request_visualization_mode_in_kit("Streamlines")).success
    assert asyncio.run(runtime.request_visualization_mode_in_kit("Smoke")).success

    asyncio.run(runtime.cleanup_streamlines_cached_presentation_in_kit())

    assert runtime._timeline_playing is True
    assert runtime._streamlines_scheduler_count == 0
    assert runtime._streamlines_controls_timeline is False
    assert runtime.visualization_snapshot().committed is VisualizationMode.SMOKE


def test_late_timeline_pause_after_flow_proof_prevents_smoke_commit():
    runtime = _Runtime()
    assert asyncio.run(runtime.request_visualization_mode_in_kit("Smoke")).success
    assert asyncio.run(runtime.request_visualization_mode_in_kit("Streamlines")).success
    runtime._pause_timeline_during_smoke_visibility_settle = True

    result = asyncio.run(runtime.request_visualization_mode_in_kit("Smoke"))

    assert result.success is False
    assert runtime.visualization_snapshot().committed is VisualizationMode.STREAMLINES
    assert runtime._streamlines_scheduler_count == 1
    assert runtime._streamlines_visible is True
    assert runtime._smoke_visible is False


def test_real_smoke_resume_rejects_only_one_source_advancement(monkeypatch):
    runtime = _SustainedSmokeRuntime(("nominal_1351.vti", "nominal_1361.vti"))
    _install_smoke_resume_modules(monkeypatch, runtime)

    result = asyncio.run(
        runtime.resume_smoke_presentation_in_kit(show_presentation=False)
    )

    proof = runtime.smoke_resume_advance_proof_in_kit()
    assert result.success is False
    assert proof.source_0 == "nominal_1351.vti"
    assert proof.source_1 == "nominal_1361.vti"
    assert proof.source_2 is None
    assert proof.sustained_flow_playback is False


def test_real_smoke_resume_requires_continued_post_cleanup_progress(monkeypatch):
    runtime = _SustainedSmokeRuntime(
        (
            "nominal_1351.vti",
            "nominal_1361.vti",
            "nominal_1371.vti",
            "nominal_1381.vti",
        )
    )
    _install_smoke_resume_modules(monkeypatch, runtime)

    result = asyncio.run(
        runtime.resume_smoke_presentation_in_kit(show_presentation=False)
    )

    proof = runtime.smoke_resume_advance_proof_in_kit()
    assert result.success is True
    assert (proof.source_0, proof.source_1, proof.source_2) == (
        "nominal_1351.vti",
        "nominal_1361.vti",
        "nominal_1371.vti",
    )
    assert proof.stability_source == "nominal_1381.vti"
    assert proof.timeline_playing is True
    assert proof.sustained_flow_playback is True


def test_repeated_round_trip_keeps_exactly_one_primary_presentation_active():
    runtime = _Runtime()

    async def _round_trip():
        await runtime.request_visualization_mode_in_kit("Smoke")
        await runtime.request_visualization_mode_in_kit("Streamlines")
        streamlines_only = runtime._streamlines_visible and not runtime._smoke_visible
        await runtime.request_visualization_mode_in_kit("Smoke")
        smoke_only = runtime._smoke_visible and not runtime._streamlines_visible
        await runtime.request_visualization_mode_in_kit("Streamlines")
        await runtime.request_visualization_mode_in_kit("Smoke")
        return streamlines_only, smoke_only

    streamlines_only, smoke_only = asyncio.run(_round_trip())

    assert streamlines_only and smoke_only
    assert runtime._streamlines_scheduler_count == 0


def test_repeated_mixed_modes_leave_no_streamlines_xray_accumulation():
    runtime = _Runtime()

    async def cycle():
        for _ in range(3):
            for target in (
                "Smoke",
                "Streamlines",
                "Streamlines + X-Ray",
                "Streamlines",
                "Smoke",
                "Normal",
            ):
                result = await runtime.request_visualization_mode_in_kit(target)
                assert result.success is True
                if target == "Streamlines + X-Ray":
                    assert runtime._streamlines_scheduler_count == 1
                    assert runtime._streamlines_root_count == 1
                    assert runtime._streamlines_material_binding_count == 1
                    assert runtime._streamlines_callback_count == 1
                    assert runtime._override_owner == "streamlines_xray"
                    assert runtime._xray_session_binding_spec_count == 2
                elif target == "Streamlines":
                    assert runtime._streamlines_scheduler_count == 1
                    assert runtime._streamlines_root_count == 1
                    assert runtime._streamlines_material_binding_count == 1
                    assert runtime._streamlines_callback_count == 1
                    assert runtime._override_owner is None
                    assert runtime._xray_session_binding_spec_count == 0
            assert runtime._streamlines_scheduler_count == 0
            assert runtime._streamlines_root_count == 0
            assert runtime._streamlines_material_binding_count == 0
            assert runtime._streamlines_callback_count == 0
            assert runtime._override_owner is None
            assert runtime._override_targets == frozenset()
            assert runtime._xray_session_binding_spec_count == 0

    asyncio.run(cycle())

    assert runtime._maximum_streamlines_root_count == 1
    assert runtime._maximum_streamlines_callback_count == 1
    assert runtime._maximum_xray_session_binding_spec_count == 2


def test_smoke_to_streamlines_cancels_flow_proof_then_detaches_flow():
    runtime = _Runtime()
    assert asyncio.run(runtime.request_visualization_mode_in_kit("Smoke")).success
    runtime._temporal_progress = TemporalProofProgress(
        state=TemporalProofState.RUNNING,
        validated_sample_count=17,
        total_sample_count=80,
    )

    result = asyncio.run(runtime.request_visualization_mode_in_kit("Streamlines"))

    assert result.success is True
    assert runtime._flow_lifecycle_state == "DETACHED"
    assert runtime._flow_detach_count == 1
    assert runtime._temporal_proof_cancellations == 1
    assert runtime.temporal_proof_progress().state is TemporalProofState.CANCELLED
    assert (
        runtime.temporal_proof_progress().cancellation_reason
        == "VISUALIZATION_MODE_TRANSITION"
    )
    assert runtime._temporal_proof_state_at_prepare is TemporalProofState.CANCELLED
    assert runtime._kit_cae_executions == 0
    assert runtime._runtime_preview_rebuilds == 0
    assert runtime._vti_imports == 0

    smoke = asyncio.run(runtime.request_visualization_mode_in_kit("Smoke"))
    streamlines = asyncio.run(runtime.request_visualization_mode_in_kit("Streamlines"))

    assert smoke.success and streamlines.success
    assert "reused=False; reconstructed=True" in smoke.message
    assert runtime._flow_lifecycle_state == "DETACHED"
    assert runtime.temporal_proof_progress().state is TemporalProofState.CANCELLED


@pytest.mark.parametrize(
    "target",
    (
        VisualizationMode.NORMAL,
        VisualizationMode.STREAMLINES,
        VisualizationMode.STREAMLINES_XRAY,
        VisualizationMode.HEATMAP,
    ),
)
def test_switching_from_smoke_to_another_mode_detaches_flow(target):
    runtime = _Runtime()
    assert asyncio.run(runtime.request_visualization_mode_in_kit("Smoke")).success

    result = asyncio.run(runtime.request_visualization_mode_in_kit(target))

    assert result.success
    assert runtime.visualization_snapshot().committed is target
    assert runtime._flow_lifecycle_state == "DETACHED"
    assert runtime._flow_detach_count == 1


def test_visualization_proof_cancellation_rejects_late_failed_progress():
    controller = RuntimeController("configs/digital_twin_runtime_suite.toml")
    generation = controller._flow_temporal_proof_generation
    controller._flow_temporal_progress = TemporalProofProgress(
        state=TemporalProofState.RUNNING,
        validated_sample_count=17,
        total_sample_count=80,
    )

    assert controller._cancel_kit_cae_temporal_proof(
        reason="VISUALIZATION_MODE_TRANSITION"
    )
    assert not controller._update_temporal_proof_progress(
        generation_id=generation,
        state=TemporalProofState.FAILED,
        total_sample_count=80,
        validated_sample_count=80,
        current_asset_name="server_airflow_velocity_normal_1201.vti",
        started_at=0.0,
    )

    progress = controller.temporal_proof_progress()
    assert progress.state is TemporalProofState.CANCELLED
    assert progress.cancellation_reason == "VISUALIZATION_MODE_TRANSITION"


def test_smoke_reconstruction_failure_preserves_active_streamlines():
    runtime = _Runtime()
    assert asyncio.run(runtime.request_visualization_mode_in_kit("Smoke")).success
    assert asyncio.run(runtime.request_visualization_mode_in_kit("Streamlines")).success
    runtime._flow_lifecycle_state = "DETACHED"
    runtime._flow_incompatible = True
    runtime._attach_failure = True

    result = asyncio.run(runtime.request_visualization_mode_in_kit("Smoke"))

    assert result.success is False
    assert runtime.visualization_snapshot().committed is VisualizationMode.STREAMLINES
    assert runtime._streamlines_scheduler_count == 1
    assert runtime._streamlines_visible is True
    assert runtime._smoke_visible is False


@pytest.mark.parametrize(
    "classification",
    ("MISSING", "STALE", "INCOMPATIBLE", "INCOMPLETE", "UNREADABLE"),
)
def test_streamlines_cache_rejection_preserves_smoke_without_runtime_fallback(
    classification,
):
    runtime = _Runtime()
    assert asyncio.run(runtime.request_visualization_mode_in_kit("Smoke")).success
    runtime._cache_classification = classification

    result = asyncio.run(runtime.request_visualization_mode_in_kit("Streamlines"))

    assert result.success is False
    assert runtime.visualization_snapshot().committed is VisualizationMode.SMOKE
    assert runtime._smoke_visible is True
    assert runtime._streamlines_scheduler_count == 0
    assert runtime._cache_mutations == 0
    assert runtime._kit_cae_executions == 0
    assert runtime._runtime_preview_rebuilds == 0
    assert runtime._vti_imports == 0


def test_normal_supersedes_pending_streamlines_without_a_late_commit():
    runtime = _Runtime()

    async def _supersede():
        runtime._prepare_started = asyncio.Event()
        runtime._prepare_release = asyncio.Event()
        streamlines = asyncio.create_task(
            runtime.request_visualization_mode_in_kit("Streamlines")
        )
        await runtime._prepare_started.wait()
        normal = asyncio.create_task(
            runtime.request_visualization_mode_in_kit("Normal")
        )
        runtime._prepare_release.set()
        return await streamlines, await normal

    streamlines, normal = asyncio.run(_supersede())

    assert streamlines.success is False
    assert normal.success is True
    assert runtime.visualization_snapshot().committed is VisualizationMode.NORMAL
    assert runtime.visualization_snapshot().pending is None
    assert runtime._streamlines_scheduler_count == 0
    assert runtime._streamlines_root_count == 0
    assert runtime._streamlines_start_count == 0


async def _yield_update_cycles() -> None:
    """Give stale candidate tasks several event-loop turns to reveal retries."""

    for _ in range(5):
        await asyncio.sleep(0)


def test_nonvalid_streamlines_target_is_rejected_without_runtime_mutation():
    runtime = _Runtime()
    runtime._cache_classification = "MISSING"

    result = asyncio.run(runtime.request_visualization_mode_in_kit("Streamlines"))

    assert result.success is False
    assert runtime.visualization_snapshot().committed is VisualizationMode.NORMAL
    assert runtime._flow_lifecycle_state == "DETACHED"
    assert runtime._cache_mutations == 0
