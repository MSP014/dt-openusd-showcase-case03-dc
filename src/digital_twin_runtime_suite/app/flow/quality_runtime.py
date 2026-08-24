# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""Live voxel-resolution switching for an attached Flow session."""

from __future__ import annotations

from digital_twin_runtime_suite.app.diagnostics import with_dtrs_local_timestamp
from digital_twin_runtime_suite.app.flow import validation as flow_validation
from digital_twin_runtime_suite.app.flow.quality import (
    validate_kit_cae_flow_voxel_resolution,
)
from digital_twin_runtime_suite.app.flow.runtime import SimulationCacheResult
from digital_twin_runtime_suite.app.status_log import format_dtrs_diagnostic_block


class FlowQualityRuntimeMixin:
    """Own runtime-only DatasetVoxelization A/B switching."""

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
            await self._pulse_attached_smoke_clear(app, flow_environment_path)
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
                await self._pulse_attached_smoke_clear(
                    app,
                    flow_environment_path,
                )
                if timeline_restarted:
                    self._restart_kit_cae_temporal_loop(timeline)
            except Exception as recovery_error:  # noqa: BLE001
                carb.log_error(
                    format_dtrs_diagnostic_block(
                        owner="FLOW",
                        process="VOXEL RESOLUTION",
                        state="RECOVERY FAIL",
                        details={"reason": str(recovery_error)},
                        append_local_timestamp=with_dtrs_local_timestamp,
                    )
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
