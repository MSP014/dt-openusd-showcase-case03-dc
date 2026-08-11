"""X-Ray material construction and parameter authoring for DTRS.

Owns transient runtime material graphs: the simple production Part A control
material and the project-owned Custom MDL material used by Debug Probe 01.
It does not decide which prims receive a material, manage Session Layer
binding ownership, or create probe geometry; those responsibilities live in
the runtime and probe sibling modules.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class XRayApplyResult:
    """Public result returned by X-Ray production and probe commands."""

    success: bool
    message: str
    target_count: int = 0
    used_fallback_color: bool = False


class XRayMaterialMixin:
    """Provide X-Ray material construction to the application runtime facade."""

    @classmethod
    def _define_xray_fresnel_probe_material(cls, stage, Sdf, UsdShade):
        """Define the debug MDL material without binding it to production geometry."""

        material = UsdShade.Material.Define(stage, cls.XRAY_PROBE_MATERIAL_PATH)
        shader = UsdShade.Shader.Define(stage, f"{cls.XRAY_PROBE_MATERIAL_PATH}/Shader")
        shader.CreateImplementationSourceAttr().Set(UsdShade.Tokens.sourceAsset)
        mdl_path = (
            Path(__file__).resolve().parents[2]
            / "ext"
            / "msp.dtrs"
            / "data"
            / "materials"
            / "DTRS_Fresnel_Test.mdl"
        )
        shader.SetSourceAsset(Sdf.AssetPath(str(mdl_path)), "mdl")
        shader.SetSourceAssetSubIdentifier("DTRS_Fresnel_Test", "mdl")
        shader.CreateOutput("out", Sdf.ValueTypeNames.Token).SetRenderType("material")
        material.CreateSurfaceOutput("mdl").ConnectToSource(
            shader.ConnectableAPI(), "out"
        )
        return material

    @classmethod
    def _set_xray_fresnel_probe_values(
        cls, stage, values, Gf, Sdf, UsdShade, *, camera_position=None
    ) -> None:
        """Author the shared Fresnel-mask controls and optional camera world position.

        The MDL owns how the NdotV mask drives colour, roughness, opacity, and
        emission.  This method only transfers validated UI values to its inputs.
        """

        (
            facing,
            edge,
            center,
            softness,
            sharpness,
            facing_roughness,
            edge_roughness,
            facing_opacity,
            edge_opacity,
            facing_emission,
            edge_emission,
            emission_scale,
        ) = values
        shader = UsdShade.Shader.Get(stage, f"{cls.XRAY_PROBE_MATERIAL_PATH}/Shader")
        for name, value, value_type in (
            ("facing_color", Gf.Vec3f(*facing), Sdf.ValueTypeNames.Color3f),
            ("edge_color", Gf.Vec3f(*edge), Sdf.ValueTypeNames.Color3f),
            ("edge_center", center, Sdf.ValueTypeNames.Float),
            ("edge_softness", softness, Sdf.ValueTypeNames.Float),
            ("edge_sharpness", sharpness, Sdf.ValueTypeNames.Float),
            ("facing_roughness", facing_roughness, Sdf.ValueTypeNames.Float),
            ("edge_roughness", edge_roughness, Sdf.ValueTypeNames.Float),
            ("facing_opacity", facing_opacity, Sdf.ValueTypeNames.Float),
            ("edge_opacity", edge_opacity, Sdf.ValueTypeNames.Float),
            ("facing_emission", facing_emission, Sdf.ValueTypeNames.Float),
            ("edge_emission", edge_emission, Sdf.ValueTypeNames.Float),
            ("emission_scale", emission_scale, Sdf.ValueTypeNames.Float),
        ):
            shader.CreateInput(name, value_type).Set(value)
        if camera_position is not None:
            shader.CreateInput("camera_position", Sdf.ValueTypeNames.Float3).Set(
                Gf.Vec3f(*camera_position)
            )

    @classmethod
    def _define_xray_control_material(cls, stage, xray, Gf, Sdf, UsdShade):
        """Create once per stage and update only the simple Part A controls.

        This intentionally uncomplicated material remains the Phase 4.0
        lifecycle payload.  Production Fresnel construction belongs to the
        later Phase 4.1B integration.
        """

        material_path = Sdf.Path(cls.XRAY_MATERIAL_PATH)
        material = UsdShade.Material.Define(stage, material_path)
        shader = UsdShade.Shader.Define(stage, material_path.AppendChild("PartA"))
        shader.CreateImplementationSourceAttr().Set(UsdShade.Tokens.sourceAsset)
        shader.SetSourceAsset(Sdf.AssetPath("OmniSurface.mdl"), "mdl")
        shader.SetSourceAssetSubIdentifier("OmniSurface", "mdl")
        shader.CreateInput("diffuse_reflection_color", Sdf.ValueTypeNames.Color3f).Set(
            Gf.Vec3f(*xray.part_a_fallback_color)
        )
        for name in ("diffuse_reflection_roughness", "specular_reflection_roughness"):
            shader.CreateInput(name, Sdf.ValueTypeNames.Float).Set(
                xray.part_a_roughness
            )
        shader.CreateInput("enable_opacity", Sdf.ValueTypeNames.Bool).Set(True)
        shader.CreateInput("geometry_opacity", Sdf.ValueTypeNames.Float).Set(
            xray.part_a_opacity
        )
        output = shader.CreateOutput("out", Sdf.ValueTypeNames.Token)
        output.SetRenderType("material")
        material.CreateSurfaceOutput("mdl").ConnectToSource(
            shader.ConnectableAPI(), "out"
        )
        return material
