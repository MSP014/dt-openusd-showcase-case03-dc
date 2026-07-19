"""Runtime commands for Blackwell Monitoring Suite."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

# isort: off
from blackwell_monitoring_suite.app.config import (
    CameraConfig,
    ChassisPresentationConfig,
    GridConfig,
    LightingConfig,
    RotationConfig,
    RuntimeConfig,
    format_runtime_override,
)
from blackwell_monitoring_suite.app.usd_preflight import run_usd_preflight

# isort: on

StatusCallback = Callable[[str], None]


@dataclass(frozen=True)
class LoadResult:
    """Result of a runtime stage-load command."""

    success: bool
    message: str
    stage_path: Path
    root_identifier: str = ""


@dataclass(frozen=True)
class LightingResult:
    """Result of applying runtime review lighting."""

    success: bool
    message: str
    hdri_path: Path


class RuntimeController:
    """Coordinates config-backed runtime operations for the viewer."""

    def __init__(self, config_path: Path | str):
        self._config_path = Path(config_path)
        self.config = RuntimeConfig.load(self._config_path)

    def reload_config(self) -> RuntimeConfig:
        """Reload and return the current runtime config."""

        self.config = RuntimeConfig.load(self._config_path)
        return self.config

    def project_defaults(self) -> RuntimeConfig:
        """Return the project defaults without local operator overrides."""

        return RuntimeConfig.load(
            self._config_path,
            apply_local_overrides=False,
        )

    def save_runtime_override(
        self,
        lighting: LightingConfig,
        camera: CameraConfig | None = None,
        grid: GridConfig | None = None,
    ) -> Path:
        """Persist local operator settings beside the base config."""

        active_camera = camera or self.config.camera
        active_grid = grid or self.config.grid
        local_path = RuntimeConfig.local_config_path_for(self._config_path)
        local_path.write_text(
            format_runtime_override(lighting, active_camera, active_grid),
            encoding="utf-8",
        )
        self.config = RuntimeConfig.load(self._config_path)
        return local_path

    def save_lighting_override(self, lighting: LightingConfig) -> Path:
        """Persist local operator lighting settings beside the base config."""

        return self.save_runtime_override(
            lighting,
            self.config.camera,
            self.config.grid,
        )

    def clear_camera_override(self, lighting: LightingConfig) -> Path:
        """Persist lighting while removing any local camera override."""

        local_path = RuntimeConfig.local_config_path_for(self._config_path)
        local_path.write_text(
            format_runtime_override(lighting, None, self.config.grid),
            encoding="utf-8",
        )
        self.config = RuntimeConfig.load(self._config_path)
        return local_path

    def save_grid_override(self, lighting: LightingConfig, grid: GridConfig) -> Path:
        """Persist local operator grid settings beside the base config."""

        return self.save_runtime_override(
            lighting,
            self.config.camera,
            grid,
        )

    def clear_lighting_override(self) -> RuntimeConfig:
        """Remove local operator lighting settings and reload project defaults."""

        local_path = RuntimeConfig.local_config_path_for(self._config_path)
        if local_path.exists():
            local_path.unlink()
        self.config = RuntimeConfig.load(self._config_path)
        return self.config

    def describe_default_asset(self) -> str:
        """Return a compact operator-facing description of the default asset."""

        asset = self.config.default_asset
        return f"{asset.label} ({asset.asset_id})"

    def describe_default_lighting(self) -> str:
        """Return a compact operator-facing description of the lighting preset."""

        return self.config.lighting.hdri_path

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
        preflight_message = ""
        viewport_message = ""
        if stage:
            root_identifier = stage.GetRootLayer().identifier
            set_status("Running USD preflight")
            preflight_result = run_usd_preflight(stage, self.config)
            preflight_message = f"; {preflight_result.format_summary()}"
            if preflight_result.has_errors:
                set_status(preflight_result.format_summary())
                return LoadResult(
                    success=False,
                    message=(
                        f"Loaded {self.config.default_asset.label}"
                        f"{preflight_message}"
                    ),
                    stage_path=asset_path,
                    root_identifier=root_identifier,
                )
            try:
                viewport_message = await self._prepare_viewport_review(stage, app)
            except Exception as exc:  # noqa: BLE001
                viewport_message = f"; viewport setup failed: {exc}"

        return LoadResult(
            success=True,
            message=(
                f"Loaded {self.config.default_asset.label}"
                f"{preflight_message}{viewport_message}"
            ),
            stage_path=asset_path,
            root_identifier=root_identifier,
        )

    async def apply_lighting_in_kit(
        self,
        lighting: LightingConfig | None = None,
        status_callback: StatusCallback | None = None,
    ) -> LightingResult:
        """Apply the review lighting baseline to the active Kit USD stage."""

        import omni.kit.app
        import omni.usd

        active_lighting = lighting or self.config.lighting
        hdri_path = self._resolve_hdri_path(active_lighting)

        def set_status(message: str) -> None:
            if status_callback:
                status_callback(message)

        usd_context = omni.usd.get_context()
        stage = usd_context.get_stage()
        if not stage:
            return LightingResult(
                success=False,
                message="Lighting skipped: no open stage.",
                hdri_path=hdri_path,
            )

        set_status(f"Applying lighting: {Path(active_lighting.hdri_path).name}")
        result = self._apply_review_lighting(stage, active_lighting)
        await omni.kit.app.get_app().next_update_async()
        return result

    async def apply_camera_in_kit(
        self,
        camera: CameraConfig,
        status_callback: StatusCallback | None = None,
    ) -> bool:
        """Apply a configured transform to the active review camera."""

        import omni.kit.app
        import omni.usd
        from pxr import UsdGeom

        stage = omni.usd.get_context().get_stage()
        if not stage:
            if status_callback:
                status_callback("Camera skipped: no open stage.")
            return False

        prim = stage.GetPrimAtPath("/BMS_Runtime/ReviewCamera")
        if not prim:
            if status_callback:
                status_callback("Camera skipped: no review camera.")
            return False

        previous_target = stage.GetEditTarget()
        stage.SetEditTarget(stage.GetSessionLayer())
        try:
            self._apply_camera_config(prim, camera, UsdGeom)
        finally:
            stage.SetEditTarget(previous_target)

        await omni.kit.app.get_app().next_update_async()
        if status_callback:
            status_callback("Camera applied.")
        return True

    async def apply_grid_in_kit(
        self,
        grid: GridConfig,
        status_callback: StatusCallback | None = None,
    ) -> bool:
        """Apply review grid visibility to the current stage."""

        import omni.kit.app
        import omni.usd
        from pxr import Gf, Sdf, Usd, UsdGeom

        stage = omni.usd.get_context().get_stage()
        if not stage:
            if status_callback:
                status_callback("Grid skipped: no open stage.")
            return False

        previous_target = stage.GetEditTarget()
        stage.SetEditTarget(stage.GetSessionLayer())
        try:
            self._create_review_grid(stage, Usd, Gf, Sdf, UsdGeom, grid)
        finally:
            stage.SetEditTarget(previous_target)

        await omni.kit.app.get_app().next_update_async()
        if status_callback:
            status_callback("Grid enabled." if grid.enabled else "Grid disabled.")
        return True

    async def apply_chassis_presentation_in_kit(
        self,
        open_chassis: bool,
        status_callback: StatusCallback | None = None,
    ) -> bool:
        """Apply the configured enclosure visibility in the session layer."""

        import omni.kit.app
        import omni.usd
        from pxr import UsdGeom

        stage = omni.usd.get_context().get_stage()
        if not stage:
            if status_callback:
                status_callback("Chassis view skipped: no open stage.")
            return False

        previous_target = stage.GetEditTarget()
        stage.SetEditTarget(stage.GetSessionLayer())
        try:
            self._apply_chassis_presentation(
                stage,
                self.config.chassis_presentation,
                open_chassis,
                UsdGeom,
            )
        finally:
            stage.SetEditTarget(previous_target)

        await omni.kit.app.get_app().next_update_async()
        if status_callback:
            status_callback("Chassis opened." if open_chassis else "Chassis closed.")
        return True

    def capture_review_camera_config(self) -> CameraConfig | None:
        """Return the current review camera transform, if the stage has one."""

        try:
            import omni.usd
            from pxr import Usd, UsdGeom
        except ImportError:
            return None

        stage = omni.usd.get_context().get_stage()
        if not stage:
            return None

        prim = stage.GetPrimAtPath("/BMS_Runtime/ReviewCamera")
        if not prim:
            return None

        return self._camera_config_from_prim(prim, Usd, UsdGeom)

    async def _prepare_viewport_review(self, stage, app) -> str:
        """Add transient review helpers and frame the active viewport."""

        try:
            import omni.kit.viewport.utility as viewport_utility
            from pxr import Gf, Sdf, Usd, UsdGeom
        except ImportError as exc:
            return f"; viewport setup skipped: {exc}"

        previous_target = stage.GetEditTarget()
        stage.SetEditTarget(stage.GetSessionLayer())
        try:
            runtime_root = UsdGeom.Xform.Define(stage, "/BMS_Runtime")
            runtime_root.GetPrim().SetActive(True)
            self._apply_chassis_presentation(
                stage,
                self.config.chassis_presentation,
                self.config.chassis_presentation.open_chassis,
                UsdGeom,
            )
            self._create_review_grid(
                stage,
                Usd,
                Gf,
                Sdf,
                UsdGeom,
                self.config.grid,
            )

            camera = UsdGeom.Camera.Define(stage, "/BMS_Runtime/ReviewCamera")
            camera.CreateFocalLengthAttr(35.0)
            camera.CreateClippingRangeAttr(Gf.Vec2f(0.001, 10000.0))
            if self.config.camera:
                self._apply_camera_config(camera.GetPrim(), self.config.camera, UsdGeom)

            lighting_result = self._apply_review_lighting(stage, self.config.lighting)
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

        if self.config.camera:
            framed = True
        else:
            await app.next_update_async()
            framed = viewport_utility.frame_viewport_selection(viewport)
            await app.next_update_async()

        if not framed:
            return "; viewport frame skipped"
        return f"; viewport framed; {lighting_result.message}"

    @staticmethod
    def _apply_chassis_presentation(
        stage,
        presentation: ChassisPresentationConfig,
        open_chassis: bool,
        UsdGeom,
    ) -> None:
        """Author reversible cover visibility opinions on the session layer."""

        visibility = (
            UsdGeom.Tokens.invisible if open_chassis else UsdGeom.Tokens.inherited
        )
        for path in presentation.cover_paths:
            prim = stage.GetPrimAtPath(path)
            if not prim or not prim.IsValid():
                continue
            imageable = UsdGeom.Imageable(prim)
            if not imageable:
                continue
            imageable.CreateVisibilityAttr().Set(visibility)

    def _resolve_hdri_path(self, lighting: LightingConfig) -> Path:
        hdri_path = Path(lighting.hdri_path)
        if hdri_path.is_absolute():
            return hdri_path.resolve()
        return (self.config.asset_root / hdri_path).resolve()

    @staticmethod
    def _apply_camera_config(prim, camera: CameraConfig, UsdGeom) -> None:
        if camera.transform:
            from pxr import Gf

            matrix_op = UsdGeom.Xformable(prim).MakeMatrixXform()
            matrix_op.Set(RuntimeController._matrix_from_values(camera.transform, Gf))
            return

        xformable = UsdGeom.Xformable(prim)
        xformable.ClearXformOpOrder()

        translate_op = xformable.GetTranslateOp()
        if not translate_op:
            translate_op = xformable.AddTranslateOp(UsdGeom.XformOp.PrecisionDouble)

        rotation_order = RuntimeController._camera_rotation_order(camera)
        rotate_getter = getattr(xformable, f"GetRotate{rotation_order}Op")
        rotate_adder = getattr(xformable, f"AddRotate{rotation_order}Op")
        rotate_op = rotate_getter()
        if not rotate_op:
            rotate_op = rotate_adder(UsdGeom.XformOp.PrecisionDouble)

        translate_op.Set(
            (
                float(camera.position.x),
                float(camera.position.y),
                float(camera.position.z),
            )
        )
        rotate_op.Set(
            (
                float(camera.rotation.x),
                float(camera.rotation.y),
                float(camera.rotation.z),
            )
        )
        xformable.SetXformOpOrder([translate_op, rotate_op])

    @staticmethod
    def _camera_rotation_order(camera: CameraConfig) -> str:
        if camera.rotation_order in {"XYZ", "XZY", "YXZ", "YZX", "ZXY", "ZYX"}:
            return camera.rotation_order
        return "YXZ"

    @staticmethod
    def _create_review_grid(stage, Usd, Gf, Sdf, UsdGeom, grid: GridConfig) -> None:
        grid_path = Sdf.Path("/BMS_Runtime/ReviewGrid")
        if stage.GetPrimAtPath(grid_path):
            stage.RemovePrim(grid_path)

        if not grid.enabled:
            return

        up_axis = str(UsdGeom.GetStageUpAxis(stage)).lower()
        size = 4
        step = max(float(grid.step), 0.001)
        extent = size * step
        half_width = max(float(grid.width), 0.0001) * 0.5
        points = []
        counts = []
        indices = []

        def add_quad(corners) -> None:
            base_index = len(points)
            points.extend(corners)
            counts.append(4)
            indices.extend(
                [
                    base_index,
                    base_index + 1,
                    base_index + 2,
                    base_index + 3,
                ]
            )

        for index in range(-size, size + 1):
            value = index * step
            if up_axis == "z":
                add_quad(
                    (
                        Gf.Vec3f(-extent, value - half_width, 0),
                        Gf.Vec3f(extent, value - half_width, 0),
                        Gf.Vec3f(extent, value + half_width, 0),
                        Gf.Vec3f(-extent, value + half_width, 0),
                    )
                )
                add_quad(
                    (
                        Gf.Vec3f(value - half_width, -extent, 0),
                        Gf.Vec3f(value + half_width, -extent, 0),
                        Gf.Vec3f(value + half_width, extent, 0),
                        Gf.Vec3f(value - half_width, extent, 0),
                    )
                )
            else:
                add_quad(
                    (
                        Gf.Vec3f(-extent, 0, value - half_width),
                        Gf.Vec3f(extent, 0, value - half_width),
                        Gf.Vec3f(extent, 0, value + half_width),
                        Gf.Vec3f(-extent, 0, value + half_width),
                    )
                )
                add_quad(
                    (
                        Gf.Vec3f(value - half_width, 0, -extent),
                        Gf.Vec3f(value + half_width, 0, -extent),
                        Gf.Vec3f(value + half_width, 0, extent),
                        Gf.Vec3f(value - half_width, 0, extent),
                    )
                )

        mesh = UsdGeom.Mesh.Define(stage, grid_path)
        mesh.CreatePointsAttr().Set(points)
        mesh.CreateFaceVertexCountsAttr().Set(counts)
        mesh.CreateFaceVertexIndicesAttr().Set(indices)
        mesh.CreateDoubleSidedAttr(True)
        mesh.CreateDisplayColorAttr().Set([Gf.Vec3f(0.35, 0.42, 0.48)])

    @staticmethod
    def _camera_config_from_prim(prim, Usd, UsdGeom) -> CameraConfig | None:
        xformable = UsdGeom.Xformable(prim)
        matrix = xformable.GetLocalTransformation()
        position = matrix.ExtractTranslation()
        rotation = RuntimeController._matrix_rotation_xyz(matrix)

        return CameraConfig(
            position=RotationConfig(
                x=float(position[0]),
                y=float(position[1]),
                z=float(position[2]),
            ),
            rotation=RotationConfig(
                x=float(rotation[0]),
                y=float(rotation[1]),
                z=float(rotation[2]),
            ),
            rotation_order="XYZ",
            transform=RuntimeController._matrix_to_values(matrix),
        )

    @staticmethod
    def _matrix_rotation_xyz(matrix):
        from pxr import Gf

        rotation = matrix.ExtractRotation()
        return rotation.Decompose(
            Gf.Vec3d(1.0, 0.0, 0.0),
            Gf.Vec3d(0.0, 1.0, 0.0),
            Gf.Vec3d(0.0, 0.0, 1.0),
        )

    @staticmethod
    def _matrix_to_values(matrix) -> tuple[float, ...]:
        return tuple(
            float(matrix[row][column]) for row in range(4) for column in range(4)
        )

    @staticmethod
    def _matrix_from_values(values: tuple[float, ...], Gf):
        try:
            return Gf.Matrix4d(*values)
        except TypeError:
            rows = [tuple(values[index : index + 4]) for index in range(0, 16, 4)]
            return Gf.Matrix4d(*rows)

    @staticmethod
    def _rotation_order_name(rotation_order, UsdGeom) -> str:
        if rotation_order is None:
            return "XYZ"
        for name in ("XYZ", "XZY", "YXZ", "YZX", "ZXY", "ZYX"):
            if rotation_order == getattr(
                UsdGeom.XformCommonAPI,
                f"RotationOrder{name}",
            ):
                return name
        return "YXZ"

    def _apply_review_lighting(self, stage, lighting: LightingConfig) -> LightingResult:
        """Create or update transient review lighting in the session layer."""

        from pxr import Gf, Sdf, UsdGeom, UsdLux

        hdri_path = self._resolve_hdri_path(lighting)
        previous_target = stage.GetEditTarget()
        stage.SetEditTarget(stage.GetSessionLayer())
        try:
            lighting_root = UsdGeom.Xform.Define(stage, "/BMS_Runtime/Lighting")
            lighting_root.GetPrim().SetActive(True)

            if not hdri_path.exists():
                dome_prim = stage.GetPrimAtPath("/BMS_Runtime/Lighting/DomeLight")
                if dome_prim:
                    dome_prim.SetActive(False)
                self._set_review_key_light(stage, lighting, Gf, UsdGeom, UsdLux)
                return LightingResult(
                    success=False,
                    message=self._format_lighting_message(
                        "Missing HDRI",
                        hdri_path,
                        lighting,
                    ),
                    hdri_path=hdri_path,
                )

            legacy_key_prim = stage.GetPrimAtPath("/BMS_Runtime/KeyLight")
            if legacy_key_prim:
                legacy_key_prim.SetActive(False)

            self._set_review_key_light(stage, lighting, Gf, UsdGeom, UsdLux)

            dome_light = UsdLux.DomeLight.Define(
                stage,
                "/BMS_Runtime/Lighting/DomeLight",
            )
            dome_light.GetPrim().SetActive(True)
            self._set_schema_attr(
                dome_light,
                "CreateTextureFileAttr",
                "inputs:texture:file",
                Sdf.AssetPath(hdri_path.as_posix()),
                Sdf.ValueTypeNames.Asset,
            )
            self._set_schema_attr(
                dome_light,
                "CreateTextureFormatAttr",
                "inputs:texture:format",
                "latlong",
                Sdf.ValueTypeNames.Token,
            )
            self._set_schema_attr(
                dome_light,
                "CreateExposureAttr",
                "inputs:exposure",
                float(lighting.exposure),
                Sdf.ValueTypeNames.Float,
            )
            self._set_schema_attr(
                dome_light,
                "CreateIntensityAttr",
                "inputs:intensity",
                float(lighting.intensity),
                Sdf.ValueTypeNames.Float,
            )
            self._set_hdri_background_visibility(
                dome_light.GetPrim(),
                lighting.show_hdri_background,
                Sdf,
            )
            dome_xform = UsdGeom.Xformable(dome_light.GetPrim())
            dome_xform.ClearXformOpOrder()
            dome_xform.AddRotateXYZOp().Set(
                Gf.Vec3f(
                    float(lighting.rotation.x),
                    float(lighting.rotation.y),
                    float(lighting.rotation.z),
                )
            )
        finally:
            stage.SetEditTarget(previous_target)

        return LightingResult(
            success=True,
            message=self._format_lighting_message(
                "Lighting loaded",
                hdri_path,
                lighting,
            ),
            hdri_path=hdri_path,
        )

    @staticmethod
    def _set_hdri_background_visibility(dome_prim, show_background: bool, Sdf) -> None:
        visibility_attr = dome_prim.GetAttribute("visibleInPrimaryRay")
        if not visibility_attr:
            visibility_attr = dome_prim.CreateAttribute(
                "visibleInPrimaryRay",
                Sdf.ValueTypeNames.Bool,
            )
        visibility_attr.Set(bool(show_background))

    @staticmethod
    def _set_schema_attr(schema, create_method: str, attr_name: str, value, type_name):
        if hasattr(schema, create_method):
            getattr(schema, create_method)(value)
            return
        attr = schema.GetPrim().CreateAttribute(attr_name, type_name)
        attr.Set(value)

    @staticmethod
    def _format_lighting_message(
        prefix: str,
        hdri_path: Path,
        lighting: LightingConfig,
    ) -> str:
        key_state = (
            f"on {lighting.review_key_light_intensity:g}"
            if lighting.review_key_light_enabled
            else "off"
        )
        background_state = "show" if lighting.show_hdri_background else "hide"
        return (
            f"{prefix}: {hdri_path.name}; exposure={lighting.exposure:g}; "
            f"intensity={lighting.intensity:g}; "
            f"hdri={background_state}; key={key_state}"
        )

    @staticmethod
    def _set_review_key_light(stage, lighting, Gf, UsdGeom, UsdLux) -> None:
        key_path = "/BMS_Runtime/Lighting/ReviewKeyLight"
        if not lighting.review_key_light_enabled:
            key_prim = stage.GetPrimAtPath(key_path)
            if key_prim:
                key_prim.SetActive(False)
            return

        key_light = UsdLux.DistantLight.Define(
            stage,
            key_path,
        )
        key_light.GetPrim().SetActive(True)
        key_light.CreateIntensityAttr(float(lighting.review_key_light_intensity))
        key_light.CreateAngleAttr(1.2)
        key_xform = UsdGeom.Xformable(key_light.GetPrim())
        key_xform.ClearXformOpOrder()
        key_xform.AddRotateXYZOp().Set(Gf.Vec3f(-45.0, 25.0, 0.0))
