"""Focused full-server guided-acceptance sequencing coverage."""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace


def test_full_server_acceptance_checks_nodes_then_restores_scene() -> None:
    messages: list[str] = []
    button_states: list[bool] = []
    controller = _Controller()
    workflow = _load_workflow()(
        controller,
        log_warning=messages.append,
        append_local_timestamp=lambda text: text,
        set_manual_verdict_enabled=button_states.append,
        restoration_action_label=lambda: "Restore Heatmap Test",
    )

    workflow.start(_result(controller))
    workflow.observe_telemetry_snapshot(SimpleNamespace(operational_state="Nominal"))
    for _ in range(3):
        assert workflow.record_manual_verdict(True)
    assert workflow.record_manual_verdict(True)
    for workload in ("Idle", "Surge", "Critical"):
        workflow.observe_telemetry_snapshot(SimpleNamespace(operational_state=workload))
        assert workflow.record_manual_verdict(True)
    controller.state = _state(controller, enabled=False, material_groups=0, bindings=0)
    workflow.on_test_presentation_disabled(
        SimpleNamespace(success=True, full_server=controller.state)
    )
    assert workflow.record_manual_verdict(True)

    assert button_states.count(True) == 8
    assert "DTRS HEATMAPS | FULL SERVER ACCEPTANCE | READY" in messages[1]
    assert "GPU 1 is ready for visual inspection." in messages[2]
    assert "CPU / CPU cooler is ready for visual inspection." in messages[4]
    assert "PSU is ready for visual inspection." in messages[6]
    assert "UNAVAILABLE_REGIONS" in messages[8]
    assert (
        'NEXT_ACTION | Press "Restore Heatmap Test" to remove the Heatmap test '
        "presentation and restore the prior scene appearance."
    ) in "\n".join(messages)
    assert "TEST COMPLETE\nPASS\nmanual_checks=8/8" in messages[-1]


@dataclass(frozen=True)
class _Hardware:
    label: str


@dataclass(frozen=True)
class _Key:
    label: str
    hardware: _Hardware


class _Controller:
    def __init__(self) -> None:
        self.gpu = _Key("gpu_1/gpu_core/gb203_die", _Hardware("gpu_1"))
        self.cpu = _Key("cpu/coldplate/coldplate", _Hardware("cpu"))
        self.psu = _Key("psu/transformer/core", _Hardware("psu"))
        self.unavailable = _Key("motherboard/chips/small_ic", _Hardware("motherboard"))
        profile = SimpleNamespace(minimum_celsius=-2.0, maximum_celsius=4.0)
        self.contract = SimpleNamespace(
            renderable_targets=tuple(
                SimpleNamespace(
                    prim_path=f"/{key.hardware.label}",
                    semantic_key=key,
                    metric_id=metric,
                    delta_profiles={
                        mode: profile
                        for mode in ("Idle", "Nominal", "Surge", "Critical")
                    },
                )
                for key, metric in (
                    (self.gpu, "gpu_1_hotspot_temp_c"),
                    (self.cpu, "cpu_temp_c"),
                    (self.psu, "psu_temp_estimate_c"),
                )
            ),
            xray_precedence_targets=(),
            xray_precedence_target_paths=(),
            unavailable_target_paths=("/motherboard",),
            unavailable_reasons={"/motherboard": "No documented telemetry metric."},
        )
        self.registry = SimpleNamespace(
            success=True,
            fingerprint=("stable",),
            for_prim=lambda path: SimpleNamespace(semantic_key=self.unavailable),
        )
        self.state = _state(self, enabled=True, material_groups=3, bindings=3)

    def heatmap_full_server_contract_snapshot(self):
        return self.contract

    def heatmap_semantic_registry_snapshot(self):
        return self.registry

    def heatmap_full_server_snapshot(self):
        return self.state

    def heatmap_full_server_node_evidence_snapshot(self):
        return self.state.node_evidence


def _result(controller):
    return SimpleNamespace(
        success=True,
        preflight=SimpleNamespace(success=True),
        registry=controller.registry,
        full_server=controller.state,
    )


def _state(controller, *, enabled: bool, material_groups: int, bindings: int):
    evidence = tuple(
        SimpleNamespace(
            hardware_identity=key.hardware.label,
            rendered_target_count=1,
            semantic_groups=(key.label,),
            telemetry=(
                SimpleNamespace(
                    metric_id=metric,
                    value=value,
                    quality=quality,
                    derived_minimum_celsius=value - 2.0,
                    derived_maximum_celsius=value + 4.0,
                ),
            ),
            unavailable_target_paths=(),
        )
        for key, metric, value, quality in (
            (controller.gpu, "gpu_1_hotspot_temp_c", 88.0, "measured"),
            (controller.cpu, "cpu_temp_c", 74.0, "estimated"),
            (controller.psu, "psu_temp_estimate_c", 51.0, "derived"),
        )
    )
    scale = SimpleNamespace(minimum=30.0, maximum=108.0)
    return SimpleNamespace(
        success=True,
        enabled=enabled,
        message="ok",
        total_thermal_targets=7,
        renderable_target_paths=("/gpu_1", "/cpu", "/psu"),
        rendered_target_paths=("/gpu_1", "/cpu", "/psu") if enabled else (),
        unavailable_target_paths=("/motherboard",),
        xray_precedence_target_paths=(),
        semantic_group_count=4,
        material_group_count=material_groups,
        session_binding_count=bindings,
        scale_resolution=SimpleNamespace(scale=scale),
        palette_identity="full_spectrum_violet_blue_to_red",
        node_evidence=evidence,
    )


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
        / "heatmap_full_server_acceptance.py"
    )
    spec = importlib.util.spec_from_file_location("heatmap_full_workflow", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.HeatmapFullServerAcceptanceWorkflow
