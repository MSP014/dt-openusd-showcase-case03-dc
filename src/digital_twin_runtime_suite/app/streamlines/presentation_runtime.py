"""Kit/USD ownership for the one production Streamlines velocity material."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Callable

from digital_twin_runtime_suite.app.diagnostics import with_dtrs_yerevan_timestamp
from digital_twin_runtime_suite.app.flow.performance import (
    ViewportPerformanceSample,
    capture_viewport_performance_sample,
)
from digital_twin_runtime_suite.app.streamlines.cache import (
    CACHE_PLAYBACK_CURVES_PATH,
)
from digital_twin_runtime_suite.app.streamlines.presentation import (
    PaletteStop,
    PhysicalSpeedScale,
    StreamlinesPresentation,
)
from digital_twin_runtime_suite.app.streamlines.speed import SPEED_PRIMVAR_ATTRIBUTE

STREAMLINES_LOOK_ROOT = "/DTRS_Looks"
STREAMLINES_MATERIAL_PATH = f"{STREAMLINES_LOOK_ROOT}/StreamlinesVelocity"
STREAMLINES_SNAPSHOT_DISPLAY_COLOUR = (0.0, 0.8, 1.0)
_PERFORMANCE_SETTLE_SECONDS = 10.0
_PERFORMANCE_SAMPLE_WINDOW_SECONDS = 2.0
_PERFORMANCE_SAMPLE_COUNT = 8
StatusCallback = Callable[[str], None]


@dataclass(frozen=True)
class StreamlinesMaterialSnapshot:
    """Real authored/bound material evidence without renderer polling."""

    material_path: str
    geometry_path: str
    presentation_signature: str
    material_bound: bool
    speed_primvar_readable: bool
    material_create_count: int
    apply_count: int


@dataclass(frozen=True)
class StreamlinesMaterialPreviewReceipt:
    """Stable material and post-settle viewport evidence for one preview."""

    material: StreamlinesMaterialSnapshot
    performance_settle_seconds: float
    performance_sample_window_seconds: float
    performance_samples: int
    viewport_fps_current: float | None
    viewport_fps_average: float | None
    viewport_fps_minimum: float | None
    frame_time_ms_current: float | None
    frame_time_ms_average: float | None
    gpu_used_gib: float | None
    process_used_gib: float | None


class StreamlinesPresentationRuntimeMixin:
    """Author and bind one stable material; never own cache/playback state."""

    def reset_streamlines_presentation_runtime_state(self) -> None:
        self.cancel_streamlines_material_preview_measurement()
        self._streamlines_material_create_count = 0
        self._streamlines_material_apply_count = 0
        self._streamlines_material_snapshot = None
        self._streamlines_material_candidate = None
        self._streamlines_material_accepted_candidate = None
        self._streamlines_material_preview_generation = 0
        self._streamlines_material_measurement_task = None

    def apply_streamlines_snapshot_display_colour_in_kit(self) -> int:
        """Preserve the accepted cyan snapshot look without authoring a material.

        Static snapshots have no Mesh prototype to inherit the old material
        binding.  This applies only the existing Full-State probe display colour;
        velocity-driven material and palette work remains owned by its later seam.
        """

        import omni.usd
        from pxr import Gf, UsdGeom

        snapshots = getattr(self, "_streamlines_snapshot_set_ownership", None)
        if snapshots is None:
            raise RuntimeError("Static snapshot presentation is unavailable.")
        stage = omni.usd.get_context().get_stage()
        if stage is None:
            raise RuntimeError("Static snapshot presentation requires an open stage.")
        previous_target = stage.GetEditTarget()
        try:
            stage.SetEditTarget(stage.GetSessionLayer())
            for state in snapshots.states:
                curves = UsdGeom.BasisCurves(stage.GetPrimAtPath(state.prim_path))
                display_colour = curves.CreateDisplayColorAttr(
                    [Gf.Vec3f(*STREAMLINES_SNAPSHOT_DISPLAY_COLOUR)]
                )
                UsdGeom.Primvar(display_colour).SetInterpolation(
                    UsdGeom.Tokens.constant
                )
        finally:
            stage.SetEditTarget(previous_target)
        return len(snapshots.states)

    def streamlines_presentation_contract(
        self,
        *,
        opacity: float | None = None,
        emission_intensity: float | None = None,
        lighting_influence: float | None = None,
    ) -> StreamlinesPresentation:
        config = self.config.streamlines_presentation
        speed_scale = getattr(self, "_streamlines_accepted_speed_scale", None)
        if speed_scale is None:
            speed_scale = PhysicalSpeedScale(
                config.speed_min, config.speed_max, config.speed_units
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
        """Update one material and direct binding without touching geometry."""

        import omni.usd
        from pxr import Gf, Sdf, UsdShade

        stage = omni.usd.get_context().get_stage()
        if not stage:
            raise RuntimeError("Streamlines material requires an open stage.")
        geometry = stage.GetPrimAtPath(CACHE_PLAYBACK_CURVES_PATH)
        if not geometry or not geometry.IsValid():
            raise RuntimeError("Streamlines presentation geometry is unavailable.")
        speed = geometry.GetAttribute(SPEED_PRIMVAR_ATTRIBUTE)
        if not speed or not speed.IsValid():
            raise RuntimeError(
                "Installed Streamlines material cannot read primvars:dtrs:speed."
            )
        presentation = presentation or self.streamlines_presentation_contract()
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
            UsdShade.MaterialBindingAPI.Apply(geometry).Bind(material)
        finally:
            stage.SetEditTarget(previous_target)
        bound, _ = UsdShade.MaterialBindingAPI(geometry).ComputeBoundMaterial()
        self._streamlines_material_apply_count += 1
        snapshot = StreamlinesMaterialSnapshot(
            material_path=STREAMLINES_MATERIAL_PATH,
            geometry_path=CACHE_PLAYBACK_CURVES_PATH,
            presentation_signature=presentation.signature,
            material_bound=bool(
                bound
                and bound.GetPrim().IsValid()
                and str(bound.GetPath()) == STREAMLINES_MATERIAL_PATH
            ),
            speed_primvar_readable=True,
            material_create_count=self._streamlines_material_create_count,
            apply_count=self._streamlines_material_apply_count,
        )
        if not snapshot.material_bound:
            raise RuntimeError("Streamlines production material binding failed.")
        self._streamlines_material_snapshot = snapshot
        return snapshot

    async def apply_streamlines_material_preview_in_kit(
        self,
        presentation: StreamlinesPresentation,
        *,
        status_callback: StatusCallback | None = None,
    ) -> StreamlinesMaterialPreviewReceipt:
        """Apply once, then publish evidence only after the stable 10+2 s gate."""

        self.cancel_streamlines_material_preview_measurement()
        self._streamlines_material_preview_generation += 1
        generation = self._streamlines_material_preview_generation
        self._streamlines_material_candidate = None
        self._report_streamlines_material_preview(
            "START",
            "Applying the shared production Streamlines material.",
            status_callback,
        )
        snapshot = self.apply_streamlines_presentation_in_kit(presentation)
        await self._await_streamlines_material_viewport_update()
        self._require_current_streamlines_material_preview(generation)
        self._report_streamlines_material_preview(
            "PROGRESS",
            "Preview visible; material binding and raw speed are valid.",
            status_callback,
        )
        self._report_streamlines_material_preview(
            "WAITING",
            "Allowing viewport to stabilize for performance measurement.",
            status_callback,
        )
        task = asyncio.ensure_future(
            self._collect_streamlines_material_performance_samples(generation)
        )
        self._streamlines_material_measurement_task = task
        try:
            samples = await task
        finally:
            if self._streamlines_material_measurement_task is task:
                self._streamlines_material_measurement_task = None
        self._require_current_streamlines_material_preview(generation)
        receipt = self._streamlines_material_preview_receipt(snapshot, samples)
        self._streamlines_material_candidate = presentation
        self._report_streamlines_material_preview(
            "COMPLETE",
            "material_bound=True; dtrs:speed_readable=True; cache_build=0; "
            "cache_rebuild=0; KitCAE=0; VTI_import=0; "
            f"performance_samples={receipt.performance_samples}; "
            f"viewport_fps_average={receipt.viewport_fps_average}; "
            f"viewport_fps_minimum={receipt.viewport_fps_minimum}.",
            status_callback,
        )
        return receipt

    def cancel_streamlines_material_preview_measurement(self) -> None:
        """Invalidate delayed evidence so superseded work cannot complete late."""

        self._streamlines_material_preview_generation = (
            getattr(self, "_streamlines_material_preview_generation", 0) + 1
        )
        task = getattr(self, "_streamlines_material_measurement_task", None)
        if task is not None and not task.done():
            task.cancel()
        self._streamlines_material_measurement_task = None
        self._streamlines_material_candidate = None

    async def _collect_streamlines_material_performance_samples(
        self,
        generation: int,
    ) -> tuple[ViewportPerformanceSample, ...]:
        await self._wait_streamlines_material_measurement_interval(
            _PERFORMANCE_SETTLE_SECONDS
        )
        self._require_current_streamlines_material_preview(generation)
        interval = _PERFORMANCE_SAMPLE_WINDOW_SECONDS / (_PERFORMANCE_SAMPLE_COUNT - 1)
        samples = []
        for index in range(_PERFORMANCE_SAMPLE_COUNT):
            self._require_current_streamlines_material_preview(generation)
            samples.append(capture_viewport_performance_sample())
            if index + 1 < _PERFORMANCE_SAMPLE_COUNT:
                await self._wait_streamlines_material_measurement_interval(interval)
        return tuple(samples)

    @staticmethod
    async def _wait_streamlines_material_measurement_interval(seconds: float) -> None:
        await asyncio.sleep(seconds)

    @staticmethod
    async def _await_streamlines_material_viewport_update() -> None:
        try:
            import omni.kit.app
        except ImportError:
            await asyncio.sleep(0)
            return
        await omni.kit.app.get_app().next_update_async()

    def _require_current_streamlines_material_preview(self, generation: int) -> None:
        if generation != self._streamlines_material_preview_generation:
            raise asyncio.CancelledError

    @staticmethod
    def _streamlines_material_preview_receipt(
        snapshot: StreamlinesMaterialSnapshot,
        samples: tuple[ViewportPerformanceSample, ...],
    ) -> StreamlinesMaterialPreviewReceipt:
        if len(samples) < 2:
            raise RuntimeError("Material performance proof requires several samples.")
        fps = tuple(value.fps for value in samples if value.fps is not None)
        frame_times = tuple(
            value.frame_time_ms for value in samples if value.frame_time_ms is not None
        )
        final = samples[-1]
        return StreamlinesMaterialPreviewReceipt(
            material=snapshot,
            performance_settle_seconds=_PERFORMANCE_SETTLE_SECONDS,
            performance_sample_window_seconds=_PERFORMANCE_SAMPLE_WINDOW_SECONDS,
            performance_samples=len(samples),
            viewport_fps_current=final.fps,
            viewport_fps_average=float(mean(fps)) if fps else None,
            viewport_fps_minimum=min(fps) if fps else None,
            frame_time_ms_current=final.frame_time_ms,
            frame_time_ms_average=(float(mean(frame_times)) if frame_times else None),
            gpu_used_gib=final.gpu_memory_used_gib,
            process_used_gib=final.process_memory_used_gib,
        )

    @staticmethod
    def _report_streamlines_material_preview(
        event: str,
        message: str,
        status_callback: StatusCallback | None,
    ) -> None:
        if status_callback:
            status_callback(message)
        try:
            import carb
        except ImportError:
            return
        carb.log_warn(
            with_dtrs_yerevan_timestamp(
                f"DTRS STREAMLINES | PHASE_4_4B_MATERIAL | {event}\nstatus={message}"
            )
        )

    def streamlines_material_snapshot(self) -> StreamlinesMaterialSnapshot | None:
        return getattr(self, "_streamlines_material_snapshot", None)

    def accept_streamlines_material_candidate(self) -> StreamlinesPresentation:
        """Return the immutable session candidate from the last successful apply."""

        candidate = getattr(self, "_streamlines_material_candidate", None)
        if candidate is None:
            raise RuntimeError("Apply a Streamlines material preview first.")
        self._streamlines_material_accepted_candidate = candidate
        return candidate

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
        """Remove only DTRS-owned look state during reload/shutdown."""

        if stage:
            previous_target = stage.GetEditTarget()
            try:
                stage.SetEditTarget(stage.GetSessionLayer())
                stage.RemovePrim(STREAMLINES_MATERIAL_PATH)
            finally:
                stage.SetEditTarget(previous_target)
        self._streamlines_material_snapshot = None
        self._streamlines_material_candidate = None
        self.cancel_streamlines_material_preview_measurement()
