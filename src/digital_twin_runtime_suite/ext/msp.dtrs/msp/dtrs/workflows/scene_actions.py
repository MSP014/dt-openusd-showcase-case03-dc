"""Application-level task ownership for scene and Flow user actions."""

from __future__ import annotations

import asyncio
import time

import carb

COMPACT_TEXT_LENGTH = 44


def _compact_text(value: str, max_length: int = COMPACT_TEXT_LENGTH) -> str:
    text = str(value)
    if len(text) <= max_length:
        return text
    return f"{text[: max_length - 3]}..."


class SceneActionsWorkflowMixin:
    """Own scene-action sequencing and cancellation at the application boundary."""

    def _reload_config(self) -> None:
        if self._reload_task and not self._reload_task.done():
            self._set_status("Configuration reload is already running.")
            return
        self._reload_task = asyncio.ensure_future(self._reload_config_and_stage())

    async def _reload_config_and_stage(self) -> None:
        try:
            heatmaps_cleanup = self._controller.clear_heatmap_full_server_test_in_kit()
        except RuntimeError as error:
            self._set_status(f"Heatmaps cleanup before Reload Config failed: {error}")
            return
        if not heatmaps_cleanup.success:
            self._set_status(heatmaps_cleanup.message)
            return
        self._reset_heatmap_test_isolation_control()
        try:
            cleanup = self._controller.clear_xray_material_in_kit()
        except RuntimeError as error:
            self._set_status(f"X-Ray cleanup before Reload Config failed: {error}")
            return
        if not cleanup.success:
            self._set_status(cleanup.message)
            return
        try:
            streamlines_cleanup = (
                self._controller.clear_streamlines_static_runtime_from_open_stage()
            )
        except Exception as error:  # noqa: BLE001 - keep Reload Config usable.
            self._set_status(
                f"Streamlines cleanup before Reload Config failed: {error}"
            )
            return
        if not streamlines_cleanup.clean:
            self._set_status(
                "Streamlines cleanup before Reload Config left runtime state."
            )
            return
        try:
            config = self._controller.reload_config()
        except RuntimeError:
            self._set_status("Detach airflow before reloading config")
            return
        if self._motion_controller:
            self._motion_controller.reset()
        # Motion bindings are config-backed. Rebuild after a runtime config reload.
        from digital_twin_runtime_suite.app.motion import (
            MultiRotationMotionController,
        )

        self._motion_controller = MultiRotationMotionController(
            config.fan_motion_bindings
        )
        if self._asset_label:
            asset_text = config.default_asset.label
            self._asset_label.text = _compact_text(asset_text)
            self._asset_label.tooltip = asset_text
        self._set_lighting_controls(config.lighting)
        self._set_grid_controls(config.grid)
        self._set_chassis_visibility_controls(config.chassis_presentation)
        if config.camera:
            self._set_camera_controls(config.camera)
        if self._lighting_status_label:
            lighting_text = f"HDRI: {config.default_hdri_path.name}"
            self._lighting_status_label.text = _compact_text(lighting_text)
            self._lighting_status_label.tooltip = lighting_text
        self._set_airflow_status("Not attached")
        result = await self._load_default_asset("Reload Config (stage open)")
        if result.success:
            self._set_status("Configuration reloaded and stage reopened.")

    @staticmethod
    def _asset_loaded_status(message: str) -> str:
        if "viewport framed" in message:
            return "Asset loaded; viewport framed."
        return "Asset loaded."

    @staticmethod
    def _lighting_status_from_load(message: str) -> str:
        for marker in ("Lighting loaded:", "Missing HDRI:"):
            marker_index = message.find(marker)
            if marker_index >= 0:
                return message[marker_index:]
        return "Lighting status unavailable."

    def _schedule_load(self) -> None:
        self._load_task = asyncio.ensure_future(self._load_default_asset())

    def _schedule_apply_lighting(self) -> None:
        self._lighting_task = asyncio.ensure_future(self._apply_lighting())

    def _schedule_attach_airflow(self) -> None:
        """Keep the legacy Attach control on the primary Smoke request path."""

        from digital_twin_runtime_suite.app.visualization_mode import (
            VisualizationMode,
        )

        self._schedule_visualization_mode_request(VisualizationMode.SMOKE)

    def _schedule_visualization_mode_request(self, mode) -> None:
        """Forward a short callback adapter to the visualization workflow."""

        self._visualization_workflow.schedule_mode(mode)

    def _schedule_workload_transition(self, workload_mode: str) -> None:
        """Forward one semantic request through the visualization workflow."""

        self._visualization_workflow.schedule_workload_transition(workload_mode)

    def _schedule_detach_airflow(self) -> None:
        """Keep the legacy Detach control on the primary Normal request path."""

        from digital_twin_runtime_suite.app.visualization_mode import (
            VisualizationMode,
        )

        self._schedule_visualization_mode_request(VisualizationMode.NORMAL)
        return

    def _schedule_legacy_detach_airflow(self) -> None:
        """Retain the established cancellation implementation for internal callers."""

        transition_task = self._visualization_workflow.workload_transition_task
        if transition_task and not transition_task.done():
            transition_task.cancel()
        if self._airflow_task and not self._airflow_task.done():
            if self._airflow_detach_requested:
                self._set_airflow_status("Cancelling airflow preparation…")
                return
            if self._controller.request_flow_attach_cancellation():
                active_attach_task = self._airflow_task
                self._airflow_detach_requested = True
                self._set_airflow_status("Cancelling airflow preparation…")
                self._airflow_task = asyncio.ensure_future(
                    self._cancel_attach_then_detach(active_attach_task)
                )
                return
            self._set_airflow_status("Airflow operation is already in progress.")
            return
        self._airflow_task = asyncio.ensure_future(self._detach_airflow())

    def _schedule_apply_smoke_tuning(self) -> None:
        if self._airflow_task and not self._airflow_task.done():
            self._set_airflow_status("Airflow operation is already in progress.")
            return
        self._airflow_task = asyncio.ensure_future(self._apply_smoke_tuning())

    def _schedule_apply_flow_voxel_resolution(self) -> None:
        if self._airflow_task and not self._airflow_task.done():
            self._set_airflow_status("Airflow operation is already in progress.")
            return
        self._airflow_task = asyncio.ensure_future(self._apply_flow_voxel_resolution())

    def _schedule_apply_emitter_layout(self) -> None:
        if self._airflow_task and not self._airflow_task.done():
            self._set_airflow_status("Airflow operation is already in progress.")
            return
        self._airflow_task = asyncio.ensure_future(self._apply_emitter_layout())

    def _schedule_apply_flow_debug_overlays(self) -> None:
        if self._airflow_task and not self._airflow_task.done():
            self._set_airflow_status("Airflow operation is already in progress.")
            return
        self._airflow_task = asyncio.ensure_future(self._apply_flow_debug_overlays())

    def _capture_flow_camera_bookmark(self, name: str) -> None:
        camera = self._controller.capture_review_camera_config()
        if not camera:
            self._set_airflow_status(f"{name} camera bookmark capture failed.")
            return
        self._flow_camera_bookmarks[name] = camera
        self._set_airflow_status(f"{name} camera bookmark captured for this session.")

    def _schedule_apply_flow_camera_bookmark(self, name: str) -> None:
        if self._airflow_task and not self._airflow_task.done():
            self._set_airflow_status("Airflow operation is already in progress.")
            return
        self._airflow_task = asyncio.ensure_future(
            self._apply_flow_camera_bookmark(name)
        )

    def _schedule_apply_chassis_visibility_controls(self) -> None:
        self._view_task = asyncio.ensure_future(
            self._apply_chassis_visibility_controls()
        )

    def _play_airflow(self) -> None:
        result = self._controller.play_simulation_cache_in_kit()
        self._set_airflow_status(result.message)

    def _pause_airflow(self) -> None:
        result = self._controller.pause_simulation_cache_in_kit()
        self._set_airflow_status(result.message)

    def _reset_airflow(self) -> None:
        if self._airflow_task and not self._airflow_task.done():
            self._set_airflow_status("Airflow operation is already in progress.")
            return
        result = self._controller.reset_simulation_cache_in_kit()
        self._set_airflow_status(result.message)

    def _schedule_apply_camera(self) -> None:
        self._lighting_task = asyncio.ensure_future(self._apply_camera())

    def _schedule_apply_grid(self) -> None:
        self._lighting_task = asyncio.ensure_future(self._apply_grid())

    def _schedule_reset_camera(self) -> None:
        self._lighting_task = asyncio.ensure_future(self._reset_camera())

    async def _sync_camera_panel(self) -> None:
        try:
            import omni.kit.app

            app = omni.kit.app.get_app()
            panel_counter = 0
            while self._controller and self._window:
                await app.next_update_async()
                self._controller.sync_xray_fresnel_material_camera_in_kit()
                self._controller.advance_xray_material_performance_sampler_in_kit()
                panel_counter += 1
                if panel_counter < 15:
                    continue
                panel_counter = 0
                if time.monotonic() < self._suspend_camera_sync_until:
                    continue
                camera = self._controller.capture_review_camera_config()
                if camera:
                    self._set_camera_controls(camera)
        except asyncio.CancelledError:
            return
        except Exception:  # noqa: BLE001
            return

    async def _load_default_asset(self, event_label: str = "Load"):
        result = await self._controller.open_default_asset_in_kit(
            status_callback=self._set_status,
        )
        self._set_status(
            self._asset_loaded_status(result.message)
            if result.success
            else result.message
        )
        if result.success:
            self._set_lighting_status(self._lighting_status_from_load(result.message))
        return result

    async def _attach_airflow(self) -> None:
        def update_status(message: str) -> None:
            self._refresh_airflow_cache_selector_label()
            self._set_airflow_status(message)

        result = await self._controller.attach_simulation_cache_in_kit(
            status_callback=update_status,
        )
        self._refresh_airflow_cache_selector_label()
        self._set_airflow_status(result.message)

    async def _cancel_attach_then_detach(self, attach_task) -> None:
        """Serialize Detach behind the cooperative preflight cancellation result."""

        try:
            await attach_task
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001
            import carb

            carb.log_error(f"DTRS airflow Attach cancellation task failed: {error}")
        finally:
            self._airflow_detach_requested = False
        await self._detach_airflow()

    async def _detach_airflow(self) -> None:
        try:
            result = await self._controller.detach_simulation_cache_in_kit()
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001
            carb.log_error(f"DTRS airflow detach task failed: {error}")
            self._set_airflow_status(f"Airflow cache detach failed: {error}")
            return
        self._refresh_airflow_cache_selector_label()
        self._set_airflow_status(result.message)

    async def _apply_smoke_tuning(self) -> None:
        from digital_twin_runtime_suite.app.view_controls import (
            build_smoke_base_color_from_models,
            build_smoke_tuning_from_models,
        )

        index_models = {
            field_name: self._combo_index_model(combo)
            for field_name, combo in self._smoke_tuning_combos.items()
        }
        if any(model is None for model in index_models.values()):
            self._set_airflow_status("Smoke Tuning controls are unavailable.")
            return
        try:
            base_color = build_smoke_base_color_from_models(
                source=self._smoke_color_input_source,
                hex_model=self._smoke_color_hex_model,
                hue_model=self._smoke_color_hue_model,
                saturation_model=self._smoke_color_saturation_model,
                value_model=self._smoke_color_value_model,
            )
            tuning = build_smoke_tuning_from_models(
                index_models,
                base_color=base_color,
            )
        except ValueError as error:
            self._set_airflow_status(f"Smoke Tuning selection is invalid: {error}")
            return
        result = self._controller.apply_kit_cae_smoke_tuning_in_kit(tuning)
        self._set_airflow_status(result.message)

    async def _apply_flow_voxel_resolution(self) -> None:
        from digital_twin_runtime_suite.app.flow.quality import (
            kit_cae_flow_voxel_resolution_from_index,
        )

        model = self._combo_index_model(self._flow_voxel_resolution_combo)
        if model is None:
            self._set_airflow_status("Flow resolution control is unavailable.")
            return
        try:
            max_resolution = kit_cae_flow_voxel_resolution_from_index(model)
        except ValueError as error:
            self._set_airflow_status(f"Flow resolution selection is invalid: {error}")
            return
        result = await self._controller.apply_kit_cae_voxel_resolution_in_kit(
            max_resolution
        )
        self._set_airflow_status(result.message)

    async def _apply_emitter_layout(self) -> None:
        from digital_twin_runtime_suite.app.view_controls import (
            build_emitter_layout_from_models,
        )

        index_models = {
            field_name: self._combo_index_model(combo)
            for field_name, combo in self._emitter_layout_combos.items()
        }
        if any(model is None for model in index_models.values()):
            self._set_airflow_status("Emitter Layout controls are unavailable.")
            return
        try:
            layout = build_emitter_layout_from_models(index_models)
        except ValueError as error:
            self._set_airflow_status(f"Emitter Layout selection is invalid: {error}")
            return
        result = await self._controller.apply_kit_cae_emitter_layout_in_kit(layout)
        self._set_airflow_status(result.message)

    async def _apply_flow_debug_overlays(self) -> None:
        if not self._show_flow_debug_overlays_model:
            self._set_airflow_status("Flow debug overlay control is unavailable.")
            return
        result = self._controller.set_kit_cae_debug_overlays_visible_in_kit(
            self._show_flow_debug_overlays_model.get_value_as_bool()
        )
        self._set_airflow_status(result.message)

    async def _apply_flow_camera_bookmark(self, name: str) -> None:
        camera = self._flow_camera_bookmarks.get(name)
        if not camera:
            self._set_airflow_status(f"Capture the {name} camera bookmark first.")
            return
        applied = await self._controller.apply_camera_in_kit(
            camera,
            status_callback=self._set_airflow_status,
        )
        if applied:
            self._controller.set_flow_performance_camera_bookmark(name)
            self._set_airflow_status(f"{name} camera bookmark applied.")

    async def _apply_chassis_visibility_controls(self) -> None:
        from digital_twin_runtime_suite.app.config import (
            chassis_presentation_with_operator_state,
        )
        from digital_twin_runtime_suite.app.view_controls import (
            build_face_panel_state,
            build_visibility_state,
        )

        group_ids = tuple(
            group.group_id
            for group in self._controller.config.chassis_presentation.visibility_groups
        )
        visibility_by_group = build_visibility_state(
            self._chassis_visibility_models,
            group_ids,
        )
        face_panel_state = build_face_panel_state(self._face_panel_open_model)
        try:
            chassis_presentation_with_operator_state(
                self._controller.config.chassis_presentation,
                visibility_by_group,
                face_panel_state,
            )
        except ValueError as error:
            self._set_status(f"Server enclosure settings are invalid: {error}")
            return

        visibility_applied = True
        if group_ids:
            visibility_applied = (
                await self._controller.apply_chassis_visibility_state_in_kit(
                    visibility_by_group,
                    status_callback=self._set_status,
                )
            )
        face_panel_applied = True
        if face_panel_state is not None:
            face_panel_applied = await self._controller.apply_face_panel_state_in_kit(
                face_panel_state,
                status_callback=self._set_status,
            )
        if not visibility_applied or not face_panel_applied:
            self._set_status("Server enclosure changes were not saved.")
            return
        try:
            self._controller.save_chassis_presentation_override(
                visibility_by_group,
                face_panel_state,
            )
        except (OSError, ValueError) as error:
            self._set_status(
                f"Server enclosure applied but could not be saved: {error}"
            )
            return
        if face_panel_state is not None:
            self._face_panel_open_state = face_panel_state
            self._set_face_panel_action_label(face_panel_state)
        self._set_status("Server enclosure settings applied and saved.")

    async def _apply_lighting(self) -> None:
        lighting = self._build_lighting_config_from_controls()
        result = await self._controller.apply_lighting_in_kit(
            lighting=lighting,
            status_callback=self._set_lighting_status,
        )
        if result.success:
            self._controller.save_lighting_override(lighting)
        self._set_lighting_status(result.message)

    async def _apply_grid(self) -> None:
        grid = self._build_grid_config_from_controls()
        result = await self._controller.apply_grid_in_kit(
            grid,
            status_callback=self._set_status,
        )
        if result:
            lighting = self._build_lighting_config_from_controls()
            self._controller.save_grid_override(lighting, grid)

    async def _apply_camera(self) -> None:
        try:
            camera = self._controller.config.camera
            if not camera:
                self._set_status("Camera apply skipped: no saved camera.")
                return
            applied = await self._controller.apply_camera_in_kit(
                camera,
                status_callback=self._set_status,
            )
            if applied:
                self._set_camera_controls(camera)
                self._suspend_camera_sync_until = 0.0
        except Exception as exc:  # noqa: BLE001
            self._set_status(f"Camera apply failed: {exc}")

    async def _reset_camera(self) -> None:
        lighting = self._build_lighting_config_from_controls()
        self._controller.clear_camera_override(lighting)
        self._set_status("Camera reset to auto-framed default.")
        await self._load_default_asset()

    def _cancel_scene_action_tasks(self) -> None:
        """Cancel only tasks created by this workflow during extension teardown."""

        for task_name in (
            "_load_task",
            "_reload_task",
            "_lighting_task",
            "_airflow_task",
            "_view_task",
        ):
            task = getattr(self, task_name, None)
            if task is not None:
                task.cancel()
            setattr(self, task_name, None)
