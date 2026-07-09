"""Blackwell Monitoring Suite Kit extension."""

from __future__ import annotations

import asyncio
import sys
import time
from dataclasses import replace
from pathlib import Path

import carb.settings
import carb.tokens
import omni.ext
import omni.ui as ui

EXTENSION_SETTINGS = "/exts/msp.bw.monitoring"
PANEL_WIDTH = 340
ROW_LABEL_WIDTH = 104
TELEMETRY_VALUE_RIGHT_PADDING = 8
COMPACT_TEXT_LENGTH = 44


def _compact_text(value: str, max_length: int = COMPACT_TEXT_LENGTH) -> str:
    text = str(value)
    if len(text) <= max_length:
        return text
    return f"{text[: max_length - 3]}..."


def _resolve_token_path(value: str) -> Path:
    tokens = carb.tokens.get_tokens_interface()
    return Path(tokens.resolve(value)).resolve()


def _fallback_source_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if parent.name == "blackwell_monitoring_suite":
            return parent
    raise RuntimeError("Unable to locate Blackwell Monitoring Suite source root.")


def _ensure_source_root(source_root: Path) -> None:
    src_root = source_root.parent
    src_root_text = str(src_root)
    if src_root_text not in sys.path:
        sys.path.insert(0, src_root_text)


class BlackwellMonitoringExtension(omni.ext.IExt):
    """Runtime controls for the current Blackwell Monitoring Suite slice."""

    def on_startup(self, ext_id: str) -> None:
        self._ext_id = ext_id
        self._window = None
        self._controller = None
        self._status_label = None
        self._lighting_status_label = None
        self._asset_label = None
        self._load_task = None
        self._lighting_task = None
        self._camera_sync_task = None
        self._telemetry_task = None
        self._motion_controller = None
        self._suspend_camera_sync_until = 0.0
        self._updating_camera_controls = False
        self._telemetry_provider = None
        self._telemetry_latch = None
        self._telemetry_frame = None
        self._config_frame = None
        self._telemetry_tab_button = None
        self._config_tab_button = None
        self._workload_combo = None
        self._refresh_combo = None
        self._freeze_button = None
        self._telemetry_timestamp_label = None
        self._telemetry_state_label = None
        self._telemetry_metric_labels = {}
        self._workload_modes = ()
        self._refresh_intervals = ()
        self._telemetry_config_path = None
        self._telemetry_config_status_label = None
        self._telemetry_config_status_clear_at = 0.0
        self._provider_default_mode_combo = None
        self._provider_default_refresh_combo = None
        self._provider_tuning_mode_combo = None
        self._provider_metric_combo = None
        self._provider_tick_model = None
        self._provider_interpolation_model = None
        self._provider_target_model = None
        self._provider_jitter_model = None
        self._provider_minimum_model = None
        self._provider_maximum_model = None
        self._provider_numeric_metrics = ()
        self._provider_component_tuning_groups = {}
        self._next_telemetry_ui_update = 0.0
        self._hdri_model = None
        self._exposure_model = None
        self._intensity_model = None
        self._show_hdri_background_model = None
        self._review_key_model = None
        self._review_key_intensity_model = None
        self._rotation_x_model = None
        self._rotation_y_model = None
        self._rotation_z_model = None
        self._grid_enabled_model = None
        self._grid_step_model = None
        self._grid_width_model = None
        self._camera_position_x_model = None
        self._camera_position_y_model = None
        self._camera_position_z_model = None
        self._camera_rotation_x_model = None
        self._camera_rotation_y_model = None
        self._camera_rotation_z_model = None
        self._camera_rotation_order = "YXZ"

        self._settings = carb.settings.get_settings()
        self._build_controller()
        self._build_window()
        asyncio.ensure_future(self._dock_left())
        self._camera_sync_task = asyncio.ensure_future(self._sync_camera_panel())
        self._telemetry_task = asyncio.ensure_future(self._run_telemetry())

        if self._settings.get_as_bool(f"{EXTENSION_SETTINGS}/autoLoad"):
            self._schedule_load()

    def on_shutdown(self) -> None:
        for task_name in ("_load_task", "_lighting_task"):
            task = getattr(self, task_name, None)
            if task:
                task.cancel()
            setattr(self, task_name, None)
        if self._camera_sync_task:
            self._camera_sync_task.cancel()
            self._camera_sync_task = None
        if self._telemetry_task:
            self._telemetry_task.cancel()
            self._telemetry_task = None
        if self._motion_controller:
            self._motion_controller.reset()
            self._motion_controller = None
        self._telemetry_provider = None
        self._telemetry_latch = None
        self._controller = None
        if self._window:
            self._window.visible = False
            self._window = None

    def _build_controller(self) -> None:
        source_root_setting = self._settings.get_as_string(
            f"{EXTENSION_SETTINGS}/sourceRoot"
        )
        if source_root_setting:
            source_root = _resolve_token_path(source_root_setting)
        else:
            source_root = _fallback_source_root()

        _ensure_source_root(source_root)

        config_path_setting = self._settings.get_as_string(
            f"{EXTENSION_SETTINGS}/configPath"
        )
        if config_path_setting:
            config_path = _resolve_token_path(config_path_setting)
        else:
            config_path = (
                source_root.parent.parent
                / "configs"
                / "blackwell_monitoring_suite.v0.2.toml"
            ).resolve()

        # isort: off
        from blackwell_monitoring_suite.app.commands import RuntimeController
        from blackwell_monitoring_suite.app.motion import RotationMotionController
        from blackwell_monitoring_suite.app.telemetry import SnapshotLatch
        from blackwell_monitoring_suite.app.telemetry import SyntheticTelemetryProvider
        from blackwell_monitoring_suite.app.telemetry import TelemetryConfig

        # isort: on

        self._controller = RuntimeController(config_path)
        telemetry_config_path = (
            source_root / "configs" / "telemetry_provider.toml"
        ).resolve()
        self._telemetry_config_path = telemetry_config_path
        telemetry_config = TelemetryConfig.load(telemetry_config_path)
        self._telemetry_provider = SyntheticTelemetryProvider(telemetry_config)
        self._telemetry_latch = SnapshotLatch()
        self._motion_controller = RotationMotionController()
        self._workload_modes = tuple(telemetry_config.modes)
        self._refresh_intervals = telemetry_config.allowed_refresh_intervals_s

    def _build_window(self) -> None:
        config = self._controller.config
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
        self._grid_step_model = ui.SimpleFloatModel(config.grid.step)
        self._grid_width_model = ui.SimpleFloatModel(config.grid.width)
        self._camera_position_x_model = ui.SimpleFloatModel(0.0)
        self._camera_position_y_model = ui.SimpleFloatModel(0.0)
        self._camera_position_z_model = ui.SimpleFloatModel(0.0)
        self._camera_rotation_x_model = ui.SimpleFloatModel(0.0)
        self._camera_rotation_y_model = ui.SimpleFloatModel(0.0)
        self._camera_rotation_z_model = ui.SimpleFloatModel(0.0)
        if config.camera:
            self._set_camera_controls(config.camera)
        self._install_camera_edit_callbacks()

        self._window = ui.Window(
            "Blackwell Monitoring Suite",
            width=PANEL_WIDTH,
            height=620,
        )
        with self._window.frame:
            with ui.VStack(spacing=6, content_clipping=True):
                ui.Label(
                    f"{config.app_name} v{config.app_version}",
                    height=20,
                    elided_text=True,
                    tooltip=f"{config.app_name} v{config.app_version}",
                )
                with ui.HStack(height=28, spacing=4):
                    self._telemetry_tab_button = ui.Button(
                        "Telemetry",
                        clicked_fn=lambda: self._select_sidebar_tab("Telemetry"),
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

                self._config_frame = ui.Frame(visible=False)
                with self._config_frame:
                    self._build_config_tab(config, default_asset)

        self._select_sidebar_tab("Telemetry")

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

    def _build_telemetry_config_section(self) -> None:
        # isort: off
        from blackwell_monitoring_suite.app.telemetry.config import (
            COMPONENT_TUNING_GROUPS,
            TUNING_METRIC_LABELS,
            TUNING_METRICS,
        )
        from blackwell_monitoring_suite.app.telemetry.model import METRIC_LABELS

        # isort: on

        config = self._telemetry_provider.config
        self._provider_numeric_metrics = tuple(sorted(TUNING_METRICS))
        self._provider_component_tuning_groups = COMPONENT_TUNING_GROUPS
        default_mode_index = self._workload_modes.index(config.default_mode)
        default_refresh_index = self._refresh_intervals.index(
            config.default_refresh_interval_s
        )
        self._provider_tick_model = ui.SimpleFloatModel(config.provider_tick_seconds)
        self._provider_interpolation_model = ui.SimpleFloatModel(
            config.interpolation_factor
        )
        self._provider_target_model = ui.SimpleFloatModel(0.0)
        self._provider_jitter_model = ui.SimpleFloatModel(0.0)
        self._provider_minimum_model = ui.SimpleFloatModel(0.0)
        self._provider_maximum_model = ui.SimpleFloatModel(0.0)

        with ui.HStack(height=24, spacing=6):
            ui.Label("Default mode", width=ROW_LABEL_WIDTH)
            self._provider_default_mode_combo = ui.ComboBox(
                default_mode_index,
                *self._workload_modes,
                width=ui.Fraction(1),
            )
        with ui.HStack(height=24, spacing=6):
            ui.Label("Default refresh", width=ROW_LABEL_WIDTH)
            refresh_labels = tuple(f"{value} s" for value in self._refresh_intervals)
            self._provider_default_refresh_combo = ui.ComboBox(
                default_refresh_index,
                *refresh_labels,
                width=ui.Fraction(1),
            )
        self._build_float_row("Provider tick", self._provider_tick_model)
        self._build_float_row(
            "Interpolation",
            self._provider_interpolation_model,
            precision=3,
        )

        ui.Label("Mode tuning", height=18)
        with ui.HStack(height=24, spacing=6):
            ui.Label("Mode", width=ROW_LABEL_WIDTH)
            self._provider_tuning_mode_combo = ui.ComboBox(
                default_mode_index,
                *self._workload_modes,
                width=ui.Fraction(1),
            )
        with ui.HStack(height=24, spacing=6):
            ui.Label("Metric", width=ROW_LABEL_WIDTH)
            metric_labels = tuple(
                (
                    TUNING_METRIC_LABELS[metric_id]
                    if metric_id in TUNING_METRIC_LABELS
                    else METRIC_LABELS[metric_id]
                )
                for metric_id in self._provider_numeric_metrics
            )
            self._provider_metric_combo = ui.ComboBox(
                0,
                *metric_labels,
                width=ui.Fraction(1),
            )
        self._build_float_row("Target", self._provider_target_model)
        self._build_float_row("Jitter", self._provider_jitter_model)
        self._build_float_row("Minimum", self._provider_minimum_model)
        self._build_float_row("Maximum", self._provider_maximum_model)
        ui.Button(
            "Save Telemetry Config",
            clicked_fn=self._save_telemetry_config,
            height=26,
            width=ui.Percent(100),
        )
        self._telemetry_config_status_label = ui.Label(
            "Packaged config with local override",
            height=34,
            elided_text=True,
        )

        for combo in (
            self._provider_tuning_mode_combo,
            self._provider_metric_combo,
        ):
            model = self._combo_index_model(combo)
            if model:
                model.add_value_changed_fn(
                    lambda _model: self._load_selected_metric_controls()
                )
        self._load_selected_metric_controls()

    def _selected_provider_mode_and_metric(self) -> tuple[str, str]:
        mode_index = self._model_int(
            self._combo_index_model(self._provider_tuning_mode_combo)
        )
        metric_index = self._model_int(
            self._combo_index_model(self._provider_metric_combo)
        )
        return (
            self._workload_modes[mode_index],
            self._provider_numeric_metrics[metric_index],
        )

    def _load_selected_metric_controls(self) -> None:
        if not self._telemetry_provider:
            return
        mode_name, metric_id = self._selected_provider_mode_and_metric()
        metric_ids = self._provider_component_tuning_groups.get(
            metric_id,
            (metric_id,),
        )
        source_metric_id = metric_ids[len(metric_ids) // 2]
        metric = self._telemetry_provider.config.modes[mode_name].numeric[
            source_metric_id
        ]
        self._provider_target_model.set_value(metric.target)
        self._provider_jitter_model.set_value(metric.jitter)
        self._provider_minimum_model.set_value(metric.minimum)
        self._provider_maximum_model.set_value(metric.maximum)

    def _save_telemetry_config(self) -> None:
        if not self._telemetry_provider or not self._telemetry_config_path:
            return

        try:
            # isort: off
            from blackwell_monitoring_suite.app.telemetry import (
                SyntheticTelemetryProvider,
                TelemetryConfig,
            )
            from blackwell_monitoring_suite.app.telemetry.config import (
                NumericMetricConfig,
            )

            # isort: on

            config = self._telemetry_provider.config
            mode_name, metric_id = self._selected_provider_mode_and_metric()
            default_mode_index = self._model_int(
                self._combo_index_model(self._provider_default_mode_combo)
            )
            default_refresh_index = self._model_int(
                self._combo_index_model(self._provider_default_refresh_combo)
            )
            tick_seconds = float(self._provider_tick_model.as_float)
            interpolation = float(self._provider_interpolation_model.as_float)
            target = float(self._provider_target_model.as_float)
            jitter = float(self._provider_jitter_model.as_float)
            minimum = float(self._provider_minimum_model.as_float)
            maximum = float(self._provider_maximum_model.as_float)

            if tick_seconds <= 0:
                raise ValueError("Provider tick must be greater than zero.")
            if not 0 < interpolation <= 1:
                raise ValueError("Interpolation must be in the range (0, 1].")
            if minimum > maximum:
                raise ValueError("Minimum must not exceed maximum.")
            if not minimum <= target <= maximum:
                raise ValueError("Target must remain inside the safe range.")
            if jitter < 0:
                raise ValueError("Jitter must not be negative.")

            current_mode = config.modes[mode_name]
            numeric = dict(current_mode.numeric)
            metric_ids = self._provider_component_tuning_groups.get(
                metric_id,
                (metric_id,),
            )
            for resolved_metric_id in metric_ids:
                numeric[resolved_metric_id] = NumericMetricConfig(
                    target=target,
                    jitter=jitter,
                    minimum=minimum,
                    maximum=maximum,
                )
            modes = dict(config.modes)
            modes[mode_name] = replace(current_mode, numeric=numeric)
            updated = replace(
                config,
                default_mode=self._workload_modes[default_mode_index],
                provider_tick_seconds=tick_seconds,
                default_refresh_interval_s=self._refresh_intervals[
                    default_refresh_index
                ],
                interpolation_factor=interpolation,
                modes=modes,
            )
            updated.save_local_override()
            reloaded = TelemetryConfig.load(self._telemetry_config_path)

            runtime_mode = self._telemetry_provider.mode
            runtime_refresh = (
                self._telemetry_provider.latest_snapshot.refresh_interval_s
            )
            self._telemetry_provider = SyntheticTelemetryProvider(reloaded)
            self._telemetry_provider.set_mode(runtime_mode)
            if runtime_refresh in reloaded.allowed_refresh_intervals_s:
                self._telemetry_provider.set_refresh_interval(runtime_refresh)
            self._next_telemetry_ui_update = 0.0
            self._set_telemetry_config_status("Telemetry config saved and applied.")
        except Exception as exc:  # noqa: BLE001
            self._provider_tick_model.set_value(
                self._telemetry_provider.config.provider_tick_seconds
            )
            self._provider_interpolation_model.set_value(
                self._telemetry_provider.config.interpolation_factor
            )
            self._load_selected_metric_controls()
            self._set_telemetry_config_status(
                f"Telemetry config error: {exc}",
                clear_after_s=8.0,
            )

    def _set_telemetry_config_status(
        self,
        message: str,
        clear_after_s: float | None = None,
    ) -> None:
        if self._telemetry_config_status_label:
            self._telemetry_config_status_label.text = _compact_text(message)
            self._telemetry_config_status_label.tooltip = message
            self._telemetry_config_status_clear_at = (
                time.monotonic() + clear_after_s if clear_after_s else 0.0
            )

    def _build_telemetry_tab(self) -> None:
        # isort: off
        from blackwell_monitoring_suite.app.telemetry.model import METRIC_LABELS
        from blackwell_monitoring_suite.app.telemetry.model import TELEMETRY_GROUPS

        # isort: on

        snapshot = self._telemetry_provider.latest_snapshot
        mode_index = self._workload_modes.index(snapshot.operational_state)
        refresh_index = self._refresh_intervals.index(snapshot.refresh_interval_s)

        with ui.ScrollingFrame(
            horizontal_scrollbar_policy=ui.ScrollBarPolicy.SCROLLBAR_ALWAYS_OFF,
            vertical_scrollbar_policy=ui.ScrollBarPolicy.SCROLLBAR_ALWAYS_ON,
        ):
            with ui.VStack(spacing=6, content_clipping=True):
                ui.Label("Node telemetry", height=20)
                with ui.HStack(height=24, spacing=6):
                    ui.Label("Workload", width=ROW_LABEL_WIDTH)
                    self._workload_combo = ui.ComboBox(
                        mode_index,
                        *self._workload_modes,
                        width=ui.Fraction(1),
                    )
                with ui.HStack(height=24, spacing=6):
                    ui.Label("Refresh", width=ROW_LABEL_WIDTH)
                    refresh_labels = tuple(
                        f"{value} s" for value in self._refresh_intervals
                    )
                    self._refresh_combo = ui.ComboBox(
                        refresh_index,
                        *refresh_labels,
                        width=ui.Fraction(1),
                    )
                self._freeze_button = ui.Button(
                    "Freeze",
                    clicked_fn=self._toggle_telemetry_freeze,
                    height=26,
                    width=ui.Percent(100),
                )
                self._telemetry_timestamp_label = ui.Label(
                    "Last update",
                    height=20,
                    elided_text=True,
                )
                self._telemetry_state_label = ui.Label(
                    snapshot.operational_state,
                    height=22,
                )

                for group_name, metric_ids in TELEMETRY_GROUPS.items():
                    ui.Spacer(height=3)
                    collapsed = group_name.startswith(("GPU 1 ", "GPU 2 ", "GPU 3 "))
                    with ui.CollapsableFrame(
                        group_name,
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
                        with ui.VStack(spacing=2, height=0):
                            ui.Spacer(height=2)
                            for metric_id in metric_ids:
                                with ui.HStack(
                                    height=22,
                                    spacing=6,
                                    content_clipping=True,
                                ):
                                    ui.Label(
                                        METRIC_LABELS[metric_id],
                                        width=ui.Fraction(1),
                                        elided_text=True,
                                    )
                                    value_label = ui.Label(
                                        "",
                                        width=112,
                                        alignment=ui.Alignment.RIGHT_CENTER,
                                    )
                                    ui.Spacer(width=TELEMETRY_VALUE_RIGHT_PADDING)
                                    self._telemetry_metric_labels.setdefault(
                                        metric_id,
                                        [],
                                    ).append(value_label)
                            ui.Spacer(height=2)

        self._install_telemetry_callbacks()
        self._update_telemetry_labels(snapshot)

    @staticmethod
    def _build_telemetry_group_header(collapsed: bool, title: str) -> None:
        with ui.ZStack(height=26):
            ui.Rectangle(style={"background_color": 0xFF383838})
            with ui.HStack(height=26, spacing=4):
                ui.Label(
                    ">" if collapsed else "v",
                    width=16,
                    alignment=ui.Alignment.CENTER,
                    style={
                        "color": 0xFFB8B8B8,
                        "font": "${fonts}/OpenSans-SemiBold.ttf",
                    },
                )
                ui.Label(
                    title,
                    alignment=ui.Alignment.LEFT_CENTER,
                    elided_text=True,
                    tooltip=title,
                    style={
                        "color": 0xFFE6E6E6,
                        "font": "${fonts}/OpenSans-SemiBold.ttf",
                        "font_size": 14,
                    },
                )

    def _select_sidebar_tab(self, tab_name: str) -> None:
        telemetry_selected = tab_name == "Telemetry"
        if self._telemetry_frame:
            self._telemetry_frame.visible = telemetry_selected
        if self._config_frame:
            self._config_frame.visible = not telemetry_selected
        if self._telemetry_tab_button:
            self._telemetry_tab_button.checked = telemetry_selected
        if self._config_tab_button:
            self._config_tab_button.checked = not telemetry_selected

    def _install_telemetry_callbacks(self) -> None:
        workload_model = self._combo_index_model(self._workload_combo)
        refresh_model = self._combo_index_model(self._refresh_combo)
        if workload_model:
            workload_model.add_value_changed_fn(self._on_workload_mode_changed)
        if refresh_model:
            refresh_model.add_value_changed_fn(self._on_refresh_interval_changed)

    @staticmethod
    def _combo_index_model(combo):
        if not combo or not combo.model:
            return None
        return combo.model.get_item_value_model(None)

    @staticmethod
    def _model_int(model) -> int:
        if hasattr(model, "as_int"):
            return int(model.as_int)
        return int(model.get_value_as_int())

    def _on_workload_mode_changed(self, model) -> None:
        if not self._telemetry_provider:
            return
        index = self._model_int(model)
        if 0 <= index < len(self._workload_modes):
            self._telemetry_provider.set_mode(self._workload_modes[index])
            self._next_telemetry_ui_update = 0.0

    def _on_refresh_interval_changed(self, model) -> None:
        if not self._telemetry_provider:
            return
        index = self._model_int(model)
        if 0 <= index < len(self._refresh_intervals):
            self._telemetry_provider.set_refresh_interval(
                self._refresh_intervals[index]
            )
            self._next_telemetry_ui_update = 0.0

    def _toggle_telemetry_freeze(self) -> None:
        if not self._telemetry_provider or not self._telemetry_latch:
            return
        if self._telemetry_latch.is_frozen:
            self._telemetry_latch.resume()
            if self._freeze_button:
                self._freeze_button.text = "Freeze"
        else:
            self._telemetry_latch.freeze(self._telemetry_provider.latest_snapshot)
            if self._freeze_button:
                self._freeze_button.text = "Resume"
        self._next_telemetry_ui_update = 0.0

    async def _run_telemetry(self) -> None:
        try:
            import omni.kit.app
            import omni.usd

            app = omni.kit.app.get_app()
            usd_context = omni.usd.get_context()
            next_provider_tick = (
                time.monotonic() + self._telemetry_provider.config.provider_tick_seconds
            )
            self._next_telemetry_ui_update = 0.0

            while self._telemetry_provider and self._window:
                await app.next_update_async()
                now = time.monotonic()

                if (
                    self._telemetry_config_status_clear_at
                    and now >= self._telemetry_config_status_clear_at
                ):
                    self._set_telemetry_config_status("")

                if now >= next_provider_tick:
                    self._telemetry_provider.tick()
                    next_provider_tick = (
                        now + self._telemetry_provider.config.provider_tick_seconds
                    )

                if self._motion_controller:
                    self._motion_controller.update(
                        usd_context.get_stage(),
                        self._telemetry_provider.latest_snapshot,
                        now,
                    )

                if now >= self._next_telemetry_ui_update:
                    latest = self._telemetry_provider.latest_snapshot
                    displayed = self._telemetry_latch.displayed(latest)
                    self._update_telemetry_labels(displayed)
                    self._next_telemetry_ui_update = now + latest.refresh_interval_s
        except asyncio.CancelledError:
            return
        except Exception as exc:  # noqa: BLE001
            self._set_status(f"Telemetry stopped: {exc}")

    def _update_telemetry_labels(self, snapshot) -> None:
        if self._telemetry_timestamp_label:
            prefix = (
                "Frozen at"
                if self._telemetry_latch and self._telemetry_latch.is_frozen
                else "Last update"
            )
            timestamp = snapshot.timestamp.astimezone().strftime("%Y-%m-%d %H:%M:%S")
            self._telemetry_timestamp_label.text = f"{prefix}: {timestamp}"

        if self._telemetry_state_label:
            health = snapshot.metrics["health_state"].value
            self._telemetry_state_label.text = (
                f"{snapshot.operational_state} / {health}"
            )
            self._telemetry_state_label.style = {
                "color": self._health_colour(str(health))
            }

        for metric_id, labels in self._telemetry_metric_labels.items():
            metric = snapshot.metrics.get(metric_id)
            if metric:
                for label in labels:
                    label.text = self._format_metric(metric.value, metric.unit)
                    if metric_id == "throttling_active":
                        label.style = {
                            "color": (0xFF5C5CE6 if bool(metric.value) else 0xFF72B88A)
                        }

    @staticmethod
    def _health_colour(health: str) -> int:
        if health == "Critical":
            return 0xFF5C5CE6
        if health == "Warning":
            return 0xFF5CC5E6
        return 0xFF72B88A

    @staticmethod
    def _format_metric(value, unit: str) -> str:
        if isinstance(value, bool):
            return "Active" if value else "Inactive"
        if isinstance(value, str):
            return value
        precision = 0 if unit in {"RPM", "W", "CFM", "sessions"} else 1
        formatted = f"{float(value):.{precision}f}"
        return f"{formatted} {unit}".strip()

    def _build_float_row(
        self,
        label: str,
        model,
        enabled: bool = True,
        precision: int = 2,
    ) -> None:
        with ui.HStack(height=24, spacing=6, content_clipping=True):
            ui.Label(label, width=ROW_LABEL_WIDTH, elided_text=True)
            ui.FloatDrag(
                model=model,
                width=ui.Fraction(1),
                precision=precision,
                enabled=enabled,
            )

    async def _dock_left(self) -> None:
        try:
            import omni.kit.app

            app = omni.kit.app.get_app()
            for _ in range(3):
                await app.next_update_async()

            viewport = ui.Workspace.get_window("Viewport")
            if viewport and self._window:
                self._window.dock_in(viewport, ui.DockPosition.LEFT, 0.15)
                await app.next_update_async()
                if self._window.dock_id:
                    ui.Workspace.set_dock_id_width(
                        self._window.dock_id,
                        PANEL_WIDTH,
                    )
        except Exception:  # noqa: BLE001
            return

    def _reload_config(self) -> None:
        config = self._controller.reload_config()
        if self._asset_label:
            asset_text = config.default_asset.label
            self._asset_label.text = _compact_text(asset_text)
            self._asset_label.tooltip = asset_text
        self._set_lighting_controls(config.lighting)
        self._set_grid_controls(config.grid)
        if config.camera:
            self._set_camera_controls(config.camera)
        if self._lighting_status_label:
            lighting_text = f"HDRI: {config.default_hdri_path.name}"
            self._lighting_status_label.text = _compact_text(lighting_text)
            self._lighting_status_label.tooltip = lighting_text
        self._set_status("Configuration reloaded.")

    def _set_status(self, message: str) -> None:
        if self._status_label:
            self._status_label.text = _compact_text(message)
            self._status_label.tooltip = message

    def _set_lighting_status(self, message: str) -> None:
        if self._lighting_status_label:
            self._lighting_status_label.text = _compact_text(message)
            self._lighting_status_label.tooltip = message

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

    def _schedule_apply_camera(self) -> None:
        self._lighting_task = asyncio.ensure_future(self._apply_camera())

    def _schedule_apply_grid(self) -> None:
        self._lighting_task = asyncio.ensure_future(self._apply_grid())

    def _schedule_reset_camera(self) -> None:
        self._lighting_task = asyncio.ensure_future(self._reset_camera())

    def _reset_lighting_controls(self) -> None:
        config = self._controller.clear_lighting_override()
        self._set_lighting_controls(config.lighting)
        self._set_lighting_status("Lighting controls reset to project defaults.")

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
        from blackwell_monitoring_suite.app.config import LightingConfig, RotationConfig

        # isort: on

        return LightingConfig(
            hdri_path=self._hdri_model.as_string.strip(),
            exposure=float(self._exposure_model.as_float),
            intensity=float(self._intensity_model.as_float),
            show_hdri_background=bool(self._show_hdri_background_model.as_bool),
            review_key_light_enabled=bool(self._review_key_model.as_bool),
            review_key_light_intensity=float(self._review_key_intensity_model.as_float),
            rotation=RotationConfig(
                x=float(self._rotation_x_model.as_float),
                y=float(self._rotation_y_model.as_float),
                z=float(self._rotation_z_model.as_float),
            ),
        )

    def _build_camera_config_from_controls(self):
        # isort: off
        from blackwell_monitoring_suite.app.config import CameraConfig, RotationConfig

        # isort: on

        return CameraConfig(
            position=RotationConfig(
                x=float(self._camera_position_x_model.as_float),
                y=float(self._camera_position_y_model.as_float),
                z=float(self._camera_position_z_model.as_float),
            ),
            rotation=RotationConfig(
                x=float(self._camera_rotation_x_model.as_float),
                y=float(self._camera_rotation_y_model.as_float),
                z=float(self._camera_rotation_z_model.as_float),
            ),
            rotation_order=self._camera_rotation_order,
        )

    def _build_grid_config_from_controls(self):
        from blackwell_monitoring_suite.app.config import GridConfig

        return GridConfig(
            enabled=bool(self._grid_enabled_model.as_bool),
            step=float(self._grid_step_model.as_float),
            width=float(self._grid_width_model.as_float),
        )

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

    async def _sync_camera_panel(self) -> None:
        try:
            import omni.kit.app

            app = omni.kit.app.get_app()
            while self._controller and self._window:
                for _ in range(15):
                    await app.next_update_async()
                if time.monotonic() < self._suspend_camera_sync_until:
                    continue
                camera = self._controller.capture_review_camera_config()
                if camera:
                    self._set_camera_controls(camera)
        except asyncio.CancelledError:
            return
        except Exception:  # noqa: BLE001
            return

    async def _load_default_asset(self) -> None:
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
