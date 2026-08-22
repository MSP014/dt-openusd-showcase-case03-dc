"""Focused guided-acceptance coverage for Stage 10.1 Heatmap bindings."""

from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from digital_twin_runtime_suite.app.heatmaps.bindings import (
    build_heatmap_semantic_registry,
)
from digital_twin_runtime_suite.app.heatmaps.discovery import (
    PROPERTY_VALUE,
    ThermalPrimMetadata,
)
from digital_twin_runtime_suite.app.telemetry.model import (
    MetricValue,
    TelemetrySnapshot,
)


def test_guided_acceptance_reaches_wrapped_pass_without_presentation_work() -> None:
    workflow_module = _load_workflow()
    registry = build_heatmap_semantic_registry(_targets())
    controller = _Controller(registry)
    records: list[str] = []
    workflow = workflow_module.HeatmapBindingAcceptanceWorkflow(
        controller,
        log_warning=records.append,
        append_local_timestamp=lambda content: content + " | local",
    )

    workflow.start(
        SimpleNamespace(
            success=True,
            preflight=SimpleNamespace(success=True),
            registry=registry,
        )
    )
    for offset, workload in enumerate(("Idle", "Critical", "Nominal")):
        snapshot = _snapshot(workload, offset)
        controller.refresh(snapshot)
        workflow.observe_telemetry_snapshot(snapshot)

    assert "DTRS HEATMAPS | BINDING ACCEPTANCE | READY" in records[1]
    assert "status=Heatmap semantic registry is ready." in records[1]
    for field in (
        "targets=6",
        "semantic_groups=6",
        "bound_groups=6",
        "unavailable_groups=0",
        "identity_errors=0",
        "xray_precedence=0",
    ):
        assert f"\n{field}" in records[1]
    assert "NEXT_ACTION | Set workload to Idle." in records[1]
    assert "REPRESENTATIVE_BINDINGS:" in records[2]
    for binding in (
        "gpu_1 | gpu_core / gb203_die\n"
        "  metric=gpu_1_hotspot_temp_c\n"
        "  value=41.0 C\n"
        "  quality=measured",
        "gpu_2 | gpu_core / gb203_die\n"
        "  metric=gpu_2_hotspot_temp_c\n"
        "  value=42.0 C\n"
        "  quality=estimated",
        "gpu_3 | gpu_core / gb203_die\n"
        "  metric=gpu_3_hotspot_temp_c\n"
        "  value=43.0 C\n"
        "  quality=derived",
        "cpu | cpu_cooler_coldplate / coldplate\n"
        "  metric=cpu_temp_c\n"
        "  value=70.0 C\n"
        "  quality=synthetic",
        "nic | nic_board / pcb\n"
        "  metric=nic_temp_c\n"
        "  value=64.0 C\n"
        "  quality=stale",
        "psu | psu_coils / coil\n"
        "  metric=psu_temp_estimate_c\n"
        "  value=52.0 C\n"
        "  quality=estimated",
    ):
        assert binding in records[2]
    assert "┬░C" not in records[2]
    assert "NEXT_ACTION | Set workload to Critical." in records[2]
    for invariant in (
        "registry_stable=PASS",
        "semantic_keys_stable=PASS",
        "metric_ids_stable=PASS",
        "gpu_identities_stable=PASS",
        "telemetry_refresh=PASS",
        "quality_preserved=PASS",
        "binding_remaps=0",
    ):
        assert f"\n{invariant}" in records[3]
    assert "NEXT_ACTION | Return workload to Nominal." in records[3]
    for count in (
        "renderer_operations=0",
        "material_operations=0",
        "scalar_operations=0",
    ):
        assert f"\n{count}" in records[4]
    assert "TEST COMPLETE\nPASS\nNo further manual action required." in records[5]
    assert all(record.startswith("\n=") and " | local" in record for record in records)
    assert (
        registry.fingerprint
        == controller.heatmap_semantic_registry_snapshot().fingerprint
    )


class _Controller:
    def __init__(self, registry) -> None:
        self._registry = registry
        self._values = None

    def refresh(self, snapshot) -> None:
        self._values = self._registry.resolve_telemetry(snapshot)

    def heatmap_semantic_registry_snapshot(self):
        return self._registry

    def heatmap_telemetry_binding_snapshot(self):
        return self._values


def _targets() -> tuple[ThermalPrimMetadata, ...]:
    return (
        _target(
            "/blackwell_rig/compute/gpu_01/geo/render/RTX4500/die",
            "gpu_core",
            "gb203_die",
        ),
        _target(
            "/blackwell_rig/compute/gpu_02/geo/render/RTX4500/die",
            "gpu_core",
            "gb203_die",
        ),
        _target(
            "/blackwell_rig/compute/gpu_03/geo/render/RTX4500/die",
            "gpu_core",
            "gb203_die",
        ),
        _target(
            "/blackwell_rig/cpu_cooler/geo/render/coldplate",
            "cpu_cooler_coldplate",
            "coldplate",
        ),
        _target("/blackwell_rig/connectx_7/geo/render/pcb", "nic_board", "pcb"),
        _target("/blackwell_rig/power/psu/geo/render/coil", "psu_coils", "coil"),
    )


def _target(path: str, zone: str, component: str) -> ThermalPrimMetadata:
    return ThermalPrimMetadata(
        prim_path=path,
        thermal_zone=zone,
        thermal_component=component,
        thermal_weight=(0.25, 0.75),
        thermal_weight_interpolation="vertex",
        temperature_preview=None,
        temperature_preview_interpolation=None,
        thermal_zone_state=PROPERTY_VALUE,
        thermal_component_state=PROPERTY_VALUE,
        thermal_weight_state=PROPERTY_VALUE,
    )


def _snapshot(workload: str, offset: int) -> TelemetrySnapshot:
    return TelemetrySnapshot.create(
        schema_version="1",
        provider_id="test",
        provider_type="test",
        timestamp=(
            datetime(2026, 8, 21, tzinfo=timezone.utc) + timedelta(seconds=offset)
        ),
        operational_state=workload,
        refresh_interval_s=1,
        metrics={
            "gpu_1_hotspot_temp_c": MetricValue(
                41.0 + offset,
                "°C",
                "measured",
            ),
            "gpu_2_hotspot_temp_c": MetricValue(
                42.0 + offset,
                "°C",
                "estimated",
            ),
            "gpu_3_hotspot_temp_c": MetricValue(
                43.0 + offset,
                "°C",
                "derived",
            ),
            "cpu_temp_c": MetricValue(70.0 + offset, "°C", "synthetic"),
            "nic_temp_c": MetricValue(64.0 + offset, "°C", "stale"),
            "psu_temp_estimate_c": MetricValue(52.0 + offset, "°C", "estimated"),
        },
    )


def _load_workflow():
    path = (
        Path(__file__).parents[2]
        / "src/digital_twin_runtime_suite/ext/msp.dtrs/msp/dtrs/workflows/"
        "heatmap_binding_acceptance.py"
    )
    spec = importlib.util.spec_from_file_location("heatmap_binding_acceptance", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module
