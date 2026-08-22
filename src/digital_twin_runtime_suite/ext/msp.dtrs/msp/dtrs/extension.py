"""Digital Twin Runtime Suite Kit extension."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import carb
import carb.settings
import carb.tokens
import carb.windowing
import omni.appwindow
import omni.ext
import omni.ui as ui
from msp.dtrs.ui.appearance import AppearanceUiMixin
from msp.dtrs.ui.configuration import ConfigurationUiMixin
from msp.dtrs.ui.controls import ControlsUiMixin
from msp.dtrs.ui.heatmaps import HeatmapsUiMixin
from msp.dtrs.ui.streamlines import StreamlinesUiMixin
from msp.dtrs.ui.telemetry import TelemetryUiMixin
from msp.dtrs.ui.view_state import ViewStateUiMixin
from msp.dtrs.ui.window import DtrsWindowUiMixin
from msp.dtrs.workflows.presentation_actions import (
    PresentationActionsWorkflowMixin,
)
from msp.dtrs.workflows.scene_actions import SceneActionsWorkflowMixin
from msp.dtrs.workflows.streamlines_cache_actions import (
    StreamlinesCacheWorkflowMixin,
)

EXTENSION_SETTINGS = "/exts/msp.dtrs"
PANEL_WIDTH = 340
_DTRS_LOG_CHANNEL_LEVEL = "/log/channels/msp.dtrs.*"
_DTRS_OBSERVABILITY_LOG_CHANNEL_LEVEL = "/observability/logs/channels/msp.dtrs.*"
# DtrsEventSink calls Carbonite from the reusable application package, so its
# semantic INFO events belong to this channel rather than the Kit extension's.
_DTRS_REPORTING_LOG_CHANNEL_LEVEL = (
    "/log/channels/digital_twin_runtime_suite.app.observability.*"
)
_DTRS_OBSERVABILITY_REPORTING_LOG_CHANNEL_LEVEL = (
    "/observability/logs/channels/digital_twin_runtime_suite.app.observability.*"
)


def _resolve_token_path(value: str) -> Path:
    tokens = carb.tokens.get_tokens_interface()
    return Path(tokens.resolve(value)).resolve()


def _fallback_source_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if parent.name == "digital_twin_runtime_suite":
            return parent
    raise RuntimeError("Unable to locate Digital Twin Runtime Suite source root.")


def _ensure_source_root(source_root: Path) -> None:
    src_root = source_root.parent
    src_root_text = str(src_root)
    if src_root_text not in sys.path:
        sys.path.insert(0, src_root_text)


def _with_dtrs_local_timestamp(message: str) -> str:
    """Load the shared formatter only after the extension source root exists."""

    from digital_twin_runtime_suite.app.diagnostics import (
        with_dtrs_local_timestamp,
    )

    return with_dtrs_local_timestamp(message)


class DigitalTwinRuntimeSuiteExtension(
    TelemetryUiMixin,
    DtrsWindowUiMixin,
    HeatmapsUiMixin,
    StreamlinesUiMixin,
    AppearanceUiMixin,
    ConfigurationUiMixin,
    ControlsUiMixin,
    ViewStateUiMixin,
    StreamlinesCacheWorkflowMixin,
    SceneActionsWorkflowMixin,
    PresentationActionsWorkflowMixin,
    omni.ext.IExt,
):
    """Runtime controls for the current Digital Twin Runtime Suite slice."""

    def on_startup(self, ext_id: str) -> None:
        self._window = None
        self._controller = None
        self._status_label = None
        self._lighting_status_label = None
        self._asset_label = None
        self._load_task = None
        self._reload_task = None
        self._airflow_task = None
        self._visualization_workflow = None
        self._airflow_detach_requested = False
        self._airflow_cache_selector_label = None
        self._streamlines_status_label = None
        self._heatmap_test_button = None
        self._heatmap_settings_frame = None
        self._heatmap_isolation_models = {}
        self._heatmap_calibration_models = {}
        self._heatmap_color_stop_models = {}
        self._heatmap_color_stops = ()
        self._heatmap_minimum_clamp_model = None
        self._heatmap_maximum_clamp_model = None
        self._streamlines_cache_build_button = None
        self._streamlines_cache_load_button = None
        self._validation_workflow = None
        self._reuse_vti_receipts_model = None
        self._reuse_streamlines_receipts_model = None
        self._validation_receipt_status_label = None
        self._validation_receipt_progress_labels = {}
        self._streamlines_profile_combo = None
        self._streamlines_workflow = None
        self._streamlines_material_apply_button = None
        self._updating_streamlines_profile_combo = False
        self._streamlines_material_tuning_combos = {}
        self._streamlines_material_status_label = None
        self._view_task = None
        self._auxiliary_windows_task = None
        self._smoke_tuning_combos = {}
        self._flow_voxel_resolution_combo = None
        self._show_flow_debug_overlays_model = None
        self._flow_camera_bookmarks = {}
        self._lighting_task = None
        self._camera_sync_task = None
        self._telemetry_task = None
        self._motion_controller = None
        self._suspend_camera_sync_until = 0.0
        self._updating_camera_controls = False
        self._telemetry_provider = None
        self._telemetry_latch = None
        self._telemetry_frame = None
        self._view_frame = None
        self._config_frame = None
        self._telemetry_tab_button = None
        self._view_tab_button = None
        self._config_tab_button = None
        self._chassis_visibility_models = {}
        self._normal_map_scale_model = None
        self._xray_target_models = {}
        self._xray_target_checkboxes = {}
        self._visualization_combo = None
        self._visualization_readiness_labels = {}
        self._updating_visualization_mode = False
        self._face_panel_open_model = None
        self._face_panel_action_label = None
        self._face_panel_open_state = False
        self._workload_combo = None
        self._refresh_combo = None
        self._freeze_button = None
        self._telemetry_timestamp_label = None
        self._telemetry_state_label = None
        self._telemetry_metric_labels = {}
        self._workload_modes = ()
        self._refresh_intervals = ()
        self._telemetry_config_path = None
        self._telemetry_config_workflow = None
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
        # Keep DTRS milestones at info while exposing only this extension's
        # and reusable reporting channels to both Carbonite and its
        # observability listener.
        self._settings.set(_DTRS_LOG_CHANNEL_LEVEL, "info")
        self._settings.set(_DTRS_OBSERVABILITY_LOG_CHANNEL_LEVEL, "info")
        self._settings.set(_DTRS_REPORTING_LOG_CHANNEL_LEVEL, "info")
        self._settings.set(
            _DTRS_OBSERVABILITY_REPORTING_LOG_CHANNEL_LEVEL,
            "info",
        )
        carb.log_info(
            "DTRS renderer delegate\n"
            "/app/useFabricSceneDelegate = "
            f"{self._settings.get_as_bool('/app/useFabricSceneDelegate')}"
        )
        self._build_controller()
        from digital_twin_runtime_suite.app.observability import (
            DtrsEventSink,
            KitStatusBarProgressSink,
            ProgressReporter,
        )

        observability_status_bar = KitStatusBarProgressSink.from_kit()
        self._observability_reporter = ProgressReporter(
            event_sinks=(
                DtrsEventSink(
                    # Kit's current console suppresses INFO even with channel
                    # overrides. Keep guided developer-gate milestones visible.
                    log_info=carb.log_warn,
                    log_warning=carb.log_warn,
                    log_error=carb.log_error,
                    append_local_timestamp=_with_dtrs_local_timestamp,
                ),
            ),
            progress_sinks=(observability_status_bar,),
            finish_sinks=(observability_status_bar.finish,),
        )
        from msp.dtrs.workflows.validation_receipts import (
            ValidationReceiptWorkflow,
        )

        self._validation_workflow = ValidationReceiptWorkflow(
            self._controller,
            current_workload=lambda: getattr(self._telemetry_provider, "mode", None),
            normal_selected=self._visualization_combo_is_normal,
            log_warning=carb.log_warn,
            append_local_timestamp=_with_dtrs_local_timestamp,
            log_error=lambda message: carb.log_error(
                _with_dtrs_local_timestamp(message)
            ),
            include_airflow_diagnostics=True,
            progress_reporter=self._observability_reporter,
        )
        self._validation_workflow.load_checkpoint()
        from msp.dtrs.workflows.visualization import VisualizationWorkflow

        self._visualization_workflow = VisualizationWorkflow(
            self._controller,
            self._validation_workflow,
            report_status=self._set_airflow_status,
            refresh_cache_selector=self._refresh_airflow_cache_selector_label,
            refresh_visualization_controls=self._update_visualization_controls,
            log_warning=carb.log_warn,
            append_local_timestamp=_with_dtrs_local_timestamp,
        )
        from msp.dtrs.workflows.streamlines import StreamlinesWorkflow

        self._streamlines_workflow = StreamlinesWorkflow(
            self._controller,
            report_status=self._set_streamlines_status,
            report_material_status=self._set_streamlines_material_status,
            restore_profile_selection=self._restore_streamlines_profile_selection,
            log_error=lambda message: carb.log_error(
                _with_dtrs_local_timestamp(message)
            ),
        )
        from msp.dtrs.workflows.telemetry_config import TelemetryConfigWorkflow

        self._telemetry_config_workflow = TelemetryConfigWorkflow(
            self._telemetry_config_path
        )
        self._build_window()
        self._observability_reporter.add_progress_sink(
            self._set_validation_receipt_live_progress
        )
        self._validation_workflow.initialize_acceptance()
        if self._validation_workflow.checkpoint is None:
            self._validation_workflow.start_background_work()
        asyncio.ensure_future(self._dock_left())
        self._auxiliary_windows_task = asyncio.ensure_future(
            self._hide_auxiliary_kit_windows()
        )
        self._camera_sync_task = asyncio.ensure_future(self._sync_camera_panel())
        self._telemetry_task = asyncio.ensure_future(self._run_telemetry())

        if self._settings.get_as_bool(f"{EXTENSION_SETTINGS}/autoLoad"):
            self._schedule_load()

    def on_shutdown(self) -> None:
        if self._controller:
            if self._validation_workflow:
                self._validation_workflow.cancel()
            if self._visualization_workflow:
                self._visualization_workflow.cancel()
            if self._streamlines_workflow:
                self._streamlines_workflow.cancel()
            cancel_material = getattr(
                self._controller,
                "cancel_streamlines_material_apply",
                None,
            )
            if cancel_material:
                cancel_material()
        self._cancel_scene_action_tasks()
        if self._auxiliary_windows_task:
            self._auxiliary_windows_task.cancel()
            self._auxiliary_windows_task = None
        if self._camera_sync_task:
            self._camera_sync_task.cancel()
            self._camera_sync_task = None
        if self._telemetry_task:
            self._telemetry_task.cancel()
            self._telemetry_task = None
        if self._controller:
            try:
                receipt = (
                    self._controller.clear_streamlines_static_runtime_from_open_stage()
                )
                if not receipt.clean:
                    carb.log_error(
                        "DTRS STREAMLINES | SHUTDOWN_CLEANUP | FAIL\n" "result=DIRTY"
                    )
            except Exception as error:  # noqa: BLE001 - shutdown must continue.
                carb.log_error(f"DTRS Streamlines shutdown cleanup failed: {error}")
            try:
                self._controller.clear_xray_material_in_kit()
            except RuntimeError as error:
                carb.log_error(f"DTRS X-Ray shutdown cleanup failed: {error}")
            self._controller.stop_flow_runtime_callbacks()
            self._controller.clear_flow_validation_cache()
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
                / "digital_twin_runtime_suite.toml"
            ).resolve()

        # isort: off
        from digital_twin_runtime_suite.app.commands import RuntimeController
        from digital_twin_runtime_suite.app.airflow_dataset import (
            AirflowDatasetError,
            format_airflow_dataset_registry,
        )
        from digital_twin_runtime_suite.app.status_log import format_dtrs_status_block
        from digital_twin_runtime_suite.app.motion import (
            MultiRotationMotionController,
        )
        from digital_twin_runtime_suite.app.telemetry import SnapshotLatch
        from digital_twin_runtime_suite.app.telemetry import (
            SyntheticTelemetryProvider,
        )
        from digital_twin_runtime_suite.app.telemetry import TelemetryConfig

        # isort: on

        self._controller = RuntimeController(config_path)
        try:
            registry_log = format_airflow_dataset_registry(
                self._controller.airflow_dataset_registry()
            )
        except AirflowDatasetError as error:
            carb.log_error(
                _with_dtrs_local_timestamp(
                    f"DTRS AIRFLOW DATASET REGISTRY | Discovery failed: {error}"
                )
            )
        else:
            carb.log_warn(
                format_dtrs_status_block(
                    registry_log,
                    append_local_timestamp=_with_dtrs_local_timestamp,
                )
            )
        self._set_application_title_version(self._controller.config)
        telemetry_config_path = (
            config_path.parent / "telemetry_provider.toml"
        ).resolve()
        self._telemetry_config_path = telemetry_config_path
        telemetry_config = TelemetryConfig.load(telemetry_config_path)
        self._telemetry_provider = SyntheticTelemetryProvider(telemetry_config)
        self._controller.configure_heatmap_telemetry_config(telemetry_config)
        self._controller.set_workload_source(lambda: self._telemetry_provider.mode)
        self._telemetry_latch = SnapshotLatch()
        self._motion_controller = MultiRotationMotionController(
            self._controller.config.fan_motion_bindings
        )
        self._workload_modes = tuple(telemetry_config.modes)
        self._refresh_intervals = telemetry_config.allowed_refresh_intervals_s
        self._log_workload_cache_mapping(telemetry_config.default_mode)

    @staticmethod
    def _set_application_title_version(config) -> None:
        """Apply the derived display version without subscribing to USD titles."""

        app_window = (
            omni.appwindow.acquire_app_window_factory_interface().get_default_window()
        )
        if app_window is None or app_window.get_window() is None:
            carb.log_warn("DTRS could not access the native application window.")
            return
        carb.windowing.acquire_windowing_interface().set_window_title(
            app_window.get_window(),
            f"{config.app_name} {config.display_version}",
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

    async def _hide_auxiliary_kit_windows(self) -> None:
        """Keep the focused DTRS shell clear of IndeX dependency windows."""

        try:
            import omni.kit.app

            app = omni.kit.app.get_app()
            for _ in range(6):
                await app.next_update_async()

            for name in ("Property", "Content", "Render Settings"):
                window = ui.Workspace.get_window(name)
                if window:
                    window.visible = False
        except Exception:  # noqa: BLE001
            return
