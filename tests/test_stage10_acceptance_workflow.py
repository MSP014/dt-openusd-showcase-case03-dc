"""Focused Stage 10 guided-acceptance workflow contracts."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

from digital_twin_runtime_suite.app.heatmaps.settings import HeatmapSettings
from digital_twin_runtime_suite.app.visualization_mode import VisualizationMode


def test_acceptance_starts_only_from_clean_normal_and_guides_heatmap() -> None:
    controller = _Controller()
    messages: list[str] = []
    workflow = _workflow(
        controller,
        log_warning=messages.append,
        append_local_timestamp=lambda message: message,
    )

    assert workflow.begin_if_ready()
    assert "NEXT_ACTION | Select Heatmap." in messages[-1]

    controller.visualization = SimpleNamespace(
        committed=VisualizationMode.HEATMAP,
        pending=None,
    )
    controller.production_active = True
    controller.primary = _primary()
    workflow.observe_mode_complete(
        VisualizationMode.HEATMAP,
        SimpleNamespace(success=True, message="Heatmap active"),
    )

    assert "Nominal" in messages[-1]


def test_acceptance_does_not_start_while_debug_heatmap_owns_state() -> None:
    controller = _Controller()
    controller.debug_active = True
    workflow = _workflow(
        controller,
        log_warning=lambda _message: None,
        append_local_timestamp=lambda message: message,
    )

    assert not workflow.begin_if_ready()


def _primary():
    return SimpleNamespace(
        smoke_presentation_visible=False,
        heatmap_presentation_active=True,
        streamlines_presentation_visible=False,
        streamlines_scheduler_tasks=0,
    )


class _Controller:
    def __init__(self) -> None:
        self.visualization = SimpleNamespace(
            committed=VisualizationMode.NORMAL,
            pending=None,
        )
        self.production_active = False
        self.debug_active = False
        self.primary = _primary()
        self.settings = HeatmapSettings(isolation_selectors=("gpu_02_housing",))

    def heatmap_catalog_snapshot(self):
        return SimpleNamespace(ready=True)

    def visualization_snapshot(self):
        return self.visualization

    def heatmap_applied_settings_snapshot(self):
        return self.settings

    def heatmap_test_active(self):
        return self.debug_active

    def heatmap_production_active(self):
        return self.production_active

    def primary_visualization_presentation_snapshot_in_kit(self):
        return self.primary

    def heatmap_presentation_snapshot(self):
        return SimpleNamespace(
            production_active=self.production_active,
            debug_active=self.debug_active,
            target_paths=("/blackwell_rig/gpu_02",),
            diagnostics=SimpleNamespace(
                active=True,
                scheduler_tasks=1,
                dynamic_transport_active=True,
                last_dynamic_update_success=True,
                unavailable_material_groups=(),
                material_group_count=1,
            ),
        )

    @staticmethod
    def xray_target_snapshot():
        return SimpleNamespace(
            override_owner="heatmap_preview",
            override_target_ids=frozenset({"gpu_shrouds"}),
            override_excluded_paths=frozenset(),
            manual_target_ids=frozenset(),
        )


def _workflow(controller, *, log_warning, append_local_timestamp):
    return _load_workflow().Stage10AcceptanceWorkflow(
        controller,
        log_warning=log_warning,
        append_local_timestamp=append_local_timestamp,
    )


def _load_workflow():
    path = (
        Path(__file__).parents[1]
        / "src"
        / "digital_twin_runtime_suite"
        / "ext"
        / "msp.dtrs"
        / "msp"
        / "dtrs"
        / "workflows"
        / "stage10_acceptance.py"
    )
    spec = importlib.util.spec_from_file_location("stage10_acceptance_workflow", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
