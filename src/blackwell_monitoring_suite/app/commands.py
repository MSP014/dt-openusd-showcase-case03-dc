"""Runtime commands for Blackwell Monitoring Suite."""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from blackwell_monitoring_suite.app.kit_cae_flow_parity import (
    capture_flow_scene,
    write_flow_snapshot,
)

# isort: off
from blackwell_monitoring_suite.app.config import (
    CameraConfig,
    ChassisPresentationConfig,
    FacePanelConfig,
    FrontPanelIndicatorsConfig,
    GridConfig,
    LightingConfig,
    QledDisplayConfig,
    RotationConfig,
    RuntimeConfig,
    format_runtime_override,
)
from blackwell_monitoring_suite.app.front_panel_indicators import (
    front_panel_indicator_state,
)
from blackwell_monitoring_suite.app.qled import SEGMENTS, qled_state_from_temperature
from blackwell_monitoring_suite.app.simulation_cache import (
    SimulationCacheContract,
    run_simulation_cache_preflight,
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


@dataclass(frozen=True)
class SimulationCacheResult:
    """Result of attaching or controlling the airflow cache."""

    success: bool
    message: str


@dataclass(frozen=True)
class FacePanelApplyResult:
    """Result of preparing or applying the runtime front-panel hinge."""

    success: bool
    message: str
    start_angle: float = 0.0
    target_angle: float = 0.0
    rotate_op: object | None = None


class RuntimeController:
    """Coordinates config-backed runtime operations for the viewer."""

    FACE_PANEL_ROTATE_OP_SUFFIX = "mspViewHinge"
    KIT_CAE_SERVER_ROOT = "/blackwell_rig"
    KIT_CAE_FLOW_ALPHA_PRESETS = {
        "native": (0.3, 0.3, 1.0),
        "medium": (0.6, 0.6, 1.0),
        "strong": (0.85, 0.85, 1.0),
    }
    QLED_MATERIAL_PATHS = {
        "normal": "/BMS_Runtime/Looks/QLEDOnNormal",
        "warning": "/BMS_Runtime/Looks/QLEDOnWarning",
        "off": "/BMS_Runtime/Looks/QLEDOff",
    }
    FRONT_PANEL_MATERIAL_PATHS = {
        "power": "/BMS_Runtime/Looks/FrontPanelPowerOn",
        "hdd": "/BMS_Runtime/Looks/FrontPanelHDDOn",
        "lan_01": "/BMS_Runtime/Looks/FrontPanelLAN01On",
        "lan_02": "/BMS_Runtime/Looks/FrontPanelLAN02On",
        "off": "/BMS_Runtime/Looks/FrontPanelIndicatorOff",
    }

    def __init__(self, config_path: Path | str):
        self._config_path = Path(config_path)
        self.config = RuntimeConfig.load(self._config_path)
        self._simulation_cache_contract: SimulationCacheContract | None = None
        self._simulation_cache_time_code: int | None = None
        self._flow_airflow_simulate_path: str | None = None
        self._front_panel_indicator_state_key: (
            tuple[int, bool, bool, bool, bool] | None
        ) = None

    def reload_config(self) -> RuntimeConfig:
        """Reload and return the current runtime config."""

        self.config = RuntimeConfig.load(self._config_path)
        self._simulation_cache_contract = None
        self._simulation_cache_time_code = None
        self._flow_airflow_simulate_path = None
        self._front_panel_indicator_state_key = None
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

    async def apply_chassis_visibility_in_kit(
        self,
        group_id: str,
        visible: bool,
        status_callback: StatusCallback | None = None,
    ) -> bool:
        """Apply one configured enclosure visibility group in the session layer."""

        import omni.kit.app
        import omni.usd
        from pxr import UsdGeom

        stage = omni.usd.get_context().get_stage()
        if not stage:
            if status_callback:
                status_callback("View skipped: no open stage.")
            return False

        group = next(
            (
                group
                for group in self.config.chassis_presentation.visibility_groups
                if group.group_id == group_id
            ),
            None,
        )
        if not group:
            if status_callback:
                status_callback(f"View skipped: unknown group {group_id}.")
            return False

        previous_target = stage.GetEditTarget()
        stage.SetEditTarget(stage.GetSessionLayer())
        try:
            matched_count = self._apply_chassis_visibility_paths(
                stage,
                group.paths,
                visible,
                UsdGeom,
            )
        finally:
            stage.SetEditTarget(previous_target)

        await omni.kit.app.get_app().next_update_async()
        if status_callback:
            if matched_count:
                state = "shown" if visible else "hidden"
                status_callback(f"{group.label} {state}.")
            else:
                status_callback(f"View skipped: {group.label} prims were not found.")
        return matched_count > 0

    async def apply_chassis_visibility_state_in_kit(
        self,
        visibility_by_group: dict[str, bool],
        status_callback: StatusCallback | None = None,
    ) -> bool:
        """Apply all configured enclosure visibility controls in one operation."""

        import omni.kit.app
        import omni.usd
        from pxr import UsdGeom

        stage = omni.usd.get_context().get_stage()
        if not stage:
            if status_callback:
                status_callback("View skipped: no open stage.")
            return False

        previous_target = stage.GetEditTarget()
        stage.SetEditTarget(stage.GetSessionLayer())
        try:
            matched_count = 0
            for group in self.config.chassis_presentation.visibility_groups:
                visible = visibility_by_group.get(
                    group.group_id,
                    group.default_visible,
                )
                matched_count += self._apply_chassis_visibility_paths(
                    stage,
                    group.paths,
                    visible,
                    UsdGeom,
                )
        finally:
            stage.SetEditTarget(previous_target)

        await omni.kit.app.get_app().next_update_async()
        if status_callback:
            if matched_count:
                status_callback(f"View applied ({matched_count} prims).")
            else:
                status_callback("View skipped: no configured prims matched the stage.")
        return matched_count > 0

    async def apply_face_panel_state_in_kit(
        self,
        open_panel: bool,
        status_callback: StatusCallback | None = None,
    ) -> bool:
        """Animate the configured front panel hinge in the session layer."""

        face_panel = self.config.chassis_presentation.face_panel
        if not face_panel.enabled:
            if status_callback:
                status_callback("Front panel skipped: no hinge configured.")
            return False

        import omni.kit.app
        import omni.usd
        from pxr import Usd, UsdGeom

        stage = omni.usd.get_context().get_stage()
        if not stage:
            if status_callback:
                status_callback("Front panel skipped: no open stage.")
            return False

        result = self._prepare_face_panel_hinge(
            stage,
            face_panel,
            open_panel,
            Usd,
            UsdGeom,
        )
        if not result.success or result.rotate_op is None:
            if status_callback:
                status_callback(result.message)
            return False

        if status_callback:
            status_callback(
                "Opening front panel." if open_panel else "Closing front panel."
            )

        app = omni.kit.app.get_app()
        duration = max(0.0, float(face_panel.animation_duration_seconds))
        if duration <= 0.0 or abs(result.target_angle - result.start_angle) < 1e-6:
            self._set_face_panel_hinge_angle(
                stage, result.rotate_op, result.target_angle, Usd
            )
            await app.next_update_async()
        else:
            started_at = time.monotonic()
            while True:
                elapsed = time.monotonic() - started_at
                progress = min(1.0, elapsed / duration)
                eased = progress * progress * (3.0 - (2.0 * progress))
                angle = result.start_angle + (
                    (result.target_angle - result.start_angle) * eased
                )
                self._set_face_panel_hinge_angle(stage, result.rotate_op, angle, Usd)
                await app.next_update_async()
                if progress >= 1.0:
                    break
            self._set_face_panel_hinge_angle(
                stage, result.rotate_op, result.target_angle, Usd
            )

        if status_callback:
            status_callback(
                "Front panel opened." if open_panel else "Front panel closed."
            )
        return True

    def apply_qled_display_snapshot_in_kit(self, snapshot) -> bool:
        """Update the QLED display from the displayed telemetry snapshot."""

        qled = self.config.chassis_presentation.qled_display
        if not qled.enabled:
            return False
        metric = getattr(snapshot, "metrics", {}).get(qled.metric_id)
        if metric is None:
            return False

        import omni.usd
        from pxr import Gf, Sdf, Usd, UsdShade

        stage = omni.usd.get_context().get_stage()
        if not stage:
            return False

        return self._apply_qled_display_temperature(
            stage,
            qled,
            float(metric.value),
            Gf,
            Sdf,
            Usd,
            UsdShade,
        )

    def apply_front_panel_indicators_snapshot_in_kit(
        self,
        snapshot,
        now_seconds: float,
    ) -> bool:
        """Update front-panel LEDs from displayed telemetry metrics."""

        indicators = self.config.chassis_presentation.front_panel_indicators
        if not indicators.enabled:
            return False

        import omni.usd
        from pxr import Gf, Sdf, Usd, UsdShade

        stage = omni.usd.get_context().get_stage()
        if not stage:
            return False

        state = front_panel_indicator_state(
            snapshot.metrics,
            now_seconds,
            storage_metric_id=indicators.storage_metric_id,
            lan_01_metric_id=indicators.lan_01_metric_id,
            lan_02_metric_id=indicators.lan_02_metric_id,
        )
        state_key = (id(stage), state.power, state.hdd, state.lan_01, state.lan_02)
        if state_key == self._front_panel_indicator_state_key:
            return True
        self._front_panel_indicator_state_key = state_key
        return self._apply_front_panel_indicator_state(
            stage,
            indicators,
            state,
            Gf,
            Sdf,
            Usd,
            UsdShade,
        )

    async def attach_simulation_cache_in_kit(
        self,
        status_callback: StatusCallback | None = None,
    ) -> SimulationCacheResult:
        """Attach the configured cache through RTX / NVIDIA IndeX compositing."""

        cache = self.config.simulation_cache
        if not cache.enabled:
            return SimulationCacheResult(
                success=False,
                message="Airflow cache is disabled in the runtime config.",
            )

        if cache.runtime_mode == "kit_cae":
            return await self._attach_kit_cae_airflow_in_kit(status_callback)

        if status_callback:
            status_callback("Checking airflow cache")
        preflight = run_simulation_cache_preflight(
            self.config.simulation_cache_path,
            cache,
        )
        if not preflight.success or not preflight.contract:
            return SimulationCacheResult(False, preflight.format_summary())

        import omni.kit.app
        import omni.timeline
        import omni.usd

        extension_manager = omni.kit.app.get_app().get_extension_manager()
        if not extension_manager.is_extension_enabled("omni.rtx.index_composite"):
            return SimulationCacheResult(
                False,
                (
                    "Airflow cache is valid, but RTX / NVIDIA IndeX Compositing "
                    "is unavailable in this Kit build. Playback remains disabled."
                ),
            )

        import carb
        import omni.kit.viewport.utility as viewport_utility
        from pxr import Gf, Sdf, UsdGeom, UsdShade

        stage = omni.usd.get_context().get_stage()
        if not stage:
            return SimulationCacheResult(False, "Airflow cache skipped: no open stage.")

        # IndeX compositing is an RTX feature, not the standalone Scientific
        # renderer. Set it before the Volume enters the composed stage.
        self._enable_index_compositing(stage, cache, carb)
        viewport = viewport_utility.get_active_viewport()
        if viewport and hasattr(viewport, "set_hd_engine"):
            viewport.set_hd_engine("rtx")

        # Session-layer metrics give the cache its authored time domain without
        # modifying the referenced rig USD on disk.
        session_layer = stage.GetSessionLayer()
        session_layer.timeCodesPerSecond = preflight.contract.time_codes_per_second
        session_layer.framesPerSecond = preflight.contract.frames_per_second

        timeline = omni.timeline.get_timeline_interface()
        previous_target = stage.GetEditTarget()
        stage.SetEditTarget(stage.GetSessionLayer())
        try:
            self._author_airflow_cache_session_layer(
                stage,
                cache,
                preflight.contract,
                Gf,
                Sdf,
                UsdGeom,
                UsdShade,
            )
        finally:
            stage.SetEditTarget(previous_target)

        self._simulation_cache_contract = preflight.contract
        self._simulation_cache_time_code = int(preflight.contract.start_time_code)

        timeline.pause()
        timeline.set_current_time(
            preflight.contract.start_time_code
            / preflight.contract.time_codes_per_second
        )
        await omni.kit.app.get_app().next_update_async()
        timeline.play(
            preflight.contract.start_time_code,
            preflight.contract.end_time_code,
            True,
        )
        return SimulationCacheResult(
            True,
            "Airflow cache is playing through RTX / NVIDIA IndeX Compositing.",
        )

    async def _attach_kit_cae_airflow_in_kit(
        self,
        status_callback: StatusCallback | None = None,
    ) -> SimulationCacheResult:
        """Import one Houdini VTI velocity field and drive a Kit-CAE Flow probe."""

        cache = self.config.simulation_cache
        velocity_path = self.config.velocity_vti_path
        if not velocity_path.is_file():
            return SimulationCacheResult(
                False,
                f"Kit-CAE airflow VTI is missing: {velocity_path}",
            )
        if status_callback:
            status_callback("Importing Houdini velocity VTI through Kit-CAE")

        import carb
        import omni.kit.app
        import omni.timeline
        import omni.usd
        from omni.cae.data.commands import execute_command
        from omni.cae.importer.vtk import import_to_stage
        from omni.cae.schema import cae
        from omni.cae.schema import viz as cae_viz
        from omni.cae.schema import vtk as cae_vtk
        from pxr import Gf, Usd, UsdGeom

        extension_manager = omni.kit.app.get_app().get_extension_manager()
        required_extensions = (
            "omni.flowusd",
            "omni.cae.delegate.vtk",
            "omni.cae.importer.vtk",
            "omni.cae.viz",
        )
        disabled_extensions = [
            extension_id
            for extension_id in required_extensions
            if not extension_manager.is_extension_enabled(extension_id)
        ]
        if disabled_extensions:
            return SimulationCacheResult(
                False,
                "Kit-CAE airflow is unavailable; start BMS through start_bms.bat "
                f"with these extensions enabled: {', '.join(disabled_extensions)}.",
            )

        stage = omni.usd.get_context().get_stage()
        if not stage:
            return SimulationCacheResult(False, "Airflow cache skipped: no open stage.")

        # Kit-CAE's current VTK importer copies its result into the root layer.
        # The import destination itself must be top-level: Sdf.CopySpec does not
        # create its parent specs in that layer.
        runtime_root = "/BMS_KitCAE"
        import_root = "/BMS_HoudiniVelocity"
        dataset_path = f"{import_root}/VTKImageData"
        field_path = f"{import_root}/PointData/{cache.velocity_field_name}"
        bbox_path = f"{runtime_root}/BoundingBox"
        flow_environment_path = f"{runtime_root}/FlowSimulation"
        smoke_injector_path = f"{runtime_root}/SmokeInjector"
        boundary_emitter_path = f"{runtime_root}/BoundaryEmitter"
        dataset_emitter_path = f"{runtime_root}/DataSetEmitter"
        app = omni.kit.app.get_app()
        previous_target = stage.GetEditTarget()
        stage.SetEditTarget(stage.GetSessionLayer())
        try:
            if stage.GetPrimAtPath(runtime_root).IsValid():
                stage.RemovePrim(runtime_root)
            await import_to_stage(str(velocity_path), import_root)
            await app.next_update_async()

            metadata = self._read_kit_cae_vti_metadata(
                velocity_path,
                cache.velocity_field_name,
            )
            dataset_prim = stage.GetPrimAtPath(dataset_path)
            field_prim = stage.GetPrimAtPath(field_path)
            origin_after_import = self._read_kit_cae_vti_origin_opinion(
                dataset_prim,
                cae_vtk,
            )
            self._author_kit_cae_vti_origin_session_opinion(
                dataset_prim,
                metadata["vti_header_origin"],
                cae_vtk,
                Gf,
            )
            await app.next_update_async()
            imported_grid = self._validate_kit_cae_velocity_field(
                dataset_prim,
                field_prim,
                metadata,
                cae,
                cae_vtk,
            )

            if status_callback:
                status_callback("Creating Kit-CAE Flow environment")
            await execute_command(
                "CreateCaeVizBoundingBox",
                dataset_paths=[dataset_path],
                prim_path=bbox_path,
            )
            await app.next_update_async()
            self._author_kit_cae_spatial_sanity_wireframes(
                stage,
                imported_grid["world_bounds"],
                Gf,
                Usd,
                UsdGeom,
            )
            await app.next_update_async()
            origin_after_bms_composition = self._read_kit_cae_vti_origin_opinion(
                dataset_prim,
                cae_vtk,
            )
            await execute_command(
                "CreateCaeVizFlowEnvironment",
                prim_path=flow_environment_path,
                layer_number=0,
            )
            await app.next_update_async()
            flow_environment_prim = stage.GetPrimAtPath(flow_environment_path)
            await execute_command(
                "CreateCaeVizFlowSmokeInjector",
                boundable_paths=[bbox_path],
                prim_path=smoke_injector_path,
                layer_number=0,
                mode="sphere",
                simulation_prim=flow_environment_prim,
            )
            await app.next_update_async()
            self._position_kit_cae_smoke_probe_injector(
                stage,
                smoke_injector_path,
                metadata,
                Gf,
                UsdGeom,
            )
            self._hide_kit_cae_smoke_injector_mesh(
                stage,
                smoke_injector_path,
                UsdGeom,
            )
            await execute_command(
                "CreateCaeVizFlowBoundaryEmitter",
                boundable_paths=[bbox_path],
                prim_path=boundary_emitter_path,
                layer_number=0,
            )
            await app.next_update_async()
            await execute_command(
                "CreateCaeVizFlowDataSetEmitter",
                dataset_path=dataset_path,
                prim_path=dataset_emitter_path,
                layer_number=0,
                simulation_prim=flow_environment_prim,
            )
            emitter_prim = stage.GetPrimAtPath(dataset_emitter_path)
            if not emitter_prim.HasAPI(cae_viz.FieldSelectionAPI, "velocities"):
                raise RuntimeError(
                    "Kit-CAE DataSetEmitter has no velocities field selector."
                )
            emitter_operator = cae_viz.OperatorAPI(emitter_prim)
            emitter_operator.CreateEnabledAttr().Set(False)
            velocity_selector = cae_viz.FieldSelectionAPI(emitter_prim, "velocities")
            velocity_selector.CreateTargetRel().SetTargets([field_path])
            dav_origin_trace = await self._trace_kit_cae_dav_velocity_dataset(
                emitter_prim,
                Usd,
            )
            emitter_operator.CreateEnabledAttr().Set(True)
            operator_readiness = await self._wait_for_kit_cae_dataset_emitter_ready(
                app,
                emitter_prim,
            )
            self._configure_kit_cae_native_fuel_smoke_probe(
                stage,
                flow_environment_path,
            )
            timeline = omni.timeline.get_timeline_interface()
            timeline.pause()
            timeline.set_current_time(0.0)
            await self._pulse_kit_cae_flow_clear(app, flow_environment_path)
            self._clear_kit_cae_server_visibility_session_opinion(
                stage,
                UsdGeom,
            )

            await app.next_update_async()
            timeline.play()
            timeline_time_before = float(timeline.get_current_time())
            for _ in range(12):
                await app.next_update_async()
            timeline_time_after = float(timeline.get_current_time())
            self._log_kit_cae_render_probe(
                stage,
                flow_environment_path,
                "NATIVE_FUEL",
                carb,
            )
            self._log_kit_cae_origin_trace(
                metadata,
                origin_after_import,
                origin_after_bms_composition,
                dav_origin_trace,
                carb,
            )
            self._log_kit_cae_flow_full_diagnostics(
                stage,
                velocity_path,
                metadata,
                imported_grid,
                dataset_path,
                flow_environment_path,
                smoke_injector_path,
                boundary_emitter_path,
                dataset_emitter_path,
                bbox_path,
                field_path,
                velocity_selector,
                timeline,
                timeline_time_before,
                timeline_time_after,
                operator_readiness,
                "NATIVE_FUEL",
                Usd,
                UsdGeom,
                carb,
            )
            parity_snapshot_path = self._write_kit_cae_flow_parity_snapshot(
                stage,
                dataset_path=dataset_path,
                field_path=field_path,
                bbox_path=bbox_path,
                flow_environment_path=flow_environment_path,
                smoke_injector_path=smoke_injector_path,
                boundary_emitter_path=boundary_emitter_path,
                dataset_emitter_path=dataset_emitter_path,
            )
            carb.log_warn(f"BMS Kit-CAE parity snapshot saved: {parity_snapshot_path}")
        except Exception as error:
            carb.log_error(f"BMS Kit-CAE Flow probe failed: {error}")
            if stage.GetPrimAtPath(runtime_root).IsValid():
                stage.RemovePrim(runtime_root)
            if stage.GetPrimAtPath(import_root).IsValid():
                stage.RemovePrim(import_root)
            return SimulationCacheResult(False, f"Kit-CAE airflow failed: {error}")
        finally:
            stage.SetEditTarget(previous_target)

        self._simulation_cache_contract = None
        self._simulation_cache_time_code = None
        self._flow_airflow_simulate_path = f"{flow_environment_path}/flowSimulate"
        return SimulationCacheResult(
            True,
            "Kit-CAE Flow is running: "
            f"PointData/{cache.velocity_field_name} Vector3 drives live smoke.",
        )

    async def apply_kit_cae_flow_presentation_in_kit(
        self,
        attenuation: float,
        alpha_preset: str,
    ) -> SimulationCacheResult:
        """Apply a presentation-only Flow ray-march and colormap preset."""

        if not self._flow_airflow_simulate_path:
            return SimulationCacheResult(
                False, "Attach the airflow cache before tuning Flow."
            )

        import carb
        import omni.kit.app
        import omni.usd
        from pxr import Gf, UsdGeom

        stage = omni.usd.get_context().get_stage()
        if not stage:
            return SimulationCacheResult(False, "Flow tuning skipped: no open stage.")

        flow_environment_path = self._flow_airflow_simulate_path.removesuffix(
            "/flowSimulate"
        )
        smoke_injector_path = "/BMS_KitCAE/SmokeInjector"
        previous_target = stage.GetEditTarget()
        stage.SetEditTarget(stage.GetSessionLayer())
        try:
            alpha_values = self._author_kit_cae_flow_presentation(
                stage,
                flow_environment_path,
                smoke_injector_path,
                attenuation,
                alpha_preset,
                Gf,
                UsdGeom,
            )
        except (RuntimeError, ValueError) as error:
            return SimulationCacheResult(False, f"Flow presentation failed: {error}")
        finally:
            stage.SetEditTarget(previous_target)

        app = omni.kit.app.get_app()
        for _ in range(3):
            await app.next_update_async()

        server_prim = stage.GetPrimAtPath(RuntimeController.KIT_CAE_SERVER_ROOT)
        injector_mesh = stage.GetPrimAtPath(smoke_injector_path)
        server_visible = (
            UsdGeom.Imageable(server_prim).ComputeVisibility()
            != UsdGeom.Tokens.invisible
            if server_prim and server_prim.IsValid()
            else None
        )
        injector_mesh_visible = (
            UsdGeom.Imageable(injector_mesh).ComputeVisibility()
            != UsdGeom.Tokens.invisible
            if injector_mesh and injector_mesh.IsValid()
            else None
        )
        carb.log_warn(
            "BMS Kit-CAE Flow presentation: "
            f"attenuation={attenuation:g}, alpha_preset={alpha_preset}, "
            f"rgba_alphas={alpha_values}, server_visible={server_visible}, "
            f"smoke_injector_mesh_visible={injector_mesh_visible}"
        )

        return SimulationCacheResult(
            True,
            "Flow presentation applied: "
            f"attenuation={attenuation:g}, {alpha_preset} opacity "
            f"{tuple(round(value, 2) for value in alpha_values)}.",
        )

    def play_simulation_cache_in_kit(self) -> SimulationCacheResult:
        """Play the attached cache over its authored frame range."""

        if self._flow_airflow_simulate_path:
            import omni.timeline

            omni.timeline.get_timeline_interface().play()
            return SimulationCacheResult(True, "Kit-CAE velocity-driven Flow started.")

        if not self._simulation_cache_contract:
            return SimulationCacheResult(
                False, "Attach the airflow cache before playback."
            )

        import omni.timeline

        contract = self._simulation_cache_contract
        timeline = omni.timeline.get_timeline_interface()
        timeline.play(
            contract.start_time_code,
            contract.end_time_code,
            True,
        )
        return SimulationCacheResult(True, "Airflow cache playback started.")

    def pause_simulation_cache_in_kit(self) -> SimulationCacheResult:
        """Pause the attached cache at the current frame."""

        if self._flow_airflow_simulate_path:
            import omni.timeline

            omni.timeline.get_timeline_interface().pause()
            return SimulationCacheResult(True, "Kit-CAE velocity-driven Flow paused.")

        if not self._simulation_cache_contract:
            return SimulationCacheResult(
                False, "Attach the airflow cache before playback."
            )

        import omni.timeline

        omni.timeline.get_timeline_interface().pause()
        return SimulationCacheResult(True, "Airflow cache paused.")

    def reset_simulation_cache_in_kit(self) -> SimulationCacheResult:
        """Return the attached cache to its first authored frame."""

        if self._flow_airflow_simulate_path:
            import omni.timeline
            import omni.usd

            stage = omni.usd.get_context().get_stage()
            simulate = (
                stage.GetPrimAtPath(self._flow_airflow_simulate_path) if stage else None
            )
            if not simulate or not simulate.IsValid():
                return SimulationCacheResult(
                    False, "Flow airflow is no longer attached."
                )
            force_clear = simulate.GetAttribute("forceClear")
            force_clear.Set(True)
            asyncio.ensure_future(self._clear_flow_after_update(force_clear))
            timeline = omni.timeline.get_timeline_interface()
            timeline.pause()
            timeline.set_current_time(0.0)
            return SimulationCacheResult(True, "Kit-CAE velocity-driven Flow reset.")

        if not self._simulation_cache_contract:
            return SimulationCacheResult(
                False, "Attach the airflow cache before playback."
            )

        import omni.timeline

        contract = self._simulation_cache_contract
        timeline = omni.timeline.get_timeline_interface()
        timeline.pause()
        timeline.set_current_time(
            contract.start_time_code / contract.time_codes_per_second
        )
        return SimulationCacheResult(True, "Airflow cache reset to its first frame.")

    def capture_gpu_profile_in_kit(self) -> SimulationCacheResult:
        """Write the current Hydra GPU profiler sample to an ignored artifact."""

        import carb
        import omni.hydra.engine.stats as engine_stats
        import omni.kit.viewport.utility as viewport_utility

        viewport = viewport_utility.get_active_viewport()
        if not viewport:
            return SimulationCacheResult(
                False, "GPU profile skipped: no active viewport."
            )

        output_dir = self.config.repo_root / "out" / "diagnostics"
        output_dir.mkdir(parents=True, exist_ok=True)
        carb.settings.get_settings().set("/profiler/filePath", str(output_dir))

        profiler = engine_stats.HydraEngineStats(
            hydra_engine_name=viewport.hydra_engine,
        )
        profile_path = self._write_gpu_profile(
            output_dir,
            viewport.hydra_engine,
            profiler.get_gpu_profiler_result(),
        )
        carb.log_info(f"BMS GPU profile saved: {profile_path}")

        return SimulationCacheResult(
            True,
            f"GPU profile saved: {profile_path}",
        )

    @staticmethod
    def _write_gpu_profile(
        output_dir: Path,
        hydra_engine: str,
        gpu_profiler_result,
    ) -> Path:
        """Serialize profiler data because Kit's save helper is unreliable."""

        output_dir.mkdir(parents=True, exist_ok=True)
        profile_path = (
            output_dir / f"airflow_gpu_profile_{int(time.time() * 1000)}.json"
        )
        payload = {
            "hydra_engine": hydra_engine,
            "gpu_profiler": gpu_profiler_result,
        }
        profile_path.write_text(
            json.dumps(payload, indent=2, default=str),
            encoding="utf-8",
        )
        return profile_path

    def _write_kit_cae_flow_parity_snapshot(
        self,
        stage,
        *,
        dataset_path: str,
        field_path: str,
        bbox_path: str,
        flow_environment_path: str,
        smoke_injector_path: str,
        boundary_emitter_path: str,
        dataset_emitter_path: str,
    ) -> Path:
        """Persist a read-only effective-state snapshot for the Flow parity audit."""

        snapshot = capture_flow_scene(
            stage,
            label="BMS_CASE03_VTI_FLOW",
            paths={
                "dataset": dataset_path,
                "velocity_field": field_path,
                "bounding_box": bbox_path,
                "flow_environment": flow_environment_path,
                "flow_simulate": f"{flow_environment_path}/flowSimulate",
                "flow_offscreen": f"{flow_environment_path}/flowOffscreen",
                "flow_render": f"{flow_environment_path}/flowRender",
                "ray_march": f"{flow_environment_path}/flowRender/rayMarch",
                "debug_volume": f"{flow_environment_path}/flowOffscreen/debugVolume",
                "smoke_injector": smoke_injector_path,
                "smoke_emitter": f"{smoke_injector_path}/EmitterSphere",
                "boundary_emitter_root": boundary_emitter_path,
                "dataset_emitter": dataset_emitter_path,
            },
        )
        return write_flow_snapshot(
            snapshot,
            self.config.repo_root
            / "out"
            / "diagnostics"
            / "kit_cae_flow_snapshot_bms.json",
        )

    def sync_simulation_cache_frame_in_kit(self) -> bool:
        """Native USD volume playback follows the Kit timeline automatically."""

        return False

    def detach_simulation_cache_in_kit(self) -> SimulationCacheResult:
        """Remove only the transient cache opinions from the session layer."""

        import omni.timeline
        import omni.usd

        stage = omni.usd.get_context().get_stage()
        if not stage:
            return SimulationCacheResult(False, "Airflow cache skipped: no open stage.")

        previous_target = stage.GetEditTarget()
        stage.SetEditTarget(stage.GetSessionLayer())
        try:
            stage.RemovePrim("/BMS_Runtime/Airflow")
            stage.RemovePrim("/BMS_Runtime/Looks/AirflowIndex")
            stage.RemovePrim("/BMS_Runtime/Flow")
            stage.RemovePrim("/BMS_KitCAE")
            stage.RemovePrim("/BMS_HoudiniVelocity")
        finally:
            stage.SetEditTarget(previous_target)
        omni.timeline.get_timeline_interface().pause()
        self._simulation_cache_contract = None
        self._simulation_cache_time_code = None
        self._flow_airflow_simulate_path = None
        return SimulationCacheResult(
            True,
            "Airflow cache detached from the session layer.",
        )

    @staticmethod
    async def _clear_flow_after_update(force_clear) -> None:
        """Pulse Flow's clear switch for one update instead of freezing simulation."""

        import omni.kit.app

        await omni.kit.app.get_app().next_update_async()
        force_clear.Set(False)

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
    def _read_kit_cae_vti_metadata(
        velocity_path: Path,
        field_name: str,
    ) -> dict[str, object]:
        """Read the VTI header through Kit-CAE's VTK runtime before Flow binds it."""

        from vtkmodules.vtkIOXML import vtkXMLImageDataReader

        header = velocity_path.read_bytes()[:16384].decode("utf-8", errors="ignore")
        header_match = re.search(r'<ImageData[^>]*\bOrigin="([^"]+)"', header)
        if header_match is None:
            raise RuntimeError("VTI ImageData header is missing its Origin attribute.")
        header_origin = tuple(float(value) for value in header_match.group(1).split())
        if len(header_origin) != 3:
            raise RuntimeError(
                "VTI ImageData header Origin must have three components."
            )

        reader = vtkXMLImageDataReader()
        reader.SetFileName(str(velocity_path))
        reader.Update()
        image = reader.GetOutput()
        array = image.GetPointData().GetArray(field_name) if image else None
        if array is None:
            raise RuntimeError(f"VTI PointData array '{field_name}' was not found.")
        components = int(array.GetNumberOfComponents())
        data_type = str(array.GetDataTypeAsString()).lower()
        if components != 3:
            raise RuntimeError(
                f"VTI PointData/{field_name} must have 3 components, got {components}."
            )
        if data_type not in {"float", "float32"}:
            raise RuntimeError(
                f"VTI PointData/{field_name} must be float32, got {data_type}."
            )
        reader_origin = tuple(float(value) for value in image.GetOrigin())
        return {
            "components": components,
            "data_type": data_type,
            "dimensions": tuple(int(value) for value in image.GetDimensions()),
            "point_count": int(image.GetNumberOfPoints()),
            "origin": reader_origin,
            "vti_header_origin": header_origin,
            "vtk_reader_origin": reader_origin,
            "spacing": tuple(float(value) for value in image.GetSpacing()),
        }

    @staticmethod
    async def _wait_for_kit_cae_dataset_emitter_ready(
        app,
        dataset_emitter,
        *,
        timeout_seconds: float = 5.0,
        max_update_cycles: int = 300,
    ) -> dict[str, object]:
        """Wait for Kit-CAE to materialize its internal Flow velocity payload."""

        started_at = time.monotonic()
        cycles = 0

        def readiness() -> tuple[bool, int, float]:
            payload_attribute = dataset_emitter.GetAttribute("nanoVdbVelocities")
            payload = (
                payload_attribute.Get()
                if payload_attribute and payload_attribute.IsValid()
                else None
            )
            payload_count = len(payload) if payload is not None else 0
            couple_rate = dataset_emitter.GetAttribute("coupleRateVelocity")
            couple_rate_raw = (
                couple_rate.Get() if couple_rate and couple_rate.IsValid() else None
            )
            couple_rate_value = (
                float(couple_rate_raw) if couple_rate_raw is not None else 0.0
            )
            return (
                payload_count > 0 and couple_rate_value > 0.0,
                payload_count,
                couple_rate_value,
            )

        ready, payload_count, couple_rate_value = readiness()
        while (
            not ready
            and cycles < max_update_cycles
            and time.monotonic() - started_at < timeout_seconds
        ):
            await app.next_update_async()
            cycles += 1
            ready, payload_count, couple_rate_value = readiness()

        waited_seconds = time.monotonic() - started_at
        return {
            "ready": ready,
            "cycles": cycles,
            "seconds": waited_seconds,
            "timed_out": not ready,
            "payload_count": payload_count,
            "couple_rate_velocity": couple_rate_value,
        }

    @staticmethod
    async def _trace_kit_cae_dav_velocity_dataset(
        dataset_emitter, Usd
    ) -> dict[str, object]:
        """Read the exact CAE source dataset consumed by FlowNanoVDBEmitter."""

        from omni.cae.viz import utils as cae_viz_utils

        source_dataset = await cae_viz_utils.get_input_dataset(
            dataset_emitter,
            "source",
            timeCode=Usd.TimeCode.Default(),
            device="cuda:0",
        )
        bounds_min, bounds_max = source_dataset.get_bounds()
        velocity_field = source_dataset.get_field("velocities")
        velocity_volume = velocity_field.get_data()
        return {
            "bounds": (
                tuple(float(value) for value in bounds_min),
                tuple(float(value) for value in bounds_max),
            ),
            "origin": tuple(float(value) for value in bounds_min),
            "voxel_size": tuple(
                float(value) for value in velocity_volume.get_voxel_size()
            ),
        }

    @staticmethod
    def _position_kit_cae_smoke_probe_injector(
        stage,
        smoke_injector_path: str,
        metadata: dict[str, object],
        Gf,
        UsdGeom,
    ) -> None:
        """Move the diagnostic injector toward the server front without resizing it."""

        injector = stage.GetPrimAtPath(smoke_injector_path)
        if not injector or not injector.IsValid():
            raise RuntimeError("Kit-CAE did not create the smoke probe injector.")

        xformable = UsdGeom.Xformable(injector)
        translate_op = next(
            (
                op
                for op in xformable.GetOrderedXformOps()
                if op.GetOpType() == UsdGeom.XformOp.TypeTranslate
            ),
            None,
        )
        if translate_op is None:
            raise RuntimeError(
                "Kit-CAE smoke probe injector is missing a translate op."
            )

        position = translate_op.Get()
        origin = metadata["vti_header_origin"]
        spacing = metadata["spacing"]
        dimensions = metadata["dimensions"]
        domain_z_max = origin[2] + (dimensions[2] - 1) * spacing[2]
        target_z = domain_z_max - (domain_z_max - origin[2]) * 0.25
        translate_op.Set(Gf.Vec3d(position[0], position[1], target_z))

    @staticmethod
    def _configure_kit_cae_native_fuel_smoke_probe(
        stage,
        flow_environment_path: str,
    ) -> None:
        """Return Flow rendering to the stock fuel-to-smoke path."""

        flow_environment = stage.GetPrimAtPath(flow_environment_path)
        offscreen = flow_environment.GetChild("flowOffscreen")
        render = flow_environment.GetChild("flowRender")
        debug_volume = offscreen.GetChild("debugVolume") if offscreen else None
        ray_march = render.GetChild("rayMarch") if render else None
        required_attributes = (
            (debug_volume, "enableVelocityAsDensity"),
            (ray_march, "enableRawMode"),
        )
        for prim, attribute_name in required_attributes:
            attribute = prim.GetAttribute(attribute_name) if prim else None
            if not attribute or not attribute.IsValid():
                prim_path = prim.GetPath() if prim else flow_environment_path
                raise RuntimeError(
                    "Kit-CAE Flow render probe is missing "
                    f"{prim_path}.{attribute_name}."
                )

        debug_volume.GetAttribute("enableVelocityAsDensity").Set(False)
        ray_march.GetAttribute("enableRawMode").Set(False)

    @classmethod
    def _author_kit_cae_flow_presentation(
        cls,
        stage,
        flow_environment_path: str,
        smoke_injector_path: str,
        attenuation: float,
        alpha_preset: str,
        Gf,
        UsdGeom,
    ) -> tuple[float, float, float]:
        """Author a render-only visibility preset without changing Flow physics."""

        if attenuation <= 0:
            raise ValueError("Flow attenuation must be greater than zero.")
        alpha_values = cls.KIT_CAE_FLOW_ALPHA_PRESETS.get(alpha_preset)
        if alpha_values is None:
            raise ValueError(f"Unknown Flow opacity preset: {alpha_preset}.")

        flow_environment = stage.GetPrimAtPath(flow_environment_path)
        flow_render = (
            flow_environment.GetChild("flowRender") if flow_environment else None
        )
        flow_offscreen = (
            flow_environment.GetChild("flowOffscreen") if flow_environment else None
        )
        ray_march = flow_render.GetChild("rayMarch") if flow_render else None
        colormap = flow_offscreen.GetChild("colormap") if flow_offscreen else None
        attenuation_attr = ray_march.GetAttribute("attenuation") if ray_march else None
        rgba_points_attr = colormap.GetAttribute("rgbaPoints") if colormap else None
        if not attenuation_attr or not attenuation_attr.IsValid():
            raise RuntimeError("Kit-CAE Flow ray march is missing attenuation.")
        if not rgba_points_attr or not rgba_points_attr.IsValid():
            raise RuntimeError("Kit-CAE Flow colormap is missing rgbaPoints.")

        rgba_points = rgba_points_attr.Get()
        if rgba_points is None or len(rgba_points) != len(alpha_values):
            raise RuntimeError(
                "Kit-CAE Flow colormap does not expose three RGBA points."
            )
        attenuation_attr.Set(float(attenuation))
        rgba_points_attr.Set(
            [
                Gf.Vec4f(point[0], point[1], point[2], alpha_values[index])
                for index, point in enumerate(rgba_points)
            ]
        )
        cls._hide_kit_cae_smoke_injector_mesh(
            stage,
            smoke_injector_path,
            UsdGeom,
        )
        return alpha_values

    @staticmethod
    def _hide_kit_cae_smoke_injector_mesh(
        stage,
        smoke_injector_path: str,
        UsdGeom,
    ) -> None:
        """Hide only the injector's diagnostic mesh; Flow data remain on its child."""

        injector_mesh = stage.GetPrimAtPath(smoke_injector_path)
        if not injector_mesh or not injector_mesh.IsA(UsdGeom.Mesh):
            raise RuntimeError("Kit-CAE smoke injector mesh is unavailable.")
        UsdGeom.Imageable(injector_mesh).CreateVisibilityAttr().Set(
            UsdGeom.Tokens.invisible
        )

    @classmethod
    def _clear_kit_cae_server_visibility_session_opinion(cls, stage, UsdGeom) -> bool:
        """Remove a leftover diagnostic visibility override from the server root."""

        server_prim = stage.GetPrimAtPath(cls.KIT_CAE_SERVER_ROOT)
        if not server_prim or not server_prim.IsValid():
            return False
        UsdGeom.Imageable(server_prim).GetVisibilityAttr().Clear()
        return True

    @staticmethod
    async def _pulse_kit_cae_flow_clear(app, flow_environment_path: str) -> None:
        """Clear prior density before the one-phase native fuel control run."""

        import omni.usd

        stage = omni.usd.get_context().get_stage()
        flow_environment = stage.GetPrimAtPath(flow_environment_path) if stage else None
        simulate = (
            flow_environment.GetChild("flowSimulate") if flow_environment else None
        )
        force_clear = simulate.GetAttribute("forceClear") if simulate else None
        if not force_clear or not force_clear.IsValid():
            raise RuntimeError(
                "Kit-CAE Flow native fuel probe is missing flowSimulate.forceClear."
            )
        force_clear.Set(True)
        await app.next_update_async()
        force_clear.Set(False)
        await app.next_update_async()

    @staticmethod
    def _log_kit_cae_render_probe(
        stage,
        flow_environment_path: str,
        smoke_probe_phase: str,
        carb,
    ) -> None:
        """Report the active Flow render mode after the control run settles."""

        flow_environment = stage.GetPrimAtPath(flow_environment_path)
        simulate = (
            flow_environment.GetChild("flowSimulate") if flow_environment else None
        )
        offscreen = (
            flow_environment.GetChild("flowOffscreen") if flow_environment else None
        )
        render = flow_environment.GetChild("flowRender") if flow_environment else None
        debug_volume = offscreen.GetChild("debugVolume") if offscreen else None
        ray_march = render.GetChild("rayMarch") if render else None

        def attr_value(prim, name: str):
            attribute = prim.GetAttribute(name) if prim else None
            return attribute.Get() if attribute and attribute.IsValid() else None

        diagnostics = {
            "smoke_probe_phase": smoke_probe_phase,
            "debug_volume_present": bool(debug_volume and debug_volume.IsValid()),
            "enableVelocityAsDensity": attr_value(
                debug_volume,
                "enableVelocityAsDensity",
            ),
            "debug_velocityScale": attr_value(debug_volume, "velocityScale"),
            "rayMarch_enableRawMode": attr_value(ray_march, "enableRawMode"),
            "rayMarch_enableBlockWireframe": attr_value(
                ray_march,
                "enableBlockWireframe",
            ),
            "rayMarch_attenuation": attr_value(ray_march, "attenuation"),
            "flow_offscreen_layer": attr_value(offscreen, "layer"),
            "flow_render_layer": attr_value(render, "layer"),
            "flow_simulate_layer": attr_value(simulate, "layer"),
        }
        details = ", ".join(f"{key}={value}" for key, value in diagnostics.items())
        carb.log_warn(f"BMS Kit-CAE render probe: {details}")

    @staticmethod
    def _log_kit_cae_origin_trace(
        metadata: dict[str, object],
        origin_after_import: dict[str, object],
        origin_after_bms_composition: dict[str, object],
        dav_origin_trace: dict[str, object],
        carb,
    ) -> None:
        """Log the origin handoff from VTI bytes through DAV's Flow input."""

        diagnostics = {
            "raw_vti_header_origin": metadata["vti_header_origin"],
            "vtkXMLImageDataReader_output_origin": metadata["vtk_reader_origin"],
            "ImageDataAPI_origin_after_import": origin_after_import["origin"],
            "ImageDataAPI_origin_after_bms_composition": (
                origin_after_bms_composition["origin"]
            ),
            "composed_usd_origin": origin_after_bms_composition["origin"],
            "ImageDataAPI_origin_property_stack": (
                origin_after_bms_composition["property_stack"]
            ),
            "dav_dataset_origin_before_FlowNanoVDBEmitter": (
                dav_origin_trace["origin"]
            ),
            "dav_dataset_bounds_before_FlowNanoVDBEmitter": (
                dav_origin_trace["bounds"]
            ),
            "dav_velocity_voxel_size_before_FlowNanoVDBEmitter": (
                dav_origin_trace["voxel_size"]
            ),
        }
        details = ", ".join(f"{key}={value}" for key, value in diagnostics.items())
        carb.log_warn(f"BMS Kit-CAE origin trace: {details}")

    @staticmethod
    def _log_kit_cae_flow_full_diagnostics(
        stage,
        velocity_path: Path,
        metadata: dict[str, object],
        imported_grid: dict[str, object],
        dataset_path: str,
        flow_environment_path: str,
        smoke_injector_path: str,
        boundary_emitter_path: str,
        dataset_emitter_path: str,
        bbox_path: str,
        field_path: str,
        velocity_selector,
        timeline,
        timeline_time_before: float,
        timeline_time_after: float,
        operator_readiness: dict[str, object],
        smoke_probe_phase: str,
        Usd,
        UsdGeom,
        carb,
    ) -> None:
        """Report one post-settle checkpoint for the VTI -> Kit-CAE -> Flow route."""

        dimensions = metadata["dimensions"]
        vti_header_origin = metadata["vti_header_origin"]
        vti_header_spacing = metadata["spacing"]
        vti_header_max = tuple(
            vti_header_origin[index]
            + (dimensions[index] - 1) * vti_header_spacing[index]
            for index in range(3)
        )
        bbox_cache = UsdGeom.BBoxCache(
            Usd.TimeCode.Default(),
            [UsdGeom.Tokens.default_, UsdGeom.Tokens.render, UsdGeom.Tokens.proxy],
        )

        def world_bounds(
            path: str,
        ) -> tuple[tuple[float, float, float], tuple[float, float, float]] | None:
            prim = stage.GetPrimAtPath(path)
            if not prim or not prim.IsValid():
                return None
            bounds = bbox_cache.ComputeWorldBound(prim).ComputeAlignedRange()
            if bounds.IsEmpty():
                return None
            return tuple(bounds.GetMin()), tuple(bounds.GetMax())

        def attr_value(prim, name: str):
            if not prim or not prim.IsValid():
                return None
            attribute = prim.GetAttribute(name)
            return attribute.Get() if attribute and attribute.IsValid() else None

        def relationship_targets(prim, name: str) -> list[str]:
            if not prim or not prim.IsValid():
                return []
            relationship = prim.GetRelationship(name)
            if not relationship or not relationship.IsValid():
                return []
            return [str(path) for path in relationship.GetTargets()]

        def array_count(prim, name: str) -> int | None:
            value = attr_value(prim, name)
            return len(value) if value is not None else None

        dataset_prim = stage.GetPrimAtPath(dataset_path)
        field_prim = stage.GetPrimAtPath(field_path)
        flow_environment = stage.GetPrimAtPath(flow_environment_path)
        flow_simulate = (
            flow_environment.GetChild("flowSimulate") if flow_environment else None
        )
        flow_offscreen = (
            flow_environment.GetChild("flowOffscreen") if flow_environment else None
        )
        flow_render = (
            flow_environment.GetChild("flowRender") if flow_environment else None
        )
        flow_colormap = flow_offscreen.GetChild("colormap") if flow_offscreen else None
        dataset_emitter = stage.GetPrimAtPath(dataset_emitter_path)
        smoke_injector = stage.GetPrimAtPath(smoke_injector_path)
        smoke_emitter = (
            smoke_injector.GetChild("EmitterSphere") if smoke_injector else None
        )
        smoke_position = None
        smoke_local_scale = None
        if smoke_injector and smoke_injector.IsValid():
            injector_xform = UsdGeom.Xformable(smoke_injector)
            smoke_position = tuple(
                injector_xform.ComputeLocalToWorldTransform(
                    Usd.TimeCode.Default()
                ).ExtractTranslation()
            )
            scale_op = next(
                (
                    op
                    for op in injector_xform.GetOrderedXformOps()
                    if op.GetOpType() == UsdGeom.XformOp.TypeScale
                ),
                None,
            )
            smoke_local_scale = (
                tuple(scale_op.Get())
                if scale_op and scale_op.Get() is not None
                else None
            )

        bbox_world_bounds = world_bounds(bbox_path)
        colormap_rgba_points = attr_value(flow_colormap, "rgbaPoints")
        colormap_alpha_values = (
            tuple(float(point[3]) for point in colormap_rgba_points)
            if colormap_rgba_points is not None
            else None
        )
        smoke_injector_mesh_visible = (
            UsdGeom.Imageable(smoke_injector).ComputeVisibility()
            != UsdGeom.Tokens.invisible
            if smoke_injector and smoke_injector.IsValid()
            else None
        )
        server_prim = stage.GetPrimAtPath(RuntimeController.KIT_CAE_SERVER_ROOT)
        server_visible = (
            UsdGeom.Imageable(server_prim).ComputeVisibility()
            != UsdGeom.Tokens.invisible
            if server_prim and server_prim.IsValid()
            else None
        )
        smoke_radius = attr_value(smoke_emitter, "radius")
        radius_is_world_space = attr_value(smoke_emitter, "radiusIsWorldSpace")
        world_radius = None
        if smoke_radius is not None:
            world_radius = (
                float(smoke_radius)
                if radius_is_world_space
                else float(smoke_radius) * max(smoke_local_scale or (1.0,))
            )
        injector_inside_bounds = bool(
            smoke_position is not None
            and world_radius is not None
            and bbox_world_bounds is not None
            and all(
                bbox_world_bounds[0][index] <= smoke_position[index] - world_radius
                and smoke_position[index] + world_radius <= bbox_world_bounds[1][index]
                for index in range(3)
            )
        )

        boundary_root = stage.GetPrimAtPath(boundary_emitter_path)
        boundary_emitters = (
            [
                prim
                for prim in Usd.PrimRange(boundary_root)
                if prim.GetTypeName() == "FlowEmitterBox"
            ]
            if boundary_root and boundary_root.IsValid()
            else []
        )
        target_paths = [
            str(path) for path in velocity_selector.GetTargetRel().GetTargets()
        ]
        advection = flow_simulate.GetChild("advection") if flow_simulate else None
        ray_march = flow_render.GetChild("rayMarch") if flow_render else None
        data_set_bbox_match = bbox_world_bounds is not None and all(
            abs(
                bbox_world_bounds[bound][axis]
                - imported_grid["world_bounds"][bound][axis]
            )
            < 1e-5
            for bound in range(2)
            for axis in range(3)
        )
        diagnostics = [
            ("active_route", "VTI_KIT_CAE_FLOW"),
            ("vti_asset_path", velocity_path),
            ("dataset_path", dataset_path),
            ("dataset_prim_type", dataset_prim.GetTypeName()),
            ("velocity_field_path", field_path),
            ("velocity_field_association", attr_value(field_prim, "fieldAssociation")),
            ("velocity_field_components", metadata["components"]),
            ("velocity_field_dtype", metadata["data_type"]),
            ("vti_header_origin", vti_header_origin),
            ("vti_header_spacing", vti_header_spacing),
            ("usd_imagedata_origin", imported_grid["origin"]),
            ("vti_world_bounds", (vti_header_origin, vti_header_max)),
            ("dataset_world_bounds", imported_grid["world_bounds"]),
            ("kit_cae_imported_spacing", imported_grid["spacing"]),
            ("vti_dimensions", dimensions),
            ("server_bounds", world_bounds("/blackwell_rig")),
            ("bbox_world_bounds", bbox_world_bounds),
            ("flow_world_bounds", bbox_world_bounds),
            ("dataset_bbox_bounds_match", data_set_bbox_match),
            ("flow_environment_path", flow_environment_path),
            ("flow_simulate_path", flow_simulate.GetPath() if flow_simulate else None),
            ("flow_simulate_layer", attr_value(flow_simulate, "layer")),
            ("densityCellSize", attr_value(flow_simulate, "densityCellSize")),
            ("forceDisableEmitters", attr_value(flow_simulate, "forceDisableEmitters")),
            (
                "forceDisableCoreSimulation",
                attr_value(flow_simulate, "forceDisableCoreSimulation"),
            ),
            ("forceClear", attr_value(flow_simulate, "forceClear")),
            ("forceSimulate", attr_value(flow_simulate, "forceSimulate")),
            ("flow_offscreen_layer", attr_value(flow_offscreen, "layer")),
            ("flow_render_layer", attr_value(flow_render, "layer")),
            ("buoyancyPerTemp", attr_value(advection, "buoyancyPerTemp")),
            ("burnPerTemp", attr_value(advection, "burnPerTemp")),
            ("fuelPerBurn", attr_value(advection, "fuelPerBurn")),
            ("ignitionTemp", attr_value(advection, "ignitionTemp")),
            ("rayMarch_attenuation", attr_value(ray_march, "attenuation")),
            ("rayMarch_colormap_alphas", colormap_alpha_values),
            ("dataset_emitter_path", dataset_emitter_path),
            (
                "dataset_emitter_prim_type",
                dataset_emitter.GetTypeName() if dataset_emitter else None,
            ),
            ("dataset_emitter_layer", attr_value(dataset_emitter, "layer")),
            (
                "operator_enabled",
                attr_value(dataset_emitter, "cae:viz:operator:enabled"),
            ),
            (
                "source_targets",
                relationship_targets(
                    dataset_emitter,
                    "cae:viz:dataset_selection:source:target",
                ),
            ),
            ("velocity_targets", target_paths),
            (
                "rescaleMode",
                attr_value(
                    dataset_emitter,
                    "cae:viz:configure_flow_environment:source:rescaleMode",
                ),
            ),
            (
                "densityCellSizeIncludes",
                relationship_targets(
                    dataset_emitter,
                    "cae:viz:configure_flow_environment:source:densityCellSizeIncludes",
                ),
            ),
            (
                "nanoVdbVelocities_present",
                attr_value(dataset_emitter, "nanoVdbVelocities") is not None,
            ),
            (
                "nanoVdbVelocities_type",
                (
                    dataset_emitter.GetAttribute("nanoVdbVelocities").GetTypeName()
                    if dataset_emitter
                    and dataset_emitter.GetAttribute("nanoVdbVelocities")
                    else None
                ),
            ),
            (
                "nanoVdbVelocities_uint_count",
                array_count(dataset_emitter, "nanoVdbVelocities"),
            ),
            ("velocityScale", attr_value(dataset_emitter, "velocityScale")),
            (
                "coupleRateVelocity",
                attr_value(dataset_emitter, "coupleRateVelocity"),
            ),
            ("operator_ready", operator_readiness["ready"]),
            ("operator_wait_cycles", operator_readiness["cycles"]),
            ("operator_wait_seconds", f"{operator_readiness['seconds']:.3f}"),
            ("operator_wait_timed_out", operator_readiness["timed_out"]),
            ("allocationScale", attr_value(dataset_emitter, "allocationScale")),
            ("applyPostPressure", attr_value(dataset_emitter, "applyPostPressure")),
            ("smoke_injector_path", smoke_injector_path),
            (
                "smoke_emitter_path",
                smoke_emitter.GetPath() if smoke_emitter else None,
            ),
            (
                "smoke_emitter_prim_type",
                smoke_emitter.GetTypeName() if smoke_emitter else None,
            ),
            ("smoke_probe_phase", smoke_probe_phase),
            ("server_visible", server_visible),
            ("smoke_injector_mesh_visible", smoke_injector_mesh_visible),
            ("smoke_emitter_enabled", attr_value(smoke_emitter, "enabled")),
            (
                "smoke_emitter_allocationScale",
                attr_value(smoke_emitter, "allocationScale"),
            ),
            ("smoke_injector_local_scale", smoke_local_scale),
            ("smoke_injector_world_scale", smoke_local_scale),
            ("emitter_position", smoke_position),
            ("emitter_layer", attr_value(smoke_emitter, "layer")),
            ("radius", smoke_radius),
            ("radiusIsWorldSpace", radius_is_world_space),
            ("smoke", attr_value(smoke_emitter, "smoke")),
            ("coupleRateSmoke", attr_value(smoke_emitter, "coupleRateSmoke")),
            ("burn", attr_value(smoke_emitter, "burn")),
            ("coupleRateBurn", attr_value(smoke_emitter, "coupleRateBurn")),
            ("fuel", attr_value(smoke_emitter, "fuel")),
            ("coupleRateFuel", attr_value(smoke_emitter, "coupleRateFuel")),
            ("temperature", attr_value(smoke_emitter, "temperature")),
            (
                "coupleRateTemperature",
                attr_value(smoke_emitter, "coupleRateTemperature"),
            ),
            (
                "smoke_emitter_coupleRateVelocity",
                attr_value(smoke_emitter, "coupleRateVelocity"),
            ),
            ("injector_inside_flow_bounds", injector_inside_bounds),
            ("boundary_emitter_path", boundary_emitter_path),
            ("boundary_emitter_count", len(boundary_emitters)),
            (
                "boundary_layers",
                [attr_value(prim, "layer") for prim in boundary_emitters],
            ),
            (
                "all_boundary_emitters_valid",
                len(boundary_emitters) == 6
                and all(prim.IsValid() for prim in boundary_emitters),
            ),
            ("timeline_is_playing", timeline.is_playing()),
            ("timeline_time_before", timeline_time_before),
            ("timeline_time_after", timeline_time_after),
            ("timeline_advancing", timeline_time_after > timeline_time_before),
            ("stage_timeCodesPerSecond", stage.GetTimeCodesPerSecond()),
        ]
        details = ", ".join(f"{key}={value}" for key, value in diagnostics)
        carb.log_warn(f"BMS Kit-CAE Flow full diagnostics: {details}")

    @staticmethod
    def _validate_kit_cae_velocity_field(
        dataset_prim,
        field_prim,
        metadata: dict[str, object],
        cae,
        cae_vtk,
    ) -> dict[str, object]:
        """Verify that Kit-CAE represented the Houdini VTI as a point vector field."""

        if not dataset_prim or not dataset_prim.IsA(cae.DataSet):
            raise RuntimeError("Kit-CAE did not create a CaeDataSet from the VTI.")
        if not dataset_prim.HasAPI(cae.DenseVolumeAPI):
            raise RuntimeError("Kit-CAE VTI dataset is missing DenseVolumeAPI.")
        if not field_prim or field_prim.GetTypeName() != "CaeVtkFieldArray":
            raise RuntimeError("Kit-CAE did not create the expected CaeVtkFieldArray.")
        association = str(field_prim.GetAttribute("fieldAssociation").Get())
        if association != str(cae.Tokens.vertex):
            raise RuntimeError(
                "Kit-CAE velocity field is not associated with VTI PointData."
            )

        dense_volume = cae.DenseVolumeAPI(dataset_prim)
        min_extent = dense_volume.GetMinExtentAttr().Get()
        max_extent = dense_volume.GetMaxExtentAttr().Get()
        imported_dimensions = tuple(
            int(max_extent[index] - min_extent[index] + 1) for index in range(3)
        )
        if imported_dimensions != metadata["dimensions"]:
            raise RuntimeError(
                "Kit-CAE VTI dimensions do not match the source VTI PointData grid."
            )
        imported_spacing = tuple(
            float(value) for value in dense_volume.GetSpacingAttr().Get()
        )
        expected_spacing = metadata["spacing"]
        if any(
            abs(imported_spacing[index] - expected_spacing[index]) > 1e-6
            for index in range(3)
        ):
            raise RuntimeError(
                "Kit-CAE VTI spacing does not match the source VTI grid."
            )

        image_data = cae_vtk.ImageDataAPI(dataset_prim)
        imported_origin = tuple(
            float(value) for value in image_data.GetOriginAttr().Get()
        )
        imported_min = tuple(
            imported_origin[index] + min_extent[index] * imported_spacing[index]
            for index in range(3)
        )
        imported_max = tuple(
            imported_origin[index] + max_extent[index] * imported_spacing[index]
            for index in range(3)
        )
        return {
            "origin": imported_origin,
            "spacing": imported_spacing,
            "world_bounds": (imported_min, imported_max),
        }

    @staticmethod
    def _read_kit_cae_vti_origin_opinion(
        dataset_prim,
        cae_vtk,
    ) -> dict[str, object]:
        """Capture the composed ImageData origin and each authored USD opinion."""

        if not dataset_prim or not dataset_prim.IsValid():
            raise RuntimeError("Kit-CAE did not create a VTI dataset to inspect.")
        origin_attr = cae_vtk.ImageDataAPI(dataset_prim).GetOriginAttr()
        if not origin_attr or not origin_attr.IsValid():
            raise RuntimeError("Kit-CAE VTI dataset is missing ImageDataAPI.origin.")

        def serialise_value(value):
            if value is None:
                return None
            try:
                return tuple(float(component) for component in value)
            except TypeError:
                return str(value)

        return {
            "origin": serialise_value(origin_attr.Get()),
            "property_stack": [
                {
                    "layer": spec.layer.identifier,
                    "path": str(spec.path),
                    "default": serialise_value(spec.default),
                }
                for spec in origin_attr.GetPropertyStack()
            ],
        }

    @staticmethod
    def _author_kit_cae_vti_origin_session_opinion(
        dataset_prim,
        vti_header_origin: tuple[float, float, float],
        cae_vtk,
        Gf,
    ) -> None:
        """Restore the VTI origin through the active BMS session layer."""

        if not dataset_prim or not dataset_prim.IsValid():
            raise RuntimeError("Kit-CAE did not create a VTI dataset to register.")
        origin_attr = cae_vtk.ImageDataAPI(dataset_prim).GetOriginAttr()
        if not origin_attr or not origin_attr.IsValid():
            raise RuntimeError("Kit-CAE VTI dataset is missing ImageDataAPI.origin.")
        origin_attr.Set(Gf.Vec3f(*vti_header_origin))

    @staticmethod
    def _author_kit_cae_spatial_sanity_wireframes(
        stage,
        dataset_world_bounds: tuple[
            tuple[float, float, float], tuple[float, float, float]
        ],
        Gf,
        Usd,
        UsdGeom,
    ) -> None:
        """Draw probe-only dataset and server bounds in distinct colors."""

        bbox_cache = UsdGeom.BBoxCache(
            Usd.TimeCode.Default(),
            [UsdGeom.Tokens.default_, UsdGeom.Tokens.render, UsdGeom.Tokens.proxy],
        )
        server_prim = stage.GetPrimAtPath("/blackwell_rig")
        server_range = bbox_cache.ComputeWorldBound(server_prim).ComputeAlignedRange()
        if server_range.IsEmpty():
            raise RuntimeError(
                "Cannot draw Flow spatial sanity check: server bounds are empty."
            )
        server_world_bounds = (
            tuple(server_range.GetMin()),
            tuple(server_range.GetMax()),
        )
        root_path = "/BMS_KitCAE/SpatialSanity"
        stage.RemovePrim(root_path)
        UsdGeom.Xform.Define(stage, root_path)

        def author_wireframe(
            name: str,
            bounds: tuple[tuple[float, float, float], tuple[float, float, float]],
            color: tuple[float, float, float],
            width: float,
        ) -> None:
            minimum, maximum = bounds
            corners = (
                (minimum[0], minimum[1], minimum[2]),
                (maximum[0], minimum[1], minimum[2]),
                (maximum[0], maximum[1], minimum[2]),
                (minimum[0], maximum[1], minimum[2]),
                (minimum[0], minimum[1], maximum[2]),
                (maximum[0], minimum[1], maximum[2]),
                (maximum[0], maximum[1], maximum[2]),
                (minimum[0], maximum[1], maximum[2]),
            )
            edges = (
                (0, 1),
                (1, 2),
                (2, 3),
                (3, 0),
                (4, 5),
                (5, 6),
                (6, 7),
                (7, 4),
                (0, 4),
                (1, 5),
                (2, 6),
                (3, 7),
            )
            points = [Gf.Vec3f(*corners[index]) for edge in edges for index in edge]
            curve = UsdGeom.BasisCurves.Define(stage, f"{root_path}/{name}")
            curve.CreateTypeAttr(UsdGeom.Tokens.linear)
            curve.CreateCurveVertexCountsAttr([2] * len(edges))
            curve.CreatePointsAttr(points)
            curve.CreateWidthsAttr([width] * len(points))
            curve.CreateDisplayColorPrimvar(UsdGeom.Tokens.vertex).Set(
                [Gf.Vec3f(*color)] * len(points)
            )

        # The wider server frame remains visible around an aligned dataset frame.
        author_wireframe(
            "ServerBounds",
            server_world_bounds,
            (1.0, 0.28, 0.55),
            0.003,
        )
        author_wireframe(
            "DatasetBounds",
            dataset_world_bounds,
            (0.1, 0.9, 1.0),
            0.0015,
        )

    @staticmethod
    def _author_airflow_cache_session_layer(
        stage,
        cache,
        contract,
        Gf,
        Sdf,
        UsdGeom,
        UsdShade,
    ) -> None:
        """Author native NVIDIA IndeX compositing opinions in the session layer."""

        runtime_path = Sdf.Path("/BMS_Runtime/Airflow")
        stage.RemovePrim(runtime_path)
        stage.RemovePrim("/BMS_Runtime/Looks/AirflowIndex")

        UsdGeom.Xform.Define(stage, "/BMS_Runtime")
        cache_root = UsdGeom.Xform.Define(stage, runtime_path)
        cache_root.GetPrim().GetReferences().AddReference(
            contract.wrapper_path.as_posix(),
            Sdf.Path(cache.root_prim_path),
        )

        volume_prim = next(
            (
                prim
                for prim in cache_root.GetPrim().GetChildren()
                if prim.GetTypeName() == "Volume"
            ),
            None,
        )
        if not volume_prim:
            raise RuntimeError("The airflow wrapper did not compose a USD Volume.")

        volume_prim.CreateAttribute(
            "nvindex:composite",
            Sdf.ValueTypeNames.Bool,
            custom=True,
        ).Set(True)
        volume_prim.CreateAttribute(
            "omni:rtx:skip",
            Sdf.ValueTypeNames.Bool,
            custom=True,
        ).Set(True)
        volume_prim.SetCustomDataByKey(
            "nvindex.renderSettings",
            {
                "filterMode": cache.filter_mode,
                "samplingDistance": cache.sampling_distance,
            },
        )

        material_path = Sdf.Path("/BMS_Runtime/Looks/AirflowIndex")
        material = UsdShade.Material.Define(stage, material_path)
        colormap = stage.DefinePrim(material_path.AppendChild("Colormap"), "Colormap")
        colormap.CreateAttribute(
            "colormapSource",
            Sdf.ValueTypeNames.Token,
            custom=True,
        ).Set("rgbaPoints")
        colormap.CreateAttribute(
            "domain",
            Sdf.ValueTypeNames.Float2,
            custom=True,
        ).Set(Gf.Vec2f(0.0, 12.5))
        colormap.CreateAttribute(
            "domainBoundaryMode",
            Sdf.ValueTypeNames.Token,
            custom=False,
            variability=Sdf.VariabilityUniform,
        ).Set("clampToTransparent")
        colormap_output = colormap.CreateAttribute(
            "outputs:colormap",
            Sdf.ValueTypeNames.Token,
            custom=True,
        )
        colormap.CreateAttribute(
            "rgbaPoints",
            Sdf.ValueTypeNames.Float4Array,
            custom=True,
        ).Set(
            [
                Gf.Vec4f(0.03, 0.12, 0.16, 0.0),
                Gf.Vec4f(0.05, 0.48, 0.64, 0.025),
                Gf.Vec4f(0.13, 0.82, 0.87, 0.16),
                Gf.Vec4f(0.62, 0.98, 0.88, 0.34),
            ]
        )
        colormap.CreateAttribute(
            "xPoints",
            Sdf.ValueTypeNames.FloatArray,
            custom=True,
        ).Set([0.0, 0.15, 1.5, 12.5])

        shader = UsdShade.Shader.Define(
            stage, material_path.AppendChild("VolumeShader")
        )
        shader_input = shader.CreateInput("colormap", Sdf.ValueTypeNames.Token)
        shader_input.GetAttr().AddConnection(colormap_output.GetPath())
        shader_output = shader.CreateOutput("volume", Sdf.ValueTypeNames.Token)
        material_output = material.GetPrim().CreateAttribute(
            "outputs:nvindex:volume",
            Sdf.ValueTypeNames.Token,
            custom=True,
        )
        material_output.AddConnection(shader_output.GetAttr().GetPath())
        UsdShade.MaterialBindingAPI.Apply(volume_prim).Bind(material)

    @staticmethod
    def _enable_index_compositing(stage, cache, carb) -> None:
        """Enable the global RTX compositing switch used by the NVIDIA fixture."""

        settings = carb.settings.get_settings()
        settings.set("/rtx/index/compositeEnabled", True)
        settings.set("/rtx/index/compositeDepthMode", 3)
        settings.set("/rtx/index/resolutionScale", cache.resolution_scale)
        settings.set("/rtx/index/renderingSamples", cache.rendering_samples)

        session_layer = stage.GetSessionLayer()
        layer_data = dict(session_layer.customLayerData)
        render_settings = dict(layer_data.get("renderSettings", {}))
        render_settings["rtx:index:compositeEnabled"] = True
        render_settings["rtx:index:compositeDepthMode"] = 3
        layer_data["renderSettings"] = render_settings
        session_layer.customLayerData = layer_data

    @staticmethod
    def _apply_chassis_presentation(
        stage,
        presentation: ChassisPresentationConfig,
        open_chassis: bool,
        UsdGeom,
    ) -> None:
        """Author reversible cover visibility opinions on the session layer."""

        if presentation.visibility_groups:
            for group in presentation.visibility_groups:
                RuntimeController._apply_chassis_visibility_paths(
                    stage,
                    group.paths,
                    group.default_visible,
                    UsdGeom,
                )
            return

        visibility = (
            UsdGeom.Tokens.invisible if open_chassis else UsdGeom.Tokens.inherited
        )
        RuntimeController._apply_chassis_visibility_paths(
            stage,
            presentation.cover_paths,
            visibility == UsdGeom.Tokens.inherited,
            UsdGeom,
        )

    @staticmethod
    def _apply_chassis_visibility_paths(stage, paths, visible: bool, UsdGeom) -> int:
        visibility = UsdGeom.Tokens.inherited if visible else UsdGeom.Tokens.invisible
        matched_count = 0
        for path in paths:
            prim = stage.GetPrimAtPath(path)
            if not prim or not prim.IsValid():
                continue
            matched_count += 1
            if visible:
                RuntimeController._make_chassis_visibility_ancestors_visible(
                    stage,
                    prim.GetPath(),
                    UsdGeom,
                )
            imageable = UsdGeom.Imageable(prim)
            if not imageable:
                continue
            imageable.CreateVisibilityAttr().Set(visibility)
        return matched_count

    @staticmethod
    def _make_chassis_visibility_ancestors_visible(stage, prim_path, UsdGeom) -> None:
        parent_path = prim_path.GetParentPath()
        while str(parent_path) != "/":
            parent_prim = stage.GetPrimAtPath(parent_path)
            if parent_prim and parent_prim.IsValid():
                imageable = UsdGeom.Imageable(parent_prim)
                if imageable:
                    imageable.CreateVisibilityAttr().Set(UsdGeom.Tokens.inherited)
            parent_path = parent_path.GetParentPath()

    @classmethod
    def _prepare_face_panel_hinge(
        cls,
        stage,
        face_panel: FacePanelConfig,
        open_panel: bool,
        Usd,
        UsdGeom,
    ) -> FacePanelApplyResult:
        if not face_panel.enabled:
            return FacePanelApplyResult(False, "Front panel skipped: disabled.")

        target_prim = stage.GetPrimAtPath(face_panel.target_path)
        if not target_prim or not target_prim.IsValid():
            return FacePanelApplyResult(
                False,
                f"Front panel skipped: target prim not found: {face_panel.target_path}",
            )

        target_angle = (
            face_panel.open_angle_degrees
            if open_panel
            else face_panel.closed_angle_degrees
        )
        rotate_op = cls._ensure_face_panel_hinge_op(
            stage,
            target_prim,
            face_panel.rotation_axis,
            Usd,
            UsdGeom,
        )
        current_value = rotate_op.Get()
        start_angle = (
            float(current_value)
            if current_value is not None
            else float(face_panel.closed_angle_degrees)
        )
        return FacePanelApplyResult(
            True,
            "Front panel hinge ready.",
            start_angle=start_angle,
            target_angle=float(target_angle),
            rotate_op=rotate_op,
        )

    @classmethod
    def _ensure_face_panel_hinge_op(
        cls,
        stage,
        target_prim,
        rotation_axis: str,
        Usd,
        UsdGeom,
    ):
        edit_target = stage.GetEditTargetForLocalLayer(stage.GetSessionLayer())
        with Usd.EditContext(stage, edit_target):
            xformable = UsdGeom.Xformable(target_prim)
            ops = list(xformable.GetOrderedXformOps())
            axis_name = rotation_axis.upper()
            rotate_name = f"xformOp:rotate{axis_name}:{cls.FACE_PANEL_ROTATE_OP_SUFFIX}"
            rotate_op = cls._find_xform_op(ops, rotate_name)
            if rotate_op is None:
                rotate_op = cls._add_axis_rotate_op(
                    xformable,
                    axis_name,
                    cls.FACE_PANEL_ROTATE_OP_SUFFIX,
                    UsdGeom,
                )
                ops.append(rotate_op)
            xformable.SetXformOpOrder(cls._dedupe_xform_ops(ops))
            return rotate_op

    @staticmethod
    def _set_face_panel_hinge_angle(stage, rotate_op, angle: float, Usd) -> None:
        edit_target = stage.GetEditTargetForLocalLayer(stage.GetSessionLayer())
        with Usd.EditContext(stage, edit_target):
            rotate_op.Set(float(angle))

    @staticmethod
    def _find_xform_op(ops, name: str):
        for op in ops:
            if op.GetOpName() == name:
                return op
        return None

    @staticmethod
    def _add_axis_rotate_op(xformable, axis_name: str, suffix: str, UsdGeom):
        if axis_name == "X":
            return xformable.AddRotateXOp(opSuffix=suffix)
        if axis_name == "Y":
            return xformable.AddRotateYOp(opSuffix=suffix)
        if axis_name == "Z":
            return xformable.AddRotateZOp(opSuffix=suffix)
        raise ValueError(f"Unsupported front panel rotation axis: {axis_name}")

    @staticmethod
    def _dedupe_xform_ops(ops):
        seen: set[str] = set()
        deduped = []
        for op in ops:
            name = op.GetOpName()
            if name in seen:
                continue
            seen.add(name)
            deduped.append(op)
        return deduped

    @classmethod
    def _apply_qled_display_temperature(
        cls,
        stage,
        qled: QledDisplayConfig,
        temperature_c: float,
        Gf,
        Sdf,
        Usd,
        UsdShade,
    ) -> bool:
        display_state = qled_state_from_temperature(
            temperature_c,
            warning_threshold_c=qled.warning_threshold_c,
            minimum_value=qled.minimum_value,
            maximum_value=qled.maximum_value,
        )
        materials = cls._ensure_qled_materials(stage, qled, Gf, Sdf, Usd, UsdShade)
        matched_count = 0
        edit_target = stage.GetEditTargetForLocalLayer(stage.GetSessionLayer())
        with Usd.EditContext(stage, edit_target):
            for digit_name, segment_paths in (qled.digits or {}).items():
                active_segments = display_state.active_segments.get(
                    digit_name,
                    frozenset(),
                )
                for segment in SEGMENTS:
                    path = segment_paths.get(segment, "")
                    prim = stage.GetPrimAtPath(path)
                    if not prim or not prim.IsValid():
                        continue
                    material = (
                        materials[display_state.mode]
                        if segment in active_segments
                        else materials["off"]
                    )
                    UsdShade.MaterialBindingAPI.Apply(prim).Bind(material)
                    matched_count += 1
        return matched_count > 0

    @classmethod
    def _ensure_qled_materials(cls, stage, qled, Gf, Sdf, Usd, UsdShade):
        edit_target = stage.GetEditTargetForLocalLayer(stage.GetSessionLayer())
        with Usd.EditContext(stage, edit_target):
            return {
                "normal": cls._define_qled_preview_material(
                    stage,
                    cls.QLED_MATERIAL_PATHS["normal"],
                    qled.normal_emission_color,
                    qled.normal_emission_color,
                    qled.emission_intensity,
                    Gf,
                    Sdf,
                    UsdShade,
                ),
                "warning": cls._define_qled_preview_material(
                    stage,
                    cls.QLED_MATERIAL_PATHS["warning"],
                    qled.warning_emission_color,
                    qled.warning_emission_color,
                    qled.emission_intensity,
                    Gf,
                    Sdf,
                    UsdShade,
                ),
                "off": cls._define_qled_preview_material(
                    stage,
                    cls.QLED_MATERIAL_PATHS["off"],
                    qled.off_color,
                    (0.0, 0.0, 0.0),
                    0.0,
                    Gf,
                    Sdf,
                    UsdShade,
                ),
            }

    @staticmethod
    def _define_qled_preview_material(
        stage,
        material_path: str,
        diffuse_color,
        emission_color,
        emission_intensity: float,
        Gf,
        Sdf,
        UsdShade,
    ):
        material = UsdShade.Material.Define(stage, material_path)
        shader = UsdShade.Shader.Define(stage, f"{material_path}/PreviewSurface")
        shader.CreateIdAttr("UsdPreviewSurface")
        shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(
            Gf.Vec3f(*diffuse_color)
        )
        shader.CreateInput("emissiveColor", Sdf.ValueTypeNames.Color3f).Set(
            Gf.Vec3f(
                *(float(value) * float(emission_intensity) for value in emission_color)
            )
        )
        shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(0.35)
        shader_output = shader.CreateOutput("surface", Sdf.ValueTypeNames.Token)
        material.CreateSurfaceOutput().ConnectToSource(
            shader.ConnectableAPI(),
            shader_output.GetBaseName(),
        )
        return material

    @classmethod
    def _apply_front_panel_indicator_state(
        cls,
        stage,
        indicators: FrontPanelIndicatorsConfig,
        state,
        Gf,
        Sdf,
        Usd,
        UsdShade,
    ) -> bool:
        materials = cls._ensure_front_panel_indicator_materials(
            stage,
            indicators,
            Gf,
            Sdf,
            Usd,
            UsdShade,
        )
        bindings = (
            (
                indicators.power_path,
                materials["power"] if state.power else materials["off"],
            ),
            (indicators.hdd_path, materials["hdd"] if state.hdd else materials["off"]),
            (
                indicators.lan_01_path,
                materials["lan_01"] if state.lan_01 else materials["off"],
            ),
            (
                indicators.lan_02_path,
                materials["lan_02"] if state.lan_02 else materials["off"],
            ),
        )

        matched_count = 0
        edit_target = stage.GetEditTargetForLocalLayer(stage.GetSessionLayer())
        with Usd.EditContext(stage, edit_target):
            for path, material in bindings:
                prim = stage.GetPrimAtPath(path)
                if not prim or not prim.IsValid():
                    continue
                UsdShade.MaterialBindingAPI.Apply(prim).Bind(material)
                matched_count += 1
        return matched_count > 0

    @classmethod
    def _ensure_front_panel_indicator_materials(
        cls,
        stage,
        indicators,
        Gf,
        Sdf,
        Usd,
        UsdShade,
    ):
        edit_target = stage.GetEditTargetForLocalLayer(stage.GetSessionLayer())
        with Usd.EditContext(stage, edit_target):
            return {
                "power": cls._define_qled_preview_material(
                    stage,
                    cls.FRONT_PANEL_MATERIAL_PATHS["power"],
                    indicators.power_color,
                    indicators.power_color,
                    indicators.emission_intensity,
                    Gf,
                    Sdf,
                    UsdShade,
                ),
                "hdd": cls._define_qled_preview_material(
                    stage,
                    cls.FRONT_PANEL_MATERIAL_PATHS["hdd"],
                    indicators.hdd_color,
                    indicators.hdd_color,
                    indicators.emission_intensity,
                    Gf,
                    Sdf,
                    UsdShade,
                ),
                "lan_01": cls._define_qled_preview_material(
                    stage,
                    cls.FRONT_PANEL_MATERIAL_PATHS["lan_01"],
                    indicators.lan_01_color,
                    indicators.lan_01_color,
                    indicators.emission_intensity,
                    Gf,
                    Sdf,
                    UsdShade,
                ),
                "lan_02": cls._define_qled_preview_material(
                    stage,
                    cls.FRONT_PANEL_MATERIAL_PATHS["lan_02"],
                    indicators.lan_02_color,
                    indicators.lan_02_color,
                    indicators.emission_intensity,
                    Gf,
                    Sdf,
                    UsdShade,
                ),
                "off": cls._define_qled_preview_material(
                    stage,
                    cls.FRONT_PANEL_MATERIAL_PATHS["off"],
                    indicators.off_color,
                    (0.0, 0.0, 0.0),
                    0.0,
                    Gf,
                    Sdf,
                    UsdShade,
                ),
            }

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
