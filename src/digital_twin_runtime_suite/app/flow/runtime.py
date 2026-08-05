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
    validate_airflow_dataset_grid,
)
from digital_twin_runtime_suite.app.config import (
    EmitterLayoutConfig,
    SmokeTuningConfig,
    validate_emitter_layout,
    validate_smoke_tuning,
)
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
from digital_twin_runtime_suite.app.flow.temporal import FlowTemporalMixin
from digital_twin_runtime_suite.app.flow.validation_cache import (
    DatasetValidationSignature,
    ValidationCacheLookup,
    build_dataset_validation_signature,
)
from digital_twin_runtime_suite.app.kit_cae_flow_parity import (
    capture_flow_scene,
    write_flow_snapshot,
)

StatusCallback = Callable[[str], None]


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

    def _cancel_kit_cae_temporal_proof(self) -> None:
        """Invalidate and cancel the proof bound to the previous Flow session."""

        self._flow_temporal_proof_generation += 1
        previous_progress = self._flow_temporal_progress
        if previous_progress.state in {
            TemporalProofState.RUNNING,
            TemporalProofState.CHECKING_LOOP_CLOSURE,
        }:
            self._flow_temporal_progress = replace(
                previous_progress,
                state=TemporalProofState.CANCELLED,
                generation_id=self._flow_temporal_proof_generation,
                last_progress_at=time.monotonic(),
            )
        task = self._flow_temporal_proof_task
        self._flow_temporal_proof_task = None
        if task and not task.done():
            task.cancel()

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

    async def _attach_kit_cae_airflow_in_kit(
        self,
        status_callback: StatusCallback | None = None,
    ) -> SimulationCacheResult:
        """Import one Houdini VTI velocity field and drive a Kit-CAE Flow probe."""

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

        cache = self.config.simulation_cache
        try:
            airflow_dataset = self.config.resolve_airflow_dataset()
        except AirflowDatasetError as error:
            carb.log_error(f"DTRS airflow dataset discovery failed: {error}")
            return SimulationCacheResult(False, str(error))
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
            density_cell_size = flow_simulate.GetAttribute("densityCellSize").Get()
            self._flow_world_bounds = imported_grid["world_bounds"]
            self._flow_density_cell_size = (
                float(density_cell_size)
                if isinstance(density_cell_size, (int, float)) and density_cell_size > 0
                else None
            )
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
            velocity_selector = cae_viz.FieldSelectionAPI(emitter_prim, "velocities")
            velocity_selector.CreateTargetRel().SetTargets([field_path])
            emitter_operator.CreateEnabledAttr().Set(True)
            operator_readiness = (
                await flow_validation.wait_for_kit_cae_dataset_emitter_ready(
                    app,
                    emitter_prim,
                )
            )
            self._flow_base_velocity_scale = (
                flow_smoke.read_kit_cae_base_velocity_scale(emitter_prim)
            )
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
            if self._flow_temporal_end_time_code is not None:
                timeline.play(0.0, self._flow_temporal_end_time_code, True)
            else:
                timeline.play()
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
        except flow_temporal.TemporalVtiValidationCancelled:
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
            self._flow_lifecycle_state = "DETACHED"
            self._flow_temporal_end_time_code = None
            self._flow_temporal_sample_time_codes = ()
            self._flow_temporal_records = []
            self._flow_temporal_failure = None
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

    def _clear_flow_runtime_state(self) -> None:
        """Forget DTRS Flow handles only after teardown or shutdown cancellation."""

        self._stop_kit_cae_operator_tracking()
        self._simulation_cache_contract = None
        self._simulation_cache_time_code = None
        self._flow_airflow_simulate_path = None
        self._flow_base_velocity_scale = None
        self._flow_world_bounds = None
        self._flow_density_cell_size = None
        self._flow_lifecycle_state = "DETACHED"
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

        return flow_temporal.validate_kit_cae_temporal_vti_contract(
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
        return "\n".join(lines)

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
    ) -> None:
        """Emit one normal-path setup summary for the Flow temporal proof."""

        dimensions = " x ".join(str(value) for value in metadata["dimensions"])
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
