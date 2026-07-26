"""Flow attach/detach lifecycle implementation for the DTRS command facade."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, replace
from pathlib import Path
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
from digital_twin_runtime_suite.app.flow.temporal import FlowTemporalMixin
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
        try:
            if stage.GetPrimAtPath(runtime_root).IsValid():
                stage.RemovePrim(runtime_root)
            await import_to_stage(str(velocity_path), import_root)
            await app.next_update_async()

            metadata, grid_match = self._validate_kit_cae_temporal_vti_contract(
                velocity_paths,
                cache.velocity_field_name,
            )
            validate_airflow_dataset_grid(
                airflow_dataset,
                tuple(metadata["dimensions"]),
            )
            dataset_prim = stage.GetPrimAtPath(dataset_path)
            field_prim = stage.GetPrimAtPath(field_path)
            self._flow_temporal_sample_time_codes = (
                self._author_kit_cae_temporal_velocity_samples(
                    field_prim,
                    velocity_paths,
                    stage.GetTimeCodesPerSecond(),
                    airflow_dataset.sample_interval_seconds,
                    cae_vtk,
                    Sdf,
                    Usd,
                )
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
                status_callback("Creating Kit-CAE Flow environment")
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
                temporal_proof_passed = await self._monitor_kit_cae_temporal_proof(
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
                )
            else:
                temporal_proof_passed = False
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
            stage.SetEditTarget(previous_target)

        self._simulation_cache_contract = None
        self._simulation_cache_time_code = None
        self._flow_airflow_simulate_path = f"{flow_environment_path}/flowSimulate"
        self._flow_lifecycle_state = "ATTACHED"
        self._start_flow_performance_sampler()
        if not temporal_proof_passed:
            return SimulationCacheResult(
                False,
                "Kit-CAE Flow remains attached, but the temporal proof failed; "
                "expanded diagnostics were logged.",
            )
        return SimulationCacheResult(
            True,
            "Kit-CAE Flow temporal loop proof passed: "
            f"PointData/{cache.velocity_field_name} Vector3 drives live smoke.",
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

    def stop_flow_runtime_callbacks(self) -> None:
        """Stop DTRS-owned asynchronous Flow diagnostics before teardown."""

        self._stop_flow_performance_sampler()

    def _clear_flow_runtime_state(self) -> None:
        """Forget DTRS Flow handles only after teardown or shutdown cancellation."""

        self._simulation_cache_contract = None
        self._simulation_cache_time_code = None
        self._flow_airflow_simulate_path = None
        self._flow_base_velocity_scale = None
        self._flow_world_bounds = None
        self._flow_density_cell_size = None
        self._flow_lifecycle_state = "DETACHED"
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
    ) -> tuple[dict[str, object], bool]:
        """Delegate temporal grid consistency checks to the shared helper."""

        return flow_temporal.validate_kit_cae_temporal_vti_contract(
            velocity_paths,
            field_name,
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
