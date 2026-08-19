"""Explicit 2.6-second Streamlines recompute fallback for cache recovery."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable

from digital_twin_runtime_suite.app.streamlines.proof import (
    STREAMLINES_RUNTIME_PREVIEW_PATH,
    build_streamlines_operator_request,
    clear_streamlines_operator_from_stage,
    clear_streamlines_seed_from_stage,
)
from digital_twin_runtime_suite.app.streamlines.temporal import (
    TemporalSampleResolution,
    resolve_temporal_source_sample,
)

RECOMPUTE_PRESENTATION_PERIOD_SECONDS = 2.6
StatusCallback = Callable[[str], None]


@dataclass(frozen=True)
class StreamlinesRecomputeResult:
    """One explicit fallback result with a surviving visible preview."""

    resolution: TemporalSampleResolution
    rebuild_ms: float | None
    runtime_preview_path: str | None
    cleanup_complete: bool


class StreamlinesRecomputeRuntimeMixin:
    """Own the retained exact-source recompute fallback, never cache cadence."""

    async def run_streamlines_recompute_fallback_in_kit(
        self,
        current_phase_seconds: float,
        status_callback: StatusCallback | None = None,
    ) -> StreamlinesRecomputeResult:
        """Execute one standard Kit-CAE fallback result for an exact phase sample.

        The 2.6-second presentation period remains a bounded fallback contract.
        This function is only explicit invocation; it never schedules itself or
        measures a source cadence.
        """

        if self._flow_lifecycle_state != "DETACHED":
            raise RuntimeError(
                "Runtime recompute fallback is unavailable while airflow Attach "
                "is active."
            )
        source = self._streamlines_temporal_source_descriptor
        if source is None:
            source = await self.prepare_streamlines_temporal_velocity_source_in_kit(
                status_callback=status_callback,
            )
        resolution = resolve_temporal_source_sample(
            source,
            current_phase_seconds,
            active_sample_index=self._streamlines_recompute_active_sample_index,
        )
        if resolution.is_no_op:
            return StreamlinesRecomputeResult(
                resolution=resolution,
                rebuild_ms=None,
                runtime_preview_path=None,
                cleanup_complete=True,
            )

        import carb
        import omni.kit.app
        import omni.usd
        import warp as wp
        from omni.cae.data import usd_utils as cae_usd_utils
        from omni.cae.data.commands import execute_command
        from omni.cae.schema import viz as cae_viz
        from omni.cae.schema import vtk as cae_vtk
        from pxr import Sdf, Usd, UsdGeom
        from usdrt import UsdGeom as UsdGeomRT

        settings = carb.settings.get_settings()
        if settings.get_as_bool("/app/useFabricSceneDelegate"):
            raise RuntimeError(
                "Runtime recompute fallback requires Fabric Scene Delegate disabled."
            )
        app = omni.kit.app.get_app()
        stage = omni.usd.get_context().get_stage()
        if not stage:
            raise RuntimeError("Runtime recompute fallback requires an open stage.")
        descriptor = source.static_descriptor
        dataset_prim = stage.GetPrimAtPath(descriptor.dataset_prim_path)
        field_prim = stage.GetPrimAtPath(descriptor.velocity_field_prim_path)
        if not dataset_prim or not dataset_prim.IsValid():
            raise RuntimeError("Runtime recompute dataset prim is unavailable.")
        if not field_prim or not field_prim.IsValid():
            raise RuntimeError("Runtime recompute velocity field is unavailable.")

        request = replace(
            build_streamlines_operator_request(descriptor),
            operator_type="standard",
        )
        cleanup = clear_streamlines_operator_from_stage(stage)
        if not cleanup.success:
            raise RuntimeError("Runtime recompute could not clear its previous result.")
        previous_target = stage.GetEditTarget()
        execution = None
        cleanup_complete = False
        try:
            stage.SetEditTarget(stage.GetSessionLayer())
            await execute_command(
                "CreateCaeVizMeshPrim",
                prim_type="UnitSphere",
                prim_path=request.seed_path,
                resolution=request.seed_resolution,
            )
            await execute_command(
                "TransformPrimSRT",
                path=request.seed_path,
                new_translation=list(request.seed_center),
                new_scale=[request.seed_radius] * 3,
            )
            await app.next_update_async()
            selected_asset = await self._select_temporal_source_in_kit(
                app,
                field_prim=field_prim,
                sample=resolution.sample,
                cae_vtk=cae_vtk,
                Usd=Usd,
            )
            if selected_asset.resolve() != resolution.sample.source_vti.resolve():
                raise RuntimeError("Runtime recompute selected a non-manifest VTI.")
            self._start_kit_cae_operator_tracking()
            execution = await self._run_fresh_streamlines_operator_in_kit(
                stage,
                app=app,
                request=request,
                descriptor=descriptor,
                dataset_prim=dataset_prim,
                field_prim=field_prim,
                cae_usd_utils=cae_usd_utils,
                cae_viz=cae_viz,
                cae_vtk=cae_vtk,
                UsdGeom=UsdGeom,
                UsdGeomRT=UsdGeomRT,
                wp=wp,
                execute_command=execute_command,
                preview_path=STREAMLINES_RUNTIME_PREVIEW_PATH,
                Sdf=Sdf,
            )
            if not execution.execution_receipt.accepted:
                raise RuntimeError(
                    "Runtime recompute did not receive a Kit-CAE receipt."
                )
        finally:
            self._stop_kit_cae_operator_tracking()
            stage.SetEditTarget(previous_target)
            # The operator itself was removed by _run_fresh_streamlines...;
            # only its seed remains disposable. Keep RuntimePreview visible.
            cleanup_complete = clear_streamlines_seed_from_stage(stage)
            await app.next_update_async()
            if execution is None or not cleanup_complete:
                self._streamlines_recompute_active_sample_index = None

        if not cleanup_complete:
            raise RuntimeError("Runtime recompute cleanup did not remove its seed.")
        self._require_runtime_preview_after_recompute(stage)
        self._streamlines_recompute_active_sample_index = resolution.sample.sample_index
        if status_callback:
            status_callback(
                "Runtime recompute complete: exact manifest sample "
                f"{resolution.sample.ordinal}/{resolution.sample.total}."
            )
        return StreamlinesRecomputeResult(
            resolution=resolution,
            rebuild_ms=execution.rebuild_ms,
            runtime_preview_path=STREAMLINES_RUNTIME_PREVIEW_PATH,
            cleanup_complete=True,
        )

    @staticmethod
    def _require_runtime_preview_after_recompute(stage) -> None:
        """Require the accepted authored preview to survive disposable cleanup."""

        preview = stage.GetPrimAtPath(STREAMLINES_RUNTIME_PREVIEW_PATH)
        if not preview or not preview.IsValid():
            raise RuntimeError(
                "Runtime recompute removed its confirmed RuntimePreview."
            )
