"""Stage 09 Kit-CAE velocity sources and no-Flow Streamlines diagnostics."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, replace
from typing import Awaitable, Callable

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
from digital_twin_runtime_suite.app.streamlines.cadence import (
    CADENCE_OPERATOR_PATH,
    CADENCE_PERFORMANCE_SETTLE_SECONDS,
    CADENCE_PERFORMANCE_SNAPSHOT_COUNT,
    CADENCE_PERFORMANCE_SNAPSHOT_INTERVAL_SECONDS,
    CADENCE_RUNTIME_PREVIEW_PATH,
    CADENCE_SEED_PATH,
    CadenceBoundaryObservation,
    CadenceFeasibilityPlan,
    CadencePerformanceEvidence,
    CadenceSample,
    build_cadence_feasibility_plan,
    build_cadence_performance_evidence,
    classify_cadence_feasibility,
    median_and_max,
    recovery_time_to_baseline_seconds,
)
from digital_twin_runtime_suite.app.streamlines.comparison import (
    COMPARISON_SHARED_SEED_PATH,
    MEASURED_RUN_COUNT,
    NANOVDB_MAX_RESOLUTION,
    OPERATOR_TYPES,
    PACKAGE_C_STEADY_SNAPSHOT_COUNT,
    PACKAGE_C_STEADY_SNAPSHOT_INITIAL_DELAY_SECONDS,
    PACKAGE_C_STEADY_SNAPSHOT_INTERVAL_SECONDS,
    PACKAGE_C_TOTAL_VISIBLE_UPDATE_SETTLE_COUNT,
    WARMUP_RUN_COUNT,
    StreamlinesOperatorExecutionReceipt,
    StreamlinesOperatorTypeBenchmarkSample,
    StreamlinesOperatorTypeComparisonCase,
    StreamlinesOperatorTypeComparisonCaseResult,
    StreamlinesOperatorTypeComparisonResult,
    build_streamlines_operator_type_comparison_cases,
    build_streamlines_steady_performance_evidence,
    calculate_nanovdb_effective_grid,
    clear_streamlines_operator_type_comparison_from_stage,
    comparison_cases_share_non_type_inputs,
    format_streamlines_operator_type_comparison,
)
from digital_twin_runtime_suite.app.streamlines.diagnostics import (
    StaticStreamlinesProofEvidence,
    format_static_source_acceptance,
    format_static_streamlines_binding_evidence,
    format_static_streamlines_proof_acceptance,
    inspect_static_source_runtime,
    inspect_static_streamlines_bindings,
    inspect_static_streamlines_proof,
)
from digital_twin_runtime_suite.app.streamlines.lifecycle import (
    STATIC_VELOCITY_SOURCE_ROOT,
    StaticStreamlinesCleanupReceipt,
    format_static_lifecycle_cleanup_receipt,
    inspect_static_runtime_cleanup,
    remove_static_runtime_roots_from_layers,
)
from digital_twin_runtime_suite.app.streamlines.presentation import (
    PRESENTATION_COARSE_PERIODS_SECONDS,
    PRESENTATION_FINAL_CONFIRMATION_TICK_COUNT,
    PRESENTATION_LOOP_DURATION_SECONDS,
    PRESENTATION_OPERATOR_PATH,
    PRESENTATION_RUNTIME_PREVIEW_PATH,
    PRESENTATION_SCREENING_TICK_COUNT,
    PRESENTATION_SEED_PATH,
    PresentationCandidateAssessment,
    PresentationCandidateResult,
    PresentationResolvedSample,
    PresentationTickObservation,
    assess_presentation_candidate,
    build_presentation_tick_phases,
    presentation_tick_action,
    resolve_presentation_sample,
)
from digital_twin_runtime_suite.app.streamlines.proof import (
    STATIC_PROOF_OPERATOR_PATH,
    STATIC_PROOF_RUNTIME_PREVIEW_PATH,
    STATIC_PROOF_SEED_PATH,
    StaticStreamlinesProofRequest,
    build_static_streamlines_proof_request,
    clear_static_streamlines_proof_from_stage,
    validate_generated_streamlines_geometry,
    validate_static_streamlines_source,
)
from digital_twin_runtime_suite.app.streamlines.temporal import (
    TEMPORAL_PROBE_OPERATOR_PATH,
    TEMPORAL_PROBE_RUNTIME_PREVIEW_PATH,
    TEMPORAL_PROBE_SEED_PATH,
    StreamlinesGeometrySignature,
    TemporalProbeSample,
    TemporalVelocitySourceDescriptor,
    build_temporal_probe_samples,
    geometry_signature_from_evidence,
    geometry_signatures_match,
)

StatusCallback = Callable[[str], None]
ErrorLogger = Callable[[str], None]


@dataclass(frozen=True)
class StaticVelocityTestResult:
    """Outcome of preparing one validated static source for Streamlines."""

    success: bool
    message: str
    descriptor: StaticVelocitySourceDescriptor | None = None


@dataclass(frozen=True)
class StreamlinesOperatorProofResult:
    """Outcome of creating one Package B Streamlines operator from static data."""

    success: bool
    message: str
    evidence: StaticStreamlinesProofEvidence | None = None


@dataclass(frozen=True)
class StreamlinesOperatorTypeComparisonRunResult:
    """Outcome of the Package C standard-versus-NanoVDB diagnostic run."""

    success: bool
    message: str
    comparison: StreamlinesOperatorTypeComparisonResult | None = None


@dataclass(frozen=True)
class StaticStreamlinesLifecycleResult:
    """Outcome of a Package D static-path lifecycle acceptance procedure."""

    success: bool
    message: str
    pre_restart_ready: bool = False


@dataclass(frozen=True)
class StreamlinesTemporalProbeResult:
    """Outcome of one Package E manifest-driven temporal Streamlines probe."""

    success: bool
    message: str
    source: TemporalVelocitySourceDescriptor | None = None


@dataclass(frozen=True)
class StreamlinesCadenceFeasibilityResult:
    """Outcome of one Package F measurement, independent of its A/B/C result."""

    success: bool
    message: str
    classification: str | None = None


@dataclass(frozen=True)
class StreamlinesPresentationCadenceResult:
    """Outcome of Package G's time-based presentation-cadence decision."""

    decision: str
    message: str
    presentation_period_seconds: float | None = None

    @property
    def viable(self) -> bool:
        """Return whether Package G proved a cadence that may close Phase 2."""

        return self.decision == "TIME_BASED_PRESENTATION_VIABLE"


@dataclass(frozen=True)
class StreamlinesLifecycleWorkflowState:
    """The two Package D actions available at one lifecycle review step."""

    lifecycle_acceptance_enabled: bool
    post_restart_check_enabled: bool


@dataclass(frozen=True)
class StreamlinesReviewWorkflowState:
    """The deliberately linear Package C controls available at one review step."""

    static_test_enabled: bool
    benchmark_enabled: bool
    show_standard_enabled: bool
    show_nanovdb_enabled: bool


_STREAMLINES_REVIEW_WORKFLOW_STATES = {
    "STARTUP": StreamlinesReviewWorkflowState(True, False, False, False),
    "STATIC_TEST_RUNNING": StreamlinesReviewWorkflowState(False, False, False, False),
    "STATIC_PASS": StreamlinesReviewWorkflowState(True, True, False, False),
    "BENCHMARK_RUNNING": StreamlinesReviewWorkflowState(False, False, False, False),
    "BENCHMARK_PASS": StreamlinesReviewWorkflowState(True, True, True, False),
    "STANDARD_ACTIVE": StreamlinesReviewWorkflowState(True, True, True, True),
    "NANOVDB_ACTIVE": StreamlinesReviewWorkflowState(True, True, True, True),
}

_STREAMLINES_LIFECYCLE_WORKFLOW_STATES = {
    "STARTUP": StreamlinesLifecycleWorkflowState(True, False),
    "RUNNING": StreamlinesLifecycleWorkflowState(False, False),
    "PRE_RESTART_PASS": StreamlinesLifecycleWorkflowState(True, True),
    "POST_RESTART_RUNNING": StreamlinesLifecycleWorkflowState(False, False),
    "POST_RESTART_PASS": StreamlinesLifecycleWorkflowState(True, True),
}


def streamlines_review_workflow_state(
    step: str,
) -> StreamlinesReviewWorkflowState:
    """Return the four-button state that prevents an out-of-order human review."""

    try:
        return _STREAMLINES_REVIEW_WORKFLOW_STATES[step]
    except KeyError as error:
        raise ValueError(
            f"Unsupported Streamlines review workflow step: {step}."
        ) from error


def streamlines_lifecycle_workflow_state(
    step: str,
) -> StreamlinesLifecycleWorkflowState:
    """Return Package D's two-button state without exposing obsolete A-C controls."""

    try:
        return _STREAMLINES_LIFECYCLE_WORKFLOW_STATES[step]
    except KeyError as error:
        raise ValueError(
            f"Unsupported Streamlines lifecycle workflow step: {step}."
        ) from error


def format_streamlines_visual_review(
    comparison: StreamlinesOperatorTypeComparisonResult,
    operator_type: str,
) -> str:
    """Format one human-review event from the already accepted Package C evidence."""

    case_result = getattr(comparison, operator_type)
    sample = case_result.final_sample
    lines = [
        "DTRS STREAMLINES | VISUAL_REVIEW | " f"{operator_type.upper()} | ACTIVE",
        f"preview_path={case_result.preview_path}",
        f"curves={sample.runtime_curve_count if sample else 'NOT_AVAILABLE'}",
        f"points={sample.runtime_point_count if sample else 'NOT_AVAILABLE'}",
        f"bounds={sample.runtime_bounds if sample else 'NOT_AVAILABLE'}",
    ]
    if operator_type == "standard":
        lines.append('NEXT_ACTION | Inspect viewport, then press "Show NanoVDB"')
    else:
        lines.append(
            "VISUAL_REVIEW | COMPLETE | No further application action is required."
        )
    return "\n".join(lines)


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
class _PackageCPreparedOperator:
    """One clean Kit-CAE operator prepared for exactly one benchmark execution."""

    creation_duration_ms: float
    operator_prim: object
    operator_api: object
    binding_evidence: object
    integration_settings: tuple[tuple[str, str], ...]
    source_processing_mode: str
    voxelization_settings: tuple[tuple[str, str], ...]
    nanovdb_effective_grid: object | None


@dataclass(frozen=True)
class _PackageCOperatorExecution:
    """One completed disposable operator and its optional FSD-safe mirror."""

    prepared: _PackageCPreparedOperator
    rebuild_ms: float
    evidence: StaticStreamlinesProofEvidence
    execution_receipt: StreamlinesOperatorExecutionReceipt
    preview_mirror_ms: float | None


def _author_usdrt_runtime_preview(
    stage,
    *,
    operator_prim,
    evidence: StaticStreamlinesProofEvidence,
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


def _author_static_streamlines_runtime_preview(
    stage,
    *,
    operator_prim,
    evidence: StaticStreamlinesProofEvidence,
    UsdGeom,
    UsdGeomRT,
    cae_usd_utils,
    Sdf,
) -> StaticStreamlinesProofEvidence:
    """Keep the Package B evidence contract while delegating its FSD-safe copy."""

    mirror = _author_usdrt_runtime_preview(
        stage,
        operator_prim=operator_prim,
        evidence=evidence,
        preview_path=STATIC_PROOF_RUNTIME_PREVIEW_PATH,
        UsdGeom=UsdGeom,
        UsdGeomRT=UsdGeomRT,
        cae_usd_utils=cae_usd_utils,
        Sdf=Sdf,
    )
    return replace(
        evidence,
        authored_usd_fallback_visibility=mirror.authored_fallback_visibility,
        runtime_usdrt_visibility=mirror.runtime_visibility,
        viewport_preview_path=mirror.path,
        viewport_preview_curve_count=mirror.curve_count,
        viewport_preview_point_count=mirror.point_count,
        viewport_preview_matches_runtime=mirror.matches_runtime,
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
) -> StaticVelocityTestResult:
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
    return StaticVelocityTestResult(False, message)


def report_streamlines_static_test_task_failure(
    error: Exception,
    *,
    status_callback: StatusCallback,
    error_logger: ErrorLogger,
) -> StaticVelocityTestResult:
    """Preserve the Stage 09 Package A UI-failure wording as a stable contract."""

    return report_streamlines_task_failure(
        error,
        area="STATIC_SOURCE",
        display_name="Streamlines static source",
        status_callback=status_callback,
        error_logger=error_logger,
    )


class StreamlinesRuntimeMixin:
    """Own no-Flow static and temporal Streamlines diagnostic state.

    ``RuntimeController`` supplies workload resolution and the accepted Stage 6
    imported-field/origin validators.  The mixin owns the reusable
    ``/DTRS_HoudiniVelocity`` source and short-lived diagnostic consumers; it
    never authors a Flow consumer, emitter, injector, or playback loop.
    """

    STATIC_IMPORT_ROOT = STATIC_VELOCITY_SOURCE_ROOT
    STATIC_DATASET_PATH = f"{STATIC_IMPORT_ROOT}/VTKImageData"
    STATIC_OPERATOR_PROOF_TIMEOUT_SECONDS = 15.0

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
    ) -> StaticStreamlinesCleanupReceipt:
        """Synchronously remove every DTRS-owned Package A-C artifact.

        This is the single teardown seam used by retries, lifecycle acceptance,
        reload, and extension shutdown.  It intentionally owns only the static
        Streamlines path; Flow runtime ownership remains untouched.
        """

        self._stop_kit_cae_operator_tracking()
        self._streamlines_static_source_descriptor = None
        self._streamlines_static_source_diagnostics_failure = None
        self._streamlines_operator_type_comparison = None
        self._streamlines_temporal_source_descriptor = None
        self._streamlines_temporal_probe_active_sample_index = None
        self._streamlines_temporal_probe_active_stage = None
        self._streamlines_cadence_active_sample_index = None
        self._streamlines_cadence_active_stage = None
        pending_tasks = self._streamlines_pending_runtime_task_count()
        try:
            import omni.usd
        except ImportError:
            return self._empty_static_cleanup_receipt(pending_tasks)

        stage = omni.usd.get_context().get_stage()
        if not stage:
            return self._empty_static_cleanup_receipt(pending_tasks)

        # Keep the original Package A-C cleanup seams active: they encode the
        # importer/session-layer behavior already accepted in earlier packages.
        clear_static_velocity_source_from_stage(stage, self.STATIC_IMPORT_ROOT)
        clear_static_streamlines_proof_from_stage(stage)
        clear_streamlines_operator_type_comparison_from_stage(stage)
        # The generic sweep additionally rejects accidental ``_001`` siblings.
        remove_static_runtime_roots_from_layers(stage)
        return inspect_static_runtime_cleanup(stage, pending_tasks=pending_tasks)

    async def clear_streamlines_static_runtime_in_kit(
        self,
    ) -> StaticStreamlinesCleanupReceipt:
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
        return inspect_static_runtime_cleanup(
            stage,
            pending_tasks=self._streamlines_pending_runtime_task_count(),
        )

    async def run_streamlines_static_lifecycle_acceptance_in_kit(
        self,
        *,
        reload_config_callback: Callable[[], bool],
        stage_reopen_callback: Callable[[], Awaitable[bool]],
        status_callback: StatusCallback | None = None,
    ) -> StaticStreamlinesLifecycleResult:
        """Run Package D's complete in-process static lifecycle matrix.

        Reload and stage-open stay extension-owned because they rebuild the UI
        shell as well as Kit state.  All DTRS static source creation, rollback,
        and cleanup stay in this runtime owner.
        """

        started_at = time.monotonic()
        carb = self._streamlines_carb_logger()
        failed_step = "CLEAN_BASELINE"

        def log(message: str, *, error: bool = False) -> None:
            if not carb:
                return
            logger = carb.log_error if error else carb.log_warn
            logger(with_dtrs_yerevan_timestamp(message))

        def publish(message: str) -> None:
            if status_callback:
                status_callback(message)

        async def clean_step(step: int, name: str) -> StaticStreamlinesCleanupReceipt:
            receipt = await self.clear_streamlines_static_runtime_in_kit()
            state = "PASS" if receipt.clean else "FAIL"
            log(
                f"DTRS STREAMLINES | STATIC_LIFECYCLE | STEP {step}/8 | "
                f"{name} | {state}\n{format_static_lifecycle_cleanup_receipt(receipt)}",
                error=not receipt.clean,
            )
            if not receipt.clean:
                raise RuntimeError(f"Cleanup receipt is DIRTY after {name}.")
            return receipt

        async def run_then_clean(step: int, name: str) -> None:
            result = await self.run_streamlines_static_test_in_kit(
                status_callback=status_callback,
            )
            if (
                not result.success
                or self.streamlines_static_source_diagnostics_failure()
            ):
                raise RuntimeError(result.message)
            await clean_step(step, name)

        try:
            publish("Static lifecycle acceptance: clean baseline")
            await clean_step(1, "CLEAN_BASELINE")

            failed_step = "RUN_1_CLEANUP"
            publish("Static lifecycle acceptance: repeatable run 1 of 2")
            await run_then_clean(2, "RUN_1_CLEANUP")

            failed_step = "RUN_2_CLEANUP"
            publish("Static lifecycle acceptance: repeatable run 2 of 2")
            await run_then_clean(3, "RUN_2_CLEANUP")

            failed_step = "FORCED_FAILURE_ROLLBACK"
            publish("Static lifecycle acceptance: forced rollback")
            forced = await self.run_streamlines_static_test_in_kit(
                status_callback=status_callback,
                force_failure_after_import=True,
            )
            if (
                forced.success
                or "Package D forced static-source failure" not in forced.message
            ):
                raise RuntimeError(
                    "Deterministic forced failure did not reach the rollback path."
                )
            await clean_step(4, "FORCED_FAILURE_ROLLBACK")

            failed_step = "RECOVERY_RUN_CLEANUP"
            publish("Static lifecycle acceptance: recovery run")
            await run_then_clean(5, "RECOVERY_RUN_CLEANUP")

            failed_step = "RELOAD_CONFIG"
            publish("Static lifecycle acceptance: reload config")
            if not reload_config_callback():
                raise RuntimeError("Reload Config callback failed.")
            await clean_step(6, "RELOAD_CONFIG_CLEAN")
            await run_then_clean(6, "RELOAD_CONFIG_RUN_CLEANUP")

            failed_step = "STAGE_REOPEN"
            publish("Static lifecycle acceptance: reopen stage")
            if not await stage_reopen_callback():
                raise RuntimeError("Stage reopen callback failed.")
            await clean_step(7, "STAGE_REOPEN_CLEAN")
            await run_then_clean(7, "STAGE_REOPEN_RUN_CLEANUP")

            failed_step = "PRE_SHUTDOWN"
            publish("Static lifecycle acceptance: pre-shutdown cleanup")
            await clean_step(8, "PRE_SHUTDOWN")
        except asyncio.CancelledError:
            raise
        except Exception:
            message = (
                "DTRS STREAMLINES | STATIC_LIFECYCLE | FAIL\n"
                f"failed_step={failed_step}\n"
                "NEXT_ACTION | Stop. Do not restart or continue; inspect this failure."
            )
            log(message, error=True)
            publish(message)
            return StaticStreamlinesLifecycleResult(False, message)

        message = (
            "DTRS STREAMLINES | STATIC_LIFECYCLE | PRE_RESTART_PASS\n\n"
            "In-process lifecycle acceptance complete.\n"
            "NEXT_ACTION | Close DTRS completely, start it again, then press "
            '"Run Post-Restart Check".'
        )
        log(f"{message}\n" f"total_ms={(time.monotonic() - started_at) * 1000.0:.0f}")
        publish(message)
        return StaticStreamlinesLifecycleResult(True, message, pre_restart_ready=True)

    async def run_streamlines_post_restart_check_in_kit(
        self,
        *,
        status_callback: StatusCallback | None = None,
    ) -> StaticStreamlinesLifecycleResult:
        """Verify a fresh DTRS process starts clean and remains cleanup-idempotent."""

        carb = self._streamlines_carb_logger()
        failed_step = "CLEAN_STARTUP_BASELINE"

        def log(message: str, *, error: bool = False) -> None:
            if carb:
                (carb.log_error if error else carb.log_warn)(
                    with_dtrs_yerevan_timestamp(message)
                )

        def publish(message: str) -> None:
            if status_callback:
                status_callback(message)

        async def clean(name: str) -> None:
            receipt = await self.clear_streamlines_static_runtime_in_kit()
            state = "PASS" if receipt.clean else "FAIL"
            log(
                f"DTRS STREAMLINES | STATIC_LIFECYCLE | POST_RESTART | "
                f"{name} | {state}\n{format_static_lifecycle_cleanup_receipt(receipt)}",
                error=not receipt.clean,
            )
            if not receipt.clean:
                raise RuntimeError(f"Cleanup receipt is DIRTY after {name}.")

        try:
            publish("Post-restart check: clean startup baseline")
            await clean("CLEAN_STARTUP_BASELINE")
            failed_step = "RUN_AFTER_RESTART"
            result = await self.run_streamlines_static_test_in_kit(
                status_callback=status_callback,
            )
            if (
                not result.success
                or self.streamlines_static_source_diagnostics_failure()
            ):
                raise RuntimeError(result.message)
            failed_step = "CLEAN_AFTER_RESTART_RUN"
            await clean("CLEAN_AFTER_RESTART_RUN")
            failed_step = "IDEMPOTENT_SECOND_CLEANUP"
            await clean("IDEMPOTENT_SECOND_CLEANUP")
        except asyncio.CancelledError:
            raise
        except Exception:
            message = (
                "DTRS STREAMLINES | STATIC_LIFECYCLE | FAIL\n"
                f"failed_step={failed_step}\n"
                "NEXT_ACTION | Stop. Do not restart or continue; inspect this failure."
            )
            log(message, error=True)
            publish(message)
            return StaticStreamlinesLifecycleResult(False, message)

        message = (
            "DTRS STREAMLINES | STATIC_LIFECYCLE | POST_RESTART_PASS\n\n"
            "Phase 1 static lifecycle acceptance complete.\n"
            "No further manual action required.\n"
            "result=PASS"
        )
        log(message)
        publish(message)
        return StaticStreamlinesLifecycleResult(True, message)

    def _streamlines_pending_runtime_task_count(self) -> int:
        """Count DTRS-owned CAE subscriptions or active operators after teardown."""

        return len(self._flow_kit_cae_operator_subscriptions) + len(
            self._flow_kit_cae_active_operator_paths
        )

    @staticmethod
    def _empty_static_cleanup_receipt(
        pending_tasks: int,
    ) -> StaticStreamlinesCleanupReceipt:
        """Treat a no-stage shutdown as clean after observer ownership is released."""

        return StaticStreamlinesCleanupReceipt(
            source_present=False,
            operator_present=False,
            seed_present=False,
            runtime_preview_present=False,
            comparison_present=False,
            stale_relationships=0,
            remaining_layer_specs=0,
            duplicate_prims=0,
            pending_tasks=pending_tasks,
        )

    @staticmethod
    def _streamlines_carb_logger():
        """Return Kit logging when available without making diagnostics a dependency."""

        try:
            import carb
        except ImportError:
            return None
        return carb

    async def run_streamlines_static_test_in_kit(
        self,
        status_callback: StatusCallback | None = None,
        *,
        force_failure_after_import: bool = False,
    ) -> StaticVelocityTestResult:
        """Prepare sample zero only when the full airflow runtime is detached.

        ``force_failure_after_import`` exists solely for Package D's rollback
        proof.  It deliberately fails after the real VTI/spatial work has
        completed, so production callers always retain the default ``False``.
        """

        if self._flow_lifecycle_state != "DETACHED":
            return StaticVelocityTestResult(
                False,
                "Run Static Test is unavailable while airflow Attach is active.",
            )
        started_at = time.monotonic()
        carb = None
        self._streamlines_operator_type_comparison = None
        try:
            try:
                import carb as carb_module
            except ImportError:
                carb_module = None
            carb = carb_module
            if carb:
                carb.log_warn(
                    with_dtrs_yerevan_timestamp(
                        "DTRS STREAMLINES | STATIC_SOURCE | BEGIN"
                    )
                )
            if force_failure_after_import:
                descriptor = await self.prepare_static_velocity_sample_in_kit(
                    sample_index=0,
                    status_callback=status_callback,
                    force_failure_after_import=True,
                )
            else:
                descriptor = await self.prepare_static_velocity_sample_in_kit(
                    sample_index=0,
                    status_callback=status_callback,
                )
        except Exception as error:
            self._streamlines_static_source_descriptor = None
            rollback = await self.clear_streamlines_static_runtime_in_kit()
            message = (
                f"Streamlines static source failed: {error}; "
                f"rollback={'CLEAN' if rollback.clean else 'DIRTY'}"
            )
            if carb:
                carb.log_error(
                    with_dtrs_yerevan_timestamp(
                        "DTRS STREAMLINES | STATIC_SOURCE | FAIL | "
                        f"total_ms={(time.monotonic() - started_at) * 1000.0:.0f} | "
                        f"reason={error}"
                    )
                )
            return StaticVelocityTestResult(False, message)
        diagnostics_failure = self.streamlines_static_source_diagnostics_failure()
        if carb:
            carb.log_warn(
                with_dtrs_yerevan_timestamp(
                    "DTRS STREAMLINES | STATIC_SOURCE | PASS | "
                    f"total_ms={(time.monotonic() - started_at) * 1000.0:.0f}"
                )
            )
        message = (
            "Static source ready, but runtime diagnostics failed: "
            f"{diagnostics_failure}"
            if diagnostics_failure
            else "Static source ready."
        )
        return StaticVelocityTestResult(
            True,
            message,
            descriptor,
        )

    def announce_streamlines_temporal_probe_ready(self) -> str:
        """Publish the single Package E action without creating Kit state."""

        message = (
            "DTRS STREAMLINES | TEMPORAL_PROBE | READY\n"
            'NEXT_ACTION | Press "Run Temporal Probe"'
        )
        carb = self._streamlines_carb_logger()
        if carb:
            carb.log_warn(with_dtrs_yerevan_timestamp(message))
        return 'Ready — Press "Run Temporal Probe".'

    def announce_streamlines_cadence_feasibility_ready(self) -> str:
        """Publish Package F's one-action workflow without authoring Kit state."""

        message = (
            "DTRS STREAMLINES | CADENCE_FEASIBILITY | READY\n"
            'NEXT_ACTION | Press "Run Cadence Feasibility Test"'
        )
        carb = self._streamlines_carb_logger()
        if carb:
            carb.log_warn(with_dtrs_yerevan_timestamp(message))
        return 'Ready — Press "Run Cadence Feasibility Test".'

    def announce_streamlines_presentation_cadence_ready(self) -> str:
        """Publish Package G's one-action workflow without authoring Kit state."""

        message = (
            "DTRS STREAMLINES | PRESENTATION_CADENCE | READY\n"
            'NEXT_ACTION | Press "Run Presentation Cadence Test"'
        )
        carb = self._streamlines_carb_logger()
        if carb:
            carb.log_warn(with_dtrs_yerevan_timestamp(message))
        return 'Ready — Press "Run Presentation Cadence Test".'

    async def run_streamlines_presentation_cadence_in_kit(
        self,
        status_callback: StatusCallback | None = None,
    ) -> StreamlinesPresentationCadenceResult:
        """Select the fastest stable time-based presentation period on real Kit state.

        Package G schedules presentation ticks against a fixed 16-second loop,
        while the manifest remains the sole owner of source sample cadence.
        It deliberately measures the frozen Package E/F rebuild path; no
        cadence optimisation, source interpolation, or Stage 8 change occurs.
        """

        if self._flow_lifecycle_state != "DETACHED":
            return StreamlinesPresentationCadenceResult(
                "FAIL",
                "Presentation Cadence is unavailable while airflow Attach is active.",
            )

        started_at = time.monotonic()
        carb = self._streamlines_carb_logger()
        source = None
        cleanup = None
        self._streamlines_presentation_cadence_active_stage = "PREPARE"
        self._streamlines_presentation_cadence_active_sample_index = None
        try:
            if carb:
                carb.log_warn(
                    with_dtrs_yerevan_timestamp(
                        "DTRS STREAMLINES | PRESENTATION_CADENCE | BEGIN"
                    )
                )
            baseline_cleanup = await self.clear_streamlines_static_runtime_in_kit()
            if not baseline_cleanup.clean:
                raise RuntimeError(
                    "Package D canonical cleanup was not clean at "
                    "presentation-test start."
                )
            source = await self.prepare_streamlines_temporal_velocity_source_in_kit(
                status_callback=status_callback,
            )
            measurement = await self._measure_streamlines_presentation_cadence_in_kit(
                source,
                status_callback=status_callback,
            )
            self._streamlines_presentation_cadence_active_stage = "CLEANUP"
            cleanup = await self.clear_streamlines_static_runtime_in_kit()
            if not cleanup.clean:
                raise RuntimeError(
                    "Package D cleanup was not clean after presentation test."
                )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            cleanup = await self.clear_streamlines_static_runtime_in_kit()
            message = self._format_presentation_cadence_failure(
                failed_stage=self._streamlines_presentation_cadence_active_stage
                or "PREPARE",
                error=error,
                cleanup=cleanup,
                total_ms=(time.monotonic() - started_at) * 1000.0,
            )
            if carb:
                carb.log_error(with_dtrs_yerevan_timestamp(message))
            if status_callback:
                status_callback(
                    "Presentation Cadence TEST COMPLETE — FAIL; inspect the log."
                )
            return StreamlinesPresentationCadenceResult("FAIL", message)

        decision = measurement["decision"]
        if not isinstance(decision, str):
            raise RuntimeError("Presentation cadence measurement has no decision.")
        message = self._format_presentation_cadence_terminal(
            source=source,
            measurement=measurement,
            cleanup=cleanup,
            total_ms=(time.monotonic() - started_at) * 1000.0,
        )
        if carb:
            carb.log_warn(with_dtrs_yerevan_timestamp(message))
        viable = decision == "TIME_BASED_PRESENTATION_VIABLE"
        if status_callback:
            status_callback(
                "Presentation Cadence TEST COMPLETE — VIABLE; "
                "no further manual action required."
                if viable
                else "Presentation Cadence TEST COMPLETE — REASSESS; inspect the log."
            )
        return StreamlinesPresentationCadenceResult(
            decision,
            message,
            presentation_period_seconds=measurement.get("selected_period_seconds"),
        )

    async def run_streamlines_temporal_probe_in_kit(
        self,
        status_callback: StatusCallback | None = None,
    ) -> StreamlinesTemporalProbeResult:
        """Exercise selected manifest samples through one no-Flow temporal field.

        Package E deliberately proves discrete source selection only.  It does
        not claim 5 Hz feasibility, modify Stage 8 workload ownership, or turn
        this diagnostic seam into a production visualization mode.
        """

        if self._flow_lifecycle_state != "DETACHED":
            return StreamlinesTemporalProbeResult(
                False,
                "Temporal Probe is unavailable while airflow Attach is active.",
            )

        started_at = time.monotonic()
        carb = self._streamlines_carb_logger()
        source = None
        records = []
        cleanup = None
        failed_sample_index = None
        failed_stage = "PREPARE"
        try:
            if carb:
                carb.log_warn(
                    with_dtrs_yerevan_timestamp(
                        "DTRS STREAMLINES | TEMPORAL_PROBE | BEGIN"
                    )
                )
            if status_callback:
                status_callback("Preparing manifest-backed temporal source…")
            baseline = await self.clear_streamlines_static_runtime_in_kit()
            if not baseline.clean:
                raise RuntimeError(
                    "Package D canonical cleanup was not clean at probe start."
                )

            source = await self.prepare_streamlines_temporal_velocity_source_in_kit(
                status_callback=status_callback,
            )
            probe_samples = build_temporal_probe_samples(source)
            if carb:
                carb.log_warn(
                    with_dtrs_yerevan_timestamp(
                        self._format_temporal_probe_sequence(source, probe_samples)
                    )
                )
            records = await self._run_temporal_probe_samples_in_kit(
                source,
                probe_samples,
                status_callback=status_callback,
            )
            failed_stage = "VALIDATING_RESULTS"
            self._streamlines_temporal_probe_active_stage = failed_stage
            self._validate_temporal_probe_records(source, records)
            failed_stage = "CLEANUP"
            self._streamlines_temporal_probe_active_stage = failed_stage
            cleanup = await self.clear_streamlines_static_runtime_in_kit()
            if not cleanup.clean:
                raise RuntimeError(
                    "Package D cleanup was not clean after temporal probe."
                )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            failed_sample_index = self._streamlines_temporal_probe_active_sample_index
            failed_stage = self._streamlines_temporal_probe_active_stage or failed_stage
            failed_sample_text = (
                failed_sample_index if failed_sample_index is not None else "PREPARE"
            )
            cleanup = await self.clear_streamlines_static_runtime_in_kit()
            message = (
                "========================================\n"
                "DTRS STREAMLINES | TEMPORAL_PROBE | TEST COMPLETE | FAIL\n"
                "========================================\n"
                "failed_sample_index="
                f"{failed_sample_text}\n"
                f"failed_stage={failed_stage}\n"
                f"reason={error}\n"
                f"rollback={'CLEAN' if cleanup.clean else 'DIRTY'}\n"
                "NEXT_ACTION | Stop. Package E is incomplete; inspect this failure."
            )
            if carb:
                carb.log_error(
                    with_dtrs_yerevan_timestamp(
                        f"{message}\ntotal_ms="
                        f"{(time.monotonic() - started_at) * 1000.0:.0f}"
                    )
                )
            if status_callback:
                status_callback("Temporal Probe failed; inspect the structured log.")
            return StreamlinesTemporalProbeResult(False, message, source)

        message = self._format_temporal_probe_success(source, records, cleanup)
        if carb:
            carb.log_warn(
                with_dtrs_yerevan_timestamp(
                    f"{message}\ntotal_ms="
                    f"{(time.monotonic() - started_at) * 1000.0:.0f}"
                )
            )
        if status_callback:
            status_callback(
                "Temporal Probe complete — no further manual action required."
            )
        return StreamlinesTemporalProbeResult(True, message, source)

    async def run_streamlines_cadence_feasibility_in_kit(
        self,
        status_callback: StatusCallback | None = None,
    ) -> StreamlinesCadenceFeasibilityResult:
        """Measure the frozen Package E path without optimizing its cadence.

        The test deliberately queues real 5 Hz source requests while one
        standard Streamlines consumer rebuilds serially.  It reports whether
        the existing path keeps up; it never drops a request, changes a VTI,
        or introduces an every-N presentation policy.
        """

        if self._flow_lifecycle_state != "DETACHED":
            return StreamlinesCadenceFeasibilityResult(
                False,
                "Cadence Feasibility is unavailable while airflow Attach is active.",
            )

        started_at = time.monotonic()
        carb = self._streamlines_carb_logger()
        source = None
        cleanup = None
        self._streamlines_cadence_active_stage = "PREPARE"
        self._streamlines_cadence_active_sample_index = None
        try:
            if carb:
                carb.log_warn(
                    with_dtrs_yerevan_timestamp(
                        "DTRS STREAMLINES | CADENCE_FEASIBILITY | BEGIN"
                    )
                )
            self._publish_cadence_stage(
                1,
                "BASELINE",
                "RUNNING",
                status_callback=status_callback,
            )
            baseline_cleanup = await self.clear_streamlines_static_runtime_in_kit()
            if not baseline_cleanup.clean:
                raise RuntimeError(
                    "Package D canonical cleanup was not clean at cadence-test start."
                )
            source = await self.prepare_streamlines_temporal_velocity_source_in_kit(
                status_callback=status_callback,
            )
            plan = build_cadence_feasibility_plan(source)
            measurement = await self._measure_streamlines_cadence_in_kit(
                source,
                plan,
                status_callback=status_callback,
            )
            classification = classify_cadence_feasibility(
                source_period_ms=plan.source_period_ms,
                burst_records=measurement["burst_records"],
                requested_samples=len(plan.burst_samples),
            )
            self._streamlines_cadence_active_stage = "CLEANUP"
            cleanup = await self.clear_streamlines_static_runtime_in_kit()
            if not cleanup.clean:
                raise RuntimeError(
                    "Package D cleanup was not clean after cadence test."
                )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            cleanup = await self.clear_streamlines_static_runtime_in_kit()
            message = self._format_cadence_feasibility_failure(
                failed_stage=self._streamlines_cadence_active_stage or "PREPARE",
                error=error,
                cleanup=cleanup,
                total_ms=(time.monotonic() - started_at) * 1000.0,
            )
            if carb:
                carb.log_error(with_dtrs_yerevan_timestamp(message))
            if status_callback:
                status_callback(
                    "Cadence Feasibility TEST COMPLETE — FAIL; inspect the log."
                )
            return StreamlinesCadenceFeasibilityResult(False, message)

        message = self._format_cadence_feasibility_success(
            source=source,
            plan=plan,
            measurement=measurement,
            classification=classification,
            cleanup=cleanup,
            total_ms=(time.monotonic() - started_at) * 1000.0,
        )
        if carb:
            carb.log_warn(with_dtrs_yerevan_timestamp(message))
        if status_callback:
            status_callback(
                "Cadence Feasibility TEST COMPLETE — PASS; "
                "no further manual action required."
            )
        return StreamlinesCadenceFeasibilityResult(
            True,
            message,
            classification=classification.value,
        )

    async def prepare_streamlines_temporal_velocity_source_in_kit(
        self,
        *,
        status_callback: StatusCallback | None = None,
    ) -> TemporalVelocitySourceDescriptor:
        """Author the Stage 6 ``vel.fileNames`` time-sample source for Streamlines.

        The first VTI is imported once through the Package A spatial seam.  All
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
            time_codes = (
                await flow_temporal.author_kit_cae_temporal_velocity_samples_in_batches(
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
            len(flow_temporal.kit_cae_file_names_time_samples(field_prim, cae_vtk, Usd))
            != source.sample_count
        ):
            raise RuntimeError(
                "Temporal Streamlines field did not retain every manifest time sample."
            )
        self._streamlines_temporal_source_descriptor = source
        return source

    async def _measure_streamlines_cadence_in_kit(
        self,
        source: TemporalVelocitySourceDescriptor,
        plan: CadenceFeasibilityPlan,
        *,
        status_callback: StatusCallback | None,
    ) -> dict[str, object]:
        """Run Package F's serial consumer under measured source-request pressure.

        The producer used by the burst queues manifest requests at their real
        source period.  The sole consumer remains intentionally serial because
        this package measures the accepted Package E rebuild boundary rather
        than concealing it with concurrent Kit-CAE operators.
        """

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

        if carb.settings.get_settings().get_as_bool("/app/useFabricSceneDelegate"):
            raise RuntimeError(
                "Cadence Feasibility requires FSD=false for the accepted X-Ray "
                "baseline."
            )
        app = omni.kit.app.get_app()
        stage = omni.usd.get_context().get_stage()
        if not stage:
            raise RuntimeError("Cadence Feasibility requires an open stage.")
        descriptor = source.static_descriptor
        dataset_prim = stage.GetPrimAtPath(descriptor.dataset_prim_path)
        field_prim = stage.GetPrimAtPath(descriptor.velocity_field_prim_path)
        if not dataset_prim or not dataset_prim.IsValid():
            raise RuntimeError("Cadence Feasibility dataset prim is unavailable.")
        if not field_prim or not field_prim.IsValid():
            raise RuntimeError("Cadence Feasibility velocity field is unavailable.")

        request = replace(
            build_static_streamlines_proof_request(descriptor),
            operator_path=CADENCE_OPERATOR_PATH,
            seed_path=CADENCE_SEED_PATH,
            operator_type="standard",
        )
        previous_target = stage.GetEditTarget()
        prepared = None
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

            async def consume_boundary(
                sample: CadenceSample,
                *,
                scenario: str,
                requested_at_seconds: float | None = None,
                scheduled_at_seconds: float | None = None,
                queue_depth_at_request: int | None = None,
                queue_depth_at_start: int | None = None,
            ) -> CadenceBoundaryObservation:
                """Consume one queued real sample through the frozen Package E seam."""

                nonlocal prepared
                self._streamlines_cadence_active_sample_index = sample.sample_index
                requested_at = (
                    time.monotonic()
                    if requested_at_seconds is None
                    else requested_at_seconds
                )
                processing_started_at = time.monotonic()
                if prepared is not None:
                    # Keep the last accepted preview visible while its Kit owner
                    # is retired.  The next preview replaces it only after a
                    # new UsdRT result is confirmed.
                    prepared.operator_api.CreateEnabledAttr().Set(False)

                source_started_at = time.monotonic()
                await self._select_temporal_probe_source_in_kit(
                    app,
                    timeline=timeline,
                    field_prim=field_prim,
                    sample=sample,
                    cae_vtk=cae_vtk,
                    Usd=Usd,
                )
                source_transition_ms = (time.monotonic() - source_started_at) * 1000.0

                operator_rebuild_started_at = time.monotonic()
                if prepared is not None:
                    cleaned = await self._cleanup_package_c_operator_in_kit(
                        stage,
                        app=app,
                        prepared=prepared,
                        UsdGeom=UsdGeom,
                    )
                    if not cleaned:
                        raise RuntimeError(
                            "Previous cadence Streamlines operator did not cleanly "
                            "rebuild."
                        )
                prepared = await self._prepare_package_c_operator_in_kit(
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
                if prepared.source_processing_mode != "subset":
                    raise RuntimeError(
                        "Cadence Feasibility must use the selected standard operator "
                        "path."
                    )
                await app.next_update_async()
                begin_before = self._kit_cae_operator_begin_count(request.operator_path)
                completion_before = self._kit_cae_operator_completion_count(
                    request.operator_path
                )
                prepared.operator_api.CreateEnabledAttr().Set(True)
                execution_receipt = await self._await_package_c_execution_receipt(
                    app,
                    request,
                    begin_before=begin_before,
                    completion_before=completion_before,
                )
                operator_rebuild_ms = (
                    time.monotonic() - operator_rebuild_started_at
                ) * 1000.0
                if not execution_receipt.accepted:
                    raise RuntimeError(
                        "Kit-CAE did not report a fresh cadence Streamlines execution "
                        f"(begin={begin_before}->"
                        f"{execution_receipt.begin_count_after}; "
                        f"end={completion_before}->"
                        f"{execution_receipt.completion_count_after}; "
                        f"success={execution_receipt.completion_success})."
                    )
                evidence = inspect_static_streamlines_proof(
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
                if not self._temporal_probe_evidence_is_valid(request, evidence):
                    raise RuntimeError(
                        "Cadence Streamlines output did not satisfy the frozen no-Flow "
                        "contract."
                    )
                usdrt_ready_ms = (time.monotonic() - requested_at) * 1000.0
                preview_started_at = time.monotonic()
                mirror = _author_usdrt_runtime_preview(
                    stage,
                    operator_prim=prepared.operator_prim,
                    evidence=evidence,
                    preview_path=CADENCE_RUNTIME_PREVIEW_PATH,
                    UsdGeom=UsdGeom,
                    UsdGeomRT=UsdGeomRT,
                    cae_usd_utils=cae_usd_utils,
                    Sdf=Sdf,
                )
                await self._await_temporal_probe_preview_quiescence(app)
                completed_visible_at = time.monotonic()
                signature = geometry_signature_from_evidence(evidence)
                record = CadenceBoundaryObservation(
                    scenario=scenario,
                    sample=sample,
                    requested_at_seconds=requested_at,
                    processing_started_at_seconds=processing_started_at,
                    completed_visible_at_seconds=completed_visible_at,
                    source_transition_ms=source_transition_ms,
                    operator_rebuild_ms=operator_rebuild_ms,
                    usdrt_ready_ms=usdrt_ready_ms,
                    preview_update_ms=(completed_visible_at - preview_started_at)
                    * 1000.0,
                    total_visible_update_ms=(completed_visible_at - requested_at)
                    * 1000.0,
                    begin_count_before=execution_receipt.begin_count_before,
                    begin_count_after=execution_receipt.begin_count_after,
                    completion_count_before=execution_receipt.completion_count_before,
                    completion_count_after=execution_receipt.completion_count_after,
                    fresh_execution=execution_receipt.fresh_execution,
                    execution_success=execution_receipt.completion_success,
                    curve_count=evidence.runtime_curve_count,
                    point_count=evidence.runtime_point_count,
                    bounds=evidence.runtime_curve_bounds,
                    geometry_replaced=execution_receipt.accepted,
                    preview_matches_runtime=mirror.matches_runtime,
                    signature=signature,
                    scheduled_at_seconds=scheduled_at_seconds,
                    queue_depth_at_request=queue_depth_at_request,
                    queue_depth_at_start=queue_depth_at_start,
                )
                carb.log_warn(
                    with_dtrs_yerevan_timestamp(
                        self._format_cadence_boundary_observation(record)
                    )
                )
                return record

            baseline_record = await consume_boundary(
                plan.initial_sample,
                scenario="baseline_initial",
            )
            baseline_performance = await self._capture_cadence_performance_evidence(
                initial_delay_seconds=CADENCE_PERFORMANCE_SETTLE_SECONDS,
            )
            self._publish_cadence_stage(
                1,
                "BASELINE",
                "PASS",
                status_callback=status_callback,
            )

            self._publish_cadence_stage(
                2,
                "SEQUENTIAL_BOUNDARIES",
                "RUNNING",
                status_callback=status_callback,
            )
            sequential_records = tuple(
                [
                    await consume_boundary(sample, scenario="sequential")
                    for sample in plan.sequential_samples
                ]
            )
            self._validate_cadence_records(sequential_records, "sequential")
            self._publish_cadence_stage(
                2,
                "SEQUENTIAL_BOUNDARIES",
                "PASS",
                status_callback=status_callback,
            )

            self._publish_cadence_stage(
                3,
                "REPEATED_SAMPLE",
                "RUNNING",
                status_callback=status_callback,
            )
            repeated_records = tuple(
                [
                    await consume_boundary(sample, scenario="repeat_sample")
                    for sample in plan.repeated_samples
                ]
            )
            self._validate_cadence_records(repeated_records, "repeat_sample")
            self._publish_cadence_stage(
                3,
                "REPEATED_SAMPLE",
                "PASS",
                status_callback=status_callback,
            )

            self._publish_cadence_stage(
                4,
                "LOOP_BOUNDARY",
                "RUNNING",
                status_callback=status_callback,
            )
            loop_records = tuple(
                [
                    await consume_boundary(sample, scenario="loop_boundary")
                    for sample in plan.loop_boundary_samples
                ]
            )
            self._validate_cadence_records(loop_records, "loop_boundary")
            returned_first = loop_records[-2]
            if not geometry_signatures_match(
                baseline_record.signature, returned_first.signature
            ):
                raise RuntimeError(
                    "Loop boundary returned first-sample geometry inconsistent with "
                    "baseline."
                )
            self._publish_cadence_stage(
                4,
                "LOOP_BOUNDARY",
                "PASS",
                status_callback=status_callback,
            )

            self._publish_cadence_stage(
                5,
                "5HZ_BURST",
                "RUNNING",
                status_callback=status_callback,
            )
            burst_records, during_performance = await self._run_cadence_burst_in_kit(
                plan,
                consume_boundary=consume_boundary,
            )
            self._validate_cadence_records(burst_records, "5hz_burst")
            self._publish_cadence_stage(
                5,
                "5HZ_BURST",
                "PASS",
                status_callback=status_callback,
            )

            self._publish_cadence_stage(
                6,
                "RECOVERY",
                "RUNNING",
                status_callback=status_callback,
            )
            recovery_started_at = time.monotonic()
            recovery_performance = await self._capture_cadence_performance_evidence(
                initial_delay_seconds=CADENCE_PERFORMANCE_SETTLE_SECONDS,
            )
            self._publish_cadence_stage(
                6,
                "RECOVERY",
                "PASS",
                status_callback=status_callback,
            )
            return {
                "baseline_record": baseline_record,
                "baseline_performance": baseline_performance,
                "sequential_records": sequential_records,
                "repeated_records": repeated_records,
                "loop_records": loop_records,
                "burst_records": burst_records,
                "during_performance": during_performance,
                "recovery_performance": recovery_performance,
                "recovery_started_at": recovery_started_at,
            }
        finally:
            if prepared is not None:
                await self._cleanup_package_c_operator_in_kit(
                    stage,
                    app=app,
                    prepared=prepared,
                    UsdGeom=UsdGeom,
                )
            self._stop_kit_cae_operator_tracking()
            stage.SetEditTarget(previous_target)

    async def _measure_streamlines_presentation_cadence_in_kit(
        self,
        source: TemporalVelocitySourceDescriptor,
        *,
        status_callback: StatusCallback | None,
    ) -> dict[str, object]:
        """Run Package G's wall-clock scheduler over the frozen Package E seam.

        The only new behaviour here is scheduling. A rebuild continues to use
        the accepted source-selection, disposable standard-operator, UsdRT,
        and RuntimePreview path from Package F. A repeated resolved sample is
        intentionally a no-op so a future lower-cadence manifest cannot cause
        redundant Kit-CAE work merely because a presentation tick occurred.
        """

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

        if carb.settings.get_settings().get_as_bool("/app/useFabricSceneDelegate"):
            raise RuntimeError(
                "Presentation Cadence requires FSD=false for the accepted X-Ray "
                "baseline."
            )
        app = omni.kit.app.get_app()
        stage = omni.usd.get_context().get_stage()
        if not stage:
            raise RuntimeError("Presentation Cadence requires an open stage.")
        descriptor = source.static_descriptor
        dataset_prim = stage.GetPrimAtPath(descriptor.dataset_prim_path)
        field_prim = stage.GetPrimAtPath(descriptor.velocity_field_prim_path)
        if not dataset_prim or not dataset_prim.IsValid():
            raise RuntimeError("Presentation Cadence dataset prim is unavailable.")
        if not field_prim or not field_prim.IsValid():
            raise RuntimeError("Presentation Cadence velocity field is unavailable.")

        request = replace(
            build_static_streamlines_proof_request(descriptor),
            operator_path=PRESENTATION_OPERATOR_PATH,
            seed_path=PRESENTATION_SEED_PATH,
            operator_type="standard",
        )
        previous_target = stage.GetEditTarget()
        prepared = None
        currently_presented_sample_index = None
        currently_selected_vti = None
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

            async def consume_tick(
                resolved: PresentationResolvedSample,
                *,
                candidate_period_seconds: float,
                tick_ordinal: int,
                scenario: str,
                scheduled_at_seconds: float | None = None,
                requested_at_seconds: float | None = None,
                pending_presentation_requests_at_request: int = 0,
                pending_presentation_requests_at_start: int = 0,
            ) -> PresentationTickObservation:
                """Present one resolved sample or preserve the existing exact result."""

                nonlocal prepared
                nonlocal currently_presented_sample_index
                nonlocal currently_selected_vti
                scheduled_at = (
                    time.monotonic()
                    if scheduled_at_seconds is None
                    else scheduled_at_seconds
                )
                requested_at = (
                    time.monotonic()
                    if requested_at_seconds is None
                    else requested_at_seconds
                )
                processing_started_at = time.monotonic()
                self._streamlines_presentation_cadence_active_sample_index = (
                    resolved.sample_index
                )
                action = presentation_tick_action(
                    resolved.sample_index,
                    currently_presented_sample_index,
                )
                if action == "NO_OP":
                    selected_matches = (
                        currently_selected_vti is not None
                        and currently_selected_vti.resolve()
                        == resolved.source_vti.resolve()
                    )
                    completed_visible_at = time.monotonic()
                    record = PresentationTickObservation(
                        candidate_period_seconds=candidate_period_seconds,
                        tick_ordinal=tick_ordinal,
                        scheduled_at_seconds=scheduled_at,
                        requested_at_seconds=requested_at,
                        processing_started_at_seconds=processing_started_at,
                        completed_visible_at_seconds=completed_visible_at,
                        resolved_sample=resolved,
                        previously_presented_sample_index=(
                            currently_presented_sample_index
                        ),
                        action=action,
                        pending_presentation_requests_at_request=(
                            pending_presentation_requests_at_request
                        ),
                        pending_presentation_requests_at_start=(
                            pending_presentation_requests_at_start
                        ),
                        selected_vti_matches_expected=selected_matches,
                        fresh_execution=None,
                        execution_success=None,
                        geometry_replaced=None,
                        preview_matches_runtime=None,
                        source_transition_ms=None,
                        operator_rebuild_ms=None,
                        usdrt_ready_ms=None,
                        preview_update_ms=None,
                        total_visible_update_ms=None,
                        curve_count=None,
                        point_count=None,
                        bounds=None,
                        signature=None,
                    )
                    carb.log_warn(
                        with_dtrs_yerevan_timestamp(
                            self._format_presentation_tick_observation(record, scenario)
                        )
                    )
                    return record

                if prepared is not None:
                    # The old preview remains authored while the old Kit owner is
                    # retired; it is replaced only after the next UsdRT result.
                    prepared.operator_api.CreateEnabledAttr().Set(False)
                source_started_at = time.monotonic()
                selected_asset = await self._select_temporal_probe_source_in_kit(
                    app,
                    timeline=timeline,
                    field_prim=field_prim,
                    sample=resolved,
                    cae_vtk=cae_vtk,
                    Usd=Usd,
                )
                source_transition_ms = (time.monotonic() - source_started_at) * 1000.0
                if selected_asset.resolve() != resolved.source_vti.resolve():
                    raise RuntimeError(
                        "Presentation resolver selected an unexpected manifest VTI."
                    )

                rebuild_started_at = time.monotonic()
                if prepared is not None:
                    cleaned = await self._cleanup_package_c_operator_in_kit(
                        stage,
                        app=app,
                        prepared=prepared,
                        UsdGeom=UsdGeom,
                    )
                    if not cleaned:
                        raise RuntimeError(
                            "Previous presentation Streamlines operator did not "
                            "cleanly rebuild."
                        )
                prepared = await self._prepare_package_c_operator_in_kit(
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
                if prepared.source_processing_mode != "subset":
                    raise RuntimeError(
                        "Presentation Cadence must use the selected standard operator "
                        "path."
                    )
                await app.next_update_async()
                begin_before = self._kit_cae_operator_begin_count(request.operator_path)
                completion_before = self._kit_cae_operator_completion_count(
                    request.operator_path
                )
                prepared.operator_api.CreateEnabledAttr().Set(True)
                receipt = await self._await_package_c_execution_receipt(
                    app,
                    request,
                    begin_before=begin_before,
                    completion_before=completion_before,
                )
                operator_rebuild_ms = (time.monotonic() - rebuild_started_at) * 1000.0
                if not receipt.accepted:
                    raise RuntimeError(
                        "Kit-CAE did not report a fresh presentation Streamlines "
                        "execution "
                        f"(begin={begin_before}->{receipt.begin_count_after}; "
                        f"end={completion_before}->{receipt.completion_count_after}; "
                        f"success={receipt.completion_success})."
                    )
                evidence = inspect_static_streamlines_proof(
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
                    operator_completion_count=receipt.completion_count_after,
                    fresh_execution=receipt.fresh_execution,
                    operator_execution_success=receipt.completion_success,
                    source_world_bounds=descriptor.world_bounds,
                )
                validate_generated_streamlines_geometry(
                    evidence.runtime_curve_count,
                    evidence.runtime_point_count,
                    point_positions=evidence.runtime_point_positions,
                    curve_vertex_counts=evidence.runtime_curve_vertex_counts,
                )
                if not self._temporal_probe_evidence_is_valid(request, evidence):
                    raise RuntimeError(
                        "Presentation Streamlines output did not satisfy the frozen "
                        "no-Flow contract."
                    )
                usdrt_ready_ms = (time.monotonic() - requested_at) * 1000.0
                preview_started_at = time.monotonic()
                mirror = _author_usdrt_runtime_preview(
                    stage,
                    operator_prim=prepared.operator_prim,
                    evidence=evidence,
                    preview_path=PRESENTATION_RUNTIME_PREVIEW_PATH,
                    UsdGeom=UsdGeom,
                    UsdGeomRT=UsdGeomRT,
                    cae_usd_utils=cae_usd_utils,
                    Sdf=Sdf,
                )
                await self._await_temporal_probe_preview_quiescence(app)
                completed_visible_at = time.monotonic()
                record = PresentationTickObservation(
                    candidate_period_seconds=candidate_period_seconds,
                    tick_ordinal=tick_ordinal,
                    scheduled_at_seconds=scheduled_at,
                    requested_at_seconds=requested_at,
                    processing_started_at_seconds=processing_started_at,
                    completed_visible_at_seconds=completed_visible_at,
                    resolved_sample=resolved,
                    previously_presented_sample_index=currently_presented_sample_index,
                    action=action,
                    pending_presentation_requests_at_request=(
                        pending_presentation_requests_at_request
                    ),
                    pending_presentation_requests_at_start=(
                        pending_presentation_requests_at_start
                    ),
                    selected_vti_matches_expected=True,
                    fresh_execution=receipt.fresh_execution,
                    execution_success=receipt.completion_success,
                    geometry_replaced=receipt.accepted,
                    preview_matches_runtime=mirror.matches_runtime,
                    source_transition_ms=source_transition_ms,
                    operator_rebuild_ms=operator_rebuild_ms,
                    usdrt_ready_ms=usdrt_ready_ms,
                    preview_update_ms=(time.monotonic() - preview_started_at) * 1000.0,
                    total_visible_update_ms=(completed_visible_at - requested_at)
                    * 1000.0,
                    curve_count=evidence.runtime_curve_count,
                    point_count=evidence.runtime_point_count,
                    bounds=evidence.runtime_curve_bounds,
                    signature=geometry_signature_from_evidence(evidence),
                )
                currently_presented_sample_index = resolved.sample_index
                currently_selected_vti = selected_asset
                carb.log_warn(
                    with_dtrs_yerevan_timestamp(
                        self._format_presentation_tick_observation(record, scenario)
                    )
                )
                return record

            async def run_scheduled_ticks(
                period_seconds: float,
                tick_count: int,
                *,
                scenario: str,
            ) -> tuple[PresentationTickObservation, ...]:
                """Queue wall-clock ticks without waiting for the serial consumer."""

                request_queue: asyncio.Queue[
                    tuple[PresentationResolvedSample, int, float, float, int]
                ] = asyncio.Queue()
                scheduled_start = time.monotonic()
                phases = build_presentation_tick_phases(
                    period_seconds,
                    tick_count,
                    loop_duration_seconds=PRESENTATION_LOOP_DURATION_SECONDS,
                )

                async def enqueue_ticks() -> None:
                    for ordinal, phase in enumerate(phases, start=1):
                        scheduled_at = scheduled_start + (ordinal - 1) * period_seconds
                        await asyncio.sleep(max(0.0, scheduled_at - time.monotonic()))
                        requested_at = time.monotonic()
                        pending_requests = request_queue.qsize()
                        await request_queue.put(
                            (
                                resolve_presentation_sample(source, phase),
                                ordinal,
                                scheduled_at,
                                requested_at,
                                pending_requests,
                            )
                        )

                producer = asyncio.ensure_future(enqueue_ticks())
                records = []
                try:
                    for _ in range(tick_count):
                        queued = await request_queue.get()
                        (
                            resolved,
                            ordinal,
                            scheduled_at,
                            requested_at,
                            pending_requests,
                        ) = queued
                        records.append(
                            await consume_tick(
                                resolved,
                                candidate_period_seconds=period_seconds,
                                tick_ordinal=ordinal,
                                scenario=scenario,
                                scheduled_at_seconds=scheduled_at,
                                requested_at_seconds=requested_at,
                                pending_presentation_requests_at_request=(
                                    pending_requests
                                ),
                                pending_presentation_requests_at_start=(
                                    request_queue.qsize()
                                ),
                            )
                        )
                    await producer
                finally:
                    if not producer.done():
                        producer.cancel()
                    try:
                        await producer
                    except asyncio.CancelledError:
                        pass
                return tuple(records)

            async def run_candidate(
                period_seconds: float,
            ) -> tuple[
                PresentationCandidateAssessment,
                tuple[PresentationTickObservation, ...],
            ]:
                """Screen one coarse or refined period with six scheduled ticks."""

                self._streamlines_presentation_cadence_active_stage = "CANDIDATE"
                carb.log_warn(
                    with_dtrs_yerevan_timestamp(
                        "DTRS STREAMLINES | PRESENTATION_CADENCE | CANDIDATE | "
                        f"period={period_seconds:.1f}s | RUNNING"
                    )
                )
                # A real warmup result removes first-use Kit work from the six
                # measured ticks without altering the manifest source contract.
                warmup = resolve_presentation_sample(
                    source,
                    PRESENTATION_LOOP_DURATION_SECONDS - source.sample_interval_seconds,
                )
                await consume_tick(
                    warmup,
                    candidate_period_seconds=period_seconds,
                    tick_ordinal=0,
                    scenario="candidate_warmup",
                )
                records = await run_scheduled_ticks(
                    period_seconds,
                    PRESENTATION_SCREENING_TICK_COUNT,
                    scenario="candidate_screen",
                )
                assessment = assess_presentation_candidate(period_seconds, records)
                state = "SCREEN_PASS" if assessment.viable else "SCREEN_REJECTED"
                carb.log_warn(
                    with_dtrs_yerevan_timestamp(
                        self._format_presentation_candidate_result(assessment, state)
                    )
                )
                return assessment, records

            async def run_sustained_confirmation(
                period_seconds: float,
            ) -> tuple[
                PresentationCandidateAssessment,
                tuple[PresentationTickObservation, ...],
                tuple[
                    tuple[
                        PresentationTickObservation,
                        PresentationTickObservation,
                    ],
                    ...,
                ],
                CadencePerformanceEvidence,
                CadencePerformanceEvidence,
            ]:
                """Confirm one screened period before allowing it to end the search."""

                self._streamlines_presentation_cadence_active_stage = (
                    "FINAL_CONFIRMATION"
                )
                carb.log_warn(
                    with_dtrs_yerevan_timestamp(
                        "DTRS STREAMLINES | PRESENTATION_CADENCE | "
                        "FINAL_CONFIRMATION | "
                        f"period={period_seconds:.1f}s | RUNNING"
                    )
                )
                await consume_tick(
                    resolve_presentation_sample(source, 0.0),
                    candidate_period_seconds=period_seconds,
                    tick_ordinal=0,
                    scenario="final_baseline_warmup",
                )
                baseline = await self._capture_cadence_performance_evidence(
                    initial_delay_seconds=CADENCE_PERFORMANCE_SETTLE_SECONDS,
                )
                sustained_task = asyncio.ensure_future(
                    self._capture_cadence_performance_evidence(
                        initial_delay_seconds=CADENCE_PERFORMANCE_SETTLE_SECONDS,
                    )
                )
                try:
                    records = await run_scheduled_ticks(
                        period_seconds,
                        PRESENTATION_FINAL_CONFIRMATION_TICK_COUNT,
                        scenario="final_confirmation",
                    )
                    sustained = await sustained_task
                except BaseException:
                    if not sustained_task.done():
                        sustained_task.cancel()
                    try:
                        await sustained_task
                    except asyncio.CancelledError:
                        pass
                    raise
                assessment = assess_presentation_candidate(period_seconds, records)
                wraps = tuple(
                    (previous, current)
                    for previous, current in zip(records, records[1:])
                    if current.resolved_sample.presentation_phase_seconds
                    < previous.resolved_sample.presentation_phase_seconds
                )
                if not wraps:
                    raise RuntimeError(
                        "Final presentation confirmation did not cross the 16-second "
                        "loop."
                    )
                return assessment, records, wraps, baseline, sustained

            candidate_results = []
            for period_seconds in PRESENTATION_COARSE_PERIODS_SECONDS:
                screening, _ = await run_candidate(period_seconds)
                candidate = PresentationCandidateResult(screening)
                if not screening.viable:
                    candidate_results.append(candidate)
                    continue

                (
                    final_assessment,
                    final_records,
                    loop_wrap_records,
                    baseline,
                    sustained,
                ) = await run_sustained_confirmation(period_seconds)
                candidate = PresentationCandidateResult(
                    screening,
                    final_confirmation=final_assessment,
                )
                candidate_results.append(candidate)
                carb.log_warn(
                    with_dtrs_yerevan_timestamp(
                        self._format_presentation_candidate_result(
                            final_assessment,
                            candidate.state,
                        )
                    )
                )
                if not final_assessment.viable:
                    # A short screen only identifies a promising boundary. A
                    # sustained miss is evidence to continue at the next
                    # larger period, not evidence that no cadence exists.
                    continue

                recovery_started_at = time.monotonic()
                recovery = await self._capture_cadence_performance_evidence(
                    initial_delay_seconds=CADENCE_PERFORMANCE_SETTLE_SECONDS,
                )
                return {
                    "decision": "TIME_BASED_PRESENTATION_VIABLE",
                    "candidate_results": tuple(candidate_results),
                    "selected_period_seconds": period_seconds,
                    "final_assessment": final_assessment,
                    "final_records": final_records,
                    "loop_wrap_records": loop_wrap_records,
                    "baseline_performance": baseline,
                    "sustained_performance": sustained,
                    "recovery_performance": recovery,
                    "recovery_started_at": recovery_started_at,
                }

            return {
                "decision": "NO_CREDIBLE_PRESENTATION_CADENCE",
                "candidate_results": tuple(candidate_results),
            }
        finally:
            if prepared is not None:
                await self._cleanup_package_c_operator_in_kit(
                    stage,
                    app=app,
                    prepared=prepared,
                    UsdGeom=UsdGeom,
                )
            self._stop_kit_cae_operator_tracking()
            stage.SetEditTarget(previous_target)

    async def _run_cadence_burst_in_kit(
        self,
        plan: CadenceFeasibilityPlan,
        *,
        consume_boundary,
    ) -> tuple[tuple[CadenceBoundaryObservation, ...], CadencePerformanceEvidence]:
        """Queue real source requests at cadence while one consumer stays serial."""

        request_queue: asyncio.Queue[tuple[CadenceSample, float, float, int] | None] = (
            asyncio.Queue()
        )
        burst_started_at = time.monotonic()
        stop_performance_sampling = asyncio.Event()

        async def enqueue_requests() -> None:
            for ordinal, sample in enumerate(plan.burst_samples):
                scheduled_at = burst_started_at + (
                    ordinal * plan.source_period_ms / 1000.0
                )
                await asyncio.sleep(max(0.0, scheduled_at - time.monotonic()))
                requested_at = time.monotonic()
                queue_depth_at_request = request_queue.qsize()
                await request_queue.put(
                    (
                        sample,
                        scheduled_at,
                        requested_at,
                        queue_depth_at_request,
                    )
                )
            await request_queue.put(None)

        async def sample_during_burst() -> CadencePerformanceEvidence:
            samples = []
            while (
                not stop_performance_sampling.is_set()
                and len(samples) < CADENCE_PERFORMANCE_SNAPSHOT_COUNT
            ):
                await asyncio.sleep(CADENCE_PERFORMANCE_SNAPSHOT_INTERVAL_SECONDS)
                if stop_performance_sampling.is_set():
                    break
                samples.append(capture_viewport_performance_sample())
            return build_cadence_performance_evidence(samples)

        producer = asyncio.ensure_future(enqueue_requests())
        sampler = asyncio.ensure_future(sample_during_burst())
        records: list[CadenceBoundaryObservation] = []
        try:
            while True:
                queued = await request_queue.get()
                if queued is None:
                    break
                sample, scheduled_at, requested_at, queue_depth_at_request = queued
                record = await consume_boundary(
                    sample,
                    scenario="5hz_burst",
                    requested_at_seconds=requested_at,
                    scheduled_at_seconds=scheduled_at,
                    queue_depth_at_request=queue_depth_at_request,
                    queue_depth_at_start=request_queue.qsize(),
                )
                records.append(record)
            await producer
        finally:
            stop_performance_sampling.set()
            if not producer.done():
                producer.cancel()
            try:
                await producer
            except asyncio.CancelledError:
                pass
            try:
                during_performance = await sampler
            except asyncio.CancelledError:
                if not sampler.done():
                    sampler.cancel()
                raise
        return tuple(records), during_performance

    async def _capture_cadence_performance_evidence(
        self,
        *,
        initial_delay_seconds: float,
    ) -> CadencePerformanceEvidence:
        """Collect independent Flow-HUD observations without touching Kit operators."""

        await asyncio.sleep(initial_delay_seconds)
        samples = []
        for ordinal in range(CADENCE_PERFORMANCE_SNAPSHOT_COUNT):
            samples.append(capture_viewport_performance_sample())
            if ordinal + 1 < CADENCE_PERFORMANCE_SNAPSHOT_COUNT:
                await asyncio.sleep(CADENCE_PERFORMANCE_SNAPSHOT_INTERVAL_SECONDS)
        return build_cadence_performance_evidence(samples)

    @staticmethod
    def _validate_cadence_records(
        records: tuple[CadenceBoundaryObservation, ...],
        scenario: str,
    ) -> None:
        """Require a confirmed visible result for every non-skipped real source."""

        if not records:
            raise RuntimeError(
                f"Cadence scenario {scenario} produced no source records."
            )
        if not all(
            record.fresh_execution
            and record.execution_success is True
            and record.geometry_replaced
            and record.preview_matches_runtime
            for record in records
        ):
            raise RuntimeError(
                f"Cadence scenario {scenario} contains an unconfirmed visible result."
            )

    def _publish_cadence_stage(
        self,
        ordinal: int,
        stage: str,
        state: str,
        *,
        status_callback: StatusCallback | None,
    ) -> None:
        """Keep the long-running Package F procedure visible in both UI and log."""

        self._streamlines_cadence_active_stage = stage
        message = (
            "DTRS STREAMLINES | CADENCE_FEASIBILITY | "
            f"STAGE {ordinal}/6 | {stage} | {state}"
        )
        carb = self._streamlines_carb_logger()
        if carb:
            carb.log_warn(with_dtrs_yerevan_timestamp(message))
        if status_callback:
            status_callback(
                f"Cadence Feasibility — stage {ordinal}/6: {stage} ({state})"
            )

    @staticmethod
    def _format_cadence_boundary_observation(
        record: CadenceBoundaryObservation,
    ) -> str:
        """Log raw boundary evidence compactly enough to identify real outliers."""

        lines = (
            "DTRS STREAMLINES | CADENCE_FEASIBILITY | BOUNDARY | PASS",
            f"scenario={record.scenario}",
            f"sample_index={record.sample.sample_index}",
            f"source_time_seconds={record.sample.source_time_seconds:.6g}",
            f"time_code={record.sample.time_code:.6g}",
            f"selected_vti={record.sample.source_vti}",
            "selected_vti_matches_expected=True",
            "operator_receipt="
            f"begin={record.begin_count_before}->{record.begin_count_after}; "
            f"end={record.completion_count_before}->{record.completion_count_after}; "
            f"fresh={record.fresh_execution}; success={record.execution_success}",
            f"source_transition_ms={record.source_transition_ms:.0f}",
            f"operator_rebuild_ms={record.operator_rebuild_ms:.0f}",
            f"usdrt_ready_ms={record.usdrt_ready_ms:.0f}",
            f"preview_update_ms={record.preview_update_ms:.0f}",
            f"total_visible_update_ms={record.total_visible_update_ms:.0f}",
            f"curve_count={record.curve_count}",
            f"point_count={record.point_count}",
            f"bounds={record.bounds}",
            f"geometry_replaced={record.geometry_replaced}",
            f"preview_matches_runtime={record.preview_matches_runtime}",
        )
        if record.scheduled_at_seconds is None:
            return "\n".join(lines)
        return "\n".join(
            (*lines,)
            + (
                f"scheduled_at={record.scheduled_at_seconds:.6f}",
                f"requested_at={record.requested_at_seconds:.6f}",
                f"actual_processing_start={record.processing_started_at_seconds:.6f}",
                f"completed_visible_at={record.completed_visible_at_seconds:.6f}",
                f"start_lateness_ms={record.start_lateness_ms:.0f}",
                f"completion_lateness_ms={record.completion_lateness_ms:.0f}",
                f"queue_depth_at_request={record.queue_depth_at_request}",
                f"queue_depth_at_start={record.queue_depth_at_start}",
            )
        )

    @staticmethod
    def _format_cadence_feasibility_failure(
        *,
        failed_stage: str,
        error: Exception,
        cleanup: StaticStreamlinesCleanupReceipt,
        total_ms: float,
    ) -> str:
        """Give an unambiguous terminal failure without hiding rollback state."""

        return "\n".join(
            (
                "========================================",
                "DTRS STREAMLINES | CADENCE_FEASIBILITY | TEST COMPLETE | FAIL",
                "========================================",
                f"failed_stage={failed_stage}",
                f"reason={error}",
                f"rollback={'CLEAN' if cleanup.clean else 'DIRTY'}",
                "NEXT_ACTION | Stop. Package F is incomplete; inspect this failure.",
                f"total_ms={total_ms:.0f}",
            )
        )

    @staticmethod
    def _format_cadence_feasibility_success(
        *,
        source: TemporalVelocitySourceDescriptor,
        plan: CadenceFeasibilityPlan,
        measurement: dict[str, object],
        classification,
        cleanup: StaticStreamlinesCleanupReceipt,
        total_ms: float,
    ) -> str:
        """Summarise a valid measurement without equating PASS with 5 Hz viability."""

        baseline = measurement["baseline_performance"]
        sequential = measurement["sequential_records"]
        repeated = measurement["repeated_records"]
        loop = measurement["loop_records"]
        burst = measurement["burst_records"]
        during = measurement["during_performance"]
        recovery = measurement["recovery_performance"]
        recovery_started_at = measurement["recovery_started_at"]
        if not isinstance(baseline, CadencePerformanceEvidence):
            raise RuntimeError("Cadence baseline performance evidence is missing.")
        if not all(
            isinstance(records, tuple)
            for records in (
                sequential,
                repeated,
                loop,
                burst,
            )
        ):
            raise RuntimeError("Cadence boundary records have an invalid shape.")
        if not isinstance(during, CadencePerformanceEvidence):
            raise RuntimeError("Cadence in-burst performance evidence is missing.")
        if not isinstance(recovery, CadencePerformanceEvidence):
            raise RuntimeError("Cadence recovery performance evidence is missing.")
        if not isinstance(recovery_started_at, float):
            raise RuntimeError("Cadence recovery start time is missing.")

        def metrics(records) -> tuple[str, ...]:
            source_median, source_max = median_and_max(records, "source_transition_ms")
            rebuild_median, rebuild_max = median_and_max(records, "operator_rebuild_ms")
            usdrt_median, usdrt_max = median_and_max(records, "usdrt_ready_ms")
            preview_median, preview_max = median_and_max(records, "preview_update_ms")
            total_median, total_max = median_and_max(records, "total_visible_update_ms")
            return (
                (
                    "  source_transition_ms median/max="
                    f"{source_median:.0f}/{source_max:.0f}"
                ),
                (
                    "  operator_rebuild_ms median/max="
                    f"{rebuild_median:.0f}/{rebuild_max:.0f}"
                ),
                f"  usdrt_ready_ms median/max={usdrt_median:.0f}/{usdrt_max:.0f}",
                (
                    "  preview_update_ms median/max="
                    f"{preview_median:.0f}/{preview_max:.0f}"
                ),
                (
                    "  total_visible_update_ms median/max="
                    f"{total_median:.0f}/{total_max:.0f}"
                ),
            )

        burst_start_median, burst_start_max = median_and_max(burst, "start_lateness_ms")
        burst_completion_median, burst_completion_max = median_and_max(
            burst,
            "completion_lateness_ms",
        )
        max_queue_depth = max(
            max(
                record.queue_depth_at_request or 0,
                record.queue_depth_at_start or 0,
            )
            for record in burst
        )
        missed_deadlines = sum(
            record.completion_lateness_ms is not None
            and record.completion_lateness_ms > plan.source_period_ms
            for record in burst
        )
        recovery_seconds = recovery_time_to_baseline_seconds(
            baseline,
            recovery,
            recovery_started_at_seconds=recovery_started_at,
        )
        return "\n".join(
            (
                "========================================",
                "DTRS STREAMLINES | CADENCE_FEASIBILITY | TEST COMPLETE | PASS",
                "========================================",
                "",
                f"classification={classification.value}",
                f"classification_reason={classification.reason}",
                "production_operator=standard",
                f"dataset_cadence_hz={source.source_cadence_hz:.6g}",
                f"source_period_ms={plan.source_period_ms:.0f}",
                "",
                "sequential:",
                *metrics(sequential),
                "repeat_sample:",
                *metrics(repeated),
                "loop_boundary:",
                *metrics(loop),
                "  final_to_first=PASS",
                "  returned_first_geometry_consistent=True",
                "5hz_burst:",
                f"  requested_samples={len(plan.burst_samples)}",
                f"  completed_samples={len(burst)}",
                f"  missed_200ms_deadlines={missed_deadlines}",
                f"  max_queue_depth={max_queue_depth}",
                (
                    "  start_lateness_ms median/max="
                    f"{burst_start_median:.0f}/{burst_start_max:.0f}"
                ),
                "  completion_lateness_ms median/max="
                f"{burst_completion_median:.0f}/{burst_completion_max:.0f}",
                *metrics(burst),
                "performance:",
                "  baseline_fps="(
                    f"median={baseline.fps_median}; min={baseline.fps_min}; "
                    f"max={baseline.fps_max}"
                ),
                f"  baseline_fps_snapshots={baseline.fps_snapshots}",
                "  during_burst_fps="(
                    f"median={during.fps_median}; min={during.fps_min}; "
                    f"max={during.fps_max}"
                ),
                f"  during_burst_fps_snapshots={during.fps_snapshots}",
                "  recovered_fps="(
                    f"median={recovery.fps_median}; min={recovery.fps_min}; "
                    f"max={recovery.fps_max}"
                ),
                f"  recovered_fps_snapshots={recovery.fps_snapshots}",
                f"  recovery_time_to_90pct_baseline_seconds={recovery_seconds}",
                "  gpu_memory_gib="
                f"baseline={baseline.gpu_memory_median_gib}; "
                f"during={during.gpu_memory_median_gib}; "
                f"recovery={recovery.gpu_memory_median_gib}",
                "  gpu_memory_snapshots_gib="
                f"baseline={baseline.gpu_memory_snapshots_gib}; "
                f"during={during.gpu_memory_snapshots_gib}; "
                f"recovery={recovery.gpu_memory_snapshots_gib}",
                "  process_memory_gib="
                f"baseline={baseline.process_memory_median_gib}; "
                f"during={during.process_memory_median_gib}; "
                f"recovery={recovery.process_memory_median_gib}",
                "  process_memory_snapshots_gib="
                f"baseline={baseline.process_memory_snapshots_gib}; "
                f"during={during.process_memory_snapshots_gib}; "
                f"recovery={recovery.process_memory_snapshots_gib}",
                f"cleanup={'CLEAN' if cleanup.clean else 'DIRTY'}",
                "",
                "Package F measurement complete.",
                "No further manual action required.",
                "No cadence optimization has been applied.",
                "result=PASS",
                f"total_ms={total_ms:.0f}",
            )
        )

    @staticmethod
    def _format_presentation_tick_observation(
        record: PresentationTickObservation,
        scenario: str,
    ) -> str:
        """Log one time-based tick without hiding a same-source no-op."""

        resolved = record.resolved_sample
        common = (
            f"candidate_period_seconds={record.candidate_period_seconds:.1f}",
            f"tick_ordinal={record.tick_ordinal}",
            f"presentation_phase_seconds={resolved.presentation_phase_seconds:.6g}",
            f"resolved_sample_index={resolved.sample_index}",
            f"resolved_source_time_seconds={resolved.source_time_seconds:.6g}",
            f"resolved_timecode={resolved.time_code:.6g}",
            f"resolved_vti={resolved.source_vti}",
            (
                "previously_presented_sample_index="
                f"{record.previously_presented_sample_index}"
            ),
            f"scheduled_at={record.scheduled_at_seconds:.6f}",
            f"requested_at={record.requested_at_seconds:.6f}",
            f"actual_processing_start={record.processing_started_at_seconds:.6f}",
            f"completed_visible_at={record.completed_visible_at_seconds:.6f}",
            f"start_lateness_ms={record.start_lateness_ms:.0f}",
            "completion_deadline_lateness_ms="
            f"{record.completion_deadline_lateness_ms:.0f}",
            "scheduler_sentinel_pending=False",
            "pending_presentation_requests_at_request="
            f"{record.pending_presentation_requests_at_request}",
            "pending_presentation_requests_at_start="
            f"{record.pending_presentation_requests_at_start}",
            f"selected_vti_matches_expected={record.selected_vti_matches_expected}",
        )
        if record.is_no_op:
            return "\n".join(
                (
                    "DTRS STREAMLINES | PRESENTATION_CADENCE | "
                    "SAME_SOURCE_SAMPLE | NO_OP",
                    f"scenario={scenario}",
                    *common,
                    "action=NO_OP",
                )
            )
        return "\n".join(
            (
                "DTRS STREAMLINES | PRESENTATION_CADENCE | TICK | PASS",
                f"scenario={scenario}",
                *common,
                "action=REBUILD",
                "operator_receipt="
                f"fresh={record.fresh_execution}; success={record.execution_success}",
                f"source_transition_ms={record.source_transition_ms:.0f}",
                f"operator_rebuild_ms={record.operator_rebuild_ms:.0f}",
                f"usdrt_ready_ms={record.usdrt_ready_ms:.0f}",
                f"preview_update_ms={record.preview_update_ms:.0f}",
                f"total_visible_update_ms={record.total_visible_update_ms:.0f}",
                (
                    "headroom_before_next_tick_ms="
                    f"{record.headroom_before_next_tick_ms:.0f}"
                ),
                f"curve_count={record.curve_count}",
                f"point_count={record.point_count}",
                f"bounds={record.bounds}",
                f"geometry_replaced={record.geometry_replaced}",
                f"preview_matches_runtime={record.preview_matches_runtime}",
            )
        )

    @staticmethod
    def _format_presentation_candidate_result(
        assessment: PresentationCandidateAssessment,
        state: str,
    ) -> str:
        """Make every coarse or refined candidate decision independently reviewable."""

        return "\n".join(
            (
                "DTRS STREAMLINES | PRESENTATION_CADENCE | CANDIDATE | "
                f"period={assessment.period_seconds:.1f}s | {state}",
                f"reason={assessment.reason}",
                f"rebuilt_ticks={assessment.rebuilt_ticks}",
                f"no_op_ticks={assessment.no_op_ticks}",
                f"missed_deadlines={assessment.missed_deadlines}",
                "max_pending_presentation_requests="
                f"{assessment.max_pending_presentation_requests}",
                "total_visible_update_ms median/max="
                f"{assessment.total_visible_update_median_ms}/"
                f"{assessment.total_visible_update_max_ms}",
                "headroom_ms median/min="
                f"{assessment.headroom_median_ms}/{assessment.headroom_min_ms}",
                f"lateness_drift={assessment.lateness_drift}",
                "scheduling_lateness_drift=" f"{assessment.scheduling_lateness_drift}",
            )
        )

    @staticmethod
    def _format_presentation_cadence_failure(
        *,
        failed_stage: str,
        error: Exception,
        cleanup: StaticStreamlinesCleanupReceipt,
        total_ms: float,
    ) -> str:
        """Give Package G a terminal harness failure distinct from reassessment."""

        return "\n".join(
            (
                "========================================",
                "DTRS STREAMLINES | PRESENTATION_CADENCE",
                "TEST COMPLETE | FAIL",
                "========================================",
                f"failed_stage={failed_stage}",
                f"reason={error}",
                f"rollback={'CLEAN' if cleanup.clean else 'DIRTY'}",
                "NEXT_ACTION | Stop. Package G is incomplete; inspect this failure.",
                f"total_ms={total_ms:.0f}",
            )
        )

    @staticmethod
    def _format_presentation_cadence_terminal(
        *,
        source: TemporalVelocitySourceDescriptor,
        measurement: dict[str, object],
        cleanup: StaticStreamlinesCleanupReceipt,
        total_ms: float,
    ) -> str:
        """Report a viable period or a scope-reassessment decision without ambiguity."""

        decision = measurement["decision"]
        candidates = measurement["candidate_results"]
        if not isinstance(decision, str):
            raise RuntimeError("Presentation cadence decision is missing.")
        if not isinstance(candidates, tuple):
            raise RuntimeError("Presentation cadence candidate evidence is missing.")
        candidate_lines = tuple(
            "  "
            f"{candidate.screening.period_seconds:.1f}s = {candidate.state}"
            + (f": {candidate.reason}" if candidate.state != "FINAL_PASS" else "")
            for candidate in candidates
            if isinstance(candidate, PresentationCandidateResult)
        )
        if decision == "NO_CREDIBLE_PRESENTATION_CADENCE":
            return "\n".join(
                (
                    "========================================",
                    "DTRS STREAMLINES | PRESENTATION_CADENCE",
                    "TEST COMPLETE | REASSESS",
                    "========================================",
                    "decision=NO_CREDIBLE_PRESENTATION_CADENCE",
                    "source_clock=MANIFEST_DEFINED_PER_WORKLOAD",
                    f"loop_duration_seconds={PRESENTATION_LOOP_DURATION_SECONDS:.0f}",
                    "presentation_clock=TIME_BASED",
                    "candidate_results:",
                    *candidate_lines,
                    f"cleanup={'CLEAN' if cleanup.clean else 'DIRTY'}",
                    "NEXT_ACTION | Stop before Phase 3 and reassess Stage 09 scope.",
                    f"total_ms={total_ms:.0f}",
                )
            )

        period = measurement["selected_period_seconds"]
        final = measurement["final_assessment"]
        records = measurement["final_records"]
        wraps = measurement["loop_wrap_records"]
        baseline = measurement["baseline_performance"]
        sustained = measurement["sustained_performance"]
        recovery = measurement["recovery_performance"]
        recovery_started_at = measurement["recovery_started_at"]
        if not isinstance(period, float):
            raise RuntimeError("Selected presentation period is missing.")
        if not isinstance(final, PresentationCandidateAssessment):
            raise RuntimeError("Final presentation assessment is missing.")
        if not isinstance(records, tuple) or not isinstance(wraps, tuple):
            raise RuntimeError("Presentation tick evidence has an invalid shape.")
        if not isinstance(baseline, CadencePerformanceEvidence):
            raise RuntimeError("Presentation baseline performance evidence is missing.")
        if not isinstance(sustained, CadencePerformanceEvidence):
            raise RuntimeError(
                "Presentation sustained performance evidence is missing."
            )
        if not isinstance(recovery, CadencePerformanceEvidence):
            raise RuntimeError("Presentation recovery performance evidence is missing.")
        if not isinstance(recovery_started_at, float):
            raise RuntimeError("Presentation recovery start time is missing.")
        recovery_seconds = recovery_time_to_baseline_seconds(
            baseline,
            recovery,
            recovery_started_at_seconds=recovery_started_at,
        )
        rebuilt_ticks = sum(
            not record.is_no_op
            for record in records
            if isinstance(record, PresentationTickObservation)
        )
        no_op_ticks = len(records) - rebuilt_ticks
        first_wrap_previous, first_wrap_current = wraps[0]
        if not isinstance(first_wrap_previous, PresentationTickObservation):
            raise RuntimeError("Loop-wrap previous observation is missing.")
        if not isinstance(first_wrap_current, PresentationTickObservation):
            raise RuntimeError("Loop-wrap current observation is missing.")
        return "\n".join(
            (
                "========================================",
                "DTRS STREAMLINES | PRESENTATION_CADENCE",
                "TEST COMPLETE | VIABLE",
                "========================================",
                "decision=TIME_BASED_PRESENTATION_VIABLE",
                "source_clock=MANIFEST_DEFINED_PER_WORKLOAD",
                f"loop_duration_seconds={PRESENTATION_LOOP_DURATION_SECONDS:.0f}",
                "presentation_clock=TIME_BASED",
                f"presentation_period_seconds={period:.1f}",
                f"presentation_cadence_hz={1.0 / period:.6g}",
                "source_resolution_policy=LATEST_SAMPLE_AT_OR_BEFORE_PHASE",
                "same_sample_policy=NO_OP",
                "interpolation=NONE",
                "candidate_results:",
                *candidate_lines,
                "final_confirmation:",
                f"  measured_ticks={len(records)}",
                f"  rebuilt_ticks={rebuilt_ticks}",
                f"  no_op_ticks={no_op_ticks}",
                f"  missed_deadlines={final.missed_deadlines}",
                "  max_pending_presentation_requests="
                f"{final.max_pending_presentation_requests}",
                f"  lateness_drift={final.lateness_drift}",
                "  scheduling_lateness_drift=" f"{final.scheduling_lateness_drift}",
                "  total_visible_update_ms median/max="
                f"{final.total_visible_update_median_ms}/"
                f"{final.total_visible_update_max_ms}",
                (
                    "  headroom_ms median/min="
                    f"{final.headroom_median_ms}/{final.headroom_min_ms}"
                ),
                "loop_wrap=PASS",
                "  previous_phase_seconds="
                f"{first_wrap_previous.resolved_sample.presentation_phase_seconds:.6g}",
                "  wrapped_phase_seconds="
                f"{first_wrap_current.resolved_sample.presentation_phase_seconds:.6g}",
                (
                    "  resolved_sample_index="
                    f"{first_wrap_current.resolved_sample.sample_index}"
                ),
                "  resolved_source_time="
                f"{first_wrap_current.resolved_sample.source_time_seconds:.6g}",
                f"  resolved_vti={first_wrap_current.resolved_sample.source_vti}",
                "exact_source_mapping=PASS",
                "geometry_correctness=PASS",
                f"cleanup={'CLEAN' if cleanup.clean else 'DIRTY'}",
                "performance:",
                f"  baseline_fps={baseline.fps_median}",
                f"  sustained_fps={sustained.fps_median}",
                f"  recovered_fps={recovery.fps_median}",
                f"  recovery_time_to_90pct_baseline_seconds={recovery_seconds}",
                "  gpu_memory_gib="
                f"baseline={baseline.gpu_memory_median_gib}; "
                f"sustained={sustained.gpu_memory_median_gib}; "
                f"recovery={recovery.gpu_memory_median_gib}",
                "  process_memory_gib="
                f"baseline={baseline.process_memory_median_gib}; "
                f"sustained={sustained.process_memory_median_gib}; "
                f"recovery={recovery.process_memory_median_gib}",
                "",
                "Phase 2 temporal feasibility complete.",
                "No further manual action required.",
                "NEXT_ACTION | Record the Phase 2 decision; do not start Phase 3 "
                "in this change set.",
                f"total_ms={total_ms:.0f}",
            )
        )

    async def _run_temporal_probe_samples_in_kit(
        self,
        source: TemporalVelocitySourceDescriptor,
        probe_samples: tuple[TemporalProbeSample, ...],
        *,
        status_callback: StatusCallback | None,
    ) -> list[dict[str, object]]:
        """Rebuild one standard consumer after every selected source boundary.

        The installed Streamlines operator does not react to a changed temporal
        field by itself.  Recreating this consumer is therefore an explicit,
        source-preserving boundary: the imported temporal ``vel`` field and
        seed contract stay intact while each Kit execution stays causal.
        """

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

        if carb.settings.get_settings().get_as_bool("/app/useFabricSceneDelegate"):
            raise RuntimeError(
                "Temporal Probe requires FSD=false for the accepted X-Ray baseline."
            )
        app = omni.kit.app.get_app()
        stage = omni.usd.get_context().get_stage()
        if not stage:
            raise RuntimeError("Temporal Probe requires an open stage.")
        descriptor = source.static_descriptor
        dataset_prim = stage.GetPrimAtPath(descriptor.dataset_prim_path)
        field_prim = stage.GetPrimAtPath(descriptor.velocity_field_prim_path)
        if not dataset_prim or not dataset_prim.IsValid():
            raise RuntimeError("Temporal Probe dataset prim is unavailable.")
        if not field_prim or not field_prim.IsValid():
            raise RuntimeError("Temporal Probe velocity field is unavailable.")

        request = replace(
            build_static_streamlines_proof_request(descriptor),
            operator_path=TEMPORAL_PROBE_OPERATOR_PATH,
            seed_path=TEMPORAL_PROBE_SEED_PATH,
            operator_type="standard",
        )
        previous_target = stage.GetEditTarget()
        prepared = None
        records: list[dict[str, object]] = []
        previous_signature = None
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
            for sample in probe_samples:
                self._streamlines_temporal_probe_active_sample_index = (
                    sample.sample_index
                )
                if prepared is not None:
                    # Retire the prior consumer before changing the shared field
                    # time. Its RuntimePreview remains visible until replacement.
                    prepared.operator_api.CreateEnabledAttr().Set(False)
                self._publish_temporal_probe_progress(
                    sample,
                    "SELECTING_SOURCE",
                    status_callback=status_callback,
                )
                selected_asset = await self._select_temporal_probe_source_in_kit(
                    app,
                    timeline=timeline,
                    field_prim=field_prim,
                    sample=sample,
                    cae_vtk=cae_vtk,
                    Usd=Usd,
                )
                self._publish_temporal_probe_progress(
                    sample,
                    "SOURCE_READY",
                    status_callback=status_callback,
                )
                carb.log_warn(
                    with_dtrs_yerevan_timestamp(
                        self._format_temporal_probe_source_selection(
                            sample,
                            selected_asset,
                        )
                    )
                )
                self._publish_temporal_probe_progress(
                    sample,
                    "REBUILDING_OPERATOR",
                    status_callback=status_callback,
                )
                if prepared is not None:
                    cleaned = await self._cleanup_package_c_operator_in_kit(
                        stage,
                        app=app,
                        prepared=prepared,
                        UsdGeom=UsdGeom,
                    )
                    if not cleaned:
                        raise RuntimeError(
                            "Previous temporal Streamlines operator did not cleanly "
                            "rebuild."
                        )
                prepared = await self._prepare_package_c_operator_in_kit(
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
                if prepared.source_processing_mode != "subset":
                    raise RuntimeError(
                        "Temporal Probe must use the selected standard operator path."
                    )
                # Follow the disposable Package C sequence: bindings are fully
                # authored first, then Kit observes the disabled operator before
                # its one allowed enable starts this sample's execution.
                await app.next_update_async()
                begin_before = self._kit_cae_operator_begin_count(request.operator_path)
                completion_before = self._kit_cae_operator_completion_count(
                    request.operator_path
                )
                carb.log_warn(
                    with_dtrs_yerevan_timestamp(
                        self._format_temporal_probe_operator_ready(
                            prepared,
                            begin_before=begin_before,
                            completion_before=completion_before,
                        )
                    )
                )
                self._streamlines_temporal_probe_active_stage = "OPERATOR_START"
                record = await self._execute_temporal_probe_consumer_rebuild_in_kit(
                    stage,
                    app=app,
                    timeline=timeline,
                    sample=sample,
                    selected_asset=selected_asset,
                    request=request,
                    descriptor=descriptor,
                    field_prim=field_prim,
                    operator_api=prepared.operator_api,
                    operator_prim=prepared.operator_prim,
                    cae_usd_utils=cae_usd_utils,
                    cae_viz=cae_viz,
                    cae_vtk=cae_vtk,
                    UsdGeom=UsdGeom,
                    UsdGeomRT=UsdGeomRT,
                    Sdf=Sdf,
                    wp=wp,
                    previous_signature=previous_signature,
                    begin_before=begin_before,
                    completion_before=completion_before,
                )
                records.append(record)
                previous_signature = record["signature"]
                self._publish_temporal_probe_progress(
                    sample,
                    "PASS",
                    status_callback=status_callback,
                    emit_log=False,
                )
                carb.log_warn(
                    with_dtrs_yerevan_timestamp(
                        self._format_temporal_probe_sample_record(record)
                    )
                )
        finally:
            if prepared is not None:
                await self._cleanup_package_c_operator_in_kit(
                    stage,
                    app=app,
                    prepared=prepared,
                    UsdGeom=UsdGeom,
                )
            self._stop_kit_cae_operator_tracking()
            stage.SetEditTarget(previous_target)
        return records

    def _publish_temporal_probe_progress(
        self,
        sample: TemporalProbeSample,
        stage: str,
        *,
        status_callback: StatusCallback | None,
        emit_log: bool = True,
    ) -> None:
        """Update probe progress, optionally deferring to a detailed receipt."""

        self._streamlines_temporal_probe_active_stage = stage
        message = (
            "DTRS STREAMLINES | TEMPORAL_PROBE | "
            f"SAMPLE {sample.ordinal}/{sample.total} | {stage}"
        )
        carb = self._streamlines_carb_logger()
        if carb and emit_log:
            carb.log_warn(with_dtrs_yerevan_timestamp(message))
        if status_callback:
            status_callback(f"Sample {sample.ordinal}/{sample.total} — {stage}")

    @staticmethod
    async def _select_temporal_probe_source_in_kit(
        app,
        *,
        timeline,
        field_prim,
        sample: TemporalProbeSample,
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

    async def _execute_temporal_probe_consumer_rebuild_in_kit(
        self,
        stage,
        *,
        app,
        timeline,
        sample: TemporalProbeSample,
        selected_asset,
        request: StaticStreamlinesProofRequest,
        descriptor: StaticVelocitySourceDescriptor,
        field_prim,
        operator_api,
        operator_prim,
        cae_usd_utils,
        cae_viz,
        cae_vtk,
        UsdGeom,
        UsdGeomRT,
        Sdf,
        wp,
        previous_signature: StreamlinesGeometrySignature | None,
        begin_before: int,
        completion_before: int,
    ) -> dict[str, object]:
        """Consume an already verified source through one fresh standard operator."""

        rebuild_started_at = time.monotonic()
        operator_api.CreateEnabledAttr().Set(True)
        execution_receipt = await self._await_package_c_execution_receipt(
            app,
            request,
            begin_before=begin_before,
            completion_before=completion_before,
        )
        rebuild_ms = (time.monotonic() - rebuild_started_at) * 1000.0
        if not execution_receipt.accepted:
            raise RuntimeError(
                "Kit-CAE did not report a fresh temporal Streamlines execution "
                f"(begin={begin_before}->{execution_receipt.begin_count_after}; "
                f"end={completion_before}->{execution_receipt.completion_count_after}; "
                f"success={execution_receipt.completion_success})."
            )
        evidence = inspect_static_streamlines_proof(
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
        if not self._temporal_probe_evidence_is_valid(request, evidence):
            raise RuntimeError(
                "Temporal Streamlines output did not satisfy the no-Flow contract."
            )
        _author_usdrt_runtime_preview(
            stage,
            operator_prim=operator_prim,
            evidence=evidence,
            preview_path=TEMPORAL_PROBE_RUNTIME_PREVIEW_PATH,
            UsdGeom=UsdGeom,
            UsdGeomRT=UsdGeomRT,
            cae_usd_utils=cae_usd_utils,
            Sdf=Sdf,
        )
        await self._await_temporal_probe_preview_quiescence(app)
        signature = geometry_signature_from_evidence(evidence)
        return {
            "sample": sample,
            "receipt": execution_receipt,
            "evidence": evidence,
            "signature": signature,
            "selected_vti": selected_asset,
            # A fresh, causally paired Kit execution is the replacement proof.
            # Geometry may legitimately match when adjacent real samples agree.
            "geometry_replaced": execution_receipt.accepted,
            "geometry_changed": (
                previous_signature is not None
                and not geometry_signatures_match(previous_signature, signature)
            ),
            "rebuild_ms": rebuild_ms,
        }

    @staticmethod
    async def _await_temporal_probe_preview_quiescence(app) -> None:
        """Yield the FSD-safe preview into the standard viewport before sampling HUD."""

        for _ in range(5):
            await app.next_update_async()

    @staticmethod
    def _temporal_probe_evidence_is_valid(
        request: StaticStreamlinesProofRequest,
        evidence: StaticStreamlinesProofEvidence,
    ) -> bool:
        """Validate Package E output while allowing its temporal field samples."""

        return (
            evidence.fresh_execution
            and evidence.operator_execution_success is True
            and evidence.runtime_usdrt_basis_curves
            and evidence.runtime_curve_count > 0
            and evidence.runtime_point_count > 4
            and not evidence.runtime_placeholder_geometry
            and evidence.runtime_curve_bounds_within_source
            and evidence.source_binding == (request.dataset_prim_path,)
            and evidence.seed_binding == (request.seed_path,)
            and evidence.velocity_binding == (request.velocity_field_prim_path,)
            and evidence.direction == request.direction
            and evidence.temporal_sequence == "PRESENT"
            and evidence.flow_environment == "ABSENT"
            and evidence.dataset_emitter == "ABSENT"
            and evidence.boundary_emitter == "ABSENT"
            and evidence.smoke_injectors == "ABSENT"
            and evidence.timeline_playback == "INACTIVE"
        )

    @staticmethod
    def _format_temporal_probe_sequence(
        source: TemporalVelocitySourceDescriptor,
        samples: tuple[TemporalProbeSample, ...],
    ) -> str:
        """Log manifest-derived sequence before Kit begins consuming it."""

        return "\n".join(
            (
                "DTRS STREAMLINES | TEMPORAL_PROBE | SEQUENCE | READY",
                f"workload={source.workload}",
                f"dataset={source.dataset_identity}",
                f"sample_count={source.sample_count}",
                f"source_cadence_hz={source.source_cadence_hz:.6g}",
                "sequence=" + str(tuple(sample.sample_index for sample in samples)),
            )
        )

    @staticmethod
    def _format_temporal_probe_source_selection(
        sample: TemporalProbeSample,
        selected_asset,
    ) -> str:
        """Record the exact composed field source before recreating its consumer."""

        return "\n".join(
            (
                "DTRS STREAMLINES | TEMPORAL_PROBE | SOURCE_SELECTION | PASS",
                f"requested_sample_index={sample.sample_index}",
                f"requested_timecode={sample.time_code:.6g}",
                f"expected_vti={sample.source_vti}",
                f"currently_selected_vti={selected_asset}",
                "selected_vti_matches_expected=True",
            )
        )

    @staticmethod
    def _format_temporal_probe_operator_ready(
        prepared: _PackageCPreparedOperator,
        *,
        begin_before: int,
        completion_before: int,
    ) -> str:
        """Record the exact Package C bindings immediately before one enable.

        This is deliberately a small, causal receipt: it distinguishes an
        operator that Kit never observed from one that was observed but failed
        during execution, without changing any source or integration input.
        """

        bindings = prepared.binding_evidence
        return "\n".join(
            (
                "DTRS STREAMLINES | TEMPORAL_PROBE | OPERATOR_READY_FOR_EXECUTION",
                f"operator_path={prepared.operator_prim.GetPath()}",
                f"operator_exists={prepared.operator_prim.IsValid()}",
                f"operator_enabled={bindings.operator_enabled}",
                f"source_target={bindings.source_targets}",
                f"seed_target={bindings.seed_targets}",
                f"velocity_target={bindings.velocity_targets}",
                f"tracker_begin_before={begin_before}",
                f"tracker_end_before={completion_before}",
            )
        )

    @staticmethod
    def _format_temporal_probe_sample_record(record: dict[str, object]) -> str:
        """Keep each temporal observation readable without dumping point arrays."""

        sample = record["sample"]
        evidence = record["evidence"]
        receipt = record["receipt"]
        if not isinstance(sample, TemporalProbeSample):
            raise RuntimeError("Temporal probe sample metadata is missing.")
        if not isinstance(evidence, StaticStreamlinesProofEvidence):
            raise RuntimeError("Temporal probe geometry evidence is missing.")
        if not isinstance(receipt, StreamlinesOperatorExecutionReceipt):
            raise RuntimeError("Temporal probe operator receipt is missing.")
        lines = (
            "DTRS STREAMLINES | TEMPORAL_PROBE | "
            f"SAMPLE {sample.ordinal}/{sample.total} | PASS",
            f"sample_index={sample.sample_index}",
            f"source_time_seconds={sample.source_time_seconds:.6g}",
            f"time_code={sample.time_code:.6g}",
            f"source_vti={sample.source_vti}",
            f"selected_vti={record['selected_vti']}",
            "operator_receipt="
            f"begin={receipt.begin_count_before}->{receipt.begin_count_after}; "
            f"end={receipt.completion_count_before}->{receipt.completion_count_after}; "
            f"fresh={receipt.fresh_execution}; success={receipt.completion_success}",
            f"rebuild_ms={record['rebuild_ms']:.0f}",
            f"curve_count={evidence.runtime_curve_count}",
            f"point_count={evidence.runtime_point_count}",
            f"bounds={evidence.runtime_curve_bounds}",
            f"geometry_replaced={record['geometry_replaced']}",
            f"geometry_changed_from_previous={record['geometry_changed']}",
            "viewport_recovery=POST_PREVIEW_UPDATES_COMPLETE",
        )
        return "\n".join(lines)

    @staticmethod
    def _validate_temporal_probe_records(
        source: TemporalVelocitySourceDescriptor,
        records: list[dict[str, object]],
    ) -> None:
        """Require every execution and a non-stale final-to-first loop return."""

        samples = build_temporal_probe_samples(source)
        if len(records) != len(samples):
            raise RuntimeError(
                "Temporal Probe did not produce evidence for every selected sample."
            )
        if not all(record["geometry_replaced"] for record in records):
            raise RuntimeError(
                "Temporal Probe contains an execution without geometry replacement "
                "proof."
            )
        first_signature = records[0]["signature"]
        final_signature = records[-2]["signature"]
        returned_signature = records[-1]["signature"]
        if not isinstance(first_signature, StreamlinesGeometrySignature):
            raise RuntimeError(
                "Temporal Probe initial UsdRT geometry signature is unavailable."
            )
        if not isinstance(final_signature, StreamlinesGeometrySignature):
            raise RuntimeError(
                "Temporal Probe final UsdRT geometry signature is unavailable."
            )
        if not isinstance(returned_signature, StreamlinesGeometrySignature):
            raise RuntimeError(
                "Temporal Probe loop-return UsdRT geometry signature is unavailable."
            )
        if not geometry_signatures_match(first_signature, returned_signature):
            raise RuntimeError(
                "Temporal Probe loop return did not restore the initial first-sample "
                "geometry."
            )

    @staticmethod
    def _format_temporal_probe_success(
        source: TemporalVelocitySourceDescriptor,
        records: list[dict[str, object]],
        cleanup: StaticStreamlinesCleanupReceipt,
    ) -> str:
        """Close Package E with the exact evidence needed before cadence work begins."""

        loop_return = records[-1]
        loop_return_consistent = geometry_signatures_match(
            records[0]["signature"],
            loop_return["signature"],
        )
        fresh_execution_count = sum(record["receipt"].accepted for record in records)
        geometry_replacement_count = sum(
            record["geometry_replaced"] for record in records
        )
        return "\n".join(
            (
                "========================================",
                "DTRS STREAMLINES | TEMPORAL_PROBE | TEST COMPLETE | PASS",
                "========================================",
                "",
                f"workload={source.workload}",
                f"dataset={source.dataset_identity}",
                f"sample_count={source.sample_count}",
                f"source_cadence_hz={source.source_cadence_hz:.6g}",
                "sequence="
                + str(tuple(record["sample"].sample_index for record in records)),
                "",
                f"fresh_executions={fresh_execution_count}/{len(records)}",
                f"geometry_replacements={geometry_replacement_count}/{len(records)}",
                "loop_return_to_first=PASS",
                f"loop_return_geometry_consistent={loop_return_consistent}",
                "FlowEnvironment=ABSENT",
                "DataSetEmitter=ABSENT",
                "SmokeInjectors=ABSENT",
                f"cleanup={'CLEAN' if cleanup.clean else 'DIRTY'}",
                "",
                "Temporal sample switching = PROVEN",
                "Streamlines consumer refresh = EXPLICIT PER SOURCE BOUNDARY",
                "5 Hz presentation feasibility = NOT TESTED",
                "",
                "Package E temporal probe complete.",
                "No further manual action required.",
                "result=PASS",
            )
        )

    async def run_streamlines_static_operator_proof_in_kit(
        self,
        status_callback: StatusCallback | None = None,
    ) -> StreamlinesOperatorProofResult:
        """Create one diagnostic Streamlines consumer from an accepted static source."""

        if self._flow_lifecycle_state != "DETACHED":
            return StreamlinesOperatorProofResult(
                False,
                "Run Streamlines Proof is unavailable while airflow Attach is active.",
            )
        descriptor = self._streamlines_static_source_descriptor
        if descriptor is None:
            return StreamlinesOperatorProofResult(
                False,
                "Run Static Test successfully before creating the Streamlines proof.",
            )
        diagnostics_failure = self.streamlines_static_source_diagnostics_failure()
        if diagnostics_failure:
            return StreamlinesOperatorProofResult(
                False,
                "Static source diagnostics must pass before creating the Streamlines "
                "proof: "
                f"{diagnostics_failure}",
            )

        started_at = time.monotonic()
        carb = None
        try:
            import carb as carb_module

            carb = carb_module
            carb.log_warn(
                with_dtrs_yerevan_timestamp("DTRS STREAMLINES | OPERATOR_PROOF | BEGIN")
            )
            evidence = await self._create_static_streamlines_operator_in_kit(
                descriptor,
                status_callback=status_callback,
            )
        except Exception as error:
            message = f"Streamlines operator proof failed: {error}"
            if carb:
                carb.log_error(
                    with_dtrs_yerevan_timestamp(
                        "DTRS STREAMLINES | OPERATOR_PROOF | FAIL | "
                        f"total_ms={(time.monotonic() - started_at) * 1000.0:.0f} | "
                        f"reason={error}"
                    )
                )
            return StreamlinesOperatorProofResult(False, message)

        if carb:
            carb.log_warn(
                with_dtrs_yerevan_timestamp(
                    "DTRS STREAMLINES | OPERATOR_PROOF | PASS | "
                    f"total_ms={(time.monotonic() - started_at) * 1000.0:.0f}"
                )
            )
        return StreamlinesOperatorProofResult(
            True,
            "Static Streamlines proof ready for viewport inspection.",
            evidence,
        )

    async def run_streamlines_operator_type_comparison_in_kit(
        self,
        status_callback: StatusCallback | None = None,
    ) -> StreamlinesOperatorTypeComparisonRunResult:
        """Measure two Kit-CAE types from one unchanged Package A/B input contract."""

        if self._flow_lifecycle_state != "DETACHED":
            return StreamlinesOperatorTypeComparisonRunResult(
                False,
                "Type comparison is unavailable while airflow Attach is active.",
            )
        descriptor = self._streamlines_static_source_descriptor
        if descriptor is None:
            return StreamlinesOperatorTypeComparisonRunResult(
                False,
                "Run Static Test successfully before comparing Streamlines types.",
            )
        diagnostics_failure = self.streamlines_static_source_diagnostics_failure()
        if diagnostics_failure:
            return StreamlinesOperatorTypeComparisonRunResult(
                False,
                "Static source diagnostics must pass before comparing Streamlines "
                "types: "
                f"{diagnostics_failure}",
            )

        started_at = time.monotonic()
        carb = None
        self._streamlines_operator_type_comparison = None
        try:
            import carb as carb_module

            carb = carb_module
            carb.log_warn(
                with_dtrs_yerevan_timestamp(
                    "DTRS STREAMLINES | OPERATOR_TYPE_COMPARISON | BEGIN"
                )
            )
            comparison = await self._compare_streamlines_operator_types_in_kit(
                descriptor,
                status_callback=status_callback,
            )
        except Exception as error:
            message = f"Streamlines type comparison failed: {error}"
            if carb:
                carb.log_error(
                    with_dtrs_yerevan_timestamp(
                        "DTRS STREAMLINES | OPERATOR_TYPE_COMPARISON | FAIL | "
                        f"total_ms={(time.monotonic() - started_at) * 1000.0:.0f} | "
                        f"reason={error}"
                    )
                )
            return StreamlinesOperatorTypeComparisonRunResult(False, message)

        logger = carb.log_warn if comparison.success else carb.log_error
        logger(
            with_dtrs_yerevan_timestamp(
                format_streamlines_operator_type_comparison(
                    descriptor,
                    build_streamlines_operator_type_comparison_cases(descriptor),
                    comparison,
                )
            )
        )
        state = "PASS" if comparison.success else "FAIL"
        logger(
            with_dtrs_yerevan_timestamp(
                "DTRS STREAMLINES | OPERATOR_TYPE_COMPARISON | "
                f"{state} | total_ms={(time.monotonic() - started_at) * 1000.0:.0f}"
            )
        )
        if comparison.success:
            self._streamlines_operator_type_comparison = comparison
            logger(
                with_dtrs_yerevan_timestamp(
                    'DTRS STREAMLINES | NEXT_ACTION | Press "Show Standard"'
                )
            )
        return StreamlinesOperatorTypeComparisonRunResult(
            comparison.success,
            (
                'Benchmark complete. Press "Show Standard".'
                if comparison.success
                else comparison.message
            ),
            comparison,
        )

    async def show_streamlines_operator_type_comparison_result_in_kit(
        self,
        operator_type: str,
    ) -> StreamlinesOperatorTypeComparisonRunResult:
        """Show one retained Package C preview without changing camera or inputs."""

        if operator_type not in OPERATOR_TYPES:
            return StreamlinesOperatorTypeComparisonRunResult(
                False,
                f"Unsupported Streamlines operator type: {operator_type}.",
            )
        if self._flow_lifecycle_state != "DETACHED":
            return StreamlinesOperatorTypeComparisonRunResult(
                False,
                "Comparison review is unavailable while airflow Attach is active.",
            )
        descriptor = self._streamlines_static_source_descriptor
        if descriptor is None:
            return StreamlinesOperatorTypeComparisonRunResult(
                False,
                "Run Static Test and the operator benchmark before selecting a "
                "preview.",
            )
        comparison = self._streamlines_operator_type_comparison
        if comparison is None or not comparison.success:
            return StreamlinesOperatorTypeComparisonRunResult(
                False,
                "Run the Standard vs NanoVDB benchmark before selecting a preview.",
            )

        import carb
        import omni.kit.app
        import omni.usd
        from pxr import UsdGeom

        stage = omni.usd.get_context().get_stage()
        if not stage:
            return StreamlinesOperatorTypeComparisonRunResult(
                False,
                "Comparison review requires an open stage.",
            )
        cases = build_streamlines_operator_type_comparison_cases(descriptor)
        selected = next(case for case in cases if case.operator_type == operator_type)
        if not stage.GetPrimAtPath(selected.preview_path).IsValid():
            return StreamlinesOperatorTypeComparisonRunResult(
                False,
                "Run the Standard vs NanoVDB benchmark before selecting a preview.",
            )

        previous_target = stage.GetEditTarget()
        try:
            stage.SetEditTarget(stage.GetSessionLayer())
            for case in cases:
                preview_prim = stage.GetPrimAtPath(case.preview_path)
                if preview_prim.IsValid():
                    UsdGeom.Imageable(preview_prim).CreateVisibilityAttr().Set(
                        UsdGeom.Tokens.inherited
                        if case.operator_type == operator_type
                        else UsdGeom.Tokens.invisible
                    )
            seed_prim = stage.GetPrimAtPath(COMPARISON_SHARED_SEED_PATH)
            if seed_prim.IsValid():
                UsdGeom.Imageable(seed_prim).CreateVisibilityAttr().Set(
                    UsdGeom.Tokens.inherited
                )
        finally:
            stage.SetEditTarget(previous_target)
        await omni.kit.app.get_app().next_update_async()
        carb.log_warn(
            with_dtrs_yerevan_timestamp(
                format_streamlines_visual_review(comparison, operator_type)
            )
        )
        return StreamlinesOperatorTypeComparisonRunResult(
            True,
            (
                'Standard preview active. Inspect viewport, then press "Show NanoVDB".'
                if operator_type == "standard"
                else "NanoVDB preview active. Visual review complete; no further "
                "application action is required."
            ),
            comparison,
        )

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
        field_path = f"{self.STATIC_IMPORT_ROOT}/PointData/{sample.velocity_field_name}"
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
                    f"duration_ms={(time.monotonic() - import_started_at) * 1000.0:.0f}"
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
                        "Package A static source detected forbidden runtime state; "
                        "review the DTRS STREAMLINES acceptance block."
                    )
            self._streamlines_static_source_descriptor = descriptor
            if force_failure_after_import:
                raise RuntimeError(
                    "Package D forced static-source failure after import."
                )
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

    async def _create_static_streamlines_operator_in_kit(
        self,
        descriptor: StaticVelocitySourceDescriptor,
        *,
        status_callback: StatusCallback | None,
    ) -> StaticStreamlinesProofEvidence:
        """Author, bind, and observe one standard Streamlines operator.

        The existing Stage 6 observer already tracks every DTRS Kit-CAE operator
        by path. Package B reuses that tested synchronization seam without
        changing its Flow-owned name; Phase 3 can make the ownership neutral if
        the shared source architecture justifies the refactor.
        """

        import carb
        import omni.kit.app
        import omni.timeline
        import omni.usd
        import warp as wp
        from omni.cae.data import usd_utils as cae_usd_utils
        from omni.cae.data.commands import execute_command
        from omni.cae.schema import viz as cae_viz
        from omni.cae.schema import vtk as cae_vtk
        from pxr import Sdf, UsdGeom
        from usdrt import UsdGeom as UsdGeomRT

        app = omni.kit.app.get_app()
        extension_manager = app.get_extension_manager()
        if not extension_manager.is_extension_enabled("omni.cae.viz"):
            raise RuntimeError(
                "Kit-CAE Streamlines is unavailable; start DTRS with omni.cae.viz "
                "enabled."
            )
        stage = omni.usd.get_context().get_stage()
        if not stage:
            raise RuntimeError("Streamlines proof requires an open stage.")
        dataset_prim = stage.GetPrimAtPath(descriptor.dataset_prim_path)
        field_prim = stage.GetPrimAtPath(descriptor.velocity_field_prim_path)
        request = validate_static_streamlines_source(
            descriptor,
            dataset_available=bool(dataset_prim and dataset_prim.IsValid()),
            velocity_field_available=bool(field_prim and field_prim.IsValid()),
        )
        cleanup = clear_static_streamlines_proof_from_stage(stage)
        if not cleanup.success:
            raise RuntimeError(
                "Previous Streamlines proof cleanup did not remove its runtime roots."
            )
        await app.next_update_async()

        previous_target = stage.GetEditTarget()
        stage.SetEditTarget(stage.GetSessionLayer())
        self._start_kit_cae_operator_tracking()
        try:
            if status_callback:
                status_callback("Creating diagnostic Streamlines operator…")
            await execute_command(
                "CreateCaeVizStreamlines",
                dataset_path=request.dataset_prim_path,
                prim_path=request.operator_path,
                type=request.operator_type,
            )
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
            operator_prim = stage.GetPrimAtPath(request.operator_path)
            if not operator_prim or not operator_prim.IsValid():
                raise RuntimeError(
                    "CreateCaeVizStreamlines did not author its BasisCurves prim."
                )
            operator_api = cae_viz.OperatorAPI(operator_prim)
            # The command enables its operator immediately.  Hold it inactive
            # while its diagnostic seed and vector-field bindings are authored
            # so the first observed execution cannot consume incomplete input.
            operator_api.CreateEnabledAttr().Set(False)
            # Match the Kit-CAE Streamlines test: let the transformed UnitSphere
            # reach Fabric before its relationship is used as a seed dataset.
            # This is authoring synchronization, not an integration-time tune.
            await app.next_update_async()
            # This value is intentionally captured before the final bindings.
            # Package B accepts output only when enabling the fully configured
            # operator produces a later end event.
            completion_before = self._kit_cae_operator_completion_count(
                request.operator_path
            )
            streamlines_api = cae_viz.StreamlinesAPI(operator_prim)
            streamlines_api.GetDirectionAttr().Set(
                getattr(cae_viz.Tokens, request.direction)
            )
            streamlines_api.GetMinStepSizeAttr().Set(request.min_step_size)
            streamlines_api.GetInitialStepSizeAttr().Set(request.initial_step_size)
            streamlines_api.GetMaxStepSizeAttr().Set(request.max_step_size)
            streamlines_api.GetMaxStepsAttr().Set(request.max_steps)
            streamlines_api.GetWidthAttr().Set(request.width)
            # The creation command starts with a visible 0.025-unit placeholder.
            # Mirror the diagnostic width to that primvar so a pending or failed
            # operator cannot be mistaken for the intended thin streamline.
            widths_primvar = UsdGeom.PrimvarsAPI(operator_prim).GetPrimvar("widths")
            if widths_primvar and widths_primvar.IsDefined():
                widths_primvar.Set([request.width] * 4)
            cae_viz.DatasetSelectionAPI(
                operator_prim, "source"
            ).GetTargetRel().SetTargets([request.dataset_prim_path])
            cae_viz.DatasetSelectionAPI(
                operator_prim, "seeds"
            ).GetTargetRel().SetTargets([request.seed_path])
            velocity_selection = cae_viz.FieldSelectionAPI(operator_prim, "velocities")
            velocity_selection.GetTargetRel().SetTargets(
                [request.velocity_field_prim_path]
            )
            # Streamlines consumes the Houdini ``vel`` vector directly.  The
            # Kit command uses ``unchanged`` explicitly; a scalar transform
            # here would make the integrator's input contract invalid.
            velocity_selection.CreateModeAttr().Set(cae_viz.Tokens.unchanged)
            binding_evidence = inspect_static_streamlines_bindings(
                stage,
                operator_prim=operator_prim,
                dataset_prim=dataset_prim,
                cae_viz=cae_viz,
                cae_usd_utils=cae_usd_utils,
            )
            carb.log_warn(
                with_dtrs_yerevan_timestamp(
                    format_static_streamlines_binding_evidence(binding_evidence)
                )
            )
            operator_api.CreateEnabledAttr().Set(True)
            completion_count, fresh_execution = (
                await self._await_static_streamlines_geometry(
                    app,
                    request,
                    completion_before=completion_before,
                )
            )
            evidence = inspect_static_streamlines_proof(
                stage,
                request=request,
                field_prim=field_prim,
                cae_viz=cae_viz,
                cae_vtk=cae_vtk,
                cae_usd_utils=cae_usd_utils,
                UsdGeom=UsdGeom,
                UsdGeomRT=UsdGeomRT,
                wp=wp,
                timeline=omni.timeline.get_timeline_interface(),
                operator_completion_count_before=completion_before,
                operator_completion_count=completion_count,
                fresh_execution=fresh_execution,
                operator_execution_success=(
                    self._kit_cae_operator_last_completion_success(
                        request.operator_path
                    )
                    if fresh_execution
                    else None
                ),
                source_world_bounds=descriptor.world_bounds,
            )
            evidence = _author_static_streamlines_runtime_preview(
                stage,
                operator_prim=operator_prim,
                evidence=evidence,
                UsdGeom=UsdGeom,
                UsdGeomRT=UsdGeomRT,
                cae_usd_utils=cae_usd_utils,
                Sdf=Sdf,
            )
            await app.next_update_async()
            # Emit the complete evidence before enforcing it: a spatially wrong
            # result must be diagnosable without manually inspecting the USD tree.
            carb.log_warn(
                with_dtrs_yerevan_timestamp(
                    format_static_streamlines_proof_acceptance(
                        descriptor,
                        request,
                        cleanup,
                        evidence,
                    )
                )
            )
            if not evidence.fresh_execution:
                raise RuntimeError(
                    "Streamlines operator did not produce a fresh execution after "
                    f"enable (before={completion_before}, after={completion_count})."
                )
            if evidence.operator_execution_success is not True:
                raise RuntimeError(
                    "Streamlines operator reached operator_end without successful "
                    "geometry generation; inspect the Package B acceptance block."
                )
            validate_generated_streamlines_geometry(
                evidence.runtime_curve_count,
                evidence.runtime_point_count,
                point_positions=evidence.runtime_point_positions,
                curve_vertex_counts=evidence.runtime_curve_vertex_counts,
            )
            if not evidence.is_valid_for(request):
                raise RuntimeError(
                    "Streamlines proof did not satisfy its binding, geometry, or "
                    "no-Flow contract."
                )
            curve_count = evidence.runtime_curve_count
            point_count = evidence.runtime_point_count
        except Exception:
            clear_static_streamlines_proof_from_stage(stage)
            raise
        finally:
            stage.SetEditTarget(previous_target)
            self._stop_kit_cae_operator_tracking()

        if status_callback:
            status_callback(
                f"Streamlines proof ready · {curve_count} curves · {point_count} points"
            )
        return evidence

    async def _await_static_streamlines_geometry(
        self,
        app,
        request: StaticStreamlinesProofRequest,
        *,
        completion_before: int,
    ) -> tuple[int, bool]:
        """Wait for a post-enable completion before inspecting UsdRT geometry."""

        deadline = time.monotonic() + self.STATIC_OPERATOR_PROOF_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            await app.next_update_async()
            completion_count = self._kit_cae_operator_completion_count(
                request.operator_path
            )
            if completion_count > completion_before:
                return completion_count, True
        return (
            self._kit_cae_operator_completion_count(request.operator_path),
            False,
        )

    async def _compare_streamlines_operator_types_in_kit(
        self,
        descriptor: StaticVelocitySourceDescriptor,
        *,
        status_callback: StatusCallback | None,
    ) -> StreamlinesOperatorTypeComparisonResult:
        """Run both Package C types sequentially against one unchanged static source.

        The dedicated comparison roots keep this experiment independent from
        Package B's visible FSD-safe preview.  Each case is disabled after its
        measurement so only one Kit-CAE operator can consume GPU work at once.
        """

        return await self._run_package_c_operator_benchmark_in_kit(
            descriptor,
            status_callback=status_callback,
        )

    @staticmethod
    def _streamlines_integration_settings(
        streamlines_api,
    ) -> tuple[tuple[str, str], ...]:
        """Capture the request-independent settings shared by both Package C cases."""

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
        """Record the fixed source-faithful handling used by each Package C type."""

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

    async def _run_package_c_operator_benchmark_in_kit(
        self,
        descriptor: StaticVelocitySourceDescriptor,
        *,
        status_callback: StatusCallback | None,
    ) -> StreamlinesOperatorTypeComparisonResult:
        """Run the retained Package C benchmark without changing Package B inputs.

        The completed operators are disabled before return. Their FSD-safe
        previews are static mirrors of the final measured UsdRT result. They
        remain hidden until the reviewer explicitly selects Standard, so the
        benchmark and human A/B steps cannot be confused.
        """

        import carb
        import omni.kit.app
        import omni.timeline
        import omni.usd
        import warp as wp
        from omni.cae.data import usd_utils as cae_usd_utils
        from omni.cae.data.commands import execute_command
        from omni.cae.schema import viz as cae_viz
        from omni.cae.schema import vtk as cae_vtk
        from pxr import Sdf, UsdGeom
        from usdrt import UsdGeom as UsdGeomRT

        if carb.settings.get_settings().get_as_bool("/app/useFabricSceneDelegate"):
            raise RuntimeError(
                "Package C requires FSD=false for the accepted X-Ray baseline."
            )
        app = omni.kit.app.get_app()
        stage = omni.usd.get_context().get_stage()
        if not stage:
            raise RuntimeError("Streamlines type comparison requires an open stage.")
        cases = build_streamlines_operator_type_comparison_cases(descriptor)
        if not comparison_cases_share_non_type_inputs(cases):
            raise RuntimeError(
                "Package C comparison requests do not share one input contract."
            )
        dataset_prim = stage.GetPrimAtPath(descriptor.dataset_prim_path)
        field_prim = stage.GetPrimAtPath(descriptor.velocity_field_prim_path)
        if not dataset_prim or not dataset_prim.IsValid():
            raise RuntimeError(
                "Accepted static dataset is unavailable for type comparison."
            )
        if not field_prim or not field_prim.IsValid():
            raise RuntimeError(
                "Accepted static velocity field is unavailable for type comparison."
            )
        previous_cleanup_success = (
            clear_streamlines_operator_type_comparison_from_stage(stage)
        )
        if not previous_cleanup_success:
            raise RuntimeError(
                "Previous Streamlines type comparison cleanup did not remove its roots."
            )
        await app.next_update_async()

        previous_target = stage.GetEditTarget()
        results: list[StreamlinesOperatorTypeComparisonCaseResult] = []
        try:
            stage.SetEditTarget(stage.GetSessionLayer())
            self._set_package_c_authored_visibility(
                stage,
                paths=(
                    STATIC_PROOF_OPERATOR_PATH,
                    STATIC_PROOF_RUNTIME_PREVIEW_PATH,
                    STATIC_PROOF_SEED_PATH,
                ),
                visibility=UsdGeom.Tokens.invisible,
                UsdGeom=UsdGeom,
            )
            base_request = cases[0].request
            await execute_command(
                "CreateCaeVizMeshPrim",
                prim_type="UnitSphere",
                prim_path=COMPARISON_SHARED_SEED_PATH,
            )
            await execute_command(
                "TransformPrimSRT",
                path=COMPARISON_SHARED_SEED_PATH,
                new_translation=list(base_request.seed_center),
                new_scale=[base_request.seed_radius] * 3,
            )
            await app.next_update_async()

            self._start_kit_cae_operator_tracking()
            try:
                for case in cases:
                    if status_callback:
                        status_callback(
                            f"Benchmarking {case.operator_type}: "
                            f"{WARMUP_RUN_COUNT} warm-up + "
                            f"{MEASURED_RUN_COUNT} measured runs."
                        )
                    results.append(
                        await self._run_package_c_benchmark_case_in_kit(
                            stage,
                            app=app,
                            case=case,
                            comparison_preview_paths=tuple(
                                item.preview_path for item in cases
                            ),
                            descriptor=descriptor,
                            dataset_prim=dataset_prim,
                            field_prim=field_prim,
                            cae_usd_utils=cae_usd_utils,
                            cae_viz=cae_viz,
                            cae_vtk=cae_vtk,
                            UsdGeom=UsdGeom,
                            UsdGeomRT=UsdGeomRT,
                            Sdf=Sdf,
                            wp=wp,
                            timeline=omni.timeline.get_timeline_interface(),
                            execute_command=execute_command,
                        )
                    )
            finally:
                self._stop_kit_cae_operator_tracking()
        finally:
            stage.SetEditTarget(previous_target)

        standard, nanovdb = results
        result = StreamlinesOperatorTypeComparisonResult(
            standard=standard,
            nanovdb=nanovdb,
            identical_non_type_inputs=comparison_cases_share_non_type_inputs(cases),
            previous_comparison_cleanup_success=previous_cleanup_success,
            active_review_type="none",
        )
        if result.success:
            previous_target = stage.GetEditTarget()
            try:
                stage.SetEditTarget(stage.GetSessionLayer())
                self._set_package_c_authored_visibility(
                    stage,
                    paths=tuple(case.preview_path for case in cases)
                    + (COMPARISON_SHARED_SEED_PATH,),
                    visibility=UsdGeom.Tokens.invisible,
                    UsdGeom=UsdGeom,
                )
            finally:
                stage.SetEditTarget(previous_target)
            await app.next_update_async()
        return result

    async def _prepare_package_c_operator_in_kit(
        self,
        stage,
        *,
        app,
        request: StaticStreamlinesProofRequest,
        descriptor: StaticVelocitySourceDescriptor,
        dataset_prim,
        cae_usd_utils,
        cae_viz,
        UsdGeom,
        execute_command,
    ) -> _PackageCPreparedOperator:
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
        velocity_selection.GetTargetRel().SetTargets([request.velocity_field_prim_path])
        velocity_selection.CreateModeAttr().Set(cae_viz.Tokens.unchanged)
        nanovdb_effective_grid = None
        if request.operator_type == "nanovdb":
            nanovdb_effective_grid = self._configure_package_c_nanovdb_fidelity(
                operator_prim,
                descriptor=descriptor,
                cae_viz=cae_viz,
            )
            if not nanovdb_effective_grid.preserves_source_fidelity:
                raise RuntimeError(
                    "NanoVDB effective voxel size is coarser than the source VTI "
                    "spacing."
                )
        binding_evidence = inspect_static_streamlines_bindings(
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
        self._validate_package_c_bindings(
            request,
            binding_evidence=binding_evidence,
            source_processing_mode=source_processing_mode,
        )
        return _PackageCPreparedOperator(
            creation_duration_ms=creation_duration_ms,
            operator_prim=operator_prim,
            operator_api=operator_api,
            binding_evidence=binding_evidence,
            integration_settings=integration_settings,
            source_processing_mode=source_processing_mode,
            voxelization_settings=voxelization_settings,
            nanovdb_effective_grid=nanovdb_effective_grid,
        )

    async def _cleanup_package_c_operator_in_kit(
        self,
        stage,
        *,
        app,
        prepared: _PackageCPreparedOperator,
        UsdGeom,
    ) -> bool:
        """Remove one completed harness operator before the next measured run.

        Kit-CAE intentionally skips unchanged enabled operators.  The benchmark
        therefore owns and replaces this disposable consumer each time, while
        preserving the shared VTI source, seed, and integration contract.
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

    async def _run_package_c_benchmark_case_in_kit(
        self,
        stage,
        *,
        app,
        case: StreamlinesOperatorTypeComparisonCase,
        comparison_preview_paths: tuple[str, ...],
        descriptor: StaticVelocitySourceDescriptor,
        dataset_prim,
        field_prim,
        cae_usd_utils,
        cae_viz,
        cae_vtk,
        UsdGeom,
        UsdGeomRT,
        Sdf,
        wp,
        timeline,
        execute_command,
    ) -> StreamlinesOperatorTypeComparisonCaseResult:
        """Measure one unchanged type exactly once warm and three visible times."""

        request = case.request
        creation_duration_ms = None
        warmup_rebuild_ms = None
        warmup_succeeded = False
        warmup_receipt = None
        measured_samples: list[StreamlinesOperatorTypeBenchmarkSample] = []
        binding_evidence = None
        integration_settings: tuple[tuple[str, str], ...] = ()
        source_processing_mode = "UNAVAILABLE"
        voxelization_settings: tuple[tuple[str, str], ...] = ()
        nanovdb_effective_grid = None
        last_evidence = None
        steady_performance = None
        reason = None
        try:
            self._set_package_c_authored_visibility(
                stage,
                paths=comparison_preview_paths,
                visibility=UsdGeom.Tokens.invisible,
                UsdGeom=UsdGeom,
            )
            await app.next_update_async()

            # CUDA compilation/allocation belongs to warm-up, not the median.
            warmup = await self._run_package_c_fresh_operator_execution(
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
            creation_duration_ms = warmup.prepared.creation_duration_ms
            warmup_rebuild_ms = warmup.rebuild_ms
            warmup_receipt = warmup.execution_receipt
            warmup_succeeded = True
            binding_evidence = warmup.prepared.binding_evidence
            integration_settings = warmup.prepared.integration_settings
            source_processing_mode = warmup.prepared.source_processing_mode
            voxelization_settings = warmup.prepared.voxelization_settings
            nanovdb_effective_grid = warmup.prepared.nanovdb_effective_grid
            last_evidence = warmup.evidence

            for _ in range(MEASURED_RUN_COUNT):
                visible_update_started_at = time.monotonic()
                execution = await self._run_package_c_fresh_operator_execution(
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
                    preview_path=case.preview_path,
                    Sdf=Sdf,
                )
                self._validate_package_c_prepared_operator(
                    warmup.prepared,
                    execution.prepared,
                )
                await self._await_package_c_preview_quiescence(app)
                measured_samples.append(
                    StreamlinesOperatorTypeBenchmarkSample(
                        operator_creation_ms=execution.prepared.creation_duration_ms,
                        operator_rebuild_ms=execution.rebuild_ms,
                        preview_mirror_ms=execution.preview_mirror_ms,
                        total_visible_update_ms=(
                            time.monotonic() - visible_update_started_at
                        )
                        * 1000.0,
                        runtime_curve_count=execution.evidence.runtime_curve_count,
                        runtime_point_count=execution.evidence.runtime_point_count,
                        points_per_curve_min_mean_max=(
                            self._package_c_points_per_curve_summary(
                                execution.evidence.runtime_curve_vertex_counts
                            )
                        ),
                        runtime_bounds=execution.evidence.runtime_curve_bounds,
                        bounds_within_source=(
                            execution.evidence.runtime_curve_bounds_within_source
                        ),
                        execution_receipt=execution.execution_receipt,
                    )
                )
                last_evidence = execution.evidence

            # Flow's established HUD snapshot source remains authoritative here.
            # Sampling every five seconds avoids treating cached adjacent frames
            # as a steady-FPS series while the final review preview stays visible.
            steady_performance = await self._capture_package_c_steady_performance()
            passed = self._package_c_case_is_valid(
                request,
                binding_evidence=binding_evidence,
                warmup_succeeded=warmup_succeeded,
                warmup_receipt=warmup_receipt,
                measured_samples=tuple(measured_samples),
                source_processing_mode=source_processing_mode,
                nanovdb_effective_grid=nanovdb_effective_grid,
                last_evidence=last_evidence,
                steady_performance=steady_performance,
            )
            reason = (
                None
                if passed
                else (
                    "Runtime output or fixed Package C comparison contract was not "
                    "accepted."
                )
            )
        except Exception as error:
            passed = False
            reason = str(error)

        return StreamlinesOperatorTypeComparisonCaseResult(
            operator_type=request.operator_type,
            operator_path=request.operator_path,
            preview_path=case.preview_path,
            creation_duration_ms=creation_duration_ms,
            warmup_rebuild_ms=warmup_rebuild_ms,
            warmup_succeeded=warmup_succeeded,
            warmup_receipt=warmup_receipt,
            measured_samples=tuple(measured_samples),
            steady_performance=steady_performance,
            source_binding=(
                binding_evidence.source_targets if binding_evidence else ()
            ),
            seed_binding=(binding_evidence.seed_targets if binding_evidence else ()),
            velocity_binding=(
                binding_evidence.velocity_targets if binding_evidence else ()
            ),
            integration_settings=integration_settings,
            source_processing_mode=source_processing_mode,
            nanovdb_voxelization_ms=None,
            voxelization_settings=voxelization_settings,
            nanovdb_effective_grid=nanovdb_effective_grid,
            warnings_errors=(
                "NONE_OBSERVED_BY_DTRS" if reason is None else f"DTRS_ERROR: {reason}"
            ),
            passed=passed,
            reason=reason,
        )

    async def _run_package_c_fresh_operator_execution(
        self,
        stage,
        *,
        app,
        request: StaticStreamlinesProofRequest,
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
    ) -> _PackageCOperatorExecution:
        """Run one clean operator lifetime, optionally leaving its static preview.

        The operator is a benchmark harness artifact, not a new source or
        presentation mode.  It is removed before viewport sampling so that the
        sampler sees exactly one authored RuntimePreview and no live Kit work.
        """

        prepared = None
        execution = None
        cleanup_success = False
        try:
            prepared = await self._prepare_package_c_operator_in_kit(
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
                await self._execute_package_c_operator_run(
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
            execution = _PackageCOperatorExecution(
                prepared=prepared,
                rebuild_ms=rebuild_ms,
                evidence=evidence,
                execution_receipt=execution_receipt,
                preview_mirror_ms=preview_mirror_ms,
            )
        finally:
            if prepared is not None:
                cleanup_success = await self._cleanup_package_c_operator_in_kit(
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
                "Package C did not remove its completed benchmark operator."
            )
        if execution is None:
            raise RuntimeError(
                "Package C operator execution produced no benchmark result."
            )
        return execution

    @staticmethod
    def _validate_package_c_prepared_operator(
        reference: _PackageCPreparedOperator,
        candidate: _PackageCPreparedOperator,
    ) -> None:
        """Prove recreation changed no semantic input or NanoVDB fidelity setting."""

        if (
            candidate.binding_evidence.source_targets
            != reference.binding_evidence.source_targets
            or candidate.binding_evidence.seed_targets
            != reference.binding_evidence.seed_targets
            or candidate.binding_evidence.velocity_targets
            != reference.binding_evidence.velocity_targets
            or candidate.integration_settings != reference.integration_settings
            or candidate.source_processing_mode != reference.source_processing_mode
            or candidate.voxelization_settings != reference.voxelization_settings
            or candidate.nanovdb_effective_grid != reference.nanovdb_effective_grid
        ):
            raise RuntimeError(
                "Recreated Package C operator diverged from the shared comparison "
                "contract."
            )

    async def _execute_package_c_operator_run(
        self,
        stage,
        *,
        app,
        request: StaticStreamlinesProofRequest,
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
        StaticStreamlinesProofEvidence,
        StreamlinesOperatorExecutionReceipt,
    ]:
        """Require this run's own successful Kit receipt before reading UsdRT."""

        begin_before = self._kit_cae_operator_begin_count(request.operator_path)
        completion_before = self._kit_cae_operator_completion_count(
            request.operator_path
        )
        rebuild_started_at = time.monotonic()
        operator_api.CreateEnabledAttr().Set(True)
        execution_receipt = await self._await_package_c_execution_receipt(
            app,
            request,
            begin_before=begin_before,
            completion_before=completion_before,
        )
        rebuild_ms = (time.monotonic() - rebuild_started_at) * 1000.0
        evidence = inspect_static_streamlines_proof(
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
                f"end={completion_before}->{execution_receipt.completion_count_after}; "
                f"end_begin={execution_receipt.completion_begin_count}; "
                f"success={execution_receipt.completion_success})."
            )
        if not evidence.runtime_curve_bounds_within_source:
            raise RuntimeError(
                "Generated Streamlines bounds are outside the accepted source domain."
            )
        return rebuild_ms, evidence, execution_receipt

    async def _await_package_c_execution_receipt(
        self,
        app,
        request: StaticStreamlinesProofRequest,
        *,
        begin_before: int,
        completion_before: int,
    ) -> StreamlinesOperatorExecutionReceipt:
        """Wait for the post-enable end paired with a new Kit begin generation.

        `operator_end` is asynchronous.  Merely reading its last success bit
        can attribute a later or earlier event to the benchmark run, so Package
        C requires a begin count and an end count that Kit paired together.
        """

        deadline = time.monotonic() + self.STATIC_OPERATOR_PROOF_TIMEOUT_SECONDS
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

    @staticmethod
    def _configure_package_c_nanovdb_fidelity(
        operator_prim,
        *,
        descriptor: StaticVelocitySourceDescriptor,
        cae_viz,
    ):
        """Set one source-faithful NanoVDB grid before timing its challenger path."""

        voxelization_api = cae_viz.DatasetVoxelizationAPI(operator_prim, "source")
        voxelization_api.GetVoxelSizeModeAttr().Set(cae_viz.Tokens.maxResolution)
        voxelization_api.GetMaxResolutionAttr().Set(NANOVDB_MAX_RESOLUTION)
        voxelization_api.GetFieldCenteringAttr().Set(cae_viz.Tokens.point)
        voxelization_api.GetInflateBoundsAttr().Set(0.0)
        return calculate_nanovdb_effective_grid(
            descriptor.world_bounds,
            descriptor.spacing,
            max_resolution=NANOVDB_MAX_RESOLUTION,
        )

    @staticmethod
    async def _await_package_c_preview_quiescence(app) -> None:
        """Preserve visible-update timing without treating adjacent frames as FPS
        samples."""

        for _ in range(PACKAGE_C_TOTAL_VISIBLE_UPDATE_SETTLE_COUNT):
            await app.next_update_async()

    @staticmethod
    async def _capture_package_c_steady_performance():
        """Sample the Flow HUD source after each final visible preview has recovered."""

        await asyncio.sleep(PACKAGE_C_STEADY_SNAPSHOT_INITIAL_DELAY_SECONDS)
        samples = []
        for index in range(PACKAGE_C_STEADY_SNAPSHOT_COUNT):
            samples.append(capture_viewport_performance_sample())
            if index < PACKAGE_C_STEADY_SNAPSHOT_COUNT - 1:
                await asyncio.sleep(PACKAGE_C_STEADY_SNAPSHOT_INTERVAL_SECONDS)
        return build_streamlines_steady_performance_evidence(samples)

    @staticmethod
    def _package_c_points_per_curve_summary(
        curve_vertex_counts: tuple[int, ...],
    ) -> tuple[int, int | float, int] | None:
        """Summarize many equal-length curves without dumping a 256-item array."""

        if not curve_vertex_counts:
            return None
        mean = sum(curve_vertex_counts) / len(curve_vertex_counts)
        return (
            min(curve_vertex_counts),
            int(mean) if mean.is_integer() else mean,
            max(curve_vertex_counts),
        )

    @staticmethod
    def _set_package_c_authored_visibility(
        stage, *, paths, visibility, UsdGeom
    ) -> None:
        """Exclude Package B visual bridges from the controlled Package C viewport."""

        for path in paths:
            prim = stage.GetPrimAtPath(path)
            if prim.IsValid():
                UsdGeom.Imageable(prim).CreateVisibilityAttr().Set(visibility)

    @staticmethod
    def _validate_package_c_bindings(
        request: StaticStreamlinesProofRequest,
        *,
        binding_evidence,
        source_processing_mode: str,
    ) -> None:
        """Fail before timing if anything except the selected operator type changed."""

        expected_mode = "subset" if request.operator_type == "standard" else "voxelized"
        if (
            binding_evidence.source_targets != (request.dataset_prim_path,)
            or binding_evidence.seed_targets != (request.seed_path,)
            or binding_evidence.velocity_targets != (request.velocity_field_prim_path,)
            or source_processing_mode != expected_mode
        ):
            raise RuntimeError(
                "Streamlines comparison binding or type contract was not accepted."
            )

    @staticmethod
    def _package_c_case_is_valid(
        request: StaticStreamlinesProofRequest,
        *,
        binding_evidence,
        warmup_succeeded: bool,
        warmup_receipt: StreamlinesOperatorExecutionReceipt | None,
        measured_samples: tuple[StreamlinesOperatorTypeBenchmarkSample, ...],
        source_processing_mode: str,
        nanovdb_effective_grid,
        last_evidence: StaticStreamlinesProofEvidence | None,
        steady_performance,
    ) -> bool:
        """Accept only three real UsdRT observations from the fixed Package C setup."""

        expected_mode = "subset" if request.operator_type == "standard" else "voxelized"
        return (
            binding_evidence.source_targets == (request.dataset_prim_path,)
            and binding_evidence.seed_targets == (request.seed_path,)
            and binding_evidence.velocity_targets == (request.velocity_field_prim_path,)
            and warmup_succeeded
            and warmup_receipt is not None
            and warmup_receipt.accepted
            and len(measured_samples) == MEASURED_RUN_COUNT
            and all(
                sample.execution_receipt.accepted
                and sample.operator_creation_ms is not None
                and sample.operator_rebuild_ms is not None
                and sample.preview_mirror_ms is not None
                and sample.runtime_curve_count > 0
                and sample.runtime_point_count > 4
                and sample.bounds_within_source
                for sample in measured_samples
            )
            and steady_performance is not None
            and steady_performance.has_complete_fps_series
            and source_processing_mode == expected_mode
            and (
                request.operator_type != "nanovdb"
                or (
                    nanovdb_effective_grid is not None
                    and nanovdb_effective_grid.preserves_source_fidelity
                )
            )
            and last_evidence is not None
            and last_evidence.flow_environment == "ABSENT"
            and last_evidence.dataset_emitter == "ABSENT"
            and last_evidence.boundary_emitter == "ABSENT"
            and last_evidence.smoke_injectors == "ABSENT"
            and last_evidence.temporal_sequence == "ABSENT"
            and last_evidence.timeline_playback == "INACTIVE"
        )
