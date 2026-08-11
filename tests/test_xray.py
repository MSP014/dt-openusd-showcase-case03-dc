import sys
from pathlib import Path
from types import ModuleType

import pytest

from digital_twin_runtime_suite.app.commands import RuntimeController
from digital_twin_runtime_suite.app.config import (
    RuntimeConfig,
    XRayFresnelProbeConfig,
    XRayMaterialConfig,
)
from digital_twin_runtime_suite.app.view_controls import (
    bool_model_value,
    xray_material_config_from_models,
)


class _BoolModel:
    def __init__(self, value):
        self.as_bool = value


class _FloatModel:
    def __init__(self, value):
        self.as_float = value


class _StringModel:
    def __init__(self, value):
        self.as_string = value


class _KitBoolModel:
    as_bool = True

    @staticmethod
    def get_value_as_bool():
        return False


def test_bool_model_prefers_kit_value_accessor_over_legacy_attribute():
    assert bool_model_value(_KitBoolModel()) is False


def test_xray_controls_build_the_persisted_operator_state():
    xray = xray_material_config_from_models(
        _BoolModel(True),
        _FloatModel(0.15),
        _FloatModel(0.45),
        _StringModel("#B85CFF"),
        _StringModel("#14FF6B"),
        _FloatModel(0.7),
        _FloatModel(0.3),
        _FloatModel(2.5),
        _FloatModel(0.5),
    )
    assert xray == XRayMaterialConfig(
        chassis_selected=True,
        part_a_opacity=0.15,
        part_a_roughness=0.45,
        part_a_fallback_color=(0.7215686274509804, 0.3607843137254902, 1.0),
        part_b_color=(0.0784313725490196, 1.0, 0.4196078431372549),
        part_b_opacity=0.7,
        part_b_roughness=0.3,
        part_b_emission_intensity=2.5,
        edge_falloff=0.5,
    )


def test_xray_local_override_round_trips_without_runtime_activation(tmp_path):
    config_path = _write_xray_config(tmp_path)
    controller = RuntimeController(config_path)
    saved = controller.save_xray_material_override(
        XRayMaterialConfig(chassis_selected=True, part_a_opacity=0.2)
    )

    reloaded = RuntimeConfig.load(config_path)

    assert saved.exists()
    assert reloaded.chassis_presentation.materials.xray.chassis_selected is True
    assert reloaded.chassis_presentation.materials.xray.part_a_opacity == 0.2
    assert "[chassis_presentation.materials.xray]" in saved.read_text(encoding="utf-8")


def test_fresnel_probe_local_override_round_trips_without_probe_activation(tmp_path):
    config_path = _write_xray_config(tmp_path)
    controller = RuntimeController(config_path)
    saved = controller.save_xray_fresnel_probe_override(
        XRayFresnelProbeConfig(
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
    )

    reloaded = RuntimeConfig.load(config_path)

    assert saved.exists()
    assert reloaded.chassis_presentation.materials.xray_fresnel_probe == (
        XRayFresnelProbeConfig(
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
    )
    assert "[chassis_presentation.materials.xray_fresnel_probe]" in saved.read_text(
        encoding="utf-8"
    )


@pytest.mark.parametrize(
    ("model_index", "value", "message"),
    (
        (1, 1.1, "Part A opacity"),
        (5, -0.1, "Part B opacity"),
        (7, 1001.0, "Emission"),
    ),
)
def test_xray_controls_reject_invalid_numeric_values(model_index, value, message):
    models = [
        _BoolModel(True),
        _FloatModel(0.1),
        _FloatModel(0.4),
        _StringModel("#B85CFF"),
        _StringModel("#14FF6B"),
        _FloatModel(0.6),
        _FloatModel(0.3),
        _FloatModel(1.5),
        _FloatModel(0.5),
    ]
    models[model_index] = _FloatModel(value)

    with pytest.raises(ValueError, match=message):
        xray_material_config_from_models(*models)


def test_xray_clear_removes_only_session_binding_and_reveals_authored_source():
    from pxr import Sdf, Usd, UsdGeom, UsdShade

    stage = Usd.Stage.CreateInMemory()
    source = UsdShade.Material.Define(stage, "/Looks/Source")
    mesh = UsdGeom.Mesh.Define(
        stage,
        "/blackwell_rig/chassis/geo/render/chassis/side/left_side_plate",
    ).GetPrim()
    UsdShade.MaterialBindingAPI.Apply(mesh).Bind(source)
    UsdGeom.Imageable(mesh).CreateVisibilityAttr().Set(UsdGeom.Tokens.invisible)

    binding_path = mesh.GetPath().AppendProperty("material:binding")
    root_binding = stage.GetRootLayer().GetPropertyAtPath(binding_path)
    assert root_binding is not None
    assert list(root_binding.targetPathList.explicitItems) == [
        Sdf.Path("/Looks/Source")
    ]

    stage.SetEditTarget(stage.GetSessionLayer())
    xray = UsdShade.Material.Define(stage, RuntimeController.XRAY_MATERIAL_PATH)
    UsdShade.MaterialBindingAPI.Apply(mesh).Bind(xray)
    assert _bound_material_path(mesh, UsdShade) == RuntimeController.XRAY_MATERIAL_PATH
    assert stage.GetSessionLayer().GetPropertyAtPath(binding_path) is not None

    removed_count = RuntimeController._clear_xray_session_overrides(
        stage, Usd, UsdShade
    )

    assert removed_count == 1
    assert _bound_material_path(mesh, UsdShade) == "/Looks/Source"
    assert stage.GetSessionLayer().GetPropertyAtPath(binding_path) is None
    assert list(root_binding.targetPathList.explicitItems) == [
        Sdf.Path("/Looks/Source")
    ]
    assert (
        stage.GetSessionLayer().GetPrimAtPath(RuntimeController.XRAY_MATERIAL_PATH)
        is None
    )
    assert UsdGeom.Imageable(mesh).GetVisibilityAttr().Get() == UsdGeom.Tokens.invisible


def test_fresnel_probe_sphere_is_a_smooth_high_resolution_mesh():
    from pxr import Gf, Usd, UsdGeom

    stage = Usd.Stage.CreateInMemory()
    sphere = RuntimeController._define_xray_fresnel_probe_sphere(
        stage,
        "/DTRS_Runtime/Debug/XRayProbe01/Sphere",
        2.0,
        Gf,
        UsdGeom,
    )

    longitude = RuntimeController.XRAY_PROBE_SPHERE_LONGITUDE_SEGMENTS
    latitude = RuntimeController.XRAY_PROBE_SPHERE_LATITUDE_SEGMENTS
    assert sphere.GetPrim().GetTypeName() == "Mesh"
    assert len(sphere.GetPointsAttr().Get()) == 2 + (latitude - 1) * longitude
    assert len(sphere.GetNormalsAttr().Get()) == 2 + (latitude - 1) * longitude
    assert len(sphere.GetFaceVertexCountsAttr().Get()) == 2 * longitude * (latitude - 1)
    assert sphere.GetNormalsInterpolation() == UsdGeom.Tokens.vertex


def test_fresnel_probe_scale_is_derived_from_server_bounds_only():
    assert RuntimeController.XRAY_PROBE_SIZE_FRACTION == pytest.approx(0.64)
    assert not hasattr(RuntimeController, "XRAY_PROBE_MINIMUM_SIZE")


def test_fresnel_probe_layout_scales_to_server_and_keeps_a_visible_gap():
    from pxr import Gf

    bbox = Gf.Range3d(Gf.Vec3d(-5.0, -2.0, -1.0), Gf.Vec3d(5.0, 2.0, 1.0))
    size, center, distance, gap = RuntimeController._xray_fresnel_probe_layout(bbox)

    assert size == pytest.approx(10.0 * 0.64)
    assert tuple(center) == pytest.approx((0.0, 0.0, 0.0))
    # The centre distance leaves a quarter-width gap between cube and sphere.
    assert gap == pytest.approx(size * 0.25)
    assert distance - size == pytest.approx(gap)


def test_fresnel_probe_geometry_uses_computed_size_and_stays_separated():
    from pxr import Gf, Usd, UsdGeom

    stage = Usd.Stage.CreateInMemory()
    bbox = Gf.Range3d(Gf.Vec3d(-5.0, -2.0, -1.0), Gf.Vec3d(5.0, 2.0, 1.0))
    cube, sphere = RuntimeController._define_xray_fresnel_probe_geometry(
        stage, bbox, Gf, UsdGeom
    )
    cube_size, _center, distance, gap = RuntimeController._xray_fresnel_probe_layout(
        bbox
    )
    sphere_points = sphere.GetPointsAttr().Get()
    sphere_radius = max(
        sum(float(component) ** 2 for component in point) ** 0.5
        for point in sphere_points
    )

    assert cube.GetSizeAttr().Get() == pytest.approx(cube_size)
    assert sphere_radius == pytest.approx(cube_size * 0.5)
    assert distance - cube_size * 0.5 - sphere_radius == pytest.approx(gap)


def test_fresnel_probe_geometry_state_reports_authored_dimensions(tmp_path):
    from pxr import Gf, Usd, UsdGeom

    stage = Usd.Stage.CreateInMemory()
    server = UsdGeom.Xform.Define(stage, RuntimeController.XRAY_PROBE_SERVER_PATH)
    server_bounds = UsdGeom.Cube.Define(
        stage, f"{RuntimeController.XRAY_PROBE_SERVER_PATH}/bounds"
    )
    server_bounds.CreateSizeAttr(10.0)
    # Match the imported server: render-purpose geometry must be included in
    # the probe bounds instead of silently producing an empty default-purpose
    # range.
    server_bounds.GetPurposeAttr().Set(UsdGeom.Tokens.render)
    bbox = RuntimeController._xray_fresnel_probe_server_bbox(
        server.GetPrim(), Usd, UsdGeom
    )
    assert bbox is not None

    controller = RuntimeController(_write_xray_config(tmp_path))
    controller._xray_probe_server_bbox_snapshot = bbox
    cube, sphere = controller._define_xray_fresnel_probe_geometry(
        stage, bbox, Gf, UsdGeom
    )
    state = controller._xray_fresnel_probe_geometry_state(stage, Usd, UsdGeom)

    expected_size = 10.0 * controller.XRAY_PROBE_SIZE_FRACTION
    assert cube.GetSizeAttr().Get() == pytest.approx(expected_size)
    assert sphere.GetPrim().IsValid()
    assert state["server_bbox_max_extent"] == pytest.approx(10.0)
    assert state["probe_size"] == pytest.approx(expected_size)
    assert state["cube_size"] == pytest.approx(expected_size)
    assert state["sphere_radius"] == pytest.approx(expected_size * 0.5)
    assert state["gap"] == pytest.approx(expected_size * 0.25)
    assert state["center_distance"] == pytest.approx(expected_size * 1.25)


@pytest.mark.parametrize(
    ("had_prior_session_visibility", "expected_session_visibility"),
    (
        (False, None),
        (True, "invisible"),
    ),
)
def test_fresnel_probe_clear_removes_or_restores_only_its_session_visibility(
    tmp_path, had_prior_session_visibility, expected_session_visibility
):
    from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade

    stage = Usd.Stage.CreateInMemory()
    server = UsdGeom.Xform.Define(
        stage, RuntimeController.XRAY_PROBE_SERVER_PATH
    ).GetPrim()
    camera = UsdGeom.Camera.Define(stage, "/DTRS_Runtime/ReviewCamera")
    camera.AddTranslateOp().Set(Gf.Vec3d(10.0, 20.0, 30.0))
    visibility = UsdGeom.Imageable(server).GetVisibilityAttr()
    stage.SetEditTarget(stage.GetSessionLayer())
    if had_prior_session_visibility:
        visibility.Set(UsdGeom.Tokens.invisible)

    controller = RuntimeController(_write_xray_config(tmp_path))
    controller._xray_probe_visibility_state = (
        had_prior_session_visibility,
        visibility.Get() if had_prior_session_visibility else None,
    )
    visibility.Set(UsdGeom.Tokens.invisible)
    UsdGeom.Xform.Define(stage, RuntimeController.XRAY_PROBE_ROOT_PATH)
    RuntimeController._define_xray_fresnel_probe_material(stage, Sdf, UsdShade)
    camera_before_clear = controller._xray_fresnel_probe_camera_position(
        stage, Usd, UsdGeom
    )

    controller._clear_xray_fresnel_probe(stage)

    session_spec = stage.GetSessionLayer().GetPropertyAtPath(visibility.GetPath())
    if expected_session_visibility is None:
        assert session_spec is None
    else:
        assert session_spec is not None
        assert visibility.Get() == expected_session_visibility
    assert not stage.GetPrimAtPath(RuntimeController.XRAY_PROBE_ROOT_PATH).IsValid()
    assert not stage.GetPrimAtPath(RuntimeController.XRAY_PROBE_MATERIAL_PATH).IsValid()
    assert controller._xray_fresnel_probe_camera_position(stage, Usd, UsdGeom) == (
        camera_before_clear
    )


def test_fresnel_mdl_uses_an_explicit_camera_position_view_vector():
    mdl_path = (
        Path(__file__).parents[1]
        / "src"
        / "digital_twin_runtime_suite"
        / "ext"
        / "msp.dtrs"
        / "data"
        / "materials"
        / "DTRS_Fresnel_Test.mdl"
    )

    source = mdl_path.read_text(encoding="utf-8")

    assert "state::normal()" in source
    assert "state::position()" in source
    assert "float3 camera_position" in source
    assert "camera_position - P" in source
    assert "dtrs_smoothstep" in source
    assert "math::pow" in source
    assert "raw_edge" in source
    assert "edge_sharpness" in source
    assert "float facing_opacity = 0.20" in source
    assert "float edge_opacity = 0.55" in source
    assert "float final_opacity" in source
    assert "dtrs_clamp01(facing_opacity) * (1.0 - mask)" in source
    assert "dtrs_clamp01(edge_opacity) * mask" in source
    assert "cutout_opacity: final_opacity" in source
    assert "float facing_roughness = 0.40" in source
    assert "float edge_roughness = 0.30" in source
    assert "float final_roughness" in source
    assert "dtrs_clamp01(facing_roughness) * (1.0 - mask)" in source
    assert "dtrs_clamp01(edge_roughness) * mask" in source
    assert "df::microfacet_ggx_smith_bsdf" in source
    assert "roughness_u: final_roughness" in source
    assert "roughness_v: final_roughness" in source
    assert "df::weighted_layer" in source
    assert "scattering: surface_scattering" in source
    assert "float facing_emission = 0.32" in source
    assert "float edge_emission = 3.20" in source
    assert "float emission_scale = 10000.0" in source
    assert "float artist_emission" in source
    assert "float final_emission" in source
    assert "artist_emission *" in source
    assert "(emission_scale < 0.0 ? 0.0 : emission_scale)" in source
    assert "final_color * color(final_emission)" in source
    assert "df::diffuse_edf()" in source
    assert "intensity: final_emission_color" in source
    assert "edge_power" not in source
    assert "state::direction()" not in source


def test_fresnel_probe_parameter_updates_preserve_geometry_and_camera(tmp_path):
    from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade

    stage = Usd.Stage.CreateInMemory()
    stage.SetEditTarget(stage.GetSessionLayer())
    RuntimeController._define_xray_fresnel_probe_material(stage, Sdf, UsdShade)
    cube = UsdGeom.Cube.Define(stage, f"{RuntimeController.XRAY_PROBE_ROOT_PATH}/Cube")
    sphere = UsdGeom.Sphere.Define(
        stage, f"{RuntimeController.XRAY_PROBE_ROOT_PATH}/Sphere"
    )
    camera = UsdGeom.Camera.Define(stage, "/DTRS_Runtime/ReviewCamera")
    camera.AddTranslateOp().Set(Gf.Vec3d(10.0, 20.0, 30.0))
    values = (
        (1.0, 1.0, 0.0),
        (0.0, 0.0, 1.0),
        0.65,
        0.2,
        1.0,
        0.4,
        0.3,
        0.2,
        0.55,
        0.32,
        3.2,
        10000.0,
    )
    camera_position = (10.0, 20.0, 30.0)

    RuntimeController._set_xray_fresnel_probe_values(
        stage, values, Gf, Sdf, UsdShade, camera_position=camera_position
    )
    shader = UsdShade.Shader.Get(
        stage, f"{RuntimeController.XRAY_PROBE_MATERIAL_PATH}/Shader"
    )
    assert tuple(shader.GetInput("camera_position").Get()) == camera_position

    updated_values = (
        (0.1, 0.2, 0.3),
        (0.4, 0.5, 0.6),
        0.25,
        0.5,
        4.0,
        0.9,
        0.1,
        0.35,
        0.8,
        1.2,
        6.4,
        5000.0,
    )
    probe_paths = (
        cube.GetPath(),
        sphere.GetPath(),
        f"{RuntimeController.XRAY_PROBE_MATERIAL_PATH}/Shader",
    )
    camera_before_update = RuntimeController._xray_fresnel_probe_camera_position(
        stage, Usd, UsdGeom
    )
    RuntimeController._set_xray_fresnel_probe_values(
        stage, updated_values, Gf, Sdf, UsdShade
    )

    assert tuple(shader.GetInput("camera_position").Get()) == camera_position
    assert tuple(shader.GetInput("facing_color").Get()) == pytest.approx(
        updated_values[0]
    )
    assert tuple(shader.GetInput("edge_color").Get()) == pytest.approx(
        updated_values[1]
    )
    assert shader.GetInput("edge_center").Get() == pytest.approx(updated_values[2])
    assert shader.GetInput("edge_softness").Get() == pytest.approx(updated_values[3])
    assert shader.GetInput("edge_sharpness").Get() == pytest.approx(updated_values[4])
    assert shader.GetInput("facing_roughness").Get() == pytest.approx(updated_values[5])
    assert shader.GetInput("edge_roughness").Get() == pytest.approx(updated_values[6])
    assert shader.GetInput("facing_opacity").Get() == pytest.approx(updated_values[7])
    assert shader.GetInput("edge_opacity").Get() == pytest.approx(updated_values[8])
    assert shader.GetInput("facing_emission").Get() == pytest.approx(updated_values[9])
    assert shader.GetInput("edge_emission").Get() == pytest.approx(updated_values[10])
    assert shader.GetInput("emission_scale").Get() == pytest.approx(updated_values[11])

    scale_only_values = updated_values[:-1] + (50000.0,)
    RuntimeController._set_xray_fresnel_probe_values(
        stage, scale_only_values, Gf, Sdf, UsdShade
    )

    assert shader.GetInput("emission_scale").Get() == pytest.approx(50000.0)
    assert tuple(shader.GetInput("facing_color").Get()) == pytest.approx(
        updated_values[0]
    )
    assert tuple(shader.GetInput("edge_color").Get()) == pytest.approx(
        updated_values[1]
    )
    assert shader.GetInput("edge_center").Get() == pytest.approx(updated_values[2])
    assert shader.GetInput("edge_softness").Get() == pytest.approx(updated_values[3])
    assert shader.GetInput("edge_sharpness").Get() == pytest.approx(updated_values[4])
    assert shader.GetInput("facing_roughness").Get() == pytest.approx(updated_values[5])
    assert shader.GetInput("edge_roughness").Get() == pytest.approx(updated_values[6])
    assert shader.GetInput("facing_opacity").Get() == pytest.approx(updated_values[7])
    assert shader.GetInput("edge_opacity").Get() == pytest.approx(updated_values[8])
    assert shader.GetInput("facing_emission").Get() == pytest.approx(updated_values[9])
    assert shader.GetInput("edge_emission").Get() == pytest.approx(updated_values[10])

    roughness_only_values = updated_values[:5] + (0.0, 1.0) + updated_values[7:]
    RuntimeController._set_xray_fresnel_probe_values(
        stage, roughness_only_values, Gf, Sdf, UsdShade
    )

    assert shader.GetInput("facing_roughness").Get() == pytest.approx(0.0)
    assert shader.GetInput("edge_roughness").Get() == pytest.approx(1.0)
    assert tuple(shader.GetInput("facing_color").Get()) == pytest.approx(
        updated_values[0]
    )
    assert tuple(shader.GetInput("edge_color").Get()) == pytest.approx(
        updated_values[1]
    )
    assert shader.GetInput("edge_center").Get() == pytest.approx(updated_values[2])
    assert shader.GetInput("edge_softness").Get() == pytest.approx(updated_values[3])
    assert shader.GetInput("edge_sharpness").Get() == pytest.approx(updated_values[4])
    assert shader.GetInput("facing_opacity").Get() == pytest.approx(updated_values[7])
    assert shader.GetInput("edge_opacity").Get() == pytest.approx(updated_values[8])
    assert shader.GetInput("facing_emission").Get() == pytest.approx(updated_values[9])
    assert shader.GetInput("edge_emission").Get() == pytest.approx(updated_values[10])
    assert shader.GetInput("emission_scale").Get() == pytest.approx(updated_values[11])
    assert not shader.GetInput("edge_power")
    assert all(stage.GetPrimAtPath(path).IsValid() for path in probe_paths)
    assert RuntimeController._xray_fresnel_probe_camera_position(
        stage, Usd, UsdGeom
    ) == (camera_before_update)


def test_fresnel_probe_camera_position_uses_review_camera_world_transform(tmp_path):
    from pxr import Gf, Usd, UsdGeom

    stage = Usd.Stage.CreateInMemory()
    camera = UsdGeom.Camera.Define(stage, "/DTRS_Runtime/ReviewCamera")
    camera.AddTranslateOp().Set(Gf.Vec3d(10.0, 20.0, 30.0))

    controller = RuntimeController(_write_xray_config(tmp_path))
    assert controller._xray_fresnel_probe_camera_position(stage, Usd, UsdGeom) == (
        10.0,
        20.0,
        30.0,
    )


def _fresnel_probe_sync_stage(tmp_path):
    from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade

    stage = Usd.Stage.CreateInMemory()
    stage.SetEditTarget(stage.GetSessionLayer())
    UsdGeom.Xform.Define(stage, RuntimeController.XRAY_PROBE_ROOT_PATH)
    RuntimeController._define_xray_fresnel_probe_material(stage, Sdf, UsdShade)
    camera = UsdGeom.Camera.Define(stage, "/DTRS_Runtime/ReviewCamera")
    camera.AddTranslateOp().Set(Gf.Vec3d(10.0, 20.0, 30.0))
    controller = RuntimeController(_write_xray_config(tmp_path))
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
    RuntimeController._set_xray_fresnel_probe_values(
        stage, values, Gf, Sdf, UsdShade, camera_position=(10.0, 20.0, 30.0)
    )
    return controller, stage, camera, values


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


def test_live_fresnel_probe_sync_noops_when_probe_is_absent(tmp_path, monkeypatch):
    from pxr import Usd

    controller = RuntimeController(_write_xray_config(tmp_path))
    stage = Usd.Stage.CreateInMemory()
    _install_omni_usd_stage(monkeypatch, stage)

    assert controller.sync_xray_fresnel_probe_camera_in_kit() is False


def test_live_fresnel_probe_sync_noops_when_camera_is_unchanged(tmp_path, monkeypatch):
    from pxr import UsdShade

    controller, stage, _camera, _values = _fresnel_probe_sync_stage(tmp_path)
    _install_omni_usd_stage(monkeypatch, stage)
    shader = UsdShade.Shader.Get(
        stage, f"{RuntimeController.XRAY_PROBE_MATERIAL_PATH}/Shader"
    )
    before = tuple(shader.GetInput("camera_position").Get())

    assert controller.sync_xray_fresnel_probe_camera_in_kit() is False
    assert tuple(shader.GetInput("camera_position").Get()) == before
    assert controller._xray_probe_live_camera_sync_updates == 0


def test_live_fresnel_probe_sync_updates_moved_camera(tmp_path, monkeypatch):
    from pxr import Gf, UsdShade

    controller, stage, camera, _values = _fresnel_probe_sync_stage(tmp_path)
    _install_omni_usd_stage(monkeypatch, stage)
    camera.GetOrderedXformOps()[0].Set(Gf.Vec3d(4.0, 5.0, 6.0))
    shader = UsdShade.Shader.Get(
        stage, f"{RuntimeController.XRAY_PROBE_MATERIAL_PATH}/Shader"
    )

    assert controller.sync_xray_fresnel_probe_camera_in_kit() is True
    assert tuple(shader.GetInput("camera_position").Get()) == pytest.approx(
        (4.0, 5.0, 6.0)
    )
    assert controller._xray_probe_live_camera_sync_updates == 1


def test_live_fresnel_probe_sync_preserves_mask_inputs(tmp_path, monkeypatch):
    from pxr import Gf, UsdShade

    controller, stage, camera, values = _fresnel_probe_sync_stage(tmp_path)
    _install_omni_usd_stage(monkeypatch, stage)
    camera.GetOrderedXformOps()[0].Set(Gf.Vec3d(4.0, 5.0, 6.0))
    shader = UsdShade.Shader.Get(
        stage, f"{RuntimeController.XRAY_PROBE_MATERIAL_PATH}/Shader"
    )

    assert controller.sync_xray_fresnel_probe_camera_in_kit() is True
    assert tuple(shader.GetInput("facing_color").Get()) == pytest.approx(values[0])
    assert tuple(shader.GetInput("edge_color").Get()) == pytest.approx(values[1])
    assert shader.GetInput("edge_center").Get() == pytest.approx(values[2])
    assert shader.GetInput("edge_softness").Get() == pytest.approx(values[3])
    assert shader.GetInput("edge_sharpness").Get() == pytest.approx(values[4])
    assert shader.GetInput("facing_roughness").Get() == pytest.approx(values[5])
    assert shader.GetInput("edge_roughness").Get() == pytest.approx(values[6])
    assert shader.GetInput("facing_opacity").Get() == pytest.approx(values[7])
    assert shader.GetInput("edge_opacity").Get() == pytest.approx(values[8])
    assert shader.GetInput("facing_emission").Get() == pytest.approx(values[9])
    assert shader.GetInput("edge_emission").Get() == pytest.approx(values[10])
    assert shader.GetInput("emission_scale").Get() == pytest.approx(values[11])


def test_live_fresnel_probe_sync_does_not_mutate_review_camera(tmp_path, monkeypatch):
    from pxr import Gf, Usd, UsdGeom

    controller, stage, camera, _values = _fresnel_probe_sync_stage(tmp_path)
    _install_omni_usd_stage(monkeypatch, stage)
    camera.GetOrderedXformOps()[0].Set(Gf.Vec3d(4.0, 5.0, 6.0))
    before = RuntimeController._xray_fresnel_probe_camera_position(stage, Usd, UsdGeom)

    assert controller.sync_xray_fresnel_probe_camera_in_kit() is True
    assert (
        RuntimeController._xray_fresnel_probe_camera_position(stage, Usd, UsdGeom)
        == before
    )


def test_live_fresnel_probe_sync_noops_after_clear(tmp_path, monkeypatch):
    controller, stage, _camera, _values = _fresnel_probe_sync_stage(tmp_path)
    _install_omni_usd_stage(monkeypatch, stage)
    stage.SetEditTarget(stage.GetSessionLayer())
    controller._clear_xray_fresnel_probe(stage)

    assert controller.sync_xray_fresnel_probe_camera_in_kit() is False


def test_fresnel_probe_clear_diagnostic_keeps_running_when_opacity_is_unavailable(
    tmp_path,
):
    from pxr import Usd, UsdGeom, UsdShade

    controller = RuntimeController(_write_xray_config(tmp_path))
    controller._xray_probe_last_values = (0.0,) * 5
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.Xform.Define(stage, RuntimeController.XRAY_PROBE_SERVER_PATH)

    output = controller._format_xray_fresnel_probe_clear_state(
        stage,
        Usd,
        UsdGeom,
        UsdShade,
        prior_visibility_state=None,
        camera_before_clear={
            "review_camera_position": (1.0, 2.0, 3.0),
            "camera_position_input": (1.0, 2.0, 3.0),
        },
        review_camera_after_clear=(1.0, 2.0, 3.0),
    )

    assert "opacity_before_clear={'facing_opacity': '<inspection failed:" in output
    assert "roughness_before_clear={'facing_roughness': '<inspection failed:" in output
    assert "emission_before_clear={'facing_emission': '<inspection failed:" in output


def test_fresnel_probe_emission_diagnostics_report_effective_endpoints(tmp_path):
    controller = RuntimeController(_write_xray_config(tmp_path))
    controller._xray_probe_last_values = (
        (0.1, 0.2, 0.3),
        (0.4, 0.5, 0.6),
        0.65,
        0.2,
        1.0,
        0.4,
        0.3,
        0.2,
        0.55,
        0.32,
        3.2,
        10000.0,
    )

    assert controller._xray_fresnel_probe_emission_state() == {
        "facing_emission": "0.32",
        "edge_emission": "3.20",
        "emission_scale": "10000.00",
        "effective_facing_emission": "3200.00",
        "effective_edge_emission": "32000.00",
    }


def test_live_fresnel_probe_performance_sampler_resets_without_duplicates(
    tmp_path, monkeypatch
):
    from digital_twin_runtime_suite.app.flow.performance import (
        ViewportPerformanceSample,
    )

    controller = RuntimeController(_write_xray_config(tmp_path))
    samples = iter(
        (
            ViewportPerformanceSample(0.0, 60.0, 16.67, 4.0, 6.0),
            ViewportPerformanceSample(1.0, 50.0, 20.0, 4.1, 6.1),
        )
    )
    monkeypatch.setattr(
        controller,
        "_capture_xray_fresnel_probe_performance_sample",
        lambda: next(samples),
    )

    controller._start_xray_fresnel_probe_performance_sampler()
    controller._start_xray_fresnel_probe_performance_sampler()

    assert controller._xray_probe_performance_started_at == 1.0
    assert controller._xray_probe_performance_samples == [
        ViewportPerformanceSample(1.0, 50.0, 20.0, 4.1, 6.1)
    ]


def test_live_fresnel_probe_performance_sampler_respects_sample_interval(
    tmp_path, monkeypatch
):
    from digital_twin_runtime_suite.app import commands
    from digital_twin_runtime_suite.app.flow.performance import (
        ViewportPerformanceSample,
    )

    controller = RuntimeController(_write_xray_config(tmp_path))
    samples = iter(
        (
            ViewportPerformanceSample(0.0, 60.0, 16.67, 4.0, 6.0),
            ViewportPerformanceSample(0.5, 50.0, 20.0, 4.1, 6.1),
        )
    )
    clock = iter((0.25, 0.5))
    monkeypatch.setattr(
        controller,
        "_capture_xray_fresnel_probe_performance_sample",
        lambda: next(samples),
    )
    monkeypatch.setattr(commands.time, "monotonic", lambda: next(clock))

    controller._start_xray_fresnel_probe_performance_sampler()
    controller._advance_xray_fresnel_probe_performance_sampler()
    controller._advance_xray_fresnel_probe_performance_sampler()

    assert len(controller._xray_probe_performance_samples) == 2


def test_live_fresnel_probe_performance_uses_viewport_statistics(tmp_path):
    from digital_twin_runtime_suite.app.flow.performance import (
        ViewportPerformanceSample,
    )

    controller = RuntimeController(_write_xray_config(tmp_path))
    controller._xray_probe_performance_samples = [
        ViewportPerformanceSample(0.0, 50.0, 20.0, 4.5, 6.0),
        ViewportPerformanceSample(0.5, 40.0, 25.0, 4.6, 6.1),
        ViewportPerformanceSample(1.0, 60.0, 16.0, 4.7, 6.2),
    ]

    assert controller._xray_fresnel_probe_performance_state() == {
        "fps_current": "60.00",
        "frame_time_ms_current": "16.00",
        "probe_avg_fps": "50.00",
        "probe_min_fps": "40.00",
        "probe_max_fps": "60.00",
        "probe_avg_frame_time_ms": "20.33",
        "gpu_used_gib": "4.70",
        "process_used_gib": "6.20",
    }


def test_live_fresnel_probe_performance_stop_clears_sampler_state(tmp_path):
    controller = RuntimeController(_write_xray_config(tmp_path))
    controller._xray_probe_performance_started_at = 0.0
    controller._xray_probe_performance_samples = [object()]

    controller._stop_xray_fresnel_probe_performance_sampler()

    assert controller._xray_probe_performance_started_at is None
    assert controller._xray_probe_performance_samples == []


def test_live_fresnel_probe_performance_unavailable_values_are_non_fatal(tmp_path):
    from digital_twin_runtime_suite.app.flow.performance import (
        ViewportPerformanceSample,
    )

    controller = RuntimeController(_write_xray_config(tmp_path))
    controller._xray_probe_performance_samples = [
        ViewportPerformanceSample(0.0, None, None, None, None)
    ]

    assert controller._xray_fresnel_probe_performance_state() == {
        "fps_current": "<unavailable>",
        "frame_time_ms_current": "<unavailable>",
        "probe_avg_fps": "<unavailable>",
        "probe_min_fps": "<unavailable>",
        "probe_max_fps": "<unavailable>",
        "probe_avg_frame_time_ms": "<unavailable>",
        "gpu_used_gib": "<unavailable>",
        "process_used_gib": "<unavailable>",
    }


def test_fresnel_probe_diagnostic_failure_cannot_escape_runtime_operation():
    class _Carb:
        def __init__(self):
            self.messages = []

        def log_warn(self, message):
            self.messages.append(message)

    carb = _Carb()
    RuntimeController._log_xray_fresnel_probe_diagnostic(
        carb,
        action="Probe 01",
        formatter=lambda: (_ for _ in ()).throw(RuntimeError("inspection failed")),
    )

    assert carb.messages == [
        "DTRS Custom MDL Fresnel Probe 01\n"
        "  action: Probe 01\n"
        "  diagnostic: <inspection failed: inspection failed>"
    ]


def _bound_material_path(mesh, UsdShade) -> str | None:
    material, _binding = UsdShade.MaterialBindingAPI(mesh).ComputeBoundMaterial()
    return str(material.GetPath()) if material else None


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
                "chassis_selected = false",
                "part_a_opacity = 0.1",
                "part_a_roughness = 0.4",
                "part_a_fallback_color = [0.72, 0.36, 1.0]",
                "part_b_color = [0.08, 1.0, 0.42]",
                "part_b_opacity = 0.6",
                "part_b_roughness = 0.3",
                "part_b_emission_intensity = 1.5",
                "edge_falloff = 0.5",
            )
        ),
        encoding="utf-8",
    )
    return config_path
