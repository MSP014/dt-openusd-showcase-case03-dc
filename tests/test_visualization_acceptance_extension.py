"""Focused regressions for the current selector and final acceptance UI."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace

from digital_twin_runtime_suite.app.visualization_mode import VisualizationMode


def test_visualization_selector_delegates_to_the_workflow(monkeypatch):
    module = _load_extension(monkeypatch)
    extension = module.DigitalTwinRuntimeSuiteExtension()
    extension._updating_visualization_mode = False
    extension._visualization_workflow = _VisualizationWorkflow()

    extension._on_visualization_mode_changed(_IntModel(1))

    assert extension._visualization_workflow.requested == [VisualizationMode.SMOKE]

    extension._updating_visualization_mode = True
    extension._on_visualization_mode_changed(_IntModel(0))

    assert extension._visualization_workflow.requested == [VisualizationMode.SMOKE]


def test_final_acceptance_controls_exist_only_for_active_visual_approval(
    monkeypatch,
):
    module = _load_extension(monkeypatch)
    extension = module.DigitalTwinRuntimeSuiteExtension()
    controller = _FinalAcceptanceController("first_visual")
    extension._controller = controller
    extension._streamlines_workflow = _FinalAcceptanceWorkflow(controller)
    extension._streamlines_final_acceptance_frame = _FinalAcceptanceControl()
    extension._streamlines_final_acceptance_confirm_button = _FinalAcceptanceControl()
    extension._streamlines_final_acceptance_failure_button = _FinalAcceptanceControl()
    extension._streamlines_final_acceptance_failure_reason = _FinalAcceptanceControl()

    extension._sync_streamlines_final_acceptance_action()

    assert extension._streamlines_final_acceptance_frame.visible is True
    assert extension._streamlines_final_acceptance_confirm_button.enabled is True
    assert (
        extension._streamlines_final_acceptance_confirm_button.text
        == "Confirm Clean Playback"
    )

    extension._confirm_streamlines_final_acceptance()

    assert controller.confirmed == 1


def test_final_acceptance_rejection_reads_the_temporary_reason_field(monkeypatch):
    module = _load_extension(monkeypatch)
    extension = module.DigitalTwinRuntimeSuiteExtension()
    controller = _FinalAcceptanceController("reentry_visual")
    extension._controller = controller
    extension._streamlines_workflow = _FinalAcceptanceWorkflow(controller)
    extension._streamlines_final_acceptance_frame = _FinalAcceptanceControl()
    extension._streamlines_final_acceptance_confirm_button = _FinalAcceptanceControl()
    extension._streamlines_final_acceptance_failure_button = _FinalAcceptanceControl()
    extension._streamlines_final_acceptance_failure_reason = _FinalTextControl(
        "snapshot flicker"
    )

    extension._sync_streamlines_final_acceptance_action()
    extension._reject_streamlines_final_acceptance()

    assert extension._streamlines_final_acceptance_frame.visible is True
    assert controller.rejected_reasons == ["snapshot flicker"]


class _IntModel:
    def __init__(self, value: int) -> None:
        self._value = value

    def get_value_as_int(self) -> int:
        return self._value


class _FinalAcceptanceControl:
    def __init__(self) -> None:
        self.enabled = False
        self.visible = False
        self.text = ""


class _FinalTextControl(_FinalAcceptanceControl):
    def __init__(self, value: str) -> None:
        super().__init__()
        self.model = SimpleNamespace(get_value_as_string=lambda: value)


class _FinalAcceptanceController:
    def __init__(self, expected_action: str) -> None:
        self.expected_action = expected_action
        self.confirmed = 0
        self.rejected_reasons = []

    def streamlines_snapshot_playback_acceptance_expected_action(self):
        return self.expected_action

    def confirm_streamlines_snapshot_playback_acceptance(self) -> bool:
        self.confirmed += 1
        return True

    def reject_streamlines_snapshot_playback_acceptance(self, reason: str) -> bool:
        self.rejected_reasons.append(reason)
        return True


class _VisualizationWorkflow:
    def __init__(self) -> None:
        self.requested = []

    def request_mode_from_ui(self, mode) -> None:
        self.requested.append(mode)


class _FinalAcceptanceWorkflow:
    """Assert final-gate UI callbacks delegate instead of owning gate state."""

    def __init__(self, controller) -> None:
        self._controller = controller

    def final_acceptance_expected_action(self):
        return self._controller.expected_action

    def confirm_final_acceptance(self) -> bool:
        return self._controller.confirm_streamlines_snapshot_playback_acceptance()

    def reject_final_acceptance(self, reason: str) -> bool:
        return self._controller.reject_streamlines_snapshot_playback_acceptance(reason)


def _load_extension(monkeypatch):
    for name in tuple(sys.modules):
        if name.startswith("msp.dtrs"):
            monkeypatch.delitem(sys.modules, name, raising=False)
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
    monkeypatch.syspath_prepend(str(path.parents[2]))
    spec = importlib.util.spec_from_file_location("visualization_extension", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
