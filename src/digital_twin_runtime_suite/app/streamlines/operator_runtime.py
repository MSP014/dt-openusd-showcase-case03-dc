"""Standard Kit-CAE Streamlines execution and confirmed UsdRT receipt mechanics."""

from __future__ import annotations

import time
from dataclasses import dataclass

from digital_twin_runtime_suite.app.flow.static_source import (
    StaticVelocitySourceDescriptor,
)
from digital_twin_runtime_suite.app.streamlines.diagnostics import (
    StreamlinesOperatorEvidence,
    inspect_streamlines_bindings,
    inspect_streamlines_operator,
)
from digital_twin_runtime_suite.app.streamlines.proof import (
    StreamlinesOperatorRequest,
    validate_generated_streamlines_geometry,
)
from digital_twin_runtime_suite.app.streamlines.speed import (
    speed_magnitudes_from_velocity_vectors,
)


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
    locked_source_time_code: float | None


@dataclass(frozen=True)
class _StreamlinesOperatorExecution:
    """One completed disposable operator and its optional FSD-safe mirror."""

    prepared: _PreparedStreamlinesOperator
    rebuild_ms: float
    evidence: StreamlinesOperatorEvidence
    execution_receipt: StreamlinesOperatorExecutionReceipt
    preview_mirror_ms: float | None
    speed_magnitudes: tuple[float, ...] | None


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


class StreamlinesOperatorRuntimeMixin:
    """Own standard Kit-CAE operator creation, receipts, and UsdRT readback."""

    @staticmethod
    def _streamlines_integration_settings(
        streamlines_api,
    ) -> tuple[tuple[str, str], ...]:
        """Capture standard-operator settings shared by cache and fallback runs."""

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
    def _streamlines_source_processing_evidence(operator_prim, *, cae_viz) -> str:
        """Require the standard operator's authored DatasetSubsetAPI source path."""

        has_subset = operator_prim.HasAPI(cae_viz.DatasetSubsetAPI, "source")
        return "subset" if has_subset else "MISSING_SUBSET_API"

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
        source_time_code: float | None,
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
        locked_source_time_code = self._lock_streamlines_operator_to_source_time(
            operator_prim,
            source_time_code=source_time_code,
            cae_viz=cae_viz,
        )
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
        source_processing_mode = self._streamlines_source_processing_evidence(
            operator_prim,
            cae_viz=cae_viz,
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
            locked_source_time_code=locked_source_time_code,
        )

    @staticmethod
    def _lock_streamlines_operator_to_source_time(
        operator_prim,
        *,
        source_time_code: float | None,
        cae_viz,
    ) -> float | None:
        """Pin one disposable cache operator to its manifest source state.

        Kit-CAE executes Streamlines with its operator temporal context.  A
        query of a temporal field alone does not select the context consumed by
        the operator, so each cache sample locks its own disposable operator.
        """

        if source_time_code is None:
            return None
        expected = float(source_time_code)
        cae_viz.OperatorTemporalAPI.Apply(operator_prim)
        temporal_api = cae_viz.OperatorTemporalAPI(operator_prim)
        temporal_api.GetUseLockedTimeAttr().Set(True)
        temporal_api.GetLockedTimeAttr().Set(expected)
        if (
            temporal_api.GetUseLockedTimeAttr().Get() is not True
            or float(temporal_api.GetLockedTimeAttr().Get()) != expected
        ):
            raise RuntimeError(
                "Streamlines operator did not retain its manifest source time."
            )
        return expected

    @staticmethod
    def _validate_streamlines_bindings(
        request: StreamlinesOperatorRequest,
        *,
        binding_evidence,
        source_processing_mode: str,
    ) -> None:
        """Reject an operator whose source, seed, or velocity binding drifted."""

        if (
            binding_evidence.source_targets != (request.dataset_prim_path,)
            or binding_evidence.seed_targets != (request.seed_path,)
            or binding_evidence.velocity_targets != (request.velocity_field_prim_path,)
            or source_processing_mode != "subset"
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
        execute_command,
        preview_path: str | None,
        Sdf,
        capture_speed_magnitudes: bool = False,
        source_time_code: float | None = None,
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
                source_time_code=source_time_code,
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
                )
            )
            speed_magnitudes = None
            if capture_speed_magnitudes:
                if source_time_code is None:
                    raise RuntimeError(
                        "A source time code is required to persist raw speed."
                    )
                speed_magnitudes = await self._probe_streamline_speed_magnitudes_in_kit(
                    operator_prim=prepared.operator_prim,
                    point_positions=evidence.runtime_point_positions,
                    source_time_code=source_time_code,
                    wp=wp,
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
                speed_magnitudes=speed_magnitudes,
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

    async def _probe_streamline_speed_magnitudes_in_kit(
        self,
        *,
        operator_prim,
        point_positions: tuple[tuple[float, float, float], ...],
        source_time_code: float,
        wp,
    ) -> tuple[float, ...]:
        """Sample the selected raw velocity field at accepted curve vertices.

        Kit-CAE deliberately omits ``velocities`` from its Streamlines primvars.
        Cache generation therefore performs this one explicit probe while the
        disposable operator still binds the exact selected source sample.
        """

        import numpy as np
        from dav.data_models.custom import point_cloud as dav_point_cloud
        from dav.operators import probe as dav_probe
        from omni.cae.viz import utils as cae_viz_utils
        from pxr import Usd

        point_count = len(point_positions)
        if point_count == 0:
            raise RuntimeError("Cannot persist speed for empty Streamlines geometry.")
        source_dataset = await cae_viz_utils.get_input_dataset(
            operator_prim,
            "source",
            timeCode=Usd.TimeCode(source_time_code),
            device=str(wp.get_device()),
            required_fields={"velocities"},
        )
        positions = wp.array(
            list(point_positions),
            dtype=wp.vec3f,
            device=source_dataset.device,
        )
        curve_vertices = dav_point_cloud.create_dataset(positions)
        probed = dav_probe.compute(
            source_dataset,
            "velocities",
            curve_vertices,
            output_mask_field_name="dtrs_speed_mask",
        )
        mask = np.asarray(
            probed.get_field("dtrs_speed_mask").to_array().numpy()
        ).reshape(-1)
        if len(mask) != point_count or not np.all(mask != 0):
            raise RuntimeError(
                "Raw speed probe found Streamlines vertices outside the source field."
            )
        vectors = probed.get_field("probed_values").to_array().numpy()
        try:
            return speed_magnitudes_from_velocity_vectors(
                vectors,
                expected_point_count=point_count,
            )
        except ValueError as error:
            raise RuntimeError(
                f"Raw Streamlines speed probe failed: {error}"
            ) from error

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
