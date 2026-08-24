# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""Smoke and tracer presentation built on an attached Flow session."""

from __future__ import annotations

from dataclasses import dataclass, replace

from digital_twin_runtime_suite.app.config import (
    EmitterLayoutConfig,
    SmokeTuningConfig,
    validate_emitter_layout,
    validate_smoke_tuning,
)
from digital_twin_runtime_suite.app.flow.runtime import SimulationCacheResult
from digital_twin_runtime_suite.app.smoke import flow as smoke_flow


@dataclass(frozen=True)
class SmokeTemporalAdvanceProof:
    """Sustained real Flow progression observed after Streamlines releases time."""

    source_0: str | None
    source_1: str | None = None
    source_2: str | None = None
    stability_source: str | None = None
    timeline_playing: bool = False

    @property
    def source_before(self) -> str | None:
        """Retain the old diagnostic name for the initial source."""

        return self.source_0

    @property
    def source_after(self) -> str | None:
        """Retain the old diagnostic name for the final required source."""

        return self.source_2

    @property
    def sustained_flow_playback(self) -> bool:
        """Require two advances plus one later playing update opportunity."""

        return bool(
            self.source_0
            and self.source_1
            and self.source_2
            and self.stability_source
            and self.source_0 != self.source_1
            and self.source_1 != self.source_2
            and self.source_2 != self.stability_source
            and self.timeline_playing
        )

    @property
    def source_advanced(self) -> bool:
        """Compatibility alias for the stronger sustained playback proof."""

        return self.sustained_flow_playback


class SmokeRuntimeMixin:
    """Own smoke tuning, tracer layout, and Flow smoke presentation hooks."""

    EMITTER_REBUILD_SETTLE_UPDATES = 3
    SMOKE_RESUME_PROOF_UPDATES = 240
    FLOW_PRESENTATION_LAYER_SEARCH_LIMIT = 64

    def flow_source_is_prepared_in_kit(self) -> bool:
        """Report retained Flow-source ownership independently of rendering."""

        return bool(
            self._flow_lifecycle_state == "ATTACHED"
            and self._flow_airflow_simulate_path
        )

    def _flow_render_prim_in_kit(self):
        """Resolve the native Flow renderer rather than its enclosing scope."""

        if not self.flow_source_is_prepared_in_kit():
            return None
        import omni.usd

        stage = omni.usd.get_context().get_stage()
        flow_path = self._flow_airflow_simulate_path.removesuffix("/flowSimulate")
        render = stage.GetPrimAtPath(f"{flow_path}/flowRender") if stage else None
        return render if render and render.IsValid() else None

    def _flow_simulate_prim_in_kit(self):
        """Resolve the retained native Flow simulation source."""

        if not self.flow_source_is_prepared_in_kit():
            return None
        import omni.usd

        stage = omni.usd.get_context().get_stage()
        simulate = (
            stage.GetPrimAtPath(self._flow_airflow_simulate_path) if stage else None
        )
        return simulate if simulate and simulate.IsValid() else None

    @staticmethod
    def _flow_layer_value(prim) -> int | None:
        """Read one native Flow layer value without assuming a USD schema."""

        attribute = prim.GetAttribute("layer") if prim else None
        if not attribute or not attribute.IsValid():
            return None
        value = attribute.Get()
        return value if isinstance(value, int) else None

    def _flow_empty_presentation_layer(self, stage, source_layer: int) -> int:
        """Choose an unpopulated Flow layer for renderer-only quiescence."""

        occupied_layers = set()
        for prim in stage.Traverse():
            if prim.GetTypeName() == "FlowSimulate":
                layer = self._flow_layer_value(prim)
                if layer is not None:
                    occupied_layers.add(layer)
        for candidate in range(
            source_layer + 1,
            source_layer + self.FLOW_PRESENTATION_LAYER_SEARCH_LIMIT + 1,
        ):
            if candidate not in occupied_layers:
                return candidate
        raise RuntimeError("No unused native Flow layer is available for Smoke.")

    def set_smoke_presentation_visible_in_kit(
        self,
        visible: bool,
    ) -> SimulationCacheResult:
        """Show or quiesce Flow smoke while retaining its prepared source."""

        if self._flow_lifecycle_state != "ATTACHED":
            return SimulationCacheResult(
                False,
                "Flow Smoke presentation is not attached.",
            )
        if not self._flow_airflow_simulate_path:
            return SimulationCacheResult(False, "Flow Smoke source is unavailable.")

        import omni.usd

        stage = omni.usd.get_context().get_stage()
        flow_render = self._flow_render_prim_in_kit()
        flow_simulate = self._flow_simulate_prim_in_kit()
        if flow_render is None or flow_simulate is None or stage is None:
            return SimulationCacheResult(
                False,
                "Flow Smoke renderer or source is missing.",
            )
        source_layer = self._flow_layer_value(flow_simulate)
        render_layer = flow_render.GetAttribute("layer")
        if source_layer is None or not render_layer or not render_layer.IsValid():
            return SimulationCacheResult(
                False,
                "Flow Smoke layer controls are unavailable.",
            )
        # FlowRender is a native Flow participant, not a UsdGeom renderer.
        # Routing only it to an unpopulated layer suppresses RTX volume output
        # without pausing or detaching the retained Flow source layer.
        target_layer = (
            source_layer
            if visible
            else self._flow_empty_presentation_layer(stage, source_layer)
        )
        previous_target = stage.GetEditTarget()
        stage.SetEditTarget(stage.GetSessionLayer())
        try:
            render_layer.Set(target_layer)
        finally:
            stage.SetEditTarget(previous_target)
        is_visible = self.smoke_presentation_is_visible_in_kit()
        if is_visible is not visible:
            return SimulationCacheResult(
                False,
                "Flow Smoke renderer visibility did not change.",
            )
        self._smoke_presentation_visible = visible
        return SimulationCacheResult(
            True,
            (
                "Flow Smoke renderer targets the prepared simulation layer."
                if visible
                else "Flow Smoke renderer targets an empty layer; source retained."
            ),
        )

    def smoke_presentation_is_visible_in_kit(self) -> bool:
        """Read the native Flow renderer state, not a requested-state flag."""

        flow_render = self._flow_render_prim_in_kit()
        flow_simulate = self._flow_simulate_prim_in_kit()
        if flow_render is None or flow_simulate is None:
            return False
        render_layer = self._flow_layer_value(flow_render)
        source_layer = self._flow_layer_value(flow_simulate)
        return render_layer is not None and render_layer == source_layer

    async def await_smoke_presentation_visibility_in_kit(self, visible: bool) -> bool:
        """Settle RTX updates before reading the native Flow visibility control."""

        import omni.kit.app

        app = omni.kit.app.get_app()
        for _ in range(3):
            await app.next_update_async()
        return self.smoke_presentation_is_visible_in_kit() is visible

    async def resume_smoke_presentation_in_kit(
        self,
        *,
        show_presentation: bool = True,
    ) -> SimulationCacheResult:
        """Restart retained Smoke and prove sustained post-cleanup progression."""

        baseline = self._kit_cae_current_temporal_source_name()
        self._smoke_resume_source_advanced = False
        self._smoke_resume_advance_proof = SmokeTemporalAdvanceProof(
            source_0=baseline,
        )
        _, dataset = self.resolve_current_airflow_dataset()
        expected = {path.name for path in dataset.velocity_vti_sequence_paths}
        if baseline not in expected:
            return SimulationCacheResult(
                False,
                "Retained Flow source has no valid initial temporal sample.",
            )
        if show_presentation:
            visible = self.set_smoke_presentation_visible_in_kit(True)
            if not visible.success:
                return visible
        played = self.play_simulation_cache_in_kit()
        if not played.success:
            return played
        import omni.kit.app
        import omni.timeline

        app = omni.kit.app.get_app()
        timeline = omni.timeline.get_timeline_interface()
        observed_sources = [baseline]
        stability_source = None
        for _ in range(self.SMOKE_RESUME_PROOF_UPDATES):
            await app.next_update_async()
            if not timeline.is_playing():
                break
            source = self._kit_cae_current_temporal_source_name()
            if source not in expected or source == observed_sources[-1]:
                continue
            if len(observed_sources) < 3:
                observed_sources.append(source)
                continue
            stability_source = source
            break
        proof = SmokeTemporalAdvanceProof(
            source_0=observed_sources[0],
            source_1=observed_sources[1] if len(observed_sources) > 1 else None,
            source_2=observed_sources[2] if len(observed_sources) > 2 else None,
            stability_source=stability_source,
            timeline_playing=bool(timeline.is_playing()),
        )
        self._smoke_resume_advance_proof = proof
        self._smoke_resume_source_advanced = proof.sustained_flow_playback
        if proof.sustained_flow_playback:
            return SimulationCacheResult(
                True,
                "Flow Smoke sustained playback: "
                f"source_0={proof.source_0}; source_1={proof.source_1}; "
                f"source_2={proof.source_2}.",
            )
        if not proof.timeline_playing:
            reason = "Flow timeline stopped during sustained Smoke resume proof."
        elif proof.source_1 is None:
            reason = "Retained Flow source did not advance after Smoke resume."
        elif proof.source_2 is None:
            reason = "One Flow source advancement is not sustained playback."
        else:
            reason = "Flow playback did not remain live for a later update opportunity."
        return SimulationCacheResult(
            False,
            reason,
        )

    def smoke_resume_source_advanced_in_kit(self) -> bool:
        """Expose the current transition's post-resume temporal proof."""

        return bool(getattr(self, "_smoke_resume_source_advanced", False))

    @staticmethod
    def flow_timeline_is_playing_in_kit() -> bool:
        """Read the production timeline state used by native Flow playback."""

        import omni.timeline

        return bool(omni.timeline.get_timeline_interface().is_playing())

    def smoke_resume_advance_proof_in_kit(self):
        """Expose sustained source progression evidence for mode acceptance."""

        return getattr(self, "_smoke_resume_advance_proof", None)

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
