# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""Stage-discovery catalogue coverage without specialized Heatmap modes."""

from __future__ import annotations

from digital_twin_runtime_suite.app.heatmaps.catalog import (
    build_heatmap_catalog_from_preflight,
)
from digital_twin_runtime_suite.app.heatmaps.discovery import (
    PROPERTY_VALUE,
    ThermalPrimMetadata,
)
from digital_twin_runtime_suite.app.heatmaps.preflight import (
    HeatmapAssetPreflightResult,
)


def test_catalog_exposes_all_selectors_and_independent_gpu_scope_membership() -> None:
    catalog = build_heatmap_catalog_from_preflight(_preflight(_all_targets()))

    assert catalog.selector_ids == (
        "motherboard",
        "connectx_7",
        "gpu_01_internals",
        "gpu_01_housing",
        "gpu_02_internals",
        "gpu_02_housing",
        "gpu_03_internals",
        "gpu_03_housing",
        "cpu_cooler",
        "ram",
        "psu",
    )
    internals = catalog.selected_targets(("gpu_01_internals",))
    housing = catalog.selected_targets(("gpu_01_housing",))
    both = catalog.selected_targets(("gpu_01_internals", "gpu_01_housing"))

    assert len(internals) == 1
    assert len(housing) == 2
    assert {target.prim_path for target in both} == {
        *(target.prim_path for target in internals),
        *(target.prim_path for target in housing),
    }
    assert len(catalog.selected_targets(catalog.selector_ids)) == len(catalog.targets)
    gpu_01_internals = next(
        selector
        for selector in catalog.selectors
        if selector.selector_id == "gpu_01_internals"
    )
    gpu_01_housing = next(
        selector
        for selector in catalog.selectors
        if selector.selector_id == "gpu_01_housing"
    )

    assert (
        gpu_01_internals.label,
        gpu_01_internals.parent_id,
        gpu_01_internals.parent_label,
    ) == ("Internals", "gpu_01", "GPU 01")
    assert (
        gpu_01_housing.label,
        gpu_01_housing.parent_id,
        gpu_01_housing.parent_label,
    ) == ("Housing", "gpu_01", "GPU 01")


def test_catalog_keeps_motherboard_dimms_individual_and_physical_ram_shared() -> None:
    catalog = build_heatmap_catalog_from_preflight(_preflight(_all_targets()))
    motherboard_rows = tuple(
        item.calibration_id
        for item in catalog.calibration
        if item.asset_id == "motherboard" and "/dimm_" in item.calibration_id
    )
    ram_rows = tuple(
        item.calibration_id for item in catalog.calibration if item.asset_id == "ram"
    )

    assert motherboard_rows == tuple(
        f"motherboard/dimm_{index:02d}/memory/dimm_slot" for index in range(1, 9)
    )
    assert ram_rows == ("ram/memory/dimm_slot",)


def test_catalog_uses_preflight_valid_targets_only_for_ignore_pair_exclusion() -> None:
    targets = _all_targets()
    ignored = _metadata(
        "/blackwell_rig/power/psu/ignored_fan",
        "ignore",
        "ignore",
    )
    catalog = build_heatmap_catalog_from_preflight(_preflight((*targets, ignored)))

    assert ignored.prim_path not in {target.prim_path for target in catalog.targets}


def _preflight(targets) -> HeatmapAssetPreflightResult:
    return HeatmapAssetPreflightResult(
        success=True,
        root_path="/blackwell_rig",
        thermal_target_count=len(targets),
        valid_target_count=len(targets),
        malformed_target_count=0,
        review_target_count=0,
        observed_weight_min=0.0,
        observed_weight_max=1.0,
        xray_overlap_targets=(),
        diagnostics=(),
        review_targets=(),
        valid_targets=tuple(
            target
            for target in targets
            if (target.thermal_zone, target.thermal_component) != ("ignore", "ignore")
        ),
    )


def _all_targets() -> tuple[ThermalPrimMetadata, ...]:
    targets = [
        _metadata(
            "/blackwell_rig/motherboard/geo/passive",
            "motherboard_passive",
            "heatsink",
        ),
        _metadata(
            "/blackwell_rig/connectx_7/geo/pcb",
            "nic_board",
            "pcb",
        ),
        _metadata(
            "/blackwell_rig/cpu_cooler/geo/coldplate",
            "cpu_cooler_coldplate",
            "coldplate",
        ),
        _metadata(
            "/blackwell_rig/power/psu/geo/coil",
            "psu_coils",
            "coil",
        ),
    ]
    for index in range(1, 9):
        targets.append(
            _metadata(
                "/blackwell_rig/motherboard/ram_slots/" f"dimm_{index:02d}/geo/dimm",
                "memory",
                "dimm_slot",
            )
        )
        targets.append(
            _metadata(
                f"/blackwell_rig/ram/ram_{index:02d}/geo/dimm",
                "memory",
                "dimm_slot",
            )
        )
    for index in range(1, 4):
        root = f"/blackwell_rig/compute/gpu_{index:02d}/geo"
        targets.extend(
            (
                _metadata(f"{root}/pcb", "board", "pcb"),
                _metadata(f"{root}/shroud", "gpu_body", "shroud"),
                _metadata(f"{root}/blower", "gpu_cooling", "blower"),
            )
        )
    return tuple(targets)


def _metadata(
    path: str,
    zone: str,
    component: str,
) -> ThermalPrimMetadata:
    return ThermalPrimMetadata(
        prim_path=path,
        thermal_zone=zone,
        thermal_component=component,
        thermal_weight=(0.0, 1.0),
        thermal_weight_interpolation="vertex",
        temperature_preview=(10.0, 20.0),
        temperature_preview_interpolation="vertex",
        thermal_zone_state=PROPERTY_VALUE,
        thermal_component_state=PROPERTY_VALUE,
        thermal_weight_state=PROPERTY_VALUE,
    )
