"""Runtime commands for Digital Twin Runtime Suite."""

from __future__ import annotations

import asyncio
import math
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
    XRayFresnelProbeConfig,
    XRayMaterialConfig,
    chassis_presentation_with_operator_state,
    format_runtime_override,
)
from digital_twin_runtime_suite.app.front_panel_indicators import (
    front_panel_indicator_state,
)
from digital_twin_runtime_suite.app.flow.performance import (
    FlowPerformanceSample,
    ViewportPerformanceSample,
    capture_viewport_performance_sample,
)
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
class XRayRPrimRebuildProbe:
    target_path: str
    binding_before_rebuild: str
    active_before: bool
    prim_disappeared: bool | None = None
    active_opinion_removed: bool | None = None


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
    XRAY_MATERIAL_PATH = "/DTRS_Runtime/Looks/XRayLifecycleControl"
    XRAY_AB_RENDER_PROBE_PATH = (
        "/blackwell_rig/chassis/geo/render/chassis/front_side/face_grill/face_grill"
    )
    XRAY_PROBE_ROOT_PATH = "/DTRS_Runtime/Debug/XRayProbe01"
    XRAY_PROBE_MATERIAL_PATH = "/DTRS_Runtime/Debug/Looks/FresnelProbe01"
    XRAY_PROBE_SERVER_PATH = "/blackwell_rig"
    # Probe 01 is deliberately derived only from the server extent.  It must
    # stay large enough to inspect in the unchanged review-camera framing, but
    # must never fall back to a hard-coded world-space size.
    XRAY_PROBE_SIZE_FRACTION = 0.64
    # The imported server carries its geometry under render/proxy purposes;
    # default alone produces an empty BBoxCache range for this asset.
    XRAY_PROBE_BOUND_PURPOSES = (
        "default_",
        "render",
        "proxy",
        "guide",
    )
    XRAY_PROBE_SPHERE_LONGITUDE_SEGMENTS = 64
    XRAY_PROBE_SPHERE_LATITUDE_SEGMENTS = 32
    XRAY_PROBE_PERFORMANCE_SAMPLE_INTERVAL_SECONDS = 0.5
    XRAY_PROBE_PERFORMANCE_LOG_INTERVAL_SECONDS = 10.0
    XRAY_MATERIAL_PERFORMANCE_SAMPLE_INTERVAL_SECONDS = 0.5
    XRAY_MATERIAL_PERFORMANCE_LOG_INTERVAL_SECONDS = 10.0

    def __init__(self, config_path: Path | str):
        self._config_path = Path(config_path)
        # Snapshots contain only a previous Session Layer material-binding
        # property spec, never prim or stage references.  They make X-Ray an
        # overlay rather than an owner of somebody else's Session opinion.
        self._xray_session_binding_layer_id: str | None = None
        self._xray_session_binding_snapshots: dict[str, object] = {}
        self._xray_baseline_composed_bindings: dict[str, str] = {}
        self._xray_last_lifecycle_diagnostics: list[dict[str, object]] = []
        self._front_panel_indicator_last_snapshot = None
        self._front_panel_indicator_last_state = None
        self._xray_probe_visibility_state: tuple[bool, object | None] | None = None
        self._xray_probe_server_bbox_snapshot = None
        self._xray_probe_last_values = None
        self._xray_probe_live_camera_sync_updates = 0
        self._xray_probe_performance_started_at: float | None = None
        self._xray_probe_performance_next_sample_at: float | None = None
        self._xray_probe_performance_next_log_at: float | None = None
        self._xray_probe_performance_interval_started_at: float | None = None
        self._xray_probe_performance_samples: list[ViewportPerformanceSample] = []
        self._xray_material_performance_started_at: float | None = None
        self._xray_material_performance_next_sample_at: float | None = None
        self._xray_material_performance_next_log_at: float | None = None
        self._xray_material_performance_interval_started_at: float | None = None
        self._xray_material_performance_samples: list[ViewportPerformanceSample] = []
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

    def save_xray_fresnel_probe_override(
        self, fresnel_probe: XRayFresnelProbeConfig
    ) -> Path:
        """Persist debug probe controls without retaining its transient USD state."""

        presentation = replace(
            self.config.chassis_presentation,
            materials=replace(
                self.config.chassis_presentation.materials,
                xray_fresnel_probe=fresnel_probe,
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
        self._front_panel_indicator_last_snapshot = snapshot
        self._front_panel_indicator_last_state = state
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
    ) -> XRayApplyResult:
        """Apply the X-Ray lifecycle boundary without authoring rejected shading."""

        import carb
        import omni.usd
        from pxr import Gf, Sdf, Usd, UsdShade

        stage = omni.usd.get_context().get_stage()
        if not stage:
            return XRayApplyResult(False, "X-Ray skipped: no open stage.")

        previous_target = stage.GetEditTarget()
        stage.SetEditTarget(stage.GetSessionLayer())
        try:
            if not xray.chassis_selected:
                removed_count, diagnostics = self._clear_xray_session_overrides(
                    stage, Sdf, Usd, UsdShade
                )
                led_reapplied, led_matches_current_state = (
                    self._reapply_front_panel_indicator_current_state(
                        stage, Gf, Sdf, Usd, UsdShade
                    )
                )
                self._log_xray_lifecycle_diagnostic(
                    carb,
                    action="OFF",
                    formatter=lambda: self._format_xray_lifecycle_diagnostics(
                        "OFF",
                        diagnostics,
                        led_current_state_reapplied=led_reapplied,
                        led_binding_matches_current_state=led_matches_current_state,
                    ),
                )
                return XRayApplyResult(
                    True,
                    "X-Ray removed; original chassis materials restored.",
                    removed_count,
                )
            try:
                target_count, diagnostics = self._apply_xray_session_overrides(
                    stage, xray, Gf, Sdf, Usd, UsdShade
                )
            except RuntimeError as error:
                carb.log_error(
                    self._format_xray_lifecycle_diagnostics(
                        "ON FAILED", self._xray_last_lifecycle_diagnostics
                    )
                    + f"\n  error: {error}"
                )
                carb.log_error(f"DTRS X-Ray apply failed: {error}")
                return XRayApplyResult(False, f"X-Ray apply failed: {error}")
            self._start_xray_material_performance_sampler()
            self._log_xray_lifecycle_diagnostic(
                carb,
                action="ON",
                formatter=lambda: self._format_xray_lifecycle_diagnostics(
                    "ON", diagnostics
                ),
            )
            return XRayApplyResult(
                True,
                "X-Ray Part A control material applied.",
                target_count,
                used_fallback_color=True,
            )
        finally:
            stage.SetEditTarget(previous_target)

    def apply_xray_fresnel_probe_in_kit(
        self,
        values: tuple[
            tuple[float, float, float],
            tuple[float, float, float],
            float,
            float,
            float,
            float,
            float,
            float,
            float,
            float,
            float,
            float,
        ],
        *,
        rebuild: bool,
    ) -> XRayApplyResult:
        """Author or update the non-persistent Custom MDL Fresnel probe."""
        import carb
        import omni.usd
        from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade

        stage = omni.usd.get_context().get_stage()
        if not stage:
            return XRayApplyResult(False, "Fresnel probe skipped: no open stage.")
        server = stage.GetPrimAtPath(self.XRAY_PROBE_SERVER_PATH)
        if not server or not server.IsValid():
            return XRayApplyResult(
                False, "Fresnel probe skipped: server root not found."
            )
        previous_target = stage.GetEditTarget()
        stage.SetEditTarget(stage.GetSessionLayer())
        try:
            camera_position = None
            if rebuild or not stage.GetPrimAtPath(self.XRAY_PROBE_ROOT_PATH):
                camera_position = self._xray_fresnel_probe_camera_position(
                    stage, Usd, UsdGeom
                )
                if camera_position is None:
                    return XRayApplyResult(
                        False, "Fresnel probe skipped: review camera not found."
                    )
                self._clear_xray_fresnel_probe(stage)
                # BBoxCache prunes a subtree with resolved visibility=invisible.
                # Snapshot bounds before the probe's Session Layer hides the server.
                bbox = self._xray_fresnel_probe_server_bbox(server, Usd, UsdGeom)
                if bbox is None:
                    return XRayApplyResult(
                        False, "Fresnel probe skipped: server bounds are unavailable."
                    )
                self._xray_probe_server_bbox_snapshot = bbox
                self._capture_and_hide_xray_probe_server(stage, Usd, UsdGeom)
                # The review camera is already framed for the server. Keep the
                # isolated objects small enough to fit that existing framing;
                # Probe 01 must not move the camera after sampling it for MDL.
                cube, sphere = self._define_xray_fresnel_probe_geometry(
                    stage, bbox, Gf, UsdGeom
                )
                material = self._define_xray_fresnel_probe_material(
                    stage, Sdf, UsdShade
                )
                for prim in (cube.GetPrim(), sphere.GetPrim()):
                    UsdShade.MaterialBindingAPI.Apply(prim).Bind(material)
                self._xray_probe_live_camera_sync_updates = 0
                self._start_xray_fresnel_probe_performance_sampler()
            self._set_xray_fresnel_probe_values(
                stage,
                values,
                Gf,
                Sdf,
                UsdShade,
                camera_position=camera_position,
            )
            self._xray_probe_last_values = values
            self._log_xray_fresnel_probe_diagnostic(
                carb,
                action="Probe 01" if rebuild else "Apply Probe Parameters",
                formatter=lambda: self._format_xray_fresnel_probe_state(
                    stage,
                    Usd,
                    UsdGeom,
                    UsdShade,
                    action="Probe 01" if rebuild else "Apply Probe Parameters",
                    values=values,
                ),
            )
            return XRayApplyResult(True, "Custom MDL Fresnel Probe 01 ready.", 2)
        finally:
            stage.SetEditTarget(previous_target)

    def clear_xray_fresnel_probe_in_kit(self) -> XRayApplyResult:
        import carb
        import omni.usd
        from pxr import Usd, UsdGeom, UsdShade

        stage = omni.usd.get_context().get_stage()
        if not stage:
            self._stop_xray_fresnel_probe_performance_sampler()
            return XRayApplyResult(True, "Fresnel probe is inactive; no open stage.")
        previous_target = stage.GetEditTarget()
        stage.SetEditTarget(stage.GetSessionLayer())
        try:
            prior_visibility_state = self._xray_probe_visibility_state
            camera_before_clear = self._xray_fresnel_probe_camera_snapshot(
                stage, Usd, UsdGeom, UsdShade
            )
            self._clear_xray_fresnel_probe(stage)
            review_camera_after_clear = self._xray_probe_diagnostic_value(
                lambda: self._xray_fresnel_probe_camera_position(stage, Usd, UsdGeom)
            )
            self._log_xray_fresnel_probe_diagnostic(
                carb,
                action="Clear Probe",
                formatter=lambda: self._format_xray_fresnel_probe_clear_state(
                    stage,
                    Usd,
                    UsdGeom,
                    UsdShade,
                    prior_visibility_state=prior_visibility_state,
                    camera_before_clear=camera_before_clear,
                    review_camera_after_clear=review_camera_after_clear,
                ),
            )
            self._stop_xray_fresnel_probe_performance_sampler()
        finally:
            stage.SetEditTarget(previous_target)
        return XRayApplyResult(True, "Custom MDL Fresnel Probe cleared.")

    def sync_xray_fresnel_probe_camera_in_kit(self) -> bool:
        """Update the active probe's MDL camera input only when it moved."""

        import omni.usd
        from pxr import Gf, Usd, UsdGeom, UsdShade

        stage = omni.usd.get_context().get_stage()
        if not stage:
            self._stop_xray_fresnel_probe_performance_sampler()
            return False
        probe_root = stage.GetPrimAtPath(self.XRAY_PROBE_ROOT_PATH)
        material_prim = stage.GetPrimAtPath(self.XRAY_PROBE_MATERIAL_PATH)
        if not (
            probe_root
            and probe_root.IsValid()
            and material_prim
            and material_prim.IsValid()
        ):
            self._stop_xray_fresnel_probe_performance_sampler()
            return False
        shader = UsdShade.Shader.Get(stage, f"{self.XRAY_PROBE_MATERIAL_PATH}/Shader")
        if not shader or not shader.GetPrim().IsValid():
            self._stop_xray_fresnel_probe_performance_sampler()
            return False
        camera_input = shader.GetInput("camera_position")
        if not camera_input or not camera_input.GetAttr().HasAuthoredValue():
            self._stop_xray_fresnel_probe_performance_sampler()
            return False
        self._advance_xray_fresnel_probe_performance_sampler()
        current_position = self._xray_fresnel_probe_camera_position(stage, Usd, UsdGeom)
        if current_position is None:
            return False
        authored_position = camera_input.Get()
        if authored_position is None or self._xray_probe_camera_positions_match(
            current_position, authored_position
        ):
            return False
        previous_target = stage.GetEditTarget()
        stage.SetEditTarget(stage.GetSessionLayer())
        try:
            camera_input.Set(Gf.Vec3f(*current_position))
            self._xray_probe_live_camera_sync_updates += 1
        finally:
            stage.SetEditTarget(previous_target)
        return True

    def _start_xray_fresnel_probe_performance_sampler(self) -> None:
        """Reset one HUD-backed sampler when a new Probe 01 is created."""

        initial_sample = self._capture_xray_fresnel_probe_performance_sample()
        started_at = initial_sample.captured_at
        self._xray_probe_performance_started_at = started_at
        self._xray_probe_performance_next_sample_at = (
            started_at + self.XRAY_PROBE_PERFORMANCE_SAMPLE_INTERVAL_SECONDS
        )
        self._xray_probe_performance_next_log_at = (
            started_at + self.XRAY_PROBE_PERFORMANCE_LOG_INTERVAL_SECONDS
        )
        self._xray_probe_performance_interval_started_at = started_at
        self._xray_probe_performance_samples = [initial_sample]

    def _stop_xray_fresnel_probe_performance_sampler(self) -> None:
        """Clear the probe sampler when its transient material no longer exists."""

        self._xray_probe_performance_started_at = None
        self._xray_probe_performance_next_sample_at = None
        self._xray_probe_performance_next_log_at = None
        self._xray_probe_performance_interval_started_at = None
        self._xray_probe_performance_samples = []

    @staticmethod
    def _capture_xray_fresnel_probe_performance_sample() -> ViewportPerformanceSample:
        return capture_viewport_performance_sample()

    def _advance_xray_fresnel_probe_performance_sampler(self) -> None:
        """Collect HUD samples in the existing camera-sync loop without a task."""

        started_at = self._xray_probe_performance_started_at
        next_sample_at = self._xray_probe_performance_next_sample_at
        next_log_at = self._xray_probe_performance_next_log_at
        if started_at is None or next_sample_at is None or next_log_at is None:
            self._start_xray_fresnel_probe_performance_sampler()
            return
        now = time.monotonic()
        if now < next_sample_at:
            return
        sample = self._capture_xray_fresnel_probe_performance_sample()
        self._xray_probe_performance_samples.append(sample)
        self._xray_probe_performance_next_sample_at = (
            now + self.XRAY_PROBE_PERFORMANCE_SAMPLE_INTERVAL_SECONDS
        )
        if now < next_log_at:
            return
        interval_started_at = self._xray_probe_performance_interval_started_at
        interval_samples = [
            item
            for item in self._xray_probe_performance_samples
            if interval_started_at is None or item.captured_at >= interval_started_at
        ]
        import carb

        self._log_xray_fresnel_probe_diagnostic(
            carb,
            action="PERFORMANCE",
            formatter=lambda: self._format_xray_fresnel_probe_performance_interval(
                interval_samples
            ),
        )
        self._xray_probe_performance_interval_started_at = sample.captured_at
        self._xray_probe_performance_next_log_at = (
            now + self.XRAY_PROBE_PERFORMANCE_LOG_INTERVAL_SECONDS
        )

    def advance_xray_material_performance_sampler_in_kit(self) -> bool:
        """Sample production X-Ray only while its transient material is active."""

        import carb
        import omni.usd

        try:
            stage = omni.usd.get_context().get_stage()
            material = stage.GetPrimAtPath(self.XRAY_MATERIAL_PATH) if stage else None
            if not material or not material.IsValid():
                self._stop_xray_material_performance_sampler()
                return False
            self._advance_xray_material_performance_sampler(carb)
            return True
        except Exception as error:  # Diagnostics must not interrupt Kit updates.
            self._log_xray_lifecycle_diagnostic(
                carb,
                action="PERFORMANCE",
                formatter=lambda error=error: (_ for _ in ()).throw(error),
            )
            return False

    def _start_xray_material_performance_sampler(self) -> None:
        """Start a HUD-backed interval for one production X-Ray activation."""

        initial_sample = self._capture_xray_fresnel_probe_performance_sample()
        started_at = initial_sample.captured_at
        self._xray_material_performance_started_at = started_at
        self._xray_material_performance_next_sample_at = (
            started_at + self.XRAY_MATERIAL_PERFORMANCE_SAMPLE_INTERVAL_SECONDS
        )
        self._xray_material_performance_next_log_at = (
            started_at + self.XRAY_MATERIAL_PERFORMANCE_LOG_INTERVAL_SECONDS
        )
        self._xray_material_performance_interval_started_at = started_at
        self._xray_material_performance_samples = [initial_sample]

    def _stop_xray_material_performance_sampler(self) -> None:
        self._xray_material_performance_started_at = None
        self._xray_material_performance_next_sample_at = None
        self._xray_material_performance_next_log_at = None
        self._xray_material_performance_interval_started_at = None
        self._xray_material_performance_samples = []

    def _advance_xray_material_performance_sampler(self, carb) -> None:
        started_at = self._xray_material_performance_started_at
        next_sample_at = self._xray_material_performance_next_sample_at
        next_log_at = self._xray_material_performance_next_log_at
        if started_at is None or next_sample_at is None or next_log_at is None:
            self._start_xray_material_performance_sampler()
            return
        now = time.monotonic()
        if now < next_sample_at:
            return
        try:
            sample = self._capture_xray_fresnel_probe_performance_sample()
        except Exception as error:
            self._xray_material_performance_next_sample_at = (
                now + self.XRAY_MATERIAL_PERFORMANCE_SAMPLE_INTERVAL_SECONDS
            )
            self._log_xray_lifecycle_diagnostic(
                carb,
                action="PERFORMANCE",
                formatter=lambda error=error: (_ for _ in ()).throw(error),
            )
            return
        self._xray_material_performance_samples.append(sample)
        self._xray_material_performance_next_sample_at = (
            now + self.XRAY_MATERIAL_PERFORMANCE_SAMPLE_INTERVAL_SECONDS
        )
        if now < next_log_at:
            return
        interval_started_at = self._xray_material_performance_interval_started_at
        interval_samples = [
            item
            for item in self._xray_material_performance_samples
            if interval_started_at is None or item.captured_at >= interval_started_at
        ]
        self._log_xray_lifecycle_diagnostic(
            carb,
            action="PERFORMANCE",
            formatter=lambda: self._format_xray_material_performance_interval(
                interval_samples
            ),
        )
        self._xray_material_performance_interval_started_at = sample.captured_at
        self._xray_material_performance_next_log_at = (
            now + self.XRAY_MATERIAL_PERFORMANCE_LOG_INTERVAL_SECONDS
        )

    def _format_xray_material_performance_interval(
        self, samples: list[ViewportPerformanceSample]
    ) -> str:
        performance = self._xray_fresnel_probe_performance_state(samples)
        latest = samples[-1] if samples else None
        started_at = self._xray_material_performance_started_at
        elapsed = (
            latest.captured_at - started_at
            if latest is not None and started_at is not None
            else None
        )
        elapsed_text = f"{elapsed:.1f} s" if elapsed is not None else "<unavailable>"
        return "\n".join(
            (
                "DTRS X-Ray binding lifecycle - PERFORMANCE",
                f"  elapsed={elapsed_text}",
                f"  control_material_path={self.XRAY_MATERIAL_PATH}",
                f"  samples={len(samples)}",
                "  FPS: "
                f"current={performance['fps_current']}; "
                f"average={performance['probe_avg_fps']}; "
                f"minimum={performance['probe_min_fps']}; "
                f"maximum={performance['probe_max_fps']}",
                "  Frame time: "
                f"current={performance['frame_time_ms_current']} ms; "
                f"average={performance['probe_avg_frame_time_ms']} ms",
                "  Memory: "
                f"gpu_used_gib={performance['gpu_used_gib']}; "
                f"process_used_gib={performance['process_used_gib']}",
            )
        )

    def _xray_fresnel_probe_performance_state(
        self, samples: list[ViewportPerformanceSample] | None = None
    ) -> dict[str, str]:
        """Format Kit HUD measurements for action diagnostics only."""

        samples = self._xray_probe_performance_samples if samples is None else samples
        latest = samples[-1] if samples else None
        fps_values = [sample.fps for sample in samples if sample.fps is not None]
        frame_times = [
            sample.frame_time_ms
            for sample in samples
            if sample.frame_time_ms is not None
        ]

        def average(values):
            return sum(values) / len(values) if values else None

        def formatted(value):
            return f"{value:.2f}" if value is not None else "<unavailable>"

        return {
            "fps_current": formatted(latest.fps if latest else None),
            "frame_time_ms_current": formatted(
                latest.frame_time_ms if latest else None
            ),
            "probe_avg_fps": formatted(average(fps_values)),
            "probe_min_fps": formatted(min(fps_values) if fps_values else None),
            "probe_max_fps": formatted(max(fps_values) if fps_values else None),
            "probe_avg_frame_time_ms": formatted(average(frame_times)),
            "gpu_used_gib": formatted(latest.gpu_memory_used_gib if latest else None),
            "process_used_gib": formatted(
                latest.process_memory_used_gib if latest else None
            ),
        }

    def _xray_fresnel_probe_opacity_state(self) -> dict[str, str]:
        try:
            values = self._xray_probe_last_values
            return {
                "facing_opacity": (
                    f"{float(values[7]):.2f}" if values is not None else "<unavailable>"
                ),
                "edge_opacity": (
                    f"{float(values[8]):.2f}" if values is not None else "<unavailable>"
                ),
            }
        except Exception as error:
            unavailable = f"<inspection failed: {error}>"
            return {"facing_opacity": unavailable, "edge_opacity": unavailable}

    def _xray_fresnel_probe_emission_state(self) -> dict[str, str]:
        try:
            values = self._xray_probe_last_values
            return {
                "facing_emission": (
                    f"{float(values[9]):.2f}" if values is not None else "<unavailable>"
                ),
                "edge_emission": (
                    f"{float(values[10]):.2f}"
                    if values is not None
                    else "<unavailable>"
                ),
                "emission_scale": (
                    f"{float(values[11]):.2f}"
                    if values is not None
                    else "<unavailable>"
                ),
                "effective_facing_emission": (
                    f"{float(values[9]) * float(values[11]):.2f}"
                    if values is not None
                    else "<unavailable>"
                ),
                "effective_edge_emission": (
                    f"{float(values[10]) * float(values[11]):.2f}"
                    if values is not None
                    else "<unavailable>"
                ),
            }
        except Exception as error:
            unavailable = f"<inspection failed: {error}>"
            return {
                "facing_emission": unavailable,
                "edge_emission": unavailable,
                "emission_scale": unavailable,
                "effective_facing_emission": unavailable,
                "effective_edge_emission": unavailable,
            }

    def _xray_fresnel_probe_roughness_state(self) -> dict[str, str]:
        try:
            values = self._xray_probe_last_values
            return {
                "facing_roughness": (
                    f"{float(values[5]):.2f}" if values is not None else "<unavailable>"
                ),
                "edge_roughness": (
                    f"{float(values[6]):.2f}" if values is not None else "<unavailable>"
                ),
            }
        except Exception as error:
            unavailable = f"<inspection failed: {error}>"
            return {"facing_roughness": unavailable, "edge_roughness": unavailable}

    def _format_xray_fresnel_probe_performance_interval(
        self, samples: list[ViewportPerformanceSample]
    ) -> str:
        performance = self._xray_fresnel_probe_performance_state(samples)
        latest = samples[-1] if samples else None
        started_at = self._xray_probe_performance_started_at
        elapsed = (
            latest.captured_at - started_at
            if latest is not None and started_at is not None
            else None
        )
        opacity = self._xray_fresnel_probe_opacity_state()
        roughness = self._xray_fresnel_probe_roughness_state()
        emission = self._xray_fresnel_probe_emission_state()
        elapsed_text = f"{elapsed:.1f} s" if elapsed is not None else "<unavailable>"
        return "\n".join(
            (
                "DTRS Custom MDL Fresnel Probe 01 - PERFORMANCE",
                f"  elapsed={elapsed_text}",
                "  live_camera_sync_updates="
                f"{self._xray_probe_live_camera_sync_updates}",
                "  opacity:",
                f"    facing_opacity={opacity['facing_opacity']}",
                f"    edge_opacity={opacity['edge_opacity']}",
                "  roughness: "
                f"facing={roughness['facing_roughness']}; "
                f"edge={roughness['edge_roughness']}",
                "  emission:",
                f"    facing_emission={emission['facing_emission']}",
                f"    edge_emission={emission['edge_emission']}",
                f"    emission_scale={emission['emission_scale']}",
                "    effective_facing=" f"{emission['effective_facing_emission']}",
                "    effective_edge=" f"{emission['effective_edge_emission']}",
                "  FPS:",
                f"    current={performance['fps_current']}",
                f"    average={performance['probe_avg_fps']}",
                f"    minimum={performance['probe_min_fps']}",
                f"    maximum={performance['probe_max_fps']}",
                "  Frame time:",
                f"    current={performance['frame_time_ms_current']} ms",
                f"    average={performance['probe_avg_frame_time_ms']} ms",
                "  Memory:",
                f"    gpu_used_gib={performance['gpu_used_gib']}",
                f"    process_used_gib={performance['process_used_gib']}",
            )
        )

    @staticmethod
    def _log_xray_fresnel_probe_diagnostic(carb, *, action: str, formatter) -> None:
        """Diagnostics must not alter the result of an already-authored probe."""

        try:
            carb.log_warn(formatter())
        except Exception as error:
            carb.log_warn(
                "DTRS Custom MDL Fresnel Probe 01\n"
                f"  action: {action}\n"
                f"  diagnostic: <inspection failed: {error}>"
            )

    @staticmethod
    def _xray_probe_diagnostic_value(reader):
        try:
            return reader()
        except Exception as error:
            return f"<inspection failed: {error}>"

    def _capture_and_hide_xray_probe_server(self, stage, Usd, UsdGeom) -> None:
        server = stage.GetPrimAtPath(self.XRAY_PROBE_SERVER_PATH)
        visibility = UsdGeom.Imageable(server).GetVisibilityAttr()
        spec = stage.GetSessionLayer().GetPropertyAtPath(visibility.GetPath())
        self._xray_probe_visibility_state = (
            spec is not None,
            visibility.Get() if spec is not None else None,
        )
        visibility.Set(UsdGeom.Tokens.invisible)
        self._xray_probe_light_visibility_states = []
        for prim in Usd.PrimRange(server):
            if not prim.GetTypeName().endswith("Light"):
                continue
            light_visibility = UsdGeom.Imageable(prim).GetVisibilityAttr()
            light_spec = stage.GetSessionLayer().GetPropertyAtPath(
                light_visibility.GetPath()
            )
            self._xray_probe_light_visibility_states.append(
                (str(prim.GetPath()), light_spec is not None, light_visibility.Get())
            )
            light_visibility.Set(UsdGeom.Tokens.inherited)

    @classmethod
    def _xray_fresnel_probe_camera_position(cls, stage, Usd, UsdGeom):
        """Return the ReviewCamera world-space position for the static MDL probe."""

        camera = stage.GetPrimAtPath("/DTRS_Runtime/ReviewCamera")
        if not camera or not camera.IsValid():
            return None
        matrix = UsdGeom.XformCache(Usd.TimeCode.Default()).GetLocalToWorldTransform(
            camera
        )
        position = matrix.ExtractTranslation()
        return (float(position[0]), float(position[1]), float(position[2]))

    @classmethod
    def _xray_fresnel_probe_layout(cls, bbox):
        """Return a non-overlapping cube/sphere layout within the server scale."""

        size = (
            max(float(component) for component in bbox.GetSize())
            * cls.XRAY_PROBE_SIZE_FRACTION
        )
        center = (bbox.GetMin() + bbox.GetMax()) * 0.5
        gap = size * 0.25
        # Cube half-width + sphere radius + visible gap.
        distance = size * 0.5 + size * 0.5 + gap
        return size, center, distance, gap

    @classmethod
    def _define_xray_fresnel_probe_geometry(cls, stage, bbox, Gf, UsdGeom):
        """Author probe geometry from server bounds without moving the camera."""

        size, center, distance, _gap = cls._xray_fresnel_probe_layout(bbox)
        cube = UsdGeom.Cube.Define(stage, f"{cls.XRAY_PROBE_ROOT_PATH}/Cube")
        cube.CreateSizeAttr(size)
        sphere = cls._define_xray_fresnel_probe_sphere(
            stage,
            f"{cls.XRAY_PROBE_ROOT_PATH}/Sphere",
            size * 0.5,
            Gf,
            UsdGeom,
        )
        cube.AddTranslateOp().Set(
            Gf.Vec3d(center[0] - distance * 0.5, center[1], center[2])
        )
        sphere.AddTranslateOp().Set(
            Gf.Vec3d(center[0] + distance * 0.5, center[1], center[2])
        )
        return cube, sphere

    @staticmethod
    def _xray_fresnel_probe_server_bbox(server, Usd, UsdGeom):
        """Return valid server bounds without depending on composed visibility."""

        purposes = [
            getattr(UsdGeom.Tokens, name)
            for name in RuntimeController.XRAY_PROBE_BOUND_PURPOSES
        ]
        bbox = (
            UsdGeom.BBoxCache(
                Usd.TimeCode.Default(),
                purposes,
                useExtentsHint=True,
                ignoreVisibility=True,
            )
            .ComputeWorldBound(server)
            .ComputeAlignedBox()
        )
        extent = bbox.GetSize()
        max_extent = max(float(component) for component in extent)
        return bbox if math.isfinite(max_extent) and max_extent > 0.0 else None

    def _xray_fresnel_probe_geometry_state(self, stage, Usd, UsdGeom) -> dict:
        """Read the authored Probe 01 dimensions for a compact operator log."""

        bbox = self._xray_probe_server_bbox_snapshot
        if bbox is None:
            raise ValueError("pre-hide server bounds were not captured")
        bbox_min = bbox.GetMin()
        bbox_max = bbox.GetMax()
        bbox_extent = bbox.GetSize()
        max_extent = max(float(component) for component in bbox_extent)
        cube = UsdGeom.Cube.Get(stage, f"{self.XRAY_PROBE_ROOT_PATH}/Cube")
        sphere = UsdGeom.Mesh.Get(stage, f"{self.XRAY_PROBE_ROOT_PATH}/Sphere")
        cube_size = float(cube.GetSizeAttr().Get())
        sphere_points = sphere.GetPointsAttr().Get() or []
        sphere_radius = max(
            (
                math.sqrt(
                    float(point[0]) ** 2 + float(point[1]) ** 2 + float(point[2]) ** 2
                )
                for point in sphere_points
            ),
            default=0.0,
        )
        xform_cache = UsdGeom.XformCache(Usd.TimeCode.Default())
        cube_center = xform_cache.GetLocalToWorldTransform(
            cube.GetPrim()
        ).ExtractTranslation()
        sphere_center = xform_cache.GetLocalToWorldTransform(
            sphere.GetPrim()
        ).ExtractTranslation()
        center_distance = math.sqrt(
            sum(
                (float(sphere_center[index]) - float(cube_center[index])) ** 2
                for index in range(3)
            )
        )
        return {
            "server_bbox_min": tuple(float(value) for value in bbox_min),
            "server_bbox_max": tuple(float(value) for value in bbox_max),
            "server_bbox_extent": tuple(float(value) for value in bbox_extent),
            "server_bbox_max_extent": max_extent,
            "probe_size": max_extent * self.XRAY_PROBE_SIZE_FRACTION,
            "cube_size": cube_size,
            "sphere_radius": sphere_radius,
            "cube_center": tuple(float(value) for value in cube_center),
            "sphere_center": tuple(float(value) for value in sphere_center),
            "center_distance": center_distance,
            "gap": center_distance - cube_size * 0.5 - sphere_radius,
        }

    def _xray_fresnel_probe_camera_snapshot(self, stage, Usd, UsdGeom, UsdShade):
        """Collect camera diagnostics without allowing inspection to affect cleanup."""

        shader = UsdShade.Shader.Get(stage, f"{self.XRAY_PROBE_MATERIAL_PATH}/Shader")
        camera_input = shader.GetInput("camera_position") if shader else None
        return {
            "review_camera_position": self._xray_probe_diagnostic_value(
                lambda: self._xray_fresnel_probe_camera_position(stage, Usd, UsdGeom)
            ),
            "camera_position_input": self._xray_probe_diagnostic_value(
                lambda: (
                    camera_input.Get()
                    if camera_input and camera_input.GetAttr().HasAuthoredValue()
                    else "<missing>"
                )
            ),
        }

    @staticmethod
    def _xray_probe_camera_positions_match(current, authored, tolerance=1.0e-4):
        if current is None or authored is None:
            raise ValueError("camera position is missing")
        return all(
            abs(float(current[index]) - float(authored[index])) <= tolerance
            for index in range(3)
        )

    def _clear_xray_fresnel_probe(self, stage) -> None:
        from pxr import UsdGeom

        stage.RemovePrim(self.XRAY_PROBE_ROOT_PATH)
        stage.RemovePrim(self.XRAY_PROBE_MATERIAL_PATH)
        server = stage.GetPrimAtPath(self.XRAY_PROBE_SERVER_PATH)
        prior = getattr(self, "_xray_probe_visibility_state", None)
        if server and server.IsValid() and prior is not None:
            had_session_spec, value = prior
            visibility = server.GetAttribute("visibility")
            if had_session_spec:
                visibility.Set(value)
            else:
                server.RemoveProperty("visibility")
                self._remove_xray_probe_session_property_spec(
                    stage, visibility.GetPath()
                )
        for path, had_session_spec, value in getattr(
            self, "_xray_probe_light_visibility_states", []
        ):
            prim = stage.GetPrimAtPath(path)
            if not prim or not prim.IsValid():
                continue
            if had_session_spec:
                UsdGeom.Imageable(prim).GetVisibilityAttr().Set(value)
            else:
                prim.RemoveProperty("visibility")
                self._remove_xray_probe_session_property_spec(
                    stage, UsdGeom.Imageable(prim).GetVisibilityAttr().GetPath()
                )
        self._xray_probe_visibility_state = None
        self._xray_probe_light_visibility_states = []
        self._xray_probe_server_bbox_snapshot = None

    @staticmethod
    def _remove_xray_probe_session_property_spec(stage, property_path) -> None:
        """Remove a probe-owned property spec if the Usd convenience call left it."""

        session_prim = stage.GetSessionLayer().GetPrimAtPath(
            property_path.GetPrimPath()
        )
        property_spec = stage.GetSessionLayer().GetPropertyAtPath(property_path)
        if session_prim and property_spec:
            session_prim.RemoveProperty(property_spec)

    @classmethod
    def _define_xray_fresnel_probe_sphere(cls, stage, path, radius, Gf, UsdGeom):
        """Define a smooth UV mesh because UsdGeom.Sphere has no resolution field."""

        longitude_count = cls.XRAY_PROBE_SPHERE_LONGITUDE_SEGMENTS
        latitude_count = cls.XRAY_PROBE_SPHERE_LATITUDE_SEGMENTS
        points = [Gf.Vec3f(0.0, float(radius), 0.0)]
        normals = [Gf.Vec3f(0.0, 1.0, 0.0)]
        for latitude in range(1, latitude_count):
            theta = math.pi * latitude / latitude_count
            sin_theta = math.sin(theta)
            y = math.cos(theta)
            for longitude in range(longitude_count):
                phi = 2.0 * math.pi * longitude / longitude_count
                normal = Gf.Vec3f(
                    sin_theta * math.cos(phi), y, sin_theta * math.sin(phi)
                )
                normals.append(normal)
                points.append(normal * radius)
        bottom_index = len(points)
        points.append(Gf.Vec3f(0.0, -float(radius), 0.0))
        normals.append(Gf.Vec3f(0.0, -1.0, 0.0))

        face_counts = []
        face_indices = []
        first_ring = 1
        last_ring = 1 + (latitude_count - 2) * longitude_count
        for longitude in range(longitude_count):
            current = first_ring + longitude
            following = first_ring + (longitude + 1) % longitude_count
            face_counts.append(3)
            face_indices.extend((0, following, current))
        for latitude in range(latitude_count - 2):
            ring = first_ring + latitude * longitude_count
            next_ring = ring + longitude_count
            for longitude in range(longitude_count):
                current = ring + longitude
                following = ring + (longitude + 1) % longitude_count
                next_current = next_ring + longitude
                next_following = next_ring + (longitude + 1) % longitude_count
                face_counts.extend((3, 3))
                face_indices.extend(
                    (
                        current,
                        following,
                        next_following,
                        current,
                        next_following,
                        next_current,
                    )
                )
        for longitude in range(longitude_count):
            current = last_ring + longitude
            following = last_ring + (longitude + 1) % longitude_count
            face_counts.append(3)
            face_indices.extend((bottom_index, current, following))

        sphere = UsdGeom.Mesh.Define(stage, path)
        sphere.CreatePointsAttr(points)
        sphere.CreateNormalsAttr(normals)
        sphere.SetNormalsInterpolation(UsdGeom.Tokens.vertex)
        sphere.CreateFaceVertexCountsAttr(face_counts)
        sphere.CreateFaceVertexIndicesAttr(face_indices)
        sphere.CreateExtentAttr(
            [
                Gf.Vec3f(-radius, -radius, -radius),
                Gf.Vec3f(radius, radius, radius),
            ]
        )
        sphere.CreateDoubleSidedAttr(True)
        return sphere

    def _format_xray_fresnel_probe_state(
        self, stage, Usd, UsdGeom, UsdShade, *, action: str, values
    ) -> str:
        material = UsdShade.Material.Get(stage, self.XRAY_PROBE_MATERIAL_PATH)
        shader = UsdShade.Shader.Get(stage, f"{self.XRAY_PROBE_MATERIAL_PATH}/Shader")
        light_paths = []
        for prim in Usd.PrimRange(stage.GetPseudoRoot()):
            if prim.GetTypeName().endswith("Light"):
                visibility = UsdGeom.Imageable(prim).ComputeVisibility()
                light_paths.append(f"{prim.GetPath()}={visibility}")
        cube = stage.GetPrimAtPath(f"{self.XRAY_PROBE_ROOT_PATH}/Cube")
        sphere = stage.GetPrimAtPath(f"{self.XRAY_PROBE_ROOT_PATH}/Sphere")
        (
            facing,
            edge,
            center,
            softness,
            sharpness,
            facing_roughness,
            edge_roughness,
            facing_opacity,
            edge_opacity,
            facing_emission,
            edge_emission,
            emission_scale,
        ) = values
        cube_binding = UsdShade.MaterialBindingAPI(cube).ComputeBoundMaterial()[0]
        sphere_binding = UsdShade.MaterialBindingAPI(sphere).ComputeBoundMaterial()[0]
        sphere_mesh = UsdGeom.Mesh(sphere)
        face_count = len(sphere_mesh.GetFaceVertexCountsAttr().Get() or [])
        point_count = len(sphere_mesh.GetPointsAttr().Get() or [])
        camera_snapshot = self._xray_fresnel_probe_camera_snapshot(
            stage, Usd, UsdGeom, UsdShade
        )
        camera_position = camera_snapshot["camera_position_input"]
        review_camera_position = camera_snapshot["review_camera_position"]
        camera_match = self._xray_probe_diagnostic_value(
            lambda: self._xray_probe_camera_positions_match(
                review_camera_position, camera_position
            )
        )
        performance = self._xray_probe_diagnostic_value(
            self._xray_fresnel_probe_performance_state
        )
        geometry = self._xray_fresnel_probe_geometry_state(stage, Usd, UsdGeom)
        shader_asset = shader.GetSourceAsset("mdl").path if shader else "<missing>"
        cube_binding_path = cube_binding.GetPath() if cube_binding else "<none>"
        sphere_binding_path = sphere_binding.GetPath() if sphere_binding else "<none>"
        server_session_visibility = (
            stage.GetSessionLayer().GetPropertyAtPath("/blackwell_rig.visibility")
            is not None
        )
        scene_lights = ", ".join(light_paths) or "<none>"
        return "\n".join(
            (
                "DTRS Custom MDL Fresnel Probe 01",
                f"  action: {action}",
                "  shader_mode: static controllable NdotV mask",
                f"  camera_position_input: {camera_position}",
                f"  review_camera_position: {review_camera_position}",
                f"  camera_match: {camera_match}",
                "  live_camera_sync: enabled",
                "  live_camera_sync_updates="
                f"{self._xray_probe_live_camera_sync_updates}",
                "  performance:",
                f"    fps_current={performance['fps_current']}",
                "    frame_time_ms_current=" f"{performance['frame_time_ms_current']}",
                f"    probe_avg_fps={performance['probe_avg_fps']}",
                "    probe_avg_frame_time_ms="
                f"{performance['probe_avg_frame_time_ms']}",
                f"    probe_min_fps={performance['probe_min_fps']}",
                f"    probe_max_fps={performance['probe_max_fps']}",
                f"    gpu_used_gib={performance['gpu_used_gib']}",
                f"    process_used_gib={performance['process_used_gib']}",
                "  viewport_framing: disabled",
                (
                    "  parameters: "
                    f"facing_color={facing}; edge_color={edge}; "
                    f"edge_center={center:g}; edge_softness={softness:g}; "
                    f"edge_sharpness={sharpness:g}"
                ),
                (
                    "  roughness: "
                    f"facing_roughness={facing_roughness:g}; "
                    f"edge_roughness={edge_roughness:g}"
                ),
                (
                    "  opacity: "
                    f"facing_opacity={facing_opacity:g}; "
                    f"edge_opacity={edge_opacity:g}"
                ),
                (
                    "  emission: "
                    f"facing_emission={facing_emission:g}; "
                    f"edge_emission={edge_emission:g}; "
                    f"emission_scale={emission_scale:.2f}; "
                    "effective_facing_emission="
                    f"{facing_emission * emission_scale:.2f}; "
                    "effective_edge_emission="
                    f"{edge_emission * emission_scale:.2f}"
                ),
                "  probe_geometry:",
                f"    server_bbox_min={geometry['server_bbox_min']}",
                f"    server_bbox_max={geometry['server_bbox_max']}",
                f"    server_bbox_extent={geometry['server_bbox_extent']}",
                f"    server_bbox_max_extent={geometry['server_bbox_max_extent']:g}",
                f"    probe_scale_fraction={self.XRAY_PROBE_SIZE_FRACTION:g}",
                f"    probe_size={geometry['probe_size']:g}",
                f"    cube_size={geometry['cube_size']:g}",
                f"    sphere_radius={geometry['sphere_radius']:g}",
                f"    cube_center={geometry['cube_center']}",
                f"    sphere_center={geometry['sphere_center']}",
                f"    center_distance={geometry['center_distance']:g}",
                f"    gap={geometry['gap']:g}",
                (
                    "  scene: "
                    f"cube={cube.IsValid()} ({cube.GetTypeName()}); "
                    f"sphere={sphere.IsValid()} ({sphere.GetTypeName()}, "
                    f"points={point_count}, triangles={face_count}, "
                    "segments="
                    f"{self.XRAY_PROBE_SPHERE_LONGITUDE_SEGMENTS}x"
                    f"{self.XRAY_PROBE_SPHERE_LATITUDE_SEGMENTS})"
                ),
                (
                    "  material: "
                    f"exists={bool(material)}; "
                    f"shader_asset={shader_asset}; "
                    f"cube_binding={cube_binding_path}; "
                    f"sphere_binding={sphere_binding_path}"
                ),
                f"  server_session_visibility={server_session_visibility}",
                (
                    "  preserved_lights="
                    f"{len(self._xray_probe_light_visibility_states)}; "
                    f"scene_lights={scene_lights}"
                ),
            )
        )

    def _format_xray_fresnel_probe_clear_state(
        self,
        stage,
        Usd,
        UsdGeom,
        UsdShade,
        *,
        prior_visibility_state,
        camera_before_clear,
        review_camera_after_clear,
    ) -> str:
        del Usd, UsdShade
        server = stage.GetPrimAtPath(self.XRAY_PROBE_SERVER_PATH)
        session = stage.GetSessionLayer()
        visibility_path = f"{self.XRAY_PROBE_SERVER_PATH}.visibility"
        camera_changed = self._xray_probe_diagnostic_value(
            lambda: not self._xray_probe_camera_positions_match(
                camera_before_clear["review_camera_position"],
                review_camera_after_clear,
            )
        )
        camera_match_before_clear = self._xray_probe_diagnostic_value(
            lambda: self._xray_probe_camera_positions_match(
                camera_before_clear["review_camera_position"],
                camera_before_clear["camera_position_input"],
            )
        )
        performance = self._xray_probe_diagnostic_value(
            self._xray_fresnel_probe_performance_state
        )
        opacity_before_clear = self._xray_fresnel_probe_opacity_state()
        roughness_before_clear = self._xray_fresnel_probe_roughness_state()
        emission_before_clear = self._xray_fresnel_probe_emission_state()
        probe_root_present = stage.GetPrimAtPath(self.XRAY_PROBE_ROOT_PATH).IsValid()
        probe_material_present = stage.GetPrimAtPath(
            self.XRAY_PROBE_MATERIAL_PATH
        ).IsValid()
        server_session_visibility_spec = (
            session.GetPropertyAtPath(visibility_path) is not None
        )
        server_composed_visibility = (
            UsdGeom.Imageable(server).ComputeVisibility() if server else "<missing>"
        )
        return "\n".join(
            (
                "DTRS Custom MDL Fresnel Probe 01",
                "  action: Clear Probe",
                "  shader_mode: static controllable NdotV mask",
                "  review_camera_position_before_clear="
                f"{camera_before_clear['review_camera_position']}",
                "  camera_position_input_before_clear="
                f"{camera_before_clear['camera_position_input']}",
                f"  camera_match_before_clear={camera_match_before_clear}",
                "  live_camera_sync_updates="
                f"{self._xray_probe_live_camera_sync_updates}",
                "  performance:",
                f"    fps_current={performance['fps_current']}",
                "    frame_time_ms_current=" f"{performance['frame_time_ms_current']}",
                f"    probe_avg_fps={performance['probe_avg_fps']}",
                "    probe_avg_frame_time_ms="
                f"{performance['probe_avg_frame_time_ms']}",
                f"    probe_min_fps={performance['probe_min_fps']}",
                f"    probe_max_fps={performance['probe_max_fps']}",
                f"    gpu_used_gib={performance['gpu_used_gib']}",
                f"    process_used_gib={performance['process_used_gib']}",
                f"  opacity_before_clear={opacity_before_clear}",
                f"  roughness_before_clear={roughness_before_clear}",
                f"  emission_before_clear={emission_before_clear}",
                "  review_camera_position_after_clear=" f"{review_camera_after_clear}",
                f"  camera_changed_by_clear={camera_changed}",
                f"  probe_root_present={probe_root_present}",
                f"  probe_material_present={probe_material_present}",
                f"  server_valid={server.IsValid() if server else False}",
                "  prior_server_session_visibility="
                f"{prior_visibility_state[0] if prior_visibility_state else '<none>'}",
                f"  server_session_visibility_spec={server_session_visibility_spec}",
                f"  server_composed_visibility={server_composed_visibility}",
            )
        )

    @classmethod
    def _format_xray_action_state(
        cls,
        stage,
        Usd,
        UsdShade,
        *,
        action: str,
        requested_selected: bool,
        result: str,
    ) -> str:
        root = stage.GetPrimAtPath(cls.XRAY_CHASSIS_ROOT_PATH)
        session = stage.GetSessionLayer()
        xray_binding_count = 0
        session_binding_spec_count = 0
        if root and root.IsValid():
            for prim in Usd.PrimRange(root):
                if prim.GetTypeName() != "Mesh":
                    continue
                relation = UsdShade.MaterialBindingAPI(prim).GetDirectBindingRel()
                if str(cls.XRAY_MATERIAL_PATH) in {
                    str(path) for path in relation.GetTargets()
                }:
                    xray_binding_count += 1
                if session.GetPropertyAtPath(relation.GetPath()) is not None:
                    session_binding_spec_count += 1
        xray_material_present = stage.GetPrimAtPath(cls.XRAY_MATERIAL_PATH).IsValid()
        return "\n".join(
            (
                "DTRS X-Ray action",
                f"  action: {action}",
                f"  requested_selected: {requested_selected}",
                f"  result: {result}",
                (
                    "  runtime: "
                    f"xray_material_present={xray_material_present}; "
                    f"xray_direct_bindings={xray_binding_count}; "
                    f"session_binding_specs={session_binding_spec_count}"
                ),
            )
        )

    @classmethod
    def _define_xray_fresnel_probe_material(cls, stage, Sdf, UsdShade):
        material = UsdShade.Material.Define(stage, cls.XRAY_PROBE_MATERIAL_PATH)
        shader = UsdShade.Shader.Define(stage, f"{cls.XRAY_PROBE_MATERIAL_PATH}/Shader")
        shader.CreateImplementationSourceAttr().Set(UsdShade.Tokens.sourceAsset)
        mdl_path = (
            Path(__file__).resolve().parents[1]
            / "ext"
            / "msp.dtrs"
            / "data"
            / "materials"
            / "DTRS_Fresnel_Test.mdl"
        )
        shader.SetSourceAsset(Sdf.AssetPath(str(mdl_path)), "mdl")
        shader.SetSourceAssetSubIdentifier("DTRS_Fresnel_Test", "mdl")
        shader.CreateOutput("out", Sdf.ValueTypeNames.Token).SetRenderType("material")
        material.CreateSurfaceOutput("mdl").ConnectToSource(
            shader.ConnectableAPI(), "out"
        )
        return material

    @classmethod
    def _set_xray_fresnel_probe_values(
        cls, stage, values, Gf, Sdf, UsdShade, *, camera_position=None
    ) -> None:
        (
            facing,
            edge,
            center,
            softness,
            sharpness,
            facing_roughness,
            edge_roughness,
            facing_opacity,
            edge_opacity,
            facing_emission,
            edge_emission,
            emission_scale,
        ) = values
        shader = UsdShade.Shader.Get(stage, f"{cls.XRAY_PROBE_MATERIAL_PATH}/Shader")
        for name, value, value_type in (
            ("facing_color", Gf.Vec3f(*facing), Sdf.ValueTypeNames.Color3f),
            ("edge_color", Gf.Vec3f(*edge), Sdf.ValueTypeNames.Color3f),
            ("edge_center", center, Sdf.ValueTypeNames.Float),
            ("edge_softness", softness, Sdf.ValueTypeNames.Float),
            ("edge_sharpness", sharpness, Sdf.ValueTypeNames.Float),
            ("facing_roughness", facing_roughness, Sdf.ValueTypeNames.Float),
            ("edge_roughness", edge_roughness, Sdf.ValueTypeNames.Float),
            ("facing_opacity", facing_opacity, Sdf.ValueTypeNames.Float),
            ("edge_opacity", edge_opacity, Sdf.ValueTypeNames.Float),
            ("facing_emission", facing_emission, Sdf.ValueTypeNames.Float),
            ("edge_emission", edge_emission, Sdf.ValueTypeNames.Float),
            ("emission_scale", emission_scale, Sdf.ValueTypeNames.Float),
        ):
            shader.CreateInput(name, value_type).Set(value)
        if camera_position is not None:
            shader.CreateInput("camera_position", Sdf.ValueTypeNames.Float3).Set(
                Gf.Vec3f(*camera_position)
            )

    def clear_xray_material_in_kit(self) -> XRayApplyResult:
        """Clear transient X-Ray bindings without changing persisted UI settings."""

        import carb
        import omni.usd
        from pxr import Gf, Sdf, Usd, UsdShade

        stage = omni.usd.get_context().get_stage()
        if not stage:
            return XRayApplyResult(True, "X-Ray is inactive; no open stage.")
        previous_target = stage.GetEditTarget()
        stage.SetEditTarget(stage.GetSessionLayer())
        try:
            removed_count, diagnostics = self._clear_xray_session_overrides(
                stage, Sdf, Usd, UsdShade
            )
            led_reapplied, led_matches_current_state = (
                self._reapply_front_panel_indicator_current_state(
                    stage, Gf, Sdf, Usd, UsdShade
                )
            )
        finally:
            stage.SetEditTarget(previous_target)
        self._log_xray_lifecycle_diagnostic(
            carb,
            action="OFF / cleanup",
            formatter=lambda: self._format_xray_lifecycle_diagnostics(
                "OFF / cleanup",
                diagnostics,
                led_current_state_reapplied=led_reapplied,
                led_binding_matches_current_state=led_matches_current_state,
            ),
        )
        return XRayApplyResult(
            True,
            "X-Ray disabled; original chassis materials restored.",
            removed_count,
        )

    def diagnose_xray_usd_fabric_after_off_in_kit(
        self, *, target_path: str, timing: str
    ) -> None:
        """Compare one post-OFF binding against the current attached Fabric stage."""

        import carb
        import omni.usd
        from pxr import UsdShade

        try:
            context = omni.usd.get_context()
            stage = context.get_stage()
            target = stage.GetPrimAtPath(target_path) if stage else None
            if not target:
                raise RuntimeError("representative static chassis mesh is unavailable")
            usd_binding = self._xray_composed_material_path(target, UsdShade)
            fabric_binding, _fabric_stage = self._xray_fabric_material_path(
                context, target.GetPath()
            )
            self._log_xray_lifecycle_diagnostic(
                carb,
                action=f"USD/Fabric {timing}",
                formatter=lambda: self._format_xray_usd_fabric_diagnostic(
                    timing,
                    target.GetPath(),
                    usd_binding,
                    fabric_binding,
                ),
            )
        except Exception as error:
            carb.log_warn(
                "DTRS X-Ray USD/Fabric diagnostic\n"
                f"  timing={timing}\n"
                f"  diagnostic: <inspection failed: {error}>"
            )

    def _capture_xray_ab_original_material_baseline(self, stage, UsdShade) -> None:
        try:
            target = stage.GetPrimAtPath(self.XRAY_AB_RENDER_PROBE_PATH)
            if not target or not target.IsValid():
                self._xray_ab_original_material_fingerprint = None
                return
            material, _binding = UsdShade.MaterialBindingAPI(
                target
            ).ComputeBoundMaterial()
            if not material or not material.GetPrim().IsValid():
                self._xray_ab_original_material_fingerprint = None
                return
            self._xray_ab_original_material_fingerprint = (
                self._xray_material_fingerprint(stage, target, UsdShade)
            )
        except Exception:
            self._xray_ab_original_material_fingerprint = None

    def _log_xray_ab_original_material_after_off(self, stage, UsdShade) -> None:
        import carb

        try:
            target = stage.GetPrimAtPath(self.XRAY_AB_RENDER_PROBE_PATH)
            fingerprint = (
                self._xray_material_fingerprint(stage, target, UsdShade)
                if target and target.IsValid()
                else None
            )
            original_material_network_match = bool(
                fingerprint
                and self._xray_ab_original_material_fingerprint == fingerprint
            )
            original_material_path = (
                fingerprint["material"] if fingerprint else "<none>"
            )
            material_session_spec = stage.GetSessionLayer().GetPrimAtPath(
                original_material_path
            )
            session_override_count = (
                len(material_session_spec.properties) if material_session_spec else 0
            )
            carb.log_warn(
                "DTRS X-Ray A/B material baseline\n"
                f"  target={self.XRAY_AB_RENDER_PROBE_PATH}\n"
                f"  original_material={original_material_path}\n"
                "  original_material_network_match="
                f"{original_material_network_match}\n"
                "  session_overrides_on_original_material="
                f"{session_override_count}"
            )
        except Exception as error:
            carb.log_warn(
                "DTRS X-Ray A/B material baseline\n"
                f"  diagnostic: <inspection failed: {error}>"
            )

    def apply_xray_ab_render_probe_in_kit(self, phase: str) -> bool:
        """Bind one visible render prim for manual A/B observation only."""

        import carb
        import omni.usd
        from pxr import UsdShade

        try:
            stage = omni.usd.get_context().get_stage()
            target = (
                stage.GetPrimAtPath(self.XRAY_AB_RENDER_PROBE_PATH) if stage else None
            )
            if not target or not target.IsValid():
                raise RuntimeError("configured render face_grill target is unavailable")
            if phase == "A":
                material = UsdShade.Material.Get(stage, self.XRAY_MATERIAL_PATH)
            elif phase == "B" and self._xray_ab_original_material_fingerprint:
                material = UsdShade.Material.Get(
                    stage, self._xray_ab_original_material_fingerprint["material"]
                )
            else:
                raise RuntimeError("original A/B material baseline is unavailable")
            if not material or not material.GetPrim().IsValid():
                raise RuntimeError(f"A/B material for phase {phase} is unavailable")
            previous_target = stage.GetEditTarget()
            stage.SetEditTarget(stage.GetSessionLayer())
            try:
                UsdShade.MaterialBindingAPI.Apply(target).Bind(material)
            finally:
                stage.SetEditTarget(previous_target)
            return True
        except Exception as error:
            carb.log_warn(
                "DTRS X-Ray A/B visual probe\n"
                f"  phase={phase}\n"
                f"  diagnostic: <inspection failed: {error}>"
            )
            return False

    def log_xray_ab_render_probe_phase_in_kit(self, phase: str) -> None:
        import carb
        import omni.usd
        from pxr import UsdShade

        stage = omni.usd.get_context().get_stage()
        target = stage.GetPrimAtPath(self.XRAY_AB_RENDER_PROBE_PATH) if stage else None
        binding = (
            self._xray_composed_material_path(target, UsdShade) if target else "<none>"
        )
        carb.log_warn(
            "DTRS X-Ray A/B visual probe\n"
            f"  phase={phase}\n"
            f"  target={self.XRAY_AB_RENDER_PROBE_PATH}\n"
            f"  binding={binding}"
        )

    def start_xray_hydra_rprim_rebuild_probe_in_kit(
        self,
    ) -> XRayRPrimRebuildProbe | None:
        """Remove one render rprim from participation for exactly one Kit update."""

        import carb
        import omni.usd
        from pxr import UsdShade

        try:
            stage = omni.usd.get_context().get_stage()
            target = (
                stage.GetPrimAtPath(self.XRAY_AB_RENDER_PROBE_PATH) if stage else None
            )
            if not target or not target.IsValid():
                raise RuntimeError("configured render face_grill target is unavailable")
            probe = XRayRPrimRebuildProbe(
                target_path=self.XRAY_AB_RENDER_PROBE_PATH,
                binding_before_rebuild=self._xray_composed_material_path(
                    target, UsdShade
                ),
                active_before=target.IsActive(),
            )
            previous_target = stage.GetEditTarget()
            stage.SetEditTarget(stage.GetSessionLayer())
            try:
                target.SetActive(False)
            finally:
                stage.SetEditTarget(previous_target)
            return probe
        except Exception as error:
            carb.log_warn(
                "DTRS X-Ray rprim rebuild probe\n"
                f"  diagnostic: <inspection failed: {error}>"
            )
            return None

    def restore_xray_hydra_rprim_rebuild_probe_in_kit(
        self, probe: XRayRPrimRebuildProbe
    ) -> XRayRPrimRebuildProbe:
        """Remove our Session active opinion; never author active=true as restore."""

        import omni.usd

        stage = omni.usd.get_context().get_stage()
        target = stage.GetPrimAtPath(probe.target_path) if stage else None
        prim_disappeared = bool(target and not target.IsActive())
        session = stage.GetSessionLayer() if stage else None
        prim_spec = session.GetPrimAtPath(probe.target_path) if session else None
        if prim_spec is None:
            raise RuntimeError("temporary Session active opinion is missing")
        prim_spec.ClearInfo("active")
        active_opinion_removed = not prim_spec.HasInfo("active")
        return XRayRPrimRebuildProbe(
            target_path=probe.target_path,
            binding_before_rebuild=probe.binding_before_rebuild,
            active_before=probe.active_before,
            prim_disappeared=prim_disappeared,
            active_opinion_removed=active_opinion_removed,
        )

    def log_xray_hydra_rprim_rebuild_probe_in_kit(
        self, probe: XRayRPrimRebuildProbe
    ) -> None:
        import carb
        import omni.usd
        from pxr import UsdShade

        stage = omni.usd.get_context().get_stage()
        target = stage.GetPrimAtPath(probe.target_path) if stage else None
        binding_after = self._xray_composed_material_path(target, UsdShade)
        carb.log_warn(
            "DTRS X-Ray rprim rebuild probe\n"
            f"  target={probe.target_path}\n"
            f"  binding_before_rebuild={probe.binding_before_rebuild}\n"
            f"  active_before={probe.active_before}\n"
            f"  prim_disappeared={probe.prim_disappeared}\n"
            f"  active_opinion_removed={probe.active_opinion_removed}\n"
            f"  binding_after_rebuild={binding_after}"
        )

    @staticmethod
    def _xray_composed_material_path(prim, UsdShade) -> str:
        material, _binding = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial()
        return str(material.GetPath()) if material else "<none>"

    @staticmethod
    def _xray_fabric_material_path(context, target_path):
        """Attach only to Kit's current stage ID; never construct a second scene."""

        try:
            import usdrt
            from usdrt import Sdf as RtSdf

            fabric_stage = usdrt.Usd.Stage.Attach(context.get_stage_id())
            fabric_stage.SynchronizeToFabric()
            fabric_prim = fabric_stage.GetPrimAtPath(RtSdf.Path(str(target_path)))
            if not fabric_prim or not fabric_prim.IsValid():
                return "<unavailable: target absent>", fabric_stage
            relationship = fabric_prim.GetRelationship("material:binding")
            targets = relationship.GetTargets() if relationship else []
            return (str(targets[0]) if targets else "<none>"), fabric_stage
        except Exception as error:
            return f"<unavailable: {error}>", None

    @staticmethod
    def _format_xray_usd_fabric_diagnostic(
        timing, target, usd_binding, fabric_binding
    ) -> str:
        match = usd_binding == fabric_binding
        if fabric_binding.startswith("<unavailable:"):
            classification = "Fabric probe unavailable"
        elif match:
            classification = (
                "USD PASS; Fabric PASS; green viewport would be downstream "
                "Hydra/RTX state FAIL"
            )
        else:
            classification = "USD PASS; Fabric STALE"
        return "\n".join(
            (
                "DTRS X-Ray USD/Fabric diagnostic",
                f"  timing={timing}",
                f"  target={target}",
                f"  usd_binding={usd_binding}",
                f"  fabric_binding={fabric_binding}",
                f"  match={match}",
                f"  classification={classification}",
            )
        )

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

    def _clear_xray_session_overrides(self, stage, Sdf, Usd, UsdShade):
        """Remove only X-Ray's binding specs and restore prior Session opinions."""

        self._discard_stale_xray_binding_snapshots(stage)
        removed_count = 0
        diagnostics = []
        root = stage.GetPrimAtPath(self.XRAY_CHASSIS_ROOT_PATH)
        if root and root.IsValid():
            records = []
            for prim in Usd.PrimRange(root):
                if prim.GetTypeName() != "Mesh":
                    continue
                relation = UsdShade.MaterialBindingAPI(prim).GetDirectBindingRel()
                property_path = relation.GetPath()
                if not self._session_binding_is_xray_owned(stage, property_path):
                    continue
                records.append(
                    (
                        prim,
                        relation,
                        property_path,
                        self._xray_binding_lifecycle_snapshot(
                            stage, prim, relation, UsdShade
                        ),
                    )
                )
            with Sdf.ChangeBlock():
                for _prim, _relation, property_path, _before in records:
                    self._remove_xray_session_binding_spec(stage, property_path)
                    prior = self._xray_session_binding_snapshots.pop(
                        str(property_path), None
                    )
                    if prior is not None:
                        self._restore_xray_session_binding_spec(
                            stage, property_path, prior, Sdf
                        )
            cleanup_failures = []
            for prim, relation, property_path, before in records:
                after = self._xray_binding_lifecycle_snapshot(
                    stage, prim, relation, UsdShade
                )
                if after["xray_owned_session_binding_after"]:
                    cleanup_failures.append(str(property_path))
                diagnostics.append(
                    {
                        "before": before,
                        "after": after,
                        "is_led": self._is_xray_led_prim(prim),
                        "baseline_match": (
                            self._xray_baseline_composed_bindings.get(
                                str(property_path)
                            )
                            == after["composed_binding"]
                        ),
                    }
                )
                removed_count += 1
            if cleanup_failures:
                raise RuntimeError(
                    "X-Ray binding cleanup did not remove: "
                    + ", ".join(cleanup_failures)
                )
        self._stop_xray_material_performance_sampler()
        self._xray_session_binding_snapshots.clear()
        self._xray_baseline_composed_bindings.clear()
        self._xray_last_lifecycle_diagnostics = diagnostics
        return removed_count, diagnostics

    def _apply_xray_session_overrides(self, stage, xray, Gf, Sdf, Usd, UsdShade):
        """Bind the simple Part A control material to resolved chassis meshes."""

        self._discard_stale_xray_binding_snapshots(stage)
        root = stage.GetPrimAtPath(self.XRAY_CHASSIS_ROOT_PATH)
        if not root or not root.IsValid():
            raise RuntimeError("X-Ray chassis target root is unavailable.")
        self._define_xray_control_material(stage, xray, Gf, Sdf, UsdShade)
        diagnostics = []
        target_count = 0
        try:
            records = []
            for prim in Usd.PrimRange(root):
                if prim.GetTypeName() != "Mesh":
                    continue
                relation = UsdShade.MaterialBindingAPI(prim).GetDirectBindingRel()
                property_path = relation.GetPath()
                before = self._xray_binding_lifecycle_snapshot(
                    stage, prim, relation, UsdShade
                )
                if not self._session_binding_is_xray_owned(stage, property_path):
                    self._capture_xray_session_binding_spec(stage, property_path, Sdf)
                    self._xray_baseline_composed_bindings.setdefault(
                        str(property_path), before["composed_binding"]
                    )
                records.append((prim, relation, property_path, before))
            with Sdf.ChangeBlock():
                for _prim, _relation, property_path, _before in records:
                    self._author_xray_session_binding_spec(stage, property_path, Sdf)
            failures = []
            for prim, relation, property_path, before in records:
                after = self._xray_binding_lifecycle_snapshot(
                    stage, prim, relation, UsdShade
                )
                diagnostics.append(
                    {
                        "before": before,
                        "after": after,
                        "is_led": self._is_xray_led_prim(prim),
                    }
                )
                if not after["xray_owned_session_binding_after"]:
                    failures.append(str(property_path))
                target_count += 1
            if failures:
                mismatch_paths = self._format_xray_mismatch_paths(failures)
                raise RuntimeError(
                    "X-Ray binding mismatch_count="
                    f"{len(failures)}; paths={mismatch_paths}"
                )
        except Exception:
            failed_diagnostics = diagnostics
            self._clear_xray_session_overrides(stage, Sdf, Usd, UsdShade)
            self._reapply_front_panel_indicator_current_state(
                stage, Gf, Sdf, Usd, UsdShade
            )
            self._xray_last_lifecycle_diagnostics = failed_diagnostics
            raise
        self._xray_last_lifecycle_diagnostics = diagnostics
        return target_count, diagnostics

    @classmethod
    def _define_xray_control_material(cls, stage, xray, Gf, Sdf, UsdShade):
        """Create once per stage; update only Part A controls on later ON cycles."""

        material_path = Sdf.Path(cls.XRAY_MATERIAL_PATH)
        material = UsdShade.Material.Define(stage, material_path)
        shader = UsdShade.Shader.Define(stage, material_path.AppendChild("PartA"))
        shader.CreateImplementationSourceAttr().Set(UsdShade.Tokens.sourceAsset)
        shader.SetSourceAsset(Sdf.AssetPath("OmniSurface.mdl"), "mdl")
        shader.SetSourceAssetSubIdentifier("OmniSurface", "mdl")
        shader.CreateInput("diffuse_reflection_color", Sdf.ValueTypeNames.Color3f).Set(
            Gf.Vec3f(*xray.part_a_fallback_color)
        )
        for name in ("diffuse_reflection_roughness", "specular_reflection_roughness"):
            shader.CreateInput(name, Sdf.ValueTypeNames.Float).Set(
                xray.part_a_roughness
            )
        shader.CreateInput("enable_opacity", Sdf.ValueTypeNames.Bool).Set(True)
        shader.CreateInput("geometry_opacity", Sdf.ValueTypeNames.Float).Set(
            xray.part_a_opacity
        )
        output = shader.CreateOutput("out", Sdf.ValueTypeNames.Token)
        output.SetRenderType("material")
        material.CreateSurfaceOutput("mdl").ConnectToSource(
            shader.ConnectableAPI(), "out"
        )
        return material

    def _is_xray_led_prim(self, prim) -> bool:
        indicators = self.config.chassis_presentation.front_panel_indicators
        target_path = str(prim.GetPath())
        return any(
            path and (target_path == path or target_path.startswith(f"{path}/"))
            for path in (
                indicators.power_path,
                indicators.hdd_path,
                indicators.lan_01_path,
                indicators.lan_02_path,
            )
        )

    def _discard_stale_xray_binding_snapshots(self, stage) -> None:
        layer_id = stage.GetSessionLayer().identifier
        if self._xray_session_binding_layer_id != layer_id:
            self._xray_session_binding_layer_id = layer_id
            self._xray_session_binding_snapshots.clear()

    def _capture_xray_session_binding_spec(self, stage, property_path, Sdf) -> None:
        key = str(property_path)
        if key in self._xray_session_binding_snapshots:
            return
        session = stage.GetSessionLayer()
        if session.GetPropertyAtPath(property_path) is None:
            self._xray_session_binding_snapshots[key] = None
            return
        snapshot = Sdf.Layer.CreateAnonymous("DTRS_XRayBindingSnapshot.usda")
        Sdf.CreatePrimInLayer(snapshot, property_path.GetPrimPath())
        if not Sdf.CopySpec(session, property_path, snapshot, property_path):
            raise RuntimeError(f"Could not snapshot Session binding {property_path}.")
        self._xray_session_binding_snapshots[key] = snapshot

    @classmethod
    def _author_xray_session_binding_spec(cls, stage, property_path, Sdf) -> None:
        """Create or retarget exactly one Session Layer material-binding spec."""

        session = stage.GetSessionLayer()
        relationship_spec = session.GetRelationshipAtPath(property_path)
        if relationship_spec is None:
            prim_spec = session.GetPrimAtPath(property_path.GetPrimPath())
            if prim_spec is None:
                prim_spec = Sdf.CreatePrimInLayer(session, property_path.GetPrimPath())
            relationship_spec = Sdf.RelationshipSpec(
                prim_spec,
                property_path.name,
                custom=False,
            )
        relationship_spec.targetPathList.explicitItems = [
            Sdf.Path(cls.XRAY_MATERIAL_PATH)
        ]

    @staticmethod
    def _format_xray_mismatch_paths(paths: list[str]) -> str:
        displayed = paths[:5]
        suffix = f", ... +{len(paths) - len(displayed)} more" if len(paths) > 5 else ""
        return ", ".join(displayed) + suffix

    @staticmethod
    def _remove_xray_session_binding_spec(stage, property_path) -> None:
        session = stage.GetSessionLayer()
        property_spec = session.GetPropertyAtPath(property_path)
        if property_spec is None:
            return
        prim_spec = session.GetPrimAtPath(property_path.GetPrimPath())
        if prim_spec is None:
            raise RuntimeError(f"Session binding owner is missing for {property_path}.")
        prim_spec.RemoveProperty(property_spec)
        if session.GetPropertyAtPath(property_path) is not None:
            raise RuntimeError(
                f"Could not remove Session binding spec {property_path}."
            )

    @staticmethod
    def _restore_xray_session_binding_spec(stage, property_path, snapshot, Sdf) -> None:
        if not Sdf.CopySpec(
            snapshot, property_path, stage.GetSessionLayer(), property_path
        ):
            raise RuntimeError(f"Could not restore Session binding {property_path}.")

    @classmethod
    def _session_binding_is_xray_owned(cls, stage, property_path) -> bool:
        spec = stage.GetSessionLayer().GetPropertyAtPath(property_path)
        return bool(
            spec
            and str(cls.XRAY_MATERIAL_PATH)
            in {str(path) for path in spec.targetPathList.explicitItems}
        )

    @classmethod
    def _xray_binding_lifecycle_snapshot(cls, stage, prim, relation, UsdShade):
        session_spec = stage.GetSessionLayer().GetPropertyAtPath(relation.GetPath())
        material, _binding = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial()
        direct_targets = (
            ", ".join(str(path) for path in relation.GetTargets()) or "<none>"
        )
        composed = str(material.GetPath()) if material else "<none>"
        return {
            "target_prim_path": str(prim.GetPath()),
            "control_material_path": str(cls.XRAY_MATERIAL_PATH),
            "binding": direct_targets,
            "session_binding_spec": "present" if session_spec else "absent",
            "composed_binding": composed,
            "control_material_alive": stage.GetPrimAtPath(
                cls.XRAY_MATERIAL_PATH
            ).IsValid(),
            "xray_owned_session_binding_after": cls._session_binding_is_xray_owned(
                stage, relation.GetPath()
            ),
        }

    @staticmethod
    def _format_xray_lifecycle_diagnostics(
        action,
        diagnostics,
        *,
        led_current_state_reapplied=None,
        led_binding_matches_current_state=None,
    ) -> str:
        static = [item for item in diagnostics if not item.get("is_led", False)]
        leds = [item for item in diagnostics if item.get("is_led", False)]
        static_baseline_matches = sum(
            bool(item.get("baseline_match")) for item in static
        )
        static_xray_remaining = sum(
            bool(item["after"]["xray_owned_session_binding_after"]) for item in static
        )
        led_xray_remaining = sum(
            bool(item["after"]["xray_owned_session_binding_after"]) for item in leds
        )
        control_material_alive = any(
            item["after"].get("control_material_alive", False) for item in diagnostics
        )
        led_reapplied_value = (
            led_current_state_reapplied
            if led_current_state_reapplied is not None
            else "<not requested>"
        )
        led_matches_value = (
            led_binding_matches_current_state
            if led_binding_matches_current_state is not None
            else "<not requested>"
        )
        lines = [
            "DTRS X-Ray binding lifecycle",
            f"  action: {action}",
            f"  static_targets_total={len(static)}",
            f"  static_baseline_matches={static_baseline_matches}",
            f"  static_xray_bindings_remaining={static_xray_remaining}",
            f"  led_targets_total={len(leds)}",
            f"  led_xray_bindings_remaining={led_xray_remaining}",
            f"  led_current_state_reapplied={led_reapplied_value}",
            f"  led_binding_matches_current_state={led_matches_value}",
            f"  control_material_alive={control_material_alive}",
        ]
        if action.startswith("OFF") and static:
            if static_baseline_matches == len(static) and static_xray_remaining == 0:
                lines.extend(
                    (
                        "  USD lifecycle: PASS",
                        "  renderer synchronisation: manual visual validation required",
                    )
                )
            else:
                lines.append("  USD lifecycle: FAIL")
        for item in diagnostics:
            after = item["after"]
            mismatch = False
            if action.startswith("ON"):
                mismatch = not after["xray_owned_session_binding_after"]
            elif action.startswith("OFF"):
                mismatch = after["xray_owned_session_binding_after"]
            if action.startswith("OFF") and not item.get("is_led", False):
                mismatch = mismatch or not item.get("baseline_match", False)
            if mismatch:
                lines.append(
                    "  mismatch: "
                    f"target={after['target_prim_path']}; "
                    f"binding={after['binding']}; "
                    f"composed_binding={after['composed_binding']}; "
                    "session_binding_spec="
                    f"{after['session_binding_spec']}"
                )
        return "\n".join(lines)

    @staticmethod
    def _xray_static_target_path(diagnostics) -> str | None:
        for diagnostic in diagnostics:
            if not diagnostic.get("is_led", False):
                return str(diagnostic["after"]["target_prim_path"])
        return None

    @staticmethod
    def _log_xray_lifecycle_diagnostic(carb, *, action: str, formatter) -> None:
        """Keep lifecycle diagnostics non-fatal after a binding mutation succeeds."""

        try:
            carb.log_warn(formatter())
        except Exception as error:
            carb.log_warn(
                "DTRS X-Ray binding lifecycle\n"
                f"  action: {action}\n"
                f"  diagnostic: <inspection failed: {error}>"
            )

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
        with Sdf.ChangeBlock():
            with Usd.EditContext(stage, edit_target):
                for path, material in bindings:
                    prim = stage.GetPrimAtPath(path)
                    if not prim or not prim.IsValid():
                        continue
                    relation = UsdShade.MaterialBindingAPI(prim).GetDirectBindingRel()
                    if cls._session_binding_is_xray_owned(stage, relation.GetPath()):
                        continue
                    UsdShade.MaterialBindingAPI.Apply(prim).Bind(material)
                    matched_count += 1
        return matched_count > 0

    def _reapply_front_panel_indicator_current_state(
        self, stage, Gf, Sdf, Usd, UsdShade
    ) -> tuple[bool, bool]:
        """Release X-Ray, then reuse the latest telemetry state without a copy."""

        snapshot = self._front_panel_indicator_last_snapshot
        if snapshot is None:
            return False, False
        indicators = self.config.chassis_presentation.front_panel_indicators
        now_seconds = time.monotonic()
        state = front_panel_indicator_state(
            snapshot.metrics,
            now_seconds,
            storage_metric_id=indicators.storage_metric_id,
            lan_01_metric_id=indicators.lan_01_metric_id,
            lan_02_metric_id=indicators.lan_02_metric_id,
        )
        self._front_panel_indicator_last_state = state
        self._front_panel_indicator_state_key = None
        reapplied = self._apply_front_panel_indicator_state(
            stage, indicators, state, Gf, Sdf, Usd, UsdShade
        )
        return reapplied, self._front_panel_indicator_bindings_match_state(
            stage, indicators, state, UsdShade
        )

    @classmethod
    def _front_panel_indicator_bindings_match_state(
        cls, stage, indicators, state, UsdShade
    ) -> bool:
        expected = (
            (indicators.power_path, "power" if state.power else "off"),
            (indicators.hdd_path, "hdd" if state.hdd else "off"),
            (indicators.lan_01_path, "lan_01" if state.lan_01 else "off"),
            (indicators.lan_02_path, "lan_02" if state.lan_02 else "off"),
        )
        checked_count = 0
        for path, material_key in expected:
            prim = stage.GetPrimAtPath(path)
            if not prim or not prim.IsValid():
                continue
            material, _binding = UsdShade.MaterialBindingAPI(
                prim
            ).ComputeBoundMaterial()
            if (
                not material
                or str(material.GetPath())
                != cls.FRONT_PANEL_MATERIAL_PATHS[material_key]
            ):
                return False
            checked_count += 1
        return checked_count > 0

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
