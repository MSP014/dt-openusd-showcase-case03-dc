"""Bind one fixed-scale velocity material to the active static snapshots."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable

from digital_twin_runtime_suite.app.streamlines.presentation import (
    PaletteStop,
    PhysicalSpeedScale,
    StreamlinesPresentation,
)
from digital_twin_runtime_suite.app.streamlines.speed import SPEED_PRIMVAR_ATTRIBUTE

STREAMLINES_LOOK_ROOT = "/DTRS_Looks"
STREAMLINES_MATERIAL_PATH = f"{STREAMLINES_LOOK_ROOT}/StreamlinesVelocity"
StatusCallback = Callable[[str], None]


@dataclass(frozen=True)
class StreamlinesMaterialSnapshot:
    """Material evidence for every static curve in the active snapshot set."""

    material_path: str
    snapshot_root_path: str
    geometry_paths: tuple[str, ...]
    presentation_signature: str
    material_bound: bool
    speed_primvar_readable: bool
    material_create_count: int
    apply_count: int

    @property
    def snapshot_count(self) -> int:
        """Return the number of static states sharing the material."""

        return len(self.geometry_paths)


@dataclass(frozen=True)
class StreamlinesMaterialApplyReceipt:
    """One latest-wins material-settings receipt without scheduler work."""

    material: StreamlinesMaterialSnapshot


class StreamlinesPresentationRuntimeMixin:
    """Own only DTRS material authoring and snapshot-set bindings.

    Cache generation, snapshot materialisation, and scheduler ownership remain
    outside this mixin. Applying a presentation only changes one material and
    bindings already owned by the current static snapshot set.
    """

    def reset_streamlines_presentation_runtime_state(self) -> None:
        """Clear session-only material state at lifecycle boundaries."""

        self.cancel_streamlines_material_apply()
        self._streamlines_material_create_count = 0
        self._streamlines_material_apply_count = 0
        self._streamlines_material_snapshot = None
        self._streamlines_material_active_presentation = None
        self._streamlines_material_apply_generation = 0

    def streamlines_presentation_contract(
        self,
        *,
        opacity: float | None = None,
        emission_intensity: float | None = None,
        lighting_influence: float | None = None,
    ) -> StreamlinesPresentation:
        """Return the immutable, cache-independent current material contract."""

        config = self.config.streamlines_presentation
        speed_scale = getattr(self, "_streamlines_accepted_speed_scale", None)
        if speed_scale is None:
            speed_scale = PhysicalSpeedScale(
                config.speed_min,
                config.speed_max,
                config.speed_units,
            )
        return StreamlinesPresentation(
            speed_scale=speed_scale,
            palette=tuple(
                PaletteStop(position, color) for position, color in config.palette
            ),
            opacity=config.opacity if opacity is None else float(opacity),
            emission_intensity=(
                config.emission_intensity
                if emission_intensity is None
                else float(emission_intensity)
            ),
            lighting_influence=(
                config.lighting_influence
                if lighting_influence is None
                else float(lighting_influence)
            ),
        )

    def apply_streamlines_presentation_in_kit(
        self,
        presentation: StreamlinesPresentation | None = None,
    ) -> StreamlinesMaterialSnapshot:
        """Bind one material across the current snapshot states only.

        The snapshot owner is authoritative: this deliberately has no fallback
        to the retired single cached-playback curve path.
        """

        import omni.usd
        from pxr import Gf, Sdf, UsdShade

        stage = omni.usd.get_context().get_stage()
        if not stage:
            raise RuntimeError("Streamlines material requires an open stage.")
        snapshots = getattr(self, "_streamlines_snapshot_set_ownership", None)
        if snapshots is None or not snapshots.states:
            raise RuntimeError(
                "Static Streamlines snapshot presentation is unavailable."
            )
        geometries = tuple(
            stage.GetPrimAtPath(state.prim_path) for state in snapshots.states
        )
        if any(not geometry or not geometry.IsValid() for geometry in geometries):
            raise RuntimeError("Streamlines snapshot geometry is unavailable.")
        if any(
            not geometry.GetAttribute(SPEED_PRIMVAR_ATTRIBUTE)
            or not geometry.GetAttribute(SPEED_PRIMVAR_ATTRIBUTE).IsValid()
            for geometry in geometries
        ):
            raise RuntimeError(
                "Installed Streamlines material cannot read primvars:dtrs:speed."
            )
        presentation = (
            presentation
            or getattr(self, "_streamlines_material_active_presentation", None)
            or self.streamlines_presentation_contract()
        )
        previous_target = stage.GetEditTarget()
        try:
            stage.SetEditTarget(stage.GetSessionLayer())
            material = UsdShade.Material.Get(stage, STREAMLINES_MATERIAL_PATH)
            if not material or not material.GetPrim().IsValid():
                material = self._define_streamlines_velocity_material(
                    stage,
                    Sdf=Sdf,
                    UsdShade=UsdShade,
                )
                self._streamlines_material_create_count += 1
            shader = UsdShade.Shader.Get(stage, f"{STREAMLINES_MATERIAL_PATH}/Shader")
            self._set_streamlines_velocity_material_values(
                shader,
                presentation,
                Gf=Gf,
                Sdf=Sdf,
            )
            for geometry in geometries:
                UsdShade.MaterialBindingAPI.Apply(geometry).Bind(material)
        finally:
            stage.SetEditTarget(previous_target)
        material_bound = all(
            self._is_streamlines_material_bound(geometry, UsdShade)
            for geometry in geometries
        )
        if not material_bound:
            raise RuntimeError("Streamlines production material binding failed.")
        self._streamlines_material_apply_count += 1
        self._streamlines_material_active_presentation = presentation
        snapshot = StreamlinesMaterialSnapshot(
            material_path=STREAMLINES_MATERIAL_PATH,
            snapshot_root_path=snapshots.root_path,
            geometry_paths=tuple(str(geometry.GetPath()) for geometry in geometries),
            presentation_signature=presentation.signature,
            material_bound=True,
            speed_primvar_readable=True,
            material_create_count=self._streamlines_material_create_count,
            apply_count=self._streamlines_material_apply_count,
        )
        self._streamlines_material_snapshot = snapshot
        return snapshot

    async def apply_streamlines_material_settings_in_kit(
        self,
        presentation: StreamlinesPresentation,
        *,
        status_callback: StatusCallback | None = None,
    ) -> StreamlinesMaterialApplyReceipt:
        """Apply settings after one Kit update, without scheduler work."""

        self.cancel_streamlines_material_apply()
        self._streamlines_material_apply_generation += 1
        generation = self._streamlines_material_apply_generation
        snapshot = self.apply_streamlines_presentation_in_kit(presentation)
        await self._await_streamlines_material_viewport_update()
        self._require_current_streamlines_material_apply(generation)
        if status_callback:
            status_callback(
                "Material settings applied: one snapshot-set material; "
                "cache_build=0; snapshot_rebuild=0; KitCAE=0; VTI_import=0."
            )
        return StreamlinesMaterialApplyReceipt(snapshot)

    def cancel_streamlines_material_apply(self) -> None:
        """Invalidate a stale material application before it reports completion."""

        self._streamlines_material_apply_generation = (
            getattr(self, "_streamlines_material_apply_generation", 0) + 1
        )

    @staticmethod
    async def _await_streamlines_material_viewport_update() -> None:
        try:
            import omni.kit.app
        except ImportError:
            await asyncio.sleep(0)
            return
        await omni.kit.app.get_app().next_update_async()

    def _require_current_streamlines_material_apply(self, generation: int) -> None:
        if generation != self._streamlines_material_apply_generation:
            raise asyncio.CancelledError

    def streamlines_material_snapshot(self) -> StreamlinesMaterialSnapshot | None:
        """Return public evidence for the material bound to active snapshots."""

        return getattr(self, "_streamlines_material_snapshot", None)

    def save_streamlines_material_settings(
        self,
        presentation: StreamlinesPresentation,
    ) -> Path:
        """Persist applied tuning without changing the shared speed scale."""

        persisted = replace(
            self.config.streamlines_presentation,
            opacity=presentation.opacity,
            emission_intensity=presentation.emission_intensity,
            lighting_influence=presentation.lighting_influence,
        )
        return self.save_streamlines_presentation_override(persisted)

    @staticmethod
    def _is_streamlines_material_bound(geometry, UsdShade) -> bool:
        material, _binding = UsdShade.MaterialBindingAPI(
            geometry
        ).ComputeBoundMaterial()
        return bool(
            material
            and material.GetPrim().IsValid()
            and str(material.GetPath()) == STREAMLINES_MATERIAL_PATH
        )

    @staticmethod
    def _define_streamlines_velocity_material(stage, *, Sdf, UsdShade):
        material = UsdShade.Material.Define(stage, STREAMLINES_MATERIAL_PATH)
        shader = UsdShade.Shader.Define(
            stage,
            f"{STREAMLINES_MATERIAL_PATH}/Shader",
        )
        shader.CreateImplementationSourceAttr().Set(UsdShade.Tokens.sourceAsset)
        mdl_path = (
            Path(__file__).resolve().parents[2]
            / "ext"
            / "msp.dtrs"
            / "data"
            / "materials"
            / "DTRS_Streamlines_Velocity.mdl"
        )
        shader.SetSourceAsset(Sdf.AssetPath(str(mdl_path)), "mdl")
        shader.SetSourceAssetSubIdentifier("DTRS_Streamlines_Velocity", "mdl")
        shader.CreateOutput("out", Sdf.ValueTypeNames.Token).SetRenderType("material")
        material.CreateSurfaceOutput("mdl").ConnectToSource(
            shader.ConnectableAPI(),
            "out",
        )
        return material

    @staticmethod
    def _set_streamlines_velocity_material_values(
        shader,
        presentation: StreamlinesPresentation,
        *,
        Gf,
        Sdf,
    ) -> None:
        values = (
            ("speed_min", presentation.speed_scale.minimum, Sdf.ValueTypeNames.Float),
            ("speed_max", presentation.speed_scale.maximum, Sdf.ValueTypeNames.Float),
            ("opacity", presentation.opacity, Sdf.ValueTypeNames.Float),
            (
                "emission_intensity",
                presentation.emission_intensity,
                Sdf.ValueTypeNames.Float,
            ),
            (
                "lighting_influence",
                presentation.lighting_influence,
                Sdf.ValueTypeNames.Float,
            ),
        )
        for name, value, value_type in values:
            shader.CreateInput(name, value_type).Set(value)
        for index, stop in enumerate(presentation.palette):
            shader.CreateInput(f"color_{index}", Sdf.ValueTypeNames.Color3f).Set(
                Gf.Vec3f(*stop.color)
            )

    def clear_streamlines_presentation_material_from_stage(self, stage) -> None:
        """Remove only the DTRS-owned material during reload or shutdown."""

        if stage:
            previous_target = stage.GetEditTarget()
            try:
                stage.SetEditTarget(stage.GetSessionLayer())
                stage.RemovePrim(STREAMLINES_MATERIAL_PATH)
            finally:
                stage.SetEditTarget(previous_target)
        self._streamlines_material_snapshot = None
        self._streamlines_material_active_presentation = None
        self.cancel_streamlines_material_apply()

    def release_streamlines_presentation_material_in_kit(self) -> None:
        """Release material state only when Streamlines returns to Normal.

        Workload and profile transitions replace snapshots while retaining the
        accepted material. Only Normal releases the material prim, apply
        task, and material snapshot together.
        """

        import omni.usd

        self.clear_streamlines_presentation_material_from_stage(
            omni.usd.get_context().get_stage()
        )
