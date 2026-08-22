"""Focused Stage 10.1 coverage for deterministic GPU thermal bindings."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from digital_twin_runtime_suite.app.heatmaps.bindings import (
    build_heatmap_semantic_registry,
    resolve_hardware_identity,
)
from digital_twin_runtime_suite.app.heatmaps.discovery import (
    PROPERTY_VALUE,
    ThermalPrimMetadata,
)
from digital_twin_runtime_suite.app.telemetry.model import (
    MetricValue,
    TelemetrySnapshot,
)


def test_gpu_instances_bind_hotspot_memory_and_general_semantics() -> None:
    targets = tuple(
        target
        for index in (1, 2, 3)
        for target in (
            _target(index, "gpu_core", "gb203_die", "die"),
            _target(index, "vram", "memory_chip", "vram"),
            _target(index, "vrm", "choke", "vrm"),
            _target(index, "gpu_body", "plug", "plug"),
            _target(index, "gpu_body", "shroud", "shroud"),
            _target(index, "gpu_cooling", "blower", "blower"),
        )
    )

    registry = build_heatmap_semantic_registry(targets)

    for index in (1, 2, 3):
        assert _binding(registry, index, "die") == f"gpu_{index}_hotspot_temp_c"
        assert _binding(registry, index, "vram") == f"gpu_{index}_memory_temp_c"
        assert _binding(registry, index, "vrm") == f"gpu_{index}_temp_c"
        assert _binding(registry, index, "plug") == f"gpu_{index}_temp_c"
        assert _binding(registry, index, "shroud") == f"gpu_{index}_temp_c"
        assert _binding(registry, index, "blower") == f"gpu_{index}_temp_c"
    assert _binding(registry, 3, "die") != "gpu_3_temp_c"


def test_unsupported_gpu_semantic_is_truthfully_unavailable() -> None:
    target = _target(1, "gpu_cooling", "fan", "fan")

    binding = (
        build_heatmap_semantic_registry((target,))
        .for_prim(target.prim_path)
        .telemetry_binding
    )

    assert not binding.available
    assert binding.unavailable_reason == (
        "No documented telemetry metric for gpu_1/gpu_cooling/fan."
    )


def test_ambiguous_gpu_ancestry_fails_with_exact_diagnostic() -> None:
    identity, diagnostic = resolve_hardware_identity(
        "/blackwell_rig/compute/gpu_01/compute/gpu_02/geo/render/die"
    )

    assert identity.family == "ambiguous"
    assert diagnostic.code == "AMBIGUOUS_HARDWARE_IDENTITY"
    assert diagnostic.message == "Ambiguous GPU identity in ancestry: gpu_01, gpu_02."


@pytest.mark.parametrize(
    "quality",
    ("measured", "estimated", "derived", "synthetic", "stale", "unavailable"),
)
def test_current_quality_is_preserved_without_binding_remap(quality: str) -> None:
    target = _target(1, "gpu_core", "gb203_die", "die")
    registry = build_heatmap_semantic_registry((target,))
    snapshot = _snapshot(
        {"gpu_1_hotspot_temp_c": MetricValue(72.5, "°C", quality=quality)}
    )

    resolved = registry.resolve_telemetry(snapshot).for_prim(target.prim_path)

    assert resolved.available
    assert resolved.metric_id == "gpu_1_hotspot_temp_c"
    assert resolved.value == 72.5
    assert resolved.quality == quality


def test_missing_hotspot_metric_only_makes_current_state_unavailable() -> None:
    target = _target(1, "gpu_core", "gb203_die", "die")
    registry = build_heatmap_semantic_registry((target,))

    resolved = registry.resolve_telemetry(_snapshot({})).for_prim(target.prim_path)

    assert registry.for_prim(target.prim_path).telemetry_binding.metric_id == (
        "gpu_1_hotspot_temp_c"
    )
    assert not resolved.available
    assert resolved.quality == "unavailable"


def test_xray_overlap_keeps_heatmap_capability_and_binding() -> None:
    target = _target(3, "gpu_core", "gb203_die", "die")

    resolved = build_heatmap_semantic_registry(
        (target,),
        xray_overlap_paths=(target.prim_path,),
    ).for_prim(target.prim_path)

    assert resolved.telemetry_binding.metric_id == "gpu_3_hotspot_temp_c"
    assert resolved.presentation_policy.heatmap_capable
    assert resolved.presentation_policy.xray_precedence


def test_unchanged_discovery_rebuilds_to_the_same_ordered_registry() -> None:
    targets = (
        _target(2, "gpu_core", "gb203_die", "die"),
        _target(1, "vram", "memory_chip", "vram"),
    )

    first = build_heatmap_semantic_registry(targets)
    second = build_heatmap_semantic_registry(tuple(reversed(targets)))

    assert first.targets == second.targets
    assert tuple(first.semantic_groups.items()) == tuple(second.semantic_groups.items())


def test_motherboard_semantics_prefer_specific_nvme_and_vrm_zones() -> None:
    targets = (
        _motherboard_target("str5_socket/cpu", "cpu", "cpu_package"),
        _motherboard_target("str5_socket/socket", "cpu", "socket"),
        _motherboard_target("pcb/chip", "mb_chips", "small_ic"),
        _motherboard_target("nvme_a/drive", "mb_nvme", "nvme_heatsink_a"),
        _motherboard_target("nvme_b/drive", "mb_nvme", "nvme_heatsink_b"),
        _motherboard_target("vrm_b/top", "vrm_east", "vrm_heatsink"),
        _motherboard_target("vrm_a/top", "vrm_west", "vrm_heatsink"),
        _motherboard_target("pcb/choke", "mb_chokes", "choke"),
    )

    registry = build_heatmap_semantic_registry(targets)

    assert _metric(registry, targets[0]) == "chipset_temp_c"
    assert _metric(registry, targets[1]) == "cpu_temp_c"
    assert _metric(registry, targets[2]) == "motherboard_temp_c"
    assert _metric(registry, targets[3]) == "nvme_1_temp_c"
    assert _metric(registry, targets[4]) == "nvme_2_temp_c"
    assert _metric(registry, targets[5]) == "vrm_e_temp_c"
    assert _metric(registry, targets[6]) == "vrm_w_temp_c"
    assert _metric(registry, targets[7]) == "motherboard_temp_c"


def test_passive_motherboard_heatsink_uses_a_cooler_board_anchor() -> None:
    """The unbacked passive heatsink follows board telemetry minus 8 C."""

    target = _motherboard_target(
        "passive/heatsink",
        "motherboard_passive",
        "heatsink",
    )
    binding = build_heatmap_semantic_registry((target,)).for_prim(target.prim_path)

    assert binding.telemetry_binding.metric_id == "motherboard_temp_c"
    assert binding.telemetry_binding.presentation_temperature_offset_celsius == -4.0


def test_motherboard_target_has_exactly_one_temperature_metric() -> None:
    target = _motherboard_target("vrm_b/top", "vrm_east", "vrm_heatsink")

    binding = build_heatmap_semantic_registry((target,)).for_prim(target.prim_path)

    assert binding.telemetry_binding.metric_id == "vrm_e_temp_c"
    assert binding.telemetry_binding.metric_id != "motherboard_temp_c"


def test_ram_modules_resolve_to_their_individual_documented_metrics() -> None:
    """Stable RAM ancestry selects the matching per-DIMM telemetry channel."""

    targets = tuple(
        _ram_target(instance, "ram_memory_chips", "memory_chip")
        for instance in range(1, 9)
    )
    registry = build_heatmap_semantic_registry(targets)

    for instance, target in enumerate(targets, start=1):
        binding = registry.for_prim(target.prim_path)
        assert binding is not None
        assert binding.semantic_key.hardware.label == f"ram_{instance}"
        assert binding.telemetry_binding.metric_id == f"ram_{instance}_temp_c"
        assert binding.telemetry_binding.presentation_temperature_offset_celsius == 2.0


def test_motherboard_dimm_slots_link_to_their_matching_ram_metrics() -> None:
    """Each authored motherboard slot uses its matching DIMM temperature minus 8 C."""

    targets = tuple(
        _motherboard_target(
            f"ram_slots/ram_slots/dimm_{instance:02d}",
            "memory",
            "dimm_slot",
        )
        for instance in range(1, 9)
    )
    registry = build_heatmap_semantic_registry(targets)

    for instance, target in enumerate(targets, start=1):
        binding = registry.for_prim(target.prim_path)
        assert binding is not None
        assert binding.semantic_key.hardware.label == f"ram_{instance}"
        assert binding.telemetry_binding.metric_id == f"ram_{instance}_temp_c"
        assert binding.telemetry_binding.presentation_temperature_offset_celsius == -8.0


def test_ram_component_offsets_preserve_the_raw_provider_value_and_quality() -> None:
    """Offsets alter only the scalar anchor, never the truthful metric snapshot."""

    targets = (
        _ram_target(1, "ram_pcb", "pcb"),
        _ram_target(1, "ram_small_components", "small_component"),
        _ram_target(1, "ram_memory_chips", "memory_chip"),
    )
    registry = build_heatmap_semantic_registry(targets)
    resolved = registry.resolve_telemetry(
        _snapshot({"ram_1_temp_c": MetricValue(43.0, "C", quality="synthetic")})
    )

    expected_offsets = (0.0, 4.0, 2.0)
    for target, expected_offset in zip(targets, expected_offsets, strict=True):
        binding = registry.for_prim(target.prim_path).telemetry_binding
        current = resolved.for_prim(target.prim_path)
        assert binding.metric_id == "ram_1_temp_c"
        assert binding.presentation_temperature_offset_celsius == expected_offset
        assert current.value == 43.0
        assert current.quality == "synthetic"


def _ram_target(
    instance: int,
    zone: str,
    component: str,
) -> ThermalPrimMetadata:
    return ThermalPrimMetadata(
        prim_path=(
            f"/blackwell_rig/ram/ram_{instance:02d}/geo/render/dimm/{component}"
        ),
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


def _target(index: int, zone: str, component: str, name: str) -> ThermalPrimMetadata:
    return ThermalPrimMetadata(
        prim_path=(
            f"/blackwell_rig/compute/gpu_{index:02d}/geo/render/RTX4500/pcb/" f"{name}"
        ),
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


def _motherboard_target(
    relative_path: str,
    zone: str,
    component: str,
) -> ThermalPrimMetadata:
    return ThermalPrimMetadata(
        prim_path=(
            "/blackwell_rig/motherboard/geo/render/ws_wrx90e/" f"{relative_path}"
        ),
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


def _metric(registry, target: ThermalPrimMetadata) -> str | None:
    return registry.for_prim(target.prim_path).telemetry_binding.metric_id


def _binding(registry, index: int, name: str) -> str:
    path = f"/blackwell_rig/compute/gpu_{index:02d}/geo/render/RTX4500/pcb/{name}"
    return registry.for_prim(path).telemetry_binding.metric_id


def _snapshot(metrics: dict[str, MetricValue]) -> TelemetrySnapshot:
    return TelemetrySnapshot.create(
        schema_version="1",
        provider_id="test",
        provider_type="test",
        timestamp=datetime(2026, 8, 21, tzinfo=timezone.utc),
        operational_state="Idle",
        refresh_interval_s=1,
        metrics=metrics,
    )
