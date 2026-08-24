# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""View-control models, labels, and short controller-facing UI adapters."""

from __future__ import annotations

import re
import time

import omni.ui as ui

COMPACT_TEXT_LENGTH = 44
SERVER_VIEW_LABEL_WIDTH = 150


def _compact_text(value: str, max_length: int = COMPACT_TEXT_LENGTH) -> str:
    text = str(value)
    if len(text) <= max_length:
        return text
    return f"{text[: max_length - 3]}..."


class ControlsUiMixin:
    """Own transient View controls while workflows retain async task ownership."""

    def _set_status(self, message: str) -> None:
        if self._status_label:
            self._status_label.text = _compact_text(message)
            self._status_label.tooltip = message

    def _set_lighting_status(self, message: str) -> None:
        if self._lighting_status_label:
            self._lighting_status_label.text = _compact_text(message)
            self._lighting_status_label.tooltip = message

    def _update_airflow_temporal_validation_status(self) -> None:
        """Render the DTRS-owned proof snapshot without reading Kit-CAE internals."""

        if not self._controller:
            return
        progress = self._controller.temporal_proof_progress()
        state = progress.state.value
        if state == "IDLE":
            return
        if state == "RUNNING":
            message = (
                "Airflow active: validation "
                f"{progress.validated_sample_count}/{progress.total_sample_count}; "
                f"{progress.percentage or 0}%"
            )
        elif state == "CHECKING_LOOP_CLOSURE":
            message = "Airflow active: checking loop"
        elif state == "PASSED":
            message = (
                "Airflow active: validation reused"
                if progress.result_source.value == "SESSION_CACHE"
                else "Airflow active: validation passed"
            )
        elif state == "CANCELLED":
            message = "Airflow detached"
        else:
            message = "Airflow active: validation failed"
        detail = (
            "Background temporal validation: "
            f"{progress.validated_sample_count} of {progress.total_sample_count} "
            f"samples passed. Current source: "
            f"{progress.current_asset_name or 'unavailable'}."
        )
        self._set_airflow_status(message, tooltip=detail)

    def _set_airflow_status(self, message: str, tooltip: str | None = None) -> None:
        """Publish compact DTRS airflow state to Kit's shared lower status bar."""

        import omni.kit.app

        compact_message = " ".join(str(message).splitlines()).strip()
        match = re.search(
            r"(?:VTI|USD|Validation) (\d+)/(\d+).*?(\d+)%",
            compact_message,
        )
        progress = -1.0
        if match:
            completed, total, _percentage = (int(value) for value in match.groups())
            progress = completed / total if total else -1.0

        # This bar is shared with Kit-CAE. DTRS reports only its own logical
        # preparation/proof progress and never reads or mutates Kit-CAE's internal
        # ProgressContext stack behind the separate "Fetching array" activity.
        omni.kit.app.queue_event(
            "omni.kit.window.status_bar@activity",
            payload={"text": compact_message},
        )
        omni.kit.app.queue_event(
            "omni.kit.window.status_bar@progress",
            payload={"progress": progress},
        )

    def _set_streamlines_status(self, message: str) -> None:
        """Publish the independent static-source state in its collapsed UI section."""

        if self._streamlines_status_label:
            text = f"Status: {message}"
            self._streamlines_status_label.text = _compact_text(text)
            self._streamlines_status_label.tooltip = text

    def _set_streamlines_cache_buttons_enabled(self, enabled: bool) -> None:
        """Keep production cache actions available without a restart gate."""

        if self._streamlines_cache_build_button:
            self._streamlines_cache_build_button.enabled = enabled
        if self._streamlines_cache_load_button:
            self._streamlines_cache_load_button.enabled = enabled

    def _build_visualization_controls(self) -> None:
        """Build the one primary-presentation selector and read-only readiness."""

        from digital_twin_runtime_suite.app.visualization_mode import (
            VisualizationMode,
        )

        modes = tuple(VisualizationMode)
        snapshot = self._controller.visualization_snapshot()
        active_index = modes.index(snapshot.committed)
        with ui.HStack(height=24, spacing=6, content_clipping=True):
            ui.Label("Mode", width=SERVER_VIEW_LABEL_WIDTH)
            self._visualization_combo = ui.ComboBox(
                active_index,
                *(mode.value for mode in modes),
                width=ui.Fraction(1),
            )
        for mode in modes:
            with ui.HStack(height=22, spacing=6, content_clipping=True):
                ui.Label(mode.value, width=SERVER_VIEW_LABEL_WIDTH, elided_text=True)
                self._visualization_readiness_labels[mode] = ui.Label(
                    "Checking current workload readiness…",
                    width=ui.Fraction(1),
                    elided_text=True,
                )
        model = self._combo_index_model(self._visualization_combo)
        if model:
            model.add_value_changed_fn(self._on_visualization_mode_changed)
        self._update_visualization_controls()

    def _on_visualization_mode_changed(self, model) -> None:
        """Route the selector through RuntimeController's single mode request path."""

        if self._updating_visualization_mode:
            return
        from digital_twin_runtime_suite.app.visualization_mode import (
            VisualizationMode,
        )

        index = self._model_int(model)
        modes = tuple(VisualizationMode)
        if 0 <= index < len(modes):
            self._visualization_workflow.request_mode_from_ui(modes[index])

    def _xray_config_from_controls(self):
        from digital_twin_runtime_suite.app.config import XRayMaterialConfig

        values = self._xray_fresnel_values()
        return XRayMaterialConfig(
            facing_color=values[0],
            edge_color=values[1],
            edge_center=values[2],
            edge_softness=values[3],
            edge_sharpness=values[4],
            facing_roughness=values[5],
            edge_roughness=values[6],
            facing_opacity=values[7],
            edge_opacity=values[8],
            facing_emission=values[9],
            edge_emission=values[10],
            emission_scale=values[11],
        )

    def _selected_xray_target_ids(self) -> frozenset[str]:
        """Return the UI-owned target selection without persisting it to config."""

        from digital_twin_runtime_suite.app.view_controls import (
            bool_model_value,
        )

        return frozenset(
            group_id
            for group_id, model in self._xray_target_models.items()
            if bool_model_value(model)
        )

    def _xray_fresnel_values(self):
        """Read the production-owned Fresnel parameter set from X-Ray controls."""

        from digital_twin_runtime_suite.app.view_controls import (
            hex_to_rgb,
            string_model_value,
        )

        models = self._xray_fresnel_models
        center = models["center"].get_value_as_float()
        softness = models["softness"].get_value_as_float()
        sharpness = models["sharpness"].get_value_as_float()
        facing_roughness = models["facing_roughness"].get_value_as_float()
        edge_roughness = models["edge_roughness"].get_value_as_float()
        facing_opacity = models["facing_opacity"].get_value_as_float()
        edge_opacity = models["edge_opacity"].get_value_as_float()
        facing_emission = models["facing_emission"].get_value_as_float()
        edge_emission = models["edge_emission"].get_value_as_float()
        emission_scale = models["emission_scale"].get_value_as_float()
        if (
            not 0.0 <= center <= 1.0
            or not 0.001 <= softness <= 1.0
            or not 0.1 <= sharpness <= 8.0
            or not 0.0 <= facing_roughness <= 1.0
            or not 0.0 <= edge_roughness <= 1.0
            or not 0.0 <= facing_opacity <= 1.0
            or not 0.0 <= edge_opacity <= 1.0
            or facing_emission < 0.0
            or edge_emission < 0.0
            or emission_scale < 0.0
        ):
            raise ValueError("X-Ray Fresnel values are outside their allowed range.")
        return (
            hex_to_rgb(string_model_value(models["facing"])),
            hex_to_rgb(string_model_value(models["edge"])),
            center,
            softness,
            sharpness,
            facing_roughness,
            edge_roughness,
            facing_opacity,
            edge_opacity,
            facing_emission,
            edge_emission,
            emission_scale,
        )

    def _set_lighting_controls(self, lighting) -> None:
        if self._hdri_model:
            self._hdri_model.set_value(lighting.hdri_path)
        if self._exposure_model:
            self._exposure_model.set_value(lighting.exposure)
        if self._intensity_model:
            self._intensity_model.set_value(lighting.intensity)
        if self._show_hdri_background_model:
            self._show_hdri_background_model.set_value(lighting.show_hdri_background)
        if self._review_key_model:
            self._review_key_model.set_value(lighting.review_key_light_enabled)
        if self._review_key_intensity_model:
            self._review_key_intensity_model.set_value(
                lighting.review_key_light_intensity
            )
        if self._rotation_x_model:
            self._rotation_x_model.set_value(lighting.rotation.x)
        if self._rotation_y_model:
            self._rotation_y_model.set_value(lighting.rotation.y)
        if self._rotation_z_model:
            self._rotation_z_model.set_value(lighting.rotation.z)

    def _set_grid_controls(self, grid) -> None:
        if self._grid_enabled_model:
            self._grid_enabled_model.set_value(grid.enabled)
        if self._grid_step_model:
            self._grid_step_model.set_value(grid.step)
        if self._grid_width_model:
            self._grid_width_model.set_value(grid.width)

    def _set_chassis_visibility_controls(self, presentation) -> None:
        for group in presentation.visibility_groups:
            model = self._chassis_visibility_models.get(group.group_id)
            if model:
                model.set_value(group.default_visible)
        if self._face_panel_open_model:
            self._face_panel_open_model.set_value(presentation.face_panel.default_open)
        if self._normal_map_scale_model:
            self._normal_map_scale_model.set_value(
                presentation.materials.normal_map_scale
            )
        xray = presentation.materials.xray
        # Material values reload from config, while target selection is runtime
        # state and must never silently re-author Session Layer bindings.
        for model in self._xray_target_models.values():
            model.set_value(False)
        if hasattr(self, "_xray_fresnel_models"):
            from digital_twin_runtime_suite.app.view_controls import rgb_to_hex

            models = self._xray_fresnel_models
            models["facing"].set_value(rgb_to_hex(xray.facing_color))
            models["edge"].set_value(rgb_to_hex(xray.edge_color))
            for key, value in (
                ("center", xray.edge_center),
                ("softness", xray.edge_softness),
                ("sharpness", xray.edge_sharpness),
                ("facing_roughness", xray.facing_roughness),
                ("edge_roughness", xray.edge_roughness),
                ("facing_opacity", xray.facing_opacity),
                ("edge_opacity", xray.edge_opacity),
                ("facing_emission", xray.facing_emission),
                ("edge_emission", xray.edge_emission),
                ("emission_scale", xray.emission_scale),
            ):
                models[key].set_value(value)
        self._face_panel_open_state = presentation.face_panel.default_open
        self._set_face_panel_action_label(self._face_panel_open_state)

    def _set_face_panel_action_label(self, is_open: bool) -> None:
        if not self._face_panel_action_label:
            return
        from digital_twin_runtime_suite.app.view_controls import (
            face_panel_action_label,
        )

        action_text = face_panel_action_label(is_open)
        self._face_panel_action_label.text = action_text
        self._face_panel_action_label.tooltip = action_text

    def _set_camera_controls(self, camera) -> None:
        self._updating_camera_controls = True
        try:
            if self._camera_position_x_model:
                self._camera_position_x_model.set_value(camera.position.x)
            if self._camera_position_y_model:
                self._camera_position_y_model.set_value(camera.position.y)
            if self._camera_position_z_model:
                self._camera_position_z_model.set_value(camera.position.z)
            if self._camera_rotation_x_model:
                self._camera_rotation_x_model.set_value(camera.rotation.x)
            if self._camera_rotation_y_model:
                self._camera_rotation_y_model.set_value(camera.rotation.y)
            if self._camera_rotation_z_model:
                self._camera_rotation_z_model.set_value(camera.rotation.z)
            self._camera_rotation_order = camera.rotation_order
        finally:
            self._updating_camera_controls = False

    def _install_camera_edit_callbacks(self) -> None:
        for model in (
            self._camera_position_x_model,
            self._camera_position_y_model,
            self._camera_position_z_model,
            self._camera_rotation_x_model,
            self._camera_rotation_y_model,
            self._camera_rotation_z_model,
        ):
            if hasattr(model, "add_value_changed_fn"):
                model.add_value_changed_fn(lambda _model: self._pause_camera_sync())

    def _pause_camera_sync(self) -> None:
        if self._updating_camera_controls:
            return
        self._suspend_camera_sync_until = time.monotonic() + 5.0

    def _build_lighting_config_from_controls(self):
        # isort: off
        from digital_twin_runtime_suite.app.config import (
            LightingConfig,
            RotationConfig,
        )

        # isort: on

        review_key_intensity = float(self._review_key_intensity_model.as_float)
        return LightingConfig(
            hdri_path=self._hdri_model.as_string.strip(),
            exposure=float(self._exposure_model.as_float),
            intensity=float(self._intensity_model.as_float),
            show_hdri_background=bool(self._show_hdri_background_model.as_bool),
            review_key_light_enabled=bool(self._review_key_model.as_bool),
            review_key_light_intensity=review_key_intensity,
            rotation=RotationConfig(
                x=float(self._rotation_x_model.as_float),
                y=float(self._rotation_y_model.as_float),
                z=float(self._rotation_z_model.as_float),
            ),
        )

    def _build_grid_config_from_controls(self):
        from digital_twin_runtime_suite.app.config import GridConfig

        return GridConfig(
            enabled=bool(self._grid_enabled_model.as_bool),
            step=float(self._grid_step_model.as_float),
            width=float(self._grid_width_model.as_float),
        )
