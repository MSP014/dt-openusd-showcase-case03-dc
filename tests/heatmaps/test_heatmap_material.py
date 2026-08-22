"""Session-only ownership coverage for the multi-target GPU03 presenter."""

from __future__ import annotations

import pytest

from digital_twin_runtime_suite.app.heatmaps.material import (
    HeatmapMaterialPresenter,
    HeatmapMaterialTarget,
)
from digital_twin_runtime_suite.app.heatmaps.scalar import (
    FULL_SPECTRUM_HEATMAP_PALETTE,
    THERMAL_WEIGHT_REMAP_COLD_BIASED,
    CelsiusScale,
    DeltaProfile,
)


def test_presenter_synchronizes_multiple_targets_and_restores_session_state() -> None:
    from pxr import Sdf, Usd, UsdGeom, UsdShade, Vt

    stage = Usd.Stage.CreateInMemory()
    paths = tuple(
        f"/blackwell_rig/compute/gpu_03/{name}" for name in "die vram vrm".split()
    )
    for path in paths:
        prim = UsdGeom.Mesh.Define(stage, path).GetPrim()
        UsdShade.MaterialBindingAPI.Apply(prim).Bind(
            UsdShade.Material.Define(stage, f"/Author/{path.rsplit('/', 1)[1]}")
        )
        _set_session_st(stage, prim, Sdf, UsdGeom, Vt)
    root_before = stage.GetRootLayer().ExportToString()
    session_before = stage.GetSessionLayer().ExportToString()
    presenter = HeatmapMaterialPresenter()
    targets = _targets(paths, telemetry=(90.0, 80.0, 70.0))

    enabled = presenter.enable(
        stage,
        targets=targets,
        scale=CelsiusScale(30.96, 101.0),
        palette=FULL_SPECTRUM_HEATMAP_PALETTE,
    )
    refreshed = presenter.refresh(
        stage,
        targets=_targets(paths, telemetry=(100.0, 90.0, 80.0)),
        scale=CelsiusScale(30.96, 101.0),
        palette=FULL_SPECTRUM_HEATMAP_PALETTE,
    )

    assert enabled.success and enabled.target_paths == paths
    assert refreshed.success and refreshed.material_creations == len(paths)
    assert refreshed.parameter_updates == 2
    assert stage.GetRootLayer().ExportToString() == root_before
    assert stage.GetPrimAtPath(presenter.MATERIAL_ROOT).IsValid()
    restored = presenter.disable(stage)

    assert restored.success and not restored.enabled
    assert not stage.GetPrimAtPath(presenter.MATERIAL_ROOT).IsValid()
    assert stage.GetRootLayer().ExportToString() == root_before
    assert stage.GetSessionLayer().ExportToString() == session_before


def test_unavailable_target_removal_keeps_remaining_material_stable() -> None:
    from pxr import Usd, UsdGeom

    stage = Usd.Stage.CreateInMemory()
    paths = tuple(
        f"/blackwell_rig/compute/gpu_03/{name}" for name in "die vram".split()
    )
    for path in paths:
        UsdGeom.Mesh.Define(stage, path)
    presenter = HeatmapMaterialPresenter()
    scale = CelsiusScale(30.96, 101.0)

    presenter.enable(
        stage,
        targets=_targets(paths, telemetry=(90.0, 80.0)),
        scale=scale,
        palette=FULL_SPECTRUM_HEATMAP_PALETTE,
    )
    reduced = presenter.refresh(
        stage,
        targets=_targets(paths[:1], telemetry=(100.0,)),
        scale=scale,
        palette=FULL_SPECTRUM_HEATMAP_PALETTE,
    )

    assert reduced.success
    assert reduced.target_paths == paths[:1]
    assert reduced.material_creations == 2


def test_presenter_reuses_one_material_for_a_semantic_target_group() -> None:
    from pxr import Usd, UsdGeom

    stage = Usd.Stage.CreateInMemory()
    paths = ("/blackwell_rig/gpu/die_a", "/blackwell_rig/gpu/die_b")
    for path in paths:
        UsdGeom.Mesh.Define(stage, path)
    presenter = HeatmapMaterialPresenter(
        material_root="/DTRS_Runtime/Heatmaps/FullServer"
    )
    targets = tuple(
        HeatmapMaterialTarget(
            material_key="gpu_hotspot",
            prim_path=path,
            thermal_weights=(0.1, 0.9),
            telemetry_celsius=90.0,
            delta_profile=DeltaProfile(-2.0, 4.0),
        )
        for path in paths
    )

    result = presenter.enable(
        stage,
        targets=targets,
        scale=CelsiusScale(30.96, 108.0),
        palette=FULL_SPECTRUM_HEATMAP_PALETTE,
    )

    assert result.success
    assert result.material_group_count == 1
    assert result.session_binding_count == 2
    assert result.material_creations == 1
    assert presenter.disable(stage).success


def test_dynamic_telemetry_update_writes_only_changed_telemetry_input() -> None:
    from pxr import Usd, UsdGeom

    stage = Usd.Stage.CreateInMemory()
    path = "/blackwell_rig/motherboard/chipset"
    UsdGeom.Mesh.Define(stage, path)
    presenter = HeatmapMaterialPresenter()
    target = _targets((path,), telemetry=(50.0,))
    presenter.enable(
        stage,
        targets=target,
        scale=CelsiusScale(30.96, 108.0),
        palette=FULL_SPECTRUM_HEATMAP_PALETTE,
    )
    before = presenter.write_counts

    changed = presenter.update_telemetry(stage, {"target_001": 55.0})
    repeated = presenter.update_telemetry(stage, {"target_001": 55.0})
    after = presenter.write_counts

    assert changed.success and repeated.success
    assert after.shader_parameter_writes - before.shader_parameter_writes == 1
    assert (
        after.skipped_unchanged_parameter_writes
        - before.skipped_unchanged_parameter_writes
        == 1
    )
    assert after.structural_material_writes == before.structural_material_writes
    assert after.material_binding_writes == before.material_binding_writes
    assert after.primvar_st_writes == before.primvar_st_writes
    assert presenter.disable(stage).success


def test_cold_biased_material_keeps_authored_weights_and_owns_policy_inputs() -> None:
    from pxr import Usd, UsdGeom, UsdShade

    stage = Usd.Stage.CreateInMemory()
    path = "/blackwell_rig/motherboard/nvme_a"
    prim = UsdGeom.Mesh.Define(stage, path).GetPrim()
    presenter = HeatmapMaterialPresenter()
    target = HeatmapMaterialTarget(
        material_key="nvme_a",
        prim_path=path,
        thermal_weights=(0.4, 0.7, 0.8),
        telemetry_celsius=45.0,
        delta_profile=DeltaProfile(-4.0, 16.0),
        thermal_weight_remap=THERMAL_WEIGHT_REMAP_COLD_BIASED,
        thermal_weight_minimum=0.4,
        thermal_weight_maximum=0.8,
    )

    result = presenter.enable(
        stage,
        targets=(target,),
        scale=CelsiusScale(26.0, 108.0),
        palette=FULL_SPECTRUM_HEATMAP_PALETTE,
    )
    shader = UsdShade.Shader.Get(
        stage,
        "/DTRS_Runtime/Heatmaps/Gpu03/nvme_a/Shader",
    )
    authored_weights = tuple(
        float(value[0]) for value in UsdGeom.PrimvarsAPI(prim).GetPrimvar("st").Get()
    )

    assert result.success
    assert authored_weights == pytest.approx((0.4, 0.7, 0.8))
    assert shader.GetInput("thermal_weight_minimum").Get() == pytest.approx(0.4)
    assert shader.GetInput("thermal_weight_maximum").Get() == pytest.approx(0.8)
    assert shader.GetInput("thermal_weight_remap_mode").Get() == 1.0
    assert presenter.disable(stage).success


def _targets(paths, *, telemetry) -> tuple[HeatmapMaterialTarget, ...]:
    return tuple(
        HeatmapMaterialTarget(
            material_key=f"target_{index:03d}",
            prim_path=path,
            thermal_weights=(0.1, 0.9),
            telemetry_celsius=value,
            delta_profile=DeltaProfile(3.0, 14.0),
        )
        for index, (path, value) in enumerate(zip(paths, telemetry), start=1)
    )


def _set_session_st(stage, prim, Sdf, UsdGeom, Vt) -> None:
    previous_target = stage.GetEditTarget()
    stage.SetEditTarget(stage.GetSessionLayer())
    try:
        UsdGeom.PrimvarsAPI(prim).CreatePrimvar(
            "st",
            Sdf.ValueTypeNames.TexCoord2fArray,
            UsdGeom.Tokens.vertex,
        ).Set(Vt.Vec2fArray(((0.25, 0.5), (0.75, 0.5))))
    finally:
        stage.SetEditTarget(previous_target)
