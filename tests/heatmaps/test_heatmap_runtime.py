"""Focused Stage 10 tests for temporary motherboard-and-RAM isolation."""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

from digital_twin_runtime_suite.app.commands import RuntimeController
from digital_twin_runtime_suite.app.heatmaps.scalar import (
    DEFAULT_HEATMAP_DELTA_PROFILE,
)

PCB_PATH = "/blackwell_rig/compute/gpu_03/geo/render/RTX4500/pcb"
MOTHERBOARD_PATH = "/blackwell_rig/motherboard"
RAM_MODULE_PATHS = tuple(
    f"/blackwell_rig/ram/ram_{instance:02d}" for instance in range(1, 9)
)
CPU_COOLER_RENDER_PATH = "/blackwell_rig/cpu_cooler/geo/render/cpu_cooler"
CPU_COOLER_FAN_PATH = f"{CPU_COOLER_RENDER_PATH}/cpu_fan"
CPU_COOLER_FAN_GPRIM_PATH = f"{CPU_COOLER_FAN_PATH}/blades"
CPU_COOLER_THERMAL_PATHS = (
    f"{CPU_COOLER_RENDER_PATH}/cpu_radiator",
    f"{CPU_COOLER_RENDER_PATH}/cooler_base",
)
GPU_PCB_PATHS = tuple(
    f"/blackwell_rig/compute/gpu_{instance:02d}/geo/render/RTX4500/pcb"
    for instance in (1, 2, 3)
)
NIC_RENDER_PATH = "/blackwell_rig/connectx_7/geo/render/connectx_7"
PSU_PATH = "/blackwell_rig/power/psu"
PSU_THERMAL_PATH = f"{PSU_PATH}/geo/render/psu/internal_components/main_coil/main_coil"
PSU_IGNORED_PATH = f"{PSU_PATH}/geo/render/psu/internal_components/ignored"
GPU_PLUG_PATHS = tuple(
    f"/blackwell_rig/compute/gpu_{instance:02d}/geo/render/RTX4500/io/"
    f"plug_{plug:02d}"
    for instance in (1, 2, 3)
    for plug in range(1, 5)
)
GPU_EXTERNAL_PATHS = tuple(
    path
    for instance in (1, 2, 3)
    for path in (
        f"/blackwell_rig/compute/gpu_{instance:02d}/geo/render/RTX4500/blower",
        f"/blackwell_rig/compute/gpu_{instance:02d}/geo/render/RTX4500/shroud",
    )
)
MOTHERBOARD_RAM_COOLER_TARGET_PATHS = (
    MOTHERBOARD_PATH,
    *RAM_MODULE_PATHS,
    *CPU_COOLER_THERMAL_PATHS,
    *GPU_PCB_PATHS,
    *GPU_PLUG_PATHS,
    *GPU_EXTERNAL_PATHS,
    PSU_THERMAL_PATH,
    NIC_RENDER_PATH,
)


def test_motherboard_and_ram_targets_isolate_the_required_view(tmp_path, monkeypatch):
    """The demo preserves motherboard plus eight DIMMs and hides other hardware."""

    from pxr import Sdf, Usd, UsdGeom

    controller = RuntimeController(_write_runtime_config(tmp_path))
    stage = _heatmap_test_stage(Usd, UsdGeom)
    _add_thermal_mesh(stage, "/blackwell_rig/motherboard/thermal_probe")
    _install_omni_usd_stage(monkeypatch, stage)
    root_before = stage.GetRootLayer().ExportToString()

    result = controller.set_heatmap_test_isolation_in_kit(True)

    assert result.success
    assert result.enabled
    assert result.target_path == MOTHERBOARD_PATH
    assert result.target_paths == MOTHERBOARD_RAM_COOLER_TARGET_PATHS
    assert result.focus_evidence is not None
    assert result.focus_evidence.ready
    assert result.focus_evidence.motherboard_visible
    assert result.focus_evidence.ram_module_paths == RAM_MODULE_PATHS
    assert result.focus_evidence.visible_ram_module_paths == RAM_MODULE_PATHS
    assert result.focus_evidence.cpu_cooler_render_paths == CPU_COOLER_THERMAL_PATHS
    assert (
        result.focus_evidence.visible_cpu_cooler_render_paths
        == CPU_COOLER_THERMAL_PATHS
    )
    assert result.focus_evidence.cpu_cooler_fan_path == CPU_COOLER_FAN_PATH
    assert result.focus_evidence.cpu_cooler_fan_hidden
    assert result.focus_evidence.gpu_internal_paths == GPU_PCB_PATHS
    assert result.focus_evidence.visible_gpu_internal_paths == GPU_PCB_PATHS
    assert result.focus_evidence.gpu_plug_paths == GPU_PLUG_PATHS
    assert result.focus_evidence.visible_gpu_plug_paths == GPU_PLUG_PATHS
    assert set(GPU_EXTERNAL_PATHS).issubset(result.target_paths)
    assert PSU_THERMAL_PATH in result.target_paths
    assert PSU_IGNORED_PATH not in result.target_paths
    assert result.focus_evidence.nic_render_path == NIC_RENDER_PATH
    assert result.focus_evidence.nic_visible
    assert result.focus_evidence.unrelated_server_hardware_hidden
    assert result.focus_evidence.outside_server_visibility_untouched
    assert result.preflight is not None
    assert result.preflight.root_path == "/blackwell_rig"
    assert result.preflight.success
    assert result.preflight.valid_target_count == 20
    assert stage.GetRootLayer().ExportToString() == root_before
    assert controller.HEATMAP_TEST_ISOLATION_OWNER == "heatmap_test_isolation"
    assert controller.heatmap_test_isolation_active()
    assert (
        str(Sdf.Path(f"{MOTHERBOARD_PATH}.visibility")) in result.owned_visibility_paths
    )
    for path in (
        "/blackwell_rig",
        MOTHERBOARD_PATH,
        *RAM_MODULE_PATHS,
        *CPU_COOLER_THERMAL_PATHS,
        *GPU_PCB_PATHS,
        *GPU_PLUG_PATHS,
        *GPU_EXTERNAL_PATHS,
        PSU_THERMAL_PATH,
        NIC_RENDER_PATH,
    ):
        assert _computed_visibility(stage, path, UsdGeom) == UsdGeom.Tokens.inherited
    assert _computed_visibility(stage, CPU_COOLER_FAN_GPRIM_PATH, UsdGeom) == (
        UsdGeom.Tokens.invisible
    )
    assert (
        _computed_visibility(stage, "/studio_lights", UsdGeom)
        == UsdGeom.Tokens.inherited
    )
    assert _computed_visibility(stage, "/blackwell_rig/power", UsdGeom) == (
        UsdGeom.Tokens.inherited
    )
    assert _computed_visibility(stage, PSU_IGNORED_PATH, UsdGeom) == (
        UsdGeom.Tokens.invisible
    )
    assert _session_visibility_default(stage, MOTHERBOARD_PATH, Sdf) == "inherited"
    assert _session_visibility_default(stage, "/blackwell_rig", Sdf) is None
    assert _session_visibility_default(stage, "/studio_lights", Sdf) is None


def test_preflight_failure_does_not_block_the_motherboard_ram_sandbox(
    tmp_path,
    monkeypatch,
):
    """Metadata defects remain visible while renderer work continues in the sandbox."""

    from pxr import Sdf, Usd, UsdGeom

    controller = RuntimeController(_write_runtime_config(tmp_path))
    stage = _heatmap_test_stage(Usd, UsdGeom)
    partial = UsdGeom.Mesh.Define(stage, "/blackwell_rig/motherboard/partial")
    partial.GetPrim().CreateAttribute(
        "thermal_zone",
        Sdf.ValueTypeNames.Token,
        custom=True,
    ).Set("motherboard")
    _install_omni_usd_stage(monkeypatch, stage)

    result = controller.set_heatmap_test_isolation_in_kit(True)

    assert result.success
    assert result.preflight is not None
    assert not result.preflight.success
    assert (
        result.preflight.diagnostics[0].prim_path
        == "/blackwell_rig/motherboard/partial"
    )


def test_isolation_does_not_change_visibility_outside_server_root(
    tmp_path,
    monkeypatch,
):
    """Lighting and runtime Session visibility stays outside the feature boundary."""

    from pxr import Sdf, Usd, UsdGeom

    controller = RuntimeController(_write_runtime_config(tmp_path))
    stage = _heatmap_test_stage(Usd, UsdGeom)
    _set_session_visibility(stage, "/studio_lights", UsdGeom.Tokens.invisible)
    _set_session_visibility(stage, "/DTRS_Runtime", UsdGeom.Tokens.inherited)
    outside_prior = {
        path: _session_visibility_default(stage, path, Sdf)
        for path in ("/studio_lights", "/DTRS_Runtime")
    }
    _install_omni_usd_stage(monkeypatch, stage)

    result = controller.set_heatmap_test_isolation_in_kit(True)

    assert result.success
    assert {
        path: _session_visibility_default(stage, path, Sdf) for path in outside_prior
    } == outside_prior
    assert all(
        property_path.startswith("/blackwell_rig/")
        for property_path in result.owned_visibility_paths
    )
    assert _session_visibility_default(stage, "/blackwell_rig", Sdf) is None


def test_missing_ram_assembly_fails_without_session_mutation(tmp_path, monkeypatch):
    """A deterministic target failure must not leave partial visibility opinions."""

    from pxr import Usd, UsdGeom

    controller = RuntimeController(_write_runtime_config(tmp_path))
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.Xform.Define(stage, "/blackwell_rig")
    _install_omni_usd_stage(monkeypatch, stage)
    before = stage.GetSessionLayer().ExportToString()

    result = controller.set_heatmap_test_isolation_in_kit(True)

    assert not result.success
    assert not result.enabled
    assert (
        result.message
        == "Heatmap test isolation RAM assembly is unavailable: /blackwell_rig/ram."
    )
    assert stage.GetSessionLayer().ExportToString() == before
    assert not controller.heatmap_test_isolation_active()


def test_repeated_enable_is_idempotent(tmp_path, monkeypatch):
    """A second enable owns no additional visibility state or USD mutations."""

    from pxr import Usd, UsdGeom

    controller = RuntimeController(_write_runtime_config(tmp_path))
    stage = _heatmap_test_stage(Usd, UsdGeom)
    _install_omni_usd_stage(monkeypatch, stage)

    first = controller.set_heatmap_test_isolation_in_kit(True)
    after_first = stage.GetSessionLayer().ExportToString()
    second = controller.set_heatmap_test_isolation_in_kit(True)

    assert first.success and second.success
    assert second.message == "Heatmap test isolation is already enabled."
    assert second.owned_visibility_paths == first.owned_visibility_paths
    assert stage.GetSessionLayer().ExportToString() == after_first


def test_disable_restores_exact_preexisting_visibility_state(tmp_path, monkeypatch):
    """Pre-existing hidden and explicitly visible Session opinions survive a cycle."""

    from pxr import Sdf, Usd, UsdGeom

    controller = RuntimeController(_write_runtime_config(tmp_path))
    stage = _heatmap_test_stage(Usd, UsdGeom)
    _set_session_visibility(
        stage,
        "/blackwell_rig/compute/gpu_02",
        UsdGeom.Tokens.inherited,
    )
    _set_session_visibility(
        stage,
        "/blackwell_rig/power",
        UsdGeom.Tokens.invisible,
    )
    prior = {
        path: _session_visibility_default(stage, path, Sdf)
        for path in (
            "/blackwell_rig/compute/gpu_02",
            "/blackwell_rig/power",
        )
    }
    _install_omni_usd_stage(monkeypatch, stage)

    enabled = controller.set_heatmap_test_isolation_in_kit(True)
    disabled = controller.set_heatmap_test_isolation_in_kit(False)
    disabled_again = controller.set_heatmap_test_isolation_in_kit(False)

    assert enabled.success
    assert disabled.success
    assert disabled_again.success
    assert disabled_again.message == "Heatmap test isolation is already disabled."
    assert not controller.heatmap_test_isolation_active()
    assert {
        path: _session_visibility_default(stage, path, Sdf) for path in prior
    } == prior
    assert _session_visibility_default(stage, PCB_PATH, Sdf) is None


def test_reload_or_shutdown_cleanup_leaves_no_feature_visibility_opinions(
    tmp_path,
    monkeypatch,
):
    """The public cleanup entry point restores all feature-owned Session state."""

    from pxr import Sdf, Usd, UsdGeom

    controller = RuntimeController(_write_runtime_config(tmp_path))
    stage = _heatmap_test_stage(Usd, UsdGeom)
    _set_session_visibility(
        stage,
        "/blackwell_rig/compute/gpu_02",
        UsdGeom.Tokens.invisible,
    )
    prior = {
        "/blackwell_rig/compute/gpu_02": _session_visibility_default(
            stage,
            "/blackwell_rig/compute/gpu_02",
            Sdf,
        ),
        "/blackwell_rig/power": _session_visibility_default(
            stage,
            "/blackwell_rig/power",
            Sdf,
        ),
    }
    _install_omni_usd_stage(monkeypatch, stage)

    enabled = controller.set_heatmap_test_isolation_in_kit(True)
    cleanup = controller.clear_heatmap_test_isolation_in_kit()

    assert enabled.success
    assert cleanup.success
    assert not cleanup.enabled
    assert controller._heatmap_test_isolation_visibility_snapshots == {}
    assert not controller.heatmap_test_isolation_active()
    assert {
        path: _session_visibility_default(stage, path, Sdf) for path in prior
    } == prior
    for property_path in enabled.owned_visibility_paths:
        if property_path not in {
            "/blackwell_rig/compute/gpu_02.visibility",
        }:
            assert (
                stage.GetSessionLayer().GetPropertyAtPath(Sdf.Path(property_path))
                is None
            )


def test_registry_refreshes_telemetry_without_rebuilding_or_presenting_usd(
    tmp_path,
    monkeypatch,
):
    """Workload changes values only; semantic and Session state stay stable."""

    from datetime import datetime, timedelta, timezone

    from pxr import Usd, UsdGeom

    controller = RuntimeController(_write_runtime_config(tmp_path))
    stage = _heatmap_test_stage(Usd, UsdGeom)
    gpu_paths = tuple(
        f"/blackwell_rig/compute/gpu_{index:02d}/geo/render/RTX4500/pcb/die"
        for index in (1, 2, 3)
    )
    for path in gpu_paths:
        _add_thermal_mesh(stage, path, zone="gpu_core", component="gb203_die")
    _add_thermal_mesh(
        stage,
        "/blackwell_rig/cpu_cooler/geo/render/coldplate",
        zone="cpu_cooler_coldplate",
        component="coldplate",
    )
    _add_thermal_mesh(
        stage,
        "/blackwell_rig/connectx_7/geo/render/pcb",
        zone="nic_board",
        component="pcb",
    )
    _add_thermal_mesh(
        stage,
        "/blackwell_rig/power/psu/geo/render/coil",
        zone="psu_coils",
        component="coil",
    )
    started_at = datetime(2026, 8, 21, tzinfo=timezone.utc)
    controller.refresh_heatmap_telemetry_snapshot(
        _telemetry_snapshot(started_at, gpu_1_hotspot_temp_c=41.0)
    )
    _install_omni_usd_stage(monkeypatch, stage)

    result = controller.set_heatmap_test_isolation_in_kit(True)
    registry = result.registry
    first_values = result.telemetry
    session_after_isolation = stage.GetSessionLayer().ExportToString()
    controller.refresh_heatmap_telemetry_snapshot(
        _telemetry_snapshot(
            started_at + timedelta(seconds=1),
            gpu_1_hotspot_temp_c=88.0,
        )
    )
    second_values = controller.heatmap_telemetry_binding_snapshot()

    assert result.success and result.preflight.success
    assert registry.success
    assert registry.target_count == 25
    assert registry.for_prim(gpu_paths[0]).telemetry_binding.metric_id == (
        "gpu_1_hotspot_temp_c"
    )
    assert registry.for_prim(gpu_paths[1]).telemetry_binding.metric_id == (
        "gpu_2_hotspot_temp_c"
    )
    assert registry.for_prim(gpu_paths[2]).telemetry_binding.metric_id == (
        "gpu_3_hotspot_temp_c"
    )
    assert first_values.for_prim(gpu_paths[0]).value == 41.0
    assert second_values.for_prim(gpu_paths[0]).value == 88.0
    assert second_values.for_prim(gpu_paths[0]).quality == "measured"
    assert (
        controller.heatmap_semantic_registry_snapshot().fingerprint
        == registry.fingerprint
    )
    assert stage.GetSessionLayer().ExportToString() == session_after_isolation


def test_gpu03_pcb_slice_uses_all_channels_and_session_material_only(
    tmp_path,
    monkeypatch,
):
    """GPU03 die, VRAM and VRM retain independent Session presentations."""

    from datetime import datetime, timedelta, timezone

    from pxr import Usd, UsdGeom

    from digital_twin_runtime_suite.app.telemetry.config import TelemetryConfig

    controller = RuntimeController(_write_runtime_config(tmp_path))
    telemetry_config = TelemetryConfig.load(_provider_config_path())
    controller.configure_heatmap_telemetry_config(telemetry_config)
    stage = _heatmap_test_stage(Usd, UsdGeom)
    die_path = f"{PCB_PATH}/trace_a"
    vram_path = f"{PCB_PATH}/trace_b"
    vrm_path = f"{PCB_PATH}/vrm"
    unavailable_path = f"{PCB_PATH}/blower"
    _add_thermal_mesh(
        stage,
        die_path,
        zone="gpu_core",
        component="gb203_die",
        preview=(64.0, 74.0),
    )
    _add_thermal_mesh(
        stage,
        vram_path,
        zone="vram",
        component="memory_chip",
        preview=(56.0, 61.0),
    )
    _add_thermal_mesh(
        stage,
        vrm_path,
        zone="vrm",
        component="choke",
        preview=(48.0, 53.0),
    )
    _add_thermal_mesh(
        stage,
        unavailable_path,
        zone="gpu_cooling",
        component="blower",
        preview=(40.0, 45.0),
    )
    started_at = datetime(2026, 8, 21, tzinfo=timezone.utc)
    controller.refresh_heatmap_telemetry_snapshot(
        _telemetry_snapshot(started_at, gpu_1_hotspot_temp_c=41.0)
    )
    _install_omni_usd_stage(monkeypatch, stage)
    root_before = stage.GetRootLayer().ExportToString()

    isolation = controller.set_heatmap_test_isolation_in_kit(True)
    enabled = controller.enable_heatmap_vertical_slice_in_kit()
    controller.refresh_heatmap_telemetry_snapshot(
        _telemetry_snapshot(
            started_at + timedelta(seconds=1),
            gpu_1_hotspot_temp_c=41.0,
            gpu_3_temp_c=88.0,
            gpu_3_hotspot_temp_c=100.0,
            gpu_3_memory_temp_c=90.0,
        )
    )
    refreshed = controller.heatmap_vertical_slice_snapshot()
    disabled = controller.set_heatmap_test_isolation_in_kit(False)

    assert isolation.success and isolation.vertical_slice.success
    assert isolation.vertical_slice.target_paths == (
        unavailable_path,
        die_path,
        vram_path,
        vrm_path,
    )
    assert not isolation.vertical_slice.unavailable_target_paths
    assert enabled.success and enabled.enabled
    assert refreshed.success and refreshed.enabled
    assert refreshed.material_creations == 4
    assert refreshed.parameter_updates >= 1
    assert not refreshed.unavailable_target_paths
    assert disabled.success and disabled.vertical_slice.success
    assert stage.GetRootLayer().ExportToString() == root_before
    assert not stage.GetPrimAtPath("/DTRS_Runtime/Heatmaps/Gpu03").IsValid()


def test_production_gpu03_pcb_contract_covers_all_documented_channels(
    tmp_path,
    monkeypatch,
):
    """The production demo resolves three independent 1/8/51 GPU matrices."""

    from collections import Counter

    from pxr import Usd

    from digital_twin_runtime_suite.app.telemetry.config import TelemetryConfig
    from digital_twin_runtime_suite.app.telemetry.provider import (
        SyntheticTelemetryProvider,
    )

    controller = RuntimeController(_write_runtime_config(tmp_path))
    telemetry_config = TelemetryConfig.load(_provider_config_path())
    provider = SyntheticTelemetryProvider(telemetry_config, seed=7)
    controller.configure_heatmap_telemetry_config(telemetry_config)
    controller.refresh_heatmap_telemetry_snapshot(provider.latest_snapshot)
    stage = Usd.Stage.Open(str(_production_asset_path()))
    _install_omni_usd_stage(monkeypatch, stage)
    root_before = stage.GetRootLayer().ExportToString()

    result = controller.set_heatmap_test_isolation_in_kit(True)
    contract = controller.heatmap_vertical_slice_contract_snapshot()
    gradient_audit = controller.heatmap_gpu03_gradient_audit_snapshot()
    full_server_contract = controller.heatmap_full_server_contract_snapshot()
    cleanup = controller.set_heatmap_test_isolation_in_kit(False)

    assert result.success and result.preflight.success
    assert result.focus_evidence is not None
    psu_target_paths = tuple(
        path for path in result.target_paths if path.startswith(f"{PSU_PATH}/")
    )
    assert len(psu_target_paths) == 26
    gpu_external_paths = tuple(
        path
        for path in result.target_paths
        if path.startswith("/blackwell_rig/compute/")
        and path not in GPU_PCB_PATHS
        and path not in result.focus_evidence.gpu_plug_paths
    )
    assert len(gpu_external_paths) == 60
    assert result.target_paths == (
        MOTHERBOARD_PATH,
        *RAM_MODULE_PATHS,
        *CPU_COOLER_THERMAL_PATHS,
        *GPU_PCB_PATHS,
        *result.focus_evidence.gpu_plug_paths,
        *gpu_external_paths,
        *psu_target_paths,
        NIC_RENDER_PATH,
    )
    assert result.focus_evidence.ready
    assert len(result.focus_evidence.gpu_plug_paths) == 12
    assert all(
        "/geo/render/RTX4500/io/" in path
        for path in result.focus_evidence.gpu_plug_paths
    )
    assert result.focus_evidence.ram_module_paths == RAM_MODULE_PATHS
    assert result.registry is not None
    ram_bindings = tuple(
        target
        for target in result.registry.targets
        if target.prim_path.startswith("/blackwell_rig/ram/")
    )
    assert len(ram_bindings) == 248
    for instance in range(1, 9):
        bindings = tuple(
            target
            for target in ram_bindings
            if target.semantic_key.hardware.instance == instance
        )
        assert len(bindings) == 31
        assert {target.telemetry_binding.metric_id for target in bindings} == {
            f"ram_{instance}_temp_c"
        }
    assert result.full_server is not None
    assert result.full_server.success and result.full_server.enabled
    assert len(result.full_server.rendered_target_paths) == 1148
    assert all(
        path.startswith(
            (
                MOTHERBOARD_PATH,
                "/blackwell_rig/ram/",
                CPU_COOLER_RENDER_PATH,
                *GPU_PCB_PATHS,
                *result.focus_evidence.gpu_plug_paths,
                *gpu_external_paths,
                PSU_PATH,
                NIC_RENDER_PATH,
            )
        )
        for path in result.full_server.rendered_target_paths
    )
    assert all(
        not path.startswith(CPU_COOLER_FAN_PATH)
        for path in result.full_server.rendered_target_paths
    )
    assert set(result.focus_evidence.gpu_plug_paths).issubset(
        result.full_server.rendered_target_paths
    )
    assert set(gpu_external_paths).issubset(result.full_server.rendered_target_paths)
    assert set(psu_target_paths).issubset(result.full_server.rendered_target_paths)
    assert full_server_contract is not None
    psu_targets = tuple(
        target
        for target in full_server_contract.renderable_targets
        if target.prim_path.startswith(f"{PSU_PATH}/")
    )
    assert len(psu_targets) == 26
    psu_semantics = {
        (target.semantic_key.thermal_zone, target.semantic_key.thermal_component)
        for target in psu_targets
    }
    assert len(psu_semantics) == 11
    assert all(
        profile == DEFAULT_HEATMAP_DELTA_PROFILE
        for target in psu_targets
        for profile in target.delta_profiles.values()
    )
    expected_psu_corrections = {
        ("psu_main_radiator", "radiator"): 16.0,
        ("psu_small_radiator", "radiator"): 4.0,
    }
    assert all(
        target.presentation_temperature_offset_celsius
        == expected_psu_corrections.get(
            (
                target.semantic_key.thermal_zone,
                target.semantic_key.thermal_component,
            ),
            0.0,
        )
        for target in psu_targets
    )
    assert contract is not None
    assert len(contract.targets) == 180
    for instance in (1, 2, 3):
        targets = tuple(
            target
            for target in contract.targets
            if target.semantic_key.hardware.instance == instance
        )
        assert Counter(target.metric_id for target in targets) == {
            f"gpu_{instance}_hotspot_temp_c": 1,
            f"gpu_{instance}_memory_temp_c": 8,
            f"gpu_{instance}_temp_c": 51,
        }
    assert sum(item.target_count for item in gradient_audit) == 180
    assert all(item.weight_minimum <= item.weight_maximum for item in gradient_audit)
    assert all(
        item.delta_minimum_celsius[0] <= item.delta_minimum_celsius[1]
        and item.delta_maximum_celsius[0] <= item.delta_maximum_celsius[1]
        and item.effective_display_span_celsius >= 0.0
        and item.variation
        for item in gradient_audit
    )
    assert not contract.unavailable_target_paths
    assert round(contract.scale_resolution.scale.minimum, 2) == 26.0
    assert contract.scale_resolution.scale.maximum == 108.0
    assert all(
        profile.minimum_celsius <= profile.maximum_celsius
        for target in contract.targets
        for profile in target.delta_profiles.values()
    )
    assert all(
        profile == DEFAULT_HEATMAP_DELTA_PROFILE
        for target in contract.targets
        for profile in target.delta_profiles.values()
    )
    assert cleanup.success
    assert stage.GetRootLayer().ExportToString() == root_before


def _telemetry_snapshot(
    timestamp,
    *,
    gpu_1_hotspot_temp_c: float,
    gpu_3_temp_c: float = 43.0,
    gpu_3_hotspot_temp_c: float = 46.0,
    gpu_3_memory_temp_c: float = 48.0,
):
    from digital_twin_runtime_suite.app.telemetry.model import (
        MetricValue,
        TelemetrySnapshot,
    )

    return TelemetrySnapshot.create(
        schema_version="1",
        provider_id="test",
        provider_type="test",
        timestamp=timestamp,
        operational_state="Idle",
        refresh_interval_s=1,
        metrics={
            "gpu_1_hotspot_temp_c": MetricValue(
                gpu_1_hotspot_temp_c,
                "°C",
                "measured",
            ),
            "gpu_2_hotspot_temp_c": MetricValue(42.0, "°C", "estimated"),
            "gpu_3_hotspot_temp_c": MetricValue(
                gpu_3_hotspot_temp_c,
                "°C",
                "derived",
            ),
            "gpu_3_memory_temp_c": MetricValue(
                gpu_3_memory_temp_c,
                "°C",
                "estimated",
            ),
            "gpu_3_temp_c": MetricValue(gpu_3_temp_c, "°C", "derived"),
            "cpu_temp_c": MetricValue(70.0, "°C", "synthetic"),
            "nic_temp_c": MetricValue(64.0, "°C", "stale"),
            "psu_temp_estimate_c": MetricValue(52.0, "°C", "estimated"),
        },
    )


def test_focused_gpu_exterior_targets_override_xray_presentation_suppression(
    tmp_path,
    monkeypatch,
):
    """Focused Test Heatmaps renders selected GPU exterior targets despite X-Ray."""

    from pxr import Usd, UsdShade

    from digital_twin_runtime_suite.app.telemetry.config import TelemetryConfig
    from digital_twin_runtime_suite.app.telemetry.provider import (
        SyntheticTelemetryProvider,
    )

    config_path = (
        Path(__file__).parents[2] / "configs" / "digital_twin_runtime_suite.toml"
    )
    controller = RuntimeController(config_path)
    telemetry_config = TelemetryConfig.load(_provider_config_path())
    provider = SyntheticTelemetryProvider(telemetry_config, seed=7)
    controller.configure_heatmap_telemetry_config(telemetry_config)
    controller.refresh_heatmap_telemetry_snapshot(provider.latest_snapshot)
    stage = Usd.Stage.Open(str(_production_asset_path()))
    session_before = stage.GetSessionLayer().ExportToString()
    _install_omni_usd_stage(monkeypatch, stage)

    result = controller.set_heatmap_test_isolation_in_kit(True)

    assert result.success and result.full_server is not None
    assert result.preflight is not None and result.registry is not None
    xray_exterior_paths = tuple(
        path
        for path in result.preflight.xray_overlap_targets
        if path.startswith("/blackwell_rig/compute/gpu_")
        and (
            result.registry.targets_by_prim_path[path].semantic_key.thermal_zone,
            result.registry.targets_by_prim_path[path].semantic_key.thermal_component,
        )
        in controller.HEATMAP_GPU_EXTERNAL_SEMANTICS
    )
    assert len(xray_exterior_paths) == 42
    assert set(xray_exterior_paths).issubset(result.full_server.rendered_target_paths)
    xray_material_keys = {
        result.registry.targets_by_prim_path[path].semantic_key
        for path in xray_exterior_paths
    }
    full_server_contract = controller.heatmap_full_server_contract_snapshot()
    assert full_server_contract is not None
    expected_material_keys = {
        target.material_key
        for target in full_server_contract.xray_precedence_targets
        if target.semantic_key in xray_material_keys
    }
    assert expected_material_keys.issubset(
        controller._full_server_group_telemetry_values()
    )
    for path in xray_exterior_paths:
        material, relation = UsdShade.MaterialBindingAPI(
            stage.GetPrimAtPath(path)
        ).ComputeBoundMaterial()
        assert str(material.GetPath()).startswith("/DTRS_Runtime/Heatmaps/FullServer/")
        assert str(relation.GetPath()) == f"{path}.material:binding"

    restored = controller.set_heatmap_test_isolation_in_kit(False)

    assert restored.success
    assert stage.GetSessionLayer().ExportToString() == session_before


def _heatmap_test_stage(Usd, UsdGeom):
    stage = Usd.Stage.CreateInMemory()
    for path in (
        "/studio_lights",
        "/DTRS_Runtime",
        MOTHERBOARD_PATH,
        *RAM_MODULE_PATHS,
        CPU_COOLER_FAN_GPRIM_PATH,
        *CPU_COOLER_THERMAL_PATHS,
        NIC_RENDER_PATH,
        "/blackwell_rig/power",
        "/blackwell_rig/compute/gpu_02",
        "/blackwell_rig/compute/gpu_03/cooling",
        "/blackwell_rig/compute/gpu_03/geo/debug",
        "/blackwell_rig/compute/gpu_03/geo/render/cables",
        "/blackwell_rig/compute/gpu_03/geo/render/RTX4500/power",
    ):
        UsdGeom.Xform.Define(stage, path)
    for target in GPU_PCB_PATHS:
        UsdGeom.Mesh.Define(stage, f"{target}/trace_a")
        UsdGeom.Mesh.Define(stage, f"{target}/trace_b")
    _add_thermal_mesh(
        stage,
        PSU_THERMAL_PATH,
        zone="psu_coils",
        component="coil",
        preview=(45.0, 50.0),
    )
    _add_thermal_mesh(
        stage,
        PSU_IGNORED_PATH,
        zone="ignore",
        component="ignore",
    )
    for path in GPU_PLUG_PATHS:
        _add_thermal_mesh(
            stage,
            path,
            zone="gpu_body",
            component="plug",
            preview=(45.0, 47.0),
        )
    for path in GPU_EXTERNAL_PATHS:
        semantic = (
            ("gpu_body", "shroud")
            if path.endswith("/shroud")
            else ("gpu_cooling", "blower")
        )
        _add_thermal_mesh(
            stage,
            path,
            zone=semantic[0],
            component=semantic[1],
            preview=(45.0, 47.0),
        )
    return stage


def _add_thermal_mesh(
    stage,
    path: str,
    *,
    zone: str = "motherboard",
    component: str = "passive",
    preview: tuple[float, ...] | None = None,
) -> None:
    from pxr import Sdf, UsdGeom, Vt

    prim = UsdGeom.Mesh.Define(stage, path).GetPrim()
    prim.CreateAttribute("thermal_zone", Sdf.ValueTypeNames.Token, custom=True).Set(
        zone
    )
    prim.CreateAttribute(
        "thermal_component",
        Sdf.ValueTypeNames.Token,
        custom=True,
    ).Set(component)
    UsdGeom.PrimvarsAPI(prim).CreatePrimvar(
        "thermal_weight",
        Sdf.ValueTypeNames.FloatArray,
        UsdGeom.Tokens.vertex,
    ).Set(Vt.FloatArray((0.25, 0.75)))
    if preview is not None:
        UsdGeom.PrimvarsAPI(prim).CreatePrimvar(
            "temperature_preview",
            Sdf.ValueTypeNames.FloatArray,
            UsdGeom.Tokens.vertex,
        ).Set(Vt.FloatArray(preview))


def _computed_visibility(stage, path: str, UsdGeom):
    return UsdGeom.Imageable(stage.GetPrimAtPath(path)).ComputeVisibility()


def _set_session_visibility(stage, path: str, visibility) -> None:
    from pxr import UsdGeom

    previous_target = stage.GetEditTarget()
    stage.SetEditTarget(stage.GetSessionLayer())
    try:
        UsdGeom.Imageable(stage.GetPrimAtPath(path)).CreateVisibilityAttr().Set(
            visibility
        )
    finally:
        stage.SetEditTarget(previous_target)


def _session_visibility_default(stage, path: str, Sdf):
    spec = stage.GetSessionLayer().GetPropertyAtPath(Sdf.Path(f"{path}.visibility"))
    return spec.default if spec else None


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


def _write_runtime_config(tmp_path) -> Path:
    config_path = tmp_path / "dtrs.toml"
    config_path.write_text(
        "\n".join(
            (
                "[app]",
                'name = "DTRS"',
                'version = "0.4.0"',
                "",
                "[paths]",
                'app_root = "src/digital_twin_runtime_suite"',
                'asset_root = "assets"',
                "",
                "[assets]",
                'default_asset_id = "server"',
                "",
                "[assets.entries.server]",
                'label = "Server"',
                'path = "server.usd"',
                'kind = "usd_stage"',
            )
        ),
        encoding="utf-8",
    )
    return config_path


def _provider_config_path() -> Path:
    return Path(__file__).parents[2] / "configs" / "telemetry_provider.toml"


def _production_asset_path() -> Path:
    return (
        Path(__file__).parents[2]
        / "assets"
        / "_external"
        / "usd"
        / "Blackwell_Rig_server_assembly.usd"
    )
