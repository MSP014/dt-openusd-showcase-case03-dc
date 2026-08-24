# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""X-Ray material construction and parameter authoring for DTRS.

Owns reusable instances of the project-owned Custom MDL.
It does not decide which prims receive a material, manage Session Layer
binding ownership, or own a render-update loop; production lifecycle lives in
the runtime sibling module.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class XRayApplyResult:
    """Public result returned by production X-Ray lifecycle commands."""

    success: bool
    message: str
    target_count: int = 0


class XRayMaterialMixin:
    """Provide X-Ray material construction to the application runtime facade."""

    @classmethod
    def _define_xray_fresnel_material(cls, stage, material_path, Sdf, UsdShade):
        """Define one Custom MDL material instance at ``material_path``.

        The caller owns the material instance and its lifecycle; this helper
        owns only the reusable MDL authoring contract.
        """

        material_path = Sdf.Path(material_path)
        material = UsdShade.Material.Define(stage, material_path)
        shader = UsdShade.Shader.Define(stage, material_path.AppendChild("Shader"))
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
    def _set_xray_fresnel_material_values(
        cls, stage, material_path, values, Gf, Sdf, UsdShade, *, camera_position=None
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
        shader = UsdShade.Shader.Get(stage, f"{material_path}/Shader")
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

    @staticmethod
    def _xray_camera_positions_match(current, authored, tolerance=1.0e-4):
        """Compare camera vectors without coupling callers to a material lifecycle."""

        if current is None or authored is None:
            raise ValueError("camera position is missing")
        return all(
            abs(float(current[index]) - float(authored[index])) <= tolerance
            for index in range(3)
        )

    @classmethod
    def _xray_review_camera_position(cls, stage, Usd, UsdGeom):
        """Return ReviewCamera world position for any live Fresnel material."""

        camera = stage.GetPrimAtPath("/DTRS_Runtime/ReviewCamera")
        if not camera or not camera.IsValid():
            return None
        matrix = UsdGeom.XformCache(Usd.TimeCode.Default()).GetLocalToWorldTransform(
            camera
        )
        position = matrix.ExtractTranslation()
        return (float(position[0]), float(position[1]), float(position[2]))
