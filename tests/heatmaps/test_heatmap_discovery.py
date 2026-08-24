# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""Focused Stage 10.1 tests for immutable USD thermal semantic discovery."""

from __future__ import annotations

from digital_twin_runtime_suite.app.heatmaps.bindings import resolve_hardware_identity
from digital_twin_runtime_suite.app.heatmaps.discovery import (
    discover_thermal_geometry,
)


def test_discovery_preserves_authored_semantics_and_stable_path_order() -> None:
    from pxr import Sdf, Usd, UsdGeom, Vt

    stage = Usd.Stage.CreateInMemory()
    gpu_03 = "/blackwell_rig/compute/gpu_03/geo/render/RTX4500/pcb/die"
    gpu_01 = "/blackwell_rig/compute/gpu_01/geo/render/RTX4500/pcb/vram"
    _thermal_mesh(
        stage,
        gpu_03,
        zone="gpu_core",
        component="gb203_die",
        Sdf=Sdf,
        UsdGeom=UsdGeom,
        Vt=Vt,
    )
    _thermal_mesh(
        stage,
        gpu_01,
        zone="vram",
        component="memory_chip",
        Sdf=Sdf,
        UsdGeom=UsdGeom,
        Vt=Vt,
    )
    _thermal_mesh(
        stage,
        "/blackwell_rig/compute/gpu_02/geo/proxy/RTX4500/die",
        zone="gpu_core",
        component="gb203_die",
        Sdf=Sdf,
        UsdGeom=UsdGeom,
        Vt=Vt,
    )
    _thermal_mesh(
        stage,
        "/blackwell_rig/compute/gpu_02/geo/render/RTX4500/shroud",
        zone="ignore",
        component="ignore",
        Sdf=Sdf,
        UsdGeom=UsdGeom,
        Vt=Vt,
    )

    discovered = discover_thermal_geometry(stage, "/blackwell_rig")

    assert tuple(target.prim_path for target in discovered) == (gpu_01, gpu_03)
    assert discovered[0].thermal_zone == "vram"
    assert discovered[0].thermal_component == "memory_chip"
    assert discovered[0].thermal_weight == (0.25, 0.75)
    assert discovered[0].thermal_weight_interpolation == "vertex"
    assert discovered[0].temperature_preview is None

    gpu_01_identity, gpu_01_error = resolve_hardware_identity(gpu_01)
    gpu_03_identity, gpu_03_error = resolve_hardware_identity(gpu_03)
    assert gpu_01_error is None and gpu_03_error is None
    assert gpu_01_identity.label == "gpu_1"
    assert gpu_03_identity.label == "gpu_3"


def _thermal_mesh(stage, path, *, zone, component, Sdf, UsdGeom, Vt) -> None:
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
