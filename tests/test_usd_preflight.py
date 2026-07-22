from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from blackwell_monitoring_suite.app.config import RuntimeConfig
from blackwell_monitoring_suite.app.usd_preflight import run_usd_preflight


def test_runtime_usd_preflight_accepts_configured_full_rig_contract():
    config = RuntimeConfig.load(
        Path("configs/blackwell_monitoring_suite.toml"),
        apply_local_overrides=False,
    )
    stage = _make_contract_stage()
    _define_configured_prims(stage, config)

    result = run_usd_preflight(stage, config)

    assert result.success is True
    assert result.findings == ()
    assert result.format_summary() == "preflight passed"


def test_runtime_usd_preflight_reports_stage_contract_mismatches():
    from pxr import Usd, UsdGeom

    config = _minimal_config()
    stage = Usd.Stage.CreateInMemory()
    wrong_root = UsdGeom.Xform.Define(stage, "/server").GetPrim()
    stage.SetDefaultPrim(wrong_root)
    UsdGeom.SetStageMetersPerUnit(stage, 0.01)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)

    result = run_usd_preflight(stage, config)

    assert result.success is False
    assert _finding_codes(result) == {
        "missing_root_prim",
        "default_prim_mismatch",
        "meters_per_unit_mismatch",
        "up_axis_mismatch",
    }


def test_runtime_usd_preflight_reports_missing_configured_prims():
    config = RuntimeConfig.load(
        Path("configs/blackwell_monitoring_suite.toml"),
        apply_local_overrides=False,
    )
    stage = _make_contract_stage()

    result = run_usd_preflight(stage, config)

    codes = _finding_codes(result)
    assert result.success is False
    assert "missing_chassis_visibility_group" in codes
    assert "missing_chassis_face_panel" in codes
    assert "missing_chassis_qled_segment" in codes
    assert "missing_chassis_front_panel_indicator" in codes
    assert "missing_fan_mesh" in codes
    assert "missing_fan_rotation_target" in codes


def test_runtime_usd_preflight_reports_dependency_contract_failures(tmp_path):
    from pxr import Usd

    absolute_layer_path = tmp_path / "absolute.usd"
    absolute_layer_path.write_text(
        '#usda 1.0\n\ndef Xform "absolute" {}\n',
        encoding="utf-8",
    )
    root_layer_path = tmp_path / "root.usda"
    root_layer_path.write_text(
        "\n".join(
            [
                "#usda 1.0",
                "(",
                '    defaultPrim = "blackwell_rig"',
                "    metersPerUnit = 1",
                '    upAxis = "Y"',
                ")",
                "",
                'def Xform "blackwell_rig" (',
                "    references = [",
                "        @missing.usd@,",
                f"        @{absolute_layer_path.as_posix()}@",
                "    ]",
                ")",
                "{",
                "}",
            ]
        ),
        encoding="utf-8",
    )

    stage = Usd.Stage.Open(root_layer_path.as_posix())
    result = run_usd_preflight(stage, _minimal_config())

    assert result.success is False
    assert "absolute_asset_dependency" in _finding_codes(result)
    assert "missing_asset_dependency" in _finding_codes(result)


def test_runtime_usd_preflight_reports_time_sampled_content():
    from pxr import Gf, UsdGeom

    stage = _make_contract_stage()
    xform = UsdGeom.Xform.Define(stage, "/blackwell_rig/animated")
    translate_op = xform.AddTranslateOp()
    translate_op.Set(Gf.Vec3d(0.0, 0.0, 0.0), 1.0)
    translate_op.Set(Gf.Vec3d(1.0, 0.0, 0.0), 2.0)

    result = run_usd_preflight(stage, _minimal_config())

    assert result.success is False
    assert "time_sampled_content" in _finding_codes(result)


def _make_contract_stage():
    from pxr import Usd, UsdGeom

    stage = Usd.Stage.CreateInMemory()
    root = UsdGeom.Xform.Define(stage, "/blackwell_rig").GetPrim()
    stage.SetDefaultPrim(root)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    return stage


def _define_configured_prims(stage, config: RuntimeConfig) -> None:
    from pxr import UsdGeom

    for path in config.chassis_presentation.cover_paths:
        UsdGeom.Xform.Define(stage, path)
    for group in config.chassis_presentation.visibility_groups:
        for path in group.paths:
            UsdGeom.Xform.Define(stage, path)
    if config.chassis_presentation.face_panel.enabled:
        UsdGeom.Xform.Define(stage, config.chassis_presentation.face_panel.target_path)
    if config.chassis_presentation.qled_display.enabled:
        for segment_paths in config.chassis_presentation.qled_display.digits.values():
            for path in segment_paths.values():
                UsdGeom.Mesh.Define(stage, path)
    if config.chassis_presentation.front_panel_indicators.enabled:
        indicators = config.chassis_presentation.front_panel_indicators
        for path in (
            indicators.power_path,
            indicators.hdd_path,
            indicators.lan_01_path,
            indicators.lan_02_path,
        ):
            UsdGeom.Mesh.Define(stage, path)
    for binding in config.fan_motion_bindings:
        UsdGeom.Xform.Define(stage, binding.rotation_target_path)
        UsdGeom.Mesh.Define(stage, binding.mesh_path)


def _minimal_config():
    return SimpleNamespace(
        chassis_presentation=SimpleNamespace(cover_paths=(), visibility_groups=()),
        fan_motion_bindings=(),
    )


def _finding_codes(result) -> set[str]:
    return {finding.code for finding in result.findings}
