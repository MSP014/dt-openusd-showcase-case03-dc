"""Configuration-pane OmniUI builders and transient control models."""

from __future__ import annotations

import omni.ui as ui

ROW_LABEL_WIDTH = 104
SERVER_VIEW_LABEL_WIDTH = 150
COMPACT_TEXT_LENGTH = 44


def _compact_text(value: str, max_length: int = COMPACT_TEXT_LENGTH) -> str:
    text = str(value)
    if len(text) <= max_length:
        return text
    return f"{text[: max_length - 3]}..."


class ConfigurationUiMixin:
    """Own Config and cache-control construction without runtime sequencing."""

    def _build_config_section(self, title, build_fn, collapsed: bool = False) -> None:
        with ui.CollapsableFrame(
            title,
            collapsed=collapsed,
            height=0,
            build_header_fn=self._build_telemetry_group_header,
            style={
                "CollapsableFrame": {
                    "background_color": 0xFF3A3A3A,
                    "secondary_color": 0xFF464646,
                    "border_color": 0xFF5A5A5A,
                    "border_width": 1,
                    "border_radius": 2,
                }
            },
        ):
            with ui.VStack(spacing=6, height=0, content_clipping=True):
                ui.Spacer(height=2)
                build_fn()
                ui.Spacer(height=2)

    def _build_asset_config_controls(self, default_asset: str) -> None:
        ui.Label("Loaded asset", height=18)
        self._asset_label = ui.Label(
            _compact_text(default_asset),
            height=18,
            elided_text=True,
            tooltip=default_asset,
        )
        ui.Button(
            "Load",
            clicked_fn=self._schedule_load,
            height=26,
            width=ui.Percent(100),
        )
        ui.Button(
            "Reload Config",
            clicked_fn=self._reload_config,
            height=26,
            width=ui.Percent(100),
        )
        self._status_label = ui.Label("Ready", height=34, elided_text=True)

    def _build_smoke_tuning_row(
        self,
        label: str,
        field_name: str,
        value: float,
    ) -> None:
        from digital_twin_runtime_suite.app.config import (
            SMOKE_TUNING_VALUE_OPTIONS,
        )
        from digital_twin_runtime_suite.app.view_controls import (
            smoke_tuning_option_index,
        )

        choices = SMOKE_TUNING_VALUE_OPTIONS[field_name]
        with ui.HStack(height=24, spacing=6, content_clipping=True):
            ui.Label(label, width=SERVER_VIEW_LABEL_WIDTH)
            self._smoke_tuning_combos[field_name] = ui.ComboBox(
                smoke_tuning_option_index(field_name, value),
                *(f"{choice:g}" for choice in choices),
                width=ui.Fraction(1),
            )

    def _build_smoke_color_controls(
        self,
        base_color: tuple[float, float, float],
    ) -> None:
        from digital_twin_runtime_suite.app.view_controls import (
            rgb_to_hex,
            rgb_to_hsv,
        )

        hue, saturation, value = rgb_to_hsv(base_color)
        self._updating_smoke_color_controls = False
        self._smoke_color_input_source = "hex"
        self._smoke_color_hex_model = ui.SimpleStringModel(rgb_to_hex(base_color))
        self._smoke_color_hue_model = ui.SimpleFloatModel(hue)
        self._smoke_color_saturation_model = ui.SimpleFloatModel(saturation)
        self._smoke_color_value_model = ui.SimpleFloatModel(value)
        with ui.HStack(height=24, spacing=6, content_clipping=True):
            ui.Label("Color", width=SERVER_VIEW_LABEL_WIDTH)
            ui.StringField(
                model=self._smoke_color_hex_model,
                width=ui.Fraction(1),
            )
            self._smoke_color_preview_frame = ui.Frame(width=32, height=20)
        with ui.HStack(height=24, spacing=6, content_clipping=True):
            ui.Label("HSV", width=SERVER_VIEW_LABEL_WIDTH)
            ui.Label("H", width=12)
            ui.FloatField(model=self._smoke_color_hue_model, width=ui.Fraction(1))
            ui.Label("S", width=12)
            ui.FloatField(
                model=self._smoke_color_saturation_model,
                width=ui.Fraction(1),
            )
            ui.Label("V", width=12)
            ui.FloatField(model=self._smoke_color_value_model, width=ui.Fraction(1))
        self._smoke_color_hex_model.add_value_changed_fn(
            self._on_smoke_color_hex_changed
        )
        for model in (
            self._smoke_color_hue_model,
            self._smoke_color_saturation_model,
            self._smoke_color_value_model,
        ):
            model.add_value_changed_fn(self._on_smoke_color_hsv_changed)
        self._set_pending_smoke_color(base_color)

    def _set_pending_smoke_color(
        self,
        base_color: tuple[float, float, float],
    ) -> None:
        from digital_twin_runtime_suite.app.view_controls import (
            rgb_to_hex,
            rgb_to_hsv,
        )

        self._updating_smoke_color_controls = True
        try:
            hue, saturation, value = rgb_to_hsv(base_color)
            self._smoke_color_hex_model.set_value(rgb_to_hex(base_color))
            self._smoke_color_hue_model.set_value(hue)
            self._smoke_color_saturation_model.set_value(saturation)
            self._smoke_color_value_model.set_value(value)
        finally:
            self._updating_smoke_color_controls = False
        self._refresh_smoke_color_preview(base_color)

    def _refresh_smoke_color_preview(
        self,
        base_color: tuple[float, float, float],
    ) -> None:
        from digital_twin_runtime_suite.app.view_controls import (
            rgb_to_omniui_color,
        )

        with self._smoke_color_preview_frame:
            ui.Rectangle(
                style={"background_color": rgb_to_omniui_color(base_color)},
                width=ui.Percent(100),
                height=ui.Percent(100),
            )

    def _on_smoke_color_hex_changed(self, _model) -> None:
        if self._updating_smoke_color_controls:
            return
        from digital_twin_runtime_suite.app.view_controls import (
            hex_to_rgb,
            string_model_value,
        )

        self._smoke_color_input_source = "hex"
        try:
            color = hex_to_rgb(string_model_value(self._smoke_color_hex_model))
        except ValueError:
            return
        self._set_pending_smoke_color(color)

    def _on_smoke_color_hsv_changed(self, _model) -> None:
        if self._updating_smoke_color_controls:
            return
        from digital_twin_runtime_suite.app.view_controls import (
            build_smoke_base_color_from_models,
        )

        self._smoke_color_input_source = "hsv"
        try:
            color = build_smoke_base_color_from_models(
                source="hsv",
                hex_model=self._smoke_color_hex_model,
                hue_model=self._smoke_color_hue_model,
                saturation_model=self._smoke_color_saturation_model,
                value_model=self._smoke_color_value_model,
            )
        except ValueError:
            return
        self._set_pending_smoke_color(color)

    def _build_emitter_layout_row(
        self,
        label: str,
        field_name: str,
        value: float | int,
    ) -> None:
        from digital_twin_runtime_suite.app.config import (
            EMITTER_LAYOUT_VALUE_OPTIONS,
        )
        from digital_twin_runtime_suite.app.view_controls import (
            emitter_layout_option_index,
        )

        choices = EMITTER_LAYOUT_VALUE_OPTIONS[field_name]
        labels = (
            (
                ("Minimum" if choice == 0 else f"{choice:.0%}")
                if field_name == "size"
                else (
                    f"{choice:.0%}"
                    if field_name in {"depth", "horizontal_margin", "vertical_margin"}
                    else f"{choice:g}"
                )
            )
            for choice in choices
        )
        with ui.HStack(height=24, spacing=6, content_clipping=True):
            ui.Label(label, width=SERVER_VIEW_LABEL_WIDTH)
            self._emitter_layout_combos[field_name] = ui.ComboBox(
                emitter_layout_option_index(field_name, value),
                *labels,
                width=ui.Fraction(1),
            )

    def _build_airflow_cache_controls(self) -> None:
        cache = self._controller.config.simulation_cache
        wrapper_name = self._airflow_cache_selector_text()
        self._airflow_cache_selector_label = ui.Label(
            _compact_text(wrapper_name),
            height=18,
            elided_text=True,
            tooltip=wrapper_name,
        )
        with ui.HStack(height=26, spacing=6, content_clipping=True):
            ui.Button(
                "Attach",
                clicked_fn=self._schedule_attach_airflow,
                width=ui.Fraction(1),
            )
            ui.Button(
                "Detach",
                clicked_fn=self._schedule_detach_airflow,
                width=ui.Fraction(1),
            )
        with ui.HStack(height=26, spacing=6, content_clipping=True):
            ui.Button(
                "Play",
                clicked_fn=self._play_airflow,
                width=ui.Fraction(1),
            )
            ui.Button(
                "Pause",
                clicked_fn=self._pause_airflow,
                width=ui.Fraction(1),
            )
            ui.Button(
                "Reset",
                clicked_fn=self._reset_airflow,
                width=ui.Fraction(1),
            )
        with ui.HStack(height=24, spacing=6, content_clipping=True):
            ui.Button(
                "Set Overview",
                clicked_fn=lambda: self._capture_flow_camera_bookmark("Overview"),
                width=ui.Fraction(1),
            )
            ui.Button(
                "Set Close-up",
                clicked_fn=lambda: self._capture_flow_camera_bookmark("Close-up"),
                width=ui.Fraction(1),
            )

        with ui.HStack(height=24, spacing=6, content_clipping=True):
            ui.Button(
                "Overview",
                clicked_fn=lambda: self._schedule_apply_flow_camera_bookmark(
                    "Overview"
                ),
                width=ui.Fraction(1),
            )
            ui.Button(
                "Close-up",
                clicked_fn=lambda: self._schedule_apply_flow_camera_bookmark(
                    "Close-up"
                ),
                width=ui.Fraction(1),
            )
        with ui.HStack(height=24, spacing=6, content_clipping=True):
            ui.Label("Show debug overlays", width=SERVER_VIEW_LABEL_WIDTH)
            ui.CheckBox(model=self._show_flow_debug_overlays_model)
        self._smoke_tuning_combos = {}
        smoke_tuning = cache.smoke_tuning
        ui.Label("Smoke Tuning", height=22)
        ui.Label("Appearance", height=18)
        self._build_smoke_tuning_row("Density", "density", smoke_tuning.density)
        self._build_smoke_tuning_row(
            "Brightness",
            "brightness",
            smoke_tuning.brightness,
        )
        self._build_smoke_tuning_row("Ambient", "ambient", smoke_tuning.ambient)
        self._build_smoke_tuning_row(
            "Shadow density",
            "shadow_density",
            smoke_tuning.shadow_density,
        )
        self._build_smoke_color_controls(smoke_tuning.base_color)
        ui.Label("Dynamics", height=18)
        self._build_smoke_tuning_row("Damping", "damping", smoke_tuning.damping)
        self._build_smoke_tuning_row("Fade", "fade", smoke_tuning.fade)
        self._build_smoke_tuning_row("Sharpness", "sharpness", smoke_tuning.sharpness)
        self._build_smoke_tuning_row(
            "Vorticity",
            "vorticity",
            smoke_tuning.vorticity,
        )
        self._build_smoke_tuning_row(
            "Velocity scale ×",
            "velocity_scale_multiplier",
            smoke_tuning.velocity_scale_multiplier,
        )
        self._build_smoke_tuning_row(
            "Time scale",
            "time_scale",
            smoke_tuning.time_scale,
        )
        ui.Label("Quality", height=18)
        self._build_smoke_tuning_row(
            "Raymarch quality",
            "raymarch_quality",
            smoke_tuning.raymarch_quality,
        )
        from digital_twin_runtime_suite.app.flow.quality import (
            KIT_CAE_FLOW_VOXEL_RESOLUTION_OPTIONS,
        )

        with ui.HStack(height=24, spacing=6, content_clipping=True):
            ui.Label("Flow voxel resolution", width=SERVER_VIEW_LABEL_WIDTH)
            self._flow_voxel_resolution_combo = ui.ComboBox(
                0,
                *(str(value) for value in KIT_CAE_FLOW_VOXEL_RESOLUTION_OPTIONS),
                width=ui.Fraction(1),
            )
        ui.Button(
            "Apply Smoke Settings",
            clicked_fn=self._schedule_apply_smoke_tuning,
            height=26,
            width=ui.Percent(100),
        )
        ui.Button(
            "Apply & Restart Flow",
            clicked_fn=self._schedule_apply_flow_voxel_resolution,
            height=26,
            width=ui.Percent(100),
        )
        self._emitter_layout_combos = {}
        emitter_layout = cache.emitter_layout
        ui.Label("Emitter Layout", height=22)
        self._build_emitter_layout_row(
            "Emitters per row",
            "emitters_per_row",
            emitter_layout.emitters_per_row,
        )
        self._build_emitter_layout_row(
            "Emitter rows",
            "rows",
            emitter_layout.rows,
        )
        self._build_emitter_layout_row(
            "Depth position",
            "depth",
            emitter_layout.depth,
        )
        self._build_emitter_layout_row(
            "Emitter size",
            "size",
            emitter_layout.size,
        )
        self._build_emitter_layout_row(
            "Horizontal margin",
            "horizontal_margin",
            emitter_layout.horizontal_margin,
        )
        self._build_emitter_layout_row(
            "Vertical margin",
            "vertical_margin",
            emitter_layout.vertical_margin,
        )
        ui.Button(
            "Apply Emitter Layout",
            clicked_fn=self._schedule_apply_emitter_layout,
            height=26,
            width=ui.Percent(100),
        )

    def _build_lighting_config_controls(self, config) -> None:
        self._lighting_status_label = ui.Label(
            _compact_text(f"HDRI: {config.default_hdri_path.name}"),
            height=34,
            elided_text=True,
            tooltip=f"HDRI: {config.default_hdri_path.name}",
        )
        ui.Label("HDRI file", height=18)
        ui.StringField(
            model=self._hdri_model,
            height=24,
            width=ui.Percent(100),
        )
        self._build_float_row("Exposure", self._exposure_model)
        self._build_float_row("HDRI intensity", self._intensity_model)
        with ui.HStack(height=24, spacing=6, content_clipping=True):
            ui.Label("Show HDRI", width=ROW_LABEL_WIDTH)
            ui.CheckBox(model=self._show_hdri_background_model)
        with ui.HStack(height=24, spacing=6, content_clipping=True):
            ui.Label("Key", width=ROW_LABEL_WIDTH)
            ui.CheckBox(model=self._review_key_model)
        self._build_float_row("Key intensity", self._review_key_intensity_model)
        ui.Label("Dome rotation", height=18)
        self._build_float_row("Rotate X", self._rotation_x_model)
        self._build_float_row("Rotate Y", self._rotation_y_model)
        self._build_float_row("Rotate Z", self._rotation_z_model)
        ui.Button(
            "Apply",
            clicked_fn=self._schedule_apply_lighting,
            height=26,
            width=ui.Percent(100),
        )
        ui.Button(
            "Use Default",
            clicked_fn=self._reset_lighting_controls,
            height=26,
            width=ui.Percent(100),
        )
        ui.Button(
            "Save Settings",
            clicked_fn=self._save_current_runtime_override,
            height=26,
            width=ui.Percent(100),
        )

    def _build_grid_config_controls(self) -> None:
        with ui.HStack(height=24, spacing=6, content_clipping=True):
            ui.Label("Show grid", width=ROW_LABEL_WIDTH)
            ui.CheckBox(model=self._grid_enabled_model)
        self._build_float_row("Grid step", self._grid_step_model, precision=3)
        self._build_float_row("Line width", self._grid_width_model, precision=5)
        ui.Button(
            "Apply Grid",
            clicked_fn=self._schedule_apply_grid,
            height=26,
            width=ui.Percent(100),
        )

    def _build_camera_config_controls(self) -> None:
        ui.Label("Position", height=18)
        self._build_float_row("Camera X", self._camera_position_x_model)
        self._build_float_row("Camera Y", self._camera_position_y_model)
        self._build_float_row("Camera Z", self._camera_position_z_model)
        ui.Label("Rotation", height=18)
        self._build_float_row("Camera RX", self._camera_rotation_x_model)
        self._build_float_row("Camera RY", self._camera_rotation_y_model)
        self._build_float_row("Camera RZ", self._camera_rotation_z_model)
        ui.Button(
            "Apply Camera",
            clicked_fn=self._schedule_apply_camera,
            height=26,
            width=ui.Percent(100),
        )
        ui.Button(
            "Save Camera Pos",
            clicked_fn=self._save_camera_position,
            height=26,
            width=ui.Percent(100),
        )
        ui.Button(
            "Reset Camera",
            clicked_fn=self._schedule_reset_camera,
            height=26,
            width=ui.Percent(100),
        )
