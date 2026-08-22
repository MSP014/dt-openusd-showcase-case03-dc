"""Focused production X-Ray config, lifecycle, camera, and telemetry tests."""

from __future__ import annotations

import sys
import tomllib
from dataclasses import replace
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from digital_twin_runtime_suite.app.commands import RuntimeController
from digital_twin_runtime_suite.app.config import (
    FrontPanelIndicatorsConfig,
    RuntimeConfig,
    XRayMaterialConfig,
    XRayTargetGroupConfig,
)
from digital_twin_runtime_suite.app.view_controls import bool_model_value


class _KitBoolModel:
    as_bool = True

    @staticmethod
    def get_value_as_bool():
        return False


def test_bool_model_prefers_kit_value_accessor_over_legacy_attribute():
    assert bool_model_value(_KitBoolModel()) is False


XRAY_CHASSIS_ROOT_PATH = "/blackwell_rig/chassis"


def test_xray_parameters_round_trip_without_persisting_runtime_selection(tmp_path):
    controller = RuntimeController(_write_xray_config(tmp_path))
    xray = XRayMaterialConfig(
        facing_color=(0.1, 0.2, 0.3),
        edge_color=(0.4, 0.5, 0.6),
        edge_center=0.5,
        edge_softness=0.4,
        edge_sharpness=2.0,
        facing_roughness=0.8,
        edge_roughness=0.1,
        facing_opacity=0.15,
        edge_opacity=0.9,
        facing_emission=0.5,
        edge_emission=5.0,
        emission_scale=25000.0,
    )

    saved = controller.save_xray_material_override(xray)
    reloaded = RuntimeConfig.load(_write_xray_config(tmp_path))

    assert saved.exists()
    assert reloaded.chassis_presentation.materials.xray == xray
    assert "chassis_selected" not in saved.read_text(encoding="utf-8")


def test_project_xray_target_groups_are_explicit_and_render_scoped():
    config = RuntimeConfig.load(Path("configs/digital_twin_runtime_suite.toml"))
    with Path("configs/digital_twin_runtime_suite.toml").open("rb") as config_file:
        project_xray = tomllib.load(config_file)["chassis_presentation"]["materials"][
            "xray"
        ]
    groups = {
        group.group_id: group
        for group in config.chassis_presentation.xray_target_groups
    }

    assert XRayMaterialConfig().facing_color == pytest.approx((8 / 255,) * 3)
    assert XRayMaterialConfig().edge_color == pytest.approx((0.0, 1.0, 0.0))
    assert project_xray == {
        "facing_color": pytest.approx([8 / 255, 8 / 255, 8 / 255]),
        "edge_color": pytest.approx([0.0, 1.0, 0.0]),
        "edge_center": pytest.approx(0.64),
        "edge_softness": pytest.approx(0.36),
        "edge_sharpness": pytest.approx(1.0),
        "facing_roughness": pytest.approx(0.1),
        "edge_roughness": pytest.approx(1.0),
        "facing_opacity": pytest.approx(0.16),
        "edge_opacity": pytest.approx(0.85),
        "facing_emission": pytest.approx(0.1),
        "edge_emission": pytest.approx(3.2),
        "emission_scale": pytest.approx(0.0),
    }
    assert tuple(groups) == (
        "chassis",
        "front_fans",
        "rear_fans",
        "cpu_cooler_fans",
        "gpu_shrouds",
        "psu_enclosure",
    )
    assert groups["front_fans"].paths[-1].endswith("p120_fan_cable_d")
    assert groups["rear_fans"].paths[-1].endswith("p8_fan_cable_b")
    assert groups["cpu_cooler_fans"].paths[0].endswith("cpu_fan")
    assert any(path.endswith("RTX4500/power") for path in groups["gpu_shrouds"].paths)
    assert any(path.endswith("cables_gpu_3") for path in groups["gpu_shrouds"].paths)
    assert groups["psu_enclosure"].paths == (
        "/blackwell_rig/power/psu/geo/render/psu/cooling",
        "/blackwell_rig/power/psu/geo/render/psu/housing",
        "/blackwell_rig/power/psu/geo/render/psu/dc_panel",
        "/blackwell_rig/power/psu/geo/render/psu/ac_panel",
    )


def test_xray_on_off_cycles_restore_authored_binding_and_remove_session_spec(tmp_path):
    from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade

    controller = RuntimeController(_write_xray_config(tmp_path))
    stage, meshes, baseline = _production_xray_stage(Usd, UsdGeom, UsdShade, 2)
    stage.SetEditTarget(stage.GetSessionLayer())
    xray = XRayMaterialConfig(
        facing_color=(0.1, 0.2, 0.3),
        edge_center=0.5,
        edge_emission=5.0,
    )

    for _ in range(3):
        target_count, _diagnostics = controller._apply_xray_session_overrides(
            stage, xray, {"chassis"}, Gf, Sdf, Usd, UsdShade
        )
        assert target_count == len(meshes)
        shader = UsdShade.Shader.Get(
            stage, f"{RuntimeController.XRAY_MATERIAL_PATH}/Shader"
        )
        assert shader.GetSourceAssetSubIdentifier("mdl") == "DTRS_Fresnel_Test"
        assert Path(shader.GetSourceAsset("mdl").path).name == "DTRS_Fresnel_Test.mdl"
        assert tuple(shader.GetInput("facing_color").Get()) == pytest.approx(
            xray.facing_color
        )
        assert shader.GetInput("edge_center").Get() == pytest.approx(xray.edge_center)
        assert shader.GetInput("edge_emission").Get() == pytest.approx(
            xray.edge_emission
        )
        for mesh in meshes:
            binding_path = mesh.GetPath().AppendProperty("material:binding")
            assert (
                _bound_material_path(mesh, UsdShade)
                == RuntimeController.XRAY_MATERIAL_PATH
            )
            assert stage.GetSessionLayer().GetPropertyAtPath(binding_path) is not None

        removed_count, _diagnostics = controller._clear_xray_session_overrides(
            stage, Sdf, Usd, UsdShade
        )
        assert removed_count == len(meshes)
        for mesh in meshes:
            binding_path = mesh.GetPath().AppendProperty("material:binding")
            assert _bound_material_path(mesh, UsdShade) == baseline
            assert stage.GetSessionLayer().GetPropertyAtPath(binding_path) is None
            assert not controller._session_binding_is_xray_owned(stage, binding_path)


def test_xray_reconciles_configured_target_groups_without_persisting_selection(
    tmp_path,
):
    from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade

    controller = RuntimeController(_write_xray_config(tmp_path))
    front_root = "/blackwell_rig/fans/p120_01/geo/render/bionix_p120"
    groups = (
        XRayTargetGroupConfig("chassis", "Chassis", (XRAY_CHASSIS_ROOT_PATH,)),
        XRayTargetGroupConfig("front_fans", "Front fans", (front_root,)),
    )
    controller.config = replace(
        controller.config,
        chassis_presentation=replace(
            controller.config.chassis_presentation,
            xray_target_groups=groups,
        ),
    )
    stage = Usd.Stage.CreateInMemory()
    authored = UsdShade.Material.Define(stage, "/Looks/Authored")
    chassis = UsdGeom.Mesh.Define(stage, f"{XRAY_CHASSIS_ROOT_PATH}/Panel").GetPrim()
    front_fan = UsdGeom.Mesh.Define(stage, f"{front_root}/body").GetPrim()
    UsdShade.MaterialBindingAPI.Apply(chassis).Bind(authored)
    UsdShade.MaterialBindingAPI.Apply(front_fan).Bind(authored)
    stage.SetEditTarget(stage.GetSessionLayer())

    controller._apply_xray_session_overrides(
        stage, XRayMaterialConfig(), {"chassis"}, Gf, Sdf, Usd, UsdShade
    )
    controller._apply_xray_session_overrides(
        stage, XRayMaterialConfig(), {"front_fans"}, Gf, Sdf, Usd, UsdShade
    )

    chassis_binding = chassis.GetPath().AppendProperty("material:binding")
    front_binding = front_fan.GetPath().AppendProperty("material:binding")
    assert _bound_material_path(chassis, UsdShade) == str(authored.GetPath())
    assert stage.GetSessionLayer().GetPropertyAtPath(chassis_binding) is None
    assert (
        _bound_material_path(front_fan, UsdShade)
        == RuntimeController.XRAY_MATERIAL_PATH
    )
    assert controller._session_binding_is_xray_owned(stage, front_binding)

    controller._clear_xray_session_overrides(stage, Sdf, Usd, UsdShade)
    assert _bound_material_path(front_fan, UsdShade) == str(authored.GetPath())
    assert stage.GetSessionLayer().GetPropertyAtPath(front_binding) is None


def test_streamlines_xray_override_uses_last_applied_ui_material(tmp_path, monkeypatch):
    from pxr import Usd, UsdGeom, UsdShade

    carb = ModuleType("carb")
    carb.log_error = lambda _message: None
    carb.log_warn = lambda _message: None
    monkeypatch.setitem(sys.modules, "carb", carb)
    controller = RuntimeController(_write_xray_config(tmp_path))
    groups = (
        XRayTargetGroupConfig("chassis", "Chassis", (XRAY_CHASSIS_ROOT_PATH,)),
        XRayTargetGroupConfig("fans", "Fans", ("/blackwell_rig/fans",)),
    )
    controller.config = replace(
        controller.config,
        chassis_presentation=replace(
            controller.config.chassis_presentation,
            xray_target_groups=groups,
        ),
    )
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.Mesh.Define(stage, f"{XRAY_CHASSIS_ROOT_PATH}/Panel")
    UsdGeom.Mesh.Define(stage, "/blackwell_rig/fans/p120_01/geo/render/body")
    _install_omni_usd_stage(monkeypatch, stage)
    material = replace(
        controller.config.chassis_presentation.materials.xray,
        facing_color=(0.13, 0.27, 0.41),
        edge_emission=4.0,
    )

    assert controller.apply_manual_xray_material_in_kit(material, {"chassis"}).success
    applied = controller.apply_streamlines_xray_override_in_kit()

    assert applied.success
    assert controller.xray_target_snapshot().override_owner == "streamlines_xray"
    assert controller.xray_target_snapshot().effective_target_ids == {
        "chassis",
        "fans",
    }
    shader = UsdShade.Shader.Get(
        stage,
        f"{RuntimeController.XRAY_MATERIAL_PATH}/Shader",
    )
    assert tuple(shader.GetInput("facing_color").Get()) == pytest.approx(
        material.facing_color
    )
    assert shader.GetInput("edge_emission").Get() == pytest.approx(
        material.edge_emission
    )

    released = controller.release_streamlines_xray_override_in_kit()

    assert released.success
    assert controller.xray_target_snapshot().effective_target_ids == {"chassis"}


def test_empty_effective_xray_targets_stop_activity_without_material_deletion(
    tmp_path,
    monkeypatch,
):
    from pxr import Usd, UsdGeom

    from digital_twin_runtime_suite.app.flow.performance import (
        ViewportPerformanceSample,
    )
    from digital_twin_runtime_suite.app.xray import performance as xray_performance

    class _Carb:
        def __init__(self):
            self.messages = []

        def log_warn(self, message):
            self.messages.append(message)

        def log_error(self, message):
            self.messages.append(message)

    carb = _Carb()
    monkeypatch.setitem(sys.modules, "carb", carb)
    monkeypatch.setattr(
        xray_performance,
        "capture_viewport_performance_sample",
        lambda: ViewportPerformanceSample(0.0, 60.0, 16.0, 4.0, 6.0),
    )
    controller = RuntimeController(_write_xray_config(tmp_path))
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.Mesh.Define(stage, f"{XRAY_CHASSIS_ROOT_PATH}/Panel")
    _install_omni_usd_stage(monkeypatch, stage)
    material = controller.config.chassis_presentation.materials.xray

    assert controller.apply_manual_xray_material_in_kit(material, {"chassis"}).success
    assert controller._xray_material_active is True
    assert stage.GetPrimAtPath(controller.XRAY_MATERIAL_PATH).IsValid()

    result = controller.apply_manual_xray_material_in_kit(material, frozenset())

    assert result.success
    assert controller.xray_target_snapshot().effective_target_ids == frozenset()
    assert controller._xray_material_active is False
    assert controller._xray_material_performance_started_at is None
    assert stage.GetPrimAtPath(controller.XRAY_MATERIAL_PATH).IsValid()

    carb.messages.clear()
    assert controller.advance_xray_material_performance_sampler_in_kit() is False
    assert not any("PERFORMANCE" in message for message in carb.messages)


def test_xray_off_is_idempotent_and_restores_prior_session_binding(tmp_path):
    from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade

    controller = RuntimeController(_write_xray_config(tmp_path))
    stage, meshes, _baseline = _production_xray_stage(Usd, UsdGeom, UsdShade, 1)
    mesh = meshes[0]
    stage.SetEditTarget(stage.GetSessionLayer())
    prior_material = UsdShade.Material.Define(stage, "/Looks/SessionPrior")
    UsdShade.MaterialBindingAPI.Apply(mesh).Bind(prior_material)
    binding_path = mesh.GetPath().AppendProperty("material:binding")
    prior_targets = list(
        stage.GetSessionLayer()
        .GetPropertyAtPath(binding_path)
        .targetPathList.explicitItems
    )

    controller._apply_xray_session_overrides(
        stage, XRayMaterialConfig(), {"chassis"}, Gf, Sdf, Usd, UsdShade
    )
    controller._clear_xray_session_overrides(stage, Sdf, Usd, UsdShade)

    restored = stage.GetSessionLayer().GetPropertyAtPath(binding_path)
    assert list(restored.targetPathList.explicitItems) == prior_targets
    assert _bound_material_path(mesh, UsdShade) == "/Looks/SessionPrior"
    removed_count, diagnostics = controller._clear_xray_session_overrides(
        stage, Sdf, Usd, UsdShade
    )
    assert removed_count == 0
    assert diagnostics == []


def test_xray_stage_loss_discards_stale_session_snapshot(tmp_path):
    from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade

    controller = RuntimeController(_write_xray_config(tmp_path))
    stage, meshes, baseline = _production_xray_stage(Usd, UsdGeom, UsdShade, 1)
    stage.SetEditTarget(stage.GetSessionLayer())
    controller._apply_xray_session_overrides(
        stage, XRayMaterialConfig(), {"chassis"}, Gf, Sdf, Usd, UsdShade
    )

    replacement = Usd.Stage.CreateInMemory()
    replacement.SetEditTarget(replacement.GetSessionLayer())
    removed_count, _diagnostics = controller._clear_xray_session_overrides(
        replacement, Sdf, Usd, UsdShade
    )

    assert removed_count == 0
    assert controller._xray_session_binding_snapshots == {}
    controller._clear_xray_session_overrides(stage, Sdf, Usd, UsdShade)
    assert _bound_material_path(meshes[0], UsdShade) == baseline
    assert (
        stage.GetSessionLayer().GetPropertyAtPath(
            meshes[0].GetPath().AppendProperty("material:binding")
        )
        is None
    )


def test_xray_failed_mixed_target_batch_rolls_back_all_ownership(tmp_path, monkeypatch):
    from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade

    controller = RuntimeController(_write_xray_config(tmp_path))
    static_path = f"{XRAY_CHASSIS_ROOT_PATH}/StaticPanel"
    led_path = f"{XRAY_CHASSIS_ROOT_PATH}/FrontPanelPower"
    indicators = FrontPanelIndicatorsConfig(enabled=True, power_path=led_path)
    controller.config = replace(
        controller.config,
        chassis_presentation=replace(
            controller.config.chassis_presentation,
            front_panel_indicators=indicators,
        ),
    )
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.Xform.Define(stage, XRAY_CHASSIS_ROOT_PATH)
    static = UsdGeom.Mesh.Define(stage, static_path).GetPrim()
    led = UsdGeom.Mesh.Define(stage, led_path).GetPrim()
    stage.SetEditTarget(stage.GetSessionLayer())
    telemetry_material = UsdShade.Material.Define(stage, "/Looks/TelemetryPrior")
    UsdShade.MaterialBindingAPI.Apply(led).Bind(telemetry_material)
    static_binding = static.GetPath().AppendProperty("material:binding")
    led_binding = led.GetPath().AppendProperty("material:binding")
    original_author = controller._author_xray_session_binding_spec

    def _skip_static(stage, property_path, sdf):
        if property_path != static_binding:
            original_author(stage, property_path, sdf)

    monkeypatch.setattr(controller, "_author_xray_session_binding_spec", _skip_static)
    with pytest.raises(RuntimeError, match="mismatch_count=1"):
        controller._apply_xray_session_overrides(
            stage, XRayMaterialConfig(), {"chassis"}, Gf, Sdf, Usd, UsdShade
        )

    assert stage.GetSessionLayer().GetPropertyAtPath(static_binding) is None
    assert not controller._session_binding_is_xray_owned(stage, led_binding)
    assert _bound_material_path(led, UsdShade) == "/Looks/TelemetryPrior"


def test_xray_led_ownership_reapplies_current_telemetry_state_after_off(
    tmp_path, monkeypatch
):
    from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade

    from digital_twin_runtime_suite.app import commands

    controller = RuntimeController(_write_xray_config(tmp_path))
    paths = tuple(
        f"{XRAY_CHASSIS_ROOT_PATH}/FrontPanel{suffix}"
        for suffix in ("Power", "HDD", "LAN01", "LAN02")
    )
    indicators = FrontPanelIndicatorsConfig(
        enabled=True,
        power_path=paths[0],
        hdd_path=paths[1],
        lan_01_path=paths[2],
        lan_02_path=paths[3],
    )
    controller.config = replace(
        controller.config,
        chassis_presentation=replace(
            controller.config.chassis_presentation,
            front_panel_indicators=indicators,
        ),
    )
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.Xform.Define(stage, XRAY_CHASSIS_ROOT_PATH)
    for path in paths:
        UsdGeom.Mesh.Define(stage, path)
    stage.SetEditTarget(stage.GetSessionLayer())
    on_state = SimpleNamespace(power=True, hdd=True, lan_01=True, lan_02=True)
    off_state = SimpleNamespace(power=False, hdd=False, lan_01=False, lan_02=False)
    assert controller._apply_front_panel_indicator_state(
        stage, indicators, on_state, Gf, Sdf, Usd, UsdShade
    )

    controller._apply_xray_session_overrides(
        stage, XRayMaterialConfig(), {"chassis"}, Gf, Sdf, Usd, UsdShade
    )
    assert (
        controller._apply_front_panel_indicator_state(
            stage, indicators, off_state, Gf, Sdf, Usd, UsdShade
        )
        is False
    )
    controller._clear_xray_session_overrides(stage, Sdf, Usd, UsdShade)
    controller._front_panel_indicator_last_snapshot = SimpleNamespace(metrics={})
    monkeypatch.setattr(
        commands, "front_panel_indicator_state", lambda *_args, **_kwargs: off_state
    )
    reapplied, matches = controller._reapply_front_panel_indicator_current_state(
        stage, Gf, Sdf, Usd, UsdShade
    )

    assert reapplied is True
    assert matches is True
    for path in paths:
        assert (
            _bound_material_path(stage.GetPrimAtPath(path), UsdShade)
            == RuntimeController.FRONT_PANEL_MATERIAL_PATHS["off"]
        )


def test_live_production_fresnel_sync_updates_without_probe(tmp_path, monkeypatch):
    from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade

    stage = Usd.Stage.CreateInMemory()
    stage.SetEditTarget(stage.GetSessionLayer())
    RuntimeController._define_xray_fresnel_material(
        stage, RuntimeController.XRAY_MATERIAL_PATH, Sdf, UsdShade
    )
    values = (
        (0.1, 0.2, 0.3),
        (0.8, 0.7, 0.6),
        0.5,
        0.3,
        3.0,
        0.4,
        0.3,
        0.2,
        0.55,
        0.32,
        3.2,
        10000.0,
    )
    RuntimeController._set_xray_fresnel_material_values(
        stage,
        RuntimeController.XRAY_MATERIAL_PATH,
        values,
        Gf,
        Sdf,
        UsdShade,
        camera_position=(10.0, 20.0, 30.0),
    )
    camera = UsdGeom.Camera.Define(stage, "/DTRS_Runtime/ReviewCamera")
    camera.AddTranslateOp().Set(Gf.Vec3d(4.0, 5.0, 6.0))
    _install_omni_usd_stage(monkeypatch, stage)

    controller = RuntimeController(_write_xray_config(tmp_path))
    assert controller.sync_xray_fresnel_material_camera_in_kit() is True
    shader = UsdShade.Shader.Get(
        stage, f"{RuntimeController.XRAY_MATERIAL_PATH}/Shader"
    )
    assert tuple(shader.GetInput("camera_position").Get()) == pytest.approx(
        (4.0, 5.0, 6.0)
    )


def test_production_xray_performance_and_diagnostics_are_non_fatal(
    tmp_path, monkeypatch
):
    from digital_twin_runtime_suite.app import commands
    from digital_twin_runtime_suite.app.flow.performance import (
        ViewportPerformanceSample,
    )
    from digital_twin_runtime_suite.app.xray import performance as xray_performance

    class _Carb:
        def __init__(self):
            self.messages = []

        def log_warn(self, message):
            self.messages.append(message)

    controller = RuntimeController(_write_xray_config(tmp_path))
    samples = iter(
        (
            ViewportPerformanceSample(0.0, 60.0, 16.0, 4.0, 6.0),
            ViewportPerformanceSample(10.0, 50.0, 20.0, 4.5, 6.5),
        )
    )
    monkeypatch.setattr(
        xray_performance, "capture_viewport_performance_sample", lambda: next(samples)
    )
    monkeypatch.setattr(commands.time, "monotonic", lambda: 10.0)
    controller._start_xray_material_performance_sampler()
    carb = _Carb()
    controller._advance_xray_material_performance_sampler(carb)
    controller._log_xray_lifecycle_diagnostic(
        carb, action="OFF", formatter=lambda: (_ for _ in ()).throw(RuntimeError("x"))
    )

    assert "DTRS X-Ray binding lifecycle - PERFORMANCE" in carb.messages[0]
    assert "diagnostic: <inspection failed: x>" in carb.messages[1]


def _production_xray_stage(Usd, UsdGeom, UsdShade, mesh_count):
    stage = Usd.Stage.CreateInMemory()
    source = UsdShade.Material.Define(stage, "/Looks/AuthoredChassis")
    UsdGeom.Xform.Define(stage, XRAY_CHASSIS_ROOT_PATH)
    meshes = []
    for index in range(mesh_count):
        mesh = UsdGeom.Mesh.Define(
            stage, f"{XRAY_CHASSIS_ROOT_PATH}/Static{index}"
        ).GetPrim()
        UsdShade.MaterialBindingAPI.Apply(mesh).Bind(source)
        meshes.append(mesh)
    return stage, meshes, str(source.GetPath())


def _bound_material_path(mesh, UsdShade) -> str | None:
    material, _binding = UsdShade.MaterialBindingAPI(mesh).ComputeBoundMaterial()
    return str(material.GetPath()) if material else None


def _install_omni_usd_stage(monkeypatch, stage):
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


def _write_xray_config(tmp_path) -> Path:
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
                "",
                "[chassis_presentation.materials.xray]",
                "",
                "[chassis_presentation.xray_target_groups.chassis]",
                'label = "Chassis - SilverStone RM44"',
                'paths = ["/blackwell_rig/chassis"]',
            )
        ),
        encoding="utf-8",
    )
    return config_path
