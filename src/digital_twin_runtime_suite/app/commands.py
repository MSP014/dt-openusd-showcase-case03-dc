"""Runtime commands for Digital Twin Runtime Suite."""

from __future__ import annotations

import asyncio
import time
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path
from threading import Event, Lock
from typing import Callable

# isort: off
from digital_twin_runtime_suite.app.config import (
    CameraConfig,
    ChassisPresentationConfig,
    EmitterLayoutConfig,
    FacePanelConfig,
    FrontPanelIndicatorsConfig,
    GridConfig,
    LightingConfig,
    QledDisplayConfig,
    RotationConfig,
    RuntimeConfig,
    SmokeTuningConfig,
    XRayMaterialConfig,
    chassis_presentation_with_operator_state,
    format_runtime_override,
)
from digital_twin_runtime_suite.app.front_panel_indicators import (
    front_panel_indicator_state,
)
from digital_twin_runtime_suite.app.flow.performance import FlowPerformanceSample
from digital_twin_runtime_suite.app.flow.progress import TemporalProofProgress
from digital_twin_runtime_suite.app.flow.validation_cache import SessionValidationCache
from digital_twin_runtime_suite.app.flow.runtime import (
    FlowRuntimeMixin,
    SimulationCacheResult,
)
from digital_twin_runtime_suite.app.qled import SEGMENTS, qled_state_from_temperature
from digital_twin_runtime_suite.app.simulation_cache import (
    SimulationCacheContract,
    run_simulation_cache_preflight,
)
from digital_twin_runtime_suite.app.usd_preflight import run_usd_preflight

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
class NormalMapScaleResult:
    """Result of applying the temporary renderer-facing normal-map scale."""

    success: bool
    message: str
    texture_count: int = 0


@dataclass(frozen=True)
class XRayApplyResult:
    """Result of applying or clearing the transient X-Ray material."""

    success: bool
    message: str
    target_count: int = 0
    used_fallback_color: bool = False


@dataclass(frozen=True)
class FacePanelApplyResult:
    """Result of preparing or applying the runtime front-panel hinge."""

    success: bool
    message: str
    start_angle: float = 0.0
    target_angle: float = 0.0
    rotate_op: object | None = None


class RuntimeController(FlowRuntimeMixin):
    """Coordinates config-backed runtime operations for the viewer."""

    FACE_PANEL_ROTATE_OP_SUFFIX = "mspViewHinge"
    KIT_CAE_SERVER_ROOT = "/blackwell_rig"
    FLOW_PERFORMANCE_SAMPLE_INTERVAL_SECONDS = 0.5
    FLOW_PERFORMANCE_LOG_INTERVAL_SECONDS = 30.0
    FLOW_DETACH_SETTLE_UPDATE_COUNT = 3
    FLOW_DETACH_OPERATOR_QUIESCE_SECONDS = 0.75
    FLOW_DETACH_OPERATOR_QUIESCE_TIMEOUT_SECONDS = 5.0
    KIT_CAE_FRONT_INTAKE_BINDING_IDS = frozenset(
        {"front_p120_01", "front_p120_02", "front_p120_03"}
    )
    KIT_CAE_INTAKE_TRACER_PASSIVE_CHANNEL_VALUES = (
        ("radius", 1.0),
        ("radiusIsWorldSpace", False),
        ("velocity", (0.0, 0.0, 0.0)),
        ("coupleRateVelocity", 0.0),
        ("fuel", 0.0),
        ("coupleRateFuel", 0.0),
        ("temperature", 0.0),
        ("coupleRateTemperature", 0.0),
        ("burn", 0.0),
        ("coupleRateBurn", 0.0),
    )
    QLED_MATERIAL_PATHS = {
        "normal": "/DTRS_Runtime/Looks/QLEDOnNormal",
        "warning": "/DTRS_Runtime/Looks/QLEDOnWarning",
        "off": "/DTRS_Runtime/Looks/QLEDOff",
    }
    FRONT_PANEL_MATERIAL_PATHS = {
        "power": "/DTRS_Runtime/Looks/FrontPanelPowerOn",
        "hdd": "/DTRS_Runtime/Looks/FrontPanelHDDOn",
        "lan_01": "/DTRS_Runtime/Looks/FrontPanelLAN01On",
        "lan_02": "/DTRS_Runtime/Looks/FrontPanelLAN02On",
        "off": "/DTRS_Runtime/Looks/FrontPanelIndicatorOff",
    }
    XRAY_CHASSIS_ROOT_PATH = "/blackwell_rig/chassis"
    XRAY_SOURCE_MATERIAL_PATH = "/blackwell_rig/chassis/mtl/base_lod00_mat"
    XRAY_MATERIAL_PATH = "/DTRS_Runtime/Looks/xray_material"
    XRAY_ISOLATION_PART_A_COLOR = (1.0, 1.0, 0.0)
    XRAY_ISOLATION_PART_B_COLOR = (0.0, 0.0, 1.0)
    XRAY_ISOLATION_ROUGHNESS = 0.4
    XRAY_ISOLATION_BLEND_BIAS = 5.0
    XRAY_SURFACE_FALLOFF_PROBES = {
        1: (0.0, 0.0, "Part A selection", "yellow", "PartB"),
        2: (1.0, 1.0, "Part B selection", "blue", "PartB"),
        3: (0.0, 1.0, "Surface Falloff", "yellow face / blue edge", "PartB"),
        4: (1.0, 1.0, "Blend input control", "yellow", "PartA"),
    }
    _xray_diagnostic_baseline: dict[str, str] | None = None
    _xray_diagnostic_representative_path: str | None = None
    _xray_diagnostic_baseline_root_dirty: bool | None = None

    def __init__(self, config_path: Path | str):
        self._config_path = Path(config_path)
        self.config = RuntimeConfig.load(self._config_path)
        self._simulation_cache_contract: SimulationCacheContract | None = None
        self._simulation_cache_time_code: int | None = None
        self._flow_airflow_simulate_path: str | None = None
        self._flow_base_velocity_scale: float | None = None
        self._flow_world_bounds: (
            tuple[tuple[float, float, float], tuple[float, float, float]] | None
        ) = None
        self._flow_density_cell_size: float | None = None
        self._flow_lifecycle_state = "DETACHED"
        self._flow_attach_cancel_event: Event | None = None
        self._flow_kit_cae_operator_lock = Lock()
        self._flow_kit_cae_active_operator_paths: set[str] = set()
        self._flow_kit_cae_operator_subscriptions: tuple[object, ...] = ()
        self._flow_temporal_asset_hashes: dict[Path, str] = {}
        self._flow_temporal_records: list[dict[str, object]] = []
        self._flow_temporal_failure: dict[str, str] | None = None
        self._flow_temporal_end_time_code: float | None = None
        self._flow_temporal_sample_time_codes: tuple[float, ...] = ()
        self._flow_temporal_proof_task: asyncio.Task | None = None
        self._flow_temporal_proof_generation = 0
        self._flow_temporal_progress = TemporalProofProgress()
        self._flow_validation_cache = SessionValidationCache()
        self._flow_performance_task: asyncio.Task | None = None
        self._flow_performance_session_id = 0
        self._flow_performance_attached_at: float | None = None
        self._flow_performance_samples: list[FlowPerformanceSample] = []
        self._flow_performance_camera_bookmark = "Unspecified"
        self._front_panel_indicator_state_key: (
            tuple[int, bool, bool, bool, bool] | None
        ) = None

    def reload_config(self) -> RuntimeConfig:
        """Reload configuration only after the current Flow session is detached."""

        if self._flow_lifecycle_state != "DETACHED":
            raise RuntimeError("Detach airflow before reloading config.")

        # A new configuration defines a new validation session. Stop every
        # DTRS-owned callback before discarding plain-data validation receipts.
        self.stop_flow_runtime_callbacks()
        self._stop_kit_cae_operator_tracking()
        self._flow_validation_cache.clear()
        self.config = RuntimeConfig.load(self._config_path)
        self._simulation_cache_contract = None
        self._simulation_cache_time_code = None
        self._flow_airflow_simulate_path = None
        self._flow_base_velocity_scale = None
        self._flow_world_bounds = None
        self._flow_density_cell_size = None
        self._flow_lifecycle_state = "DETACHED"
        self._flow_attach_cancel_event = None
        self._flow_temporal_asset_hashes = {}
        self._flow_temporal_records = []
        self._flow_temporal_failure = None
        self._flow_temporal_end_time_code = None
        self._flow_temporal_sample_time_codes = ()
        self._flow_performance_attached_at = None
        self._flow_performance_samples = []
        self._flow_performance_camera_bookmark = "Unspecified"
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
        smoke_tuning: SmokeTuningConfig | None = None,
        emitter_layout: EmitterLayoutConfig | None = None,
        chassis_presentation: ChassisPresentationConfig | None = None,
    ) -> Path:
        """Persist local operator settings beside the base config."""

        active_camera = camera or self.config.camera
        active_grid = grid or self.config.grid
        active_smoke_tuning = smoke_tuning or self.config.simulation_cache.smoke_tuning
        active_emitter_layout = (
            emitter_layout or self.config.simulation_cache.emitter_layout
        )
        active_chassis_presentation = (
            chassis_presentation or self.config.chassis_presentation
        )
        local_path = RuntimeConfig.local_config_path_for(self._config_path)
        temporary_path = local_path.with_name(f"{local_path.name}.tmp")
        temporary_path.write_text(
            format_runtime_override(
                lighting,
                active_camera,
                active_grid,
                active_smoke_tuning,
                active_emitter_layout,
                active_chassis_presentation,
            ),
            encoding="utf-8",
        )
        temporary_path.replace(local_path)
        self.config = RuntimeConfig.load(self._config_path)
        return local_path

    def save_smoke_tuning_override(self, smoke_tuning: SmokeTuningConfig) -> Path:
        """Persist a successfully applied Flow tuning without losing peer overrides."""

        return self.save_runtime_override(
            self.config.lighting,
            self.config.camera,
            self.config.grid,
            smoke_tuning,
        )

    def save_emitter_layout_override(
        self,
        emitter_layout: EmitterLayoutConfig,
    ) -> Path:
        """Persist a successfully applied tracer layout without losing peers."""

        return self.save_runtime_override(
            self.config.lighting,
            self.config.camera,
            self.config.grid,
            self.config.simulation_cache.smoke_tuning,
            emitter_layout,
        )

    def save_chassis_presentation_override(
        self,
        visibility_by_group: dict[str, bool],
        face_panel_open: bool | None,
    ) -> Path:
        """Persist validated enclosure controls without replacing peer overrides."""

        presentation = chassis_presentation_with_operator_state(
            self.config.chassis_presentation,
            visibility_by_group,
            face_panel_open,
        )
        return self.save_runtime_override(
            self.config.lighting,
            self.config.camera,
            self.config.grid,
            self.config.simulation_cache.smoke_tuning,
            self.config.simulation_cache.emitter_layout,
            presentation,
        )

    def save_normal_map_scale_override(self, normal_map_scale: float) -> Path:
        """Persist the temporary material-tuning value with appearance controls."""

        if not 0.0 <= normal_map_scale <= 4.0:
            raise ValueError("Normal map scale must be between 0 and 4.")
        presentation = replace(
            self.config.chassis_presentation,
            materials=replace(
                self.config.chassis_presentation.materials,
                normal_map_scale=normal_map_scale,
            ),
        )
        return self.save_runtime_override(
            self.config.lighting,
            self.config.camera,
            self.config.grid,
            self.config.simulation_cache.smoke_tuning,
            self.config.simulation_cache.emitter_layout,
            presentation,
        )

    def save_xray_material_override(self, xray: XRayMaterialConfig) -> Path:
        """Persist the X-Ray UI state without storing transient USD opinions."""

        presentation = replace(
            self.config.chassis_presentation,
            materials=replace(
                self.config.chassis_presentation.materials,
                xray=xray,
            ),
        )
        return self.save_runtime_override(
            self.config.lighting,
            self.config.camera,
            self.config.grid,
            self.config.simulation_cache.smoke_tuning,
            self.config.simulation_cache.emitter_layout,
            presentation,
        )

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
        temporary_path = local_path.with_name(f"{local_path.name}.tmp")
        temporary_path.write_text(
            format_runtime_override(
                lighting,
                None,
                self.config.grid,
                self.config.simulation_cache.smoke_tuning,
                self.config.simulation_cache.emitter_layout,
                self.config.chassis_presentation,
            ),
            encoding="utf-8",
        )
        temporary_path.replace(local_path)
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

        import carb
        import omni.kit.app
        import omni.usd
        from pxr import Gf, Sdf, UsdShade

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
            if preflight_result.material_repairs:
                carb.log_info(
                    preflight_result.format_material_repairs(
                        self.config.default_asset_id
                    )
                )
            normal_map_count = self._apply_normal_map_scale(
                stage,
                self.config.chassis_presentation.materials.normal_map_scale,
                Gf,
                Sdf,
                UsdShade,
            )
            if normal_map_count:
                carb.log_info(
                    "DTRS normal-map scale applied to "
                    f"{normal_map_count} renderer-facing texture(s): "
                    f"{self.config.chassis_presentation.materials.normal_map_scale:g}"
                )
            if preflight_result.has_errors:
                # The sidebar is intentionally compact; write every finding to the
                # startup log so a missing composition asset is immediately actionable.
                carb.log_error(
                    preflight_result.format_diagnostics(
                        asset_path=asset_path,
                        root_identifier=root_identifier,
                    )
                )
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

        prim = stage.GetPrimAtPath("/DTRS_Runtime/ReviewCamera")
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

        prim = stage.GetPrimAtPath("/DTRS_Runtime/ReviewCamera")
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
            runtime_root = UsdGeom.Xform.Define(stage, "/DTRS_Runtime")
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

            camera = UsdGeom.Camera.Define(stage, "/DTRS_Runtime/ReviewCamera")
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

        camera_path = Sdf.Path("/DTRS_Runtime/ReviewCamera")
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

        runtime_path = Sdf.Path("/DTRS_Runtime/Airflow")
        stage.RemovePrim(runtime_path)
        stage.RemovePrim("/DTRS_Runtime/Looks/AirflowIndex")

        UsdGeom.Xform.Define(stage, "/DTRS_Runtime")
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

        material_path = Sdf.Path("/DTRS_Runtime/Looks/AirflowIndex")
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

    def apply_normal_map_scale_in_kit(
        self,
        normal_map_scale: float,
    ) -> NormalMapScaleResult:
        """Apply the temporary normal-map scale to renderer-facing texture nodes."""

        import omni.usd
        from pxr import Gf, Sdf, UsdShade

        if not 0.0 <= normal_map_scale <= 4.0:
            return NormalMapScaleResult(
                success=False,
                message="Normal map scale must be between 0 and 4.",
            )
        stage = omni.usd.get_context().get_stage()
        if not stage:
            return NormalMapScaleResult(
                success=False,
                message="Normal map scale skipped: no open stage.",
            )
        texture_count = self._apply_normal_map_scale(
            stage,
            normal_map_scale,
            Gf,
            Sdf,
            UsdShade,
        )
        if not texture_count:
            return NormalMapScaleResult(
                success=True,
                message="No renderer-facing normal maps are connected.",
            )
        return NormalMapScaleResult(
            success=True,
            message=(
                f"Normal-map scale {normal_map_scale:g} applied to "
                f"{texture_count} texture(s)."
            ),
            texture_count=texture_count,
        )

    def apply_xray_material_in_kit(
        self,
        xray: XRayMaterialConfig,
        surface_falloff_probe: int | None = None,
    ) -> XRayApplyResult:
        """Apply the temporary Surface Falloff isolation graph in the session layer."""

        import omni.usd
        from pxr import Gf, Sdf, Usd, UsdShade

        stage = omni.usd.get_context().get_stage()
        if not stage:
            return XRayApplyResult(False, "X-Ray skipped: no open stage.")

        previous_target = stage.GetEditTarget()
        stage.SetEditTarget(stage.GetSessionLayer())
        self._xray_last_authoring_edit_target = (
            stage.GetEditTarget().GetLayer().identifier
        )
        try:
            if not xray.chassis_selected:
                removed_count = self._clear_xray_session_overrides(
                    stage,
                    Usd,
                    UsdShade,
                )
                return XRayApplyResult(
                    True,
                    "X-Ray removed; original chassis materials restored.",
                    removed_count,
                )

            root = stage.GetPrimAtPath(self.XRAY_CHASSIS_ROOT_PATH)
            if not root or not root.IsValid():
                return XRayApplyResult(
                    False,
                    "X-Ray skipped: Chassis - SilverStone RM44 was not found.",
                )
            self._clear_xray_session_overrides(stage, Usd, UsdShade)
            probe = surface_falloff_probe or 3
            facing_weight, edge_weight, _name, _expected, blend_part = (
                self._xray_surface_falloff_probe(probe)
            )
            material = self._define_xray_material(
                stage,
                (facing_weight, edge_weight),
                blend_part,
                Gf,
                Sdf,
                UsdShade,
            )
            target_count = self._bind_xray_material_to_chassis(
                stage,
                root,
                material,
                Usd,
                UsdShade,
            )
        finally:
            stage.SetEditTarget(previous_target)

        if not target_count:
            return XRayApplyResult(
                False,
                "X-Ray skipped: no chassis mesh targets were found.",
            )
        return XRayApplyResult(
            True,
            "X-Ray Surface Falloff isolation probe "
            f"{probe} applied to {target_count} chassis mesh target(s).",
            target_count,
        )

    @classmethod
    def _xray_surface_falloff_probe(
        cls,
        probe: int,
    ) -> tuple[float, float, str, str, str]:
        """Return the fixed, non-persistent weights for one isolation probe."""

        try:
            return cls.XRAY_SURFACE_FALLOFF_PROBES[probe]
        except KeyError as error:
            raise ValueError(
                f"Unknown Surface Falloff isolation probe: {probe}"
            ) from error

    def log_xray_surface_falloff_probe(
        self,
        probe: int,
        result: XRayApplyResult,
    ) -> None:
        """Log the actual composed state immediately after a probe click."""

        import carb
        import omni.usd
        from pxr import Usd, UsdShade

        stage = omni.usd.get_context().get_stage()
        if not stage:
            carb.log_warn(
                "DTRS X-Ray SurfaceFalloff isolation\n"
                f"  Probe {probe}: stage=<none>\n"
                f"  result: {result.message}"
            )
            return
        carb.log_warn(
            self._format_xray_surface_falloff_isolation_state(
                stage,
                probe,
                result,
                Usd,
                UsdShade,
            )
        )
        if probe == 4 and result.success:
            asyncio.ensure_future(
                self._log_xray_surface_falloff_neuray_backend_after_renderer_update()
            )

    async def _log_xray_surface_falloff_neuray_backend_after_renderer_update(
        self,
    ) -> None:
        """Inspect the active RTX MDL call after its renderer update."""

        import carb
        import omni.kit.app

        for _ in range(3):
            await omni.kit.app.get_app().next_update_async()
        carb.log_warn(self._format_xray_surface_falloff_neuray_backend())

    @classmethod
    def _format_xray_surface_falloff_neuray_backend(cls) -> str:
        """Read only the five runtime arguments of SurfaceFalloff's active MDL call."""

        import omni.mdl.neuraylib
        import omni.mdl.pymdlsdk as pymdlsdk

        entity = None
        snapshot = None
        transaction = None
        path = f"{cls.XRAY_MATERIAL_PATH}/SurfaceFalloff"
        try:
            neuraylib = omni.mdl.neuraylib.get_neuraylib()
            entity = neuraylib.createMdlEntity(path)
            entity_valid = bool(entity and entity.valid())
            lines = [
                "DTRS X-Ray Neuray SurfaceFalloff backend",
                f"  prim: {path}",
                "  entity: "
                f"valid={entity_valid}; "
                f"dbScopeName={getattr(entity, 'dbScopeName', '<missing>')}; "
                "simpleNameWithSignature="
                f"{getattr(entity, 'simpleNameWithSignature', '<missing>')}",
            ]
            if not entity_valid:
                lines.append("  snapshot: NOT CREATED (entity invalid)")
                return "\n".join(lines)

            snapshot = neuraylib.createMdlEntitySnapshot(entity)
            # MdlEntitySnapshot in this Kit build has no valid() method.  A
            # non-null snapshot is the supported success condition; its DB
            # identifiers name the renderer-side material call to inspect.
            snapshot_valid = snapshot is not None
            lines.append(
                "  snapshot: "
                f"returned={snapshot_valid}; "
                f"dbScopeName={getattr(snapshot, 'dbScopeName', '<missing>')}; "
                f"dbName={getattr(snapshot, 'dbName', '<missing>')}; "
                "simpleNameWithSignature="
                f"{getattr(snapshot, 'simpleNameWithSignature', '<missing>')}"
            )
            if not snapshot_valid:
                return "\n".join(lines)

            transaction_handle = neuraylib.createReadingTransaction(
                snapshot.dbScopeName
            )
            transaction = pymdlsdk.attach_itransaction(transaction_handle)
            # Keep all DB-interface handles in this helper's local scope. It
            # drops them before the outer finally aborts the read transaction.
            lines.extend(
                cls._read_xray_surface_falloff_backend_values(
                    transaction,
                    snapshot.dbName,
                    pymdlsdk,
                )
            )
            return "\n".join(lines)
        except Exception as error:
            return (
                "DTRS X-Ray Neuray SurfaceFalloff backend\n"
                f"  prim: {path}\n"
                f"  inspection_failed: {error}"
            )
        finally:
            if transaction and transaction.is_open():
                transaction.abort()
            if snapshot is not None:
                neuraylib.destroyMdlEntitySnapshot(snapshot)
            if entity is not None:
                neuraylib.destroyMdlEntity(entity)

    @classmethod
    def _read_xray_surface_falloff_backend_values(
        cls,
        transaction,
        falloff_db_name: str,
        pymdlsdk,
    ) -> list[str]:
        """Read primitive diagnostics, then drop all MDL DB handles before abort."""

        falloff_call = None
        falloff_arguments = None
        part_a_call = None
        part_a_arguments = None
        try:
            falloff_call = transaction.access_as(
                pymdlsdk.IFunction_call, falloff_db_name
            )
            if not falloff_call or not falloff_call.is_valid_interface():
                return ["  function_call: <invalid>"]

            falloff_arguments = falloff_call.get_arguments()
            lines = ["  backend_arguments:"]
            base_reference = "<none>"
            for name in (
                "base",
                "blend",
                "facing_weight",
                "edge_weight",
                "blend_bias",
            ):
                details = cls._xray_neuray_expression_details(
                    falloff_arguments.get_expression(name), pymdlsdk
                )
                if name == "base":
                    base_reference = details["reference"]
                lines.append(cls._xray_neuray_details_line(name, details))

            if base_reference == "<none>":
                lines.append("  shared_part_a: <not a call>")
                return lines

            part_a_call = transaction.access_as(pymdlsdk.IFunction_call, base_reference)
            if not part_a_call or not part_a_call.is_valid_interface():
                lines.append("  shared_part_a: <invalid>")
                return lines

            part_a_arguments = part_a_call.get_arguments()
            lines.append(f"  shared_part_a: {base_reference}")
            for name in ("diffuse_reflection_color", "enable_opacity"):
                details = cls._xray_neuray_expression_details(
                    part_a_arguments.get_expression(name), pymdlsdk
                )
                lines.append(
                    cls._xray_neuray_details_line(name, details, indent="    ")
                )
            return lines
        finally:
            # Explicitly discard all transaction-backed handles before its
            # abort in the caller. The SWIG wrappers release their references
            # when these local references disappear.
            part_a_arguments = None
            part_a_call = None
            falloff_arguments = None
            falloff_call = None

    @classmethod
    def _xray_neuray_expression_details(cls, expression, pymdlsdk) -> dict[str, object]:
        """Convert the small supported MDL expression set to plain Python data."""

        if not expression or not expression.is_valid_interface():
            return {"kind": "<missing>", "reference": "<none>", "constant": "<none>"}

        kind = expression.get_kind()
        reference = "<none>"
        constant: object = "<not a constant>"
        call_expression = expression.get_interface(pymdlsdk.IExpression_call)
        if call_expression and call_expression.is_valid_interface():
            reference = call_expression.get_call()
        else:
            direct_call = expression.get_interface(pymdlsdk.IExpression_direct_call)
            if direct_call and direct_call.is_valid_interface():
                reference = direct_call.get_definition()
            else:
                constant_expression = expression.get_interface(
                    pymdlsdk.IExpression_constant
                )
                if constant_expression and constant_expression.is_valid_interface():
                    value = constant_expression.get_value()
                    constant = cls._xray_neuray_value_to_python(value, pymdlsdk)
        return {"kind": kind, "reference": reference, "constant": constant}

    @staticmethod
    def _xray_neuray_value_to_python(value, pymdlsdk) -> object:
        """Decode only the float, color, and bool values used by Probe 4."""

        if not value or not value.is_valid_interface():
            return "<invalid>"
        float_value = value.get_interface(pymdlsdk.IValue_float)
        if float_value and float_value.is_valid_interface():
            return float(float_value.get_value())
        bool_value = value.get_interface(pymdlsdk.IValue_bool)
        if bool_value and bool_value.is_valid_interface():
            return bool(bool_value.get_value())
        color_value = value.get_interface(pymdlsdk.IValue_color)
        if color_value and color_value.is_valid_interface():
            components = []
            for index in range(3):
                component = color_value.get_value(index)
                component_float = component.get_interface(pymdlsdk.IValue_float)
                components.append(float(component_float.get_value()))
            return tuple(components)
        return f"<unsupported {value.get_kind()}>"

    @staticmethod
    def _xray_neuray_details_line(
        name: str,
        details: dict[str, object],
        *,
        indent: str = "    ",
    ) -> str:
        return (
            f"{indent}{name}: kind={details['kind']}; "
            f"reference={details['reference']}; constant={details['constant']}"
        )

    @classmethod
    def _format_xray_surface_falloff_isolation_state(
        cls,
        stage,
        probe: int,
        result: XRayApplyResult,
        Usd,
        UsdShade,
    ) -> str:
        """Format one compact post-Apply state proof; never dump all meshes."""

        facing_weight, edge_weight, name, expected, _blend_part = (
            cls._xray_surface_falloff_probe(probe)
        )
        root = stage.GetPrimAtPath(cls.XRAY_CHASSIS_ROOT_PATH)
        representative = cls._xray_diagnostic_representative_mesh(
            stage, root, Usd, UsdShade
        )
        aggregate = cls._xray_binding_aggregate(root, Usd, UsdShade)
        material = UsdShade.Material.Get(stage, cls.XRAY_MATERIAL_PATH)
        part_a = UsdShade.Shader.Get(stage, f"{cls.XRAY_MATERIAL_PATH}/PartA")
        part_b = UsdShade.Shader.Get(stage, f"{cls.XRAY_MATERIAL_PATH}/PartB")
        falloff = UsdShade.Shader.Get(stage, f"{cls.XRAY_MATERIAL_PATH}/SurfaceFalloff")
        representative_binding = "<none>"
        binding_owner = "<none>"
        if representative:
            binding_api = UsdShade.MaterialBindingAPI(representative)
            bound_material, _binding = binding_api.ComputeBoundMaterial()
            representative_binding = (
                str(bound_material.GetPath()) if bound_material else "<none>"
            )
            binding_owner = cls._xray_property_owners(binding_api.GetDirectBindingRel())
        session = stage.GetSessionLayer()
        registry_inspection = cls._format_xray_surface_falloff_registry(falloff)
        authored_ports = cls._xray_surface_falloff_authored_port_lines(
            material, part_a, falloff
        )
        probe_status = (
            f"  Probe {probe} [{facing_weight:g}/{edge_weight:g}] "
            f"— {name}: AWAITING VISUAL RESULT"
        )
        material_defined = bool(material and material.GetPrim().IsValid())
        direct_bindings = f"{aggregate['xray_direct_count']}/{aggregate['mesh_count']}"
        representative_path = representative.GetPath() if representative else "<none>"
        terminal = cls._xray_connection(
            material.GetSurfaceOutput("mdl") if material else None
        )
        part_a_emission = bool(part_a.GetInput("emission_color")) if part_a else False
        part_b_emission = bool(part_b.GetInput("emission_color")) if part_b else False
        falloff_base = cls._xray_connection(
            falloff.GetInput("base") if falloff else None
        )
        falloff_blend = cls._xray_connection(
            falloff.GetInput("blend") if falloff else None
        )
        session_representative = (
            bool(session.GetPrimAtPath(representative.GetPath()))
            if representative
            else False
        )
        from pxr import Sdf

        material_fragment = cls._xray_session_fragment(stage, None, Sdf)
        return "\n".join(
            (
                "DTRS X-Ray SurfaceFalloff isolation",
                "  configured: "
                "PartA=yellow opaque; PartB=blue opaque; roughness=0.4; emission=off",
                probe_status,
                f"  expected: {expected}",
                "  after_apply:",
                f"    xray_material_defined: {material_defined}",
                f"    xray_direct_bindings: {direct_bindings}",
                f"    representative: {representative_path}",
                f"    representative_binding: {representative_binding}",
                f"    representative_binding_owner: {binding_owner}",
                f"    terminal: {terminal}",
                "    PartA: "
                f"color={cls._xray_input_value(part_a, 'diffuse_reflection_color')}; "
                f"opacity_enabled={cls._xray_input_value(part_a, 'enable_opacity')}; "
                f"emission_input={part_a_emission}",
                "    PartB: "
                f"color={cls._xray_input_value(part_b, 'diffuse_reflection_color')}; "
                f"opacity_enabled={cls._xray_input_value(part_b, 'enable_opacity')}; "
                f"emission_input={part_b_emission}",
                "    SurfaceFalloff: "
                f"asset={cls._xray_shader_asset(falloff)}; "
                f"base={falloff_base}; "
                f"blend={falloff_blend}; "
                f"facing={cls._xray_input_value(falloff, 'facing_weight')}; "
                f"edge={cls._xray_input_value(falloff, 'edge_weight')}; "
                f"bias={cls._xray_input_value(falloff, 'blend_bias')}",
                registry_inspection,
                "    authored_ports:",
                *authored_ports,
                "    authored_usda:",
                material_fragment,
                "    session_owns: "
                f"material={bool(session.GetPrimAtPath(cls.XRAY_MATERIAL_PATH))}; "
                f"representative={session_representative}",
                f"  result: {result.message}",
            )
        )

    @classmethod
    def _format_xray_surface_falloff_registry(cls, falloff, UsdMdl=None) -> str:
        """Return the narrow registry/type diagnostic for Surface Falloff."""

        if not falloff:
            return "    registry: surface_falloff=<missing>"
        try:
            if UsdMdl is None:
                import omni.UsdMdl as UsdMdl

            node = UsdMdl.RegistryUtils.GetShaderNodeForPrim(falloff.GetPrim())
            if not node:
                return "    registry: surface_falloff=<unresolved>"
            resolved = (
                f"module={node.GetModuleUsdIdentifier()}; "
                f"subIdentifier={node.GetSubIdentifier()}; "
                f"signature={node.GetNameWithSignature()}"
            )
            lines = [f"    registry: {resolved}"]
            for name, definition, authored in (
                ("base", node.GetShaderInput("base"), falloff.GetInput("base")),
                ("blend", node.GetShaderInput("blend"), falloff.GetInput("blend")),
                ("out", node.GetShaderOutput("out"), falloff.GetOutput("out")),
            ):
                declared_type = (
                    cls._sdf_type_from_sdr_property(definition)
                    if definition
                    else "<missing>"
                )
                declared_sdr_type = definition.GetType() if definition else "<missing>"
                declared_metadata = definition.GetMetadata() if definition else {}
                authored_type = authored.GetTypeName() if authored else "<missing>"
                authored_metadata = (
                    authored.GetAttr().GetMetadata("sdrMetadata") if authored else {}
                )
                lines.append(
                    f"      {name}: registry_sdf={declared_type}; "
                    f"registry_sdr={declared_sdr_type}; "
                    f"registry_sdrMetadata={declared_metadata}; "
                    f"authored_sdf={authored_type}; "
                    f"authored_sdrMetadata={authored_metadata}"
                )
            return "\n".join(lines)
        except Exception as error:
            return f"    registry: inspection_failed={error}"

    @classmethod
    def _xray_surface_falloff_authored_port_lines(cls, material, part_a, falloff):
        """Describe only authored MDL material ports and their exact connections."""

        return tuple(
            cls._xray_authored_port_line(name, port)
            for name, port in (
                ("PartA.outputs:out", part_a.GetOutput("out") if part_a else None),
                (
                    "SurfaceFalloff.inputs:base",
                    falloff.GetInput("base") if falloff else None,
                ),
                (
                    "SurfaceFalloff.inputs:blend",
                    falloff.GetInput("blend") if falloff else None,
                ),
                (
                    "SurfaceFalloff.outputs:out",
                    falloff.GetOutput("out") if falloff else None,
                ),
                (
                    "Material.outputs:mdl:surface",
                    material.GetSurfaceOutput("mdl") if material else None,
                ),
            )
        )

    @classmethod
    def _xray_authored_port_line(cls, name: str, port) -> str:
        if not port:
            return f"      {name}: <missing>"
        return (
            f"      {name}: sdf={port.GetTypeName()}; "
            f"sdrMetadata={port.GetAttr().GetMetadata('sdrMetadata')}; "
            f"connection={cls._xray_connection(port)}"
        )

    def clear_xray_material_in_kit(self) -> XRayApplyResult:
        """Clear transient X-Ray bindings without changing persisted UI settings."""

        import omni.usd
        from pxr import Usd, UsdShade

        stage = omni.usd.get_context().get_stage()
        if not stage:
            return XRayApplyResult(True, "X-Ray is inactive; no open stage.")
        previous_target = stage.GetEditTarget()
        stage.SetEditTarget(stage.GetSessionLayer())
        try:
            removed_count = self._clear_xray_session_overrides(stage, Usd, UsdShade)
        finally:
            stage.SetEditTarget(previous_target)
        return XRayApplyResult(
            True,
            "X-Ray disabled; original chassis materials restored.",
            removed_count,
        )

    def log_xray_material_state_in_kit(
        self,
        requested_selected: bool,
        result: XRayApplyResult | None = None,
        event_label: str = "Apply",
        state: str | None = None,
    ) -> None:
        """Write one compact, composed-state X-Ray diagnostic report."""

        import carb
        import omni.usd
        from pxr import Sdf, Usd, UsdShade

        stage = omni.usd.get_context().get_stage()
        result_message = result.message if result else "No stage mutation has run."
        if not stage:
            carb.log_warn(
                "DTRS X-Ray diagnostic\n"
                f"  event: {event_label}\n"
                f"  state: {state or '<unknown>'}\n"
                f"  requested_selected: {requested_selected}\n"
                f"  result: {result_message}\n"
                "  stage: <none>"
            )
            return
        carb.log_warn(
            self._format_xray_material_state(
                stage,
                requested_selected,
                XRayApplyResult(True, result_message),
                Sdf,
                Usd,
                UsdShade,
                event_label,
                state,
                getattr(self, "_xray_last_authoring_edit_target", "<not authored>"),
            )
        )

    @classmethod
    def _format_xray_material_state(
        cls,
        stage,
        requested_selected: bool,
        result: XRayApplyResult,
        Sdf,
        Usd,
        UsdShade,
        event_label: str = "Apply",
        state: str | None = None,
        authoring_edit_target: str = "<not authored>",
    ) -> str:
        """Format A/B/C evidence without dumping all chassis meshes."""

        actual_state = state or ("B" if requested_selected else "C")
        root = stage.GetPrimAtPath(cls.XRAY_CHASSIS_ROOT_PATH)
        material = UsdShade.Material.Get(stage, cls.XRAY_MATERIAL_PATH)
        material_defined = bool(material and material.GetPrim().IsValid())
        representative = cls._xray_diagnostic_representative_mesh(
            stage, root, Usd, UsdShade
        )
        aggregate = cls._xray_binding_aggregate(root, Usd, UsdShade)
        original = cls._xray_material_fingerprint(stage, representative, UsdShade)
        if actual_state == "A":
            cls._xray_diagnostic_baseline = original
            cls._xray_diagnostic_baseline_root_dirty = stage.GetRootLayer().dirty
        comparison = cls._xray_fingerprint_comparison(actual_state, original)
        lines = [
            "DTRS X-Ray diagnostic",
            f"  event: {event_label}",
            f"  state: {actual_state}",
            f"  requested_selected: {requested_selected}",
            f"  result: {result.message}",
            "  composition:",
            f"    root_layer: {stage.GetRootLayer().identifier}",
            f"    root_dirty: {stage.GetRootLayer().dirty}",
            f"    session_layer: {stage.GetSessionLayer().identifier}",
            f"    current_edit_target: {stage.GetEditTarget().GetLayer().identifier}",
            f"    xray_authoring_edit_target: {authoring_edit_target}",
            "    root_dirty_vs_A: "
            + (
                "baseline captured"
                if actual_state == "A"
                else (
                    str(
                        stage.GetRootLayer().dirty
                        == cls._xray_diagnostic_baseline_root_dirty
                    )
                    if cls._xray_diagnostic_baseline_root_dirty is not None
                    else "baseline unavailable"
                )
            ),
            "  chassis_bindings:",
            f"    mesh_count: {aggregate['mesh_count']}",
            f"    xray_direct_count: {aggregate['xray_direct_count']}",
            f"    resolved: {aggregate['resolved']}",
            "  representative_mesh: "
            f"{representative.GetPath() if representative else '<none>'}",
            f"  representative_binding: {original['binding']}",
            f"  representative_binding_owners: {original['binding_owners']}",
            f"  effective_material: {original['material']}",
            "  effective_mdl: "
            f"{original['mdl_source']} | {original['mdl_subidentifier']}",
            f"  effective_base_color: {original['base_color']}",
            f"  effective_opacity: {original['opacity']}",
            f"  effective_roughness: {original['roughness']}",
            f"  effective_emission: {original['emission']}",
            f"  A_vs_{actual_state}: {comparison}",
        ]
        if material_defined:
            lines.extend(
                cls._xray_graph_diagnostic_lines(
                    stage, material, representative, Sdf, UsdShade
                )
            )
        return "\n".join(lines)

    @classmethod
    def _xray_diagnostic_representative_mesh(cls, stage, root, Usd, UsdShade):
        """Choose one stable mesh that resolves to base_lod00_mat before X-Ray."""

        if cls._xray_diagnostic_representative_path:
            prim = stage.GetPrimAtPath(cls._xray_diagnostic_representative_path)
            if prim and prim.IsValid() and prim.GetTypeName() == "Mesh":
                return prim
        fallback = None
        if root and root.IsValid():
            for prim in Usd.PrimRange(root):
                if prim.GetTypeName() != "Mesh":
                    continue
                fallback = fallback or prim
                material, _binding = UsdShade.MaterialBindingAPI(
                    prim
                ).ComputeBoundMaterial()
                if (
                    material
                    and str(material.GetPath()) == cls.XRAY_SOURCE_MATERIAL_PATH
                ):
                    cls._xray_diagnostic_representative_path = str(prim.GetPath())
                    return prim
        if fallback:
            cls._xray_diagnostic_representative_path = str(fallback.GetPath())
        return fallback

    @classmethod
    def _xray_binding_aggregate(cls, root, Usd, UsdShade) -> dict[str, object]:
        """Return counts only; per-mesh dumps hide the actual material evidence."""

        resolved: Counter[str] = Counter()
        mesh_count = 0
        xray_direct_count = 0
        if root and root.IsValid():
            for prim in Usd.PrimRange(root):
                if prim.GetTypeName() != "Mesh":
                    continue
                mesh_count += 1
                binding_api = UsdShade.MaterialBindingAPI(prim)
                material, _binding = binding_api.ComputeBoundMaterial()
                path = str(material.GetPath()) if material else "<none>"
                resolved[path] += 1
                if str(cls.XRAY_MATERIAL_PATH) in {
                    str(path) for path in binding_api.GetDirectBindingRel().GetTargets()
                }:
                    xray_direct_count += 1
        resolved_summary = (
            ", ".join(f"{path} ({count})" for path, count in sorted(resolved.items()))
            or "<none>"
        )
        return {
            "mesh_count": mesh_count,
            "xray_direct_count": xray_direct_count,
            "resolved": resolved_summary,
        }

    @classmethod
    def _xray_material_fingerprint(cls, stage, mesh, UsdShade) -> dict[str, str]:
        """Capture only fields needed to compare original material A and C."""

        empty = {
            "binding": "<none>",
            "binding_owners": "<none>",
            "material": "<none>",
            "mdl_source": "<none>",
            "mdl_subidentifier": "<none>",
            "base_color": "<none>",
            "opacity": "<none>",
            "roughness": "<none>",
            "emission": "<none>",
        }
        if not mesh:
            return empty
        binding_api = UsdShade.MaterialBindingAPI(mesh)
        material, _binding = binding_api.ComputeBoundMaterial()
        direct_rel = binding_api.GetDirectBindingRel()
        owners = cls._xray_property_owners(direct_rel)
        if not material or not material.GetPrim().IsValid():
            return {**empty, "binding_owners": owners}
        material_path = str(material.GetPath())
        terminal = material.GetSurfaceOutput("mdl")
        source = cls._xray_connection(terminal)
        shader = None
        if terminal:
            connected = terminal.GetConnectedSource()
            if connected:
                shader = UsdShade.Shader(connected[0].GetPrim())
        basecolor_shader = UsdShade.Shader.Get(stage, f"{material_path}/basecolor")
        basecolor_file = cls._xray_input_value(basecolor_shader, "file")
        return {
            "binding": material_path,
            "binding_owners": owners,
            "material": material_path,
            "mdl_source": cls._xray_shader_asset(shader),
            "mdl_subidentifier": cls._xray_shader_subidentifier(shader),
            "base_color": basecolor_file if basecolor_file != "<missing>" else source,
            "opacity": cls._xray_input_value(shader, "geometry_opacity"),
            "roughness": cls._xray_input_value(shader, "diffuse_reflection_roughness"),
            "emission": (
                f"color={cls._xray_input_value(shader, 'emission_color')}; "
                f"intensity={cls._xray_input_value(shader, 'emission_intensity')}"
            ),
        }

    @classmethod
    def _xray_fingerprint_comparison(
        cls,
        state: str,
        current: dict[str, str],
    ) -> str:
        """Compare only the baseline and post-removal source-material evidence."""

        if state == "A":
            return "baseline captured"
        if state != "C":
            return "not applicable"
        if cls._xray_diagnostic_baseline is None:
            return "baseline unavailable; use Load, then repeat A/B/C"
        differences = [
            key
            for key, value in current.items()
            if cls._xray_diagnostic_baseline.get(key) != value
        ]
        return (
            "identical" if not differences else "different: " + ", ".join(differences)
        )

    @classmethod
    def _xray_graph_diagnostic_lines(
        cls, stage, material, representative, Sdf, UsdShade
    ) -> list[str]:
        """Expose composed MDL connections and the small session-layer fragment."""

        part_a = UsdShade.Shader.Get(stage, f"{cls.XRAY_MATERIAL_PATH}/PartA")
        part_b = UsdShade.Shader.Get(stage, f"{cls.XRAY_MATERIAL_PATH}/PartB")
        falloff = UsdShade.Shader.Get(stage, f"{cls.XRAY_MATERIAL_PATH}/SurfaceFalloff")
        terminal = material.GetSurfaceOutput("mdl")
        session = stage.GetSessionLayer()
        representative_session_spec = (
            session.GetPrimAtPath(representative.GetPath()) if representative else None
        )
        part_b_emission_intensity = cls._xray_input_value(part_b, "emission_intensity")
        part_b_base_owner = cls._xray_property_owners(
            part_b.GetInput("diffuse_reflection_color")
        )
        part_b_emission_owner = cls._xray_property_owners(
            part_b.GetInput("emission_color")
        )
        lines = [
            "  xray_graph:",
            f"    material.outputs:mdl:surface -> {cls._xray_connection(terminal)}",
            f"    terminal_owner: {cls._xray_property_owners(terminal)}",
            "    session_specs: "
            f"material={bool(session.GetPrimAtPath(material.GetPath()))}; "
            f"representative_binding={bool(representative_session_spec)}",
            "    SurfaceFalloff: "
            f"asset={cls._xray_shader_asset(falloff)}; "
            f"subIdentifier={cls._xray_shader_subidentifier(falloff)}; "
            f"output={cls._xray_output(falloff, 'out')}",
            f"      base -> {cls._xray_connection(falloff.GetInput('base'))}",
            f"      blend -> {cls._xray_connection(falloff.GetInput('blend'))}",
            "      weights: "
            f"facing={cls._xray_input_value(falloff, 'facing_weight')}; "
            f"edge={cls._xray_input_value(falloff, 'edge_weight')}; "
            f"bias={cls._xray_input_value(falloff, 'blend_bias')}",
            "    PartA: "
            f"asset={cls._xray_shader_asset(part_a)}; "
            f"subIdentifier={cls._xray_shader_subidentifier(part_a)}; "
            f"output={cls._xray_output(part_a, 'out')}",
            "    PartB: "
            f"asset={cls._xray_shader_asset(part_b)}; "
            f"subIdentifier={cls._xray_shader_subidentifier(part_b)}; "
            f"output={cls._xray_output(part_b, 'out')}",
            "      composed: "
            f"base_color={cls._xray_input_value(part_b, 'diffuse_reflection_color')}; "
            f"emission_color={cls._xray_input_value(part_b, 'emission_color')}; "
            f"emission_intensity={part_b_emission_intensity}",
            "    owners: "
            f"material={cls._xray_prim_owners(material.GetPrim())}; "
            f"PartA={cls._xray_prim_owners(part_a.GetPrim())}; "
            f"PartB={cls._xray_prim_owners(part_b.GetPrim())}; "
            f"SurfaceFalloff={cls._xray_prim_owners(falloff.GetPrim())}",
            "    input_owners: "
            f"base={cls._xray_property_owners(falloff.GetInput('base'))}; "
            f"blend={cls._xray_property_owners(falloff.GetInput('blend'))}; "
            f"PartB.base={part_b_base_owner}; "
            f"PartB.emission={part_b_emission_owner}",
            "  session_fragment:",
            cls._xray_session_fragment(stage, representative, Sdf),
        ]
        return lines

    @staticmethod
    def _xray_input_value(shader, name: str) -> str:
        shader_input = shader.GetInput(name) if shader else None
        return str(shader_input.Get()) if shader_input else "<missing>"

    @staticmethod
    def _xray_output(shader, name: str) -> str:
        output = shader.GetOutput(name) if shader else None
        if not output:
            return "<missing>"
        return (
            f"{output.GetBaseName()} ({output.GetTypeName()}, {output.GetRenderType()})"
        )

    @staticmethod
    def _xray_connection(connectable) -> str:
        if not connectable:
            return "<none>"
        connected = connectable.GetConnectedSource()
        if not connected:
            return "<none>"
        source, name, source_type = connected
        return f"{source.GetPrim().GetPath()}.outputs:{name} ({source_type})"

    @staticmethod
    def _xray_shader_asset(shader) -> str:
        if not shader:
            return "<none>"
        asset = shader.GetSourceAsset("mdl")
        return str(asset.path) if asset else "<none>"

    @staticmethod
    def _xray_shader_subidentifier(shader) -> str:
        return shader.GetSourceAssetSubIdentifier("mdl") if shader else "<none>"

    @staticmethod
    def _xray_property_owners(property_api) -> str:
        if not property_api:
            return "<none>"
        property_spec = (
            property_api.GetAttr() if hasattr(property_api, "GetAttr") else property_api
        )
        stack = property_spec.GetPropertyStack() if property_spec else []
        return ", ".join(spec.layer.identifier for spec in stack) or "<none>"

    @staticmethod
    def _xray_prim_owners(prim) -> str:
        if not prim:
            return "<none>"
        return (
            ", ".join(spec.layer.identifier for spec in prim.GetPrimStack()) or "<none>"
        )

    @classmethod
    def _xray_session_fragment(cls, stage, representative, Sdf) -> str:
        session = stage.GetSessionLayer()
        fragment = Sdf.Layer.CreateAnonymous("DTRS_XRayDiagnostic.usda")
        for path in (
            Sdf.Path(cls.XRAY_MATERIAL_PATH),
            representative.GetPath() if representative else None,
        ):
            if path and session.GetPrimAtPath(path):
                for ancestor in path.GetPrefixes()[:-1]:
                    if ancestor != Sdf.Path.absoluteRootPath:
                        Sdf.CreatePrimInLayer(fragment, ancestor)
                Sdf.CopySpec(session, path, fragment, path)
        exported = fragment.ExportToString().strip()
        return "\n".join(f"    {line}" for line in exported.splitlines())

    @classmethod
    def _clear_xray_session_overrides(cls, stage, Usd, UsdShade) -> int:
        """Remove only bindings owned by X-Ray, preserving runtime state."""

        removed_count = 0
        xray_path = str(cls.XRAY_MATERIAL_PATH)
        root = stage.GetPrimAtPath(cls.XRAY_CHASSIS_ROOT_PATH)
        if not root or not root.IsValid():
            stage.RemovePrim(cls.XRAY_MATERIAL_PATH)
            return removed_count
        for prim in Usd.PrimRange(root):
            if prim.GetTypeName() != "Mesh":
                continue
            direct_binding = UsdShade.MaterialBindingAPI(prim).GetDirectBindingRel()
            target_paths = {str(path) for path in direct_binding.GetTargets()}
            if xray_path in target_paths:
                # Removing the SdfPrimSpec directly updates composition but bypasses
                # the UsdStage change notice that Hydra needs to refresh bindings.
                # This public API removes only the session-layer relation spec and
                # notifies renderer clients, revealing the weaker authored binding.
                direct_binding.ClearTargets(True)
                original_material, _binding = UsdShade.MaterialBindingAPI(
                    prim
                ).ComputeBoundMaterial()
                if original_material and original_material.GetPrim().IsValid():
                    # RTX retains the prior compiled material when a direct binding
                    # merely disappears. Re-authoring the already resolved source
                    # material provides the renderer with an explicit replacement
                    # without changing the source asset or visibility.
                    UsdShade.MaterialBindingAPI.Apply(prim).Bind(original_material)
                removed_count += 1
        stage.RemovePrim(cls.XRAY_MATERIAL_PATH)
        return removed_count

    @classmethod
    def _define_xray_material(
        cls,
        stage,
        surface_falloff_weights: tuple[float, float],
        blend_part: str,
        Gf,
        Sdf,
        UsdShade,
        UsdMdl=None,
    ):
        """Author the temporary opaque yellow/blue Surface Falloff isolation graph."""

        if UsdMdl is None:
            import omni.UsdMdl as UsdMdl

        material_path = Sdf.Path(cls.XRAY_MATERIAL_PATH)
        material = UsdShade.Material.Define(stage, material_path)
        part_a = cls._define_omni_surface_part(
            stage,
            material_path.AppendChild("PartA"),
            cls.XRAY_ISOLATION_PART_A_COLOR,
            cls.XRAY_ISOLATION_ROUGHNESS,
            Gf,
            Sdf,
            UsdShade,
        )
        part_b = cls._define_omni_surface_part(
            stage,
            material_path.AppendChild("PartB"),
            cls.XRAY_ISOLATION_PART_B_COLOR,
            cls.XRAY_ISOLATION_ROUGHNESS,
            Gf,
            Sdf,
            UsdShade,
        )
        falloff = UsdShade.Shader.Define(
            stage, material_path.AppendChild("SurfaceFalloff")
        )
        falloff.CreateImplementationSourceAttr().Set(UsdShade.Tokens.sourceAsset)
        falloff.SetSourceAsset(Sdf.AssetPath("nvidia/core_definitions.mdl"), "mdl")
        falloff.SetSourceAssetSubIdentifier("surface_falloff", "mdl")
        shader_node = UsdMdl.RegistryUtils.GetShaderNodeForPrim(falloff.GetPrim())
        if not shader_node:
            raise RuntimeError(
                "MDL registry could not resolve "
                "nvidia/core_definitions.mdl::surface_falloff."
            )
        falloff.SetSdrMetadata(shader_node.GetMetadata())
        cls._create_mdl_registry_input(
            falloff, shader_node, "base", Sdf
        ).ConnectToSource(part_a.ConnectableAPI(), "out")
        blend_source = part_a if blend_part == "PartA" else part_b
        cls._create_mdl_registry_input(
            falloff, shader_node, "blend", Sdf
        ).ConnectToSource(blend_source.ConnectableAPI(), "out")
        facing_weight, edge_weight = surface_falloff_weights
        falloff.CreateInput("facing_weight", Sdf.ValueTypeNames.Float).Set(
            facing_weight
        )
        falloff.CreateInput("edge_weight", Sdf.ValueTypeNames.Float).Set(edge_weight)
        falloff.CreateInput("blend_bias", Sdf.ValueTypeNames.Float).Set(
            cls.XRAY_ISOLATION_BLEND_BIAS
        )
        output = falloff.CreateOutput("out", Sdf.ValueTypeNames.Token)
        output.SetRenderType("material")
        material.CreateSurfaceOutput("mdl").ConnectToSource(
            falloff.ConnectableAPI(), "out"
        )
        return material

    @staticmethod
    def _create_mdl_registry_input(shader, shader_node, name: str, Sdf):
        """Create one MDL input with the exact Sdr-declared type and metadata."""

        property_definition = shader_node.GetShaderInput(name)
        if not property_definition:
            raise RuntimeError(f"MDL registry has no '{name}' input.")
        sdf_type = RuntimeController._sdf_type_from_sdr_property(property_definition)
        if not sdf_type:
            raise RuntimeError(f"MDL registry has no Sdf type for '{name}'.")
        shader_input = shader.CreateInput(name, sdf_type)
        sdr_metadata = property_definition.GetMetadata()
        if sdr_metadata:
            shader_input.GetAttr().SetMetadata("sdrMetadata", sdr_metadata)
        return shader_input

    @staticmethod
    def _sdf_type_from_sdr_property(property_definition):
        """Accept both legacy tuple and current SdfTypeIndicator Sdr bindings."""

        type_indicator = property_definition.GetTypeAsSdfType()
        if hasattr(type_indicator, "GetSdfType"):
            return type_indicator.GetSdfType()
        return type_indicator[0]

    @staticmethod
    def _define_omni_surface_part(
        stage,
        path,
        base_color,
        roughness: float,
        Gf,
        Sdf,
        UsdShade,
    ):
        shader = UsdShade.Shader.Define(stage, path)
        shader.CreateImplementationSourceAttr().Set(UsdShade.Tokens.sourceAsset)
        shader.SetSourceAsset(Sdf.AssetPath("OmniSurface.mdl"), "mdl")
        shader.SetSourceAssetSubIdentifier("OmniSurface", "mdl")
        shader.CreateInput("diffuse_reflection_color", Sdf.ValueTypeNames.Color3f).Set(
            Gf.Vec3f(*base_color)
        )
        shader.CreateInput(
            "diffuse_reflection_roughness", Sdf.ValueTypeNames.Float
        ).Set(roughness)
        shader.CreateInput(
            "specular_reflection_roughness", Sdf.ValueTypeNames.Float
        ).Set(roughness)
        shader.CreateInput("enable_opacity", Sdf.ValueTypeNames.Bool).Set(False)
        output = shader.CreateOutput("out", Sdf.ValueTypeNames.Token)
        output.SetRenderType("material")
        return shader

    @classmethod
    def _bind_xray_material_to_chassis(
        cls,
        stage,
        root,
        material,
        Usd,
        UsdShade,
    ) -> int:
        target_count = 0
        for prim in Usd.PrimRange(root):
            if prim.GetTypeName() != "Mesh":
                continue
            UsdShade.MaterialBindingAPI.Apply(prim).Bind(material)
            target_count += 1
        return target_count

    @staticmethod
    def _apply_normal_map_scale(
        stage,
        normal_map_scale: float,
        Gf,
        Sdf,
        UsdShade,
    ) -> int:
        """Set only UV textures directly connected to PreviewSurface normal inputs."""

        texture_paths: set[str] = set()
        previous_target = stage.GetEditTarget()
        stage.SetEditTarget(stage.GetSessionLayer())
        try:
            for prim in stage.Traverse():
                shader = UsdShade.Shader(prim)
                if shader.GetIdAttr().Get() != "UsdPreviewSurface":
                    continue
                normal_input = shader.GetInput("normal")
                if not normal_input:
                    continue
                for connection in normal_input.GetAttr().GetConnections():
                    texture = UsdShade.Shader(
                        stage.GetPrimAtPath(connection.GetPrimPath())
                    )
                    if texture.GetIdAttr().Get() != "UsdUVTexture":
                        continue
                    texture_paths.add(str(texture.GetPath()))
            for texture_path in texture_paths:
                texture = UsdShade.Shader(stage.GetPrimAtPath(texture_path))
                texture.CreateInput("scale", Sdf.ValueTypeNames.Float4).Set(
                    Gf.Vec4f(
                        normal_map_scale,
                        normal_map_scale,
                        normal_map_scale,
                        1.0,
                    )
                )
        finally:
            stage.SetEditTarget(previous_target)
        return len(texture_paths)

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
        grid_path = Sdf.Path("/DTRS_Runtime/ReviewGrid")
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
            lighting_root = UsdGeom.Xform.Define(stage, "/DTRS_Runtime/Lighting")
            lighting_root.GetPrim().SetActive(True)

            if not hdri_path.exists():
                dome_prim = stage.GetPrimAtPath("/DTRS_Runtime/Lighting/DomeLight")
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

            legacy_key_prim = stage.GetPrimAtPath("/DTRS_Runtime/KeyLight")
            if legacy_key_prim:
                legacy_key_prim.SetActive(False)

            self._set_review_key_light(stage, lighting, Gf, UsdGeom, UsdLux)

            dome_light = UsdLux.DomeLight.Define(
                stage,
                "/DTRS_Runtime/Lighting/DomeLight",
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
        key_path = "/DTRS_Runtime/Lighting/ReviewKeyLight"
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
