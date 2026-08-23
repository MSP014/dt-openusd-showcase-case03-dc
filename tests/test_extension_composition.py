"""Focused composition-root regressions for the extracted DTRS extension."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace


def test_extension_keeps_private_controller_state_out_of_its_source() -> None:
    source = _extension_path().read_text(encoding="utf-8")
    startup = source[
        source.index("    def on_startup") : source.index("    def on_shutdown")
    ]
    shutdown = source[
        source.index("    def on_shutdown") : source.index("    def _build_controller")
    ]

    assert "_controller._" not in source
    assert "class DigitalTwinRuntimeSuiteExtension(" in source
    assert "_reload_config_and_stage" not in source
    controls_source = (_extension_path().parent / "ui" / "controls.py").read_text(
        encoding="utf-8"
    )
    assert (
        "@staticmethod\n\n    def _build_visualization_controls" not in controls_source
    )
    assert "SERVER_VIEW_LABEL_WIDTH = 150" in controls_source
    assert "self._build_controller()" in startup
    assert "ValidationReceiptWorkflow(" in startup
    assert "VisualizationWorkflow(" in startup
    assert "StreamlinesWorkflow(" in startup
    assert "PeriodicPerformanceWorkflow(" in startup
    assert startup.index("PeriodicPerformanceWorkflow(") < startup.index(
        "VisualizationWorkflow("
    )
    assert "self._build_window()" in startup
    assert "self._cancel_scene_action_tasks()" in shutdown
    assert "clear_streamlines_static_runtime_from_open_stage()" in shutdown
    assert "deactivate_heatmap_production_in_kit()" in shutdown
    assert "restore_heatmap_test_in_kit()" in shutdown


def test_shutdown_cancels_extracted_workflows_and_owned_tasks(monkeypatch) -> None:
    module = _load_extension(monkeypatch)
    extension = module.DigitalTwinRuntimeSuiteExtension()
    workflow_events: list[str] = []
    scene_tasks = [_Task(), _Task(), _Task(), _Task(), _Task()]
    camera_task = _Task()
    telemetry_task = _Task()
    auxiliary_task = _Task()
    controller = _Controller()

    extension._controller = controller
    extension._validation_workflow = _Workflow(workflow_events, "validation")
    extension._visualization_workflow = _Workflow(workflow_events, "visualization")
    extension._streamlines_workflow = _Workflow(workflow_events, "streamlines")
    extension._periodic_performance_workflow = _Workflow(
        workflow_events,
        "periodic_performance",
    )
    (
        extension._load_task,
        extension._reload_task,
        extension._lighting_task,
        extension._airflow_task,
        extension._view_task,
    ) = scene_tasks
    extension._auxiliary_windows_task = auxiliary_task
    extension._camera_sync_task = camera_task
    extension._telemetry_task = telemetry_task
    extension._motion_controller = _Motion()
    extension._window = _Window()

    extension.on_shutdown()

    assert workflow_events == [
        "validation",
        "visualization",
        "streamlines",
        "periodic_performance",
    ]
    assert all(task.cancelled for task in scene_tasks)
    assert auxiliary_task.cancelled
    assert camera_task.cancelled
    assert telemetry_task.cancelled
    assert controller.calls == [
        "cancel_transition",
        "heatmap_cleanup",
        "streamlines_cleanup",
        "xray_cleanup",
        "stop_flow_callbacks",
        "clear_flow_validation",
    ]


def test_shutdown_restores_active_debug_heatmap_before_remaining_cleanup(
    monkeypatch,
) -> None:
    module = _load_extension(monkeypatch)
    extension = module.DigitalTwinRuntimeSuiteExtension()
    controller = _Controller(heatmap_owner="debug")

    extension._controller = controller
    extension._validation_workflow = None
    extension._visualization_workflow = None
    extension._streamlines_workflow = None
    extension._periodic_performance_workflow = None
    extension._load_task = None
    extension._reload_task = None
    extension._lighting_task = None
    extension._airflow_task = None
    extension._view_task = None
    extension._auxiliary_windows_task = None
    extension._camera_sync_task = None
    extension._telemetry_task = None
    extension._motion_controller = None
    extension._window = None

    extension.on_shutdown()

    assert controller.debug_scheduler_stopped
    assert controller.heatmap_session_restored
    assert controller.calls == [
        "cancel_transition",
        "heatmap_test_restore",
        "streamlines_cleanup",
        "xray_cleanup",
        "stop_flow_callbacks",
        "clear_flow_validation",
    ]


def test_workload_cache_mapping_logs_when_a_controller_is_available(
    monkeypatch,
) -> None:
    module = _load_extension(monkeypatch)
    extension = module.DigitalTwinRuntimeSuiteExtension()
    extension._controller = _MappingController()

    extension._log_workload_cache_mapping("Nominal")

    assert extension._controller.requested_workloads == ["Nominal"]


class _Workflow:
    def __init__(self, events: list[str], name: str) -> None:
        self._events = events
        self._name = name

    def cancel(self) -> None:
        self._events.append(self._name)


class _Task:
    def __init__(self) -> None:
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class _Controller:
    def __init__(self, *, heatmap_owner: str = "production") -> None:
        self.calls: list[str] = []
        self._heatmap_owner = heatmap_owner
        self.debug_scheduler_stopped = False
        self.heatmap_session_restored = False

    def clear_streamlines_static_runtime_from_open_stage(self):
        self.calls.append("streamlines_cleanup")
        return SimpleNamespace(clean=True)

    def cancel_visualization_transition(self) -> None:
        self.calls.append("cancel_transition")

    def deactivate_heatmap_production_in_kit(self):
        self.calls.append("heatmap_cleanup")
        return SimpleNamespace(success=True)

    def heatmap_production_active(self) -> bool:
        return self._heatmap_owner == "production"

    def heatmap_test_active(self) -> bool:
        return self._heatmap_owner == "debug"

    def restore_heatmap_test_in_kit(self):
        self.calls.append("heatmap_test_restore")
        self.debug_scheduler_stopped = True
        self.heatmap_session_restored = True
        self._heatmap_owner = "none"
        return SimpleNamespace(success=True)

    def clear_xray_material_in_kit(self) -> None:
        self.calls.append("xray_cleanup")

    def stop_flow_runtime_callbacks(self) -> None:
        self.calls.append("stop_flow_callbacks")

    def clear_flow_validation_cache(self) -> None:
        self.calls.append("clear_flow_validation")


class _MappingController:
    def __init__(self) -> None:
        self.requested_workloads: list[str] = []

    def resolve_workload_airflow_binding(self, workload_mode: str):
        self.requested_workloads.append(workload_mode)
        return SimpleNamespace(format_mapping_log=lambda: "workload mapping")


class _Motion:
    def reset(self) -> None:
        pass


class _Window:
    def __init__(self) -> None:
        self.visible = True


def _extension_path() -> Path:
    return (
        Path(__file__).parents[1]
        / "src"
        / "digital_twin_runtime_suite"
        / "ext"
        / "msp.dtrs"
        / "msp"
        / "dtrs"
        / "extension.py"
    )


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

    path = _extension_path()
    monkeypatch.syspath_prepend(str(path.parents[2]))
    spec = importlib.util.spec_from_file_location("composition_extension", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
