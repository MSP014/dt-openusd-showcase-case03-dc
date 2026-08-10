from pathlib import Path

import pytest

from digital_twin_runtime_suite.app.commands import RuntimeController
from digital_twin_runtime_suite.app.config import RuntimeConfig, XRayMaterialConfig
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
    values = ((1.0, 1.0, 0.0), (0.0, 0.0, 1.0), 0.65, 0.2, 1.0)
    camera_position = (10.0, 20.0, 30.0)

    RuntimeController._set_xray_fresnel_probe_values(
        stage, values, Gf, Sdf, UsdShade, camera_position=camera_position
    )
    shader = UsdShade.Shader.Get(
        stage, f"{RuntimeController.XRAY_PROBE_MATERIAL_PATH}/Shader"
    )
    assert tuple(shader.GetInput("camera_position").Get()) == camera_position

    updated_values = ((0.1, 0.2, 0.3), (0.4, 0.5, 0.6), 0.25, 0.5, 4.0)
    geometry_paths = (cube.GetPath(), sphere.GetPath())
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
    assert not shader.GetInput("edge_power")
    assert all(stage.GetPrimAtPath(path).IsValid() for path in geometry_paths)
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
