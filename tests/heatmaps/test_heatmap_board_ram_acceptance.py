"""Focused motherboard Heatmap acceptance workflow coverage."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace


def test_motherboard_acceptance_sequences_all_focuses_then_restoration() -> None:
    messages: list[str] = []
    button_states: list[bool] = []
    controller = _Controller()
    workflow = _load_workflow()(
        controller,
        log_warning=messages.append,
        append_local_timestamp=lambda text: text,
        set_manual_verdict_enabled=button_states.append,
        set_test_enabled=controller.set_test_enabled,
        restoration_action_label=lambda: "Restore Heatmap Test",
    )

    workflow.start(SimpleNamespace(success=True, full_server=_state()))
    for _ in range(8):
        assert workflow.record_manual_verdict(True)
    controller.active = False
    controller.filter_active = False
    workflow.on_test_presentation_disabled(SimpleNamespace(success=True))
    assert workflow.record_manual_verdict(True)

    assert "DTRS HEATMAPS | MOTHERBOARD BINDING ACCEPTANCE | START" in messages[0]
    assert any("| READY" in message for message in messages)
    assert "MOTHERBOARD_BASE_BINDING" in "\n".join(messages)
    assert "MOTHERBOARD_CPU_SOCKET_BINDING" in "\n".join(messages)
    assert "MOTHERBOARD_VRM_EAST_BINDING" in "\n".join(messages)
    assert "foreign_target_count=0" in "\n".join(messages)
    assert "MOTHERBOARD_DELTA_CALIBRATION" in "\n".join(messages)
    assert "classification=SMALL target=10.0 C" in "\n".join(messages)
    assert 'Press "Restore Heatmap Test"' in "\n".join(messages)
    assert "TEST COMPLETE\nPASS\nmanual_checks=9/9" in messages[-1]
    assert button_states.count(True) == 9
    assert "DTRS PERFORMANCE PROBE" not in "\n".join(messages)
    assert controller.cadences == []


def test_automatic_focus_failure_cleans_up_without_waiting_for_a_verdict() -> None:
    messages: list[str] = []
    controller = _Controller(focus_success=False)
    workflow = _load_workflow()(
        controller,
        log_warning=messages.append,
        append_local_timestamp=lambda text: text,
        set_manual_verdict_enabled=lambda _enabled: None,
        set_test_enabled=controller.set_test_enabled,
        restoration_action_label=lambda: "Restore Heatmap Test",
    )

    workflow.start(SimpleNamespace(success=True, full_server=_state()))

    assert not workflow.active
    assert controller.cleaned
    assert controller.test_enabled == [False]
    assert "| FAIL" in "\n".join(messages)
    assert "TEST COMPLETE\nFAIL" in messages[-1]


class _Controller:
    def __init__(self, *, focus_success: bool = True) -> None:
        self._focus_success = focus_success
        self.active = True
        self.filter_active = True
        self.cleaned = False
        self.test_enabled: list[bool] = []
        self.cadences: list[int] = []

    def set_heatmap_binding_calibration_focus_in_kit(self, metric_ids, scope):
        counts = {
            "motherboard_temp_c": 572,
            "chipset_temp_c": 1,
            "cpu_temp_c": 7,
            "vrm_e_temp_c": 2,
            "vrm_w_temp_c": 2,
            "nvme_1_temp_c": 2,
            "nvme_2_temp_c": 3,
            **{f"ram_{instance}_temp_c": 1 for instance in range(1, 9)},
        }
        count = sum(counts[metric_id] for metric_id in metric_ids)
        paths = tuple(f"{scope}/{metric_ids[0]}_{index}" for index in range(count))
        return SimpleNamespace(
            success=self._focus_success,
            metric_ids=metric_ids,
            expected_target_paths=paths,
            rendered_target_paths=paths,
            foreign_rendered_target_paths=(),
            message="ok" if self._focus_success else "focus failed",
        )

    def set_heatmap_binding_calibration_full_scope_in_kit(self, scope):
        return self.set_heatmap_binding_calibration_focus_in_kit(
            (
                "motherboard_temp_c",
                "chipset_temp_c",
                "cpu_temp_c",
                "vrm_e_temp_c",
                "vrm_w_temp_c",
                "nvme_1_temp_c",
                "nvme_2_temp_c",
                *(f"ram_{instance}_temp_c" for instance in range(1, 9)),
            ),
            scope,
        )

    @staticmethod
    def heatmap_telemetry_binding_snapshot():
        return SimpleNamespace(
            for_prim=lambda _path: SimpleNamespace(
                value=45.0,
                quality="synthetic",
            )
        )

    def heatmap_binding_calibration_test_active(self) -> bool:
        return self.active

    def heatmap_binding_calibration_filter_active(self) -> bool:
        return self.filter_active

    def set_heatmap_binding_calibration_test_in_kit(self, enabled: bool):
        if not enabled:
            self.active = False
            self.filter_active = False
            self.cleaned = True
        return SimpleNamespace(success=True)

    def set_heatmap_presentation_cadence_hz(self, cadence_hz: int) -> None:
        self.cadences.append(cadence_hz)

    @staticmethod
    def heatmap_motherboard_delta_calibration_snapshot():
        profile = SimpleNamespace(
            workload="Nominal",
            delta_minimum_celsius=-5.0,
            delta_maximum_celsius=5.0,
            display_minimum_celsius=40.0,
            display_maximum_celsius=44.5,
            effective_span_celsius=4.5,
        )
        return (
            SimpleNamespace(
                thermal_zone="mb_chips",
                thermal_component="small_ic",
                metric_id="motherboard_temp_c",
                target_count=108,
                weight_minimum=0.2,
                weight_maximum=0.8,
                calibration_kind="SMALL target=10.0 C",
                profiles=(profile,),
            ),
        )

    @staticmethod
    def heatmap_presentation_transition_duration_seconds() -> float:
        return 2.0

    @staticmethod
    def heatmap_presentation_retarget_evidence_snapshot():
        return (
            SimpleNamespace(
                material_group_key="motherboard_temp_c",
                displayed_before_celsius=45.0,
                target_celsius=46.0,
                first_displayed_after_celsius=45.2,
                maximum_step_celsius=0.2,
                continuous=True,
            ),
        )

    @staticmethod
    def heatmap_presentation_diagnostics_snapshot():
        return SimpleNamespace(
            scheduler_tick_count=0,
            telemetry_target_changes=0,
            semantic_groups_considered=0,
            shader_parameter_writes=0,
            skipped_unchanged_parameter_writes=0,
            structural_material_writes=0,
            material_binding_writes=0,
            primvar_st_writes=0,
        )

    def set_test_enabled(self, enabled: bool) -> None:
        self.test_enabled.append(enabled)


def _state():
    return SimpleNamespace(workload="Nominal")


def _load_workflow():
    path = (
        Path(__file__).parents[2]
        / "src"
        / "digital_twin_runtime_suite"
        / "ext"
        / "msp.dtrs"
        / "msp"
        / "dtrs"
        / "workflows"
        / "heatmap_board_ram_acceptance.py"
    )
    spec = importlib.util.spec_from_file_location("heatmap_board_ram_workflow", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.HeatmapMotherboardAcceptanceWorkflow
