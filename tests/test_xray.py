from pathlib import Path

import pytest

from digital_twin_runtime_suite.app.commands import RuntimeController, XRayApplyResult
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


class _FakeSdfTypeIndicator:
    def __init__(self, sdf_type):
        self._sdf_type = sdf_type

    def GetSdfType(self):
        return self._sdf_type


class _FakeSdrProperty:
    def __init__(self, sdf_type, metadata):
        self._sdf_type = sdf_type
        self._metadata = metadata

    def GetTypeAsSdfType(self):
        return _FakeSdfTypeIndicator(self._sdf_type)

    def GetMetadata(self):
        return self._metadata

    @staticmethod
    def GetType():
        return "token"


class _FakeSurfaceFalloffNode:
    def __init__(self, token_type):
        material_metadata = {
            "renderType": "struct",
            "structType": "material",
            "symbol": "::material",
        }
        self._inputs = {
            "base": _FakeSdrProperty(token_type, material_metadata),
            "blend": _FakeSdrProperty(token_type, material_metadata),
        }
        self._outputs = {"out": _FakeSdrProperty(token_type, material_metadata)}

    def GetShaderInput(self, name):
        return self._inputs.get(name)

    def GetShaderOutput(self, name):
        return self._outputs.get(name)

    @staticmethod
    def GetModuleUsdIdentifier():
        return "nvidia/core_definitions.mdl"

    @staticmethod
    def GetSubIdentifier():
        return "surface_falloff"

    @staticmethod
    def GetNameWithSignature():
        return "surface_falloff(material,material,float,float,float)"

    @staticmethod
    def GetMetadata():
        return {}


class _FakeUsdMdl:
    class RegistryUtils:
        @staticmethod
        def GetShaderNodeForPrim(_prim):
            from pxr import Sdf

            return _FakeSurfaceFalloffNode(Sdf.ValueTypeNames.Token)


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


@pytest.mark.parametrize(
    ("probe", "weights", "blend_part"),
    (
        (1, (0.0, 0.0), "PartB"),
        (2, (1.0, 1.0), "PartB"),
        (3, (0.0, 1.0), "PartB"),
        (4, (1.0, 1.0), "PartA"),
    ),
)
def test_xray_surface_falloff_isolation_graph_uses_two_opaque_colour_only_parts(
    probe, weights, blend_part
):
    from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade

    stage = Usd.Stage.CreateInMemory()
    mesh = UsdGeom.Mesh.Define(
        stage,
        "/blackwell_rig/chassis/geo/render/chassis/side/left_side_plate",
    ).GetPrim()

    stage.SetEditTarget(stage.GetSessionLayer())
    material = RuntimeController._define_xray_material(
        stage,
        weights,
        blend_part,
        Gf,
        Sdf,
        UsdShade,
        _FakeUsdMdl,
    )
    bound_count = RuntimeController._bind_xray_material_to_chassis(
        stage,
        stage.GetPrimAtPath(RuntimeController.XRAY_CHASSIS_ROOT_PATH),
        material,
        Usd,
        UsdShade,
    )

    assert bound_count == 1
    assert (
        _bound_material_path(stage, mesh, UsdShade)
        == RuntimeController.XRAY_MATERIAL_PATH
    )
    falloff = UsdShade.Shader.Get(
        stage, f"{RuntimeController.XRAY_MATERIAL_PATH}/SurfaceFalloff"
    )
    assert falloff.GetSourceAsset("mdl").path == "nvidia/core_definitions.mdl"
    assert falloff.GetSourceAssetSubIdentifier("mdl") == "surface_falloff"
    assert falloff.GetInput("base").GetTypeName() == Sdf.ValueTypeNames.Token
    assert falloff.GetInput("blend").GetTypeName() == Sdf.ValueTypeNames.Token
    expected_material_metadata = {
        "renderType": "struct",
        "structType": "material",
        "symbol": "::material",
    }
    assert (
        falloff.GetInput("base").GetAttr().GetMetadata("sdrMetadata")
        == expected_material_metadata
    )
    assert (
        falloff.GetInput("blend").GetAttr().GetMetadata("sdrMetadata")
        == expected_material_metadata
    )
    assert falloff.GetInput("facing_weight").Get() == weights[0]
    assert falloff.GetInput("edge_weight").Get() == weights[1]
    assert falloff.GetInput("blend_bias").Get() == 5.0
    assert (
        falloff.GetInput("blend").GetConnectedSource()[0].GetPrim().GetName()
        == blend_part
    )
    part_a = UsdShade.Shader.Get(stage, f"{RuntimeController.XRAY_MATERIAL_PATH}/PartA")
    part_b = UsdShade.Shader.Get(stage, f"{RuntimeController.XRAY_MATERIAL_PATH}/PartB")
    assert part_a.GetInput("diffuse_reflection_color").Get() == Gf.Vec3f(1, 1, 0)
    assert part_b.GetInput("diffuse_reflection_color").Get() == Gf.Vec3f(0, 0, 1)
    assert part_a.GetInput("diffuse_reflection_roughness").Get() == pytest.approx(0.4)
    assert part_b.GetInput("diffuse_reflection_roughness").Get() == pytest.approx(0.4)
    assert part_a.GetInput("enable_opacity").Get() is False
    assert part_b.GetInput("enable_opacity").Get() is False
    assert not part_a.GetInput("geometry_opacity")
    assert not part_b.GetInput("geometry_opacity")
    assert not part_a.GetInput("emission_color")
    assert not part_b.GetInput("emission_color")
    assert "xray_material" in stage.GetSessionLayer().ExportToString()
    assert "xray_material" not in stage.GetRootLayer().ExportToString()
    snapshot = RuntimeController._format_xray_material_state(
        stage,
        requested_selected=True,
        result=XRayApplyResult(True, "X-Ray applied."),
        Sdf=Sdf,
        Usd=Usd,
        UsdShade=UsdShade,
    )
    assert "state: B" in snapshot
    assert "xray_direct_count: 1" in snapshot
    assert "resolved: /DTRS_Runtime/Looks/xray_material (1)" in snapshot
    assert (
        "material.outputs:mdl:surface -> "
        "/DTRS_Runtime/Looks/xray_material/SurfaceFalloff.outputs:out" in snapshot
    )
    assert f"facing={weights[0]}; edge={weights[1]}; bias=5.0" in snapshot
    assert RuntimeController._xray_surface_falloff_probe(probe)[:2] == weights
    assert RuntimeController._xray_surface_falloff_probe(probe)[4] == blend_part
    isolation_snapshot = RuntimeController._format_xray_surface_falloff_isolation_state(
        stage,
        probe,
        XRayApplyResult(True, "Probe applied."),
        Usd,
        UsdShade,
    )
    assert f"Probe {probe}" in isolation_snapshot
    assert "xray_direct_bindings: 1/1" in isolation_snapshot
    assert (
        "representative_binding: /DTRS_Runtime/Looks/xray_material"
        in isolation_snapshot
    )
    assert (
        "PartA: color=(1, 1, 0); opacity_enabled=False; emission_input=False"
        in isolation_snapshot
    )
    assert (
        "PartB: color=(0, 0, 1); opacity_enabled=False; emission_input=False"
        in isolation_snapshot
    )
    registry_snapshot = RuntimeController._format_xray_surface_falloff_registry(
        falloff, _FakeUsdMdl
    )
    assert "module=nvidia/core_definitions.mdl" in registry_snapshot
    assert "subIdentifier=surface_falloff" in registry_snapshot
    assert "base: registry_sdf=token; registry_sdr=token" in registry_snapshot
    assert "blend: registry_sdf=token; registry_sdr=token" in registry_snapshot
    assert "out: registry_sdf=token; registry_sdr=token" in registry_snapshot


def test_xray_clear_restores_authored_binding_without_touching_visibility():
    from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade

    stage = Usd.Stage.CreateInMemory()
    source = UsdShade.Material.Define(stage, "/Looks/Source")
    mesh = UsdGeom.Mesh.Define(
        stage,
        "/blackwell_rig/chassis/geo/render/chassis/side/left_side_plate",
    ).GetPrim()
    UsdShade.MaterialBindingAPI.Apply(mesh).Bind(source)
    UsdGeom.Imageable(mesh).CreateVisibilityAttr().Set(UsdGeom.Tokens.invisible)
    stage.SetEditTarget(stage.GetSessionLayer())
    material = RuntimeController._define_xray_material(
        stage,
        (0.0, 1.0),
        "PartB",
        Gf,
        Sdf,
        UsdShade,
        _FakeUsdMdl,
    )
    RuntimeController._bind_xray_material_to_chassis(
        stage,
        stage.GetPrimAtPath(RuntimeController.XRAY_CHASSIS_ROOT_PATH),
        material,
        Usd,
        UsdShade,
    )

    removed_count = RuntimeController._clear_xray_session_overrides(
        stage, Usd, UsdShade
    )

    assert removed_count == 1
    assert _bound_material_path(stage, mesh, UsdShade) == "/Looks/Source"
    assert {
        str(path)
        for path in UsdShade.MaterialBindingAPI(mesh).GetDirectBindingRel().GetTargets()
    } == {"/Looks/Source"}
    assert UsdGeom.Imageable(mesh).GetVisibilityAttr().Get() == UsdGeom.Tokens.invisible
    assert "xray_material" not in stage.GetSessionLayer().ExportToString()


def _bound_material_path(stage, mesh, UsdShade) -> str | None:
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
