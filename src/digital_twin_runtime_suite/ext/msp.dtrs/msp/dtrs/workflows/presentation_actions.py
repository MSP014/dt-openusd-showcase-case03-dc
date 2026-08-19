"""Synchronous presentation actions triggered by View controls."""

from __future__ import annotations


class PresentationActionsWorkflowMixin:
    """Keep controller apply/save sequencing outside OmniUI construction code."""

    def _apply_normal_map_scale(self) -> None:
        from digital_twin_runtime_suite.app.view_controls import (
            normal_map_scale_from_model,
        )

        if not self._normal_map_scale_model:
            self._set_status("Normal Map Scale control is unavailable.")
            return
        try:
            scale = normal_map_scale_from_model(self._normal_map_scale_model)
        except ValueError as error:
            self._set_status(f"Normal Map Scale is invalid: {error}")
            return
        result = self._controller.apply_normal_map_scale_in_kit(scale)
        if not result.success:
            self._set_status(result.message)
            return
        try:
            self._controller.save_normal_map_scale_override(scale)
        except OSError as error:
            self._set_status(f"Normal Map Scale was applied but not saved: {error}")
            return
        self._set_status(f"{result.message} Saved to local config.")

    def _apply_xray_material(self) -> None:
        try:
            xray = self._xray_config_from_controls()
        except ValueError as error:
            self._set_status(f"X-Ray settings are invalid: {error}")
            return
        result = self._controller.apply_manual_xray_material_in_kit(
            xray, self._selected_xray_target_ids()
        )
        try:
            self._controller.save_xray_material_override(xray)
        except OSError as error:
            self._set_status(f"X-Ray settings were not saved: {error}")
            return
        if not result.success:
            self._set_status(result.message)
            return
        self._sync_xray_target_controls()
        self._set_status(f"{result.message} Saved to local config.")

    def _reset_lighting_controls(self) -> None:
        config = self._controller.clear_lighting_override()
        self._set_lighting_controls(config.lighting)
        self._set_lighting_status("Lighting controls reset to project defaults.")

    def _save_current_runtime_override(self) -> None:
        if not self._controller or not self._hdri_model:
            return

        try:
            lighting = self._build_lighting_config_from_controls()
            camera = self._controller.capture_review_camera_config()
            grid = self._build_grid_config_from_controls()
            self._controller.save_runtime_override(lighting, camera, grid)
            self._set_status("Settings saved.")
        except Exception:  # noqa: BLE001
            return

    def _save_camera_position(self) -> None:
        if not self._controller:
            return

        camera = self._controller.capture_review_camera_config()
        if not camera:
            self._set_status("Camera save skipped: no review camera.")
            return

        try:
            lighting = self._build_lighting_config_from_controls()
            grid = self._build_grid_config_from_controls()
            self._controller.save_runtime_override(lighting, camera, grid)
            self._set_camera_controls(camera)
            self._suspend_camera_sync_until = 0.0
            self._set_status("Camera position saved.")
        except Exception:  # noqa: BLE001
            self._set_status("Camera save failed.")
