"""Flow attach/detach lifecycle implementation for the DTRS command facade."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, replace
from pathlib import Path
from queue import Empty, SimpleQueue
from threading import Event
from typing import Callable

from digital_twin_runtime_suite.app.airflow_dataset import (
    AirflowDatasetError,
    discover_airflow_dataset,
    discover_airflow_dataset_registry,
    validate_airflow_dataset_grid,
)
from digital_twin_runtime_suite.app.airflow_validation import family as airflow_family
from digital_twin_runtime_suite.app.airflow_validation import (
    preflight as airflow_preflight,
)
from digital_twin_runtime_suite.app.airflow_validation.cache import (
    DatasetValidationSignature,
    ValidationCacheLookup,
    build_dataset_validation_signature,
)
from digital_twin_runtime_suite.app.config import (
    EmitterLayoutConfig,
    SmokeTuningConfig,
    validate_emitter_layout,
    validate_smoke_tuning,
)
from digital_twin_runtime_suite.app.diagnostics import with_dtrs_local_timestamp
from digital_twin_runtime_suite.app.flow import smoke as flow_smoke
from digital_twin_runtime_suite.app.flow import temporal as flow_temporal
from digital_twin_runtime_suite.app.flow import validation as flow_validation
from digital_twin_runtime_suite.app.flow.diagnostics import FlowDiagnosticsMixin
from digital_twin_runtime_suite.app.flow.performance import (
    FlowPerformanceMixin,
)
from digital_twin_runtime_suite.app.flow.progress import (
    TemporalProofProgress,
    TemporalProofResultSource,
    TemporalProofState,
)
from digital_twin_runtime_suite.app.flow.quality import (
    validate_kit_cae_flow_voxel_resolution,
)
from digital_twin_runtime_suite.app.flow.temporal import FlowTemporalMixin
from digital_twin_runtime_suite.app.kit_cae_flow_parity import (
    capture_flow_scene,
    write_flow_snapshot,
)
from digital_twin_runtime_suite.app.workload_binding import BackgroundValidationError

StatusCallback = Callable[[str], None]

# Local aliases preserve the narrow transition seam while the implementation
# lives with dataset-level validation rather than the Flow lifecycle package.
AirflowDatasetFamilyCompatibilityError = (
    airflow_family.AirflowDatasetFamilyCompatibilityError
)


@dataclass(frozen=True)
class SimulationCacheResult:
    """Result of attaching or controlling the airflow cache."""

    success: bool
    message: str


class FlowRuntimeMixin(
    FlowPerformanceMixin,
    FlowTemporalMixin,
    FlowDiagnosticsMixin,
):
    """Own Flow lifecycle methods while RuntimeController keeps the public facade."""

    EMITTER_REBUILD_SETTLE_UPDATES = 3
    TEMPORAL_AUTHORING_BATCH_SIZE = 8

    @staticmethod
    def _log_kit_cae_attach_phase(carb, phase: str, started_at: float) -> None:
        """Record a measured Attach phase without affecting runtime state."""

        elapsed_ms = (time.monotonic() - started_at) * 1000.0
        carb.log_warn(f"DTRS FLOW ATTACH PHASE | {phase} | {elapsed_ms:.0f} ms")

    def _log_dataset_validation_cache(
        self,
        carb,
        lookup: ValidationCacheLookup,
    ) -> None:
        """Record the cache decision without enumerating all VTI paths."""

        carb.log_warn(
            self._format_flow_log_block(
                "DATASET VALIDATION CACHE",
                (
                    (
                        "",
                        (
                            ("Selector:", lookup.signature.selector),
                            ("Result:", lookup.result),
                            ("Reason:", lookup.reason),
                            ("Signature:", lookup.signature.compact_digest),
                            ("Preflight:", "REUSED" if lookup.preflight else "RUN"),
                            (
                                "Temporal proof:",
                                "REUSED" if lookup.temporal_proof else "RUN",
                            ),
                        ),
                    ),
                ),
            )
        )

    def temporal_proof_progress(self) -> TemporalProofProgress:
        """Return the latest plain-data temporal validation snapshot."""

        return self._flow_temporal_progress

    def _set_temporal_proof_progress(
        self,
        *,
        state: TemporalProofState,
        generation_id: int,
        total_sample_count: int,
        validated_sample_count: int = 0,
        current_sample_index: int | None = None,
        current_asset_name: str | None = None,
        started_at: float | None = None,
        loop_closure_state: str | None = None,
        failure_reason: str | None = None,
        result_source: TemporalProofResultSource = TemporalProofResultSource.LIVE,
    ) -> None:
        """Replace progress atomically with values safe for OmniUI polling."""

        now = time.monotonic()
        self._flow_temporal_progress = TemporalProofProgress(
            state=state,
            result_source=result_source,
            validated_sample_count=validated_sample_count,
            total_sample_count=total_sample_count,
            current_sample_index=current_sample_index,
            current_asset_name=current_asset_name,
            elapsed_seconds=(now - started_at) if started_at is not None else 0.0,
            loop_closure_state=loop_closure_state,
            failure_reason=failure_reason,
            generation_id=generation_id,
            last_progress_at=now,
        )

    def _update_temporal_proof_progress(
        self,
        *,
        generation_id: int,
        state: TemporalProofState,
        total_sample_count: int,
        validated_sample_count: int,
        current_asset_name: str | None,
        started_at: float,
        loop_closure_state: str | None = None,
    ) -> bool:
        """Ignore stale proof tasks before they can replace current DTRS state."""

        if generation_id != self._flow_temporal_proof_generation:
            return False
        self._set_temporal_proof_progress(
            state=state,
            generation_id=generation_id,
            total_sample_count=total_sample_count,
            validated_sample_count=validated_sample_count,
            current_sample_index=validated_sample_count - 1,
            current_asset_name=current_asset_name,
            started_at=started_at,
            loop_closure_state=loop_closure_state,
        )
        return True

    def _cancel_kit_cae_temporal_proof(
        self,
        *,
        reason: str = "CANCELLED",
    ) -> bool:
        """Invalidate a proof without allowing it to certify a later runtime state."""

        self._flow_temporal_proof_generation += 1
        previous_progress = self._flow_temporal_progress
        cancelled = False
        if previous_progress.state in {
            TemporalProofState.RUNNING,
            TemporalProofState.CHECKING_LOOP_CLOSURE,
        }:
            cancelled = True
            self._flow_temporal_progress = replace(
                previous_progress,
                state=TemporalProofState.CANCELLED,
                loop_closure_state=None,
                failure_reason=None,
                cancellation_reason=(
                    "WORKLOAD_TRANSITION"
                    if reason == "SUPERSEDED_BY_WORKLOAD_TRANSITION"
                    else reason
                ),
                generation_id=self._flow_temporal_proof_generation,
                last_progress_at=time.monotonic(),
            )
        task = self._flow_temporal_proof_task
        self._flow_temporal_proof_task = None
        if task and not task.done():
            task.cancel()
        return cancelled

    def _schedule_kit_cae_temporal_proof(
        self,
        *,
        app,
        carb,
        stage,
        timeline,
        velocity_paths: tuple[Path, ...],
        field_prim,
        dataset_emitter,
        flow_environment_path: str,
        dataset_emitter_path: str,
        origin_match: bool,
        grid_match: bool,
        cae_vtk,
        Usd,
        status_callback: StatusCallback | None,
        dataset_signature: DatasetValidationSignature,
    ) -> None:
        """Keep the full Stage 6 proof available without extending Attach."""

        self._cancel_kit_cae_temporal_proof()
        generation = self._flow_temporal_proof_generation
        started_at = time.monotonic()
        self._set_temporal_proof_progress(
            state=TemporalProofState.RUNNING,
            generation_id=generation,
            total_sample_count=len(velocity_paths),
            validated_sample_count=1,
            current_sample_index=0,
            current_asset_name=velocity_paths[0].name,
            started_at=started_at,
        )

        def update_progress(validated_count, asset, checking_loop) -> None:
            if generation != self._flow_temporal_proof_generation:
                return
            self._update_temporal_proof_progress(
                generation_id=generation,
                state=(
                    TemporalProofState.CHECKING_LOOP_CLOSURE
                    if checking_loop
                    else TemporalProofState.RUNNING
                ),
                total_sample_count=len(velocity_paths),
                validated_sample_count=validated_count,
                current_asset_name=asset.name,
                started_at=started_at,
                loop_closure_state=("CHECKING" if checking_loop else None),
            )

        async def monitor() -> None:
            try:
                passed = await self._monitor_kit_cae_temporal_proof(
                    app=app,
                    carb=carb,
                    stage=stage,
                    timeline=timeline,
                    velocity_paths=velocity_paths,
                    field_prim=field_prim,
                    dataset_emitter=dataset_emitter,
                    flow_environment_path=flow_environment_path,
                    dataset_emitter_path=dataset_emitter_path,
                    origin_match=origin_match,
                    grid_match=grid_match,
                    cae_vtk=cae_vtk,
                    Usd=Usd,
                    progress_callback=update_progress,
                )
            except asyncio.CancelledError:
                carb.log_info("DTRS FLOW TEMPORAL PROOF | cancelled")
                raise
            except Exception as error:  # noqa: BLE001
                carb.log_error(f"DTRS FLOW TEMPORAL PROOF | failed: {error}")
                if generation == self._flow_temporal_proof_generation:
                    self._flow_temporal_failure = {"reason": str(error)}
                    self._set_temporal_proof_progress(
                        state=TemporalProofState.FAILED,
                        generation_id=generation,
                        total_sample_count=len(velocity_paths),
                        failure_reason=str(error),
                    )
                    if status_callback:
                        status_callback("Airflow active · Validation failed")
                return
            finally:
                if generation == self._flow_temporal_proof_generation:
                    self._flow_temporal_proof_task = None

            if (
                generation != self._flow_temporal_proof_generation
                or self._flow_lifecycle_state != "ATTACHED"
            ):
                return
            self._set_temporal_proof_progress(
                state=(
                    TemporalProofState.PASSED if passed else TemporalProofState.FAILED
                ),
                generation_id=generation,
                total_sample_count=len(velocity_paths),
                validated_sample_count=len(velocity_paths),
                current_sample_index=len(velocity_paths) - 1,
                current_asset_name=velocity_paths[-1].name,
                started_at=started_at,
                loop_closure_state=("PASSED" if passed else "FAILED"),
                failure_reason=None if passed else "See temporal validation log.",
            )
            if passed:
                # Store only after the task survived generation/lifecycle checks above;
                # a cancelled or stale proof must never certify a later Attach.
                receipt = self._flow_validation_cache.store_temporal_proof(
                    dataset_signature,
                    validated_sample_count=len(velocity_paths),
                    duration_seconds=time.monotonic() - started_at,
                )
                carb.log_warn(
                    "DTRS FLOW DATASET VALIDATION CACHE | "
                    "Temporal receipt stored | signature="
                    + receipt.signature.compact_digest
                )
            carb.log_info(
                "DTRS FLOW TEMPORAL VALIDATION | " + ("passed" if passed else "failed")
            )
            if status_callback:
                status_callback(
                    "Airflow active · Validation " + ("passed" if passed else "failed")
                )

        self._flow_temporal_proof_task = asyncio.ensure_future(monitor())

    def _resolve_kit_cae_attach_airflow_dataset(self):
        """Resolve current workload to the manifest-backed dataset for Attach."""

        binding = self.resolve_current_workload_airflow_binding()
        return binding, discover_airflow_dataset(
            self.config.asset_root,
            binding.dataset,
        )

    async def _attach_kit_cae_airflow_in_kit(
        self,
        status_callback: StatusCallback | None = None,
    ) -> SimulationCacheResult:
        """Give manual Attach validation priority before the Stage 6 lifecycle."""

        if self._flow_lifecycle_state == "DETACHING":
            return SimulationCacheResult(
                False,
                "Kit-CAE Flow detach is still in progress.",
            )
        if self._flow_lifecycle_state == "ATTACHING":
            return SimulationCacheResult(
                False,
                "Kit-CAE Flow attach is still in progress.",
            )
        if self._flow_lifecycle_state == "ATTACHED":
            return SimulationCacheResult(
                False,
                "Kit-CAE Flow is already attached; detach it before attaching again.",
            )

        import carb

        binding = None
        try:
            binding = self.resolve_current_workload_airflow_binding()
            airflow_dataset = discover_airflow_dataset(
                self.config.asset_root,
                binding.dataset,
            )
        except (AirflowDatasetError, RuntimeError, ValueError) as error:
            return self._finalize_airflow_failure(
                semantic_workload=(
                    binding.workload_mode
                    if binding is not None
                    else (
                        self._workload_source()
                        if self._workload_source
                        else "unavailable"
                    )
                ),
                requested_binding=binding,
                reason=str(error),
                failure_stage="dataset_discovery",
                logger=carb.log_error,
                status_callback=status_callback,
            )
        try:
            validation_lease = await self.acquire_airflow_validation_for_attach(binding)
        except BackgroundValidationError as error:
            return self._finalize_airflow_failure(
                semantic_workload=binding.workload_mode,
                requested_binding=binding,
                reason=str(error),
                failure_stage="validation",
                logger=carb.log_error,
                status_callback=status_callback,
            )
        try:
            result = await self._attach_kit_cae_airflow_after_validation_in_kit(
                binding,
                airflow_dataset,
                status_callback,
            )
            if result.success:
                self._flow_last_airflow_failure = None
                return result
            return self._finalize_airflow_failure(
                semantic_workload=binding.workload_mode,
                requested_binding=binding,
                reason=result.message,
                failure_stage="attach_lifecycle",
                logger=carb.log_error,
                status_callback=status_callback,
            )
        finally:
            validation_lease.release()

    async def _attach_kit_cae_airflow_after_validation_in_kit(
        self,
        binding,
        airflow_dataset,
        status_callback: StatusCallback | None = None,
    ) -> SimulationCacheResult:
        """Run the unchanged Stage 6 Flow lifecycle after preflight arbitration."""

        import carb

        cache = self.config.simulation_cache
        attach_selector_log = (
            "DTRS FLOW ATTACH SELECTOR | "
            f"workload={binding.workload_mode} | "
            f"Selector: {binding.dataset_identity} | "
            f"State: {binding.dataset.state}"
        )
        carb.log_warn(with_dtrs_local_timestamp(attach_selector_log))
        velocity_paths = airflow_dataset.velocity_vti_sequence_paths
        velocity_path = velocity_paths[0]
        missing_velocity_paths = [path for path in velocity_paths if not path.is_file()]
        if missing_velocity_paths:
            message = "Kit-CAE airflow VTI is missing: " + ", ".join(
                str(path) for path in missing_velocity_paths
            )
            carb.log_error(
                "DTRS Flow temporal expanded diagnostics: "
                f"reason=asset missing or unreadable, assets={missing_velocity_paths}"
            )
            return SimulationCacheResult(False, message)
        if status_callback:
            status_callback("Importing Houdini velocity VTI through Kit-CAE")

        import omni.kit.app
        import omni.timeline
        import omni.usd
        from omni.cae.data.commands import execute_command
        from omni.cae.importer.vtk import import_to_stage
        from omni.cae.schema import cae
        from omni.cae.schema import viz as cae_viz
        from omni.cae.schema import vtk as cae_vtk
        from pxr import Gf, Sdf, Usd, UsdGeom

        extension_manager = omni.kit.app.get_app().get_extension_manager()
        required_extensions = (
            "omni.flowusd",
            "omni.cae.delegate.vtk",
            "omni.cae.importer.vtk",
            "omni.cae.viz",
        )
        disabled_extensions = [
            extension_id
            for extension_id in required_extensions
            if not extension_manager.is_extension_enabled(extension_id)
        ]
        if disabled_extensions:
            return SimulationCacheResult(
                False,
                "Kit-CAE airflow is unavailable; start DTRS through start_dtrs.bat "
                f"with these extensions enabled: {', '.join(disabled_extensions)}.",
            )

        stage = omni.usd.get_context().get_stage()
        if not stage:
            return SimulationCacheResult(False, "Airflow cache skipped: no open stage.")

        self._flow_lifecycle_state = "ATTACHING"
        self._flow_session_workload_binding = binding
        self._flow_pending_workload_binding = None
        self._flow_attach_cancel_event = Event()
        self._start_kit_cae_operator_tracking()
        self._stop_flow_performance_sampler()
        self._log_flow_performance_event(
            carb,
            event="PRE_ATTACH",
            sample=self._capture_flow_performance_sample(),
        )

        # Kit-CAE's current VTK importer copies its result into the root layer.
        # The import destination itself must be top-level: Sdf.CopySpec does not
        # create its parent specs in that layer.
        runtime_root = "/DTRS_KitCAE"
        import_root = "/DTRS_HoudiniVelocity"
        dataset_path = f"{import_root}/VTKImageData"
        field_path = f"{import_root}/PointData/{cache.velocity_field_name}"
        bbox_path = f"{runtime_root}/BoundingBox"
        flow_environment_path = f"{runtime_root}/FlowSimulation"
        tracer_root_path = f"{runtime_root}/AirflowTracerEmitters"
        boundary_emitter_path = f"{runtime_root}/BoundaryEmitter"
        dataset_emitter_path = f"{runtime_root}/DataSetEmitter"
        app = omni.kit.app.get_app()
        previous_target = stage.GetEditTarget()
        session_layer = stage.GetSessionLayer()
        session_layer.timeCodesPerSecond = float(stage.GetTimeCodesPerSecond())
        stage.SetEditTarget(session_layer)
        temporal_proof_ready = False
        dataset_signature = None
        validation_cache_lookup = None
        try:
            dataset_signature = build_dataset_validation_signature(
                airflow_dataset,
                cache.velocity_field_name,
            )
            validation_cache_lookup = self._flow_validation_cache.lookup(
                dataset_signature
            )
            self._log_dataset_validation_cache(carb, validation_cache_lookup)
            if validation_cache_lookup.preflight:
                metadata = dict(validation_cache_lookup.preflight.metadata)
                grid_match = validation_cache_lookup.preflight.grid_match
                if status_callback:
                    status_callback(
                        "Preparing airflow · Verified this session"
                        if validation_cache_lookup.temporal_proof
                        else "Preparing airflow · Preflight reused"
                    )
                preflight_started_at = time.monotonic()
                self._log_kit_cae_attach_phase(
                    carb,
                    "VTI preflight | session cache hit",
                    preflight_started_at,
                )
            else:
                if status_callback:
                    status_callback(
                        f"Preparing airflow · VTI 0/{len(velocity_paths)} · 0%"
                    )
                preflight_started_at = time.monotonic()
                preflight_updates = SimpleQueue()

                # The worker sends only plain VTI facts. The Kit coroutine owns
                # status updates and cache mutation after the result is accepted.
                preflight_task = asyncio.create_task(
                    asyncio.to_thread(
                        self._validate_kit_cae_temporal_vti_contract,
                        velocity_paths,
                        cache.velocity_field_name,
                        lambda completed, total, asset_name: preflight_updates.put(
                            (completed, total, asset_name)
                        ),
                        cancel_requested=self._flow_attach_cancel_event.is_set,
                    )
                )
                while not preflight_task.done():
                    try:
                        completed, total, _asset_name = preflight_updates.get_nowait()
                        if status_callback:
                            status_callback(
                                f"Preparing airflow · VTI {completed}/{total} · "
                                f"{round(100 * completed / total)}%"
                            )
                    except Empty:
                        pass
                    await app.next_update_async()
                metadata, grid_match = await preflight_task
                while not preflight_updates.empty():
                    completed, total, _asset_name = preflight_updates.get_nowait()
                    if status_callback:
                        status_callback(
                            f"Preparing airflow · VTI {completed}/{total} · "
                            f"{round(100 * completed / total)}%"
                        )
                validate_airflow_dataset_grid(
                    airflow_dataset,
                    tuple(metadata["dimensions"]),
                )
                metadata = {
                    **metadata,
                    "velocity_field_name": cache.velocity_field_name,
                    "velocity_field_association": "point_data",
                }
                receipt = self._flow_validation_cache.store_preflight(
                    dataset_signature,
                    metadata,
                    grid_match,
                )
                carb.log_warn(
                    "DTRS FLOW DATASET VALIDATION CACHE | "
                    "Preflight receipt stored | "
                    f"signature={receipt.signature.compact_digest} | "
                    f"samples={len(velocity_paths)}"
                )
                self._log_kit_cae_attach_phase(
                    carb,
                    "VTI preflight",
                    preflight_started_at,
                )
            if status_callback:
                status_callback("Importing Houdini velocity VTI through Kit-CAE")
            import_started_at = time.monotonic()
            if stage.GetPrimAtPath(runtime_root).IsValid():
                stage.RemovePrim(runtime_root)
            await import_to_stage(str(velocity_path), import_root)
            await app.next_update_async()
            self._log_kit_cae_attach_phase(
                carb,
                "initial VTI import",
                import_started_at,
            )

            dataset_prim = stage.GetPrimAtPath(dataset_path)
            field_prim = stage.GetPrimAtPath(field_path)
            if status_callback:
                status_callback(
                    f"Activating airflow · USD 0/{len(velocity_paths)} · 0%"
                )
            authoring_started_at = time.monotonic()
            self._flow_temporal_sample_time_codes = (
                await flow_temporal.author_kit_cae_temporal_velocity_samples_in_batches(
                    field_prim,
                    velocity_paths,
                    stage.GetTimeCodesPerSecond(),
                    airflow_dataset.sample_interval_seconds,
                    cae_vtk,
                    Sdf,
                    Usd,
                    app.next_update_async,
                    self.TEMPORAL_AUTHORING_BATCH_SIZE,
                    (
                        lambda completed, total: (
                            status_callback(
                                "Activating airflow · USD "
                                f"{completed}/{total} · "
                                f"{round(100 * completed / total)}%"
                            )
                            if status_callback
                            else None
                        )
                    ),
                )
            )
            self._log_kit_cae_attach_phase(
                carb,
                "temporal USD authoring",
                authoring_started_at,
            )
            self._flow_temporal_end_time_code = (
                self._flow_temporal_sample_time_codes[-1]
                + (
                    self._flow_temporal_sample_time_codes[-1]
                    - self._flow_temporal_sample_time_codes[-2]
                )
                if len(self._flow_temporal_sample_time_codes) > 1
                else None
            )
            origin_after_import = self._read_kit_cae_vti_origin_opinion(
                dataset_prim,
                cae_vtk,
            )
            self._author_kit_cae_vti_origin_session_opinion(
                dataset_prim,
                metadata["vti_header_origin"],
                cae_vtk,
                Gf,
            )
            await app.next_update_async()
            imported_grid = self._validate_kit_cae_velocity_field(
                dataset_prim,
                field_prim,
                metadata,
                cae,
                cae_vtk,
            )

            if status_callback:
                status_callback("Activating airflow · Waiting for Flow")
            flow_readiness_started_at = time.monotonic()
            await execute_command(
                "CreateCaeVizBoundingBox",
                dataset_paths=[dataset_path],
                prim_path=bbox_path,
            )
            await app.next_update_async()
            self._author_kit_cae_spatial_sanity_wireframes(
                stage,
                imported_grid["world_bounds"],
                Gf,
                Usd,
                UsdGeom,
            )
            self._set_kit_cae_spatial_sanity_wireframes_visibility(
                stage,
                False,
                UsdGeom,
            )
            await app.next_update_async()
            origin_after_dtrs_composition = self._read_kit_cae_vti_origin_opinion(
                dataset_prim,
                cae_vtk,
            )
            await execute_command(
                "CreateCaeVizFlowEnvironment",
                prim_path=flow_environment_path,
                layer_number=0,
            )
            await app.next_update_async()
            flow_environment_prim = stage.GetPrimAtPath(flow_environment_path)
            flow_simulate = flow_environment_prim.GetChild("flowSimulate")
            self._flow_world_bounds = imported_grid["world_bounds"]
            UsdGeom.Xform.Define(stage, tracer_root_path)
            derived_layout = flow_smoke.kit_cae_front_intake_emitter_layout(
                stage,
                cache.emitter_layout,
                self.config.fan_motion_bindings,
                imported_grid["world_bounds"],
                cache.intake_tracers.radius,
                cache.intake_tracers.front_offset,
                Gf,
                Usd,
                UsdGeom,
            )
            tracer_config = replace(cache.intake_tracers, radius=derived_layout.radius)
            for index, position in enumerate(derived_layout.positions, start=1):
                tracer_path = f"{tracer_root_path}/intake_{index:02d}"
                await execute_command(
                    "CreateCaeVizFlowSmokeInjector",
                    boundable_paths=[bbox_path],
                    prim_path=tracer_path,
                    layer_number=0,
                    mode="sphere",
                    simulation_prim=flow_environment_prim,
                )
                await app.next_update_async()
                flow_smoke.configure_kit_cae_intake_tracer_emitter(
                    stage,
                    tracer_path,
                    position,
                    tracer_config,
                    Gf,
                    UsdGeom,
                )
            flow_smoke.hide_kit_cae_intake_tracer_meshes(
                stage,
                tracer_root_path,
                UsdGeom,
                expected_count=len(derived_layout.positions),
            )
            await execute_command(
                "CreateCaeVizFlowBoundaryEmitter",
                boundable_paths=[bbox_path],
                prim_path=boundary_emitter_path,
                layer_number=0,
            )
            await app.next_update_async()
            await execute_command(
                "CreateCaeVizFlowDataSetEmitter",
                dataset_path=dataset_path,
                prim_path=dataset_emitter_path,
                layer_number=0,
                simulation_prim=flow_environment_prim,
            )
            emitter_prim = stage.GetPrimAtPath(dataset_emitter_path)
            if not emitter_prim.HasAPI(cae_viz.FieldSelectionAPI, "velocities"):
                raise RuntimeError(
                    "Kit-CAE DataSetEmitter has no velocities field selector."
                )
            emitter_operator = cae_viz.OperatorAPI(emitter_prim)
            emitter_operator.CreateEnabledAttr().Set(False)
            voxelization_api = cae_viz.DatasetVoxelizationAPI(
                emitter_prim,
                "source",
            )
            configured_max_resolution = voxelization_api.GetMaxResolutionAttr().Get()
            self._flow_voxel_max_resolution = (
                int(configured_max_resolution)
                if isinstance(configured_max_resolution, int)
                else None
            )
            velocity_selector = cae_viz.FieldSelectionAPI(emitter_prim, "velocities")
            velocity_selector.CreateTargetRel().SetTargets([field_path])
            emitter_operator.CreateEnabledAttr().Set(True)
            operator_readiness = (
                await flow_validation.wait_for_kit_cae_dataset_emitter_ready(
                    app,
                    emitter_prim,
                )
            )
            effective_density_cell_size = flow_simulate.GetAttribute(
                "densityCellSize"
            ).Get()
            self._flow_density_cell_size = (
                float(effective_density_cell_size)
                if isinstance(effective_density_cell_size, (int, float))
                and effective_density_cell_size > 0
                else None
            )
            resolve_runtime_contract = (
                flow_validation.resolve_live_kit_cae_direct_attach_runtime_contract
            )
            direct_attach_runtime_contract = await resolve_runtime_contract(
                emitter_prim,
                Usd,
                cache.smoke_tuning.velocity_scale_multiplier,
                Usd.TimeCode(self._flow_temporal_sample_time_codes[0]),
            )
            self._flow_base_velocity_scale = direct_attach_runtime_contract[
                "base_velocity_scale"
            ]
            self._flow_last_temporal_proof_selector = binding.dataset_identity
            flow_smoke.configure_kit_cae_smoke_only_tracer_flow(
                stage,
                flow_environment_path,
                cache.intake_tracers,
                cache.smoke_tuning,
                dataset_emitter_path=dataset_emitter_path,
                base_velocity_scale=self._flow_base_velocity_scale,
            )
            timeline = omni.timeline.get_timeline_interface()
            timeline.pause()
            timeline.set_current_time(0.0)
            self._flow_airflow_simulate_path = f"{flow_environment_path}/flowSimulate"
            await flow_smoke.pulse_kit_cae_flow_clear(app, flow_environment_path)
            flow_smoke.clear_kit_cae_server_visibility_session_opinion(
                stage,
                UsdGeom,
            )

            await app.next_update_async()
            self._restart_kit_cae_temporal_loop(timeline)
            timeline_time_before = float(timeline.get_current_time())
            for _ in range(12):
                await app.next_update_async()
            timeline_time_after = float(timeline.get_current_time())
            self._log_kit_cae_attach_phase(
                carb,
                "initial Flow readiness",
                flow_readiness_started_at,
            )
            origin_match = self._kit_cae_vectors_match(
                metadata["vti_header_origin"],
                origin_after_dtrs_composition["origin"],
            )
            payload_attribute = emitter_prim.GetAttribute("nanoVdbVelocities")
            payload = (
                payload_attribute.Get()
                if payload_attribute and payload_attribute.IsValid()
                else None
            )
            payload_count = len(payload) if payload is not None else 0
            velocity_scale = emitter_prim.GetAttribute("velocityScale").Get()
            couple_rate_velocity = emitter_prim.GetAttribute("coupleRateVelocity").Get()
            velocity_scale_matches = self._kit_cae_velocity_scale_matches_expected(
                velocity_scale
            )
            timeline_advancing = timeline_time_after > timeline_time_before
            self._flow_vti_spacing = tuple(
                float(value) for value in metadata["spacing"]
            )
            evidence_valid = (
                operator_readiness["ready"]
                and not operator_readiness["timed_out"]
                and origin_match
                and grid_match
                and timeline_advancing
                and payload_count > 0
                and float(couple_rate_velocity or 0.0) > 0.0
                and velocity_scale_matches
            )
            self._flow_temporal_records = []
            self._flow_temporal_failure = None
            if evidence_valid:
                stage_meters_per_unit = UsdGeom.GetStageMetersPerUnit(stage)
                density_cell_size_m = (
                    self._flow_density_cell_size * stage_meters_per_unit
                    if self._flow_density_cell_size is not None
                    else None
                )
                intake_tracer_radius = self._read_kit_cae_intake_tracer_radius(
                    stage,
                    tracer_root_path,
                    UsdGeom,
                )
                self._flow_intake_tracer_radius_to_cell = (
                    self._kit_cae_tracer_radius_cell_ratio(
                        intake_tracer_radius,
                        self._flow_density_cell_size,
                    )
                )
                self._log_kit_cae_airflow_dataset(carb, airflow_dataset)
                self._log_kit_cae_flow_attached(
                    carb,
                    temporal_frames=len(velocity_paths),
                    intake_tracer_count=cache.intake_tracers.count,
                    metadata=metadata,
                    origin_match=origin_match,
                    grid_match=grid_match,
                    operator_ready=bool(operator_readiness["ready"]),
                    flow_environment_path=flow_environment_path,
                    dataset_emitter_path=dataset_emitter_path,
                    base_velocity_scale=self._flow_base_velocity_scale,
                    stage_meters_per_unit=stage_meters_per_unit,
                    density_cell_size_m=density_cell_size_m,
                    intake_tracer_radius=intake_tracer_radius,
                )
                self._log_kit_cae_temporal_frame(
                    carb,
                    sequence_index=0,
                    temporal_frames=len(velocity_paths) + 1,
                    asset=velocity_path,
                    previous_frame=None,
                    transition="INITIAL",
                    operator_ready=bool(operator_readiness["ready"]),
                    operator_wait_ms=float(operator_readiness["seconds"]) * 1000.0,
                    nano_vdb_velocities_uint_count=payload_count,
                    velocity_scale=velocity_scale,
                    velocity_scale_matches=velocity_scale_matches,
                    couple_rate_velocity=couple_rate_velocity,
                    timeline_time_before=timeline_time_before,
                    timeline_time_after=timeline_time_after,
                    timeline_advancing=timeline_advancing,
                    flow_reset=False,
                    origin_match=origin_match,
                    grid_match=grid_match,
                    verbose=cache.temporal_debug_logging,
                )
                temporal_proof_ready = True
            else:
                dav_origin_trace = (
                    await flow_validation.trace_kit_cae_dav_velocity_dataset(
                        emitter_prim,
                        Usd,
                    )
                )
                self._log_kit_cae_render_probe(
                    stage,
                    flow_environment_path,
                    "NATIVE_FUEL",
                    carb,
                )
                self._log_kit_cae_origin_trace(
                    metadata,
                    origin_after_import,
                    origin_after_dtrs_composition,
                    dav_origin_trace,
                    carb,
                )
                self._log_kit_cae_flow_full_diagnostics(
                    stage,
                    velocity_path,
                    metadata,
                    imported_grid,
                    dataset_path,
                    flow_environment_path,
                    tracer_root_path,
                    boundary_emitter_path,
                    dataset_emitter_path,
                    bbox_path,
                    field_path,
                    velocity_selector,
                    timeline,
                    timeline_time_before,
                    timeline_time_after,
                    operator_readiness,
                    "NATIVE_FUEL",
                    Usd,
                    UsdGeom,
                    carb,
                )
            self._write_kit_cae_flow_parity_snapshot(
                stage,
                dataset_path=dataset_path,
                field_path=field_path,
                bbox_path=bbox_path,
                flow_environment_path=flow_environment_path,
                tracer_root_path=tracer_root_path,
                boundary_emitter_path=boundary_emitter_path,
                dataset_emitter_path=dataset_emitter_path,
            )
        except airflow_preflight.TemporalVtiValidationCancelled:
            # The worker has returned before any importer or Flow prim is authored.
            # Keep session validation receipts untouched because no full preflight ran.
            carb.log_info("DTRS FLOW ATTACH | cancelled during VTI preflight")
            self._clear_flow_runtime_state()
            return SimulationCacheResult(False, "Airflow preparation cancelled.")
        except Exception as error:
            carb.log_error(f"DTRS Kit-CAE Flow probe failed: {error}")
            self._flow_airflow_simulate_path = None
            self._flow_base_velocity_scale = None
            self._flow_world_bounds = None
            self._flow_density_cell_size = None
            self._flow_intake_tracer_radius_to_cell = None
            self._flow_vti_spacing = None
            self._flow_voxel_max_resolution = None
            self._flow_lifecycle_state = "DETACHED"
            self._flow_temporal_end_time_code = None
            self._flow_temporal_sample_time_codes = ()
            self._flow_temporal_records = []
            self._flow_temporal_failure = None
            self._flow_session_workload_binding = None
            self._flow_pending_workload_binding = None
            # The VTK importer authors into both the session and root layers.
            # Roll back both opinions so a failed attach cannot poison the next one.
            rollback_paths = (runtime_root, import_root)
            for prim_path in rollback_paths:
                if stage.GetPrimAtPath(prim_path).IsValid():
                    stage.RemovePrim(prim_path)
            await app.next_update_async()
            stage.SetEditTarget(stage.GetRootLayer())
            for prim_path in rollback_paths:
                if stage.GetPrimAtPath(prim_path).IsValid():
                    stage.RemovePrim(prim_path)
            await app.next_update_async()
            return SimulationCacheResult(False, f"Kit-CAE airflow failed: {error}")
        finally:
            self._flow_attach_cancel_event = None
            stage.SetEditTarget(previous_target)

        self._simulation_cache_contract = None
        self._simulation_cache_time_code = None
        self._flow_airflow_simulate_path = f"{flow_environment_path}/flowSimulate"
        self._flow_lifecycle_state = "ATTACHED"
        self._start_flow_performance_sampler()
        if not temporal_proof_ready:
            return SimulationCacheResult(
                False,
                "Kit-CAE Flow remains attached, but initial readiness validation "
                "failed; "
                "expanded diagnostics were logged.",
            )
        if validation_cache_lookup.temporal_proof:
            receipt = validation_cache_lookup.temporal_proof
            # Flow is recreated above on every Attach. Only the already completed
            # VTI proof is reused, so this status never pretends a new proof ran.
            self._set_temporal_proof_progress(
                state=TemporalProofState.PASSED,
                result_source=TemporalProofResultSource.SESSION_CACHE,
                generation_id=self._flow_temporal_proof_generation,
                total_sample_count=len(velocity_paths),
                validated_sample_count=receipt.validated_sample_count,
                current_sample_index=len(velocity_paths) - 1,
                current_asset_name=velocity_paths[-1].name,
                loop_closure_state="PASSED",
            )
            if status_callback:
                status_callback("Airflow active · Validation reused")
            return SimulationCacheResult(
                True,
                "Kit-CAE Flow initial readiness passed; temporal validation "
                "was reused from this DTRS session.",
            )
        self._schedule_kit_cae_temporal_proof(
            app=app,
            carb=carb,
            stage=stage,
            timeline=timeline,
            velocity_paths=velocity_paths,
            field_prim=field_prim,
            dataset_emitter=emitter_prim,
            flow_environment_path=flow_environment_path,
            dataset_emitter_path=dataset_emitter_path,
            origin_match=origin_match,
            grid_match=grid_match,
            cae_vtk=cae_vtk,
            Usd=Usd,
            status_callback=status_callback,
            dataset_signature=dataset_signature,
        )
        return SimulationCacheResult(
            True,
            "Kit-CAE Flow initial readiness passed; temporal loop proof is running "
            f"in the background for PointData/{cache.velocity_field_name}.",
        )

    def apply_kit_cae_smoke_tuning_in_kit(
        self,
        tuning: SmokeTuningConfig,
    ) -> SimulationCacheResult:
        """Apply and persist Cloud smoke settings without recreating Flow."""

        try:
            validate_smoke_tuning(tuning)
        except ValueError as error:
            return SimulationCacheResult(False, f"Smoke settings are invalid: {error}")
        if self._flow_lifecycle_state == "ATTACHING":
            return SimulationCacheResult(
                False,
                "Kit-CAE Flow attach is still in progress.",
            )
        if not self._flow_airflow_simulate_path:
            return SimulationCacheResult(
                False,
                "Attach the airflow cache before tuning smoke.",
            )
        if self._flow_base_velocity_scale is None:
            return SimulationCacheResult(
                False,
                "Kit-CAE base velocityScale is unavailable for this Flow session.",
            )

        import carb
        import omni.usd
        from pxr import Gf

        stage = omni.usd.get_context().get_stage()
        if not stage:
            return SimulationCacheResult(False, "Smoke tuning skipped: no open stage.")

        flow_environment_path = self._flow_airflow_simulate_path.removesuffix(
            "/flowSimulate"
        )
        previous_target = stage.GetEditTarget()
        stage.SetEditTarget(stage.GetSessionLayer())
        try:
            effective_velocity_scale = flow_smoke.author_kit_cae_smoke_tuning(
                stage,
                flow_environment_path,
                tuning,
                Gf,
                dataset_emitter_path="/DTRS_KitCAE/DataSetEmitter",
                base_velocity_scale=self._flow_base_velocity_scale,
            )
        except (RuntimeError, ValueError) as error:
            return SimulationCacheResult(False, f"Smoke settings failed: {error}")
        finally:
            stage.SetEditTarget(previous_target)

        try:
            self.save_smoke_tuning_override(tuning)
        except OSError as error:
            carb.log_error(f"Smoke settings applied but could not be saved: {error}")
            return SimulationCacheResult(
                False,
                "Smoke settings were applied, but local persistence failed.",
            )

        carb.log_info(
            "\n".join(
                (
                    "=== DTRS FLOW / SMOKE SETTINGS ===",
                    "",
                    "Appearance:",
                    f"  Density:          {tuning.density:g}",
                    f"  Brightness:       {tuning.brightness:g}",
                    f"  Ambient:          {tuning.ambient:g}",
                    f"  Shadow density:   {tuning.shadow_density:g}",
                    "  Base color:       "
                    + ", ".join(f"{component:.3g}" for component in tuning.base_color),
                    "",
                    "Dynamics:",
                    f"  Damping:          {tuning.damping:g}",
                    f"  Fade:             {tuning.fade:g}",
                    f"  Sharpness:        {tuning.sharpness:g}",
                    f"  Vorticity:        {tuning.vorticity:g}",
                    "",
                    "Flow transport:",
                    "  Kit-CAE base velocityScale: "
                    f"{self._flow_base_velocity_scale:g}",
                    "  Velocity multiplier:        "
                    f"{tuning.velocity_scale_multiplier:g}",
                    f"  Effective velocityScale:    {effective_velocity_scale:g}",
                    f"  Time scale:                 {tuning.time_scale:g}",
                    "",
                    "Quality:",
                    f"  Raymarch quality: {tuning.raymarch_quality:g}",
                    "",
                    "Flow reset:         False",
                    "Settings saved:     True",
                )
            )
        )
        return SimulationCacheResult(
            True,
            "Smoke settings applied and saved without a Flow reset.",
        )

    async def apply_kit_cae_voxel_resolution_in_kit(
        self,
        max_resolution: int,
    ) -> SimulationCacheResult:
        """Re-voxelize the attached Flow emitter for a runtime-only A/B test."""

        try:
            validate_kit_cae_flow_voxel_resolution(max_resolution)
        except ValueError as error:
            return SimulationCacheResult(False, f"Flow resolution is invalid: {error}")
        if self._flow_lifecycle_state != "ATTACHED":
            return SimulationCacheResult(
                False,
                "Attach the airflow cache before changing Flow resolution.",
            )
        if self._flow_temporal_proof_task and not self._flow_temporal_proof_task.done():
            return SimulationCacheResult(
                False,
                "Wait for the temporal proof to finish before changing Flow "
                "resolution.",
            )
        if not self._flow_airflow_simulate_path:
            return SimulationCacheResult(
                False,
                "Kit-CAE Flow simulation path is unavailable.",
            )

        import carb
        import omni.kit.app
        import omni.timeline
        import omni.usd
        from omni.cae.schema import viz as cae_viz
        from omni.cae.schema import vtk as cae_vtk
        from pxr import Gf, Usd, UsdGeom

        stage = omni.usd.get_context().get_stage()
        if not stage:
            return SimulationCacheResult(
                False,
                "Flow resolution skipped: no open stage.",
            )
        emitter_prim = stage.GetPrimAtPath("/DTRS_KitCAE/DataSetEmitter")
        flow_simulate = stage.GetPrimAtPath(self._flow_airflow_simulate_path)
        if not emitter_prim or not emitter_prim.IsValid():
            return SimulationCacheResult(
                False,
                "Flow resolution skipped: DataSetEmitter is unavailable.",
            )
        if not flow_simulate or not flow_simulate.IsValid():
            return SimulationCacheResult(
                False,
                "Flow resolution skipped: flowSimulate is unavailable.",
            )
        field_prim = stage.GetPrimAtPath(
            "/DTRS_HoudiniVelocity/PointData/"
            f"{self.config.simulation_cache.velocity_field_name}"
        )
        if not field_prim or not field_prim.IsValid():
            return SimulationCacheResult(
                False,
                "Flow resolution skipped: temporal velocity field is unavailable.",
            )

        app = omni.kit.app.get_app()
        timeline = omni.timeline.get_timeline_interface()
        timeline_time = float(timeline.get_current_time())
        timeline_was_playing = bool(timeline.is_playing())
        emitter_operator = cae_viz.OperatorAPI(emitter_prim)
        enabled_attribute = emitter_operator.CreateEnabledAttr()
        voxelization_api = cae_viz.DatasetVoxelizationAPI(emitter_prim, "source")
        previous_mode = voxelization_api.GetVoxelSizeModeAttr().Get()
        previous_max_resolution = voxelization_api.GetMaxResolutionAttr().Get()
        if previous_mode is None or not isinstance(previous_max_resolution, int):
            return SimulationCacheResult(
                False,
                "Flow resolution skipped: DataSetEmitter voxelization state is "
                "unavailable.",
            )

        flow_environment_path = self._flow_airflow_simulate_path.removesuffix(
            "/flowSimulate"
        )
        previous_target = stage.GetEditTarget()
        timeline_restarted = False
        timeline_advancing = False
        source_after_restart = None
        trace_state: dict[str, object] = {}
        self._log_kit_cae_voxel_switch_trace(
            carb,
            phase="PRE_CHANGE",
            requested_max_resolution=max_resolution,
            previous_max_resolution=previous_max_resolution,
            stage=stage,
            timeline=timeline,
            emitter_prim=emitter_prim,
            emitter_operator=emitter_operator,
            voxelization_api=voxelization_api,
            flow_simulate=flow_simulate,
            field_prim=field_prim,
            cae_vtk=cae_vtk,
            Usd=Usd,
            trace_state=trace_state,
        )
        timeline.pause()
        previous_density_raw = flow_simulate.GetAttribute("densityCellSize").Get()
        previous_density_cell_size = (
            float(previous_density_raw)
            if isinstance(previous_density_raw, (int, float))
            and previous_density_raw > 0
            else self._flow_density_cell_size
        )
        previous_payload_attribute = emitter_prim.GetAttribute("nanoVdbVelocities")
        previous_payload = (
            previous_payload_attribute.Get()
            if previous_payload_attribute and previous_payload_attribute.IsValid()
            else None
        )
        previous_payload_fingerprint = self._kit_cae_nano_vdb_payload_fingerprint(
            previous_payload,
            len(previous_payload) if previous_payload is not None else 0,
        )
        tracer_root_path = "/DTRS_KitCAE/AirflowTracerEmitters"
        previous_tracer_radius = self._read_kit_cae_intake_tracer_radius(
            stage,
            tracer_root_path,
            UsdGeom,
        )
        completion_count_before = self._kit_cae_operator_completion_count(
            str(emitter_prim.GetPath())
        )
        stage.SetEditTarget(stage.GetSessionLayer())
        try:
            enabled_attribute.Set(False)
            await app.next_update_async()
            voxelization_api.CreateVoxelSizeModeAttr().Set("maxResolution")
            voxelization_api.CreateMaxResolutionAttr().Set(max_resolution)
            self._log_kit_cae_voxel_switch_trace(
                carb,
                phase="AFTER_MAX_RESOLUTION_SET",
                requested_max_resolution=max_resolution,
                previous_max_resolution=previous_max_resolution,
                stage=stage,
                timeline=timeline,
                emitter_prim=emitter_prim,
                emitter_operator=emitter_operator,
                voxelization_api=voxelization_api,
                flow_simulate=flow_simulate,
                field_prim=field_prim,
                cae_vtk=cae_vtk,
                Usd=Usd,
                trace_state=trace_state,
            )
            enabled_attribute.Set(True)
            rebuild = await self._await_kit_cae_fresh_dataset_emitter_rebuild(
                app,
                emitter_prim,
                flow_simulate,
                requested_max_resolution=max_resolution,
                previous_max_resolution=previous_max_resolution,
                previous_density_cell_size=previous_density_cell_size,
                previous_payload_fingerprint=previous_payload_fingerprint,
                completion_count_before=completion_count_before,
            )
            if not rebuild["fresh_rebuild"]:
                self._log_kit_cae_voxel_switch_abort(
                    carb,
                    requested_max_resolution=max_resolution,
                    readback_max_resolution=(
                        voxelization_api.GetMaxResolutionAttr().Get()
                    ),
                    density_cell_size=rebuild["density_cell_size"],
                    stage_meters_per_unit=float(UsdGeom.GetStageMetersPerUnit(stage)),
                    reason="DataSetEmitter output did not rebuild",
                )
                raise RuntimeError("DataSetEmitter output did not rebuild.")
            readiness = await flow_validation.wait_for_kit_cae_dataset_emitter_ready(
                app,
                emitter_prim,
            )
            if not readiness["ready"]:
                raise RuntimeError(
                    "DataSetEmitter did not become ready after re-voxelization."
                )
            self._log_kit_cae_voxel_switch_trace(
                carb,
                phase="AFTER_DATASET_EMITTER_READY",
                requested_max_resolution=max_resolution,
                previous_max_resolution=previous_max_resolution,
                stage=stage,
                timeline=timeline,
                emitter_prim=emitter_prim,
                emitter_operator=emitter_operator,
                voxelization_api=voxelization_api,
                flow_simulate=flow_simulate,
                field_prim=field_prim,
                cae_vtk=cae_vtk,
                Usd=Usd,
                trace_state=trace_state,
            )
            self._flow_density_cell_size = rebuild["density_cell_size"]
            self._flow_voxel_max_resolution = max_resolution
            new_tracer_radius = self._kit_cae_scaled_tracer_radius(
                self._flow_density_cell_size,
                self._flow_intake_tracer_radius_to_cell,
            )
            if new_tracer_radius is None:
                raise RuntimeError(
                    "Attached intake tracer radius baseline is unavailable."
                )
            self._author_kit_cae_intake_tracer_radius(
                stage,
                tracer_root_path,
                new_tracer_radius,
                Gf,
                UsdGeom,
            )
            await app.next_update_async()
            intake_tracer_radius = self._read_kit_cae_intake_tracer_radius(
                stage,
                tracer_root_path,
                UsdGeom,
            )
            if intake_tracer_radius is None:
                raise RuntimeError("Intake tracer radius did not author successfully.")
            self._log_kit_cae_voxel_rebuild(
                carb,
                requested_max_resolution=max_resolution,
                previous_density_cell_size=previous_density_cell_size,
                new_density_cell_size=self._flow_density_cell_size,
                fresh_rebuild=True,
                stage_meters_per_unit=float(UsdGeom.GetStageMetersPerUnit(stage)),
                previous_intake_tracer_radius=previous_tracer_radius,
                intake_tracer_radius=intake_tracer_radius,
            )
            await flow_smoke.pulse_kit_cae_flow_clear(app, flow_environment_path)
            self._log_kit_cae_voxel_switch_trace(
                carb,
                phase="AFTER_FLOW_CLEAR",
                requested_max_resolution=max_resolution,
                previous_max_resolution=previous_max_resolution,
                stage=stage,
                timeline=timeline,
                emitter_prim=emitter_prim,
                emitter_operator=emitter_operator,
                voxelization_api=voxelization_api,
                flow_simulate=flow_simulate,
                field_prim=field_prim,
                cae_vtk=cae_vtk,
                Usd=Usd,
                trace_state=trace_state,
            )
            self._restart_kit_cae_temporal_loop(timeline)
            timeline_restarted = True
            self._log_kit_cae_voxel_switch_trace(
                carb,
                phase="AFTER_LOOP_RESTART",
                requested_max_resolution=max_resolution,
                previous_max_resolution=previous_max_resolution,
                stage=stage,
                timeline=timeline,
                emitter_prim=emitter_prim,
                emitter_operator=emitter_operator,
                voxelization_api=voxelization_api,
                flow_simulate=flow_simulate,
                field_prim=field_prim,
                cae_vtk=cae_vtk,
                Usd=Usd,
                trace_state=trace_state,
            )
            initial_source = trace_state.get("source")
            timeline_time_before = float(timeline.get_current_time())
            for update_count in range(1, 31):
                await app.next_update_async()
                if update_count in (4, 12, 30):
                    self._log_kit_cae_voxel_switch_trace(
                        carb,
                        phase=f"POST_UPDATE_{update_count:02d}",
                        requested_max_resolution=max_resolution,
                        previous_max_resolution=previous_max_resolution,
                        stage=stage,
                        timeline=timeline,
                        emitter_prim=emitter_prim,
                        emitter_operator=emitter_operator,
                        voxelization_api=voxelization_api,
                        flow_simulate=flow_simulate,
                        field_prim=field_prim,
                        cae_vtk=cae_vtk,
                        Usd=Usd,
                        trace_state=trace_state,
                    )
            timeline_time_after = float(timeline.get_current_time())
            source_after_restart = trace_state.get("source")
            timeline_advancing = timeline_time_after > timeline_time_before
            if not timeline_advancing:
                raise RuntimeError("Timeline did not advance after restarting Flow.")
            if self._flow_temporal_end_time_code is None:
                raise RuntimeError(
                    "Temporal loop end is unavailable after restarting Flow."
                )
            if initial_source is None or source_after_restart == initial_source:
                raise RuntimeError(
                    "Temporal source did not leave the initial VTI after restarting "
                    "Flow."
                )
        except Exception as error:  # noqa: BLE001
            try:
                enabled_attribute.Set(False)
                voxelization_api.CreateVoxelSizeModeAttr().Set(previous_mode)
                voxelization_api.CreateMaxResolutionAttr().Set(previous_max_resolution)
                enabled_attribute.Set(True)
                await app.next_update_async()
                restored_readiness = (
                    await flow_validation.wait_for_kit_cae_dataset_emitter_ready(
                        app,
                        emitter_prim,
                    )
                )
                if not restored_readiness["ready"]:
                    raise RuntimeError(
                        "DataSetEmitter did not recover after restoring its "
                        "voxelization."
                    )
                restored_density_cell_size = flow_simulate.GetAttribute(
                    "densityCellSize"
                ).Get()
                self._flow_density_cell_size = (
                    float(restored_density_cell_size)
                    if isinstance(restored_density_cell_size, (int, float))
                    and restored_density_cell_size > 0
                    else previous_density_cell_size
                )
                self._flow_voxel_max_resolution = previous_max_resolution
                if previous_tracer_radius is not None:
                    self._author_kit_cae_intake_tracer_radius(
                        stage,
                        tracer_root_path,
                        previous_tracer_radius,
                        Gf,
                        UsdGeom,
                    )
                    await app.next_update_async()
                await flow_smoke.pulse_kit_cae_flow_clear(
                    app,
                    flow_environment_path,
                )
                if timeline_restarted:
                    self._restart_kit_cae_temporal_loop(timeline)
            except Exception as recovery_error:  # noqa: BLE001
                carb.log_error(
                    "DTRS FLOW / VOXEL RESOLUTION recovery failed: " f"{recovery_error}"
                )
            finally:
                enabled_attribute.Set(True)
            return SimulationCacheResult(
                False,
                f"Flow resolution failed; previous voxelization was restored: {error}",
            )
        finally:
            stage.SetEditTarget(previous_target)
            if not timeline_restarted:
                timeline.set_current_time(timeline_time)
                if timeline_was_playing:
                    timeline.play()

        stage_meters_per_unit = float(UsdGeom.GetStageMetersPerUnit(stage))
        carb.log_warn(
            self._format_flow_log_block(
                "VOXEL RESOLUTION",
                (
                    (
                        "",
                        (
                            ("Kit-CAE maxResolution:", max_resolution),
                            (
                                "VTI voxel size:",
                                self._format_flow_vti_voxel_size_mm(
                                    stage_meters_per_unit
                                ),
                            ),
                            (
                                "Flow density cell size:",
                                (
                                    self._kit_cae_physical_length_text(
                                        self._flow_density_cell_size,
                                        stage_meters_per_unit,
                                    )
                                ),
                            ),
                            ("Flow reset:", True),
                            ("VTI reimport:", False),
                            ("Timeline restarted:", timeline_restarted),
                            ("Loop start:", 0),
                            (
                                "Loop end:",
                                f"{self._flow_temporal_end_time_code:g}",
                            ),
                            ("Timeline advancing:", timeline_advancing),
                            (
                                "Source after restart:",
                                (
                                    source_after_restart.name
                                    if source_after_restart is not None
                                    else "unavailable"
                                ),
                            ),
                        ),
                    ),
                ),
            )
        )
        return SimulationCacheResult(
            True,
            f"Flow voxel resolution set to {max_resolution} without VTI reimport.",
        )

    async def apply_kit_cae_emitter_layout_in_kit(
        self,
        layout: EmitterLayoutConfig,
    ) -> SimulationCacheResult:
        """Rebuild only passive tracer sources from normalized layout controls."""

        try:
            validate_emitter_layout(layout)
        except ValueError as error:
            return SimulationCacheResult(False, f"Emitter layout is invalid: {error}")
        if self._flow_lifecycle_state == "ATTACHING":
            return SimulationCacheResult(
                False, "Kit-CAE Flow attach is still in progress."
            )
        if not self._flow_airflow_simulate_path:
            return SimulationCacheResult(
                False, "Attach the airflow cache before applying an emitter layout."
            )
        if not self._flow_world_bounds:
            return SimulationCacheResult(
                False, "Flow layout geometry is unavailable for this session."
            )

        import carb
        import omni.kit.app
        import omni.usd
        from omni.cae.data.commands import execute_command
        from pxr import Gf, Usd, UsdGeom

        stage = omni.usd.get_context().get_stage()
        if not stage:
            return SimulationCacheResult(
                False, "Emitter layout skipped: no open stage."
            )
        runtime_root = self._flow_airflow_simulate_path.removesuffix(
            "/FlowSimulation/flowSimulate"
        )
        tracer_root_path = f"{runtime_root}/AirflowTracerEmitters"
        bbox_path = f"{runtime_root}/BoundingBox"
        flow_environment_path = self._flow_airflow_simulate_path.removesuffix(
            "/flowSimulate"
        )
        flow_environment = stage.GetPrimAtPath(flow_environment_path)
        if not flow_environment or not flow_environment.IsValid():
            return SimulationCacheResult(
                False, "Flow environment is no longer attached."
            )

        try:
            derived = flow_smoke.kit_cae_front_intake_emitter_layout(
                stage,
                layout,
                self.config.fan_motion_bindings,
                self._flow_world_bounds,
                self.config.simulation_cache.intake_tracers.radius,
                self.config.simulation_cache.intake_tracers.front_offset,
                Gf,
                Usd,
                UsdGeom,
            )
        except (RuntimeError, ValueError) as error:
            return SimulationCacheResult(False, f"Emitter layout failed: {error}")

        previous_target = stage.GetEditTarget()
        stage.SetEditTarget(stage.GetSessionLayer())
        try:
            if stage.GetPrimAtPath(tracer_root_path).IsValid():
                stage.RemovePrim(tracer_root_path)
            app = omni.kit.app.get_app()
            for _ in range(self.EMITTER_REBUILD_SETTLE_UPDATES):
                await app.next_update_async()
            UsdGeom.Xform.Define(stage, tracer_root_path)
            tracer_config = replace(
                self.config.simulation_cache.intake_tracers,
                radius=derived.radius,
            )
            for index, position in enumerate(derived.positions, start=1):
                tracer_path = f"{tracer_root_path}/intake_{index:02d}"
                await execute_command(
                    "CreateCaeVizFlowSmokeInjector",
                    boundable_paths=[bbox_path],
                    prim_path=tracer_path,
                    layer_number=0,
                    mode="sphere",
                    simulation_prim=flow_environment,
                )
                await app.next_update_async()
                flow_smoke.configure_kit_cae_intake_tracer_emitter(
                    stage,
                    tracer_path,
                    position,
                    tracer_config,
                    Gf,
                    UsdGeom,
                )
            flow_smoke.hide_kit_cae_intake_tracer_meshes(
                stage,
                tracer_root_path,
                UsdGeom,
                expected_count=len(derived.positions),
            )
            for _ in range(self.EMITTER_REBUILD_SETTLE_UPDATES):
                await app.next_update_async()
            verified_emitters = flow_smoke.verify_kit_cae_intake_tracer_emitters(
                stage,
                tracer_root_path,
                len(derived.positions),
                UsdGeom,
            )
        except Exception as error:  # noqa: BLE001
            return SimulationCacheResult(
                False, f"Emitter layout rebuild failed: {error}"
            )
        finally:
            stage.SetEditTarget(previous_target)

        self.save_emitter_layout_override(layout)
        carb.log_warn(
            "\n".join(
                (
                    "=== DTRS FLOW / EMITTER LAYOUT =================================",
                    f"  Columns:             {layout.emitters_per_row}",
                    f"  Rows:                {layout.rows}",
                    f"  Total emitters:      {len(derived.positions)}",
                    f"  Sources verified:    {verified_emitters}",
                    f"  Depth:               {layout.depth:.0%}",
                    f"  Emitter size:        {layout.size:.0%}",
                    f"  Horizontal margin:   {layout.horizontal_margin:.0%}",
                    f"  Vertical margin:     {layout.vertical_margin:.0%}",
                    "",
                    "Derived:",
                    f"  Depth world plane:   {derived.depth_world_plane:.6g}",
                    f"  Radius:              {derived.radius:.6g}",
                    (
                        "  Flow densityCellSize: " f"{self._flow_density_cell_size:.6g}"
                        if self._flow_density_cell_size is not None
                        else "  Flow densityCellSize: unavailable"
                    ),
                    f"  Safe minimum radius: {derived.minimum_radius:.6g}",
                    "===============================================================",
                )
            )
        )
        return SimulationCacheResult(
            True,
            "Emitter layout applied and saved without VTI reload or Flow reset.",
        )

    def play_simulation_cache_in_kit(self) -> SimulationCacheResult:
        """Play the attached cache over its authored frame range."""

        if self._flow_lifecycle_state == "ATTACHING":
            return SimulationCacheResult(
                False, "Kit-CAE Flow attach is still in progress."
            )
        if self._flow_airflow_simulate_path:
            import omni.timeline

            timeline = omni.timeline.get_timeline_interface()
            if self._flow_temporal_end_time_code is not None:
                timeline.play(0.0, self._flow_temporal_end_time_code, True)
            else:
                timeline.play()
            return SimulationCacheResult(True, "Kit-CAE velocity-driven Flow started.")

        if not self._simulation_cache_contract:
            return SimulationCacheResult(
                False, "Attach the airflow cache before playback."
            )

        import omni.timeline

        contract = self._simulation_cache_contract
        timeline = omni.timeline.get_timeline_interface()
        timeline.play(
            contract.start_time_code,
            contract.end_time_code,
            True,
        )
        return SimulationCacheResult(True, "Airflow cache playback started.")

    def pause_simulation_cache_in_kit(self) -> SimulationCacheResult:
        """Pause the attached cache at the current frame."""

        if self._flow_lifecycle_state == "ATTACHING":
            return SimulationCacheResult(
                False, "Kit-CAE Flow attach is still in progress."
            )
        if self._flow_airflow_simulate_path:
            import omni.timeline

            omni.timeline.get_timeline_interface().pause()
            return SimulationCacheResult(True, "Kit-CAE velocity-driven Flow paused.")

        if not self._simulation_cache_contract:
            return SimulationCacheResult(
                False, "Attach the airflow cache before playback."
            )

        import omni.timeline

        omni.timeline.get_timeline_interface().pause()
        return SimulationCacheResult(True, "Airflow cache paused.")

    def reset_simulation_cache_in_kit(self) -> SimulationCacheResult:
        """Return the attached cache to its first authored frame."""

        if self._flow_lifecycle_state == "ATTACHING":
            return SimulationCacheResult(
                False, "Kit-CAE Flow attach is still in progress."
            )
        if self._flow_airflow_simulate_path:
            import omni.timeline
            import omni.usd

            stage = omni.usd.get_context().get_stage()
            simulate = (
                stage.GetPrimAtPath(self._flow_airflow_simulate_path) if stage else None
            )
            if not simulate or not simulate.IsValid():
                return SimulationCacheResult(
                    False, "Flow airflow is no longer attached."
                )
            force_clear = simulate.GetAttribute("forceClear")
            force_clear.Set(True)
            asyncio.ensure_future(self._clear_flow_after_update(force_clear))
            timeline = omni.timeline.get_timeline_interface()
            timeline.pause()
            timeline.set_current_time(0.0)
            return SimulationCacheResult(True, "Kit-CAE velocity-driven Flow reset.")

        if not self._simulation_cache_contract:
            return SimulationCacheResult(
                False, "Attach the airflow cache before playback."
            )

        import omni.timeline

        contract = self._simulation_cache_contract
        timeline = omni.timeline.get_timeline_interface()
        timeline.pause()
        timeline.set_current_time(
            contract.start_time_code / contract.time_codes_per_second
        )
        return SimulationCacheResult(True, "Airflow cache reset to its first frame.")

    async def request_attached_workload_transition_in_kit(
        self,
        workload_mode: str,
        status_callback: StatusCallback | None = None,
    ) -> SimulationCacheResult:
        """Request an in-place transition from active to semantic workload airflow.

        Telemetry has already accepted ``workload_mode`` before this consumer
        runs.  Until live Kit-CAE consumption proves the target, the confirmed
        active selector remains visible and the requested selector is pending.
        Transition IDs make every async checkpoint reject a superseded request;
        this method never attaches, detaches, resets, or rebuilds Flow.
        """

        if self._flow_lifecycle_state != "ATTACHED":
            return SimulationCacheResult(
                True, "Flow remains detached; no airflow transition requested."
            )

        import carb

        active_binding = self._flow_session_workload_binding
        target_binding = self.resolve_workload_airflow_binding(workload_mode)
        if active_binding is None:
            return SimulationCacheResult(
                False, "Attached Flow has no active airflow selector."
            )
        pending_binding = self._flow_pending_workload_binding
        if pending_binding is not None:
            if pending_binding.dataset_identity == target_binding.dataset_identity:
                return SimulationCacheResult(
                    True,
                    "Airflow transition already targets the current workload.",
                )
            self._flow_transition_sequence += 1
            transition_id = f"T{self._flow_transition_sequence:04d}"
            superseded_transition_id = self._flow_active_transition_id or "unknown"
            self._flow_active_transition_id = transition_id
            self._flow_pending_workload_binding = target_binding
            carb.log_warn(
                self._format_airflow_transition_log_block(
                    "SUPERSEDED",
                    (
                        ("Transition:", superseded_transition_id),
                        ("Target:", pending_binding.dataset_identity),
                        ("Superseded by transition:", transition_id),
                        ("New target:", target_binding.dataset_identity),
                        ("Last committed active:", active_binding.dataset_identity),
                        ("Old commit allowed:", False),
                    ),
                )
            )
            if target_binding.dataset_identity == active_binding.dataset_identity:
                self._flow_pending_workload_binding = None
                self._flow_active_transition_id = None
                return SimulationCacheResult(
                    True,
                    "Attached airflow already matches the latest workload.",
                )
        if target_binding.dataset_identity == active_binding.dataset_identity:
            self._flow_pending_workload_binding = None
            return SimulationCacheResult(
                True, "Attached airflow already matches workload."
            )

        if pending_binding is None:
            self._flow_transition_sequence += 1
            transition_id = f"T{self._flow_transition_sequence:04d}"
            self._flow_active_transition_id = transition_id
        self._flow_pending_workload_binding = target_binding
        proof_superseded = self._cancel_kit_cae_temporal_proof(
            reason="SUPERSEDED_BY_WORKLOAD_TRANSITION"
        )
        carb.log_warn(
            self._format_airflow_transition_log_block(
                "REQUEST",
                (
                    ("Transition:", transition_id),
                    ("Semantic workload:", workload_mode),
                    ("Active airflow:", active_binding.dataset_identity),
                    ("Target airflow:", target_binding.dataset_identity),
                    ("Pending airflow:", target_binding.dataset_identity),
                    (
                        "Temporal proof state:",
                        "CANCELLED" if proof_superseded else "UNCHANGED",
                    ),
                    (
                        "Temporal proof reason:",
                        "WORKLOAD_TRANSITION" if proof_superseded else "not_running",
                    ),
                ),
            )
        )
        try:
            target_dataset = discover_airflow_dataset(
                self.config.asset_root, target_binding.dataset
            )
            signature = build_dataset_validation_signature(
                target_dataset, self.config.simulation_cache.velocity_field_name
            )
            validation_was_hit = bool(
                self._flow_validation_cache.lookup(signature).preflight
            )
        except AirflowDatasetError as error:
            return self._finalize_airflow_failure(
                semantic_workload=workload_mode,
                requested_binding=target_binding,
                reason=str(error),
                failure_stage="dataset_discovery",
                logger=carb.log_error,
                status_callback=status_callback,
            )
        except RuntimeError as error:
            return self._finalize_airflow_failure(
                semantic_workload=workload_mode,
                requested_binding=target_binding,
                reason=str(error),
                failure_stage="validation_signature",
                logger=carb.log_error,
                status_callback=status_callback,
            )
        try:
            lease = await self.acquire_airflow_validation_for_transition(target_binding)
        except BackgroundValidationError as error:
            if not self._is_current_airflow_transition(transition_id, target_binding):
                return self._superseded_transition_result(transition_id, target_binding)
            return self._finalize_airflow_failure(
                semantic_workload=workload_mode,
                requested_binding=target_binding,
                reason=str(error),
                failure_stage="validation",
                logger=carb.log_error,
                status_callback=status_callback,
                transition_id=transition_id,
            )
        receipt = lease.receipt
        lease.release()
        if not self._is_current_airflow_transition(transition_id, target_binding):
            return self._superseded_transition_result(transition_id, target_binding)
        try:
            family = self.validate_registered_airflow_dataset_family()
            if not family.family_compatible:
                raise AirflowDatasetFamilyCompatibilityError(
                    "Airflow family compatibility mismatch: dataset=family; "
                    "property=family_compatible; expected=True; actual=False."
                )
        except (
            AirflowDatasetError,
            AirflowDatasetFamilyCompatibilityError,
            RuntimeError,
        ) as error:
            carb.log_error(
                self._format_airflow_transition_log_block(
                    "FAMILY COMPATIBILITY",
                    (
                        ("Transition:", transition_id),
                        ("Active:", active_binding.dataset_identity),
                        ("Target:", target_binding.dataset_identity),
                        ("Family compatible:", False),
                        ("Reason:", str(error)),
                    ),
                )
            )
            return self._finalize_airflow_failure(
                semantic_workload=workload_mode,
                requested_binding=target_binding,
                reason=str(error),
                failure_stage="family_compatibility",
                logger=carb.log_error,
                status_callback=status_callback,
                transition_id=transition_id,
            )
        carb.log_warn(
            self._format_airflow_transition_log_block(
                "FAMILY COMPATIBILITY",
                (
                    ("Transition:", transition_id),
                    ("Active:", active_binding.dataset_identity),
                    ("Target:", target_binding.dataset_identity),
                    ("Members:", ", ".join(family.member_selectors)),
                    ("Family compatible:", family.family_compatible),
                    ("Phase mapping:", family.phase_mapping),
                    ("VTI preflight:", "REUSED"),
                    ("RESULT:", "PASS"),
                ),
            )
        )
        carb.log_warn(
            self._format_airflow_transition_log_block(
                "READY",
                (
                    ("Transition:", transition_id),
                    ("Target:", target_binding.dataset_identity),
                    ("Validation:", "REUSED" if validation_was_hit else "PASS"),
                    ("Receipt:", receipt.signature.compact_digest),
                    ("Pending airflow:", target_binding.dataset_identity),
                    ("Waiting for sample boundary:", True),
                ),
            )
        )
        result = await self._retarget_attached_workload_in_kit(
            active_binding,
            target_binding,
            target_dataset,
            status_callback,
            transition_id,
        )
        if result.success:
            return result
        if not self._is_current_airflow_transition(transition_id, target_binding):
            return self._superseded_transition_result(transition_id, target_binding)
        if self._is_current_airflow_transition(transition_id, target_binding):
            return self._finalize_airflow_failure(
                semantic_workload=workload_mode,
                requested_binding=target_binding,
                reason=result.message,
                failure_stage="runtime_transition",
                logger=carb.log_error,
                status_callback=status_callback,
                transition_id=transition_id,
            )
        return result

    async def _retarget_attached_workload_in_kit(
        self,
        active_binding,
        target_binding,
        target_dataset,
        status_callback: StatusCallback | None,
        transition_id: str,
    ) -> SimulationCacheResult:
        """Retarget at a sample boundary and commit only after runtime proof.

        The target sample is selected through normalized phase mapping, then
        authored as a session-layer FieldArray override.  Kit-CAE is allowed to
        consume that change naturally on its next temporal update—forced CAE
        refresh is deliberately avoided here because it can re-enter VTK.  The
        direct-Attach velocity-scale contract is applied and read back before
        the pending selector becomes active.
        """

        import carb
        import omni.kit.app
        import omni.timeline
        import omni.usd
        from omni.cae.schema import vtk as cae_vtk
        from pxr import Sdf, Usd

        if not self._is_current_airflow_transition(transition_id, target_binding):
            return self._superseded_transition_result(transition_id, target_binding)
        cache = self.config.simulation_cache
        stage = omni.usd.get_context().get_stage()
        timeline = omni.timeline.get_timeline_interface()
        field_prim = (
            stage.GetPrimAtPath(
                f"/DTRS_HoudiniVelocity/PointData/{cache.velocity_field_name}"
            )
            if stage
            else None
        )
        emitter_prim = (
            stage.GetPrimAtPath("/DTRS_KitCAE/DataSetEmitter") if stage else None
        )
        if not all(prim and prim.IsValid() for prim in (field_prim, emitter_prim)):
            return SimulationCacheResult(
                False, "Attached airflow runtime objects are unavailable."
            )
        try:
            active_dataset = discover_airflow_dataset(
                self.config.asset_root, active_binding.dataset
            )
            active_time_code = (
                float(timeline.get_current_time()) * stage.GetTimeCodesPerSecond()
            )
            active_source = flow_temporal.kit_cae_selected_velocity_asset(
                field_prim, active_time_code, cae_vtk, Usd
            )
            phase_dataset, active_index = self._resolve_live_airflow_phase_dataset(
                active_dataset,
                active_source,
            )
        except (AirflowDatasetError, ValueError) as error:
            return SimulationCacheResult(
                False, f"Active airflow phase is unavailable: {error}"
            )

        time_codes = self._flow_temporal_sample_time_codes
        if len(time_codes) < 2 or len(
            target_dataset.velocity_vti_sequence_paths
        ) != len(time_codes):
            return SimulationCacheResult(
                False,
                "Target airflow sequence cannot preserve the attached temporal phase.",
            )
        target_index = airflow_family.next_normalized_phase_target_sample_index(
            active_index,
            len(phase_dataset.velocity_vti_sequence_paths),
            len(target_dataset.velocity_vti_sequence_paths),
        )
        target_source = target_dataset.velocity_vti_sequence_paths[target_index]
        target_time_code = time_codes[target_index]

        if not await self._wait_for_attached_airflow_playback(
            timeline,
            omni.kit.app.get_app().next_update_async,
            transition_id,
            target_binding,
        ):
            return self._superseded_transition_result(transition_id, target_binding)

        emitter_path = str(emitter_prim.GetPath())
        velocity_scale_attribute = emitter_prim.GetAttribute("velocityScale")
        velocity_scale_before = (
            velocity_scale_attribute.Get()
            if velocity_scale_attribute and velocity_scale_attribute.IsValid()
            else None
        )
        flow_resets_before = sum(
            bool(record.get("flow_reset")) for record in self._flow_temporal_records
        )
        completions_before = self._kit_cae_operator_completion_count(emitter_path)
        payload_attr = emitter_prim.GetAttribute("nanoVdbVelocities")
        payload_before = (
            payload_attr.Get() if payload_attr and payload_attr.IsValid() else None
        )
        payload_before_digest = flow_temporal.kit_cae_payload_digest(
            payload_before, len(payload_before) if payload_before is not None else 0
        )
        previous_edit_target = stage.GetEditTarget()
        stage.SetEditTarget(stage.GetSessionLayer())
        try:
            flow_temporal.author_kit_cae_temporal_velocity_samples_except_index(
                field_prim,
                target_dataset.velocity_vti_sequence_paths,
                time_codes,
                active_index,
                cae_vtk,
                Sdf,
                Usd,
            )
        finally:
            stage.SetEditTarget(previous_edit_target)
        app = omni.kit.app.get_app()
        retarget_result = await flow_temporal.retarget_kit_cae_temporal_source_in_place(
            stage,
            field_prim,
            target_source,
            target_time_code,
            cae_vtk,
            Sdf,
            Usd,
            refresh=False,
        )
        if not self._is_current_airflow_transition(transition_id, target_binding):
            return self._superseded_transition_result(transition_id, target_binding)
        carb.log_warn(
            self._format_airflow_transition_log_block(
                "RETARGET",
                (
                    ("Transition:", transition_id),
                    ("From source:", active_source.name),
                    ("To source:", target_source.name),
                    ("Sample index:", target_index),
                    ("Phase preserved:", True),
                    ("Retarget readback:", retarget_result.resolved_source.name),
                ),
            )
        )
        carb.log_warn(
            self._format_airflow_transition_log_block(
                "AWAIT CONSUMPTION",
                (
                    ("Transition:", transition_id),
                    ("Target:", target_binding.dataset_identity),
                    ("Forced refresh:", False),
                ),
            )
        )

        runtime_consumed = False
        payload_changed = False
        observed_source = active_source
        observed_sources: set[Path] = set()
        for _ in range(240):
            await app.next_update_async()
            if not self._is_current_airflow_transition(transition_id, target_binding):
                return self._superseded_transition_result(transition_id, target_binding)
            if not timeline.is_playing():
                continue
            observed_source = flow_temporal.kit_cae_selected_velocity_asset(
                field_prim,
                float(timeline.get_current_time()) * stage.GetTimeCodesPerSecond(),
                cae_vtk,
                Usd,
            )
            if observed_source is not None:
                observed_sources.add(observed_source)
            payload = (
                payload_attr.Get() if payload_attr and payload_attr.IsValid() else None
            )
            payload_changed = (
                flow_temporal.kit_cae_payload_digest(
                    payload, len(payload) if payload is not None else 0
                )
                != payload_before_digest
            )
            runtime_consumed = (
                observed_source == target_source
                and self._kit_cae_operator_completion_count(emitter_path)
                > completions_before
                and payload_changed
            )
            if runtime_consumed:
                break
        if not runtime_consumed:
            carb.log_error(
                self._format_airflow_transition_log_block(
                    "CONSUMPTION TIMEOUT",
                    (
                        ("Transition:", transition_id),
                        ("Target:", target_binding.dataset_identity),
                        (
                            "Last observed source:",
                            observed_source.name if observed_source else "unavailable",
                        ),
                        ("Observed sample boundaries:", len(observed_sources)),
                        ("Forced refresh:", False),
                    ),
                )
            )
            return SimulationCacheResult(
                False, "Airflow transition is pending live runtime consumption."
            )

        carb.log_warn(
            self._format_airflow_transition_log_block(
                "CONSUMED",
                (
                    ("Transition:", transition_id),
                    ("Observed source:", observed_source.name),
                    ("Consumption:", "native_temporal_update"),
                    ("Operator update observed:", True),
                    ("Payload changed:", payload_changed),
                ),
            )
        )

        if not self._is_current_airflow_transition(transition_id, target_binding):
            return self._superseded_transition_result(transition_id, target_binding)
        await flow_temporal.retarget_kit_cae_temporal_source_in_place(
            stage,
            field_prim,
            target_dataset.velocity_vti_sequence_paths[active_index],
            time_codes[active_index],
            cae_vtk,
            Sdf,
            Usd,
            refresh=False,
        )
        if not self._is_current_airflow_transition(transition_id, target_binding):
            return self._superseded_transition_result(transition_id, target_binding)

        try:
            resolve_runtime_contract = (
                flow_validation.resolve_live_kit_cae_direct_attach_runtime_contract
            )
            target_runtime_contract = await resolve_runtime_contract(
                emitter_prim,
                Usd,
                self.config.simulation_cache.smoke_tuning.velocity_scale_multiplier,
                Usd.TimeCode(self._flow_temporal_sample_time_codes[0]),
            )
        except RuntimeError as error:
            return SimulationCacheResult(
                False,
                f"Airflow transition target runtime contract failed: {error}",
            )
        if not self._is_current_airflow_transition(transition_id, target_binding):
            return self._superseded_transition_result(transition_id, target_binding)
        target_base_velocity_scale = target_runtime_contract["base_velocity_scale"]
        target_direct_attach_equivalent = target_runtime_contract[
            "effective_velocity_scale"
        ]

        # A dataset-specific transport scale is authored by Kit-CAE during a
        # direct Attach.  Do not guess it from workload names or VTI filenames.
        target_velocity_scale_applied = False
        velocity_scale_apply_error: str | None = None
        velocity_scale_after = velocity_scale_before
        velocity_scale_edit_target = stage.GetEditTarget()
        stage.SetEditTarget(stage.GetSessionLayer())
        try:
            apply_velocity_scale = flow_smoke.apply_kit_cae_direct_attach_velocity_scale
            velocity_scale_after = apply_velocity_scale(
                emitter_prim,
                base_velocity_scale=target_base_velocity_scale,
                velocity_scale_multiplier=(
                    self.config.simulation_cache.smoke_tuning.velocity_scale_multiplier
                ),
            )
            target_velocity_scale_applied = True
        except RuntimeError as error:
            velocity_scale_apply_error = str(error)
            velocity_scale_after = (
                velocity_scale_attribute.Get()
                if velocity_scale_attribute and velocity_scale_attribute.IsValid()
                else None
            )
        finally:
            stage.SetEditTarget(velocity_scale_edit_target)
        carb.log_warn(
            self._format_airflow_transition_log_block(
                "VELOCITY SCALE APPLY",
                (
                    ("Transition:", transition_id),
                    ("Target selector:", target_binding.dataset_identity),
                    ("Target value:", target_direct_attach_equivalent),
                    (
                        "Write path/function:",
                        "flow_smoke.apply_kit_cae_direct_attach_velocity_scale",
                    ),
                    (
                        "Runtime property/path:",
                        f"{emitter_prim.GetPath()}.velocityScale",
                    ),
                    ("Value before:", velocity_scale_before),
                    ("Write attempted:", True),
                    ("Write succeeded:", target_velocity_scale_applied),
                    ("Value after:", velocity_scale_after),
                    ("Reason:", velocity_scale_apply_error or "none"),
                ),
            )
        )
        if not target_velocity_scale_applied:
            return SimulationCacheResult(
                False,
                "Airflow transition velocityScale write failed: "
                + (velocity_scale_apply_error or "unknown reason"),
            )

        if not self._is_current_airflow_transition(transition_id, target_binding):
            return self._superseded_transition_result(transition_id, target_binding)

        payload_after = (
            payload_attr.Get() if payload_attr and payload_attr.IsValid() else None
        )
        payload_updated = (
            flow_temporal.kit_cae_payload_digest(
                payload_after, len(payload_after) if payload_after is not None else 0
            )
            != payload_before_digest
        )
        couple_rate_attribute = emitter_prim.GetAttribute("coupleRateVelocity")
        couple_rate_velocity = (
            couple_rate_attribute.Get()
            if couple_rate_attribute and couple_rate_attribute.IsValid()
            else None
        )
        operator_ready = (
            payload_after is not None
            and len(payload_after) > 0
            and float(couple_rate_velocity or 0.0) > 0.0
        )
        target_family_observed = (
            observed_source in target_dataset.velocity_vti_sequence_paths
        )
        flow_resets_after = sum(
            bool(record.get("flow_reset")) for record in self._flow_temporal_records
        )
        flow_resets_delta = flow_resets_after - flow_resets_before
        timeline_continuous = timeline.is_playing()
        velocity_scale_matches_target = (
            target_direct_attach_equivalent is not None
            and velocity_scale_after is not None
            and abs(float(velocity_scale_after) - target_direct_attach_equivalent)
            < 1e-6
        )
        runtime_contract_match = (
            runtime_consumed
            and target_family_observed
            and velocity_scale_matches_target
            and operator_ready
            and payload_updated
            and flow_resets_delta == 0
            and timeline_continuous
        )
        carb.log_warn(
            self._format_airflow_transition_log_block(
                "RUNTIME CONTRACT",
                (
                    ("Transition:", transition_id),
                    ("Target selector:", target_binding.dataset_identity),
                    (
                        "Target direct-Attach velocityScale:",
                        (
                            target_direct_attach_equivalent
                            if target_direct_attach_equivalent is not None
                            else "unavailable"
                        ),
                    ),
                    ("Runtime velocityScale before:", velocity_scale_before),
                    ("Applied:", target_velocity_scale_applied),
                    ("Runtime velocityScale after:", velocity_scale_after),
                    ("Effective velocityScale after:", velocity_scale_after),
                    ("Target VTI family observed:", target_family_observed),
                    ("Operator ready:", operator_ready),
                    ("Payload updated:", payload_updated),
                    ("Flow resets delta:", flow_resets_delta),
                    ("Timeline continuous:", timeline_continuous),
                    ("Runtime contract match:", runtime_contract_match),
                ),
            )
        )
        if not runtime_contract_match:
            return SimulationCacheResult(
                False,
                "Airflow transition remains pending: target direct-Attach "
                "runtime contract is not proven.",
            )

        if not self._commit_attached_workload_transition(
            target_binding,
            runtime_consumed,
            runtime_contract_match=True,
            transition_id=transition_id,
        ):
            return self._superseded_transition_result(transition_id, target_binding)
        self._flow_base_velocity_scale = target_base_velocity_scale
        self._flow_temporal_records = []
        self._flow_temporal_failure = None
        carb.log_warn(
            self._format_airflow_transition_log_block(
                "COMMIT",
                (
                    ("Transition:", transition_id),
                    ("Active airflow:", target_binding.dataset_identity),
                    ("Pending airflow:", "None"),
                    ("Runtime source:", observed_source.name),
                    ("Runtime consumed:", runtime_consumed),
                    ("Flow resets delta:", flow_resets_delta),
                    ("Timeline continuous:", timeline_continuous),
                    ("RESULT:", "PASS"),
                ),
            )
        )
        if status_callback:
            status_callback(
                f"Airflow transitioned to {target_binding.dataset_identity}."
            )
        return SimulationCacheResult(
            True, f"Airflow transitioned to {target_binding.dataset_identity}."
        )

    async def _wait_for_attached_airflow_playback(
        self,
        timeline,
        next_update_async,
        transition_id: str,
        target_binding,
    ) -> bool:
        """Wait for the operator's playback intent without changing it."""

        while not timeline.is_playing():
            await next_update_async()
            if not self._is_current_airflow_transition(transition_id, target_binding):
                return False
        return self._is_current_airflow_transition(transition_id, target_binding)

    async def _observe_attached_target_family_proof(
        self,
        app,
        timeline,
        stage,
        field_prim,
        emitter_prim,
        target_dataset,
        target_index: int,
        first_source: Path,
        target_velocity_scale: float,
        cae_vtk,
        Usd,
    ) -> dict[str, object]:
        """Optional development diagnostic; never blocks a runtime transition."""

        expected_paths = target_dataset.velocity_vti_sequence_paths
        observed: list[Path] = [first_source]
        previous_source: Path | None = first_source
        runtime_contract_match = True
        for _ in range(len(expected_paths) * 90):
            if self._flow_lifecycle_state != "ATTACHED" or not timeline.is_playing():
                break
            source = flow_temporal.kit_cae_selected_velocity_asset(
                field_prim,
                float(timeline.get_current_time()) * stage.GetTimeCodesPerSecond(),
                cae_vtk,
                Usd,
            )
            if source is not None and source != previous_source:
                observed.append(source)
                previous_source = source
                velocity_scale = emitter_prim.GetAttribute("velocityScale").Get()
                payload = emitter_prim.GetAttribute("nanoVdbVelocities").Get()
                couple_rate = emitter_prim.GetAttribute("coupleRateVelocity").Get()
                runtime_contract_match = runtime_contract_match and (
                    velocity_scale is not None
                    and abs(float(velocity_scale) - target_velocity_scale) < 1e-6
                    and payload is not None
                    and len(payload) > 0
                    and float(couple_rate or 0.0) > 0.0
                )
                if len(observed) == len(expected_paths):
                    break
            await app.next_update_async()
        return self._evaluate_target_family_proof(
            expected_paths,
            target_index,
            tuple(observed),
            runtime_contract_match,
        )

    @staticmethod
    def _evaluate_target_family_proof(
        expected_paths: tuple[Path, ...],
        start_index: int,
        observed_paths: tuple[Path, ...],
        runtime_contract_match: bool,
    ) -> dict[str, object]:
        """Evaluate target samples without conflating them with old proof state."""

        total = len(expected_paths)
        expected = tuple(
            expected_paths[(start_index + offset) % total] for offset in range(total)
        )
        observed = observed_paths[:total]
        foreign = sum(source not in expected_paths for source in observed)
        ordered = len(observed) == total and observed == expected
        return {
            "samples_observed": f"{len(observed)}/{total}",
            "foreign_family_samples": foreign,
            "forward_transitions": max(len(observed) - 1, 0),
            "loop_closure": "PASS" if ordered else "FAIL",
            "runtime_contract_match": runtime_contract_match,
            "last_source": observed[-1].name if observed else "unavailable",
            "passed": ordered and foreign == 0 and runtime_contract_match,
        }

    def _commit_attached_workload_transition(
        self,
        target_binding,
        runtime_consumed: bool,
        *,
        runtime_contract_match: bool = True,
        transition_id: str | None = None,
    ) -> bool:
        """Commit immediately after the live target runtime contract is proven."""

        if not (runtime_consumed and runtime_contract_match):
            return False
        if transition_id is not None and not self._is_current_airflow_transition(
            transition_id, target_binding
        ):
            return False
        self._flow_session_workload_binding = target_binding
        self._flow_pending_workload_binding = None
        if transition_id is not None:
            self._flow_active_transition_id = None
        self._flow_last_airflow_failure = None
        return True

    def _is_current_airflow_transition(
        self, transition_id: str, target_binding
    ) -> bool:
        """Return whether this async path still owns terminal transition state."""

        return (
            self._flow_lifecycle_state == "ATTACHED"
            and self._flow_active_transition_id == transition_id
            and self._flow_pending_workload_binding == target_binding
        )

    def _resolve_live_airflow_phase_dataset(self, committed_dataset, live_source: Path):
        """Resolve phase from the actual temporal family after a superseded retarget."""

        candidates = (committed_dataset,) + tuple(
            dataset
            for dataset in discover_airflow_dataset_registry(
                self.config.asset_root,
                self.config.simulation_cache.airflow_dataset.root,
            )
            if dataset != committed_dataset
        )
        for dataset in candidates:
            try:
                return dataset, dataset.velocity_vti_sequence_paths.index(live_source)
            except ValueError:
                continue
        raise ValueError(
            "Live temporal source is absent from the registered airflow family: "
            f"{live_source}"
        )

    @staticmethod
    def _superseded_transition_result(
        transition_id: str,
        target_binding,
    ) -> SimulationCacheResult:
        """End a stale async path without treating supersession as failure."""

        return SimulationCacheResult(
            True,
            f"Airflow transition {transition_id} to "
            f"{target_binding.dataset_identity} was superseded.",
        )

    def _finalize_airflow_failure(
        self,
        *,
        semantic_workload: str,
        requested_binding,
        reason: str,
        failure_stage: str,
        logger: Callable[[str], None] | None = None,
        status_callback: StatusCallback | None = None,
        transition_id: str | None = None,
    ) -> SimulationCacheResult:
        """End an unsuccessful airflow operation without changing semantic workload."""

        if transition_id is not None and not self._is_current_airflow_transition(
            transition_id, requested_binding
        ):
            return self._superseded_transition_result(transition_id, requested_binding)

        active_binding = self._flow_session_workload_binding
        self._flow_pending_workload_binding = None
        if transition_id is not None:
            self._flow_active_transition_id = None
        pending_cleared = self._flow_pending_workload_binding is None
        attached = (
            self._flow_lifecycle_state == "ATTACHED" and active_binding is not None
        )
        active_selector = active_binding.dataset_identity if attached else "DETACHED"
        requested_selector = (
            requested_binding.dataset_identity
            if requested_binding is not None
            else "unresolved"
        )
        action = "kept_previous_safe_dataset" if attached else "remained_detached"
        self._flow_last_airflow_failure = {
            "semantic_workload": semantic_workload,
            "requested_airflow_selector": requested_selector,
            "active_airflow_selector": active_selector,
            "reason": reason,
            "failure_stage": failure_stage,
            "action": action,
        }
        message = (
            "Airflow failed | "
            f"workload={semantic_workload} | requested={requested_selector} | "
            f"active={active_selector} | action={action} | reason={reason}"
        )
        log_block = self._format_airflow_transition_log_block(
            "FAILED",
            (
                ("Semantic workload:", semantic_workload),
                ("Requested airflow:", requested_selector),
                ("Active airflow:", active_selector),
                ("Reason:", reason),
                ("Failure stage:", failure_stage),
                ("Action:", action),
                ("Telemetry rolled back:", False),
                ("Pending cleared:", pending_cleared),
                ("Flow reset:", False),
                ("RESULT:", "FAIL"),
            ),
        )
        if logger:
            logger(log_block)
        if status_callback:
            status_callback(message)
        return SimulationCacheResult(False, message)

    @staticmethod
    def _format_airflow_transition_log_block(
        event: str,
        fields: tuple[tuple[str, object], ...],
    ) -> str:
        """Format transition evidence in the same bounded Kit Warning style."""

        rule = "=" * 63
        lines = [f"=== DTRS AIRFLOW TRANSITION / {event} {rule}"]
        lines.extend(f"  {label:<43}{value}" for label, value in fields)
        lines.extend(("", rule))
        return with_dtrs_local_timestamp("\n".join(lines))

    def capture_gpu_profile_in_kit(self) -> SimulationCacheResult:
        """Write the current Hydra GPU profiler sample to an ignored artifact."""

        import carb
        import omni.hydra.engine.stats as engine_stats
        import omni.kit.viewport.utility as viewport_utility

        viewport = viewport_utility.get_active_viewport()
        if not viewport:
            return SimulationCacheResult(
                False, "GPU profile skipped: no active viewport."
            )

        output_dir = self.config.repo_root / "out" / "diagnostics"
        output_dir.mkdir(parents=True, exist_ok=True)
        carb.settings.get_settings().set("/profiler/filePath", str(output_dir))

        profiler = engine_stats.HydraEngineStats(
            hydra_engine_name=viewport.hydra_engine,
        )
        profile_path = self._write_gpu_profile(
            output_dir,
            viewport.hydra_engine,
            profiler.get_gpu_profiler_result(),
        )
        carb.log_info(f"DTRS GPU profile saved: {profile_path}")

        return SimulationCacheResult(
            True,
            f"GPU profile saved: {profile_path}",
        )

    @staticmethod
    def _write_gpu_profile(
        output_dir: Path,
        hydra_engine: str,
        gpu_profiler_result,
    ) -> Path:
        """Serialize profiler data because Kit's save helper is unreliable."""

        output_dir.mkdir(parents=True, exist_ok=True)
        profile_path = (
            output_dir / f"airflow_gpu_profile_{int(time.time() * 1000)}.json"
        )
        payload = {
            "hydra_engine": hydra_engine,
            "gpu_profiler": gpu_profiler_result,
        }
        profile_path.write_text(
            json.dumps(payload, indent=2, default=str),
            encoding="utf-8",
        )
        return profile_path

    def _write_kit_cae_flow_parity_snapshot(
        self,
        stage,
        *,
        dataset_path: str,
        field_path: str,
        bbox_path: str,
        flow_environment_path: str,
        tracer_root_path: str,
        boundary_emitter_path: str,
        dataset_emitter_path: str,
    ) -> Path:
        """Persist a read-only effective-state snapshot for the Flow parity audit."""

        snapshot = capture_flow_scene(
            stage,
            label="DTRS_CASE03_VTI_FLOW",
            paths={
                "dataset": dataset_path,
                "velocity_field": field_path,
                "bounding_box": bbox_path,
                "flow_environment": flow_environment_path,
                "flow_simulate": f"{flow_environment_path}/flowSimulate",
                "flow_offscreen": f"{flow_environment_path}/flowOffscreen",
                "flow_render": f"{flow_environment_path}/flowRender",
                "ray_march": f"{flow_environment_path}/flowRender/rayMarch",
                "debug_volume": f"{flow_environment_path}/flowOffscreen/debugVolume",
                "airflow_tracer_emitters": tracer_root_path,
                "airflow_tracer_first": f"{tracer_root_path}/intake_01/EmitterSphere",
                "boundary_emitter_root": boundary_emitter_path,
                "dataset_emitter": dataset_emitter_path,
            },
        )
        return write_flow_snapshot(
            snapshot,
            self.config.repo_root
            / "out"
            / "diagnostics"
            / "kit_cae_flow_snapshot_dtrs.json",
        )

    def sync_simulation_cache_frame_in_kit(self) -> bool:
        """Native USD volume playback follows the Kit timeline automatically."""

        return False

    async def detach_simulation_cache_in_kit(self) -> SimulationCacheResult:
        """Deactivate Flow, flush Kit updates, then remove DTRS runtime prims."""

        import carb
        import omni.kit.app
        import omni.timeline
        import omni.usd
        from omni.cae.schema import viz as cae_viz

        if self._flow_lifecycle_state == "DETACHING":
            return SimulationCacheResult(
                False, "Airflow cache detach is already in progress."
            )
        if self._flow_lifecycle_state == "ATTACHING":
            return SimulationCacheResult(
                False, "Kit-CAE Flow attach is still in progress."
            )

        stage = omni.usd.get_context().get_stage()
        if not stage:
            self.stop_flow_runtime_callbacks()
            self._clear_flow_runtime_state()
            return SimulationCacheResult(False, "Airflow cache skipped: no open stage.")

        session_runtime_paths = (
            "/DTRS_Runtime/Airflow",
            "/DTRS_Runtime/Looks/AirflowIndex",
            "/DTRS_Runtime/Flow",
            "/DTRS_KitCAE",
        )
        imported_dataset_path = "/DTRS_HoudiniVelocity"
        runtime_paths = (*session_runtime_paths, imported_dataset_path)
        if not any(stage.GetPrimAtPath(path).IsValid() for path in runtime_paths):
            self.stop_flow_runtime_callbacks()
            self._clear_flow_runtime_state()
            return SimulationCacheResult(True, "Airflow cache is already detached.")

        self._flow_lifecycle_state = "DETACHING"
        self.stop_flow_runtime_callbacks()
        self._log_flow_performance_summary(carb)
        timeline = omni.timeline.get_timeline_interface()
        timeline.pause()
        app = omni.kit.app.get_app()
        previous_target = stage.GetEditTarget()
        callbacks_stopped = self._flow_performance_task is None
        operators_disabled = False
        removed = False
        try:
            stage.SetEditTarget(stage.GetSessionLayer())
            operators_disabled = self._deactivate_kit_cae_flow_for_detach(
                stage, cae_viz
            )
            for _ in range(self.FLOW_DETACH_SETTLE_UPDATE_COUNT):
                await app.next_update_async()

            # Kit-CAE publishes begin/end events for external synchronization.
            # Disable new emissions first, but keep FlowSimulation active until
            # each in-flight emitter has finished reading its relation targets.
            # Inactivating the parent earlier turns those targets into null USD
            # attributes while FlowNanoVDBEmitter is still executing.
            operators_quiesced = await self._await_kit_cae_operator_quiescence(
                app, carb
            )
            if not operators_quiesced:
                carb.log_warn(
                    "DTRS FLOW DETACH | Kit-CAE operator quiesce timed out; "
                    "continuing teardown."
                )

            flow_environment = stage.GetPrimAtPath("/DTRS_KitCAE/FlowSimulation")
            if flow_environment and flow_environment.IsValid():
                flow_environment.SetActive(False)
            for _ in range(self.FLOW_DETACH_SETTLE_UPDATE_COUNT):
                await app.next_update_async()

            # The VTK importer first defines its destination at the current
            # session edit target, then copies the populated spec into root.
            # Remove every runtime subtree from both contributing layers.
            for path in runtime_paths:
                if stage.GetPrimAtPath(path).IsValid():
                    stage.RemovePrim(path)
            for _ in range(2):
                await app.next_update_async()

            stage.SetEditTarget(stage.GetRootLayer())
            # The VTK importer and Kit-CAE commands can both author root-layer
            # runtime specs. Clear every DTRS runtime subtree from that layer.
            for path in runtime_paths:
                if stage.GetPrimAtPath(path).IsValid():
                    stage.RemovePrim(path)
            for _ in range(2):
                await app.next_update_async()
            removed = not any(
                stage.GetPrimAtPath(path).IsValid() for path in runtime_paths
            )
        except asyncio.CancelledError:
            # Shutdown owns the stage after cancellation; leave no DTRS callbacks live.
            self._clear_flow_runtime_state()
            raise
        except Exception as error:
            carb.log_error(f"DTRS Flow detach failed: {error}")
            self._flow_lifecycle_state = "ATTACHED"
            self._log_kit_cae_flow_detach(
                carb,
                callbacks_stopped=callbacks_stopped,
                operators_disabled=operators_disabled,
                flow_prims_removed=False,
                controller_state_cleared=False,
                result="FAIL",
                reason=str(error),
            )
            return SimulationCacheResult(False, f"Airflow cache detach failed: {error}")
        finally:
            stage.SetEditTarget(previous_target)
            if self._flow_lifecycle_state == "DETACHING":
                self._flow_lifecycle_state = "ATTACHED"

        if not removed:
            self._log_kit_cae_flow_detach(
                carb,
                callbacks_stopped=callbacks_stopped,
                operators_disabled=operators_disabled,
                flow_prims_removed=False,
                controller_state_cleared=False,
                result="FAIL",
                reason="runtime prim removal incomplete: "
                + ", ".join(
                    path
                    for path in runtime_paths
                    if stage.GetPrimAtPath(path).IsValid()
                ),
            )
            return SimulationCacheResult(
                False,
                "Airflow cache detach did not remove all DTRS runtime prims.",
            )

        self._clear_flow_runtime_state()
        self._log_kit_cae_flow_detach(
            carb,
            callbacks_stopped=callbacks_stopped,
            operators_disabled=operators_disabled,
            flow_prims_removed=True,
            controller_state_cleared=True,
            result="PASS",
        )
        return SimulationCacheResult(
            True,
            "Airflow cache detached from the session layer.",
        )

    def clear_flow_validation_cache(self) -> None:
        """Drop session receipts only when configuration or DTRS shuts down."""

        self._flow_validation_cache.clear()

    def request_flow_attach_cancellation(self) -> bool:
        """Ask the worker preflight to stop without crossing the Kit thread boundary."""

        event = self._flow_attach_cancel_event
        if self._flow_lifecycle_state != "ATTACHING" or event is None:
            return False
        event.set()
        return True

    def stop_flow_runtime_callbacks(self) -> None:
        """Stop DTRS-owned asynchronous Flow diagnostics before teardown."""

        if self._flow_attach_cancel_event is not None:
            self._flow_attach_cancel_event.set()
        self._cancel_kit_cae_temporal_proof()
        self._stop_flow_performance_sampler()

    @staticmethod
    def _kit_cae_operator_event_path(event) -> str:
        """Read Kit's single-argument Event.get contract without callback errors."""

        return str(event.get("prim_path") or "")

    def _start_kit_cae_operator_tracking(self) -> None:
        """Track DTRS Kit-CAE operator lifetimes using its synchronization events."""

        from carb.eventdispatcher import get_eventdispatcher

        self._stop_kit_cae_operator_tracking()
        dispatcher = get_eventdispatcher()

        def update_active_paths(event, is_begin: bool) -> None:
            prim_path = self._kit_cae_operator_event_path(event)
            if not prim_path.startswith("/DTRS_KitCAE/"):
                return
            # Event dispatch can originate outside the UI callback path, so the
            # teardown coroutine reads this plain set under the same lock.
            with self._flow_kit_cae_operator_lock:
                if is_begin:
                    self._flow_kit_cae_active_operator_paths.add(prim_path)
                else:
                    self._flow_kit_cae_active_operator_paths.discard(prim_path)
                    self._flow_kit_cae_operator_completion_counts[prim_path] = (
                        self._flow_kit_cae_operator_completion_counts.get(prim_path, 0)
                        + 1
                    )

        self._flow_kit_cae_operator_subscriptions = (
            dispatcher.observe_event(
                event_name="omni.cae.viz@operator_begin",
                on_event=lambda event: update_active_paths(event, True),
                observer_name="DTRS Flow operator begin tracking",
            ),
            dispatcher.observe_event(
                event_name="omni.cae.viz@operator_end",
                on_event=lambda event: update_active_paths(event, False),
                observer_name="DTRS Flow operator end tracking",
            ),
        )

    def _stop_kit_cae_operator_tracking(self) -> None:
        """Release only DTRS observer guards after Flow has quiesced or failed."""

        subscriptions = self._flow_kit_cae_operator_subscriptions
        self._flow_kit_cae_operator_subscriptions = ()
        for subscription in subscriptions:
            reset = getattr(subscription, "reset", None)
            if reset:
                reset()
        with self._flow_kit_cae_operator_lock:
            self._flow_kit_cae_active_operator_paths.clear()
            self._flow_kit_cae_operator_completion_counts.clear()

    async def _await_kit_cae_operator_quiescence(self, app, carb) -> bool:
        """Wait for tracked Kit-CAE work without freezing the Kit update loop."""

        deadline = time.monotonic() + self.FLOW_DETACH_OPERATOR_QUIESCE_TIMEOUT_SECONDS
        quiet_since = None
        while True:
            with self._flow_kit_cae_operator_lock:
                active_paths = tuple(self._flow_kit_cae_active_operator_paths)
            now = time.monotonic()
            if active_paths:
                quiet_since = None
            else:
                quiet_since = quiet_since or now
                if now - quiet_since >= self.FLOW_DETACH_OPERATOR_QUIESCE_SECONDS:
                    return True
            if now >= deadline:
                carb.log_warn(
                    "DTRS FLOW DETACH | active Kit-CAE operators at timeout: "
                    + ", ".join(active_paths)
                )
                return False
            await app.next_update_async()

    def _kit_cae_operator_completion_count(self, prim_path: str) -> int:
        """Return the observed lifecycle-completion count for one CAE operator."""

        with self._flow_kit_cae_operator_lock:
            return self._flow_kit_cae_operator_completion_counts.get(prim_path, 0)

    async def _await_kit_cae_fresh_dataset_emitter_rebuild(
        self,
        app,
        emitter_prim,
        flow_simulate,
        *,
        requested_max_resolution: int,
        previous_max_resolution: int,
        previous_density_cell_size: float | None,
        previous_payload_fingerprint: str,
        completion_count_before: int,
    ) -> dict[str, object]:
        """Wait for a new DataSetEmitter execution and resolution-consistent output."""

        emitter_path = str(emitter_prim.GetPath())
        deadline = time.monotonic() + 10.0
        while True:
            completion_count = self._kit_cae_operator_completion_count(emitter_path)
            density_raw = flow_simulate.GetAttribute("densityCellSize").Get()
            density_cell_size = (
                float(density_raw)
                if isinstance(density_raw, (int, float)) and density_raw > 0
                else None
            )
            payload_attribute = emitter_prim.GetAttribute("nanoVdbVelocities")
            payload = (
                payload_attribute.Get()
                if payload_attribute and payload_attribute.IsValid()
                else None
            )
            payload_count = len(payload) if payload is not None else 0
            payload_fingerprint = self._kit_cae_nano_vdb_payload_fingerprint(
                payload,
                payload_count,
            )
            operator_completed = completion_count > completion_count_before
            payload_changed = payload_fingerprint != previous_payload_fingerprint
            fresh_rebuild = self._kit_cae_voxel_rebuild_is_fresh(
                requested_max_resolution=requested_max_resolution,
                previous_max_resolution=previous_max_resolution,
                previous_density_cell_size=previous_density_cell_size,
                density_cell_size=density_cell_size,
                operator_completed=operator_completed,
                payload_changed=payload_changed,
            )
            if fresh_rebuild:
                return {
                    "completed": True,
                    "density_cell_size": density_cell_size,
                    "payload_count": payload_count,
                    "payload_fingerprint": payload_fingerprint,
                    "fresh_rebuild": True,
                }
            if time.monotonic() >= deadline:
                return {
                    "completed": operator_completed,
                    "density_cell_size": density_cell_size,
                    "payload_count": payload_count,
                    "payload_fingerprint": payload_fingerprint,
                    "fresh_rebuild": False,
                }
            await app.next_update_async()

    def _log_kit_cae_voxel_rebuild(
        self,
        carb,
        *,
        requested_max_resolution: int,
        previous_density_cell_size: float | None,
        new_density_cell_size: float | None,
        fresh_rebuild: bool,
        stage_meters_per_unit: float,
        previous_intake_tracer_radius: float | None,
        intake_tracer_radius: float | None,
    ) -> None:
        """Record the fresh-output barrier that protects the Flow restart."""

        carb.log_warn(
            self._format_flow_log_block(
                "VOXEL REBUILD",
                (
                    (
                        "",
                        (
                            ("Requested resolution:", requested_max_resolution),
                            ("Operator execution:", "COMPLETE"),
                            (
                                "Previous density cell:",
                                self._kit_cae_physical_length_text(
                                    previous_density_cell_size,
                                    stage_meters_per_unit,
                                ),
                            ),
                            (
                                "New density cell:",
                                self._kit_cae_physical_length_text(
                                    new_density_cell_size,
                                    stage_meters_per_unit,
                                ),
                            ),
                            ("Fresh rebuild:", fresh_rebuild),
                        ),
                    ),
                    (
                        "Tracer emitters",
                        self._kit_cae_voxel_rebuild_tracer_log_fields(
                            previous_intake_tracer_radius,
                            intake_tracer_radius,
                            new_density_cell_size,
                            stage_meters_per_unit,
                        ),
                    ),
                ),
            )
        )

    def _log_kit_cae_voxel_switch_abort(
        self,
        carb,
        *,
        requested_max_resolution: int,
        readback_max_resolution,
        density_cell_size: float | None,
        stage_meters_per_unit: float,
        reason: str,
    ) -> None:
        """Record a failed fresh-output barrier before restoring the prior session."""

        density_text = (
            f"{density_cell_size * stage_meters_per_unit * 1000.0:.3f} mm"
            if density_cell_size is not None
            else "unavailable"
        )
        carb.log_error(
            self._format_flow_log_block(
                "VOXEL SWITCH ABORT",
                (
                    (
                        "",
                        (
                            ("Phase:", "WAITING_FOR_FRESH_DATASET_EMITTER"),
                            ("Requested:", requested_max_resolution),
                            ("Readback:", readback_max_resolution),
                            ("Density cell:", density_text),
                            ("Reason:", reason),
                        ),
                    ),
                ),
            )
        )

    def _clear_flow_runtime_state(self) -> None:
        """Forget DTRS Flow handles only after teardown or shutdown cancellation."""

        self._stop_kit_cae_operator_tracking()
        self._simulation_cache_contract = None
        self._simulation_cache_time_code = None
        self._flow_airflow_simulate_path = None
        self._flow_base_velocity_scale = None
        self._flow_world_bounds = None
        self._flow_density_cell_size = None
        self._flow_intake_tracer_radius_to_cell = None
        self._flow_vti_spacing = None
        self._flow_voxel_max_resolution = None
        self._flow_lifecycle_state = "DETACHED"
        self._flow_session_workload_binding = None
        self._flow_pending_workload_binding = None
        self._flow_active_transition_id = None
        self._flow_attach_cancel_event = None
        self._flow_temporal_records = []
        self._flow_temporal_failure = None
        self._flow_temporal_end_time_code = None
        self._flow_temporal_sample_time_codes = ()
        self._flow_performance_attached_at = None
        self._flow_performance_samples = []
        self._flow_performance_camera_bookmark = "Unspecified"

    @classmethod
    def _log_kit_cae_flow_detach(
        cls,
        carb,
        *,
        callbacks_stopped: bool,
        operators_disabled: bool,
        flow_prims_removed: bool,
        controller_state_cleared: bool,
        result: str,
        reason: str | None = None,
    ) -> None:
        """Write compact lifecycle evidence for a DTRS Flow detach attempt."""

        fields = [
            ("callbacks_stopped:", callbacks_stopped),
            ("operators_disabled:", operators_disabled),
            ("flow_prims_removed:", flow_prims_removed),
            ("controller_state_cleared:", controller_state_cleared),
        ]
        if reason:
            fields.append(("Reason:", reason))
        fields.append(("RESULT:", result))
        logger = carb.log_warn if result == "PASS" else carb.log_error
        logger(cls._format_flow_log_block("DETACH", (("", tuple(fields)),)))

    @staticmethod
    def _deactivate_kit_cae_flow_for_detach(stage, cae_viz) -> bool:
        """Disable the proven CAE and Flow participants before prim removal."""

        disabled = True
        emitter = stage.GetPrimAtPath("/DTRS_KitCAE/DataSetEmitter")
        if not emitter or not emitter.IsValid():
            disabled = False
        else:
            enabled_attr = cae_viz.OperatorAPI(emitter).CreateEnabledAttr()
            enabled_attr.Set(False)
            disabled = disabled and enabled_attr.Get() is False

        simulate = stage.GetPrimAtPath("/DTRS_KitCAE/FlowSimulation/flowSimulate")
        if not simulate or not simulate.IsValid():
            disabled = False
        else:
            for attribute_name in (
                "forceDisableEmitters",
                "forceDisableCoreSimulation",
            ):
                attribute = simulate.GetAttribute(attribute_name)
                if not attribute or not attribute.IsValid():
                    disabled = False
                    continue
                attribute.Set(True)
                disabled = disabled and attribute.Get() is True

        for path in (
            "/DTRS_KitCAE/FlowSimulation/flowOffscreen",
            "/DTRS_KitCAE/FlowSimulation/flowRender",
        ):
            prim = stage.GetPrimAtPath(path)
            if not prim or not prim.IsValid():
                disabled = False
                continue
            prim.SetActive(False)
            disabled = disabled and not prim.IsActive()
        return disabled

    @staticmethod
    async def _clear_flow_after_update(force_clear) -> None:
        """Pulse Flow's clear switch for one update instead of freezing simulation."""

        import omni.kit.app

        await omni.kit.app.get_app().next_update_async()
        force_clear.Set(False)

    @classmethod
    def _validate_kit_cae_temporal_vti_contract(
        cls,
        velocity_paths: tuple[Path, ...],
        field_name: str,
        progress_callback=None,
        cancel_requested=None,
    ) -> tuple[dict[str, object], bool]:
        """Delegate VTI checks and plain-data worker progress to the shared helper."""

        return airflow_preflight.validate_kit_cae_temporal_vti_contract(
            velocity_paths,
            field_name,
            progress_callback=progress_callback,
            cancel_requested=cancel_requested,
        )

    @staticmethod
    def _format_flow_log_block(
        title: str,
        sections: tuple[tuple[str, tuple[tuple[str, object], ...]], ...],
    ) -> str:
        """Format bounded Flow proof evidence as one grep-friendly log block."""

        rule = "=" * 63
        lines = [f"=== DTRS FLOW / {title} {rule}"]
        for heading, fields in sections:
            if heading:
                lines.extend(("", f"{heading}:"))
            lines.extend(f"  {label:<24}{value}" for label, value in fields)
        lines.extend(("", rule))
        return with_dtrs_local_timestamp("\n".join(lines))

    def _format_flow_vti_voxel_size_mm(self, stage_meters_per_unit: float) -> str:
        """Format the attached VTI spacing in physical units for A/B evidence."""

        if not self._flow_vti_spacing:
            return "unavailable"
        spacing_mm = tuple(
            value * stage_meters_per_unit * 1000.0 for value in self._flow_vti_spacing
        )
        if max(spacing_mm) - min(spacing_mm) < 1e-9:
            return f"{spacing_mm[0]:.3f} mm"
        return " x ".join(f"{value:.3f}" for value in spacing_mm) + " mm"

    @staticmethod
    def _kit_cae_nano_vdb_payload_fingerprint(payload, payload_count: int) -> str:
        """Summarize NanoVDB output without hashing or traversing the full payload."""

        if payload is None:
            return "unavailable"
        sample_count = min(4, payload_count)
        head = tuple(int(payload[index]) for index in range(sample_count))
        tail_start = max(payload_count - sample_count, 0)
        tail = tuple(int(payload[index]) for index in range(tail_start, payload_count))
        return f"len={payload_count}; head={head}; tail={tail}"

    @staticmethod
    def _read_kit_cae_intake_tracer_radius(
        stage,
        tracer_root_path: str,
        UsdGeom,
    ) -> float | None:
        """Read the uniform scale authored on every active intake tracer mesh."""

        tracer_root = stage.GetPrimAtPath(tracer_root_path)
        if not tracer_root or not tracer_root.IsValid():
            return None
        radii: list[float] = []
        tracer_meshes = sorted(
            (prim for prim in tracer_root.GetChildren() if prim.IsA(UsdGeom.Mesh)),
            key=lambda prim: str(prim.GetPath()),
        )
        for tracer_mesh in tracer_meshes:
            scale_op = next(
                (
                    op
                    for op in UsdGeom.Xformable(tracer_mesh).GetOrderedXformOps()
                    if op.GetOpType() == UsdGeom.XformOp.TypeScale
                ),
                None,
            )
            scale = scale_op.Get() if scale_op is not None else None
            if scale is None:
                return None
            try:
                scale_components = tuple(float(scale[index]) for index in range(3))
            except (IndexError, TypeError, ValueError):
                return None
            if (
                any(component <= 0.0 for component in scale_components)
                or max(scale_components) - min(scale_components) > 1e-6
            ):
                return None
            radii.append(scale_components[0])
        if not radii or max(radii) - min(radii) > 1e-6:
            return None
        return radii[0]

    @staticmethod
    def _author_kit_cae_intake_tracer_radius(
        stage,
        tracer_root_path: str,
        radius: float,
        Gf,
        UsdGeom,
    ) -> int:
        """Set only the uniform authored scale on every existing intake tracer."""

        if radius <= 0.0:
            raise ValueError("Kit-CAE intake tracer radius must be positive.")
        tracer_root = stage.GetPrimAtPath(tracer_root_path)
        if not tracer_root or not tracer_root.IsValid():
            raise RuntimeError("Kit-CAE intake tracer root is unavailable.")
        tracer_meshes = sorted(
            (prim for prim in tracer_root.GetChildren() if prim.IsA(UsdGeom.Mesh)),
            key=lambda prim: str(prim.GetPath()),
        )
        if not tracer_meshes:
            raise RuntimeError("Kit-CAE intake tracer meshes are unavailable.")
        for tracer_mesh in tracer_meshes:
            scale_op = next(
                (
                    op
                    for op in UsdGeom.Xformable(tracer_mesh).GetOrderedXformOps()
                    if op.GetOpType() == UsdGeom.XformOp.TypeScale
                ),
                None,
            )
            if scale_op is None:
                raise RuntimeError(
                    "Kit-CAE intake tracer is missing its scale transform."
                )
            scale_op.Set(Gf.Vec3f(radius, radius, radius))
        return len(tracer_meshes)

    @staticmethod
    def _kit_cae_physical_length_text(
        world_units: float | None,
        stage_meters_per_unit: float,
    ) -> str:
        """Format a world-space length as its physical millimetre value."""

        return (
            f"{world_units * stage_meters_per_unit * 1000.0:.3f} mm"
            if world_units is not None
            else "unavailable"
        )

    @staticmethod
    def _kit_cae_tracer_radius_cell_ratio(
        intake_tracer_radius: float | None,
        density_cell_size: float | None,
    ) -> float | None:
        """Return the authored emitter-radius-to-effective-Flow-cell ratio."""

        if (
            intake_tracer_radius is None
            or density_cell_size is None
            or intake_tracer_radius <= 0.0
            or density_cell_size <= 0.0
        ):
            return None
        return intake_tracer_radius / density_cell_size

    @staticmethod
    def _kit_cae_scaled_tracer_radius(
        density_cell_size: float | None,
        baseline_radius_to_cell: float | None,
    ) -> float | None:
        """Scale the tracer footprint from the successful Attach baseline."""

        if (
            density_cell_size is None
            or baseline_radius_to_cell is None
            or density_cell_size <= 0.0
            or baseline_radius_to_cell <= 0.0
        ):
            return None
        return density_cell_size * baseline_radius_to_cell

    @classmethod
    def _kit_cae_tracer_emitter_log_fields(
        cls,
        intake_tracer_radius: float | None,
        density_cell_size: float | None,
        stage_meters_per_unit: float,
    ) -> tuple[tuple[str, object], ...]:
        """Build actual authored tracer-radius evidence for Flow diagnostics."""

        radius_per_cell = cls._kit_cae_tracer_radius_cell_ratio(
            intake_tracer_radius,
            density_cell_size,
        )
        return (
            (
                "Radius:",
                cls._kit_cae_physical_length_text(
                    intake_tracer_radius,
                    stage_meters_per_unit,
                ),
            ),
            (
                "Flow density cell:",
                cls._kit_cae_physical_length_text(
                    density_cell_size,
                    stage_meters_per_unit,
                ),
            ),
            (
                "Radius / cell size:",
                (
                    f"{radius_per_cell:.3f}"
                    if radius_per_cell is not None
                    else "unavailable"
                ),
            ),
        )

    @classmethod
    def _kit_cae_voxel_rebuild_tracer_log_fields(
        cls,
        previous_intake_tracer_radius: float | None,
        intake_tracer_radius: float | None,
        density_cell_size: float | None,
        stage_meters_per_unit: float,
    ) -> tuple[tuple[str, object], ...]:
        """Build live-switch evidence from radius read back after re-authoring."""

        radius_changed = cls._kit_cae_tracer_radius_changed(
            previous_intake_tracer_radius,
            intake_tracer_radius,
        )
        radius_per_cell = cls._kit_cae_tracer_radius_cell_ratio(
            intake_tracer_radius,
            density_cell_size,
        )
        fields: tuple[tuple[str, object], ...] = (
            (
                "Previous radius:",
                cls._kit_cae_physical_length_text(
                    previous_intake_tracer_radius,
                    stage_meters_per_unit,
                ),
            ),
            (
                "New radius:",
                cls._kit_cae_physical_length_text(
                    intake_tracer_radius,
                    stage_meters_per_unit,
                ),
            ),
            (
                "Flow density cell:",
                cls._kit_cae_physical_length_text(
                    density_cell_size,
                    stage_meters_per_unit,
                ),
            ),
            (
                "Radius / cell size:",
                (
                    f"{radius_per_cell:.3f}"
                    if radius_per_cell is not None
                    else "unavailable"
                ),
            ),
            ("Radius changed:", radius_changed),
        )
        if radius_changed is False:
            return fields + (("Radius status:", "UNCHANGED AFTER VOXEL SWITCH"),)
        return fields

    @staticmethod
    def _kit_cae_tracer_radius_changed(
        previous_radius: float | None,
        new_radius: float | None,
    ) -> bool | None:
        """Compare authored tracer radii while preserving unavailable diagnostics."""

        if previous_radius is None or new_radius is None:
            return None
        return abs(new_radius - previous_radius) > 1e-6

    @staticmethod
    def _kit_cae_voxel_rebuild_is_fresh(
        *,
        requested_max_resolution: int,
        previous_max_resolution: int,
        previous_density_cell_size: float | None,
        density_cell_size: float | None,
        operator_completed: bool,
        payload_changed: bool,
    ) -> bool:
        """Require a completed operator and output consistent with the new grid."""

        if not operator_completed or density_cell_size is None:
            return False
        if requested_max_resolution == previous_max_resolution:
            return True
        if previous_density_cell_size is None:
            return payload_changed
        density_changed_in_expected_direction = (
            density_cell_size < previous_density_cell_size
            if requested_max_resolution > previous_max_resolution
            else density_cell_size > previous_density_cell_size
        )
        return density_changed_in_expected_direction and payload_changed

    def _log_kit_cae_voxel_switch_trace(
        self,
        carb,
        *,
        phase: str,
        requested_max_resolution: int,
        previous_max_resolution: int,
        stage,
        timeline,
        emitter_prim,
        emitter_operator,
        voxelization_api,
        flow_simulate,
        field_prim,
        cae_vtk,
        Usd,
        trace_state: dict[str, object],
    ) -> None:
        """Log bounded evidence for one phase of a live voxel-resolution switch."""

        from pxr import UsdGeom

        timeline_time = float(timeline.get_current_time())
        previous_timeline_time = trace_state.get("timeline_time")
        timeline_advancing = (
            timeline_time > previous_timeline_time
            if isinstance(previous_timeline_time, (int, float))
            else "n/a"
        )
        source = self._kit_cae_selected_velocity_asset(
            field_prim,
            timeline_time * stage.GetTimeCodesPerSecond(),
            cae_vtk,
            Usd,
        )
        previous_source = trace_state.get("source")
        source_changed = (
            source != previous_source if previous_source is not None else "n/a"
        )
        payload_attribute = emitter_prim.GetAttribute("nanoVdbVelocities")
        payload = (
            payload_attribute.Get()
            if payload_attribute and payload_attribute.IsValid()
            else None
        )
        payload_count = len(payload) if payload is not None else 0
        fingerprint = self._kit_cae_nano_vdb_payload_fingerprint(
            payload,
            payload_count,
        )
        previous_fingerprint = trace_state.get("payload_fingerprint")
        payload_changed = (
            fingerprint != previous_fingerprint
            if previous_fingerprint is not None
            else "n/a"
        )
        couple_rate_attribute = emitter_prim.GetAttribute("coupleRateVelocity")
        couple_rate = (
            couple_rate_attribute.Get()
            if couple_rate_attribute and couple_rate_attribute.IsValid()
            else None
        )
        operator_ready = payload_count > 0 and float(couple_rate or 0.0) > 0.0
        density_cell_size = flow_simulate.GetAttribute("densityCellSize").Get()
        stage_meters_per_unit = float(UsdGeom.GetStageMetersPerUnit(stage))
        density_cell_size_text = (
            f"{float(density_cell_size) * stage_meters_per_unit * 1000.0:.3f} mm"
            if isinstance(density_cell_size, (int, float)) and density_cell_size > 0
            else "unavailable"
        )
        source_name = source.name if source is not None else "unavailable"
        source_frame = (
            flow_temporal.kit_cae_vti_source_frame(source)
            if source is not None
            else "unavailable"
        )
        readback_max_resolution = voxelization_api.GetMaxResolutionAttr().Get()
        trace_state["timeline_time"] = timeline_time
        trace_state["source"] = source
        trace_state["payload_fingerprint"] = fingerprint
        carb.log_warn(
            self._format_flow_log_block(
                "VOXEL SWITCH TRACE",
                (
                    (
                        "",
                        (
                            ("Phase:", phase),
                            (
                                "Resolution:",
                                (
                                    f"{previous_max_resolution} -> "
                                    f"{requested_max_resolution}"
                                ),
                            ),
                        ),
                    ),
                    (
                        "Voxelization",
                        (
                            ("mode:", voxelization_api.GetVoxelSizeModeAttr().Get()),
                            ("requested:", requested_max_resolution),
                            ("readback:", readback_max_resolution),
                            ("densityCellSize:", density_cell_size_text),
                        ),
                    ),
                    (
                        "Timeline",
                        (
                            ("current:", f"{timeline_time:.3f} s"),
                            ("playing:", timeline.is_playing()),
                            (
                                "loop end:",
                                (
                                    f"{self._flow_temporal_end_time_code:.3f} s"
                                    if self._flow_temporal_end_time_code is not None
                                    else "unavailable"
                                ),
                            ),
                            ("advancing:", timeline_advancing),
                        ),
                    ),
                    (
                        "Temporal source",
                        (
                            ("resolved VTI:", source_name),
                            ("source frame:", source_frame),
                            ("source changed:", source_changed),
                        ),
                    ),
                    (
                        "DataSetEmitter",
                        (
                            ("enabled:", emitter_operator.CreateEnabledAttr().Get()),
                            ("operator ready:", operator_ready),
                        ),
                    ),
                    (
                        "NanoVDB",
                        (
                            ("uint count:", payload_count),
                            ("fingerprint:", fingerprint),
                            ("payload changed:", payload_changed),
                        ),
                    ),
                ),
            )
        )

    def _restart_kit_cae_temporal_loop(self, timeline) -> None:
        """Restart the attached temporal VTI sequence at its bounded loop range."""

        timeline.pause()
        timeline.set_current_time(0.0)
        if self._flow_temporal_end_time_code is not None:
            timeline.play(0.0, self._flow_temporal_end_time_code, True)
        else:
            timeline.play()

    def _log_kit_cae_flow_attached(
        self,
        carb,
        *,
        temporal_frames: int,
        intake_tracer_count: int,
        metadata: dict[str, object],
        origin_match: bool,
        grid_match: bool,
        operator_ready: bool,
        flow_environment_path: str,
        dataset_emitter_path: str,
        base_velocity_scale: float,
        stage_meters_per_unit: float,
        density_cell_size_m: float | None,
        intake_tracer_radius: float | None,
    ) -> None:
        """Emit one normal-path setup summary for the Flow temporal proof."""

        dimensions = " x ".join(str(value) for value in metadata["dimensions"])
        vti_spacing = " x ".join(f"{float(value):.6g}" for value in metadata["spacing"])
        tracer_config = self.config.simulation_cache.intake_tracers
        smoke_tuning = self.config.simulation_cache.smoke_tuning
        effective_velocity_scale = (
            base_velocity_scale * smoke_tuning.velocity_scale_multiplier
        )
        carb.log_warn(
            self._format_flow_log_block(
                "ATTACH",
                (
                    (
                        "",
                        (
                            ("Route:", "VTI_KIT_CAE_FLOW"),
                            ("Temporal frames:", temporal_frames),
                            ("Intake tracers:", intake_tracer_count),
                            ("Grid:", dimensions),
                        ),
                    ),
                    (
                        "Spatial",
                        (
                            ("origin_match:", origin_match),
                            ("grid_match:", grid_match),
                        ),
                    ),
                    (
                        "Flow",
                        (
                            ("operator_ready:", operator_ready),
                            ("Environment:", flow_environment_path),
                            ("Dataset emitter:", dataset_emitter_path),
                            (
                                "Stage metersPerUnit:",
                                f"{stage_meters_per_unit:.6g}",
                            ),
                            (
                                "VTI voxel size:",
                                f"{vti_spacing} world units",
                            ),
                            (
                                "Kit-CAE voxel maxResolution: ",
                                (
                                    self._flow_voxel_max_resolution
                                    if self._flow_voxel_max_resolution is not None
                                    else "unavailable"
                                ),
                            ),
                            (
                                "Flow density cell size:",
                                (
                                    f"{self._flow_density_cell_size:.6g} world units"
                                    if self._flow_density_cell_size is not None
                                    else "unavailable"
                                ),
                            ),
                            (
                                "Density cell physical:",
                                (
                                    f"{density_cell_size_m:.6g} m "
                                    f"({density_cell_size_m * 1000.0:.3f} mm)"
                                    if density_cell_size_m is not None
                                    else "unavailable"
                                ),
                            ),
                        ),
                    ),
                    (
                        "Tracer injection",
                        (
                            ("Tracer mode:", "SMOKE_ONLY"),
                            ("Smoke target:", f"{tracer_config.smoke_target:g}"),
                            ("Smoke coupling:", f"{tracer_config.smoke_couple_rate:g}"),
                            ("Renderer:", "VOLUME_SMOKE_CLOUD"),
                            (
                                "Smoke base color:",
                                ", ".join(
                                    f"{component:g}"
                                    for component in smoke_tuning.base_color
                                ),
                            ),
                            ("Buoyancy:", "OFF"),
                            ("Combustion:", "OFF"),
                        ),
                    ),
                    (
                        "Tracer emitters",
                        self._kit_cae_tracer_emitter_log_fields(
                            intake_tracer_radius,
                            self._flow_density_cell_size,
                            stage_meters_per_unit,
                        ),
                    ),
                    (
                        "Flow transport",
                        (
                            (
                                "Kit-CAE base velocityScale:",
                                f"{base_velocity_scale:g}",
                            ),
                            (
                                "Velocity multiplier:",
                                f"{smoke_tuning.velocity_scale_multiplier:g}",
                            ),
                            (
                                "Effective velocityScale:",
                                f"{effective_velocity_scale:g}",
                            ),
                            ("Time scale:", f"{smoke_tuning.time_scale:g}"),
                        ),
                    ),
                    (
                        "Smoke tuning",
                        (
                            ("Density:", f"{smoke_tuning.density:g}"),
                            ("Brightness:", f"{smoke_tuning.brightness:g}"),
                            ("Ambient:", f"{smoke_tuning.ambient:g}"),
                            ("Shadow density:", f"{smoke_tuning.shadow_density:g}"),
                            (
                                "Base color:",
                                ", ".join(
                                    f"{component:.3g}"
                                    for component in smoke_tuning.base_color
                                ),
                            ),
                            ("Damping:", f"{smoke_tuning.damping:g}"),
                            ("Fade:", f"{smoke_tuning.fade:g}"),
                            ("Sharpness:", f"{smoke_tuning.sharpness:g}"),
                            ("Vorticity:", f"{smoke_tuning.vorticity:g}"),
                            ("Raymarch quality:", f"{smoke_tuning.raymarch_quality:g}"),
                        ),
                    ),
                ),
            )
        )

    def _kit_cae_velocity_scale_matches_expected(self, value) -> bool:
        """Verify that Kit-CAE did not overwrite the locked transport scale."""

        if self._flow_base_velocity_scale is None:
            return False
        expected = (
            self._flow_base_velocity_scale
            * self.config.simulation_cache.smoke_tuning.velocity_scale_multiplier
        )
        try:
            return abs(float(value) - expected) < 1e-6
        except (TypeError, ValueError):
            return False
