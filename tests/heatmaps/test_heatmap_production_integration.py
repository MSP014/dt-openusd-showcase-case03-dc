# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""Generic production-server Heatmap proof with no special FullServer mode."""

from __future__ import annotations

from pathlib import Path

import pytest

from digital_twin_runtime_suite.app.heatmaps.composition import (
    build_heatmap_composition_plan,
)
from digital_twin_runtime_suite.app.heatmaps.presentation import (
    build_heatmap_presentation_plan,
)
from digital_twin_runtime_suite.app.heatmaps.settings import (
    HeatmapSettings,
    HeatmapSettingsStore,
)


def test_generic_heatmaps_cover_the_production_server_and_restore_exactly(
    tmp_path,
) -> None:
    pytest.importorskip("pxr")
    from pxr import Usd, UsdGeom

    from digital_twin_runtime_suite.app.commands import RuntimeController
    from digital_twin_runtime_suite.app.telemetry.config import TelemetryConfig
    from digital_twin_runtime_suite.app.telemetry.provider import (
        SyntheticTelemetryProvider,
    )

    asset_path = _production_asset_path()
    if not asset_path.is_file():
        pytest.skip("Production Blackwell Rig USD is not hydrated locally.")
    stage = Usd.Stage.Open(str(asset_path))
    assert stage is not None
    controller = RuntimeController(_runtime_config_path())
    controller._heatmap_settings_store = HeatmapSettingsStore(
        tmp_path / "heatmap_settings.toml"
    )
    controller._heatmap_applied_settings = controller._heatmap_settings_store.load()
    controller._heatmap_stage = lambda: stage
    controller._ensure_heatmap_presentation_scheduler = lambda: None

    catalog = controller.prepare_heatmaps_for_open_stage()

    assert catalog is not None and catalog.ready
    assert catalog.preflight.valid_target_count == 1148
    all_settings = HeatmapSettings(isolation_selectors=catalog.selector_ids)
    selected = catalog.selected_targets(all_settings.isolation_selectors)
    assert len(selected) == len(catalog.targets) == 1148
    rack_only_rj45_paths = tuple(
        target.prim_path for target in selected if "/rj_45_male" in target.prim_path
    )
    assert len(rack_only_rj45_paths) == 2
    assert all(
        UsdGeom.Imageable(stage.GetPrimAtPath(path)).ComputeVisibility()
        == UsdGeom.Tokens.invisible
        for path in rack_only_rj45_paths
    )
    assert _metric_for(catalog, "gpu_1", "gpu_core", "gb203_die") == (
        "gpu_1_hotspot_temp_c"
    )
    assert _metric_for(catalog, "gpu_2", "vram", "memory_chip") == (
        "gpu_2_memory_temp_c"
    )
    assert _metric_for(catalog, "gpu_3", "vrm", "capacitor") == "gpu_3_temp_c"
    assert _ram_metric_ids(catalog) == {f"ram_{index}_temp_c" for index in range(1, 9)}

    telemetry_config = TelemetryConfig.load(_telemetry_config_path())
    provider = SyntheticTelemetryProvider(telemetry_config, seed=7)
    controller.configure_heatmap_telemetry_config(telemetry_config)
    controller.refresh_heatmap_telemetry_snapshot(provider.latest_snapshot)
    plan = build_heatmap_presentation_plan(
        catalog,
        all_settings,
        controller._heatmap_telemetry_snapshot,
        telemetry_config,
    )
    assert plan.selected_target_paths == tuple(target.prim_path for target in selected)
    assert plan.material_targets

    saved = controller.apply_heatmap_settings_in_kit(all_settings)
    root_before = stage.GetRootLayer().ExportToString()
    session_before = stage.GetSessionLayer().ExportToString()
    enabled = controller.test_heatmaps_in_kit()

    assert saved.success and not saved.enabled
    assert enabled.success and enabled.enabled
    assert all(
        UsdGeom.Imageable(stage.GetPrimAtPath(path)).ComputeVisibility()
        == UsdGeom.Tokens.invisible
        for path in rack_only_rj45_paths
    )
    restored = controller.restore_heatmap_test_in_kit()

    assert restored.success and not restored.enabled
    assert stage.GetRootLayer().ExportToString() == root_before
    assert stage.GetSessionLayer().ExportToString() == session_before


def test_production_gpu_housing_precedence_preserves_catalogued_targets(
    tmp_path,
) -> None:
    pytest.importorskip("pxr")
    from pxr import Usd

    from digital_twin_runtime_suite.app.commands import RuntimeController

    asset_path = _production_asset_path()
    if not asset_path.is_file():
        pytest.skip("Production Blackwell Rig USD is not hydrated locally.")
    stage = Usd.Stage.Open(str(asset_path))
    assert stage is not None
    controller = RuntimeController(_runtime_config_path())
    controller._heatmap_settings_store = HeatmapSettingsStore(
        tmp_path / "heatmap_settings.toml"
    )
    controller._heatmap_applied_settings = controller._heatmap_settings_store.load()
    controller._heatmap_stage = lambda: stage
    catalog = controller.prepare_heatmaps_for_open_stage()

    assert catalog is not None and catalog.ready
    settings = HeatmapSettings(
        isolation_selectors=("gpu_01_housing", "gpu_03_housing"),
        xray_overlay_group_ids=("gpu_shrouds",),
    )
    composition = build_heatmap_composition_plan(
        settings,
        catalog,
        controller.heatmap_xray_overlay_groups_snapshot(),
    )
    xray_paths = next(
        group.paths
        for group in controller.heatmap_xray_overlay_groups_snapshot()
        if group.group_id == "gpu_shrouds"
    )
    excluded = set(composition.xray_excluded_paths)
    heatmap_paths = set(composition.heatmap_target_paths)

    for gpu_index in (1, 3):
        selector_id = f"gpu_{gpu_index:02d}_housing"
        selected = catalog.selected_targets((selector_id,))
        shroud_and_blower = tuple(
            path
            for path in xray_paths
            if f"/gpu_{gpu_index:02d}/" in path
            and path.endswith(("/shroud", "/blower"))
        )
        assert shroud_and_blower
        assert set(shroud_and_blower) <= excluded
        assert selected
        for root in shroud_and_blower:
            root_targets = tuple(
                target
                for target in selected
                if target.prim_path == root or target.prim_path.startswith(f"{root}/")
            )
            assert root_targets
            assert all(target.prim_path in heatmap_paths for target in root_targets)
        assert all(target.prim_path in heatmap_paths for target in selected)
        assert all(selector_id in target.selector_ids for target in selected)
        assert all(
            catalog.registry.targets_by_prim_path[target.prim_path] is target.binding
            for target in selected
        )

    gpu_02_shroud_and_blower = {
        path
        for path in xray_paths
        if "/gpu_02/" in path and path.endswith(("/shroud", "/blower"))
    }
    unrelated_gpu_shroud_paths = {
        path
        for path in xray_paths
        if path.endswith(("/power", "/io/ports")) or "cables_gpu_" in path
    }
    assert gpu_02_shroud_and_blower
    assert not gpu_02_shroud_and_blower.intersection(excluded)
    assert all(
        target.prim_path not in heatmap_paths
        for target in catalog.selected_targets(("gpu_02_housing",))
    )
    assert not unrelated_gpu_shroud_paths.intersection(excluded)
    assert set(xray_paths).issubset(composition.visibility_target_paths)


def _metric_for(catalog, hardware: str, zone: str, component: str) -> str | None:
    return next(
        target.binding.telemetry_binding.metric_id
        for target in catalog.targets
        if (
            target.binding.semantic_key.hardware.label == hardware
            and target.binding.semantic_key.thermal_zone == zone
            and target.binding.semantic_key.thermal_component == component
        )
    )


def _ram_metric_ids(catalog) -> set[str]:
    return {
        target.binding.telemetry_binding.metric_id
        for target in catalog.targets
        if (
            target.binding.semantic_key.hardware.family == "ram"
            and target.binding.telemetry_binding.metric_id is not None
        )
    }


def _telemetry_config_path() -> Path:
    return Path(__file__).parents[2] / "configs" / "telemetry_provider.toml"


def _runtime_config_path() -> Path:
    return Path(__file__).parents[2] / "configs" / "digital_twin_runtime_suite.toml"


def _production_asset_path() -> Path:
    return (
        Path(__file__).parents[2]
        / "assets"
        / "_external"
        / "usd"
        / "Blackwell_Rig_server_assembly.usd"
    )
