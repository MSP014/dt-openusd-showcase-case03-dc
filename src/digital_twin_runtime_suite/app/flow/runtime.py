"""Flow attach/detach lifecycle implementation for the DTRS command facade."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from digital_twin_runtime_suite.app.config import (
    SmokeTuningConfig,
    validate_smoke_tuning,
)
from digital_twin_runtime_suite.app.flow import smoke as flow_smoke
from digital_twin_runtime_suite.app.flow import validation as flow_validation
from digital_twin_runtime_suite.app.flow.performance import FlowPerformanceSample
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


class FlowRuntimeMixin:
    """Own Flow lifecycle methods while RuntimeController keeps the public facade."""

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
        velocity_paths = self.config.velocity_vti_sequence_paths
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
            dataset_prim = stage.GetPrimAtPath(dataset_path)
            field_prim = stage.GetPrimAtPath(field_path)
            self._flow_temporal_sample_time_codes = (
                self._author_kit_cae_temporal_velocity_samples(
                    field_prim,
                    velocity_paths,
                    stage.GetTimeCodesPerSecond(),
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
            UsdGeom.Xform.Define(stage, tracer_root_path)
            tracer_positions = flow_smoke.kit_cae_front_intake_tracer_positions(
                stage,
                cache.intake_tracers,
                self.config.fan_motion_bindings,
                imported_grid["world_bounds"],
                Gf,
                Usd,
                UsdGeom,
            )
            for index, position in enumerate(tracer_positions, start=1):
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
                    cache.intake_tracers,
                    Gf,
                    UsdGeom,
                )
            flow_smoke.hide_kit_cae_intake_tracer_meshes(
                stage,
                tracer_root_path,
                UsdGeom,
                expected_count=cache.intake_tracers.count,
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
            flow_smoke.configure_kit_cae_smoke_only_tracer_flow(
                stage,
                flow_environment_path,
                cache.intake_tracers,
                cache.smoke_tuning,
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
            timeline_advancing = timeline_time_after > timeline_time_before
            evidence_valid = (
                operator_readiness["ready"]
                and not operator_readiness["timed_out"]
                and origin_match
                and grid_match
                and timeline_advancing
                and payload_count > 0
                and float(couple_rate_velocity or 0.0) > 0.0
            )
            self._flow_temporal_records = []
            self._flow_temporal_failure = None
            if evidence_valid:
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
            flow_smoke.author_kit_cae_smoke_tuning(
                stage,
                flow_environment_path,
                tuning,
                Gf,
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
                    "",
                    "Dynamics:",
                    f"  Damping:          {tuning.damping:g}",
                    f"  Fade:             {tuning.fade:g}",
                    f"  Sharpness:        {tuning.sharpness:g}",
                    f"  Vorticity:        {tuning.vorticity:g}",
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

    @staticmethod
    def _kit_cae_vectors_match(expected, actual, tolerance: float = 1e-6) -> bool:
        """Compare three-component grid values without exposing diagnostic internals."""

        if expected is None or actual is None:
            return False
        try:
            return len(expected) == len(actual) == 3 and all(
                abs(float(expected[index]) - float(actual[index])) <= tolerance
                for index in range(3)
            )
        except (TypeError, ValueError):
            return False

    @classmethod
    def _validate_kit_cae_temporal_vti_contract(
        cls,
        velocity_paths: tuple[Path, ...],
        field_name: str,
    ) -> tuple[dict[str, object], bool]:
        """Require each Stage 6 temporal fixture to share the imported grid contract."""

        metadata_by_path = [
            (path, flow_validation.read_kit_cae_vti_metadata(path, field_name))
            for path in velocity_paths
        ]
        primary_path, primary_metadata = metadata_by_path[0]
        for path, metadata in metadata_by_path[1:]:
            for key in ("dimensions", "spacing", "vti_header_origin"):
                if metadata[key] != primary_metadata[key]:
                    raise RuntimeError(
                        "Temporal VTI grid contract mismatch: "
                        f"{path.name} {key} differs from {primary_path.name}."
                    )
        return primary_metadata, True

    def _kit_cae_vti_asset_hash(self, asset: Path) -> str:
        """Return a cached SHA-256 identity for temporal proof evidence."""

        cached = self._flow_temporal_asset_hashes.get(asset)
        if cached:
            return cached
        digest = hashlib.sha256()
        with asset.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        value = digest.hexdigest()
        self._flow_temporal_asset_hashes[asset] = value
        return value

    @staticmethod
    def _kit_cae_vti_source_frame(asset: Path) -> str:
        """Extract the Houdini frame suffix for compact temporal evidence."""

        match = re.search(r"(\d+)$", asset.stem)
        return match.group(1) if match else asset.stem

    @staticmethod
    def _flow_log_value(value) -> object:
        """Keep compact Flow evidence stable for scalar Kit attribute values."""

        try:
            return round(float(value), 3)
        except (TypeError, ValueError):
            return value

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

    @staticmethod
    def _format_flow_performance_value(
        value: float | None,
        *,
        suffix: str = "",
    ) -> str:
        """Format optional Stage 6 performance values without inventing data."""

        return "unavailable" if value is None else f"{value:.1f}{suffix}"

    @staticmethod
    def _flow_performance_statistics(
        samples: list[FlowPerformanceSample],
    ) -> dict[str, float | None]:
        """Reduce viewport observations for a log interval or Attach lifetime."""

        fps_values = [sample.fps for sample in samples if sample.fps is not None]
        frame_times = [
            sample.frame_time_ms
            for sample in samples
            if sample.frame_time_ms is not None
        ]
        return {
            "fps_average": sum(fps_values) / len(fps_values) if fps_values else None,
            "fps_minimum": min(fps_values) if fps_values else None,
            "fps_maximum": max(fps_values) if fps_values else None,
            "frame_time_average": (
                sum(frame_times) / len(frame_times) if frame_times else None
            ),
        }

    def _capture_flow_performance_sample(self) -> FlowPerformanceSample:
        """Read the same viewport FPS and memory sources used by Kit's HUD."""

        captured_at = time.monotonic()
        fps = None
        frame_time_ms = None
        gpu_memory_used_gib = None
        process_memory_used_gib = None
        try:
            import omni.hydra.engine.stats as engine_stats
            import omni.kit.viewport.utility as viewport_utility
            from omni.gpu_foundation_factory import get_memory_info

            viewport = viewport_utility.get_active_viewport()
            frame_info = viewport.frame_info if viewport else {}
            if viewport:
                subframe_count = frame_info.get("subframe_count", 1) or 1
                effective_fps = float(viewport.fps) * float(subframe_count)
                if effective_fps > 0.0:
                    fps = effective_fps
                    frame_time_ms = 1000.0 / effective_fps

            device_mask = frame_info.get("device_mask")
            device_info = engine_stats.get_device_info()
            enabled_devices = [
                device
                for index, device in enumerate(device_info)
                if device_mask is None or device_mask & (1 << index)
            ]
            selected_device = (enabled_devices or device_info or [None])[0]
            if selected_device:
                gpu_memory_used_gib = float(selected_device["usage"]) / (1024**3)

            host_info = get_memory_info(rss=True)
            process_memory_used_gib = float(host_info["rss_memory"]) / (1024**3)
        except Exception:
            # Performance instrumentation must never make Flow Attach fail.
            fps = frame_time_ms = gpu_memory_used_gib = process_memory_used_gib = None

        return FlowPerformanceSample(
            captured_at=captured_at,
            fps=fps,
            frame_time_ms=frame_time_ms,
            gpu_memory_used_gib=gpu_memory_used_gib,
            process_memory_used_gib=process_memory_used_gib,
            temporal_source=self._kit_cae_current_temporal_source_name(),
        )

    def _kit_cae_current_temporal_source_name(self) -> str | None:
        """Read the composed source active at the current Kit timeline time."""

        if not self._flow_airflow_simulate_path:
            return None
        try:
            import omni.timeline
            import omni.usd
            from omni.cae.schema import vtk as cae_vtk
            from pxr import Usd

            stage = omni.usd.get_context().get_stage()
            if not stage:
                return None
            field_path = (
                "/DTRS_HoudiniVelocity/PointData/"
                f"{self.config.simulation_cache.velocity_field_name}"
            )
            field_prim = stage.GetPrimAtPath(field_path)
            if not field_prim or not field_prim.IsValid():
                return None
            timeline_seconds = float(
                omni.timeline.get_timeline_interface().get_current_time()
            )
            asset = self._kit_cae_selected_velocity_asset(
                field_prim,
                timeline_seconds * float(stage.GetTimeCodesPerSecond()),
                cae_vtk,
                Usd,
            )
            return asset.name if asset else None
        except Exception:
            # The temporal source is evidence only; an unavailable read is non-fatal.
            return None

    def _log_flow_performance_event(
        self,
        carb,
        *,
        event: str,
        sample: FlowPerformanceSample,
    ) -> None:
        """Record the baseline or settled Flow performance from Kit's HUD data."""

        fields = [
            ("Event:", event),
            ("FPS:", self._format_flow_performance_value(sample.fps)),
            (
                "Frame time:",
                self._format_flow_performance_value(
                    sample.frame_time_ms,
                    suffix=" ms",
                ),
            ),
        ]
        if event == "FLOW_ATTACHED":
            fields.extend(
                (
                    (
                        "GPU memory used:",
                        self._format_flow_performance_value(
                            sample.gpu_memory_used_gib,
                            suffix=" GiB",
                        ),
                    ),
                    (
                        "Process memory:",
                        self._format_flow_performance_value(
                            sample.process_memory_used_gib,
                            suffix=" GiB",
                        ),
                    ),
                    ("Temporal source:", sample.temporal_source or "unavailable"),
                    ("Camera bookmark:", self._flow_performance_camera_bookmark),
                    ("Flow attached:", True),
                )
            )
        carb.log_warn(
            self._format_flow_log_block("PERFORMANCE", (("", tuple(fields)),))
        )

    def _start_flow_performance_sampler(self) -> None:
        """Start one low-frequency Stage 6 sampler after Flow is live and settled."""

        self._stop_flow_performance_sampler()
        self._flow_performance_session_id += 1
        session_id = self._flow_performance_session_id
        self._flow_performance_attached_at = time.monotonic()
        initial_sample = self._capture_flow_performance_sample()
        self._flow_performance_samples = [initial_sample]

        import carb

        self._log_flow_performance_event(
            carb,
            event="FLOW_ATTACHED",
            sample=initial_sample,
        )
        self._flow_performance_task = asyncio.ensure_future(
            self._run_flow_performance_sampler(session_id)
        )

    def set_flow_performance_camera_bookmark(self, name: str) -> None:
        """Label future Flow performance intervals with the active fixed camera."""

        self._flow_performance_camera_bookmark = name

    def _stop_flow_performance_sampler(self) -> None:
        """Cancel a prior Stage 6 sampler before reload, detach, or reattach."""

        self._flow_performance_session_id += 1
        task = self._flow_performance_task
        self._flow_performance_task = None
        if task and not task.done():
            task.cancel()

    async def _run_flow_performance_sampler(self, session_id: int) -> None:
        """Collect HUD observations at low frequency and log thirty-second intervals."""

        import carb

        attached_at = self._flow_performance_attached_at
        if attached_at is None:
            return
        next_log_at = attached_at + self.FLOW_PERFORMANCE_LOG_INTERVAL_SECONDS
        interval_start = attached_at
        try:
            while (
                session_id == self._flow_performance_session_id
                and self._flow_lifecycle_state == "ATTACHED"
                and self._flow_airflow_simulate_path
            ):
                await asyncio.sleep(self.FLOW_PERFORMANCE_SAMPLE_INTERVAL_SECONDS)
                if session_id != self._flow_performance_session_id:
                    return
                sample = self._capture_flow_performance_sample()
                self._flow_performance_samples.append(sample)
                if sample.captured_at >= next_log_at:
                    interval_samples = [
                        item
                        for item in self._flow_performance_samples
                        if item.captured_at >= interval_start
                    ]
                    self._log_flow_performance_interval(carb, interval_samples)
                    interval_start = sample.captured_at
                    next_log_at = (
                        sample.captured_at + self.FLOW_PERFORMANCE_LOG_INTERVAL_SECONDS
                    )
        except asyncio.CancelledError:
            return

    def _log_flow_performance_interval(
        self,
        carb,
        samples: list[FlowPerformanceSample],
    ) -> None:
        """Emit rolling ten-second Stage 6 evidence while Flow remains attached."""

        if not samples or self._flow_performance_attached_at is None:
            return
        latest_sample = samples[-1]
        statistics = self._flow_performance_statistics(samples)
        elapsed = latest_sample.captured_at - self._flow_performance_attached_at
        carb.log_warn(
            self._format_flow_log_block(
                "PERFORMANCE",
                (
                    (
                        "",
                        (("Elapsed since Attach:", f"{elapsed:.1f} s"),),
                    ),
                    (
                        "FPS",
                        (
                            (
                                "Average:",
                                self._format_flow_performance_value(
                                    statistics["fps_average"]
                                ),
                            ),
                            (
                                "Minimum:",
                                self._format_flow_performance_value(
                                    statistics["fps_minimum"]
                                ),
                            ),
                            (
                                "Maximum:",
                                self._format_flow_performance_value(
                                    statistics["fps_maximum"]
                                ),
                            ),
                        ),
                    ),
                    (
                        "Frame time",
                        (
                            (
                                "Average:",
                                self._format_flow_performance_value(
                                    statistics["frame_time_average"],
                                    suffix=" ms",
                                ),
                            ),
                        ),
                    ),
                    (
                        "Memory",
                        (
                            (
                                "GPU memory used:",
                                self._format_flow_performance_value(
                                    latest_sample.gpu_memory_used_gib,
                                    suffix=" GiB",
                                ),
                            ),
                            (
                                "Process memory:",
                                self._format_flow_performance_value(
                                    latest_sample.process_memory_used_gib,
                                    suffix=" GiB",
                                ),
                            ),
                        ),
                    ),
                    (
                        "Flow",
                        (
                            (
                                "Temporal source:",
                                latest_sample.temporal_source or "unavailable",
                            ),
                            (
                                "Camera bookmark:",
                                self._flow_performance_camera_bookmark,
                            ),
                            ("Flow attached:", bool(self._flow_airflow_simulate_path)),
                        ),
                    ),
                ),
            )
        )

    def _log_flow_performance_summary(self, carb) -> None:
        """Write the final Attach-lifetime result before clearing sampler state."""

        if (
            not self._flow_performance_samples
            or self._flow_performance_attached_at is None
        ):
            return
        statistics = self._flow_performance_statistics(self._flow_performance_samples)
        duration = time.monotonic() - self._flow_performance_attached_at
        gpu_samples = [
            sample.gpu_memory_used_gib
            for sample in self._flow_performance_samples
            if sample.gpu_memory_used_gib is not None
        ]
        flow_resets = sum(
            1 for record in self._flow_temporal_records if record["flow_reset"]
        )
        summary_fields = [
            ("Flow resets:", flow_resets),
        ]
        if gpu_samples:
            summary_fields.append(("Peak GPU memory:", f"{max(gpu_samples):.1f} GiB"))
        carb.log_warn(
            self._format_flow_log_block(
                "PERFORMANCE SUMMARY",
                (
                    (
                        "",
                        (("Attached duration:", f"{duration:.1f} s"),),
                    ),
                    (
                        "FPS",
                        (
                            (
                                "Average:",
                                self._format_flow_performance_value(
                                    statistics["fps_average"]
                                ),
                            ),
                            (
                                "Minimum:",
                                self._format_flow_performance_value(
                                    statistics["fps_minimum"]
                                ),
                            ),
                            (
                                "Maximum:",
                                self._format_flow_performance_value(
                                    statistics["fps_maximum"]
                                ),
                            ),
                        ),
                    ),
                    ("Flow", tuple(summary_fields)),
                ),
            )
        )

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
    ) -> None:
        """Emit one normal-path setup summary for the Flow temporal proof."""

        dimensions = " x ".join(str(value) for value in metadata["dimensions"])
        tracer_config = self.config.simulation_cache.intake_tracers
        smoke_tuning = self.config.simulation_cache.smoke_tuning
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
                                    for component in (
                                        tracer_config.smoke_cloud_base_color
                                    )
                                ),
                            ),
                            ("Buoyancy:", "OFF"),
                            ("Combustion:", "OFF"),
                        ),
                    ),
                    (
                        "Smoke tuning",
                        (
                            ("Density:", f"{smoke_tuning.density:g}"),
                            ("Brightness:", f"{smoke_tuning.brightness:g}"),
                            ("Ambient:", f"{smoke_tuning.ambient:g}"),
                            ("Shadow density:", f"{smoke_tuning.shadow_density:g}"),
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

    def _log_kit_cae_temporal_frame(
        self,
        carb,
        *,
        sequence_index: int,
        temporal_frames: int,
        asset: Path,
        previous_frame: str | None,
        transition: str,
        operator_ready: bool,
        operator_wait_ms: float,
        nano_vdb_velocities_uint_count: int,
        velocity_scale,
        couple_rate_velocity,
        timeline_time_before: float,
        timeline_time_after: float,
        timeline_advancing: bool,
        flow_reset: bool,
        origin_match: bool,
        grid_match: bool,
        verbose: bool,
    ) -> None:
        """Record one actual source activation without recreating Flow diagnostics."""

        source_frame = self._kit_cae_vti_source_frame(asset)
        asset_hash = self._kit_cae_vti_asset_hash(asset)[:12]
        record = {
            "sequence_index": sequence_index,
            "source_frame": source_frame,
            "asset": asset.name,
            "asset_hash": asset_hash,
            "previous_frame": previous_frame,
            "transition": transition,
            "operator_ready": operator_ready,
            "operator_wait_ms": round(operator_wait_ms),
            "nano_vdb_velocities_uint_count": nano_vdb_velocities_uint_count,
            "velocity_scale": self._flow_log_value(velocity_scale),
            "couple_rate_velocity": self._flow_log_value(couple_rate_velocity),
            "timeline_time_before": round(timeline_time_before, 3),
            "timeline_time_after": round(timeline_time_after, 3),
            "timeline_advancing": timeline_advancing,
            "flow_reset": flow_reset,
            "origin_match": origin_match,
            "grid_match": grid_match,
        }
        self._flow_temporal_records.append(record)
        if not verbose:
            return
        carb.log_warn(
            self._format_flow_log_block(
                f"TEMPORAL FRAME {sequence_index + 1}/{temporal_frames}",
                (
                    (
                        "Source",
                        (
                            ("source_frame:", source_frame),
                            ("Asset:", asset.name),
                            ("SHA-256:", asset_hash),
                            ("previous_frame:", previous_frame),
                            ("Transition:", transition),
                        ),
                    ),
                    (
                        "CAE -> Flow",
                        (
                            ("operator_ready:", operator_ready),
                            ("Operator wait:", f"{round(operator_wait_ms)} ms"),
                            ("NanoVDB uint count:", nano_vdb_velocities_uint_count),
                            ("Velocity scale:", record["velocity_scale"]),
                            ("Couple rate:", record["couple_rate_velocity"]),
                        ),
                    ),
                    (
                        "Timeline",
                        (
                            ("Before:", f"{timeline_time_before:.2f} s"),
                            ("After:", f"{timeline_time_after:.2f} s"),
                            ("Advancing:", timeline_advancing),
                            ("flow_reset:", flow_reset),
                        ),
                    ),
                    (
                        "Invariants",
                        (
                            ("origin_match:", origin_match),
                            ("grid_match:", grid_match),
                        ),
                    ),
                ),
            )
        )

    @staticmethod
    def _kit_cae_temporal_loop_proof_summary(
        records: list[dict[str, object]],
        velocity_paths: tuple[Path, ...],
    ) -> dict[str, object]:
        """Reduce the fixed Stage 6 loop contract into explicit proof evidence."""

        expected_assets = (*velocity_paths, velocity_paths[0]) if velocity_paths else ()
        expected_names = [asset.name for asset in expected_assets]
        observed_names = [str(record.get("asset", "unavailable")) for record in records]
        frames = [str(record.get("source_frame", "unavailable")) for record in records]
        hashes = {
            str(record["asset_hash"])
            for record in records
            if record.get("asset_hash") is not None
        }
        transitions = [str(record.get("transition", "")) for record in records[1:]]
        forward_transitions = sum(transition == "SWAP" for transition in transitions)
        loop_transitions = sum(transition == "LOOP" for transition in transitions)
        operator_ready_all = all(
            bool(record.get("operator_ready")) for record in records
        )
        origin_match_all = all(bool(record.get("origin_match")) for record in records)
        grid_match_all = all(bool(record.get("grid_match")) for record in records)
        timeline_continuous = all(
            bool(record.get("timeline_advancing")) for record in records
        )
        flow_resets = sum(bool(record.get("flow_reset")) for record in records)
        loop_closure = (
            len(records) == len(expected_assets)
            and bool(records)
            and observed_names[-1] == expected_names[0]
            and transitions[-1:] == ["LOOP"]
        )
        mismatch = next(
            (
                (expected_name, observed_name)
                for expected_name, observed_name in zip(expected_names, observed_names)
                if expected_name != observed_name
            ),
            None,
        )
        if mismatch is None and len(observed_names) < len(expected_names):
            mismatch = (expected_names[len(observed_names)], "unavailable")
        passed = (
            len(velocity_paths) == 16
            and len(records) == 17
            and observed_names == expected_names
            and len(set(observed_names)) == 16
            and len(hashes) == 16
            and transitions == ["SWAP"] * 15 + ["LOOP"]
            and forward_transitions == 15
            and loop_transitions == 1
            and loop_closure
            and operator_ready_all
            and origin_match_all
            and grid_match_all
            and timeline_continuous
            and flow_resets == 0
        )
        return {
            "frames": frames,
            "unique_assets": len(set(observed_names)),
            "unique_hashes": len(hashes),
            "forward_transitions": forward_transitions,
            "loop_transitions": loop_transitions,
            "operator_ready_all": operator_ready_all,
            "origin_match_all": origin_match_all,
            "grid_match_all": grid_match_all,
            "timeline_continuous": timeline_continuous,
            "flow_resets": flow_resets,
            "loop_closure": loop_closure,
            "mismatch": mismatch,
            "passed": passed,
        }

    def _log_kit_cae_temporal_proof(
        self,
        carb,
        velocity_paths: tuple[Path, ...],
    ) -> bool:
        """Emit the Stage 6 sixteen-frame temporal loop proof result."""

        summary = self._kit_cae_temporal_loop_proof_summary(
            self._flow_temporal_records,
            velocity_paths,
        )
        sections = (
            (
                "",
                (
                    ("Frames observed:", " -> ".join(summary["frames"]) or "none"),
                    ("Unique source assets:", summary["unique_assets"]),
                    ("Unique source hashes:", summary["unique_hashes"]),
                    ("Forward transitions:", summary["forward_transitions"]),
                    ("Loop transitions:", summary["loop_transitions"]),
                ),
            ),
            (
                "Invariants",
                (
                    ("operator_ready_all:", summary["operator_ready_all"]),
                    ("origin_match_all:", summary["origin_match_all"]),
                    ("grid_match_all:", summary["grid_match_all"]),
                    ("timeline_continuous:", summary["timeline_continuous"]),
                    ("Flow resets:", summary["flow_resets"]),
                    (
                        "Loop closure:",
                        "PASS" if summary["loop_closure"] else "FAIL",
                    ),
                ),
            ),
        )
        if not summary["passed"]:
            mismatch = summary["mismatch"]
            failure = self._flow_temporal_failure or {}
            expected_source = (
                mismatch[0]
                if mismatch is not None
                else failure.get("expected_asset", "unavailable")
            )
            resolved_source = (
                failure.get("resolved_asset", "unavailable")
                if mismatch is not None and mismatch[1] == "unavailable"
                else (
                    mismatch[1]
                    if mismatch is not None
                    else failure.get("resolved_asset", "unavailable")
                )
            )
            reason = (
                failure.get("reason", "temporal loop evidence invariant failed")
                if mismatch is not None and mismatch[1] == "unavailable"
                else (
                    "source_asset_match=False"
                    if mismatch is not None
                    else failure.get(
                        "reason", "temporal loop evidence invariant failed"
                    )
                )
            )
            sections += (
                (
                    "Failure",
                    (
                        ("Reason:", reason),
                        ("Expected source:", expected_source),
                        ("Resolved source:", resolved_source),
                    ),
                ),
            )
        sections += (("", (("RESULT:", "PASS" if summary["passed"] else "FAIL"),)),)
        message = self._format_flow_log_block("TEMPORAL LOOP PROOF", sections)
        if summary["passed"]:
            carb.log_warn(message)
        else:
            carb.log_error(message)
        return bool(summary["passed"])

    @staticmethod
    def _author_kit_cae_temporal_velocity_samples(
        field_prim,
        velocity_paths: tuple[Path, ...],
        time_codes_per_second: float,
        cae_vtk,
        Sdf,
        Usd,
    ) -> tuple[float, ...]:
        """Map the bounded Stage 6 probe to time samples on one VTK field."""

        file_names_attr = cae_vtk.FieldArray(field_prim).GetFileNamesAttr()
        if not file_names_attr or not file_names_attr.IsValid():
            raise RuntimeError("Kit-CAE velocity field is missing fileNames.")
        if time_codes_per_second <= 0:
            raise RuntimeError("Stage timeCodesPerSecond must be positive.")
        time_codes = tuple(
            float(index) * float(time_codes_per_second)
            for index in range(len(velocity_paths))
        )
        for time_code, velocity_path in zip(time_codes, velocity_paths):
            file_names_attr.Set(
                [Sdf.AssetPath(velocity_path.as_posix())],
                Usd.TimeCode(time_code),
            )
        return time_codes

    @staticmethod
    def _kit_cae_file_names_value_at_time(field_prim, time_code, cae_vtk, Usd):
        """Read the VTK source assets selected at one USD time code."""

        file_names_attr = cae_vtk.FieldArray(field_prim).GetFileNamesAttr()
        return file_names_attr.Get(Usd.TimeCode(time_code))

    @staticmethod
    def _kit_cae_file_names_value_repr(value) -> list[str]:
        """Serialize a composed USD asset array for temporal evidence."""

        return [
            asset.resolvedPath or asset.path or str(asset) for asset in (value or [])
        ]

    @classmethod
    def _kit_cae_file_names_time_samples(cls, field_prim, cae_vtk, Usd) -> list[str]:
        """Format authored VTI source samples for compact time-domain evidence."""

        file_names_attr = cae_vtk.FieldArray(field_prim).GetFileNamesAttr()
        return [
            f"{time_code}:"
            + "|".join(
                cls._kit_cae_file_names_value_repr(
                    cls._kit_cae_file_names_value_at_time(
                        field_prim,
                        time_code,
                        cae_vtk,
                        Usd,
                    )
                )
            )
            for time_code in file_names_attr.GetTimeSamples()
        ]

    @classmethod
    def _kit_cae_file_names_property_stack(
        cls, field_prim, cae_vtk
    ) -> list[dict[str, object]]:
        """Expose only the composed fileNames opinions needed to debug time samples."""

        file_names_attr = cae_vtk.FieldArray(field_prim).GetFileNamesAttr()
        stack = []
        for spec in file_names_attr.GetPropertyStack():
            try:
                time_samples = spec.GetInfo("timeSamples") or {}
            except Exception:
                time_samples = {}
            stack.append(
                {
                    "layer": spec.layer.identifier,
                    "time_codes_per_second": spec.layer.timeCodesPerSecond,
                    "default": cls._kit_cae_file_names_value_repr(spec.default),
                    "authored_time_samples": {
                        str(time_code): cls._kit_cae_file_names_value_repr(value)
                        for time_code, value in time_samples.items()
                    },
                }
            )
        return stack

    @classmethod
    def _log_kit_cae_temporal_time_mapping(
        cls,
        carb,
        *,
        field_prim,
        timeline_time_seconds: float,
        stage_time_codes_per_second: float,
        resolved_stage_time_code: float,
        cae_vtk,
        Usd,
    ) -> None:
        """Log actual composed fileNames values before source-match evaluation."""

        file_names_attr = cae_vtk.FieldArray(field_prim).GetFileNamesAttr()

        def names_at(time_code) -> str:
            values = cls._kit_cae_file_names_value_repr(
                cls._kit_cae_file_names_value_at_time(
                    field_prim,
                    time_code,
                    cae_vtk,
                    Usd,
                )
            )
            return " | ".join(Path(value).name for value in values) or "none"

        property_stack = cls._kit_cae_file_names_property_stack(
            field_prim,
            cae_vtk,
        )
        authoring_layer_tcps = (
            property_stack[0]["time_codes_per_second"]
            if property_stack
            else "unavailable"
        )
        composed_sample_fields = tuple(
            (f"TC {float(time_code):.3f}:", names_at(time_code))
            for time_code in file_names_attr.GetTimeSamples()
        )
        message = cls._format_flow_log_block(
            "TEMPORAL MAPPING",
            (
                (
                    "Field",
                    (
                        ("Prim:", field_prim.GetPath()),
                        ("Attribute:", file_names_attr.GetPath()),
                    ),
                ),
                (
                    "Time domain",
                    (
                        ("Stage TCPS:", stage_time_codes_per_second),
                        ("Authoring layer TCPS:", authoring_layer_tcps),
                        ("Timeline:", f"{timeline_time_seconds:.3f} s"),
                        ("Resolved timeCode:", f"{resolved_stage_time_code:.3f}"),
                    ),
                ),
                ("Composed samples", composed_sample_fields),
                (
                    "Resolved",
                    (
                        (
                            f"TC {resolved_stage_time_code:.3f}:",
                            names_at(resolved_stage_time_code),
                        ),
                    ),
                ),
            ),
        )
        property_lines = ["", "Property stack:"]
        for index, entry in enumerate(property_stack):
            samples = entry["authored_time_samples"]
            sample_text = (
                ", ".join(
                    f"{time_code} -> "
                    f"{' | '.join(Path(value).name for value in values)}"
                    for time_code, values in samples.items()
                )
                or "none"
            )
            default_text = (
                " | ".join(Path(value).name for value in entry["default"]) or "[]"
            )
            property_lines.extend(
                (
                    "",
                    f"  Layer {index}:",
                    f"    Path: {entry['layer']}",
                    f"    TCPS: {entry['time_codes_per_second']}",
                    f"    Default: {default_text}",
                    f"    Samples: {sample_text}",
                )
            )
        message = (
            message.rsplit("\n", 1)[0]
            + "\n"
            + "\n".join(property_lines)
            + "\n"
            + "=" * 63
        )
        carb.log_warn(message)

    @classmethod
    def _kit_cae_selected_velocity_asset(
        cls, field_prim, time_code, cae_vtk, Usd
    ) -> Path | None:
        """Resolve the source VTI selected by the current USD time code."""

        file_names = cls._kit_cae_file_names_value_at_time(
            field_prim,
            time_code,
            cae_vtk,
            Usd,
        )
        if not file_names or len(file_names) != 1:
            return None
        asset_path = file_names[0]
        resolved = asset_path.resolvedPath or asset_path.path
        return Path(resolved).resolve() if resolved else None

    async def _monitor_kit_cae_temporal_proof(
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
    ) -> bool:
        """Observe all sparse VTI swaps and the closing loop in one Flow session."""

        if len(velocity_paths) < 2 or not self._flow_temporal_sample_time_codes:
            return self._log_kit_cae_temporal_proof(carb, velocity_paths)

        time_codes_per_second = float(stage.GetTimeCodesPerSecond())
        proof_event_count = len(velocity_paths) + 1

        async def record_transition(
            *,
            sequence_index: int,
            expected_asset: Path,
            previous_frame: str,
            transition: str,
            timeline_time_before: float,
            timeline_time_after: float,
            timeline_advancing: bool,
        ) -> bool:
            resolved_stage_time_code = timeline_time_after * time_codes_per_second
            if self.config.simulation_cache.temporal_debug_logging:
                self._log_kit_cae_temporal_time_mapping(
                    carb,
                    field_prim=field_prim,
                    timeline_time_seconds=timeline_time_after,
                    stage_time_codes_per_second=time_codes_per_second,
                    resolved_stage_time_code=resolved_stage_time_code,
                    cae_vtk=cae_vtk,
                    Usd=Usd,
                )
            active_asset = self._kit_cae_selected_velocity_asset(
                field_prim,
                resolved_stage_time_code,
                cae_vtk,
                Usd,
            )
            source_asset_match = active_asset == expected_asset
            operator_readiness = (
                await flow_validation.wait_for_kit_cae_dataset_emitter_ready(
                    app,
                    dataset_emitter,
                )
            )
            payload_attribute = dataset_emitter.GetAttribute("nanoVdbVelocities")
            payload = (
                payload_attribute.Get()
                if payload_attribute and payload_attribute.IsValid()
                else None
            )
            payload_count = len(payload) if payload is not None else 0
            velocity_scale = dataset_emitter.GetAttribute("velocityScale").Get()
            couple_rate_velocity = dataset_emitter.GetAttribute(
                "coupleRateVelocity"
            ).Get()
            flow_simulate = stage.GetPrimAtPath(f"{flow_environment_path}/flowSimulate")
            flow_reset = not (
                self._flow_airflow_simulate_path
                == f"{flow_environment_path}/flowSimulate"
                and flow_simulate
                and flow_simulate.IsValid()
                and dataset_emitter
                and dataset_emitter.IsValid()
                and str(dataset_emitter.GetPath()) == dataset_emitter_path
            )
            frame_evidence_valid = (
                source_asset_match
                and bool(operator_readiness["ready"])
                and not bool(operator_readiness["timed_out"])
                and payload_count > 0
                and float(couple_rate_velocity or 0.0) > 0.0
                and timeline_advancing
                and not flow_reset
                and origin_match
                and grid_match
            )
            self._log_kit_cae_temporal_frame(
                carb,
                sequence_index=sequence_index,
                temporal_frames=proof_event_count,
                asset=active_asset or expected_asset,
                previous_frame=previous_frame,
                transition=transition,
                operator_ready=bool(operator_readiness["ready"]),
                operator_wait_ms=float(operator_readiness["seconds"]) * 1000.0,
                nano_vdb_velocities_uint_count=payload_count,
                velocity_scale=velocity_scale,
                couple_rate_velocity=couple_rate_velocity,
                timeline_time_before=timeline_time_before,
                timeline_time_after=timeline_time_after,
                timeline_advancing=timeline_advancing,
                flow_reset=flow_reset,
                origin_match=origin_match,
                grid_match=grid_match,
                verbose=self.config.simulation_cache.temporal_debug_logging,
            )
            if frame_evidence_valid:
                return True

            self._log_kit_cae_temporal_failure_details(
                carb,
                reason=(
                    "source_asset_match="
                    f"{source_asset_match}, operator_ready="
                    f"{operator_readiness['ready']}, flow_reset={flow_reset}"
                ),
                timeline=timeline,
                field_prim=field_prim,
                dataset_emitter=dataset_emitter,
                cae_vtk=cae_vtk,
                Usd=Usd,
                time_codes_per_second=time_codes_per_second,
                expected_asset=expected_asset,
                flow_reset=flow_reset,
            )
            return False

        for sequence_index, expected_asset in enumerate(velocity_paths[1:], start=1):
            expected_time_code = self._flow_temporal_sample_time_codes[sequence_index]
            deadline = time.monotonic() + 8.0
            timeline_time_before = float(timeline.get_current_time())
            while (
                float(timeline.get_current_time()) * time_codes_per_second
                < expected_time_code
                and time.monotonic() < deadline
            ):
                await app.next_update_async()
            timeline_time_after = float(timeline.get_current_time())
            if timeline_time_after * time_codes_per_second < expected_time_code:
                self._log_kit_cae_temporal_failure_details(
                    carb,
                    reason=f"timeline did not reach source frame {expected_asset.name}",
                    timeline=timeline,
                    field_prim=field_prim,
                    dataset_emitter=dataset_emitter,
                    cae_vtk=cae_vtk,
                    Usd=Usd,
                    time_codes_per_second=time_codes_per_second,
                    expected_asset=expected_asset,
                )
                self._log_kit_cae_temporal_proof(carb, velocity_paths)
                return False
            if not await record_transition(
                sequence_index=sequence_index,
                expected_asset=expected_asset,
                previous_frame=self._kit_cae_vti_source_frame(
                    velocity_paths[sequence_index - 1]
                ),
                transition="SWAP",
                timeline_time_before=timeline_time_before,
                timeline_time_after=timeline_time_after,
                timeline_advancing=timeline_time_after > timeline_time_before,
            ):
                self._log_kit_cae_temporal_proof(carb, velocity_paths)
                return False

        loop_deadline = time.monotonic() + 8.0
        previous_time = float(timeline.get_current_time())
        loop_time_before = previous_time
        loop_time_after = previous_time
        loop_observed = False
        while time.monotonic() < loop_deadline:
            await app.next_update_async()
            current_time = float(timeline.get_current_time())
            if current_time + 1e-6 < previous_time:
                loop_time_before = previous_time
                await app.next_update_async()
                loop_time_after = float(timeline.get_current_time())
                loop_observed = True
                break
            previous_time = current_time

        if not loop_observed:
            self._log_kit_cae_temporal_failure_details(
                carb,
                reason="timeline did not close the Stage 6 temporal loop",
                timeline=timeline,
                field_prim=field_prim,
                dataset_emitter=dataset_emitter,
                cae_vtk=cae_vtk,
                Usd=Usd,
                time_codes_per_second=time_codes_per_second,
                expected_asset=velocity_paths[0],
            )
            self._log_kit_cae_temporal_proof(carb, velocity_paths)
            return False

        if not await record_transition(
            sequence_index=len(velocity_paths),
            expected_asset=velocity_paths[0],
            previous_frame=self._kit_cae_vti_source_frame(velocity_paths[-1]),
            transition="LOOP",
            timeline_time_before=loop_time_before,
            timeline_time_after=loop_time_after,
            timeline_advancing=True,
        ):
            self._log_kit_cae_temporal_proof(carb, velocity_paths)
            return False

        return self._log_kit_cae_temporal_proof(carb, velocity_paths)

    def _log_kit_cae_temporal_failure_details(
        self,
        carb,
        *,
        reason: str,
        timeline,
        field_prim,
        dataset_emitter,
        cae_vtk,
        Usd,
        time_codes_per_second: float,
        expected_asset: Path | None = None,
        flow_reset: bool = False,
    ) -> None:
        """Emit expanded evidence only when one temporal proof invariant fails."""

        current_time_code = float(timeline.get_current_time()) * time_codes_per_second
        selected_asset = self._kit_cae_selected_velocity_asset(
            field_prim,
            current_time_code,
            cae_vtk,
            Usd,
        )
        self._flow_temporal_failure = {
            "reason": reason,
            "expected_asset": expected_asset.name if expected_asset else "unavailable",
            "resolved_asset": selected_asset.name if selected_asset else "unavailable",
        }
        payload_attribute = dataset_emitter.GetAttribute("nanoVdbVelocities")
        payload = (
            payload_attribute.Get()
            if payload_attribute and payload_attribute.IsValid()
            else None
        )
        velocity_scale = dataset_emitter.GetAttribute("velocityScale").Get()
        couple_rate_velocity = dataset_emitter.GetAttribute("coupleRateVelocity").Get()
        operator_ready = (
            payload is not None
            and len(payload) > 0
            and float(couple_rate_velocity or 0.0) > 0.0
        )
        carb.log_error(
            self._format_flow_log_block(
                "FAILURE DIAGNOSTICS",
                (
                    (
                        "Failure",
                        (("Reason:", reason),),
                    ),
                    (
                        "Expected",
                        (
                            (
                                "Frame:",
                                (
                                    self._kit_cae_vti_source_frame(expected_asset)
                                    if expected_asset
                                    else "unavailable"
                                ),
                            ),
                            (
                                "Asset:",
                                (
                                    expected_asset.name
                                    if expected_asset
                                    else "unavailable"
                                ),
                            ),
                        ),
                    ),
                    (
                        "Observed",
                        (
                            (
                                "Frame:",
                                (
                                    self._kit_cae_vti_source_frame(selected_asset)
                                    if selected_asset
                                    else "unavailable"
                                ),
                            ),
                            (
                                "Asset:",
                                (
                                    selected_asset.name
                                    if selected_asset
                                    else "unavailable"
                                ),
                            ),
                        ),
                    ),
                    (
                        "Flow state",
                        (
                            ("operator_ready:", operator_ready),
                            (
                                "NanoVDB count:",
                                len(payload) if payload is not None else 0,
                            ),
                            ("Velocity scale:", self._flow_log_value(velocity_scale)),
                            (
                                "Couple rate:",
                                self._flow_log_value(couple_rate_velocity),
                            ),
                            ("flow_reset:", flow_reset),
                        ),
                    ),
                ),
            )
        )

    _read_kit_cae_vti_metadata = staticmethod(flow_validation.read_kit_cae_vti_metadata)
    _wait_for_kit_cae_dataset_emitter_ready = staticmethod(
        flow_validation.wait_for_kit_cae_dataset_emitter_ready
    )
    _trace_kit_cae_dav_velocity_dataset = staticmethod(
        flow_validation.trace_kit_cae_dav_velocity_dataset
    )

    _kit_cae_front_intake_tracer_positions = staticmethod(
        flow_smoke.kit_cae_front_intake_tracer_positions
    )

    _configure_kit_cae_intake_tracer_emitter = staticmethod(
        flow_smoke.configure_kit_cae_intake_tracer_emitter
    )
    _configure_kit_cae_smoke_only_tracer_flow = staticmethod(
        flow_smoke.configure_kit_cae_smoke_only_tracer_flow
    )
    _author_kit_cae_smoke_tuning = staticmethod(flow_smoke.author_kit_cae_smoke_tuning)
    _set_kit_cae_spatial_sanity_wireframes_visibility = staticmethod(
        flow_smoke.set_kit_cae_spatial_sanity_wireframes_visibility
    )
    _hide_kit_cae_intake_tracer_meshes = staticmethod(
        flow_smoke.hide_kit_cae_intake_tracer_meshes
    )
    _clear_kit_cae_server_visibility_session_opinion = staticmethod(
        flow_smoke.clear_kit_cae_server_visibility_session_opinion
    )
    _pulse_kit_cae_flow_clear = staticmethod(flow_smoke.pulse_kit_cae_flow_clear)

    def set_kit_cae_debug_overlays_visible_in_kit(
        self,
        visible: bool,
    ) -> SimulationCacheResult:
        """Show or hide the optional Flow spatial-sanity wireframes."""

        import omni.usd
        from pxr import UsdGeom

        stage = omni.usd.get_context().get_stage()
        if not stage:
            return SimulationCacheResult(
                False, "Debug overlays skipped: no open stage."
            )
        if not flow_smoke.set_kit_cae_spatial_sanity_wireframes_visibility(
            stage,
            visible,
            UsdGeom,
        ):
            return SimulationCacheResult(
                False,
                "Attach the airflow cache before changing debug overlays.",
            )
        return SimulationCacheResult(
            True,
            f"Flow debug overlays {'shown' if visible else 'hidden'}.",
        )

    @staticmethod
    def _log_kit_cae_render_probe(
        stage,
        flow_environment_path: str,
        smoke_probe_phase: str,
        carb,
    ) -> None:
        """Report the active Flow render mode after the control run settles."""

        flow_environment = stage.GetPrimAtPath(flow_environment_path)
        simulate = (
            flow_environment.GetChild("flowSimulate") if flow_environment else None
        )
        offscreen = (
            flow_environment.GetChild("flowOffscreen") if flow_environment else None
        )
        render = flow_environment.GetChild("flowRender") if flow_environment else None
        debug_volume = offscreen.GetChild("debugVolume") if offscreen else None
        ray_march = render.GetChild("rayMarch") if render else None

        def attr_value(prim, name: str):
            attribute = prim.GetAttribute(name) if prim else None
            return attribute.Get() if attribute and attribute.IsValid() else None

        diagnostics = {
            "smoke_probe_phase": smoke_probe_phase,
            "debug_volume_present": bool(debug_volume and debug_volume.IsValid()),
            "enableVelocityAsDensity": attr_value(
                debug_volume,
                "enableVelocityAsDensity",
            ),
            "debug_velocityScale": attr_value(debug_volume, "velocityScale"),
            "rayMarch_enableRawMode": attr_value(ray_march, "enableRawMode"),
            "rayMarch_enableBlockWireframe": attr_value(
                ray_march,
                "enableBlockWireframe",
            ),
            "rayMarch_attenuation": attr_value(ray_march, "attenuation"),
            "flow_offscreen_layer": attr_value(offscreen, "layer"),
            "flow_render_layer": attr_value(render, "layer"),
            "flow_simulate_layer": attr_value(simulate, "layer"),
        }
        details = ", ".join(f"{key}={value}" for key, value in diagnostics.items())
        carb.log_warn(f"DTRS Kit-CAE render probe: {details}")

    @staticmethod
    def _log_kit_cae_origin_trace(
        metadata: dict[str, object],
        origin_after_import: dict[str, object],
        origin_after_dtrs_composition: dict[str, object],
        dav_origin_trace: dict[str, object],
        carb,
    ) -> None:
        """Log the origin handoff from VTI bytes through DAV's Flow input."""

        diagnostics = {
            "raw_vti_header_origin": metadata["vti_header_origin"],
            "vtkXMLImageDataReader_output_origin": metadata["vtk_reader_origin"],
            "ImageDataAPI_origin_after_import": origin_after_import["origin"],
            "ImageDataAPI_origin_after_dtrs_composition": (
                origin_after_dtrs_composition["origin"]
            ),
            "composed_usd_origin": origin_after_dtrs_composition["origin"],
            "ImageDataAPI_origin_property_stack": (
                origin_after_dtrs_composition["property_stack"]
            ),
            "dav_dataset_origin_before_FlowNanoVDBEmitter": (
                dav_origin_trace["origin"]
            ),
            "dav_dataset_bounds_before_FlowNanoVDBEmitter": (
                dav_origin_trace["bounds"]
            ),
            "dav_velocity_voxel_size_before_FlowNanoVDBEmitter": (
                dav_origin_trace["voxel_size"]
            ),
        }
        details = ", ".join(f"{key}={value}" for key, value in diagnostics.items())
        carb.log_warn(f"DTRS Kit-CAE origin trace: {details}")

    @staticmethod
    def _log_kit_cae_flow_full_diagnostics(
        stage,
        velocity_path: Path,
        metadata: dict[str, object],
        imported_grid: dict[str, object],
        dataset_path: str,
        flow_environment_path: str,
        tracer_root_path: str,
        boundary_emitter_path: str,
        dataset_emitter_path: str,
        bbox_path: str,
        field_path: str,
        velocity_selector,
        timeline,
        timeline_time_before: float,
        timeline_time_after: float,
        operator_readiness: dict[str, object],
        smoke_probe_phase: str,
        Usd,
        UsdGeom,
        carb,
    ) -> None:
        """Report one post-settle checkpoint for the VTI -> Kit-CAE -> Flow route."""

        dimensions = metadata["dimensions"]
        vti_header_origin = metadata["vti_header_origin"]
        vti_header_spacing = metadata["spacing"]
        vti_header_max = tuple(
            vti_header_origin[index]
            + (dimensions[index] - 1) * vti_header_spacing[index]
            for index in range(3)
        )
        bbox_cache = UsdGeom.BBoxCache(
            Usd.TimeCode.Default(),
            [UsdGeom.Tokens.default_, UsdGeom.Tokens.render, UsdGeom.Tokens.proxy],
        )

        def world_bounds(
            path: str,
        ) -> tuple[tuple[float, float, float], tuple[float, float, float]] | None:
            prim = stage.GetPrimAtPath(path)
            if not prim or not prim.IsValid():
                return None
            bounds = bbox_cache.ComputeWorldBound(prim).ComputeAlignedRange()
            if bounds.IsEmpty():
                return None
            return tuple(bounds.GetMin()), tuple(bounds.GetMax())

        def attr_value(prim, name: str):
            if not prim or not prim.IsValid():
                return None
            attribute = prim.GetAttribute(name)
            return attribute.Get() if attribute and attribute.IsValid() else None

        def relationship_targets(prim, name: str) -> list[str]:
            if not prim or not prim.IsValid():
                return []
            relationship = prim.GetRelationship(name)
            if not relationship or not relationship.IsValid():
                return []
            return [str(path) for path in relationship.GetTargets()]

        def array_count(prim, name: str) -> int | None:
            value = attr_value(prim, name)
            return len(value) if value is not None else None

        dataset_prim = stage.GetPrimAtPath(dataset_path)
        field_prim = stage.GetPrimAtPath(field_path)
        flow_environment = stage.GetPrimAtPath(flow_environment_path)
        flow_simulate = (
            flow_environment.GetChild("flowSimulate") if flow_environment else None
        )
        flow_offscreen = (
            flow_environment.GetChild("flowOffscreen") if flow_environment else None
        )
        flow_render = (
            flow_environment.GetChild("flowRender") if flow_environment else None
        )
        flow_colormap = flow_offscreen.GetChild("colormap") if flow_offscreen else None
        dataset_emitter = stage.GetPrimAtPath(dataset_emitter_path)
        tracer_root = stage.GetPrimAtPath(tracer_root_path)
        tracer_meshes = (
            [prim for prim in tracer_root.GetChildren() if prim.IsA(UsdGeom.Mesh)]
            if tracer_root and tracer_root.IsValid()
            else []
        )
        smoke_injector = tracer_meshes[0] if tracer_meshes else None
        smoke_emitter = (
            smoke_injector.GetChild("EmitterSphere") if smoke_injector else None
        )
        smoke_position = None
        smoke_local_scale = None
        if smoke_injector and smoke_injector.IsValid():
            injector_xform = UsdGeom.Xformable(smoke_injector)
            smoke_position = tuple(
                injector_xform.ComputeLocalToWorldTransform(
                    Usd.TimeCode.Default()
                ).ExtractTranslation()
            )
            scale_op = next(
                (
                    op
                    for op in injector_xform.GetOrderedXformOps()
                    if op.GetOpType() == UsdGeom.XformOp.TypeScale
                ),
                None,
            )
            smoke_local_scale = (
                tuple(scale_op.Get())
                if scale_op and scale_op.Get() is not None
                else None
            )

        bbox_world_bounds = world_bounds(bbox_path)
        colormap_rgba_points = attr_value(flow_colormap, "rgbaPoints")
        colormap_alpha_values = (
            tuple(float(point[3]) for point in colormap_rgba_points)
            if colormap_rgba_points is not None
            else None
        )
        smoke_injector_mesh_visible = (
            UsdGeom.Imageable(smoke_injector).ComputeVisibility()
            != UsdGeom.Tokens.invisible
            if smoke_injector and smoke_injector.IsValid()
            else None
        )
        server_prim = stage.GetPrimAtPath(flow_smoke.KIT_CAE_SERVER_ROOT)
        server_visible = (
            UsdGeom.Imageable(server_prim).ComputeVisibility()
            != UsdGeom.Tokens.invisible
            if server_prim and server_prim.IsValid()
            else None
        )
        smoke_radius = attr_value(smoke_emitter, "radius")
        radius_is_world_space = attr_value(smoke_emitter, "radiusIsWorldSpace")
        world_radius = None
        if smoke_radius is not None:
            world_radius = (
                float(smoke_radius)
                if radius_is_world_space
                else float(smoke_radius) * max(smoke_local_scale or (1.0,))
            )
        injector_inside_bounds = bool(
            smoke_position is not None
            and world_radius is not None
            and bbox_world_bounds is not None
            and all(
                bbox_world_bounds[0][index] <= smoke_position[index] - world_radius
                and smoke_position[index] + world_radius <= bbox_world_bounds[1][index]
                for index in range(3)
            )
        )

        boundary_root = stage.GetPrimAtPath(boundary_emitter_path)
        boundary_emitters = (
            [
                prim
                for prim in Usd.PrimRange(boundary_root)
                if prim.GetTypeName() == "FlowEmitterBox"
            ]
            if boundary_root and boundary_root.IsValid()
            else []
        )
        target_paths = [
            str(path) for path in velocity_selector.GetTargetRel().GetTargets()
        ]
        advection = flow_simulate.GetChild("advection") if flow_simulate else None
        ray_march = flow_render.GetChild("rayMarch") if flow_render else None
        data_set_bbox_match = bbox_world_bounds is not None and all(
            abs(
                bbox_world_bounds[bound][axis]
                - imported_grid["world_bounds"][bound][axis]
            )
            < 1e-5
            for bound in range(2)
            for axis in range(3)
        )
        diagnostics = [
            ("active_route", "VTI_KIT_CAE_FLOW"),
            ("vti_asset_path", velocity_path),
            ("dataset_path", dataset_path),
            ("dataset_prim_type", dataset_prim.GetTypeName()),
            ("velocity_field_path", field_path),
            ("velocity_field_association", attr_value(field_prim, "fieldAssociation")),
            ("velocity_field_components", metadata["components"]),
            ("velocity_field_dtype", metadata["data_type"]),
            ("vti_header_origin", vti_header_origin),
            ("vti_header_spacing", vti_header_spacing),
            ("usd_imagedata_origin", imported_grid["origin"]),
            ("vti_world_bounds", (vti_header_origin, vti_header_max)),
            ("dataset_world_bounds", imported_grid["world_bounds"]),
            ("kit_cae_imported_spacing", imported_grid["spacing"]),
            ("vti_dimensions", dimensions),
            ("server_bounds", world_bounds("/blackwell_rig")),
            ("bbox_world_bounds", bbox_world_bounds),
            ("flow_world_bounds", bbox_world_bounds),
            ("dataset_bbox_bounds_match", data_set_bbox_match),
            ("flow_environment_path", flow_environment_path),
            ("flow_simulate_path", flow_simulate.GetPath() if flow_simulate else None),
            ("flow_simulate_layer", attr_value(flow_simulate, "layer")),
            ("densityCellSize", attr_value(flow_simulate, "densityCellSize")),
            ("forceDisableEmitters", attr_value(flow_simulate, "forceDisableEmitters")),
            (
                "forceDisableCoreSimulation",
                attr_value(flow_simulate, "forceDisableCoreSimulation"),
            ),
            ("forceClear", attr_value(flow_simulate, "forceClear")),
            ("forceSimulate", attr_value(flow_simulate, "forceSimulate")),
            ("flow_offscreen_layer", attr_value(flow_offscreen, "layer")),
            ("flow_render_layer", attr_value(flow_render, "layer")),
            ("buoyancyPerTemp", attr_value(advection, "buoyancyPerTemp")),
            ("burnPerTemp", attr_value(advection, "burnPerTemp")),
            ("fuelPerBurn", attr_value(advection, "fuelPerBurn")),
            ("ignitionTemp", attr_value(advection, "ignitionTemp")),
            ("rayMarch_attenuation", attr_value(ray_march, "attenuation")),
            ("rayMarch_colormap_alphas", colormap_alpha_values),
            ("dataset_emitter_path", dataset_emitter_path),
            (
                "dataset_emitter_prim_type",
                dataset_emitter.GetTypeName() if dataset_emitter else None,
            ),
            ("dataset_emitter_layer", attr_value(dataset_emitter, "layer")),
            (
                "operator_enabled",
                attr_value(dataset_emitter, "cae:viz:operator:enabled"),
            ),
            (
                "source_targets",
                relationship_targets(
                    dataset_emitter,
                    "cae:viz:dataset_selection:source:target",
                ),
            ),
            ("velocity_targets", target_paths),
            (
                "rescaleMode",
                attr_value(
                    dataset_emitter,
                    "cae:viz:configure_flow_environment:source:rescaleMode",
                ),
            ),
            (
                "densityCellSizeIncludes",
                relationship_targets(
                    dataset_emitter,
                    "cae:viz:configure_flow_environment:source:densityCellSizeIncludes",
                ),
            ),
            (
                "nanoVdbVelocities_present",
                attr_value(dataset_emitter, "nanoVdbVelocities") is not None,
            ),
            (
                "nanoVdbVelocities_type",
                (
                    dataset_emitter.GetAttribute("nanoVdbVelocities").GetTypeName()
                    if dataset_emitter
                    and dataset_emitter.GetAttribute("nanoVdbVelocities")
                    else None
                ),
            ),
            (
                "nanoVdbVelocities_uint_count",
                array_count(dataset_emitter, "nanoVdbVelocities"),
            ),
            ("velocityScale", attr_value(dataset_emitter, "velocityScale")),
            (
                "coupleRateVelocity",
                attr_value(dataset_emitter, "coupleRateVelocity"),
            ),
            ("operator_ready", operator_readiness["ready"]),
            ("operator_wait_cycles", operator_readiness["cycles"]),
            ("operator_wait_seconds", f"{operator_readiness['seconds']:.3f}"),
            ("operator_wait_timed_out", operator_readiness["timed_out"]),
            ("allocationScale", attr_value(dataset_emitter, "allocationScale")),
            ("applyPostPressure", attr_value(dataset_emitter, "applyPostPressure")),
            ("tracer_root_path", tracer_root_path),
            ("tracer_mesh_count", len(tracer_meshes)),
            (
                "smoke_emitter_path",
                smoke_emitter.GetPath() if smoke_emitter else None,
            ),
            (
                "smoke_emitter_prim_type",
                smoke_emitter.GetTypeName() if smoke_emitter else None,
            ),
            ("smoke_probe_phase", smoke_probe_phase),
            ("server_visible", server_visible),
            ("smoke_injector_mesh_visible", smoke_injector_mesh_visible),
            ("smoke_emitter_enabled", attr_value(smoke_emitter, "enabled")),
            (
                "smoke_emitter_allocationScale",
                attr_value(smoke_emitter, "allocationScale"),
            ),
            ("smoke_injector_local_scale", smoke_local_scale),
            ("smoke_injector_world_scale", smoke_local_scale),
            ("emitter_position", smoke_position),
            ("emitter_layer", attr_value(smoke_emitter, "layer")),
            ("radius", smoke_radius),
            ("radiusIsWorldSpace", radius_is_world_space),
            ("smoke", attr_value(smoke_emitter, "smoke")),
            ("coupleRateSmoke", attr_value(smoke_emitter, "coupleRateSmoke")),
            ("burn", attr_value(smoke_emitter, "burn")),
            ("coupleRateBurn", attr_value(smoke_emitter, "coupleRateBurn")),
            ("fuel", attr_value(smoke_emitter, "fuel")),
            ("coupleRateFuel", attr_value(smoke_emitter, "coupleRateFuel")),
            ("temperature", attr_value(smoke_emitter, "temperature")),
            (
                "coupleRateTemperature",
                attr_value(smoke_emitter, "coupleRateTemperature"),
            ),
            (
                "smoke_emitter_coupleRateVelocity",
                attr_value(smoke_emitter, "coupleRateVelocity"),
            ),
            ("injector_inside_flow_bounds", injector_inside_bounds),
            ("boundary_emitter_path", boundary_emitter_path),
            ("boundary_emitter_count", len(boundary_emitters)),
            (
                "boundary_layers",
                [attr_value(prim, "layer") for prim in boundary_emitters],
            ),
            (
                "all_boundary_emitters_valid",
                len(boundary_emitters) == 6
                and all(prim.IsValid() for prim in boundary_emitters),
            ),
            ("timeline_is_playing", timeline.is_playing()),
            ("timeline_time_before", timeline_time_before),
            ("timeline_time_after", timeline_time_after),
            ("timeline_advancing", timeline_time_after > timeline_time_before),
            ("stage_timeCodesPerSecond", stage.GetTimeCodesPerSecond()),
        ]
        details = ", ".join(f"{key}={value}" for key, value in diagnostics)
        carb.log_warn(f"DTRS Kit-CAE Flow full diagnostics: {details}")

    @staticmethod
    def _validate_kit_cae_velocity_field(
        dataset_prim,
        field_prim,
        metadata: dict[str, object],
        cae,
        cae_vtk,
    ) -> dict[str, object]:
        """Verify that Kit-CAE represented the Houdini VTI as a point vector field."""

        if not dataset_prim or not dataset_prim.IsA(cae.DataSet):
            raise RuntimeError("Kit-CAE did not create a CaeDataSet from the VTI.")
        if not dataset_prim.HasAPI(cae.DenseVolumeAPI):
            raise RuntimeError("Kit-CAE VTI dataset is missing DenseVolumeAPI.")
        if not field_prim or field_prim.GetTypeName() != "CaeVtkFieldArray":
            raise RuntimeError("Kit-CAE did not create the expected CaeVtkFieldArray.")
        association = str(field_prim.GetAttribute("fieldAssociation").Get())
        if association != str(cae.Tokens.vertex):
            raise RuntimeError(
                "Kit-CAE velocity field is not associated with VTI PointData."
            )

        dense_volume = cae.DenseVolumeAPI(dataset_prim)
        min_extent = dense_volume.GetMinExtentAttr().Get()
        max_extent = dense_volume.GetMaxExtentAttr().Get()
        imported_dimensions = tuple(
            int(max_extent[index] - min_extent[index] + 1) for index in range(3)
        )
        if imported_dimensions != metadata["dimensions"]:
            raise RuntimeError(
                "Kit-CAE VTI dimensions do not match the source VTI PointData grid."
            )
        imported_spacing = tuple(
            float(value) for value in dense_volume.GetSpacingAttr().Get()
        )
        expected_spacing = metadata["spacing"]
        if any(
            abs(imported_spacing[index] - expected_spacing[index]) > 1e-6
            for index in range(3)
        ):
            raise RuntimeError(
                "Kit-CAE VTI spacing does not match the source VTI grid."
            )

        image_data = cae_vtk.ImageDataAPI(dataset_prim)
        imported_origin = tuple(
            float(value) for value in image_data.GetOriginAttr().Get()
        )
        imported_min = tuple(
            imported_origin[index] + min_extent[index] * imported_spacing[index]
            for index in range(3)
        )
        imported_max = tuple(
            imported_origin[index] + max_extent[index] * imported_spacing[index]
            for index in range(3)
        )
        return {
            "origin": imported_origin,
            "spacing": imported_spacing,
            "world_bounds": (imported_min, imported_max),
        }

    @staticmethod
    def _read_kit_cae_vti_origin_opinion(
        dataset_prim,
        cae_vtk,
    ) -> dict[str, object]:
        """Capture the composed ImageData origin and each authored USD opinion."""

        if not dataset_prim or not dataset_prim.IsValid():
            raise RuntimeError("Kit-CAE did not create a VTI dataset to inspect.")
        origin_attr = cae_vtk.ImageDataAPI(dataset_prim).GetOriginAttr()
        if not origin_attr or not origin_attr.IsValid():
            raise RuntimeError("Kit-CAE VTI dataset is missing ImageDataAPI.origin.")

        def serialise_value(value):
            if value is None:
                return None
            try:
                return tuple(float(component) for component in value)
            except TypeError:
                return str(value)

        return {
            "origin": serialise_value(origin_attr.Get()),
            "property_stack": [
                {
                    "layer": spec.layer.identifier,
                    "path": str(spec.path),
                    "default": serialise_value(spec.default),
                }
                for spec in origin_attr.GetPropertyStack()
            ],
        }

    @staticmethod
    def _author_kit_cae_vti_origin_session_opinion(
        dataset_prim,
        vti_header_origin: tuple[float, float, float],
        cae_vtk,
        Gf,
    ) -> None:
        """Restore the VTI origin through the active DTRS session layer."""

        if not dataset_prim or not dataset_prim.IsValid():
            raise RuntimeError("Kit-CAE did not create a VTI dataset to register.")
        origin_attr = cae_vtk.ImageDataAPI(dataset_prim).GetOriginAttr()
        if not origin_attr or not origin_attr.IsValid():
            raise RuntimeError("Kit-CAE VTI dataset is missing ImageDataAPI.origin.")
        origin_attr.Set(Gf.Vec3f(*vti_header_origin))

    @staticmethod
    def _author_kit_cae_spatial_sanity_wireframes(
        stage,
        dataset_world_bounds: tuple[
            tuple[float, float, float], tuple[float, float, float]
        ],
        Gf,
        Usd,
        UsdGeom,
    ) -> None:
        """Draw probe-only dataset and server bounds in distinct colors."""

        bbox_cache = UsdGeom.BBoxCache(
            Usd.TimeCode.Default(),
            [UsdGeom.Tokens.default_, UsdGeom.Tokens.render, UsdGeom.Tokens.proxy],
        )
        server_prim = stage.GetPrimAtPath("/blackwell_rig")
        server_range = bbox_cache.ComputeWorldBound(server_prim).ComputeAlignedRange()
        if server_range.IsEmpty():
            raise RuntimeError(
                "Cannot draw Flow spatial sanity check: server bounds are empty."
            )
        server_world_bounds = (
            tuple(server_range.GetMin()),
            tuple(server_range.GetMax()),
        )
        root_path = "/DTRS_KitCAE/SpatialSanity"
        stage.RemovePrim(root_path)
        root = UsdGeom.Xform.Define(stage, root_path)
        UsdGeom.Imageable(root.GetPrim()).CreateVisibilityAttr().Set(
            UsdGeom.Tokens.invisible
        )

        def author_wireframe(
            name: str,
            bounds: tuple[tuple[float, float, float], tuple[float, float, float]],
            color: tuple[float, float, float],
            width: float,
        ) -> None:
            minimum, maximum = bounds
            corners = (
                (minimum[0], minimum[1], minimum[2]),
                (maximum[0], minimum[1], minimum[2]),
                (maximum[0], maximum[1], minimum[2]),
                (minimum[0], maximum[1], minimum[2]),
                (minimum[0], minimum[1], maximum[2]),
                (maximum[0], minimum[1], maximum[2]),
                (maximum[0], maximum[1], maximum[2]),
                (minimum[0], maximum[1], maximum[2]),
            )
            edges = (
                (0, 1),
                (1, 2),
                (2, 3),
                (3, 0),
                (4, 5),
                (5, 6),
                (6, 7),
                (7, 4),
                (0, 4),
                (1, 5),
                (2, 6),
                (3, 7),
            )
            points = [Gf.Vec3f(*corners[index]) for edge in edges for index in edge]
            curve = UsdGeom.BasisCurves.Define(stage, f"{root_path}/{name}")
            curve.CreateTypeAttr(UsdGeom.Tokens.linear)
            curve.CreateCurveVertexCountsAttr([2] * len(edges))
            curve.CreatePointsAttr(points)
            curve.CreateWidthsAttr([width] * len(points))
            curve.CreateDisplayColorPrimvar(UsdGeom.Tokens.vertex).Set(
                [Gf.Vec3f(*color)] * len(points)
            )

        # The wider server frame remains visible around an aligned dataset frame.
        author_wireframe(
            "ServerBounds",
            server_world_bounds,
            (1.0, 0.28, 0.55),
            0.003,
        )
        author_wireframe(
            "DatasetBounds",
            dataset_world_bounds,
            (0.1, 0.9, 1.0),
            0.0015,
        )

    # FLOW_RUNTIME_METHODS
