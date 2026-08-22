"""Production-scale Stage 10.3 full-server Heatmap runtime coverage."""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path
from types import ModuleType

import pytest


def test_full_server_uses_truthful_bindings_and_restores_session_state(
    monkeypatch,
) -> None:
    from pxr import Usd

    from digital_twin_runtime_suite.app.commands import RuntimeController
    from digital_twin_runtime_suite.app.telemetry.config import TelemetryConfig
    from digital_twin_runtime_suite.app.telemetry.provider import (
        SyntheticTelemetryProvider,
    )

    controller = RuntimeController(_runtime_config_path())
    telemetry_config = TelemetryConfig.load(_telemetry_config_path())
    provider = SyntheticTelemetryProvider(telemetry_config, seed=7)
    controller.configure_heatmap_telemetry_config(telemetry_config)
    controller.refresh_heatmap_telemetry_snapshot(provider.latest_snapshot)
    stage = Usd.Stage.Open(str(_production_asset_path()))
    _install_omni_usd_stage(monkeypatch, stage)
    root_before = stage.GetRootLayer().ExportToString()
    session_before = stage.GetSessionLayer().ExportToString()

    enabled = controller.set_heatmap_full_server_test_in_kit(True)
    initial = controller.heatmap_full_server_snapshot()
    contract = controller.heatmap_full_server_contract_snapshot()
    registry = controller.heatmap_semantic_registry_snapshot()
    writes_before_unchanged_snapshot = (
        controller._heatmap_full_server_material_presenter.write_counts
    )
    controller.refresh_heatmap_telemetry_snapshot(provider.latest_snapshot)
    writes_after_unchanged_snapshot = (
        controller._heatmap_full_server_material_presenter.write_counts
    )

    assert enabled.success and enabled.enabled
    assert initial is not None and initial.success and initial.enabled
    assert writes_after_unchanged_snapshot == writes_before_unchanged_snapshot
    assert contract is not None and registry is not None
    assert initial.total_thermal_targets == 1148
    classified_paths = (
        set(initial.renderable_target_paths)
        | set(contract.unavailable_target_paths)
        | set(contract.xray_precedence_target_paths)
    )
    assert len(classified_paths) == 1148
    assert initial.xray_precedence_target_paths == contract.xray_precedence_target_paths
    assert not (
        set(initial.rendered_target_paths) & set(initial.xray_precedence_target_paths)
    )
    assert _gpu_metric(registry, 1, "gpu_core", "gb203_die") == ("gpu_1_hotspot_temp_c")
    assert _gpu_metric(registry, 2, "vram", "memory_chip") == ("gpu_2_memory_temp_c")
    assert _gpu_metric(registry, 3, "vrm", "capacitor") == ("gpu_3_temp_c")
    assert any(
        target.telemetry_binding.metric_id == "cpu_temp_c"
        for target in registry.targets
    )
    assert any(
        target.telemetry_binding.metric_id == "nic_temp_c"
        for target in registry.targets
    )
    nic_targets = tuple(
        target
        for target in (
            *contract.renderable_targets,
            *contract.xray_precedence_targets,
        )
        if target.semantic_key.hardware.family == "nic"
    )
    assert len(nic_targets) == 17
    assert all(
        profile.maximum_celsius - profile.minimum_celsius == pytest.approx(20.0)
        for target in nic_targets
        for profile in target.delta_profiles.values()
    )
    assert any(
        target.telemetry_binding.metric_id == "psu_temp_estimate_c"
        for target in registry.targets
    )
    assert any(
        value.quality == "derived"
        for node in initial.node_evidence
        for value in node.telemetry
        if value.metric_id == "psu_temp_estimate_c"
    )

    provider.set_mode("Critical")
    controller.refresh_heatmap_telemetry_snapshot(provider.tick())
    critical = controller.heatmap_full_server_snapshot()
    missing = _without_metric(provider.latest_snapshot, "gpu_2_memory_temp_c")
    controller.refresh_heatmap_telemetry_snapshot(missing)
    degraded = controller.heatmap_full_server_snapshot()
    controller.refresh_heatmap_telemetry_snapshot(provider.tick())
    recovered = controller.heatmap_full_server_snapshot()
    restored = controller.set_heatmap_full_server_test_in_kit(False)

    assert critical is not None
    assert critical.registry_fingerprint == initial.registry_fingerprint
    assert critical.scale_resolution == initial.scale_resolution
    assert critical.palette_identity == initial.palette_identity
    assert critical.material_group_count == initial.material_group_count
    assert critical.session_binding_count == initial.session_binding_count
    assert degraded is not None
    assert any("gpu_02" in path for path in degraded.unavailable_target_paths)
    assert recovered is not None
    assert recovered.registry_fingerprint == initial.registry_fingerprint
    assert recovered.material_group_count == initial.material_group_count
    assert recovered.session_binding_count == initial.session_binding_count
    assert restored.success and not restored.enabled
    assert stage.GetRootLayer().ExportToString() == root_before
    assert stage.GetSessionLayer().ExportToString() == session_before


def test_motherboard_calibration_focus_filters_without_remapping_registry(
    monkeypatch,
) -> None:
    from pxr import Usd

    from digital_twin_runtime_suite.app.commands import RuntimeController
    from digital_twin_runtime_suite.app.heatmaps.scalar import (
        DEFAULT_HEATMAP_DELTA_PROFILE,
        THERMAL_WEIGHT_REMAP_COLD_BIASED,
        THERMAL_WEIGHT_REMAP_LINEAR,
    )
    from digital_twin_runtime_suite.app.telemetry.config import TelemetryConfig
    from digital_twin_runtime_suite.app.telemetry.provider import (
        SyntheticTelemetryProvider,
    )

    controller = RuntimeController(_runtime_config_path())
    telemetry_config = TelemetryConfig.load(_telemetry_config_path())
    provider = SyntheticTelemetryProvider(telemetry_config, seed=9)
    controller.configure_heatmap_telemetry_config(telemetry_config)
    controller.refresh_heatmap_telemetry_snapshot(provider.latest_snapshot)
    provider_metric_ids = tuple(provider.latest_snapshot.metrics)
    stage = Usd.Stage.Open(str(_production_asset_path()))
    _install_omni_usd_stage(monkeypatch, stage)
    root_before = stage.GetRootLayer().ExportToString()
    session_before = stage.GetSessionLayer().ExportToString()

    started = controller.set_heatmap_binding_calibration_test_in_kit(True)
    registry = controller.heatmap_semantic_registry_snapshot()
    contract = controller.heatmap_full_server_contract_snapshot()
    calibration_matrix = controller.heatmap_motherboard_delta_calibration_snapshot()
    motherboard = controller.set_heatmap_binding_calibration_focus_in_kit(
        ("motherboard_temp_c",),
        controller.HEATMAP_MOTHERBOARD_PATH,
    )
    chipset = controller.set_heatmap_binding_calibration_focus_in_kit(
        ("chipset_temp_c",),
        controller.HEATMAP_MOTHERBOARD_PATH,
    )
    cpu_socket = controller.set_heatmap_binding_calibration_focus_in_kit(
        ("cpu_temp_c",),
        controller.HEATMAP_MOTHERBOARD_PATH,
    )
    vrm_east = controller.set_heatmap_binding_calibration_focus_in_kit(
        ("vrm_e_temp_c",),
        controller.HEATMAP_MOTHERBOARD_PATH,
    )
    vrm_west = controller.set_heatmap_binding_calibration_focus_in_kit(
        ("vrm_w_temp_c",),
        controller.HEATMAP_MOTHERBOARD_PATH,
    )
    nvme_a = controller.set_heatmap_binding_calibration_focus_in_kit(
        ("nvme_1_temp_c",),
        controller.HEATMAP_MOTHERBOARD_PATH,
    )
    nvme_b = controller.set_heatmap_binding_calibration_focus_in_kit(
        ("nvme_2_temp_c",),
        controller.HEATMAP_MOTHERBOARD_PATH,
    )
    nvme_b_telemetry = controller.heatmap_telemetry_binding_snapshot()
    source_metric = provider.latest_snapshot.metrics["nvme_2_temp_c"]
    combined = controller.set_heatmap_binding_calibration_full_scope_in_kit(
        controller.HEATMAP_MOTHERBOARD_PATH,
    )
    filtered = controller.heatmap_telemetry_binding_snapshot()
    controller.refresh_heatmap_telemetry_snapshot(provider.tick())
    refreshed = controller.heatmap_binding_calibration_focus_snapshot()
    filter_cleared = not controller.heatmap_binding_calibration_filter_active()
    restored = controller.set_heatmap_binding_calibration_test_in_kit(False)

    assert started.success and started.enabled
    assert started.full_server is not None and not started.full_server.enabled
    assert registry is not None and contract is not None
    motherboard_metrics = Counter(
        target.telemetry_binding.metric_id
        for target in registry.targets
        if target.prim_path.startswith("/blackwell_rig/motherboard/")
    )
    assert motherboard_metrics == {
        "motherboard_temp_c": 572,
        "chipset_temp_c": 1,
        "cpu_temp_c": 7,
        "vrm_e_temp_c": 2,
        "vrm_w_temp_c": 2,
        "nvme_1_temp_c": 2,
        "nvme_2_temp_c": 3,
        **{f"ram_{instance}_temp_c": 1 for instance in range(1, 9)},
    }
    assert sum(motherboard_metrics.values()) == 597
    assert len(calibration_matrix) == 22
    slot_targets = tuple(
        target
        for target in contract.renderable_targets
        if (
            target.prim_path.startswith("/blackwell_rig/motherboard/")
            and target.semantic_key.thermal_zone == "memory"
            and target.semantic_key.thermal_component == "dimm_slot"
        )
    )
    assert len(slot_targets) == 8
    assert {target.metric_id for target in slot_targets} == {
        f"ram_{instance}_temp_c" for instance in range(1, 9)
    }
    assert {
        target.presentation_temperature_offset_celsius for target in slot_targets
    } == {-8.0}
    slot_calibrations = tuple(
        row
        for row in calibration_matrix
        if (row.thermal_zone == "memory" and row.thermal_component == "dimm_slot")
    )
    assert len(slot_calibrations) == 8
    assert {row.metric_id for row in slot_calibrations} == {
        f"ram_{instance}_temp_c" for instance in range(1, 9)
    }
    assert {
        row.presentation_temperature_offset_celsius for row in slot_calibrations
    } == {-8.0}
    assert {row.target_count for row in slot_calibrations} == {1}
    calibration_by_semantic = {
        (row.thermal_zone, row.thermal_component): row for row in calibration_matrix
    }
    target_groups = {}
    for target in contract.renderable_targets:
        key = target.semantic_key
        if not target.prim_path.startswith("/blackwell_rig/motherboard/"):
            continue
        key = (key.thermal_zone, key.thermal_component)
        if key == ("memory", "dimm_slot"):
            continue
        target_groups.setdefault(key, []).append(target)
    cold_biased_groups = {
        ("mb_nvme", "nvme_heatsink_a"),
        ("mb_nvme", "nvme_heatsink_b"),
        ("mb_pcie_gpu", "pcie_gpu_slot"),
        ("motherboard_passive", "heatsink"),
        ("motherboard_power", "power_connector"),
        ("vrm_east", "vrm_heatsink"),
        ("vrm_west", "vrm_heatsink"),
    }
    for key, targets in target_groups.items():
        weights = tuple(
            weight for target in targets for weight in target.thermal_weights
        )
        expected_remap = (
            THERMAL_WEIGHT_REMAP_COLD_BIASED
            if key in cold_biased_groups
            else THERMAL_WEIGHT_REMAP_LINEAR
        )
        assert {target.thermal_weight_remap for target in targets} == {expected_remap}
        assert {target.thermal_weight_minimum for target in targets} == {min(weights)}
        assert {target.thermal_weight_maximum for target in targets} == {max(weights)}
    for targets in target_groups.values():
        for target in targets:
            for profile in target.delta_profiles.values():
                assert (
                    profile.minimum_celsius
                    == DEFAULT_HEATMAP_DELTA_PROFILE.minimum_celsius
                )
                assert (
                    profile.maximum_celsius
                    == DEFAULT_HEATMAP_DELTA_PROFILE.maximum_celsius
                )
    for key, row in calibration_by_semantic.items():
        if key == ("memory", "dimm_slot"):
            continue
        assert row.target_count == len(target_groups[key])
        assert tuple(profile.workload for profile in row.profiles) == (
            "Idle",
            "Nominal",
            "Surge",
            "Critical",
        )
        for profile in row.profiles:
            assert (
                profile.delta_minimum_celsius
                == DEFAULT_HEATMAP_DELTA_PROFILE.minimum_celsius
            )
            assert (
                profile.delta_maximum_celsius
                == DEFAULT_HEATMAP_DELTA_PROFILE.maximum_celsius
            )
            assert profile.effective_span_celsius >= 0.0
    assert motherboard is not None and motherboard.success
    assert len(motherboard.expected_target_paths) == 572
    assert set(motherboard.rendered_target_paths) == set(
        motherboard.expected_target_paths
    )
    assert not motherboard.foreign_rendered_target_paths
    assert chipset.success and len(chipset.expected_target_paths) == 1
    assert cpu_socket.success and len(cpu_socket.expected_target_paths) == 7
    assert vrm_east.success and len(vrm_east.expected_target_paths) == 2
    assert vrm_west.success and len(vrm_west.expected_target_paths) == 2
    assert nvme_a.success and len(nvme_a.expected_target_paths) == 2
    assert nvme_b.success and len(nvme_b.expected_target_paths) == 3
    assert combined.success and len(combined.expected_target_paths) == 597
    selected = nvme_b_telemetry.for_prim(nvme_b.expected_target_paths[0])
    hidden = nvme_b_telemetry.for_prim(motherboard.expected_target_paths[0])
    assert (selected.value, selected.unit, selected.quality) == (
        source_metric.value,
        source_metric.unit,
        source_metric.quality,
    )
    assert not hidden.available
    assert tuple(provider.latest_snapshot.metrics) == provider_metric_ids
    assert filtered is not None
    assert filtered.for_prim(combined.expected_target_paths[0]).available
    assert refreshed is not None and refreshed.metric_ids == ()
    assert filter_cleared
    assert controller.heatmap_semantic_registry_snapshot() is registry
    assert restored.success and not restored.enabled
    assert not controller.heatmap_binding_calibration_test_active()
    assert not controller.heatmap_binding_calibration_filter_active()
    assert stage.GetRootLayer().ExportToString() == root_before
    assert stage.GetSessionLayer().ExportToString() == session_before


def _without_metric(snapshot, metric_id: str):
    from digital_twin_runtime_suite.app.telemetry.model import TelemetrySnapshot

    metrics = dict(snapshot.metrics)
    metrics.pop(metric_id)
    return TelemetrySnapshot.create(
        schema_version=snapshot.schema_version,
        provider_id=snapshot.provider_id,
        provider_type=snapshot.provider_type,
        timestamp=snapshot.timestamp,
        operational_state=snapshot.operational_state,
        refresh_interval_s=snapshot.refresh_interval_s,
        metrics=metrics,
    )


def _gpu_metric(registry, instance: int, zone: str, component: str) -> str:
    return next(
        target.telemetry_binding.metric_id
        for target in registry.targets
        if (
            target.semantic_key.hardware.label == f"gpu_{instance}"
            and target.semantic_key.thermal_zone == zone
            and target.semantic_key.thermal_component == component
        )
    )


def _install_omni_usd_stage(monkeypatch, stage) -> None:
    class _Context:
        @staticmethod
        def get_stage():
            return stage

    omni_module = ModuleType("omni")
    omni_module.__path__ = []
    usd_module = ModuleType("omni.usd")
    usd_module.get_context = _Context
    omni_module.usd = usd_module
    monkeypatch.setitem(sys.modules, "omni", omni_module)
    monkeypatch.setitem(sys.modules, "omni.usd", usd_module)


def _runtime_config_path() -> Path:
    return Path(__file__).parents[2] / "configs" / "digital_twin_runtime_suite.toml"


def _telemetry_config_path() -> Path:
    return Path(__file__).parents[2] / "configs" / "telemetry_provider.toml"


def _production_asset_path() -> Path:
    return (
        Path(__file__).parents[2]
        / "assets"
        / "_external"
        / "usd"
        / "Blackwell_Rig_server_assembly.usd"
    )
