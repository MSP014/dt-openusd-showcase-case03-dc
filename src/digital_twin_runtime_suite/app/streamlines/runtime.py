"""Kit-facing Streamlines runtime mechanics.

The production path builds and plays a persisted cache; ``cache.py`` owns its
plain identity and persistence contract.  This facade retains the shared
temporal VTI selection, standard Kit-CAE operator execution receipts, the
cache-facing Kit operations, and canonical cleanup. The former 2.6-second
recompute path remains documented fallback evidence; it is not an active
runtime scheduler.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, replace
from pathlib import Path
from statistics import median
from typing import Callable

from digital_twin_runtime_suite.app.airflow_dataset import (
    discover_airflow_dataset,
)
from digital_twin_runtime_suite.app.diagnostics import (
    with_dtrs_yerevan_timestamp,
)
from digital_twin_runtime_suite.app.flow import temporal as flow_temporal
from digital_twin_runtime_suite.app.flow.performance import (
    capture_viewport_performance_sample,
)
from digital_twin_runtime_suite.app.flow.static_source import (
    StaticVelocitySourceDescriptor,
    clear_static_velocity_source_from_stage,
    describe_imported_static_velocity_source,
    resolve_static_velocity_sample,
)
from digital_twin_runtime_suite.app.streamlines.cache import (
    CACHE_BUILD_OPERATOR_PATH,
    CACHE_BUILD_SEED_PATH,
    CACHE_PLAYBACK_CURVES_PATH,
    CACHE_PLAYBACK_ROOT_PATH,
    CACHE_SCHEMA_VERSION,
    StreamlinesCacheMetadata,
    StreamlinesCachePaths,
    StreamlinesCacheSettings,
    StreamlinesCacheState,
    StreamlinesCacheValidation,
    build_streamlines_cache_metadata,
    cache_settings_differences,
    discard_streamlines_cache_staging,
    file_sha256,
)
from digital_twin_runtime_suite.app.streamlines.cache import (
    geometry_signature as cache_geometry_signature,
)
from digital_twin_runtime_suite.app.streamlines.cache import (
    load_streamlines_cache_metadata,
    replace_streamlines_cache_artifacts,
    serialise_streamlines_cache_metadata,
    source_signature_from_values,
    streamlines_cache_build_mode,
    streamlines_cache_paths,
    streamlines_cache_settings,
    streamlines_settings_signature,
)
from digital_twin_runtime_suite.app.streamlines.cache import (
    topology_signature as cache_topology_signature,
)
from digital_twin_runtime_suite.app.streamlines.cache import (
    validate_streamlines_cache,
    vti_file_identity,
)
from digital_twin_runtime_suite.app.streamlines.diagnostics import (
    StreamlinesOperatorEvidence,
    format_static_source_acceptance,
    inspect_static_source_runtime,
    inspect_streamlines_bindings,
    inspect_streamlines_operator,
)
from digital_twin_runtime_suite.app.streamlines.lifecycle import (
    STATIC_VELOCITY_SOURCE_ROOT,
    StreamlinesCleanupReceipt,
    inspect_streamlines_runtime_cleanup,
    remove_streamlines_runtime_roots_from_layers,
)
from digital_twin_runtime_suite.app.streamlines.proof import (
    StreamlinesOperatorRequest,
    build_streamlines_operator_request,
    clear_streamlines_operator_from_stage,
    validate_generated_streamlines_geometry,
)
from digital_twin_runtime_suite.app.streamlines.temporal import (
    TemporalSourceSample,
    TemporalVelocitySourceDescriptor,
)

StatusCallback = Callable[[str], None]
ErrorLogger = Callable[[str], None]


@dataclass(frozen=True)
class StreamlinesCacheBuildResult:
    """Outcome of a derived-cache build before process restart."""

    success: bool
    message: str
    metadata: StreamlinesCacheMetadata | None = None


@dataclass(frozen=True)
class StreamlinesCachePlaybackResult:
    """Outcome of restart validation and cached geometry playback."""

    decision: str
    message: str

    @property
    def viable(self) -> bool:
        """Return whether exact cached playback met the real source cadence."""

        return self.decision == "CACHE_PLAYBACK_VIABLE"


@dataclass(frozen=True)
class StreamlinesOperatorExecutionReceipt:
    """Causally linked Kit begin/end result for one runtime operator execution."""

    begin_count_before: int
    begin_count_after: int
    completion_count_before: int
    completion_count_after: int
    completion_begin_count: int | None
    completion_success: bool | None

    @property
    def fresh_execution(self) -> bool:
        """Require both a new begin and its paired later completion event."""

        return (
            self.begin_count_after > self.begin_count_before
            and self.completion_count_after > self.completion_count_before
            and self.completion_begin_count is not None
            and self.completion_begin_count >= self.begin_count_after
        )

    @property
    def accepted(self) -> bool:
        """Require a fresh execution whose paired completion succeeded."""

        return self.fresh_execution and self.completion_success is True


@dataclass(frozen=True)
class _RuntimePreviewMirror:
    """FSD-safe authored copy of one accepted Kit-CAE UsdRT curve snapshot."""

    path: str
    curve_count: int
    point_count: int
    matches_runtime: bool
    authored_fallback_visibility: str
    runtime_visibility: str


@dataclass(frozen=True)
class _PreparedStreamlinesOperator:
    """One disposable standard operator prepared for one real execution."""

    creation_duration_ms: float
    operator_prim: object
    operator_api: object
    binding_evidence: object
    integration_settings: tuple[tuple[str, str], ...]
    source_processing_mode: str
    voxelization_settings: tuple[tuple[str, str], ...]
    nanovdb_effective_grid: object | None


@dataclass(frozen=True)
class _StreamlinesOperatorExecution:
    """One completed disposable operator and its optional FSD-safe mirror."""

    prepared: _PreparedStreamlinesOperator
    rebuild_ms: float
    evidence: StreamlinesOperatorEvidence
    execution_receipt: StreamlinesOperatorExecutionReceipt
    preview_mirror_ms: float | None


def _author_usdrt_runtime_preview(
    stage,
    *,
    operator_prim,
    evidence: StreamlinesOperatorEvidence,
    preview_path: str,
    UsdGeom,
    UsdGeomRT,
    cae_usd_utils,
    Sdf,
) -> _RuntimePreviewMirror:
    """Mirror confirmed UsdRT curves for a human viewport running without FSD.

    Stage 7 keeps Fabric Scene Delegate disabled because its X-Ray rollback is
    not reliable with FSD enabled. Kit-CAE Streamlines therefore remains the
    computational owner, while this short-lived authored preview makes the
    exact accepted UsdRT snapshot inspectable by the standard USD renderer.
    The command's visible four-point fallback is hidden rather than repurposed.
    """

    if not evidence.runtime_usdrt_basis_curves:
        raise RuntimeError(
            "Cannot create a viewport preview without UsdRT BasisCurves."
        )

    authored_operator = UsdGeom.Imageable(operator_prim)
    authored_operator.CreateVisibilityAttr().Set(UsdGeom.Tokens.invisible)

    runtime_operator = UsdGeomRT.BasisCurves(cae_usd_utils.get_prim_rt(operator_prim))
    runtime_operator.CreateVisibilityAttr().Set(UsdGeomRT.Tokens.inherited)

    preview = UsdGeom.BasisCurves.Define(stage, preview_path)
    preview.CreatePointsAttr().Set(list(evidence.runtime_point_positions))
    preview.CreateCurveVertexCountsAttr().Set(
        list(evidence.runtime_curve_vertex_counts)
    )
    if evidence.runtime_curve_bounds:
        preview.CreateExtentAttr().Set(list(evidence.runtime_curve_bounds))
    preview.CreateBasisAttr().Set(UsdGeom.Tokens.bspline)
    preview.CreateTypeAttr().Set(UsdGeom.Tokens.cubic)
    preview.CreateWrapAttr().Set(UsdGeom.Tokens.pinned)
    preview.SetWidthsInterpolation(UsdGeom.Tokens.constant)
    UsdGeom.PrimvarsAPI(preview.GetPrim()).CreatePrimvar(
        "widths",
        Sdf.ValueTypeNames.FloatArray,
        UsdGeom.Tokens.constant,
    ).Set([evidence.configured_width])
    # Cyan isolates the UsdRT-derived diagnostic result from the white fallback
    # line that the Kit creation command otherwise authors at the stage origin.
    preview.CreateDisplayColorPrimvar(UsdGeom.Tokens.constant).Set([(0.1, 0.8, 1.0)])

    preview_points = tuple(
        tuple(float(component) for component in point)
        for point in (preview.GetPointsAttr().Get() or ())
    )
    preview_counts = tuple(
        int(count) for count in (preview.GetCurveVertexCountsAttr().Get() or ())
    )
    preview_matches_runtime = (
        preview_points == evidence.runtime_point_positions
        and preview_counts == evidence.runtime_curve_vertex_counts
    )
    if not preview_matches_runtime:
        raise RuntimeError(
            "Viewport preview does not match the accepted UsdRT geometry."
        )

    return _RuntimePreviewMirror(
        path=preview_path,
        curve_count=len(preview_counts),
        point_count=len(preview_points),
        matches_runtime=preview_matches_runtime,
        authored_fallback_visibility=str(authored_operator.GetVisibilityAttr().Get()),
        runtime_visibility=str(runtime_operator.GetVisibilityAttr().Get()),
    )


def _emit_streamlines_task_error(error_logger: ErrorLogger, message: str) -> None:
    """Contain a secondary logging failure at the UI-task error boundary."""

    try:
        error_logger(message)
    except Exception:
        return


def _set_streamlines_task_error_status(
    status_callback: StatusCallback,
    message: str,
) -> None:
    """Contain a secondary status-label failure at the UI-task boundary."""

    try:
        status_callback(message)
    except Exception:
        return


def report_streamlines_task_failure(
    error: Exception,
    *,
    area: str,
    display_name: str,
    status_callback: StatusCallback,
    error_logger: ErrorLogger,
) -> None:
    """Contain an unexpected Streamlines UI-task failure without blocking a retry.

    Kit tasks are detached from the clicked button.  This last boundary turns a
    failure outside the normal controller result into a visible DTRS event and
    status, while independently shielding the task from a faulty logger or UI
    label during error handling.
    """

    reason = " ".join(str(error).splitlines()) or type(error).__name__
    message = f"{display_name} failed: {reason}"
    _emit_streamlines_task_error(
        error_logger,
        with_dtrs_yerevan_timestamp(
            f"DTRS STREAMLINES | {area} | FAIL | "
            "boundary=UI_TASK | "
            f"error_type={type(error).__name__} | reason={reason}"
        ),
    )
    _set_streamlines_task_error_status(status_callback, message)
    return None


class StreamlinesRuntimeMixin:
    """Public Streamlines facade used by ``RuntimeController`` and OmniUI."""

    STATIC_IMPORT_ROOT = STATIC_VELOCITY_SOURCE_ROOT
    STATIC_DATASET_PATH = f"{STATIC_IMPORT_ROOT}/VTKImageData"
    STREAMLINES_OPERATOR_TIMEOUT_SECONDS = 15.0

    # --- Lifecycle ownership -------------------------------------------------

    def streamlines_static_source_descriptor(
        self,
    ) -> StaticVelocitySourceDescriptor | None:
        """Return the current static source descriptor without mutating Kit state."""

        return self._streamlines_static_source_descriptor

    def streamlines_static_source_diagnostics_failure(self) -> str | None:
        """Return a non-fatal diagnostics warning for the current static source."""

        return self._streamlines_static_source_diagnostics_failure

    def clear_streamlines_static_runtime_from_open_stage(
        self,
    ) -> StreamlinesCleanupReceipt:
        """Synchronously remove every DTRS-owned Streamlines artifact.

        This is the single teardown owner for retries, reload, and extension
        shutdown. It owns only DTRS Streamlines state; Flow remains untouched.
        """

        self._stop_kit_cae_operator_tracking()
        self._streamlines_static_source_descriptor = None
        self._streamlines_static_source_diagnostics_failure = None
        self._streamlines_temporal_source_descriptor = None
        pending_tasks = self._streamlines_pending_runtime_task_count()
        try:
            import omni.usd
        except ImportError:
            return self._empty_static_cleanup_receipt(pending_tasks)

        stage = omni.usd.get_context().get_stage()
        if not stage:
            return self._empty_static_cleanup_receipt(pending_tasks)

        # The persisted cache never becomes a permanent stage sublayer. Detach
        # playback before the canonical root sweep so cleanup stays idempotent.
        self._detach_streamlines_cache_playback_layer(stage)
        clear_static_velocity_source_from_stage(stage, self.STATIC_IMPORT_ROOT)
        clear_streamlines_operator_from_stage(stage)
        # The generic sweep additionally rejects accidental ``_001`` siblings.
        remove_streamlines_runtime_roots_from_layers(stage)
        return inspect_streamlines_runtime_cleanup(stage, pending_tasks=pending_tasks)

    async def clear_streamlines_static_runtime_in_kit(
        self,
    ) -> StreamlinesCleanupReceipt:
        """Clear the static path and yield one Kit update before accepting it clean."""

        receipt = self.clear_streamlines_static_runtime_from_open_stage()
        try:
            import omni.kit.app
        except ImportError:
            return receipt
        await omni.kit.app.get_app().next_update_async()
        try:
            import omni.usd
        except ImportError:
            return receipt
        stage = omni.usd.get_context().get_stage()
        if not stage:
            return receipt
        return inspect_streamlines_runtime_cleanup(
            stage,
            pending_tasks=self._streamlines_pending_runtime_task_count(),
        )

    def _streamlines_pending_runtime_task_count(self) -> int:
        """Count DTRS-owned CAE subscriptions or active operators after teardown."""

        return len(self._flow_kit_cae_operator_subscriptions) + len(
            self._flow_kit_cae_active_operator_paths
        )

    @staticmethod
    def _empty_static_cleanup_receipt(
        pending_tasks: int,
    ) -> StreamlinesCleanupReceipt:
        """Treat a no-stage shutdown as clean after observer ownership is released."""

        return StreamlinesCleanupReceipt(
            source_present=False,
            operator_present=False,
            seed_present=False,
            runtime_preview_present=False,
            stale_relationships=0,
            remaining_layer_specs=0,
            duplicate_prims=0,
            pending_tasks=pending_tasks,
        )

    @staticmethod
    def _streamlines_carb_logger():
        """Return Kit logging without making diagnostics a runtime dependency."""

        try:
            import carb
        except ImportError:
            return None
        return carb

    # --- Cache build, validation, and playback ownership ---------------------

    def announce_streamlines_cache_build_ready(self) -> str:
        """Publish cache-build readiness without touching an existing artifact."""

        action = "Build Streamlines Cache"
        ready_header = "DTRS STREAMLINES | CACHE_BUILD | READY"
        message = f'{ready_header}\nNEXT_ACTION | Press "{action}"'
        carb = self._streamlines_carb_logger()
        if carb:
            carb.log_warn(with_dtrs_yerevan_timestamp(message))
        return f'Ready — Press "{action}".'

    def announce_streamlines_cache_playback_ready(self) -> str:
        """Publish cache-playback readiness only after the restart handoff."""

        action = "Run Cache Playback Acceptance"
        message = (
            "DTRS STREAMLINES | CACHE_PLAYBACK | READY\n"
            f'NEXT_ACTION | Press "{action}"'
        )
        carb = self._streamlines_carb_logger()
        if carb:
            carb.log_warn(with_dtrs_yerevan_timestamp(message))
        return f'Ready — Press "{action}".'

    def inspect_streamlines_cache_restart_handoff(self) -> StreamlinesCacheValidation:
        """Read cache provenance at startup without creating a Kit-CAE operator."""

        cache_paths = streamlines_cache_paths(self.config.repo_root)
        if not cache_paths.metadata_path.is_file():
            return StreamlinesCacheValidation(
                False,
                "No completed Streamlines cache metadata was found.",
            )
        if not cache_paths.geometry_path.is_file():
            return StreamlinesCacheValidation(
                False,
                "No completed Streamlines cache geometry was found.",
            )
        try:
            metadata = load_streamlines_cache_metadata(cache_paths.metadata_path)
            expected = self._streamlines_cache_expected_contract(
                stage_time_codes_per_second=metadata.time_codes_per_second,
            )
            return validate_streamlines_cache(
                metadata,
                source_signature=expected["source_signature"],
                settings_signature=expected["settings_signature"],
                workload=expected["workload"],
                dataset_identity=expected["dataset_identity"],
                sample_count=expected["sample_count"],
                geometry_path=cache_paths.geometry_path,
            )
        except Exception as error:
            return StreamlinesCacheValidation(
                False,
                f"Cache restart handoff inspection failed: {error}",
            )

    async def build_streamlines_cache_in_kit(
        self,
        status_callback: StatusCallback | None = None,
    ) -> StreamlinesCacheBuildResult:
        """Build one complete Nominal cache from real Kit-CAE/UsdRT results.

        The VTI sequence remains authoritative only while this bounded build
        runs. The USDC result is a derived view cache and leaves the accepted
        Historical recompute evidence remains documentation only.
        """

        if self._flow_lifecycle_state != "DETACHED":
            return StreamlinesCacheBuildResult(
                False,
                "Cache build is unavailable while airflow Attach is active.",
            )

        started_at = time.monotonic()
        carb = self._streamlines_carb_logger()
        cleanup = None
        cache_paths = streamlines_cache_paths(self.config.repo_root)
        build_mode = streamlines_cache_build_mode(cache_paths)
        self._streamlines_cache_build_active_sample_index = None
        try:
            if carb:
                carb.log_warn(
                    with_dtrs_yerevan_timestamp(
                        "DTRS STREAMLINES | CACHE_BUILD | " f"{build_mode}"
                    )
                )
            if status_callback:
                status_callback("Cache build: preparing manifest temporal source")
            cleanup = await self.clear_streamlines_static_runtime_in_kit()
            if not cleanup.clean:
                raise RuntimeError(
                    "Streamlines cleanup was not clean before cache build."
                )
            source = await self.prepare_streamlines_temporal_velocity_source_in_kit(
                status_callback=status_callback,
            )
            if source.workload != "Nominal":
                raise RuntimeError(
                    "Cache build is scoped to Nominal; "
                    f"current workload={source.workload}."
                )
            metadata, generation_ms = await self._build_cache_geometry_in_kit(
                source,
                cache_paths=cache_paths,
                status_callback=status_callback,
            )
            cleanup = await self.clear_streamlines_static_runtime_in_kit()
            if not cleanup.clean:
                raise RuntimeError(
                    "Streamlines cleanup was not clean after cache build."
                )
            replace_streamlines_cache_artifacts(cache_paths)
            if carb:
                carb.log_warn(
                    with_dtrs_yerevan_timestamp(
                        "DTRS STREAMLINES | CACHE_REPLACEMENT | PASS"
                    )
                )
        except asyncio.CancelledError:
            discard_streamlines_cache_staging(cache_paths)
            raise
        except Exception as error:
            discard_streamlines_cache_staging(cache_paths)
            cleanup = await self.clear_streamlines_static_runtime_in_kit()
            message = self._format_cache_build_failure(
                error=error,
                failed_sample_index=self._streamlines_cache_build_active_sample_index,
                cleanup=cleanup,
                total_ms=(time.monotonic() - started_at) * 1000.0,
            )
            if carb:
                carb.log_error(with_dtrs_yerevan_timestamp(message))
            if status_callback:
                status_callback("Cache build failed; inspect the structured log.")
            return StreamlinesCacheBuildResult(False, message)

        message = self._format_cache_build_success(
            metadata=metadata,
            cache_paths=cache_paths,
            generation_ms=generation_ms,
            total_ms=(time.monotonic() - started_at) * 1000.0,
        )
        if carb:
            carb.log_warn(with_dtrs_yerevan_timestamp(message))
        if status_callback:
            status_callback(
                "Cache build complete. Restart DTRS, then run playback acceptance."
            )
        self._streamlines_cache_build_active_sample_index = None
        return StreamlinesCacheBuildResult(True, message, metadata)

    async def run_streamlines_cache_playback_acceptance_in_kit(
        self,
        status_callback: StatusCallback | None = None,
    ) -> StreamlinesCachePlaybackResult:
        """Validate a restarted cache and replay two exact source-clock loops."""

        if self._flow_lifecycle_state != "DETACHED":
            return StreamlinesCachePlaybackResult(
                "FAIL",
                "Cache playback is unavailable while airflow Attach is active.",
            )

        started_at = time.monotonic()
        carb = self._streamlines_carb_logger()
        cleanup = None
        failed_stage = "LOAD"
        try:
            if carb:
                carb.log_warn(
                    with_dtrs_yerevan_timestamp(
                        "DTRS STREAMLINES | CACHE_PLAYBACK | BEGIN"
                    )
                )
            if status_callback:
                status_callback("Cache playback: validating persistent cache")
            cleanup = await self.clear_streamlines_static_runtime_in_kit()
            if not cleanup.clean:
                message = "Streamlines cleanup was not clean before playback."
                raise RuntimeError(message)
            loaded = await self._load_streamlines_cache_for_playback_in_kit()
            failed_stage = "PLAYBACK"
            if status_callback:
                status_callback("Cache playback: replaying 2 loops at source cadence")
            measurement = await self._play_cached_streamlines_in_kit(
                loaded,
                status_callback=status_callback,
            )
            failed_stage = "CLEANUP"
            cleanup = await self.clear_streamlines_static_runtime_in_kit()
            if not cleanup.clean:
                raise RuntimeError("Streamlines cleanup was not clean after playback.")
        except asyncio.CancelledError:
            raise
        except Exception as error:
            cleanup = await self.clear_streamlines_static_runtime_in_kit()
            message = self._format_cache_playback_failure(
                failed_stage=failed_stage,
                error=error,
                cleanup=cleanup,
                total_ms=(time.monotonic() - started_at) * 1000.0,
            )
            if carb:
                carb.log_error(with_dtrs_yerevan_timestamp(message))
            if status_callback:
                status_callback("Cache playback TEST COMPLETE — FAIL; inspect log.")
            return StreamlinesCachePlaybackResult("FAIL", message)

        decision = (
            "CACHE_PLAYBACK_VIABLE"
            if measurement["viable"]
            else "CACHE_PLAYBACK_NOT_VIABLE"
        )
        message = self._format_cache_playback_terminal(
            loaded=loaded,
            measurement=measurement,
            decision=decision,
            cleanup=cleanup,
            total_ms=(time.monotonic() - started_at) * 1000.0,
        )
        if carb:
            logger = carb.log_warn
            if decision != "CACHE_PLAYBACK_VIABLE":
                logger = carb.log_error
            logger(with_dtrs_yerevan_timestamp(message))
        if status_callback:
            status_callback(
                "Cache playback TEST COMPLETE — VIABLE; no further manual "
                "action required."
                if decision == "CACHE_PLAYBACK_VIABLE"
                else "Cache playback TEST COMPLETE — NOT VIABLE; inspect log."
            )
        return StreamlinesCachePlaybackResult(decision, message)

    # --- Manifest-backed temporal source ownership ---------------------------

    async def prepare_streamlines_temporal_velocity_source_in_kit(
        self,
        *,
        status_callback: StatusCallback | None = None,
    ) -> TemporalVelocitySourceDescriptor:
        """Author the shared ``vel.fileNames`` time-sample source for Streamlines.

        The first VTI is imported once through the spatial-validation seam. All
        remaining real VTI files are selected by USD time codes on that same
        imported ``vel`` field, matching the accepted DTRS temporal mechanism.
        """

        binding = self.resolve_current_workload_airflow_binding()
        airflow_dataset = discover_airflow_dataset(
            self.config.asset_root,
            binding.dataset,
        )
        descriptor = await self.prepare_static_velocity_sample_in_kit(
            sample_index=0,
            status_callback=status_callback,
        )
        if (
            descriptor.workload != binding.workload_mode
            or descriptor.dataset_identity != binding.dataset_identity
        ):
            raise RuntimeError(
                "Telemetry workload changed while the temporal Streamlines source was "
                "being prepared; retry from a stable workload."
            )
        velocity_paths = airflow_dataset.velocity_vti_sequence_paths
        if (
            not velocity_paths
            or descriptor.vti_path.resolve() != velocity_paths[0].resolve()
        ):
            raise RuntimeError(
                "Temporal Streamlines source does not begin with the accepted "
                "manifest sample zero."
            )

        import omni.kit.app
        import omni.usd
        from omni.cae.schema import vtk as cae_vtk
        from pxr import Sdf, Usd

        app = omni.kit.app.get_app()
        stage = omni.usd.get_context().get_stage()
        if not stage:
            raise RuntimeError("Temporal Streamlines source requires an open stage.")
        field_prim = stage.GetPrimAtPath(descriptor.velocity_field_prim_path)
        if not field_prim or not field_prim.IsValid():
            raise RuntimeError(
                "Accepted static velocity field is unavailable for temporal authoring."
            )
        if status_callback:
            status_callback(
                f"Authoring temporal source · {len(velocity_paths)} manifest samples"
            )
        previous_target = stage.GetEditTarget()
        try:
            session_layer = stage.GetSessionLayer()
            session_layer.timeCodesPerSecond = float(stage.GetTimeCodesPerSecond())
            stage.SetEditTarget(session_layer)
            author_samples = (
                flow_temporal.author_kit_cae_temporal_velocity_samples_in_batches
            )
            time_codes = await author_samples(
                field_prim,
                velocity_paths,
                float(stage.GetTimeCodesPerSecond()),
                airflow_dataset.sample_interval_seconds,
                cae_vtk,
                Sdf,
                Usd,
                app.next_update_async,
                self.TEMPORAL_AUTHORING_BATCH_SIZE,
            )
        finally:
            stage.SetEditTarget(previous_target)
        await app.next_update_async()
        source = TemporalVelocitySourceDescriptor(
            static_descriptor=descriptor,
            velocity_paths=velocity_paths,
            sample_time_codes=time_codes,
            time_codes_per_second=float(stage.GetTimeCodesPerSecond()),
            sample_interval_seconds=airflow_dataset.sample_interval_seconds,
        )
        if (
            len(
                flow_temporal.kit_cae_file_names_time_samples(
                    field_prim,
                    cae_vtk,
                    Usd,
                )
            )
            != source.sample_count
        ):
            raise RuntimeError(
                "Temporal Streamlines field did not retain every manifest time sample."
            )
        self._streamlines_temporal_source_descriptor = source
        return source

    @staticmethod
    async def _select_temporal_source_in_kit(
        app,
        *,
        timeline,
        field_prim,
        sample: TemporalSourceSample,
        cae_vtk,
        Usd,
    ):
        """Select and verify one real manifest VTI before touching its consumer."""

        timeline.pause()
        timeline.set_current_time(sample.source_time_seconds)
        # Selection is authored on the same temporal ``vel`` field as Stage 6.
        # Yield twice before reading it so Kit has composed the new time code.
        await app.next_update_async()
        await app.next_update_async()
        selected_asset = flow_temporal.kit_cae_selected_velocity_asset(
            field_prim,
            sample.time_code,
            cae_vtk,
            Usd,
        )
        expected_asset = sample.source_vti.resolve()
        if selected_asset is None or selected_asset.resolve() != expected_asset:
            raise RuntimeError(
                "Temporal field selected a different source VTI: "
                f"expected={expected_asset}, actual={selected_asset}."
            )
        return selected_asset

    async def prepare_static_velocity_sample_in_kit(
        self,
        sample_index: int = 0,
        status_callback: StatusCallback | None = None,
        *,
        force_failure_after_import: bool = False,
    ) -> StaticVelocitySourceDescriptor:
        """Resolve, import, and spatially validate one manifest-backed VTI sample.

        This is source preparation rather than a partial Flow Attach. It reuses
        the accepted Stage 6 origin compatibility shim because the current VTK
        importer does not retain the Houdini ImageData origin by itself.
        """

        binding = self.resolve_current_workload_airflow_binding()
        cache = self.config.simulation_cache
        sample = resolve_static_velocity_sample(
            self.config.asset_root,
            binding,
            cache.velocity_field_name,
            sample_index,
        )
        if status_callback:
            status_callback(
                f"Preparing Streamlines source · {sample.dataset_identity} · "
                f"VTI {sample.sample_index}"
            )

        import carb
        import omni.kit.app
        import omni.timeline
        import omni.usd
        from omni.cae.importer.vtk import import_to_stage
        from omni.cae.schema import cae
        from omni.cae.schema import vtk as cae_vtk
        from pxr import Gf, UsdGeom

        app = omni.kit.app.get_app()
        extension_manager = app.get_extension_manager()
        required_extensions = (
            "omni.cae.delegate.vtk",
            "omni.cae.importer.vtk",
        )
        disabled_extensions = [
            extension_id
            for extension_id in required_extensions
            if not extension_manager.is_extension_enabled(extension_id)
        ]
        if disabled_extensions:
            raise RuntimeError(
                "Kit-CAE static VTI import is unavailable; start DTRS through "
                "start_dtrs.bat with these extensions enabled: "
                f"{', '.join(disabled_extensions)}."
            )

        stage = omni.usd.get_context().get_stage()
        if not stage:
            raise RuntimeError("Static source preparation requires an open stage.")
        timeline = omni.timeline.get_timeline_interface()
        velocity_field_name = sample.velocity_field_name
        field_path = f"{self.STATIC_IMPORT_ROOT}/PointData/{velocity_field_name}"
        cleanup = clear_static_velocity_source_from_stage(
            stage, self.STATIC_IMPORT_ROOT
        )
        if not cleanup.success:
            raise RuntimeError(
                "Previous static source cleanup did not remove its runtime prim."
            )
        await app.next_update_async()
        self._streamlines_static_source_descriptor = None
        self._streamlines_static_source_diagnostics_failure = None
        import_started_at = time.monotonic()
        try:
            await import_to_stage(str(sample.vti_path), self.STATIC_IMPORT_ROOT)
            await app.next_update_async()
            carb.log_warn(
                with_dtrs_yerevan_timestamp(
                    "DTRS STREAMLINES | VTI_IMPORT | PASS | "
                    "duration_ms="
                    f"{(time.monotonic() - import_started_at) * 1000.0:.0f}"
                )
            )

            dataset_prim = stage.GetPrimAtPath(self.STATIC_DATASET_PATH)
            field_prim = stage.GetPrimAtPath(field_path)
            spatial_started_at = time.monotonic()
            previous_target = stage.GetEditTarget()
            stage.SetEditTarget(stage.GetSessionLayer())
            try:
                self._author_kit_cae_vti_origin_session_opinion(
                    dataset_prim,
                    sample.source_origin,
                    cae_vtk,
                    Gf,
                )
            finally:
                stage.SetEditTarget(previous_target)
            await app.next_update_async()
            imported_grid = self._validate_kit_cae_velocity_field(
                dataset_prim,
                field_prim,
                {
                    "dimensions": sample.dimensions,
                    "spacing": sample.spacing,
                },
                cae,
                cae_vtk,
            )
            descriptor = describe_imported_static_velocity_source(
                sample,
                dataset_prim_path=self.STATIC_DATASET_PATH,
                velocity_field_prim_path=field_path,
                imported_grid=imported_grid,
                stage_meters_per_unit=float(UsdGeom.GetStageMetersPerUnit(stage)),
            )
            carb.log_warn(
                with_dtrs_yerevan_timestamp(
                    "DTRS STREAMLINES | SPATIAL_VALIDATION | PASS | "
                    "duration_ms="
                    f"{(time.monotonic() - spatial_started_at) * 1000.0:.0f}"
                )
            )
            try:
                evidence = inspect_static_source_runtime(
                    stage,
                    import_root_path=self.STATIC_IMPORT_ROOT,
                    field_prim=field_prim,
                    cae_vtk=cae_vtk,
                    timeline=timeline,
                )
                carb.log_warn(
                    with_dtrs_yerevan_timestamp(
                        format_static_source_acceptance(descriptor, cleanup, evidence)
                    )
                )
            except Exception as error:
                # Evidence is required for acceptance, but a diagnostic failure
                # must not discard the already validated reusable source.
                diagnostic_reason = (
                    " ".join(str(error).splitlines()) or type(error).__name__
                )
                self._streamlines_static_source_diagnostics_failure = diagnostic_reason
                try:
                    carb.log_error(
                        with_dtrs_yerevan_timestamp(
                            "DTRS STREAMLINES | DIAGNOSTICS | FAIL | "
                            f"reason={diagnostic_reason}"
                        )
                    )
                except Exception:
                    # A failed secondary log sink must not discard the source
                    # descriptor already validated above.
                    self._streamlines_static_source_diagnostics_failure = (
                        diagnostic_reason
                    )
            else:
                if not evidence.package_a_clean:
                    raise RuntimeError(
                        "Velocity-source import detected forbidden runtime state; "
                        "review the DTRS STREAMLINES acceptance block."
                    )
            self._streamlines_static_source_descriptor = descriptor
            if force_failure_after_import:
                raise RuntimeError("Forced velocity-source failure after import.")
        except Exception:
            self._streamlines_static_source_descriptor = None
            clear_static_velocity_source_from_stage(stage, self.STATIC_IMPORT_ROOT)
            raise

        if status_callback:
            status_callback(
                f"Static source ready · {descriptor.dataset_identity} · "
                f"VTI {descriptor.sample_index}"
            )
        return descriptor

    @staticmethod
    def _streamlines_integration_settings(
        streamlines_api,
    ) -> tuple[tuple[str, str], ...]:
        """Capture request-independent settings shared by every cache sample."""

        return (
            ("direction", str(streamlines_api.GetDirectionAttr().Get())),
            ("min_step_size", str(streamlines_api.GetMinStepSizeAttr().Get())),
            (
                "initial_step_size",
                str(streamlines_api.GetInitialStepSizeAttr().Get()),
            ),
            ("max_step_size", str(streamlines_api.GetMaxStepSizeAttr().Get())),
            ("max_steps", str(streamlines_api.GetMaxStepsAttr().Get())),
            ("width", str(streamlines_api.GetWidthAttr().Get())),
        )

    @staticmethod
    def _streamlines_source_processing_evidence(
        operator_prim,
        *,
        operator_type: str,
        cae_viz,
    ) -> tuple[str, tuple[tuple[str, str], ...]]:
        """Record fixed source-faithful handling used by the standard operator."""

        if operator_type == "standard":
            has_subset = operator_prim.HasAPI(cae_viz.DatasetSubsetAPI, "source")
            return ("subset" if has_subset else "MISSING_SUBSET_API"), ()
        has_voxelization = operator_prim.HasAPI(
            cae_viz.DatasetVoxelizationAPI,
            "source",
        )
        if not has_voxelization:
            return "MISSING_VOXELIZATION_API", ()
        voxelization_api = cae_viz.DatasetVoxelizationAPI(operator_prim, "source")
        return "voxelized", (
            (
                "voxel_size_mode",
                str(voxelization_api.GetVoxelSizeModeAttr().Get()),
            ),
            (
                "max_resolution",
                str(voxelization_api.GetMaxResolutionAttr().Get()),
            ),
            ("voxel_size", str(voxelization_api.GetVoxelSizeAttr().Get())),
            (
                "field_centering",
                str(voxelization_api.GetFieldCenteringAttr().Get()),
            ),
            (
                "inflate_bounds",
                str(voxelization_api.GetInflateBoundsAttr().Get()),
            ),
        )

    # --- Cache geometry build and playback ownership -------------------------

    async def _build_cache_geometry_in_kit(
        self,
        source: TemporalVelocitySourceDescriptor,
        *,
        cache_paths: StreamlinesCachePaths,
        status_callback: StatusCallback | None,
    ) -> tuple[StreamlinesCacheMetadata, tuple[float, ...]]:
        """Persist every real manifest sample without creating a RuntimePreview."""

        import carb
        import omni.kit.app
        import omni.timeline
        import omni.usd
        import warp as wp
        from omni.cae.data import usd_utils as cae_usd_utils
        from omni.cae.data.commands import execute_command
        from omni.cae.schema import viz as cae_viz
        from omni.cae.schema import vtk as cae_vtk
        from pxr import Sdf, Usd, UsdGeom
        from usdrt import UsdGeom as UsdGeomRT

        app = omni.kit.app.get_app()
        stage = omni.usd.get_context().get_stage()
        if not stage:
            raise RuntimeError("Cache build requires an open stage.")
        descriptor = source.static_descriptor
        dataset_prim = stage.GetPrimAtPath(descriptor.dataset_prim_path)
        field_prim = stage.GetPrimAtPath(descriptor.velocity_field_prim_path)
        if not dataset_prim or not dataset_prim.IsValid():
            raise RuntimeError("Cache build dataset prim is unavailable.")
        if not field_prim or not field_prim.IsValid():
            raise RuntimeError("Cache build velocity field is unavailable.")

        request = self._build_streamlines_cache_request(descriptor)
        cache_paths.directory.mkdir(parents=True, exist_ok=True)
        for partial_path in (
            cache_paths.partial_geometry_path,
            cache_paths.partial_metadata_path,
        ):
            partial_path.unlink(missing_ok=True)
        cache_stage = Usd.Stage.CreateNew(cache_paths.partial_geometry_path.as_posix())
        cache_stage.SetTimeCodesPerSecond(source.time_codes_per_second)
        cache_stage.SetStartTimeCode(source.sample_time_codes[0])
        cache_stage.SetEndTimeCode(source.sample_time_codes[-1])
        cache_root = UsdGeom.Xform.Define(cache_stage, CACHE_PLAYBACK_ROOT_PATH)
        cache_root.GetPrim().SetCustomDataByKey(
            "dtrs:streamlinesCacheSchema",
            CACHE_SCHEMA_VERSION,
        )
        cache_curves = UsdGeom.BasisCurves.Define(
            cache_stage,
            CACHE_PLAYBACK_CURVES_PATH,
        )
        cache_curves.CreateBasisAttr().Set(UsdGeom.Tokens.bspline)
        cache_curves.CreateTypeAttr().Set(UsdGeom.Tokens.cubic)
        cache_curves.CreateWrapAttr().Set(UsdGeom.Tokens.pinned)
        cache_curves.SetWidthsInterpolation(UsdGeom.Tokens.constant)
        UsdGeom.PrimvarsAPI(cache_curves.GetPrim()).CreatePrimvar(
            "widths",
            Sdf.ValueTypeNames.FloatArray,
            UsdGeom.Tokens.constant,
        ).Set([request.width])
        cache_curves.CreateDisplayColorPrimvar(UsdGeom.Tokens.constant).Set(
            [(0.1, 0.8, 1.0)]
        )

        previous_target = stage.GetEditTarget()
        states: list[StreamlinesCacheState] = []
        generation_ms: list[float] = []
        try:
            stage.SetEditTarget(stage.GetSessionLayer())
            await execute_command(
                "CreateCaeVizMeshPrim",
                prim_type="UnitSphere",
                prim_path=request.seed_path,
            )
            await execute_command(
                "TransformPrimSRT",
                path=request.seed_path,
                new_translation=list(request.seed_center),
                new_scale=[request.seed_radius] * 3,
            )
            await app.next_update_async()
            self._start_kit_cae_operator_tracking()
            timeline = omni.timeline.get_timeline_interface()
            for index, source_vti in enumerate(source.velocity_paths):
                self._streamlines_cache_build_active_sample_index = index
                sample_started_at = time.monotonic()
                sample = TemporalSourceSample(
                    ordinal=index + 1,
                    total=source.sample_count,
                    sample_index=index,
                    source_vti=source_vti,
                    source_time_seconds=(
                        source.sample_time_codes[index] / source.time_codes_per_second
                    ),
                    time_code=source.sample_time_codes[index],
                )
                selected_asset = await self._select_temporal_source_in_kit(
                    app,
                    timeline=timeline,
                    field_prim=field_prim,
                    sample=sample,
                    cae_vtk=cae_vtk,
                    Usd=Usd,
                )
                if selected_asset.resolve() != source_vti.resolve():
                    raise RuntimeError(
                        "Cache build selected a VTI outside the active manifest."
                    )
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
                    timeline=timeline,
                    execute_command=execute_command,
                    preview_path=None,
                    Sdf=Sdf,
                )
                evidence = execution.evidence
                if not execution.execution_receipt.accepted:
                    raise RuntimeError(
                        "Cache build received an unpaired Kit-CAE execution."
                    )
                if evidence.runtime_curve_bounds is None:
                    raise RuntimeError("Cache build UsdRT geometry has no bounds.")
                time_code = Usd.TimeCode(sample.time_code)
                cache_curves.GetPointsAttr().Set(
                    list(evidence.runtime_point_positions),
                    time_code,
                )
                cache_curves.GetCurveVertexCountsAttr().Set(
                    list(evidence.runtime_curve_vertex_counts),
                    time_code,
                )
                cache_curves.CreateExtentAttr().Set(
                    list(evidence.runtime_curve_bounds),
                    time_code,
                )
                elapsed_ms = (time.monotonic() - sample_started_at) * 1000.0
                states.append(
                    StreamlinesCacheState(
                        sample_index=index,
                        source_time_seconds=sample.source_time_seconds,
                        time_code=sample.time_code,
                        source_vti=source_vti.resolve().as_posix(),
                        source_vti_identity=vti_file_identity(source_vti),
                        curve_count=evidence.runtime_curve_count,
                        point_count=evidence.runtime_point_count,
                        topology_signature=cache_topology_signature(
                            evidence.runtime_curve_vertex_counts
                        ),
                        geometry_signature=cache_geometry_signature(
                            curve_count=evidence.runtime_curve_count,
                            point_count=evidence.runtime_point_count,
                            bounds=evidence.runtime_curve_bounds,
                            point_head=evidence.point_head,
                            point_tail=evidence.point_tail,
                        ),
                        generation_ms=elapsed_ms,
                        bounds=evidence.runtime_curve_bounds,
                    )
                )
                generation_ms.append(elapsed_ms)
                if status_callback:
                    status_callback(
                        f"Cache build: sample {sample.ordinal}/{sample.total}"
                    )
                if index == 0 or sample.ordinal % 10 == 0:
                    carb.log_warn(
                        with_dtrs_yerevan_timestamp(
                            "DTRS STREAMLINES | CACHE_BUILD | "
                            f"SAMPLE {sample.ordinal}/{sample.total} | PASS | "
                            f"generation_ms={elapsed_ms:.0f}"
                        )
                    )
        finally:
            self._stop_kit_cae_operator_tracking()
            stage.SetEditTarget(previous_target)

        cache_stage.GetRootLayer().Save()
        geometry_sha256 = file_sha256(cache_paths.partial_geometry_path)
        metadata = build_streamlines_cache_metadata(
            source,
            request,
            states,
            geometry_file_name=cache_paths.geometry_path.name,
            geometry_sha256=geometry_sha256,
        )
        staged_metadata = replace(
            metadata,
            geometry_file_name=cache_paths.partial_geometry_path.name,
        )
        staged_validation = validate_streamlines_cache(
            staged_metadata,
            source_signature=metadata.source_signature,
            settings_signature=metadata.settings_signature,
            workload=metadata.workload,
            dataset_identity=metadata.dataset_identity,
            sample_count=metadata.sample_count,
            geometry_path=cache_paths.partial_geometry_path,
        )
        if not staged_validation.valid:
            raise RuntimeError(
                "Staged Streamlines cache validation failed: "
                f"{staged_validation.message}"
            )
        cache_paths.partial_metadata_path.write_text(
            serialise_streamlines_cache_metadata(metadata),
            encoding="utf-8",
        )
        return metadata, tuple(generation_ms)

    async def _load_streamlines_cache_for_playback_in_kit(self) -> dict[str, object]:
        """Attach a complete cache only after identity validation succeeds."""

        import omni.kit.app
        import omni.usd
        from pxr import UsdGeom

        started_at = time.monotonic()
        stage = omni.usd.get_context().get_stage()
        if not stage:
            raise RuntimeError("Cache playback requires an open stage.")
        cache_paths = streamlines_cache_paths(self.config.repo_root)
        if not cache_paths.metadata_path.is_file():
            raise RuntimeError("No completed Streamlines cache metadata was found.")
        if not cache_paths.geometry_path.is_file():
            raise RuntimeError("No completed Streamlines cache geometry was found.")

        memory_before = capture_viewport_performance_sample()
        metadata = load_streamlines_cache_metadata(cache_paths.metadata_path)
        expected = self._streamlines_cache_expected_contract(
            stage_time_codes_per_second=float(stage.GetTimeCodesPerSecond()),
        )
        validation = validate_streamlines_cache(
            metadata,
            source_signature=expected["source_signature"],
            settings_signature=expected["settings_signature"],
            workload=expected["workload"],
            dataset_identity=expected["dataset_identity"],
            sample_count=expected["sample_count"],
            geometry_path=cache_paths.geometry_path,
        )
        if not validation.valid:
            if metadata.settings is None or validation.message.startswith(
                "Cache settings"
            ):
                self._log_streamlines_cache_identity_mismatch(metadata, expected)
            raise RuntimeError(
                "Cache validation failed: "
                f"{validation.message} Explicitly rebuild the cache."
            )
        self._attach_streamlines_cache_playback_layer(
            stage,
            cache_paths,
        )
        app = omni.kit.app.get_app()
        for _ in range(3):
            await app.next_update_async()
        curves_prim = stage.GetPrimAtPath(CACHE_PLAYBACK_CURVES_PATH)
        if not curves_prim or not curves_prim.IsValid():
            raise RuntimeError("Cache layer did not compose its BasisCurves prim.")
        curves = UsdGeom.BasisCurves(curves_prim)
        actual_time_codes = tuple(
            float(value) for value in curves.GetPointsAttr().GetTimeSamples()
        )
        expected_time_codes = tuple(state.time_code for state in metadata.states)
        if actual_time_codes != expected_time_codes:
            raise RuntimeError("Cache geometry time samples do not match metadata.")
        if stage.GetPrimAtPath(CACHE_BUILD_OPERATOR_PATH).IsValid():
            raise RuntimeError("Cache playback retained a Kit-CAE build operator.")
        return {
            "metadata": metadata,
            "paths": cache_paths,
            "curves": curves,
            "load_ms": (time.monotonic() - started_at) * 1000.0,
            "memory_before": memory_before,
            "memory_after": capture_viewport_performance_sample(),
            "kit_cae_streamlines_executions": 0,
        }

    def _streamlines_cache_expected_contract(
        self,
        *,
        stage_time_codes_per_second: float,
    ) -> dict[str, object]:
        """Resolve cache invalidation facts without importing a VTI into Kit."""

        binding = self.resolve_current_workload_airflow_binding()
        sample = resolve_static_velocity_sample(
            self.config.asset_root,
            binding,
            self.config.simulation_cache.velocity_field_name,
            sample_index=0,
        )
        dataset = discover_airflow_dataset(self.config.asset_root, binding.dataset)
        velocity_paths = dataset.velocity_vti_sequence_paths
        interval_seconds = dataset.sample_interval_seconds
        time_codes = tuple(
            index * stage_time_codes_per_second * interval_seconds
            for index in range(len(velocity_paths))
        )
        descriptor = StaticVelocitySourceDescriptor(
            workload=sample.workload,
            dataset_identity=sample.dataset_identity,
            sample_index=sample.sample_index,
            vti_path=sample.vti_path,
            dataset_prim_path=self.STATIC_DATASET_PATH,
            velocity_field_prim_path=(
                f"{self.STATIC_IMPORT_ROOT}/PointData/" f"{sample.velocity_field_name}"
            ),
            world_bounds=sample.source_world_bounds,
            dimensions=sample.dimensions,
            spacing=sample.spacing,
            origin=sample.source_origin,
            source_origin=sample.source_origin,
            stage_meters_per_unit=1.0,
        )
        request = self._build_streamlines_cache_request(descriptor)
        return {
            "workload": binding.workload_mode,
            "dataset_identity": binding.dataset_identity,
            "sample_count": len(velocity_paths),
            "source_signature": source_signature_from_values(
                workload=binding.workload_mode,
                dataset_identity=binding.dataset_identity,
                velocity_paths=velocity_paths,
                sample_time_codes=time_codes,
                time_codes_per_second=stage_time_codes_per_second,
                sample_interval_seconds=interval_seconds,
            ),
            "settings_signature": streamlines_settings_signature(request),
            "settings": streamlines_cache_settings(request),
        }

    def _build_streamlines_cache_request(
        self,
        descriptor: StaticVelocitySourceDescriptor,
    ) -> StreamlinesOperatorRequest:
        """Derive cache geometry settings from VTI data, not importer floats."""

        minimum = tuple(float(value) for value in descriptor.source_origin)
        maximum = tuple(
            minimum[index]
            + ((descriptor.dimensions[index] - 1) * descriptor.spacing[index])
            for index in range(3)
        )
        canonical_descriptor = replace(
            descriptor,
            world_bounds=(minimum, maximum),
            origin=minimum,
        )
        return replace(
            build_streamlines_operator_request(canonical_descriptor),
            operator_path=CACHE_BUILD_OPERATOR_PATH,
            seed_path=CACHE_BUILD_SEED_PATH,
            operator_type="standard",
        )

    def _log_streamlines_cache_identity_mismatch(
        self,
        metadata: StreamlinesCacheMetadata,
        expected: dict[str, object],
    ) -> None:
        """Log canonical identity evidence without dumping cache geometry details."""

        current = expected.get("settings")
        if metadata.settings is not None and isinstance(
            current, StreamlinesCacheSettings
        ):
            differences = cache_settings_differences(metadata.settings, current)
        elif metadata.settings is None:
            differences = ("canonical settings payload unavailable",)
        else:
            differences = ("current canonical settings payload unavailable",)
        cached_payload = (
            metadata.settings.to_dict() if metadata.settings is not None else None
        )
        current_payload = current.to_dict() if hasattr(current, "to_dict") else None
        carb = self._streamlines_carb_logger()
        if carb:
            message = "\n".join(
                (
                    "DTRS STREAMLINES | CACHE_IDENTITY | MISMATCH",
                    f"cached_settings_signature={metadata.settings_signature}",
                    f"expected_settings_signature="
                    f"{expected.get('settings_signature')}",
                    "cached_canonical_settings_seed="
                    f"{json.dumps(cached_payload, sort_keys=True)}",
                    "current_canonical_settings_seed="
                    f"{json.dumps(current_payload, sort_keys=True)}",
                    f"differing_fields={','.join(differences) or 'none'}",
                )
            )
            carb.log_error(with_dtrs_yerevan_timestamp(message))

    def _attach_streamlines_cache_playback_layer(
        self,
        stage,
        cache_paths: StreamlinesCachePaths,
    ) -> None:
        """Attach one verified cache file only to the transient Session Layer."""

        self._detach_streamlines_cache_playback_layer(stage)
        stage.GetSessionLayer().subLayerPaths.append(
            cache_paths.geometry_path.resolve().as_posix()
        )

    def _detach_streamlines_cache_playback_layer(self, stage) -> None:
        """Detach only this cache reference; the persisted cache stays on disk."""

        expected_paths = {
            streamlines_cache_paths(self.config.repo_root)
            .geometry_path.resolve()
            .as_posix()
        }
        session_layer = stage.GetSessionLayer()
        for sublayer_path in tuple(session_layer.subLayerPaths):
            try:
                matches_cache = (
                    Path(sublayer_path).resolve().as_posix() in expected_paths
                )
            except OSError:
                matches_cache = sublayer_path.replace("\\", "/") in expected_paths
            if matches_cache:
                session_layer.subLayerPaths.remove(sublayer_path)

    async def _play_cached_streamlines_in_kit(
        self,
        loaded: dict[str, object],
        *,
        status_callback: StatusCallback | None,
    ) -> dict[str, object]:
        """Display two exact loops through USD time samples without Kit-CAE work."""

        import omni.kit.app
        import omni.timeline
        from pxr import Usd

        metadata = loaded["metadata"]
        curves = loaded["curves"]
        if not isinstance(metadata, StreamlinesCacheMetadata):
            raise RuntimeError("Cache playback metadata is unavailable.")
        if metadata.sample_interval_seconds <= 0.0:
            raise RuntimeError("Cache playback sample interval must be positive.")
        sample_interval_seconds = metadata.sample_interval_seconds
        loop_duration_seconds = metadata.sample_count * sample_interval_seconds
        if abs(loop_duration_seconds - 16.0) > 1e-6:
            raise RuntimeError("Cached playback requires the fixed 16-second loop.")

        app = omni.kit.app.get_app()
        timeline = omni.timeline.get_timeline_interface()
        timeline.pause()
        baseline = capture_viewport_performance_sample()
        records: list[dict[str, object]] = []
        sustained_samples = []
        started_at = time.monotonic()
        previous_signature = None
        for tick_index in range(metadata.sample_count * 2):
            state = metadata.states[tick_index % metadata.sample_count]
            scheduled_at = started_at + (tick_index * metadata.sample_interval_seconds)
            await asyncio.sleep(max(0.0, scheduled_at - time.monotonic()))
            processing_started_at = time.monotonic()
            timeline.set_current_time(state.source_time_seconds)
            for _ in range(2):
                await app.next_update_async()
            points = tuple(
                tuple(float(component) for component in point)
                for point in (
                    curves.GetPointsAttr().Get(Usd.TimeCode(state.time_code)) or ()
                )
            )
            counts = tuple(
                int(value)
                for value in (
                    curves.GetCurveVertexCountsAttr().Get(Usd.TimeCode(state.time_code))
                    or ()
                )
            )
            bounds = tuple(
                tuple(float(component) for component in point)
                for point in (
                    curves.GetExtentAttr().Get(Usd.TimeCode(state.time_code)) or ()
                )
            )
            if len(bounds) != 2:
                raise RuntimeError("Cached state has invalid geometry bounds.")
            signature = cache_geometry_signature(
                curve_count=len(counts),
                point_count=len(points),
                bounds=(bounds[0], bounds[1]),
                point_head=points[:3],
                point_tail=points[-3:],
            )
            if signature != state.geometry_signature:
                raise RuntimeError(
                    "Cached geometry does not match its manifest state metadata."
                )
            completed_at = time.monotonic()
            deadline_ms = metadata.sample_interval_seconds * 1000.0
            start_lateness_ms = max(
                0.0,
                (processing_started_at - scheduled_at) * 1000.0,
            )
            completion_lateness_ms = max(
                0.0,
                (completed_at - scheduled_at) * 1000.0,
            )
            records.append(
                {
                    "tick_index": tick_index,
                    "state": state,
                    "switch_latency_ms": (completed_at - processing_started_at)
                    * 1000.0,
                    "start_lateness_ms": start_lateness_ms,
                    "completion_lateness_ms": completion_lateness_ms,
                    "pending_requests": int(start_lateness_ms >= deadline_ms),
                    "geometry_replaced": (
                        previous_signature is None or signature != previous_signature
                    ),
                }
            )
            previous_signature = signature
            if tick_index % 25 == 0:
                sustained_samples.append(capture_viewport_performance_sample())
            if status_callback and (tick_index + 1) % metadata.sample_count == 0:
                status_callback(
                    "Cache playback: completed "
                    f"loop {(tick_index + 1) // metadata.sample_count}/2"
                )

        recovery_started_at = time.monotonic()
        await asyncio.sleep(5.0)
        recovered = capture_viewport_performance_sample()
        deadline_ms = metadata.sample_interval_seconds * 1000.0
        switch_latencies = [float(record["switch_latency_ms"]) for record in records]
        completion_lateness = [
            float(record["completion_lateness_ms"]) for record in records
        ]
        expected_loop = tuple(range(metadata.sample_count))
        first_loop = tuple(
            record["state"].sample_index for record in records[: metadata.sample_count]
        )
        second_loop = tuple(
            record["state"].sample_index for record in records[metadata.sample_count :]
        )
        exact_mapping = first_loop == expected_loop and second_loop == expected_loop
        wrap_record = records[metadata.sample_count]
        loop_wrap = wrap_record["state"].sample_index == 0
        max_pending = max(int(record["pending_requests"]) for record in records)
        missed_deadlines = sum(value > deadline_ms for value in completion_lateness)
        drift_present = self._cache_playback_drift_present(records)
        return {
            "loop_duration_seconds": loop_duration_seconds,
            "baseline": baseline,
            "sustained_samples": tuple(sustained_samples),
            "recovered": recovered,
            "recovery_seconds": time.monotonic() - recovery_started_at,
            "switch_latency_median_ms": median(switch_latencies),
            "switch_latency_max_ms": max(switch_latencies),
            "missed_deadlines": missed_deadlines,
            "max_pending": max_pending,
            "drift_present": drift_present,
            "exact_mapping": exact_mapping,
            "loop_wrap": loop_wrap,
            "viable": bool(
                exact_mapping
                and loop_wrap
                and missed_deadlines == 0
                and max_pending == 0
                and not drift_present
            ),
        }

    @staticmethod
    def _cache_playback_drift_present(records: list[dict[str, object]]) -> bool:
        """Detect growing lateness rather than one isolated scheduler jitter."""

        lateness = [float(record["start_lateness_ms"]) for record in records]
        if len(lateness) < 10:
            return False
        first = median(lateness[:5])
        last = median(lateness[-5:])
        return last - first > 20.0 and last > 20.0

    @staticmethod
    def _format_cache_build_success(
        *,
        metadata: StreamlinesCacheMetadata,
        cache_paths: StreamlinesCachePaths,
        generation_ms: tuple[float, ...],
        total_ms: float,
    ) -> str:
        """Summarise all 80 build states without dumping their raw geometry."""

        cache_size = (
            cache_paths.geometry_path.stat().st_size
            + cache_paths.metadata_path.stat().st_size
        )
        first_state = metadata.states[0]
        settings = metadata.settings
        max_steps = settings.max_steps if settings else "unknown"
        return "\n".join(
            (
                "DTRS STREAMLINES | CACHE_BUILD | PASS",
                f"workload={metadata.workload}",
                f"dataset={metadata.dataset_identity}",
                f"sample_count={metadata.sample_count}",
                f"generated_curve_count={first_state.curve_count}",
                f"generated_point_count={first_state.point_count}",
                f"max_steps={max_steps}",
                f"source_signature={metadata.source_signature}",
                f"settings_signature={metadata.settings_signature}",
                f"cache_geometry={cache_paths.geometry_path}",
                f"cache_size_bytes={cache_size}",
                f"generation_ms_median={median(generation_ms):.0f}",
                f"generation_ms_max={max(generation_ms):.0f}",
                f"topology_consistent={metadata.topology_consistent}",
                "failed_samples=()",
                "state=VALID",
                "NEXT_ACTION | Restart DTRS, then press "
                '"Run Cache Playback Acceptance"',
                f"total_ms={total_ms:.0f}",
            )
        )

    @staticmethod
    def _format_cache_build_failure(
        *,
        error: Exception,
        failed_sample_index: int | None,
        cleanup: StreamlinesCleanupReceipt,
        total_ms: float,
    ) -> str:
        """Report a broken build without certifying a partial cache artifact."""

        return "\n".join(
            (
                "========================================",
                "DTRS STREAMLINES | CACHE_BUILD | FAIL",
                "========================================",
                f"failed_sample_index={failed_sample_index}",
                f"reason={error}",
                f"rollback={'CLEAN' if cleanup.clean else 'DIRTY'}",
                "cache_replacement=NOT_APPLIED",
                "result=FAIL",
                f"total_ms={total_ms:.0f}",
            )
        )

    @staticmethod
    def _format_cache_playback_failure(
        *,
        failed_stage: str,
        error: Exception,
        cleanup: StreamlinesCleanupReceipt,
        total_ms: float,
    ) -> str:
        """Keep a harness error distinct from CACHE_PLAYBACK_NOT_VIABLE."""

        next_action = (
            "NEXT_ACTION | Inspect the failure before retrying cached playback."
        )
        return "\n".join(
            (
                "========================================",
                "DTRS STREAMLINES | CACHE_PLAYBACK | TEST COMPLETE | FAIL",
                "========================================",
                f"failed_stage={failed_stage}",
                f"reason={error}",
                f"rollback={'CLEAN' if cleanup.clean else 'DIRTY'}",
                next_action,
                f"total_ms={total_ms:.0f}",
            )
        )

    @staticmethod
    def _format_cache_playback_terminal(
        *,
        loaded: dict[str, object],
        measurement: dict[str, object],
        decision: str,
        cleanup: StreamlinesCleanupReceipt,
        total_ms: float,
    ) -> str:
        """Report the cache decision with source-clock and memory evidence."""

        metadata = loaded["metadata"]
        if not isinstance(metadata, StreamlinesCacheMetadata):
            raise RuntimeError("Cache terminal metadata is unavailable.")
        memory_before = loaded["memory_before"]
        memory_after = loaded["memory_after"]
        sustained_samples = measurement["sustained_samples"]
        sustained_fps = [
            sample.fps
            for sample in sustained_samples
            if getattr(sample, "fps", None) is not None
        ]
        sustained_fps_text = (
            f"{median(sustained_fps):.1f}" if sustained_fps else "unavailable"
        )

        def sustained_value(attribute: str) -> str:
            values = [
                getattr(sample, attribute)
                for sample in sustained_samples
                if getattr(sample, attribute, None) is not None
            ]
            return f"{median(values):.1f}" if values else "unavailable"

        switch_max = float(measurement["switch_latency_max_ms"])
        headroom_10hz = 100.0 - switch_max
        headroom_12hz = (1000.0 / 12.0) - switch_max
        terminal = "VIABLE" if decision == "CACHE_PLAYBACK_VIABLE" else "NOT_VIABLE"

        def value(sample, attribute: str) -> str:
            raw = getattr(sample, attribute, None)
            return "unavailable" if raw is None else f"{raw:.1f}"

        return "\n".join(
            (
                "========================================",
                "DTRS STREAMLINES | CACHE_PLAYBACK",
                f"TEST COMPLETE | {terminal}",
                "========================================",
                f"decision={decision}",
                f"workload={metadata.workload}",
                f"dataset={metadata.dataset_identity}",
                f"sample_count={metadata.sample_count}",
                "cache_manifest_mapping="
                f"{metadata.sample_count}/{metadata.sample_count}",
                f"loop_duration_seconds={measurement['loop_duration_seconds']:.1f}",
                f"source_cadence_hz={1.0 / metadata.sample_interval_seconds:.6g}",
                f"source_period_ms={metadata.sample_interval_seconds * 1000.0:.0f}",
                "interpolation=NONE",
                "kit_cae_streamlines_executions="
                f"{loaded['kit_cae_streamlines_executions']}",
                "runtime_preview_rebuilds=0",
                f"cache_load_ms={loaded['load_ms']:.0f}",
                "cache_load_memory_gib="
                f"gpu_before={value(memory_before, 'gpu_memory_used_gib')}; "
                f"gpu_after={value(memory_after, 'gpu_memory_used_gib')}; "
                f"process_before={value(memory_before, 'process_memory_used_gib')}; "
                f"process_after={value(memory_after, 'process_memory_used_gib')}",
                "cached_switch_latency_ms="
                f"median={measurement['switch_latency_median_ms']:.1f}; "
                f"max={measurement['switch_latency_max_ms']:.1f}",
                f"missed_200ms_deadlines={measurement['missed_deadlines']}",
                f"max_pending_requests={measurement['max_pending']}",
                "scheduling_drift="
                f"{'PRESENT' if measurement['drift_present'] else 'NONE'}",
                "exact_sample_mapping="
                f"{'PASS' if measurement['exact_mapping'] else 'FAIL'}",
                f"loop_wrap={'PASS' if measurement['loop_wrap'] else 'FAIL'}",
                f"baseline_fps={value(measurement['baseline'], 'fps')}",
                f"sustained_fps={sustained_fps_text}",
                f"recovered_fps={value(measurement['recovered'], 'fps')}",
                f"sustained_gpu_memory_gib={sustained_value('gpu_memory_used_gib')}",
                "sustained_process_memory_gib="
                f"{sustained_value('process_memory_used_gib')}",
                f"recovered_gpu_memory_gib="
                f"{value(measurement['recovered'], 'gpu_memory_used_gib')}",
                "recovered_process_memory_gib="
                f"{value(measurement['recovered'], 'process_memory_used_gib')}",
                "future_10hz_headroom="
                f"ms={headroom_10hz:.1f}; credible={headroom_10hz >= 10.0}",
                "future_12hz_headroom="
                f"ms={headroom_12hz:.1f}; credible={headroom_12hz >= 10.0}",
                f"cleanup={'CLEAN' if cleanup.clean else 'DIRTY'}",
                "runtime_recompute=DOCUMENTED_FALLBACK_EVIDENCE_ONLY",
                "NEXT_ACTION | Review cached playback evidence.",
                f"total_ms={total_ms:.0f}",
            )
        )

    # --- Standard Kit-CAE Streamlines operator ownership ---------------------

    async def _prepare_streamlines_operator_in_kit(
        self,
        stage,
        *,
        app,
        request: StreamlinesOperatorRequest,
        descriptor: StaticVelocitySourceDescriptor,
        dataset_prim,
        cae_usd_utils,
        cae_viz,
        UsdGeom,
        execute_command,
    ) -> _PreparedStreamlinesOperator:
        """Create and bind a disposable operator without modifying shared inputs."""

        creation_started_at = time.monotonic()
        await execute_command(
            "CreateCaeVizStreamlines",
            dataset_path=request.dataset_prim_path,
            prim_path=request.operator_path,
            type=request.operator_type,
        )
        creation_duration_ms = (time.monotonic() - creation_started_at) * 1000.0
        operator_prim = stage.GetPrimAtPath(request.operator_path)
        if not operator_prim or not operator_prim.IsValid():
            raise RuntimeError(
                "CreateCaeVizStreamlines did not author its operator prim."
            )
        operator_api = cae_viz.OperatorAPI(operator_prim)
        operator_api.CreateEnabledAttr().Set(False)
        await app.next_update_async()

        streamlines_api = cae_viz.StreamlinesAPI(operator_prim)
        streamlines_api.GetDirectionAttr().Set(
            getattr(cae_viz.Tokens, request.direction)
        )
        streamlines_api.GetMinStepSizeAttr().Set(request.min_step_size)
        streamlines_api.GetInitialStepSizeAttr().Set(request.initial_step_size)
        streamlines_api.GetMaxStepSizeAttr().Set(request.max_step_size)
        streamlines_api.GetMaxStepsAttr().Set(request.max_steps)
        streamlines_api.GetWidthAttr().Set(request.width)
        widths_primvar = UsdGeom.PrimvarsAPI(operator_prim).GetPrimvar("widths")
        if widths_primvar and widths_primvar.IsDefined():
            widths_primvar.Set([request.width] * 4)
        cae_viz.DatasetSelectionAPI(operator_prim, "source").GetTargetRel().SetTargets(
            [request.dataset_prim_path]
        )
        cae_viz.DatasetSelectionAPI(operator_prim, "seeds").GetTargetRel().SetTargets(
            [request.seed_path]
        )
        velocity_selection = cae_viz.FieldSelectionAPI(operator_prim, "velocities")
        velocity_target = request.velocity_field_prim_path
        velocity_selection.GetTargetRel().SetTargets([velocity_target])
        velocity_selection.CreateModeAttr().Set(cae_viz.Tokens.unchanged)
        if request.operator_type != "standard":
            raise RuntimeError(
                "Only the standard Kit-CAE Streamlines operator is supported."
            )
        binding_evidence = inspect_streamlines_bindings(
            stage,
            operator_prim=operator_prim,
            dataset_prim=dataset_prim,
            cae_viz=cae_viz,
            cae_usd_utils=cae_usd_utils,
        )
        integration_settings = self._streamlines_integration_settings(streamlines_api)
        source_processing_mode, voxelization_settings = (
            self._streamlines_source_processing_evidence(
                operator_prim,
                operator_type=request.operator_type,
                cae_viz=cae_viz,
            )
        )
        self._validate_streamlines_bindings(
            request,
            binding_evidence=binding_evidence,
            source_processing_mode=source_processing_mode,
        )
        return _PreparedStreamlinesOperator(
            creation_duration_ms=creation_duration_ms,
            operator_prim=operator_prim,
            operator_api=operator_api,
            binding_evidence=binding_evidence,
            integration_settings=integration_settings,
            source_processing_mode=source_processing_mode,
            voxelization_settings=voxelization_settings,
            nanovdb_effective_grid=None,
        )

    @staticmethod
    def _validate_streamlines_bindings(
        request: StreamlinesOperatorRequest,
        *,
        binding_evidence,
        source_processing_mode: str,
    ) -> None:
        """Reject an operator whose source, seed, or velocity binding drifted."""

        expected_mode = "subset"
        if request.operator_type != "standard":
            expected_mode = "voxelized"
        if (
            binding_evidence.source_targets != (request.dataset_prim_path,)
            or binding_evidence.seed_targets != (request.seed_path,)
            or binding_evidence.velocity_targets != (request.velocity_field_prim_path,)
            or source_processing_mode != expected_mode
        ):
            raise RuntimeError(
                "Streamlines operator binding or processing contract was not accepted."
            )

    async def _cleanup_streamlines_operator_in_kit(
        self,
        stage,
        *,
        app,
        prepared: _PreparedStreamlinesOperator,
        UsdGeom,
    ) -> bool:
        """Remove one completed disposable operator before the next execution.

        Kit-CAE skips an unchanged enabled operator. Replacing this consumer
        preserves the shared VTI source while requiring a fresh execution.
        """

        prepared.operator_api.CreateEnabledAttr().Set(False)
        UsdGeom.Imageable(prepared.operator_prim).CreateVisibilityAttr().Set(
            UsdGeom.Tokens.invisible
        )
        await app.next_update_async()
        operator_path = prepared.operator_prim.GetPath()
        stage.RemovePrim(operator_path)
        await app.next_update_async()
        return not stage.GetPrimAtPath(operator_path).IsValid()

    async def _run_fresh_streamlines_operator_in_kit(
        self,
        stage,
        *,
        app,
        request: StreamlinesOperatorRequest,
        descriptor: StaticVelocitySourceDescriptor,
        dataset_prim,
        field_prim,
        cae_usd_utils,
        cae_viz,
        cae_vtk,
        UsdGeom,
        UsdGeomRT,
        wp,
        timeline,
        execute_command,
        preview_path: str | None,
        Sdf,
    ) -> _StreamlinesOperatorExecution:
        """Run one clean operator lifetime and optionally author a preview.

        The disposable operator is removed after its receipt and UsdRT readback
        so cache generation never retains live Kit-CAE work between samples.
        """

        prepared = None
        execution = None
        cleanup_success = False
        try:
            prepared = await self._prepare_streamlines_operator_in_kit(
                stage,
                app=app,
                request=request,
                descriptor=descriptor,
                dataset_prim=dataset_prim,
                cae_usd_utils=cae_usd_utils,
                cae_viz=cae_viz,
                UsdGeom=UsdGeom,
                execute_command=execute_command,
            )
            rebuild_ms, evidence, execution_receipt = (
                await self._execute_streamlines_operator_in_kit(
                    stage,
                    app=app,
                    request=request,
                    descriptor=descriptor,
                    field_prim=field_prim,
                    operator_api=prepared.operator_api,
                    cae_viz=cae_viz,
                    cae_vtk=cae_vtk,
                    cae_usd_utils=cae_usd_utils,
                    UsdGeom=UsdGeom,
                    UsdGeomRT=UsdGeomRT,
                    wp=wp,
                    timeline=timeline,
                )
            )
            preview_mirror_ms = None
            if preview_path is not None:
                preview_started_at = time.monotonic()
                _author_usdrt_runtime_preview(
                    stage,
                    operator_prim=prepared.operator_prim,
                    evidence=evidence,
                    preview_path=preview_path,
                    UsdGeom=UsdGeom,
                    UsdGeomRT=UsdGeomRT,
                    cae_usd_utils=cae_usd_utils,
                    Sdf=Sdf,
                )
                preview_mirror_ms = (time.monotonic() - preview_started_at) * 1000.0
            execution = _StreamlinesOperatorExecution(
                prepared=prepared,
                rebuild_ms=rebuild_ms,
                evidence=evidence,
                execution_receipt=execution_receipt,
                preview_mirror_ms=preview_mirror_ms,
            )
        finally:
            if prepared is not None:
                cleanup_success = await self._cleanup_streamlines_operator_in_kit(
                    stage,
                    app=app,
                    prepared=prepared,
                    UsdGeom=UsdGeom,
                )
            else:
                orphan = stage.GetPrimAtPath(request.operator_path)
                if orphan.IsValid():
                    UsdGeom.Imageable(orphan).CreateVisibilityAttr().Set(
                        UsdGeom.Tokens.invisible
                    )
                    await app.next_update_async()
                    stage.RemovePrim(request.operator_path)
                    await app.next_update_async()
                cleanup_success = not stage.GetPrimAtPath(
                    request.operator_path
                ).IsValid()
        if not cleanup_success:
            raise RuntimeError(
                "Streamlines did not remove its completed disposable operator."
            )
        if execution is None:
            raise RuntimeError("Streamlines operator execution produced no result.")
        return execution

    async def _execute_streamlines_operator_in_kit(
        self,
        stage,
        *,
        app,
        request: StreamlinesOperatorRequest,
        descriptor: StaticVelocitySourceDescriptor,
        field_prim,
        operator_api,
        cae_viz,
        cae_vtk,
        cae_usd_utils,
        UsdGeom,
        UsdGeomRT,
        wp,
        timeline,
    ) -> tuple[
        float,
        StreamlinesOperatorEvidence,
        StreamlinesOperatorExecutionReceipt,
    ]:
        """Require this run's own successful Kit receipt before reading UsdRT."""

        begin_before = self._kit_cae_operator_begin_count(request.operator_path)
        completion_before = self._kit_cae_operator_completion_count(
            request.operator_path
        )
        rebuild_started_at = time.monotonic()
        operator_api.CreateEnabledAttr().Set(True)
        execution_receipt = await self._await_streamlines_execution_receipt(
            app,
            request,
            begin_before=begin_before,
            completion_before=completion_before,
        )
        rebuild_ms = (time.monotonic() - rebuild_started_at) * 1000.0
        evidence = inspect_streamlines_operator(
            stage,
            request=request,
            field_prim=field_prim,
            cae_viz=cae_viz,
            cae_vtk=cae_vtk,
            cae_usd_utils=cae_usd_utils,
            UsdGeom=UsdGeom,
            UsdGeomRT=UsdGeomRT,
            wp=wp,
            timeline=timeline,
            operator_completion_count_before=completion_before,
            operator_completion_count=execution_receipt.completion_count_after,
            fresh_execution=execution_receipt.fresh_execution,
            operator_execution_success=execution_receipt.completion_success,
            source_world_bounds=descriptor.world_bounds,
        )
        validate_generated_streamlines_geometry(
            evidence.runtime_curve_count,
            evidence.runtime_point_count,
            point_positions=evidence.runtime_point_positions,
            curve_vertex_counts=evidence.runtime_curve_vertex_counts,
        )
        if not execution_receipt.accepted:
            raise RuntimeError(
                "Kit-CAE did not report a fresh successful Streamlines execution "
                f"(begin={begin_before}->{execution_receipt.begin_count_after}; "
                "end="
                f"{completion_before}->{execution_receipt.completion_count_after}; "
                f"end_begin={execution_receipt.completion_begin_count}; "
                f"success={execution_receipt.completion_success})."
            )
        if not evidence.runtime_curve_bounds_within_source:
            raise RuntimeError(
                "Generated Streamlines bounds are outside the accepted source domain."
            )
        return rebuild_ms, evidence, execution_receipt

    async def _await_streamlines_execution_receipt(
        self,
        app,
        request: StreamlinesOperatorRequest,
        *,
        begin_before: int,
        completion_before: int,
    ) -> StreamlinesOperatorExecutionReceipt:
        """Wait for the post-enable end paired with a new Kit begin generation.

        `operator_end` is asynchronous. A previous success bit cannot prove
        this execution completed, so the receipt pairs its begin and end counts.
        """

        deadline = time.monotonic() + self.STREAMLINES_OPERATOR_TIMEOUT_SECONDS
        latest = None
        while time.monotonic() < deadline:
            await app.next_update_async()
            begin_after = self._kit_cae_operator_begin_count(request.operator_path)
            completion_after = self._kit_cae_operator_completion_count(
                request.operator_path
            )
            completion_begin_count = self._kit_cae_operator_completion_begin_count_at(
                request.operator_path,
                completion_after,
            )
            receipt = StreamlinesOperatorExecutionReceipt(
                begin_count_before=begin_before,
                begin_count_after=begin_after,
                completion_count_before=completion_before,
                completion_count_after=completion_after,
                completion_begin_count=completion_begin_count,
                completion_success=self._kit_cae_operator_completion_success_at(
                    request.operator_path,
                    completion_after,
                ),
            )
            latest = receipt
            if receipt.fresh_execution:
                return receipt
        if latest is not None:
            return latest
        return StreamlinesOperatorExecutionReceipt(
            begin_count_before=begin_before,
            begin_count_after=self._kit_cae_operator_begin_count(request.operator_path),
            completion_count_before=completion_before,
            completion_count_after=self._kit_cae_operator_completion_count(
                request.operator_path
            ),
            completion_begin_count=None,
            completion_success=None,
        )

    def reset_streamlines_runtime_state(self) -> None:
        """Reset only transient Streamlines state on startup or config reload."""

        self._streamlines_static_source_descriptor = None
        self._streamlines_static_source_diagnostics_failure = None
        self._streamlines_temporal_source_descriptor = None
        self._streamlines_cache_build_active_sample_index = None
