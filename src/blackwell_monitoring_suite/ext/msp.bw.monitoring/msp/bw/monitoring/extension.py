"""Blackwell Monitoring Suite Kit extension."""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

import carb.settings
import carb.tokens
import omni.ext
import omni.ui as ui

EXTENSION_SETTINGS = "/exts/msp.bw.monitoring"
PANEL_WIDTH = 340
ROW_LABEL_WIDTH = 104
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
    """Stage 1 controls for loading the configured BMS asset."""

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
        self._suspend_camera_sync_until = 0.0
        self._updating_camera_controls = False
        self._hdri_model = None
        self._exposure_model = None
        self._intensity_model = None
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

        if self._settings.get_as_bool(f"{EXTENSION_SETTINGS}/autoLoad"):
            self._schedule_load()

    def on_shutdown(self) -> None:
        self._load_task = None
        self._lighting_task = None
        if self._camera_sync_task:
            self._camera_sync_task.cancel()
            self._camera_sync_task = None
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
                / "blackwell_monitoring_suite.v0.1.toml"
            ).resolve()

        from blackwell_monitoring_suite.app.commands import RuntimeController

        self._controller = RuntimeController(config_path)

    def _build_window(self) -> None:
        config = self._controller.config
        default_asset = config.default_asset.label
        lighting = config.lighting

        self._hdri_model = ui.SimpleStringModel(lighting.hdri_path)
        self._exposure_model = ui.SimpleFloatModel(lighting.exposure)
        self._intensity_model = ui.SimpleFloatModel(lighting.intensity)
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
                self._status_label = ui.Label(
                    "Ready",
                    height=34,
                    elided_text=True,
                )

                ui.Spacer(height=6)
                ui.Label("Config", height=18)
                ui.Label("Lighting", height=18)
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
                    ui.Label("Key", width=ROW_LABEL_WIDTH)
                    ui.CheckBox(model=self._review_key_model)

                self._build_float_row(
                    "Key intensity",
                    self._review_key_intensity_model,
                )

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

                ui.Spacer(height=6)
                ui.Label("Grid", height=18)
                with ui.HStack(height=24, spacing=6, content_clipping=True):
                    ui.Label("Show grid", width=ROW_LABEL_WIDTH)
                    ui.CheckBox(model=self._grid_enabled_model)
                self._build_float_row(
                    "Grid step",
                    self._grid_step_model,
                    precision=3,
                )
                self._build_float_row(
                    "Line width",
                    self._grid_width_model,
                    precision=5,
                )
                ui.Button(
                    "Apply Grid",
                    clicked_fn=self._schedule_apply_grid,
                    height=26,
                    width=ui.Percent(100),
                )

                ui.Spacer(height=6)
                ui.Label("Camera", height=18)
                ui.Label("Position", height=18)
                self._build_float_row(
                    "Camera X",
                    self._camera_position_x_model,
                )
                self._build_float_row(
                    "Camera Y",
                    self._camera_position_y_model,
                )
                self._build_float_row(
                    "Camera Z",
                    self._camera_position_z_model,
                )
                ui.Label("Rotation", height=18)
                self._build_float_row(
                    "Camera RX",
                    self._camera_rotation_x_model,
                )
                self._build_float_row(
                    "Camera RY",
                    self._camera_rotation_y_model,
                )
                self._build_float_row(
                    "Camera RZ",
                    self._camera_rotation_z_model,
                )
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
