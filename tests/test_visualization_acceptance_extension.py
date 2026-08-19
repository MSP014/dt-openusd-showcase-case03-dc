"""Focused Phase 4.3 selector and manual-acceptance regression contracts."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace

from digital_twin_runtime_suite.app.manual_acceptance import GuidedAcceptanceSession
from digital_twin_runtime_suite.app.streamlines.profile import StreamlinesProfileId
from digital_twin_runtime_suite.app.streamlines.tuning import (
    DEFAULT_GLOBAL_FLOW_PATH_TUNING,
    DEFAULT_VOLUME_COVERAGE_TUNING,
    StreamlinesPreviewWorkloadMismatchError,
)
from digital_twin_runtime_suite.app.visualization_mode import VisualizationMode


def test_visualization_selector_schedules_one_authoritative_request(monkeypatch):
    module = _load_extension(monkeypatch)
    extension = module.DigitalTwinRuntimeSuiteExtension()
    scheduled = []
    extension._updating_visualization_mode = False
    extension._controller = _SelectorController()
    extension._schedule_visualization_mode_request = scheduled.append

    extension._on_visualization_mode_changed(_IntModel(1))

    assert scheduled == [VisualizationMode.SMOKE]

    extension._updating_visualization_mode = True
    extension._on_visualization_mode_changed(_IntModel(0))

    assert scheduled == [VisualizationMode.SMOKE]


def test_visualization_scheduler_ignores_duplicate_pending_mode(monkeypatch):
    module = _load_extension(monkeypatch)
    extension = module.DigitalTwinRuntimeSuiteExtension()
    active_task = _ActiveTask()
    extension._controller = _SelectorController()
    extension._visualization_task = active_task
    extension._scheduled_visualization_mode = VisualizationMode.STREAMLINES

    extension._schedule_visualization_mode_request(VisualizationMode.STREAMLINES)

    assert extension._visualization_task is active_task


def test_phase44a_preview_button_supersedes_active_task(monkeypatch):
    module = _load_extension(monkeypatch)
    extension = module.DigitalTwinRuntimeSuiteExtension()
    active = _ActiveTask()
    extension._streamlines_preview_task = active
    extension._streamlines_preview_button = SimpleNamespace(enabled=True)
    extension._workload_modes = ("Idle", "Nominal", "Surge", "Critical")
    extension._workload_combo = _Combo(0)
    extension._selected_streamlines_profile_tuning = lambda: (
        StreamlinesProfileId.GLOBAL_FLOW_PATH,
        DEFAULT_GLOBAL_FLOW_PATH_TUNING,
    )
    scheduled = []
    monkeypatch.setattr(module.asyncio, "ensure_future", scheduled.append)

    extension._schedule_streamlines_phase44a_preview()

    assert active.cancelled
    assert len(scheduled) == 1
    assert extension._streamlines_preview_button.enabled is False
    scheduled[0].close()


def test_phase44a_preview_button_schedules_one_authoritative_preview(monkeypatch):
    module = _load_extension(monkeypatch)
    extension = module.DigitalTwinRuntimeSuiteExtension()
    extension._streamlines_preview_task = None
    extension._streamlines_preview_button = SimpleNamespace(enabled=True)
    extension._workload_modes = ("Idle", "Nominal", "Surge", "Critical")
    extension._workload_combo = _Combo(0)
    extension._streamlines_tuning_max_steps_combo = _Combo(0)
    extension._streamlines_tuning_step_scale_combo = _Combo(3)
    extension._selected_streamlines_profile_tuning = lambda: (
        StreamlinesProfileId.GLOBAL_FLOW_PATH,
        DEFAULT_GLOBAL_FLOW_PATH_TUNING,
    )
    scheduled = []

    def capture(coroutine):
        scheduled.append(coroutine)
        return _ActiveTask()

    monkeypatch.setattr(module.asyncio, "ensure_future", capture)

    extension._schedule_streamlines_phase44a_preview()

    assert len(scheduled) == 1
    assert extension._streamlines_preview_button.enabled is False
    scheduled[0].close()


def test_phase44a_preview_click_reads_current_visible_workload(monkeypatch):
    module = _load_extension(monkeypatch)
    extension = module.DigitalTwinRuntimeSuiteExtension()
    extension._streamlines_preview_task = None
    extension._streamlines_preview_button = SimpleNamespace(enabled=True)
    extension._workload_modes = ("Idle", "Nominal", "Surge", "Critical")
    extension._workload_combo = _Combo(0)
    extension._streamlines_tuning_max_steps_combo = _Combo(0)
    extension._streamlines_tuning_step_scale_combo = _Combo(3)
    extension._selected_streamlines_profile_tuning = lambda: (
        StreamlinesProfileId.GLOBAL_FLOW_PATH,
        DEFAULT_GLOBAL_FLOW_PATH_TUNING,
    )
    requested = []

    async def capture(workload, _profile_id, _tuning):
        requested.append(workload)

    extension._run_streamlines_phase44a_preview = capture
    monkeypatch.setattr(module.asyncio, "ensure_future", _run_immediately)

    extension._workload_combo.model.set_index(1)
    extension._schedule_streamlines_phase44a_preview()

    assert requested == ["Nominal"]


def test_phase44a_preview_click_does_not_retain_initial_workload(monkeypatch):
    module = _load_extension(monkeypatch)
    extension = module.DigitalTwinRuntimeSuiteExtension()
    extension._streamlines_preview_task = None
    extension._streamlines_preview_button = SimpleNamespace(enabled=True)
    extension._workload_modes = ("Idle", "Nominal", "Surge", "Critical")
    extension._streamlines_tuning_max_steps_combo = _Combo(0)
    extension._streamlines_tuning_step_scale_combo = _Combo(3)
    extension._selected_streamlines_profile_tuning = lambda: (
        StreamlinesProfileId.GLOBAL_FLOW_PATH,
        DEFAULT_GLOBAL_FLOW_PATH_TUNING,
    )
    extension._workload_combo = _Combo(0)
    requested = []

    async def capture(workload, _profile_id, _tuning):
        requested.append(workload)

    extension._run_streamlines_phase44a_preview = capture
    monkeypatch.setattr(module.asyncio, "ensure_future", _run_immediately)

    for index in range(4):
        extension._workload_combo.model.set_index(index)
        extension._schedule_streamlines_phase44a_preview()

    assert requested == ["Idle", "Nominal", "Surge", "Critical"]


def test_phase44a_volume_controls_resolve_only_volume_selection(monkeypatch):
    module = _load_extension(monkeypatch)
    extension = module.DigitalTwinRuntimeSuiteExtension()
    extension._streamlines_profile_combo = _Combo(0)
    extension._streamlines_global_tuning_combos = {
        "seed_count": _Combo(0),
        "max_steps": _Combo(3),
        "step_scale": _Combo(0),
    }
    extension._streamlines_volume_tuning_combos = {
        "section_count": _Combo(3),
        "seeds_per_section": _Combo(2),
        "max_steps": _Combo(2),
        "step_scale": _Combo(2),
    }

    profile_id, selection = extension._selected_streamlines_profile_tuning()

    assert profile_id is StreamlinesProfileId.VOLUME_COVERAGE
    assert selection == DEFAULT_VOLUME_COVERAGE_TUNING


def test_phase44a_preview_action_uses_preview_backend_without_mode_request(
    monkeypatch,
):
    module = _load_extension(monkeypatch)
    extension = module.DigitalTwinRuntimeSuiteExtension()
    controller = _PreviewController()
    extension._controller = controller
    extension._streamlines_preview_button = SimpleNamespace(enabled=False)
    extension._streamlines_preview_status_label = SimpleNamespace(
        text="",
        tooltip="",
    )

    def reject_mode_request(_mode):
        raise AssertionError("Preview must not request a primary visualization mode.")

    extension._schedule_visualization_mode_request = reject_mode_request

    tuning = DEFAULT_GLOBAL_FLOW_PATH_TUNING
    asyncio.run(
        extension._run_streamlines_phase44a_preview(
            "Surge",
            StreamlinesProfileId.GLOBAL_FLOW_PATH,
            tuning,
        )
    )

    assert controller.preview_calls == 1
    assert controller.workload == "Surge"
    assert controller.tuning == tuning
    assert extension._streamlines_preview_button.enabled is True
    assert (
        "curves=12; points=345" in extension._streamlines_preview_status_label.tooltip
    )


def test_phase44a_mismatch_status_reports_expected_and_selected(monkeypatch):
    module = _load_extension(monkeypatch)
    extension = module.DigitalTwinRuntimeSuiteExtension()
    extension._controller = _MismatchPreviewController()
    extension._streamlines_preview_button = SimpleNamespace(enabled=False)
    extension._streamlines_preview_status_label = SimpleNamespace(text="", tooltip="")
    messages = []
    module.carb.log_error = messages.append

    asyncio.run(
        extension._run_streamlines_phase44a_preview(
            "Idle",
            StreamlinesProfileId.GLOBAL_FLOW_PATH,
            DEFAULT_GLOBAL_FLOW_PATH_TUNING,
        )
    )

    expected = "Unexpected 4.4A preview workload: " "expected=Nominal; selected=Idle."
    assert extension._streamlines_preview_status_label.tooltip == expected
    assert expected in "\n".join(messages)
    assert "Idle Streamlines preview failed" not in "\n".join(messages)


def test_phase44b_ready_retires_old_guidance_and_requests_playback_gate(
    monkeypatch,
):
    module = _load_extension(monkeypatch)
    messages = []
    module.carb.log_warn = messages.append
    extension = module.DigitalTwinRuntimeSuiteExtension()
    extension._controller = _AcceptanceController()
    extension._telemetry_provider = SimpleNamespace(mode="Nominal")
    extension._visualization_acceptance = None
    extension._validation_receipt_acceptance_owns_actions = False
    readiness = SimpleNamespace(entries=())

    extension._announce_visualization_acceptance_when_ready(readiness)

    output = "\n".join(messages)
    assert extension._controller.phase44b_announcements == 1
    assert extension._visualization_acceptance is None
    assert "PHASE_4_4A" not in output
    assert "PHASE_4_3" not in output
    assert "PRE_4_3" not in output


def test_visualization_acceptance_rejects_nonadvancing_visible_streamlines(
    monkeypatch,
):
    module = _load_extension(monkeypatch)
    messages = []
    module.carb.log_warn = messages.append
    extension = module.DigitalTwinRuntimeSuiteExtension()
    session = GuidedAcceptanceSession(("Streamlines",))
    session.begin()
    extension._visualization_acceptance = session
    extension._controller = _AcceptanceController()
    extension._controller.set_streamlines_baseline("Nominal")
    extension._controller.streamlines_advanced = False

    extension._report_visualization_acceptance_result(
        VisualizationMode.STREAMLINES,
        SimpleNamespace(success=True, message="Streamlines verified."),
    )

    events = "\n".join(messages)
    assert "| FAIL" in events
    assert "TEST COMPLETE" not in events


def test_visualization_acceptance_rejects_nonisolated_streamlines_reference(
    monkeypatch,
):
    module = _load_extension(monkeypatch)
    messages = []
    module.carb.log_warn = messages.append
    extension = module.DigitalTwinRuntimeSuiteExtension()
    session = GuidedAcceptanceSession(("Streamlines",))
    session.begin()
    extension._visualization_acceptance = session
    extension._controller = _AcceptanceController()
    extension._controller.set_streamlines_baseline("Nominal")
    extension._controller.reference_swap_passed = False

    extension._report_visualization_acceptance_result(
        VisualizationMode.STREAMLINES,
        SimpleNamespace(success=True, message="Streamlines verified."),
    )

    events = "\n".join(messages)
    assert "| FAIL" in events
    assert "TEST COMPLETE" not in events


def test_phase43_workload_failure_cannot_emit_test_complete(monkeypatch):
    module = _load_extension(monkeypatch)
    messages = []
    module.carb.log_warn = messages.append
    extension = module.DigitalTwinRuntimeSuiteExtension()
    session = GuidedAcceptanceSession(("Critical", "Normal"))
    session.begin()
    extension._visualization_acceptance = session
    extension._controller = _AcceptanceController()
    extension._controller.set_streamlines_baseline("Nominal")

    extension._report_phase43_workload_start("Critical")
    extension._report_phase43_workload_result(
        "Critical",
        SimpleNamespace(success=False, message="Critical cache is STALE."),
    )

    events = "\n".join(messages)
    assert "| FAIL" in events
    assert "Critical cache is STALE" in events
    assert "TEST COMPLETE" not in events


def test_normal_acceptance_ignores_hidden_prepared_streamlines_but_rejects_smoke(
    monkeypatch,
):
    module = _load_extension(monkeypatch)
    extension = module.DigitalTwinRuntimeSuiteExtension()
    extension._controller = _AcceptanceController()
    extension._controller.streamlines_root_prepared = True

    hidden_reason = extension._visualization_acceptance_failure_reason(
        VisualizationMode.NORMAL,
        SimpleNamespace(success=True, message="Normal verified."),
    )
    extension._controller.smoke_visible = True
    active_reason = extension._visualization_acceptance_failure_reason(
        VisualizationMode.NORMAL,
        SimpleNamespace(success=True, message="Normal verified."),
    )

    assert hidden_reason is None
    assert active_reason is not None
    assert "smoke_visible=True" in active_reason


class _IntModel:
    def __init__(self, value: int) -> None:
        self._value = value

    def get_value_as_int(self) -> int:
        return self._value

    def set_value(self, value: int) -> None:
        self._value = value


class _SelectorController:
    def visualization_readiness(self):
        return SimpleNamespace(
            for_mode=lambda _mode: SimpleNamespace(activation_available=True)
        )

    def visualization_snapshot(self):
        return SimpleNamespace(pending=None)


class _ActiveTask:
    def __init__(self) -> None:
        self.cancelled = False

    def done(self) -> bool:
        return False

    def cancel(self) -> None:
        self.cancelled = True


class _ComboModel:
    def __init__(self, index: int) -> None:
        self._index = _IntModel(index)

    def get_item_value_model(self, _item):
        return self._index

    def set_index(self, index: int) -> None:
        self._index.set_value(index)


class _Combo:
    def __init__(self, index: int) -> None:
        self.model = _ComboModel(index)


class _PreviewController:
    def __init__(self) -> None:
        self.preview_calls = 0
        self.tuning = None
        self.workload = None

    async def run_streamlines_profile_preview(
        self,
        *,
        status_callback,
        profile_id,
        workload,
        tuning_selection,
    ):
        self.preview_calls += 1
        self.profile_id = profile_id
        self.tuning = tuning_selection
        self.workload = workload
        status_callback("Executing standard Kit-CAE Streamlines preview.")
        return (SimpleNamespace(curve_count=12, point_count=345),)


class _MismatchPreviewController:
    async def run_streamlines_profile_preview(self, **_kwargs):
        raise StreamlinesPreviewWorkloadMismatchError(
            expected="Nominal",
            selected="Idle",
        )


class _CompletedTask:
    def done(self) -> bool:
        return True


def _run_immediately(coroutine):
    asyncio.run(coroutine)
    return _CompletedTask()


class _AcceptanceController:
    def __init__(self) -> None:
        self.committed = VisualizationMode.NORMAL
        self._flow_lifecycle_state = "DETACHED"
        self.override_owner = None
        self.scheduler_count = 0
        self.streamlines_root_prepared = False
        self.streamlines_visible = False
        self.smoke_visible = False
        self.streamlines_advanced = True
        self.smoke_resumed = True
        self.smoke_advancement_count = 3
        self._streamlines_controls_timeline = False
        self.temporal_proof_state = "PASSED"
        self.temporal_failure_reason = None
        self.timeline_playing = True
        self.flow_attach_calls = 0
        self.phase44b_announcements = 0
        self.reference_swap_passed = True
        self._airflow_state = _AcceptanceAirflowState()
        self._streamlines_cache_playback_contract = None
        self._workload_evidence = None
        self.config = SimpleNamespace(
            chassis_presentation=SimpleNamespace(xray_target_groups=())
        )

    def visualization_readiness(self):
        return SimpleNamespace()

    def announce_streamlines_phase44b_mesh_playback_when_ready(self):
        self.phase44b_announcements += 1

    def configured_streamlines_cache_readiness_snapshot(self):
        return tuple(SimpleNamespace(classification="VALID") for _ in range(4))

    def airflow_transition_state(self):
        snapshot = self._airflow_state.snapshot
        return {
            "pending_airflow_selector": (
                snapshot.pending.target.binding.dataset_identity
                if snapshot.pending
                else None
            )
        }

    def visualization_snapshot(self):
        return SimpleNamespace(committed=self.committed, pending=None)

    def xray_target_snapshot(self):
        return SimpleNamespace(
            override_owner=self.override_owner,
            effective_target_ids=frozenset(),
        )

    def _active_streamlines_playback_task_count(self):
        return self.scheduler_count

    def streamlines_cached_presentation_is_visible_in_kit(self):
        return self.streamlines_visible

    def smoke_presentation_is_visible_in_kit(self):
        return self.smoke_visible

    def streamlines_cached_playback_advanced_in_kit(self):
        return self.streamlines_advanced

    def streamlines_cached_playback_advance_proof_in_kit(self):
        return SimpleNamespace(
            initial_sample_identity="index=36; source=nominal_1037.vti",
            advanced_sample_identity=(
                "index=37; source=nominal_1038.vti"
                if self.streamlines_advanced
                else None
            ),
            scheduler_tasks=self.scheduler_count,
            scheduler_tick_count=(2 if self.streamlines_advanced else 1),
            sample_advanced=self.streamlines_advanced,
        )

    def smoke_resume_source_advanced_in_kit(self):
        return self.smoke_resumed

    def smoke_resume_advance_proof_in_kit(self):
        count = self.smoke_advancement_count if self.smoke_resumed else 0
        return SimpleNamespace(
            source_0="nominal_1037.vti",
            source_1=("nominal_1038.vti" if count >= 1 else None),
            source_2=("nominal_1039.vti" if count >= 2 else None),
            stability_source=("nominal_1040.vti" if count >= 3 else None),
            source_advanced=count >= 3,
            sustained_flow_playback=count >= 3,
            timeline_playing=True,
        )

    def streamlines_controls_timeline_in_kit(self):
        return self._streamlines_controls_timeline

    def flow_timeline_is_playing_in_kit(self):
        return self.timeline_playing

    def visualization_flow_attach_call_count(self):
        return self.flow_attach_calls

    def streamlines_presentation_reference_snapshot(self):
        return SimpleNamespace(
            reference_swap_passed=self.reference_swap_passed,
            session_sublayers_unchanged=True,
            root_sublayers_unchanged=True,
            server_scene_composition_mutations=0,
        )

    def primary_visualization_presentation_snapshot_in_kit(self):
        return SimpleNamespace(
            flow_source_prepared=self._flow_lifecycle_state == "ATTACHED",
            smoke_presentation_visible=self.smoke_visible,
            streamlines_root_prepared=self.streamlines_root_prepared,
            streamlines_presentation_visible=self.streamlines_visible,
            streamlines_scheduler_tasks=self.scheduler_count,
        )

    def temporal_proof_progress(self):
        return SimpleNamespace(
            state=SimpleNamespace(value=self.temporal_proof_state),
            failure_reason=self.temporal_failure_reason,
        )

    def streamlines_workload_transition_evidence(self):
        return self._workload_evidence

    def set_streamlines_baseline(self, workload):
        target = _acceptance_target(workload)
        self.committed = VisualizationMode.STREAMLINES
        self._airflow_state.committed = target
        self._airflow_state.pending = None
        self._streamlines_cache_playback_contract = SimpleNamespace(
            workload=workload,
            dataset_identity=target.binding.dataset_identity,
        )
        self.scheduler_count = 1
        self.streamlines_visible = True
        self.smoke_visible = False

    def set_workload_evidence(self, workload):
        previous = self._airflow_state.committed.workload_mode
        target = _acceptance_target(workload)
        self._airflow_state.committed = target
        self._airflow_state.pending = None
        self._streamlines_cache_playback_contract = SimpleNamespace(
            workload=workload,
            dataset_identity=target.binding.dataset_identity,
        )
        self._workload_evidence = SimpleNamespace(
            requested_workload=workload,
            previous_workload=previous,
            target_dataset=target.binding.dataset_identity,
            target_cache="VALID",
            selected_sample_identity=f"index=7; source={workload.lower()}_7.vti",
            initial_sample_identity=f"index=7; source={workload.lower()}_7.vti",
            advanced_sample_identity=(f"index=8; source={workload.lower()}_8.vti"),
            committed_workload=workload,
            streamlines_visible=True,
            scheduler_tasks=1,
            sample_advanced=True,
            flow_attach_calls=0,
            streamlines_reference_swap=True,
            session_sublayers_unchanged=True,
            root_sublayers_unchanged=True,
            server_scene_composition_mutations=0,
        )

    def set_normal(self):
        self.committed = VisualizationMode.NORMAL
        self.scheduler_count = 0
        self.streamlines_visible = False
        self.smoke_visible = False
        self._streamlines_controls_timeline = False


class _AcceptanceAirflowState:
    def __init__(self):
        self.committed = None
        self.pending = None

    @property
    def snapshot(self):
        return SimpleNamespace(
            committed=self.committed,
            pending=self.pending,
        )


def _acceptance_target(workload):
    state = {
        "Idle": "load_idle",
        "Nominal": "load_normal",
        "Surge": "load_surge",
        "Critical": "load_critical",
    }[workload]
    return SimpleNamespace(
        workload_mode=workload,
        binding=SimpleNamespace(dataset_identity=f"server/{state}"),
    )


def _load_extension(monkeypatch):
    carb = types.ModuleType("carb")
    carb.log_warn = lambda _message: None
    carb.log_error = lambda _message: None
    monkeypatch.setitem(sys.modules, "carb", carb)
    for name in ("settings", "tokens", "windowing"):
        child = types.ModuleType(f"carb.{name}")
        setattr(carb, name, child)
        monkeypatch.setitem(sys.modules, f"carb.{name}", child)

    omni = types.ModuleType("omni")
    omni.__path__ = []
    monkeypatch.setitem(sys.modules, "omni", omni)
    for name in ("appwindow", "ext", "ui"):
        child = types.ModuleType(f"omni.{name}")
        setattr(omni, name, child)
        monkeypatch.setitem(sys.modules, f"omni.{name}", child)
    omni.ext.IExt = object

    path = (
        Path(__file__).parents[1]
        / "src"
        / "digital_twin_runtime_suite"
        / "ext"
        / "msp.dtrs"
        / "msp"
        / "dtrs"
        / "extension.py"
    )
    spec = importlib.util.spec_from_file_location("visualization_extension", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
