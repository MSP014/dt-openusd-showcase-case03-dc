"""Runtime commands for Blackwell Monitoring Suite."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from blackwell_monitoring_suite.app.config import RuntimeConfig

StatusCallback = Callable[[str], None]


@dataclass(frozen=True)
class LoadResult:
    """Result of a runtime stage-load command."""

    success: bool
    message: str
    stage_path: Path
    root_identifier: str = ""


class RuntimeController:
    """Coordinates config-backed runtime operations for the viewer."""

    def __init__(self, config_path: Path | str):
        self._config_path = Path(config_path)
        self.config = RuntimeConfig.load(self._config_path)

    def reload_config(self) -> RuntimeConfig:
        """Reload and return the current runtime config."""

        self.config = RuntimeConfig.load(self._config_path)
        return self.config

    def describe_default_asset(self) -> str:
        """Return a compact operator-facing description of the default asset."""

        asset = self.config.default_asset
        return f"{asset.label} ({asset.asset_id})"

    async def open_default_asset_in_kit(
        self,
        status_callback: StatusCallback | None = None,
        max_wait_frames: int = 120,
    ) -> LoadResult:
        """Open the configured default asset in the active Kit USD context."""

        asset_path = self.config.default_asset_path
        if not asset_path.exists():
            return LoadResult(
                success=False,
                message=f"Missing configured asset: {asset_path}",
                stage_path=asset_path,
            )

        def set_status(message: str) -> None:
            if status_callback:
                status_callback(message)

        import omni.kit.app
        import omni.usd

        usd_context = omni.usd.get_context()
        app = omni.kit.app.get_app()

        waited_frames = 0
        set_status(f"Waiting for USD context: {asset_path.name}")
        while not usd_context.can_open_stage():
            await app.next_update_async()
            waited_frames += 1
            if waited_frames >= max_wait_frames:
                return LoadResult(
                    success=False,
                    message="Timed out waiting for USD context.",
                    stage_path=asset_path,
                )

        set_status(f"Opening {asset_path.name}")
        result, error = await usd_context.open_stage_async(
            asset_path.as_posix(),
            omni.usd.UsdContextInitialLoadSet.LOAD_ALL,
        )

        if not result:
            return LoadResult(
                success=False,
                message=f"Failed to open asset: {error}",
                stage_path=asset_path,
            )

        stage = usd_context.get_stage()
        root_identifier = ""
        viewport_message = ""
        if stage:
            root_identifier = stage.GetRootLayer().identifier
            try:
                viewport_message = await self._prepare_viewport_review(stage, app)
            except Exception as exc:  # noqa: BLE001
                viewport_message = f"; viewport setup failed: {exc}"

        return LoadResult(
            success=True,
            message=f"Loaded {self.config.default_asset.label}{viewport_message}",
            stage_path=asset_path,
            root_identifier=root_identifier,
        )

    async def _prepare_viewport_review(self, stage, app) -> str:
        """Add transient review helpers and frame the active viewport."""

        try:
            import omni.kit.viewport.utility as viewport_utility
            from pxr import Gf, Sdf, UsdGeom, UsdLux
        except ImportError as exc:
            return f"; viewport setup skipped: {exc}"

        previous_target = stage.GetEditTarget()
        stage.SetEditTarget(stage.GetSessionLayer())
        try:
            runtime_root = UsdGeom.Xform.Define(stage, "/BMS_Runtime")
            runtime_root.GetPrim().SetActive(True)

            camera = UsdGeom.Camera.Define(stage, "/BMS_Runtime/ReviewCamera")
            camera.CreateFocalLengthAttr(35.0)
            camera.CreateClippingRangeAttr(Gf.Vec2f(0.001, 10000.0))

            key_light = UsdLux.DistantLight.Define(stage, "/BMS_Runtime/KeyLight")
            key_light.CreateIntensityAttr(5000.0)
            key_light.CreateAngleAttr(0.8)
            key_xform = UsdGeom.Xformable(key_light.GetPrim())
            key_xform.ClearXformOpOrder()
            key_xform.AddRotateXYZOp().Set(Gf.Vec3f(-45.0, 25.0, 0.0))
        finally:
            stage.SetEditTarget(previous_target)

        viewport = None
        deadline = time.monotonic() + 20.0
        while time.monotonic() < deadline:
            viewport = viewport_utility.get_active_viewport()
            if viewport and viewport.stage:
                break
            await app.next_update_async()

        if not viewport or not viewport.stage:
            return "; viewport setup skipped: no active viewport"

        camera_path = Sdf.Path("/BMS_Runtime/ReviewCamera")
        if hasattr(viewport, "set_active_camera"):
            viewport.set_active_camera(camera_path)
        else:
            viewport.camera_path = camera_path

        await app.next_update_async()
        framed = viewport_utility.frame_viewport_selection(viewport)
        await app.next_update_async()

        if not framed:
            return "; viewport frame skipped"
        return "; viewport framed"
