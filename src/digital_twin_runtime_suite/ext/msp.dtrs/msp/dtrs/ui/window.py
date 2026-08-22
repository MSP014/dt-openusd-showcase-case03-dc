"""Window and tab construction for the DTRS Kit shell."""

from __future__ import annotations

import omni.ui as ui

PANEL_WIDTH = 340


class DtrsWindowUiMixin:
    """Own the Kit window, tabs, and static section composition."""

    def _build_window(self) -> None:
        config = self._controller.config
        display_version = config.display_version
        default_asset = config.default_asset.label
        lighting = config.lighting

        self._hdri_model = ui.SimpleStringModel(lighting.hdri_path)
        self._exposure_model = ui.SimpleFloatModel(lighting.exposure)
        self._intensity_model = ui.SimpleFloatModel(lighting.intensity)
        self._show_hdri_background_model = ui.SimpleBoolModel(
            lighting.show_hdri_background
        )
        self._review_key_model = ui.SimpleBoolModel(lighting.review_key_light_enabled)
        self._review_key_intensity_model = ui.SimpleFloatModel(
            lighting.review_key_light_intensity
        )
        self._rotation_x_model = ui.SimpleFloatModel(lighting.rotation.x)
        self._rotation_y_model = ui.SimpleFloatModel(lighting.rotation.y)
        self._rotation_z_model = ui.SimpleFloatModel(lighting.rotation.z)
        self._grid_enabled_model = ui.SimpleBoolModel(config.grid.enabled)
        self._show_flow_debug_overlays_model = ui.SimpleBoolModel(False)
        self._show_flow_debug_overlays_model.add_value_changed_fn(
            lambda _model: self._schedule_apply_flow_debug_overlays()
        )
        self._grid_step_model = ui.SimpleFloatModel(config.grid.step)
        self._grid_width_model = ui.SimpleFloatModel(config.grid.width)
        receipt_preferences = config.validation_receipts
        self._reuse_vti_receipts_model = ui.SimpleBoolModel(
            receipt_preferences.reuse_verified_vti_receipts
        )
        self._reuse_streamlines_receipts_model = ui.SimpleBoolModel(
            receipt_preferences.reuse_verified_streamlines_cache_receipts
        )
        self._reuse_vti_receipts_model.add_value_changed_fn(
            self._on_validation_receipt_reuse_changed
        )
        self._reuse_streamlines_receipts_model.add_value_changed_fn(
            self._on_validation_receipt_reuse_changed
        )
        self._camera_position_x_model = ui.SimpleFloatModel(0.0)
        self._camera_position_y_model = ui.SimpleFloatModel(0.0)
        self._camera_position_z_model = ui.SimpleFloatModel(0.0)
        self._camera_rotation_x_model = ui.SimpleFloatModel(0.0)
        self._camera_rotation_y_model = ui.SimpleFloatModel(0.0)
        self._camera_rotation_z_model = ui.SimpleFloatModel(0.0)
        self._chassis_visibility_models = {
            group.group_id: ui.SimpleBoolModel(group.default_visible)
            for group in config.chassis_presentation.visibility_groups
        }
        self._face_panel_open_model = ui.SimpleBoolModel(
            config.chassis_presentation.face_panel.default_open
        )
        self._face_panel_open_state = (
            config.chassis_presentation.face_panel.default_open
        )
        if config.camera:
            self._set_camera_controls(config.camera)
        self._install_camera_edit_callbacks()

        self._window = ui.Window(
            f"{config.app_name} {display_version}",
            width=PANEL_WIDTH,
            height=620,
        )
        with self._window.frame:
            with ui.VStack(spacing=6, content_clipping=True):
                ui.Label(
                    f"{config.app_name} {display_version}",
                    height=20,
                    elided_text=True,
                    tooltip=f"{config.app_name} {display_version}",
                )
                with ui.HStack(height=28, spacing=4):
                    self._telemetry_tab_button = ui.Button(
                        "Telemetry",
                        clicked_fn=lambda: self._select_sidebar_tab("Telemetry"),
                        width=ui.Fraction(1),
                        height=28,
                    )
                    self._view_tab_button = ui.Button(
                        "View",
                        clicked_fn=lambda: self._select_sidebar_tab("View"),
                        width=ui.Fraction(1),
                        height=28,
                    )
                    self._config_tab_button = ui.Button(
                        "Config",
                        clicked_fn=lambda: self._select_sidebar_tab("Config"),
                        width=ui.Fraction(1),
                        height=28,
                    )

                self._telemetry_frame = ui.Frame(visible=True)
                with self._telemetry_frame:
                    self._build_telemetry_tab()

                self._view_frame = ui.Frame(visible=False)
                with self._view_frame:
                    self._build_view_tab(config)

                self._config_frame = ui.Frame(visible=False)
                with self._config_frame:
                    self._build_config_tab(config, default_asset)

        self._select_sidebar_tab("View")

    def _build_config_tab(self, config, default_asset: str) -> None:
        with ui.ScrollingFrame(
            horizontal_scrollbar_policy=ui.ScrollBarPolicy.SCROLLBAR_ALWAYS_OFF,
            vertical_scrollbar_policy=ui.ScrollBarPolicy.SCROLLBAR_ALWAYS_ON,
        ):
            with ui.VStack(spacing=6, content_clipping=True):
                self._build_config_section(
                    "Asset",
                    lambda: self._build_asset_config_controls(default_asset),
                )
                self._build_config_section(
                    "Lighting",
                    lambda: self._build_lighting_config_controls(config),
                    collapsed=True,
                )
                self._build_config_section(
                    "Grid",
                    self._build_grid_config_controls,
                    collapsed=True,
                )
                self._build_config_section(
                    "Camera",
                    self._build_camera_config_controls,
                    collapsed=True,
                )
                self._build_config_section(
                    "Telemetry provider",
                    self._build_telemetry_config_section,
                )

    def _build_view_tab(self, config) -> None:
        with ui.ScrollingFrame(
            horizontal_scrollbar_policy=ui.ScrollBarPolicy.SCROLLBAR_ALWAYS_OFF,
            vertical_scrollbar_policy=ui.ScrollBarPolicy.SCROLLBAR_ALWAYS_ON,
        ):
            with ui.VStack(spacing=6, content_clipping=True):
                self._build_config_section(
                    "Server Appearance",
                    lambda: self._build_server_appearance_controls(
                        config.chassis_presentation
                    ),
                    collapsed=True,
                )
                self._build_config_section(
                    "Visualization",
                    self._build_visualization_controls,
                    collapsed=True,
                )
                self._build_config_section(
                    "Heatmaps",
                    self._build_heatmaps_controls,
                )
                self._build_config_section(
                    "Streamlines",
                    self._build_streamlines_profile_controls,
                    collapsed=True,
                )
                self._build_config_section(
                    "Development validation",
                    self._build_validation_receipt_controls,
                    collapsed=True,
                )
                self._build_config_section(
                    "Airflow cache",
                    self._build_airflow_cache_controls,
                    collapsed=True,
                )

    def _build_server_appearance_controls(self, presentation) -> None:
        with ui.VStack(spacing=6, content_clipping=True):
            self._build_config_section(
                "Server enclosure",
                lambda: self._build_server_view_controls(presentation),
            )
            self._build_config_section(
                "Materials",
                lambda: self._build_material_controls(presentation),
            )
