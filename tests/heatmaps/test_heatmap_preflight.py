# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""Focused full-server Heatmap asset-contract tests."""

from __future__ import annotations

import math

import pytest

from digital_twin_runtime_suite.app.heatmaps.discovery import (
    PROPERTY_ABSENT,
    PROPERTY_DECLARED_NO_VALUE,
    PROPERTY_EMPTY,
    PROPERTY_VALUE,
    discover_thermal_geometry,
)
from digital_twin_runtime_suite.app.heatmaps.preflight import (
    run_heatmap_asset_preflight,
)

ROOT_PATH = "/blackwell_rig"


def test_valid_thermal_targets_pass_and_ignore_ordinary_geometry():
    """Only annotated geometry participates in the thermal contract."""

    from pxr import Usd, UsdGeom

    stage = _stage(Usd, UsdGeom)
    _thermal_mesh(stage, "/blackwell_rig/gpu/core", include_preview=True)
    UsdGeom.Mesh.Define(stage, "/blackwell_rig/chassis/plain_mesh")

    result = run_heatmap_asset_preflight(stage)

    assert result.success
    assert result.thermal_target_count == 1
    assert result.valid_target_count == 1
    assert result.malformed_target_count == 0
    assert result.review_target_count == 0
    assert result.observed_weight_min == pytest.approx(0.2)
    assert result.observed_weight_max == pytest.approx(0.8)


def test_missing_optional_temperature_preview_remains_valid():
    """Preview values are useful authoring data, not a required runtime contract."""

    from pxr import Usd, UsdGeom

    stage = _stage(Usd, UsdGeom)
    _thermal_mesh(stage, "/blackwell_rig/gpu/core")

    result = run_heatmap_asset_preflight(stage)

    assert result.success
    assert result.valid_target_count == 1


@pytest.mark.parametrize(
    (
        "include_zone",
        "include_component",
        "include_weight",
        "present",
        "missing",
    ),
    (
        (
            True,
            False,
            False,
            ("thermal_zone",),
            ("thermal_component", "primvars:thermal_weight"),
        ),
        (
            True,
            False,
            True,
            ("thermal_zone", "primvars:thermal_weight"),
            ("thermal_component",),
        ),
    ),
)
def test_partial_thermal_contract_fails_with_the_exact_prim_path(
    include_zone,
    include_component,
    include_weight,
    present,
    missing,
):
    """One or two core fields are definite contract failures, not review items."""

    from pxr import Usd, UsdGeom

    stage = _stage(Usd, UsdGeom)
    path = "/blackwell_rig/gpu/partial"
    _thermal_mesh(
        stage,
        path,
        include_zone=include_zone,
        include_component=include_component,
        include_weight=include_weight,
    )

    result = run_heatmap_asset_preflight(stage)

    assert not result.success
    assert result.malformed_target_count == 1
    assert result.diagnostics[0].prim_path == path
    assert result.diagnostics[0].core_attributes_present == present
    assert result.diagnostics[0].core_attributes_missing == missing


def test_unannotated_standalone_asset_is_ignored():
    """An asset without core Heatmap metadata remains outside the contract."""

    from pxr import Usd, UsdGeom

    stage = _stage(Usd, UsdGeom)
    UsdGeom.Mesh.Define(stage, "/blackwell_rig/chassis/plain_mesh")

    result = run_heatmap_asset_preflight(stage)

    assert result.success
    assert result.thermal_target_count == 0
    assert result.malformed_target_count == 0
    assert result.review_target_count == 0


def test_discovery_distinguishes_absent_declared_empty_and_value_properties():
    """USD property state is retained before the validator inspects its value."""

    from pxr import Sdf, Usd, UsdGeom, Vt

    stage = _stage(Usd, UsdGeom)
    absent_path = "/blackwell_rig/chassis/absent"
    declared_path = "/blackwell_rig/chassis/declared"
    empty_path = "/blackwell_rig/chassis/empty"
    value_path = "/blackwell_rig/chassis/value"
    UsdGeom.Mesh.Define(stage, absent_path)
    declared = UsdGeom.Mesh.Define(stage, declared_path).GetPrim()
    declared.CreateAttribute("thermal_zone", Sdf.ValueTypeNames.Token, custom=True)
    empty = UsdGeom.Mesh.Define(stage, empty_path).GetPrim()
    empty.CreateAttribute("thermal_zone", Sdf.ValueTypeNames.Token, custom=True).Set("")
    value = UsdGeom.Mesh.Define(stage, value_path).GetPrim()
    UsdGeom.PrimvarsAPI(value).CreatePrimvar(
        "thermal_weight",
        Sdf.ValueTypeNames.FloatArray,
        UsdGeom.Tokens.vertex,
    ).Set(Vt.FloatArray((0.5,)))

    metadata = {
        item.prim_path: item for item in discover_thermal_geometry(stage, ROOT_PATH)
    }

    assert metadata[absent_path].thermal_zone_state == PROPERTY_ABSENT
    assert metadata[declared_path].thermal_zone_state == PROPERTY_DECLARED_NO_VALUE
    assert metadata[empty_path].thermal_zone_state == PROPERTY_EMPTY
    assert metadata[value_path].thermal_weight_state == PROPERTY_VALUE


def test_authored_empty_core_property_fails_instead_of_being_unannotated():
    """An authored empty string is a definite value error on a full contract."""

    from pxr import Usd, UsdGeom

    stage = _stage(Usd, UsdGeom)
    path = "/blackwell_rig/gpu/empty_zone"
    _thermal_mesh(stage, path, zone_value="")

    result = run_heatmap_asset_preflight(stage)

    assert not result.success
    assert result.diagnostics[0].prim_path == path
    assert result.diagnostics[0].reason == "empty thermal_zone"


def test_ignore_pair_is_a_valid_explicit_heatmap_exclusion():
    """The paired sentinel bypasses target, review, and weight validation."""

    from pxr import Usd, UsdGeom

    stage = _stage(Usd, UsdGeom)
    _thermal_mesh(
        stage,
        "/blackwell_rig/gpu/ignored",
        include_weight=False,
        zone_value="ignore",
        component_value="ignore",
    )

    result = run_heatmap_asset_preflight(stage)

    assert result.success
    assert result.thermal_target_count == 0
    assert result.valid_target_count == 0
    assert result.malformed_target_count == 0
    assert result.review_target_count == 0


@pytest.mark.parametrize(
    ("zone_value", "component_value"),
    (("ignore", "core"), ("gpu", "ignore")),
)
def test_unpaired_ignore_sentinel_fails(zone_value, component_value):
    """Either side of the opt-out sentinel is invalid without its matching pair."""

    from pxr import Usd, UsdGeom

    stage = _stage(Usd, UsdGeom)
    path = "/blackwell_rig/gpu/invalid_ignore"
    _thermal_mesh(
        stage,
        path,
        zone_value=zone_value,
        component_value=component_value,
    )

    result = run_heatmap_asset_preflight(stage)

    assert not result.success
    assert result.diagnostics[0].prim_path == path
    assert "must both be 'ignore'" in result.diagnostics[0].reason


def test_empty_values_are_not_the_explicit_ignore_sentinel():
    """Authored empty strings remain definite contract errors."""

    from pxr import Usd, UsdGeom

    stage = _stage(Usd, UsdGeom)
    _thermal_mesh(
        stage,
        "/blackwell_rig/gpu/empty_pair",
        zone_value="",
        component_value="",
    )

    result = run_heatmap_asset_preflight(stage)

    assert not result.success
    assert result.diagnostics[0].reason == "empty thermal_zone; empty thermal_component"


def test_ignore_pair_skips_invalid_thermal_weight_validation():
    """Explicitly excluded geometry does not consume a Heatmap weight contract."""

    from pxr import Usd, UsdGeom

    stage = _stage(Usd, UsdGeom)
    _thermal_mesh(
        stage,
        "/blackwell_rig/gpu/ignored_invalid_weight",
        weights=(math.nan,),
        zone_value="ignore",
        component_value="ignore",
    )

    result = run_heatmap_asset_preflight(stage)

    assert result.success
    assert result.thermal_target_count == 0


def test_unannotated_part_in_heatmap_asset_requires_review_but_still_passes():
    """A bare part shares review intent with a valid target in its own asset."""

    from pxr import Usd, UsdGeom

    stage = _stage(Usd, UsdGeom)
    _thermal_mesh(stage, "/blackwell_rig/cpu_cooler/radiator")
    review_path = "/blackwell_rig/cpu_cooler/fan"
    UsdGeom.Mesh.Define(stage, review_path)

    result = run_heatmap_asset_preflight(stage)

    assert result.success
    assert result.valid_target_count == 1
    assert result.malformed_target_count == 0
    assert result.review_target_count == 1
    assert result.review_targets == (review_path,)


def test_heatmap_free_power_sibling_subtree_is_not_reviewed():
    """PSU intent does not propagate across the independent cable subtree."""

    from pxr import Usd, UsdGeom

    stage = _stage(Usd, UsdGeom)
    _thermal_mesh(stage, "/blackwell_rig/power/psu/geo/render/psu/core")
    psu_review_path = "/blackwell_rig/power/psu/geo/render/psu/fan"
    cable_path = "/blackwell_rig/power/cables/geo/render/cables/power_cable"
    UsdGeom.Mesh.Define(stage, psu_review_path)
    UsdGeom.Mesh.Define(stage, cable_path)

    result = run_heatmap_asset_preflight(stage)

    assert result.success
    assert result.review_target_count == 1
    assert result.review_targets == (psu_review_path,)


@pytest.mark.parametrize("weight", (1.1, math.nan, math.inf))
def test_invalid_weight_values_fail(weight):
    """Thermal weights must remain finite normalised values."""

    from pxr import Usd, UsdGeom

    stage = _stage(Usd, UsdGeom)
    path = "/blackwell_rig/gpu/invalid_weight"
    _thermal_mesh(stage, path, weights=(weight,))

    result = run_heatmap_asset_preflight(stage)

    assert not result.success
    assert result.diagnostics[0].prim_path == path
    assert (
        "thermal_weight must be finite and within [0, 1]"
        in result.diagnostics[0].reason
    )


def test_xray_overlap_retains_only_valid_dual_purpose_geometry():
    """Overlap evidence contains every and only valid Heatmap X-Ray prim path."""

    from pxr import Usd, UsdGeom

    stage = _stage(Usd, UsdGeom)
    xray_root = "/blackwell_rig/compute/gpu_03/shroud"
    overlap_paths = (
        f"{xray_root}/thermal_mesh_a",
        f"{xray_root}/thermal_mesh_b",
    )
    for path in overlap_paths:
        _thermal_mesh(stage, path)
    xray_only_path = f"{xray_root}/xray_only_mesh"
    heatmap_only_path = "/blackwell_rig/compute/gpu_03/pcb/thermal_mesh"
    UsdGeom.Mesh.Define(stage, xray_only_path)
    _thermal_mesh(stage, heatmap_only_path)

    result = run_heatmap_asset_preflight(
        stage,
        xray_target_paths=(xray_root,),
    )

    assert result.success
    assert len(result.xray_overlap_targets) == 2
    assert result.xray_overlap_targets == overlap_paths
    assert all(path.startswith(f"{xray_root}/") for path in result.xray_overlap_targets)
    assert xray_only_path not in result.xray_overlap_targets
    assert heatmap_only_path not in result.xray_overlap_targets


def test_xray_only_geometry_is_not_a_heatmap_contract_failure():
    """X-Ray membership alone neither creates a target nor requires metadata."""

    from pxr import Usd, UsdGeom

    stage = _stage(Usd, UsdGeom)
    path = "/blackwell_rig/chassis/xray_only_mesh"
    UsdGeom.Mesh.Define(stage, path)

    result = run_heatmap_asset_preflight(stage, xray_target_paths=(path,))

    assert result.success
    assert result.thermal_target_count == 0
    assert result.xray_overlap_targets == ()


def test_proxy_geometry_is_excluded_before_heatmap_classification():
    """Proxy Gprims do not affect Heatmap counts, diagnostics, review, or overlap."""

    from pxr import Usd, UsdGeom

    stage = _stage(Usd, UsdGeom)
    render_path = "/blackwell_rig/compute/gpu_03/geo/render/RTX4500/core"
    partial_proxy_path = "/blackwell_rig/compute/gpu_03/geo/proxy/core_proxy"
    bare_proxy_path = "/blackwell_rig/compute/gpu_03/geo/proxy/fan_proxy"
    _thermal_mesh(stage, render_path)
    _thermal_mesh(
        stage,
        partial_proxy_path,
        include_component=False,
        include_weight=False,
    )
    UsdGeom.Mesh.Define(stage, bare_proxy_path)

    result = run_heatmap_asset_preflight(
        stage,
        xray_target_paths=("/blackwell_rig/compute/gpu_03/geo/proxy",),
    )

    assert result.success
    assert result.thermal_target_count == 1
    assert result.valid_target_count == 1
    assert result.malformed_target_count == 0
    assert result.review_target_count == 0
    assert result.xray_overlap_targets == ()


def _stage(Usd, UsdGeom):
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.Xform.Define(stage, ROOT_PATH)
    return stage


def _thermal_mesh(
    stage,
    path: str,
    *,
    weights: tuple[float, ...] = (0.2, 0.8),
    include_zone: bool = True,
    zone_value: str = "gpu",
    include_component: bool = True,
    component_value: str = "core",
    include_weight: bool = True,
    include_preview: bool = False,
) -> None:
    from pxr import Sdf, UsdGeom, Vt

    prim = UsdGeom.Mesh.Define(stage, path).GetPrim()
    if include_zone:
        prim.CreateAttribute("thermal_zone", Sdf.ValueTypeNames.Token, custom=True).Set(
            zone_value
        )
    if include_component:
        prim.CreateAttribute(
            "thermal_component",
            Sdf.ValueTypeNames.Token,
            custom=True,
        ).Set(component_value)
    primvars = UsdGeom.PrimvarsAPI(prim)
    if include_weight:
        primvars.CreatePrimvar(
            "thermal_weight",
            Sdf.ValueTypeNames.FloatArray,
            UsdGeom.Tokens.vertex,
        ).Set(Vt.FloatArray(weights))
    if include_preview:
        primvars.CreatePrimvar(
            "temperature_preview",
            Sdf.ValueTypeNames.FloatArray,
            UsdGeom.Tokens.vertex,
        ).Set(Vt.FloatArray((42.0, 43.0)))
