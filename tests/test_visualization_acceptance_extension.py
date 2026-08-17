"""Focused Phase 4.2 selector and manual-acceptance regression contracts."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace

from digital_twin_runtime_suite.app.manual_acceptance import GuidedAcceptanceSession
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


def test_visualization_acceptance_reports_progress_waiting_and_final_complete_once(
    monkeypatch,
):
    module = _load_extension(monkeypatch)
    messages = []
    module.carb.log_warn = messages.append
    extension = module.DigitalTwinRuntimeSuiteExtension()
    session = GuidedAcceptanceSession(
        ("Smoke", "Streamlines", "Smoke", "Streamlines", "Smoke", "Normal")
    )
    session.begin()
    extension._visualization_acceptance = session
    extension._controller = _AcceptanceController()

    for index, mode in enumerate(
        (
            VisualizationMode.SMOKE,
            VisualizationMode.STREAMLINES,
            VisualizationMode.SMOKE,
            VisualizationMode.STREAMLINES,
            VisualizationMode.SMOKE,
            VisualizationMode.NORMAL,
        )
    ):
        extension._report_visualization_acceptance_start(mode)
        if index == 0:
            extension._report_visualization_acceptance_waiting_once(mode, 5)
        extension._controller.committed = mode
        extension._controller._flow_lifecycle_state = (
            "DETACHED" if mode is VisualizationMode.NORMAL else "ATTACHED"
        )
        extension._controller.scheduler_count = (
            1 if mode is VisualizationMode.STREAMLINES else 0
        )
        extension._controller.streamlines_visible = (
            mode is VisualizationMode.STREAMLINES
        )
        extension._controller.smoke_visible = mode is VisualizationMode.SMOKE
        extension._report_visualization_acceptance_result(
            mode,
            SimpleNamespace(success=True, message=f"{mode.value} verified."),
        )

    events = "\n".join(messages)
    assert "| START" in events
    assert "| PROGRESS" in events
    assert "| WAITING" in events
    assert events.index("Committed=Normal") < events.index("TEST COMPLETE")
    assert events.count("TEST COMPLETE") == 1


def test_visualization_acceptance_rejects_an_unexpected_failed_flow_proof(
    monkeypatch,
):
    module = _load_extension(monkeypatch)
    messages = []
    module.carb.log_warn = messages.append
    extension = module.DigitalTwinRuntimeSuiteExtension()
    session = GuidedAcceptanceSession(("Normal",))
    session.begin()
    extension._visualization_acceptance = session
    extension._controller = _AcceptanceController()
    extension._controller.temporal_proof_state = "FAILED"
    extension._controller.temporal_failure_reason = "strict source sequence failed"

    extension._report_visualization_acceptance_result(
        VisualizationMode.NORMAL,
        SimpleNamespace(success=True, message="Normal verified."),
    )

    events = "\n".join(messages)
    assert "| FAIL" in events
    assert "strict source sequence failed" in events
    assert "TEST COMPLETE" not in events


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
    extension._controller.committed = VisualizationMode.STREAMLINES
    extension._controller._flow_lifecycle_state = "ATTACHED"
    extension._controller.scheduler_count = 1
    extension._controller.streamlines_visible = True
    extension._controller.streamlines_advanced = False

    extension._report_visualization_acceptance_result(
        VisualizationMode.STREAMLINES,
        SimpleNamespace(success=True, message="Streamlines verified."),
    )

    events = "\n".join(messages)
    assert "| FAIL" in events
    assert "TEST COMPLETE" not in events


def test_visualization_acceptance_rejects_one_step_flow_resume(monkeypatch):
    module = _load_extension(monkeypatch)
    messages = []
    module.carb.log_warn = messages.append
    extension = module.DigitalTwinRuntimeSuiteExtension()
    session = GuidedAcceptanceSession(("Smoke",))
    session.begin()
    extension._visualization_acceptance = session
    extension._controller = _AcceptanceController()
    extension._controller.committed = VisualizationMode.SMOKE
    extension._controller._flow_lifecycle_state = "ATTACHED"
    extension._controller.smoke_visible = True
    extension._controller.smoke_advancement_count = 1

    extension._report_visualization_acceptance_result(
        VisualizationMode.SMOKE,
        SimpleNamespace(
            success=True,
            message="Smoke active; reused=True; reconstructed=False.",
        ),
    )

    events = "\n".join(messages)
    assert "| FAIL" in events
    assert "sustained post-Streamlines Flow playback proof" in events
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


class _SelectorController:
    def visualization_readiness(self):
        return SimpleNamespace(
            for_mode=lambda _mode: SimpleNamespace(activation_available=True)
        )

    def visualization_snapshot(self):
        return SimpleNamespace(pending=None)


class _ActiveTask:
    def done(self) -> bool:
        return False


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
        self.config = SimpleNamespace(
            chassis_presentation=SimpleNamespace(xray_target_groups=())
        )

    def visualization_readiness(self):
        return SimpleNamespace()

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
