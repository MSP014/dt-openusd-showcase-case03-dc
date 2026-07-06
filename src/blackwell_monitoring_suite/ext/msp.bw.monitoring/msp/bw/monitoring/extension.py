"""Blackwell Monitoring Suite Kit extension."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import carb.settings
import carb.tokens
import omni.ext
import omni.ui as ui

EXTENSION_SETTINGS = "/exts/msp.bw.monitoring"


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
        self._asset_label = None
        self._path_label = None
        self._load_task = None

        self._settings = carb.settings.get_settings()
        self._build_controller()
        self._build_window()

        if self._settings.get_as_bool(f"{EXTENSION_SETTINGS}/autoLoad"):
            self._schedule_load()

    def on_shutdown(self) -> None:
        self._load_task = None
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
        default_asset = self._controller.describe_default_asset()
        default_path = config.default_asset_path

        self._window = ui.Window(
            "Blackwell Monitoring Suite",
            width=380,
            height=260,
        )
        with self._window.frame:
            with ui.VStack(spacing=8):
                ui.Label(f"{config.app_name} v{config.app_version}")
                self._asset_label = ui.Label(default_asset)
                self._path_label = ui.Label(default_path.as_posix())
                with ui.HStack(height=28, spacing=6):
                    ui.Button("Load", clicked_fn=self._schedule_load)
                    ui.Button("Reload Config", clicked_fn=self._reload_config)
                ui.Spacer(height=4)
                self._status_label = ui.Label("Ready")

    def _reload_config(self) -> None:
        config = self._controller.reload_config()
        if self._asset_label:
            self._asset_label.text = self._controller.describe_default_asset()
        if self._path_label:
            self._path_label.text = config.default_asset_path.as_posix()
        self._set_status("Configuration reloaded.")

    def _set_status(self, message: str) -> None:
        if self._status_label:
            self._status_label.text = message

    def _schedule_load(self) -> None:
        self._load_task = asyncio.ensure_future(self._load_default_asset())

    async def _load_default_asset(self) -> None:
        result = await self._controller.open_default_asset_in_kit(
            status_callback=self._set_status,
        )
        self._set_status(result.message)
