"""Focused workflow sequencing for the three-GPU internal demo verdict."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace


def test_gpu_internal_demo_has_one_fast_visual_checkpoint() -> None:
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
    assert workflow.record_manual_verdict(False)
    controller.state = _state((), enabled=False)
    workflow.on_test_presentation_disabled(
        SimpleNamespace(success=True, vertical_slice=controller.state)
    )
    assert workflow.record_manual_verdict(True)

    output = "\n".join(messages)
    assert button_states.count(True) == 2
    assert "DTRS HEATMAPS | GPU INTERNAL DEMO | READY" in output
    assert "GPU_INTERNALS_GRADIENT_AUDIT | workload=Nominal" in output
    assert "GPU_PCB_DISPLAY_RANGES" in output
    assert "check=GPU_INTERNALS_PCB_PRESENTATION\nresult=FAIL" in output
    assert 'Press "Restore Heatmap Test" to restore the prior scene.' in output
    assert "DTRS PERFORMANCE PROBE" not in output
    assert "TEST COMPLETE\nFAIL" in messages[-1]
    assert "failed_checks=GPU_INTERNALS_PCB_PRESENTATION" in messages[-1]


class _Controller:
    def __init__(self) -> None:
        self.paths = ()
        targets = []
        for instance in (1, 2, 3):
            channels = (
                (f"gpu_{instance}_hotspot_temp_c",)
                + ((f"gpu_{instance}_memory_temp_c",) * 8)
                + ((f"gpu_{instance}_temp_c",) * 51)
            )
            for index, metric_id in enumerate(channels):
                path = f"/gpu{instance}/target_{index:02d}"
                self.paths += (path,)
                targets.append(
                    SimpleNamespace(
                        prim_path=path,
                        metric_id=metric_id,
                        semantic_key=SimpleNamespace(
                            hardware=SimpleNamespace(instance=instance),
                            thermal_zone="board" if index in {9, 10} else "vrm",
                            thermal_component="pcb" if index in {9, 10} else "choke",
                        ),
                        thermal_weights=(0.1, 1.0),
                        delta_profiles={
                            mode: SimpleNamespace(
                                minimum_celsius=-25.0,
                                maximum_celsius=-12.0,
                            )
                            for mode in ("Idle", "Nominal", "Surge", "Critical")
                        },
                    )
                )
        self.registry = SimpleNamespace(success=True, fingerprint=("stable",))
        self.contract = SimpleNamespace(
            targets=tuple(targets),
            unavailable_target_paths=(),
            scale_resolution=SimpleNamespace(
                scale=SimpleNamespace(minimum=26.0, maximum=108.0)
            ),
            provider_profiles={
                f"gpu_{instance}_temp_c": {
                    workload: (60.0, 0.0, 0.0, 0.0)
                    for workload in ("Idle", "Nominal", "Surge", "Critical")
                }
                for instance in (1, 2, 3)
            },
        )
        self.values = SimpleNamespace(
            for_prim=lambda path: SimpleNamespace(
                available=True,
                metric_id=self.contract.targets[self.paths.index(path)].metric_id,
            )
        )
        self.state = _state(self.paths)

    def heatmap_semantic_registry_snapshot(self):
        return self.registry

    def heatmap_vertical_slice_contract_snapshot(self):
        return self.contract

    def heatmap_gpu03_gradient_audit_snapshot(self):
        return (
            SimpleNamespace(
                thermal_zone="gpu_core",
                thermal_component="gb203_die",
                metric_id="gpu_3_hotspot_temp_c",
                target_count=1,
                weight_minimum=0.1,
                weight_maximum=0.9,
                delta_minimum_celsius=(-3.0, -3.0),
                delta_maximum_celsius=(7.0, 7.0),
                effective_display_span_celsius=8.0,
                variation="inside GPrim",
            ),
        )

    def heatmap_telemetry_binding_snapshot(self):
        return self.values

    def enable_heatmap_vertical_slice_in_kit(self):
        return self.state


def _result(controller):
    return SimpleNamespace(
        success=True,
        preflight=SimpleNamespace(success=True),
        registry=controller.registry,
        vertical_slice=SimpleNamespace(success=True),
    )


def _state(paths, *, enabled: bool = True):
    return SimpleNamespace(
        success=True,
        enabled=enabled,
        message="ok",
        target_paths=paths,
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
        / "heatmap_vertical_slice_acceptance.py"
    )
    spec = importlib.util.spec_from_file_location("heatmap_vertical_workflow", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.HeatmapVerticalSliceAcceptanceWorkflow
