# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""Exact Session-layer restoration coverage for generic Heatmap isolation."""

from __future__ import annotations

from digital_twin_runtime_suite.app.heatmaps.isolation import HeatmapIsolation


def test_arbitrary_target_union_restores_exact_prior_visibility_specs() -> None:
    from pxr import Sdf, Usd, UsdGeom

    stage = _stage(Usd, UsdGeom)
    _set_session_visibility(
        stage,
        "/blackwell_rig/compute/gpu_02",
        "invisible",
        UsdGeom,
    )
    before = stage.GetSessionLayer().ExportToString()
    isolation = HeatmapIsolation()
    targets = (
        "/blackwell_rig/motherboard/geo/board",
        "/blackwell_rig/compute/gpu_01/geo/pcb",
        "/blackwell_rig/compute/gpu_01/geo/shroud",
    )

    enabled = isolation.apply(stage, targets)
    restored = isolation.restore(stage)

    assert enabled.success and enabled.enabled
    assert enabled.target_paths == tuple(sorted(targets))
    assert all(
        path.startswith("/blackwell_rig/") for path in enabled.owned_visibility_paths
    )
    assert restored.success and not restored.enabled
    assert stage.GetSessionLayer().ExportToString() == before
    assert (
        _session_visibility(stage, "/blackwell_rig/compute/gpu_02", Sdf) == "invisible"
    )


def test_each_isolation_selector_can_be_represented_by_an_arbitrary_union() -> None:
    from pxr import Usd, UsdGeom

    stage = _stage(Usd, UsdGeom)
    isolation = HeatmapIsolation()
    selector_targets = {
        "motherboard": "/blackwell_rig/motherboard/geo/board",
        "connectx_7": "/blackwell_rig/connectx_7/geo/pcb",
        "gpu_01_internals": "/blackwell_rig/compute/gpu_01/geo/pcb",
        "gpu_01_housing": "/blackwell_rig/compute/gpu_01/geo/shroud",
        "gpu_02_internals": "/blackwell_rig/compute/gpu_02/geo/pcb",
        "gpu_02_housing": "/blackwell_rig/compute/gpu_02/geo/shroud",
        "gpu_03_internals": "/blackwell_rig/compute/gpu_03/geo/pcb",
        "gpu_03_housing": "/blackwell_rig/compute/gpu_03/geo/shroud",
        "cpu_cooler": "/blackwell_rig/cpu_cooler/geo/coldplate",
        "ram": "/blackwell_rig/ram/ram_01/geo/dimm",
        "psu": "/blackwell_rig/power/psu/geo/coil",
    }

    for path in selector_targets.values():
        result = isolation.apply(stage, (path,))
        assert result.success, path
        assert isolation.restore(stage).success

    all_selected = isolation.apply(stage, tuple(selector_targets.values()))
    assert all_selected.success
    assert isolation.restore(stage).success


def test_isolation_does_not_reveal_authored_hidden_selected_geometry() -> None:
    from pxr import Usd, UsdGeom

    stage = _stage(Usd, UsdGeom)
    connector_path = "/blackwell_rig/motherboard/geo/rack_only_rj45"
    UsdGeom.Mesh.Define(stage, connector_path)
    UsdGeom.Imageable(stage.GetPrimAtPath(connector_path)).CreateVisibilityAttr().Set(
        UsdGeom.Tokens.invisible
    )
    before = stage.GetSessionLayer().ExportToString()
    isolation = HeatmapIsolation()

    enabled = isolation.apply(
        stage,
        (
            "/blackwell_rig/motherboard/geo/board",
            connector_path,
        ),
    )

    assert enabled.success
    assert (
        UsdGeom.Imageable(stage.GetPrimAtPath(connector_path)).ComputeVisibility()
        == UsdGeom.Tokens.invisible
    )
    assert isolation.restore(stage).success
    assert stage.GetSessionLayer().ExportToString() == before


def test_replacement_stage_discards_stale_ownership_without_mutating_new_session() -> (
    None
):
    from pxr import Usd, UsdGeom

    first = _stage(Usd, UsdGeom)
    second = _stage(Usd, UsdGeom)
    isolation = HeatmapIsolation()
    isolation.apply(first, ("/blackwell_rig/motherboard/geo/board",))
    second_before = second.GetSessionLayer().ExportToString()

    isolation.discard_stale_stage(second)

    assert not isolation.active
    assert second.GetSessionLayer().ExportToString() == second_before


def _stage(Usd, UsdGeom):
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.Xform.Define(stage, "/blackwell_rig")
    for path in (
        "/blackwell_rig/motherboard/geo/board",
        "/blackwell_rig/connectx_7/geo/pcb",
        "/blackwell_rig/compute/gpu_01/geo/pcb",
        "/blackwell_rig/compute/gpu_01/geo/shroud",
        "/blackwell_rig/compute/gpu_02/geo/pcb",
        "/blackwell_rig/compute/gpu_02/geo/shroud",
        "/blackwell_rig/compute/gpu_03/geo/pcb",
        "/blackwell_rig/compute/gpu_03/geo/shroud",
        "/blackwell_rig/cpu_cooler/geo/coldplate",
        "/blackwell_rig/ram/ram_01/geo/dimm",
        "/blackwell_rig/power/psu/geo/coil",
    ):
        UsdGeom.Mesh.Define(stage, path)
    return stage


def _set_session_visibility(stage, path: str, value: str, UsdGeom) -> None:
    previous = stage.GetEditTarget()
    stage.SetEditTarget(stage.GetSessionLayer())
    try:
        UsdGeom.Imageable(stage.GetPrimAtPath(path)).CreateVisibilityAttr().Set(value)
    finally:
        stage.SetEditTarget(previous)


def _session_visibility(stage, path: str, Sdf) -> str | None:
    property_path = Sdf.Path(path).AppendProperty("visibility")
    spec = stage.GetSessionLayer().GetPropertyAtPath(property_path)
    return str(spec.default) if spec is not None else None
