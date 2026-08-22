"""Focused UI and log coverage for the temporary Heatmaps test control."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace


def test_view_tab_starts_with_only_heatmaps_expanded() -> None:
    """The temporary control remains the sole expanded View-tab section."""

    window_source = _window_path().read_text(encoding="utf-8")
    heatmaps_source = _heatmaps_ui_path().read_text(encoding="utf-8")

    visualization_index = window_source.index('"Visualization"')
    heatmaps_index = window_source.index('"Heatmaps"')
    streamlines_index = window_source.index('"Streamlines"')

    assert visualization_index < heatmaps_index < streamlines_index
    assert "heatmap_test_action_label(False)" in heatmaps_source
    assert "omni.usd" not in heatmaps_source
    assert "from pxr" not in heatmaps_source
    for title in (
        "Server Appearance",
        "Visualization",
        "Streamlines",
        "Development validation",
        "Airflow cache",
    ):
        section_start = window_source.index(f'"{title}"')
        section_end = window_source.find("self._build_config_section", section_start)
        assert "collapsed=True" in window_source[section_start:section_end]
    heatmaps_start = window_source.index('"Heatmaps"')
    heatmaps_end = window_source.find("self._build_config_section", heatmaps_start)
    assert "collapsed=True" not in window_source[heatmaps_start:heatmaps_end]
    assert 'self._select_sidebar_tab("View")' in window_source


def test_test_heatmaps_click_logs_a_stamped_start_record(monkeypatch) -> None:
    """Starting calibration emits the requested lifecycle record."""

    from digital_twin_runtime_suite.app.observability import (
        DtrsEventSink,
        ProgressReporter,
    )

    messages: list[str] = []
    carb = ModuleType("carb")
    carb.log_info = messages.append
    carb.log_error = messages.append
    monkeypatch.setitem(sys.modules, "carb", carb)
    _install_omni_ui(monkeypatch)
    module = _load_heatmaps_ui()
    panel = module.HeatmapsUiMixin()
    controller = _Controller()
    panel._controller = controller
    panel._observability_reporter = ProgressReporter(
        event_sinks=(
            DtrsEventSink(
                log_info=messages.append,
                log_warning=messages.append,
                log_error=messages.append,
                append_local_timestamp=lambda message: message,
            ),
        ),
    )
    panel._heatmap_test_isolation_button = SimpleNamespace(text="", tooltip="")
    panel._heatmap_vertical_slice_workflow = _Workflow()

    panel._toggle_heatmap_test_isolation()

    assert controller.requests == [True]
    assert panel._heatmap_test_isolation_button.text == "Restore Heatmap Test"
    assert len(messages) == 4
    assert "DTRS HEATMAPS | TEST | START" in messages[0]
    assert "status=Heatmap test started." in messages[0]
    assert "DTRS HEATMAPS | ASSET PREFLIGHT | START" in messages[1]
    assert "DTRS HEATMAPS | ASSET PREFLIGHT | COMPLETE" in messages[2]
    assert "result=PASS" in messages[2]
    assert (
        "DTRS HEATMAPS | MOTHERBOARD + RAM + CPU COOLER + GPU + NIC + PSU ISOLATION "
        "| COMPLETE" in messages[3]
    )
    assert "isolated with Heatmap presentation." in messages[3]
    assert "root=/blackwell_rig" in messages[3]
    assert "motherboard_visible=PASS" in messages[3]
    assert "ram_modules=8" in messages[3]
    assert "ram_instances=ram_01,ram_02,ram_03,ram_04" in messages[3]
    assert "ram_visible=PASS" in messages[3]
    assert "cpu_cooler_render_paths=2" in messages[3]
    assert "cpu_cooler_visible=PASS" in messages[3]
    assert "cpu_cooler_fan_hidden=PASS" in messages[3]
    assert "gpu_internals=3" in messages[3]
    assert "gpu_internals_visible=PASS" in messages[3]
    assert "gpu_plug_targets=12" in messages[3]
    assert "gpu_plugs_visible=PASS" in messages[3]
    assert "connectx_7_visible=PASS" in messages[3]
    assert "heatmap_presentation=PASS" in messages[3]
    assert "heatmap_presented_targets=1" in messages[3]
    assert panel._heatmap_vertical_slice_workflow.cancel_calls == 1
    assert panel._heatmap_vertical_slice_workflow.started == []


def test_failed_preflight_is_reported_before_motherboard_ram_isolation_failure(
    monkeypatch,
) -> None:
    """A production-contract FAIL remains visible before the test failure event."""

    from digital_twin_runtime_suite.app.observability import (
        DtrsEventSink,
        ProgressReporter,
    )

    messages: list[str] = []
    carb = ModuleType("carb")
    carb.log_info = messages.append
    carb.log_error = messages.append
    monkeypatch.setitem(sys.modules, "carb", carb)
    _install_omni_ui(monkeypatch)
    module = _load_heatmaps_ui()
    panel = module.HeatmapsUiMixin()
    controller = _Controller(
        preflight_status="FAIL",
        diagnostics=(
            SimpleNamespace(
                prim_path=(
                    "/blackwell_rig/motherboard/geo/render/ws_wrx90e/pcb/"
                    "resistor_311"
                ),
                reason="missing thermal_zone; missing thermal_component",
                core_attributes_present=(
                    "thermal_zone",
                    "primvars:thermal_weight",
                ),
                core_attributes_missing=("thermal_component",),
            ),
        ),
    )
    panel._controller = controller
    panel._observability_reporter = ProgressReporter(
        event_sinks=(
            DtrsEventSink(
                log_info=messages.append,
                log_warning=messages.append,
                log_error=messages.append,
                append_local_timestamp=lambda message: message,
            ),
        ),
    )
    panel._heatmap_test_isolation_button = SimpleNamespace(text="", tooltip="")

    panel._toggle_heatmap_test_isolation()

    assert controller.requests == [True]
    assert "DTRS HEATMAPS | ASSET PREFLIGHT | COMPLETE" in messages[2]
    assert "result=FAIL" in messages[2]
    assert "FAILED_ASSETS_TO_FIX:\nmotherboard\nfailed=1" in messages[2]
    assert (
        "- pcb/resistor_311\n"
        "  present: thermal_zone, primvars:thermal_weight\n"
        "  missing: thermal_component" in messages[2]
    )
    assert (
        "DTRS HEATMAPS | MOTHERBOARD + RAM + CPU COOLER + GPU + NIC + PSU ISOLATION "
        "| FAIL" in messages[3]
    )


def test_preflight_report_lists_every_failure_and_review_path(
    monkeypatch,
) -> None:
    """Terminal evidence retains all failed and review-required geometry."""

    from digital_twin_runtime_suite.app.observability import (
        DtrsEventSink,
        ProgressReporter,
    )

    messages: list[str] = []
    carb = ModuleType("carb")
    carb.log_info = messages.append
    carb.log_error = messages.append
    monkeypatch.setitem(sys.modules, "carb", carb)
    _install_omni_ui(monkeypatch)
    module = _load_heatmaps_ui()
    diagnostics = tuple(
        SimpleNamespace(
            prim_path=(
                "/blackwell_rig/motherboard/geo/render/ws_wrx90e/pcb/"
                f"resistor_{index}"
            ),
            reason="missing thermal_zone; missing thermal_component",
        )
        for index in range(4)
    )
    review_targets = tuple(
        f"/blackwell_rig/cpu_cooler/geo/render/NH_D9/fan_{index}" for index in range(4)
    )
    panel = module.HeatmapsUiMixin()
    panel._controller = _Controller(
        preflight_status="FAIL",
        diagnostics=diagnostics,
        review_targets=review_targets,
    )
    panel._observability_reporter = ProgressReporter(
        event_sinks=(
            DtrsEventSink(
                log_info=messages.append,
                log_warning=messages.append,
                log_error=messages.append,
                append_local_timestamp=lambda message: message,
            ),
        ),
    )
    panel._heatmap_test_isolation_button = SimpleNamespace(text="", tooltip="")

    panel._toggle_heatmap_test_isolation()

    report = messages[2]
    assert report.index("FAILED_ASSETS_TO_FIX:") < report.index("ASSETS_TO_REVIEW:")
    assert "motherboard\nfailed=4" in report
    assert "cpu_cooler\nreview=4" in report
    for index in range(4):
        assert f"- pcb/resistor_{index}" in report
        assert f"- fan_{index}" in report
    assert "... +" not in report
    assert "/blackwell_rig/" not in report


class _Controller:
    def __init__(
        self,
        *,
        preflight_status: str = "PASS",
        diagnostics=(),
        review_targets=(),
    ) -> None:
        self.requests: list[bool] = []
        self._preflight_status = preflight_status
        self._diagnostics = diagnostics
        self._review_targets = review_targets

    @staticmethod
    def heatmap_test_isolation_active() -> bool:
        return False

    def set_heatmap_test_isolation_in_kit(self, enabled: bool):
        self.requests.append(enabled)
        success = self._preflight_status == "PASS"
        self.result = SimpleNamespace(
            success=success,
            enabled=success,
            target_path="/blackwell_rig",
            message=(
                "Heatmap test isolation enabled for motherboard, eight RAM modules, "
                "CPU cooler without fans, GPU 1/2/3 internals, ConnectX-7, "
                "and PSU thermal internals."
                if success
                else "Heatmap asset preflight did not pass."
            ),
            focus_evidence=(
                SimpleNamespace(
                    motherboard_visible=True,
                    ram_module_paths=tuple(f"ram_{index:02d}" for index in range(1, 9)),
                    visible_ram_module_paths=tuple(
                        f"ram_{index:02d}" for index in range(1, 9)
                    ),
                    cpu_cooler_render_paths=(
                        "/blackwell_rig/cpu_cooler/geo/render/cpu_cooler/"
                        "cpu_radiator",
                        "/blackwell_rig/cpu_cooler/geo/render/cpu_cooler/"
                        "cooler_base",
                    ),
                    visible_cpu_cooler_render_paths=(
                        "/blackwell_rig/cpu_cooler/geo/render/cpu_cooler/"
                        "cpu_radiator",
                        "/blackwell_rig/cpu_cooler/geo/render/cpu_cooler/"
                        "cooler_base",
                    ),
                    cpu_cooler_fan_hidden=True,
                    gpu_internal_paths=("gpu_01", "gpu_02", "gpu_03"),
                    visible_gpu_internal_paths=("gpu_01", "gpu_02", "gpu_03"),
                    gpu_plug_paths=tuple(f"plug_{index}" for index in range(12)),
                    visible_gpu_plug_paths=tuple(
                        f"plug_{index}" for index in range(12)
                    ),
                    nic_render_path="/blackwell_rig/connectx_7/geo/render/connectx_7",
                    nic_visible=True,
                    unrelated_server_hardware_hidden=True,
                    outside_server_visibility_untouched=True,
                )
                if success
                else None
            ),
            full_server=(
                SimpleNamespace(
                    success=True,
                    enabled=True,
                    rendered_target_paths=("/blackwell_rig/motherboard/thermal",),
                )
                if success
                else None
            ),
            preflight=SimpleNamespace(
                root_path="/blackwell_rig",
                status=self._preflight_status,
                thermal_target_count=1,
                valid_target_count=1,
                malformed_target_count=len(self._diagnostics),
                review_target_count=len(self._review_targets),
                observed_weight_min=0.2,
                observed_weight_max=0.8,
                xray_overlap_targets=(),
                diagnostics=self._diagnostics,
                review_targets=self._review_targets,
            ),
        )
        return self.result


class _Workflow:
    def __init__(self) -> None:
        self.cancel_calls = 0
        self.started = []

    def cancel(self) -> None:
        self.cancel_calls += 1

    def start(self, result) -> None:
        self.started.append(result)


def _install_omni_ui(monkeypatch) -> None:
    omni_module = ModuleType("omni")
    omni_module.__path__ = []
    ui_module = ModuleType("omni.ui")
    omni_module.ui = ui_module
    monkeypatch.setitem(sys.modules, "omni", omni_module)
    monkeypatch.setitem(sys.modules, "omni.ui", ui_module)


def _load_heatmaps_ui():
    spec = importlib.util.spec_from_file_location(
        "test_heatmaps_ui_module",
        _heatmaps_ui_path(),
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _window_path() -> Path:
    return _heatmaps_ui_path().with_name("window.py")


def _heatmaps_ui_path() -> Path:
    return (
        Path(__file__).parents[2]
        / "src"
        / "digital_twin_runtime_suite"
        / "ext"
        / "msp.dtrs"
        / "msp"
        / "dtrs"
        / "ui"
        / "heatmaps.py"
    )
