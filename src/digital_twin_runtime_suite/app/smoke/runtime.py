"""Smoke and tracer presentation built on an attached Flow session."""

from __future__ import annotations

from dataclasses import replace

from digital_twin_runtime_suite.app.config import (
    EmitterLayoutConfig,
    SmokeTuningConfig,
    validate_emitter_layout,
    validate_smoke_tuning,
)
from digital_twin_runtime_suite.app.flow.runtime import SimulationCacheResult
from digital_twin_runtime_suite.app.smoke import flow as smoke_flow


class SmokeRuntimeMixin:
    """Own smoke tuning, tracer layout, and Flow smoke presentation hooks."""

    EMITTER_REBUILD_SETTLE_UPDATES = 3

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
            effective_velocity_scale = smoke_flow.author_kit_cae_smoke_tuning(
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
            derived = smoke_flow.kit_cae_front_intake_emitter_layout(
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
                smoke_flow.configure_kit_cae_intake_tracer_emitter(
                    stage,
                    tracer_path,
                    position,
                    tracer_config,
                    Gf,
                    UsdGeom,
                )
            smoke_flow.hide_kit_cae_intake_tracer_meshes(
                stage,
                tracer_root_path,
                UsdGeom,
                expected_count=len(derived.positions),
            )
            for _ in range(self.EMITTER_REBUILD_SETTLE_UPDATES):
                await app.next_update_async()
            verified_emitters = smoke_flow.verify_kit_cae_intake_tracer_emitters(
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

    def _derive_attached_smoke_emitter_layout(self, *args, **kwargs):
        return smoke_flow.kit_cae_front_intake_emitter_layout(*args, **kwargs)

    def _configure_attached_smoke_tracer(self, *args, **kwargs) -> None:
        smoke_flow.configure_kit_cae_intake_tracer_emitter(*args, **kwargs)

    def _hide_attached_smoke_tracer_meshes(self, *args, **kwargs) -> None:
        smoke_flow.hide_kit_cae_intake_tracer_meshes(*args, **kwargs)

    def _configure_attached_smoke_presentation(self, *args, **kwargs) -> None:
        smoke_flow.configure_kit_cae_smoke_only_tracer_flow(*args, **kwargs)

    async def _pulse_attached_smoke_clear(self, *args, **kwargs) -> None:
        await smoke_flow.pulse_kit_cae_flow_clear(*args, **kwargs)

    def _clear_attached_smoke_server_visibility(self, *args, **kwargs) -> bool:
        return smoke_flow.clear_kit_cae_server_visibility_session_opinion(
            *args, **kwargs
        )

    def _apply_attached_velocity_scale(self, *args, **kwargs) -> float:
        return smoke_flow.apply_kit_cae_direct_attach_velocity_scale(*args, **kwargs)
