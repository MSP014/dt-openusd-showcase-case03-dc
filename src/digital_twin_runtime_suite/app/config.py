"""Runtime configuration loading for Digital Twin Runtime Suite."""

from __future__ import annotations

import logging
import math
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from digital_twin_runtime_suite.app.airflow_dataset import (
    AirflowDataset,
    AirflowDatasetSelector,
    discover_airflow_dataset,
)

LOGGER = logging.getLogger(__name__)


SMOKE_TUNING_VALUE_OPTIONS: dict[str, tuple[float, ...]] = {
    "density": (0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0),
    "brightness": (0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0),
    "ambient": (0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0),
    "shadow_density": (0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0),
    "damping": (0.0, 0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 1.0),
    "fade": (0.0, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.65),
    "sharpness": (0.0, 0.001, 0.125, 0.25, 0.5, 0.625, 0.75, 0.9, 1.0),
    "vorticity": (0.0, 0.2, 0.4, 0.6, 0.8, 1.0, 1.5, 2.0),
    "velocity_scale_multiplier": (0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 8.0, 16.0),
    "time_scale": (0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0),
    "raymarch_quality": (0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0),
}

DEFAULT_SMOKE_BASE_COLOR = (0.58, 0.64, 0.69)

EMITTER_LAYOUT_VALUE_OPTIONS: dict[str, tuple[float | int, ...]] = {
    "emitters_per_row": (5, 6, 7, 8, 9, 10),
    "rows": (1, 2, 3, 4, 5),
    "depth": (0.0, 0.25, 0.5, 0.75, 1.0),
    "size": (0.0, 0.25, 0.5, 0.75, 1.0),
    "horizontal_margin": (0.02, 0.04, 0.08, 0.1),
    "vertical_margin": (0.02, 0.04, 0.08, 0.1),
}

LIGHTING_OVERRIDE_KEYS = (
    "default_hdri_path",
    "exposure",
    "intensity",
    "show_hdri_background",
    "review_key_light_enabled",
    "review_key_light_intensity",
)

SIMULATION_CACHE_OVERRIDE_KEYS = (
    "enabled",
    "runtime_mode",
    "wrapper_path",
    "root_prim_path",
    "volume_prim_path",
    "field_name",
    "sampling_distance",
    "resolution_scale",
    "rendering_samples",
    "filter_mode",
    "airflow_dataset",
    "velocity_field_name",
)


@dataclass(frozen=True)
class AssetEntry:
    """A configured runtime asset."""

    asset_id: str
    label: str
    path: str
    kind: str


@dataclass(frozen=True)
class RotationConfig:
    """Configured XYZ rotation in degrees."""

    x: float
    y: float
    z: float


@dataclass(frozen=True)
class LightingConfig:
    """Configured runtime lighting baseline."""

    hdri_path: str
    exposure: float
    intensity: float
    show_hdri_background: bool
    review_key_light_enabled: bool
    review_key_light_intensity: float
    rotation: RotationConfig


@dataclass(frozen=True)
class CameraConfig:
    """Configured review camera transform in world/session space."""

    position: RotationConfig
    rotation: RotationConfig
    rotation_order: str = "YXZ"
    transform: tuple[float, ...] | None = None


@dataclass(frozen=True)
class GridConfig:
    """Configured review grid visibility and dimensions."""

    enabled: bool = True
    step: float = 0.25
    width: float = 0.00075


@dataclass(frozen=True)
class VisibilityGroupConfig:
    """Runtime-only visibility group for presentation controls."""

    group_id: str
    label: str
    default_visible: bool
    paths: tuple[str, ...]


@dataclass(frozen=True)
class FacePanelConfig:
    """Runtime-only hinge animation for the chassis front panel."""

    enabled: bool = False
    label: str = "Front panel"
    target_path: str = ""
    rotation_axis: str = "X"
    closed_angle_degrees: float = 0.0
    open_angle_degrees: float = -90.0
    animation_duration_seconds: float = 1.0
    default_open: bool = False


@dataclass(frozen=True)
class QledDisplayConfig:
    """Runtime-only two-digit QLED telemetry display."""

    enabled: bool = False
    metric_id: str = "cpu_temp_c"
    warning_threshold_c: float = 100.0
    minimum_value: int = 0
    maximum_value: int = 99
    normal_emission_color: tuple[float, float, float] = (0.9, 0.96, 1.0)
    warning_emission_color: tuple[float, float, float] = (1.0, 0.32, 0.04)
    off_color: tuple[float, float, float] = (0.015, 0.018, 0.022)
    emission_intensity: float = 1.0
    digits: dict[str, dict[str, str]] | None = None


@dataclass(frozen=True)
class FrontPanelIndicatorsConfig:
    """Runtime-only front-panel power, storage, and LAN indicators."""

    enabled: bool = False
    power_path: str = ""
    hdd_path: str = ""
    lan_01_path: str = ""
    lan_02_path: str = ""
    power_color: tuple[float, float, float] = (0.95, 0.98, 1.0)
    hdd_color: tuple[float, float, float] = (0.95, 0.98, 1.0)
    lan_01_color: tuple[float, float, float] = (0.95, 0.98, 1.0)
    lan_02_color: tuple[float, float, float] = (0.95, 0.98, 1.0)
    off_color: tuple[float, float, float] = (0.62, 0.65, 0.68)
    emission_intensity: float = 1.0
    storage_metric_id: str = "storage_activity_percent"
    lan_01_metric_id: str = "lan_1_activity_percent"
    lan_02_metric_id: str = "lan_2_activity_percent"


@dataclass(frozen=True)
class XRayMaterialConfig:
    """Persisted production X-Ray enablement and Custom MDL parameters."""

    chassis_selected: bool = False
    facing_color: tuple[float, float, float] = (1.0, 1.0, 0.0)
    edge_color: tuple[float, float, float] = (0.0, 0.0, 1.0)
    edge_center: float = 0.65
    edge_softness: float = 0.20
    edge_sharpness: float = 1.0
    facing_roughness: float = 0.40
    edge_roughness: float = 0.30
    facing_opacity: float = 0.20
    edge_opacity: float = 0.55
    facing_emission: float = 0.32
    edge_emission: float = 3.20
    emission_scale: float = 10000.0


@dataclass(frozen=True)
class MaterialPresentationConfig:
    """Runtime material presentation settings for the server appearance."""

    normal_map_scale: float = 2.0
    xray: XRayMaterialConfig = XRayMaterialConfig()


@dataclass(frozen=True)
class ChassisPresentationConfig:
    """Runtime-only presentation state for the server enclosure."""

    open_chassis: bool = False
    cover_paths: tuple[str, ...] = ()
    visibility_groups: tuple[VisibilityGroupConfig, ...] = ()
    face_panel: FacePanelConfig = FacePanelConfig()
    qled_display: QledDisplayConfig = QledDisplayConfig()
    front_panel_indicators: FrontPanelIndicatorsConfig = FrontPanelIndicatorsConfig()
    materials: MaterialPresentationConfig = MaterialPresentationConfig()


@dataclass(frozen=True)
class FanMotionBindingConfig:
    """Configured telemetry-driven rotation binding for one runtime fan."""

    binding_id: str
    label: str
    mesh_path: str
    rotation_target_path: str
    rotation_axis: str
    pivot_mode: str
    metric_id: str
    telemetry_min_rpm: float = 650.0
    telemetry_max_rpm: float = 2300.0
    visual_min_rpm: float = 40.0
    visual_max_rpm: float = 360.0


@dataclass(frozen=True)
class IntakeTracerConfig:
    """Shared geometry for the Stage 6 front-intake Flow tracer sources."""

    count: int = 7
    radius: float = 0.01
    front_offset: float = 0.008
    smoke_target: float = 0.5
    smoke_couple_rate: float = 30.0


@dataclass(frozen=True)
class SmokeTuningConfig:
    """Operator-facing NVIDIA Flow settings for the smoke volume."""

    density: float = 0.5
    brightness: float = 1.0
    ambient: float = 1.0
    shadow_density: float = 1.0
    damping: float = 0.0
    fade: float = 0.0
    sharpness: float = 0.9
    vorticity: float = 0.6
    velocity_scale_multiplier: float = 1.0
    time_scale: float = 1.0
    raymarch_quality: float = 0.75
    base_color: tuple[float, float, float] = DEFAULT_SMOKE_BASE_COLOR


@dataclass(frozen=True)
class EmitterLayoutConfig:
    """Normalized operator controls for the procedural intake tracer grid."""

    emitters_per_row: int = 7
    rows: int = 1
    depth: float = 1.0
    size: float = 0.75
    horizontal_margin: float = 0.04
    vertical_margin: float = 0.02


@dataclass(frozen=True)
class SimulationCacheConfig:
    """Configured airflow runtime input and rendering route."""

    enabled: bool = False
    runtime_mode: str = "index"
    wrapper_path: str = ""
    root_prim_path: str = "/sim"
    volume_prim_path: str = "/sim/server_airflow_load_50"
    field_name: str = "density"
    sampling_distance: float = 0.012
    resolution_scale: int = 25
    rendering_samples: int = 1
    filter_mode: str = "nearest"
    airflow_dataset: AirflowDatasetSelector = AirflowDatasetSelector(
        root="airflow_datasets",
        scope="server",
        state="load_normal",
    )
    velocity_field_name: str = "vel"
    temporal_debug_logging: bool = False
    smoke_tuning: SmokeTuningConfig = SmokeTuningConfig()
    emitter_layout: EmitterLayoutConfig = EmitterLayoutConfig()
    intake_tracers: IntakeTracerConfig = IntakeTracerConfig()


@dataclass(frozen=True)
class RuntimeConfig:
    """Resolved runtime configuration for the current DTRS slice."""

    app_name: str
    app_version: str
    config_path: Path
    repo_root: Path
    app_root: Path
    asset_root: Path
    default_asset_id: str
    assets: dict[str, AssetEntry]
    lighting: LightingConfig
    camera: CameraConfig | None
    grid: GridConfig
    chassis_presentation: ChassisPresentationConfig
    fan_motion_bindings: tuple[FanMotionBindingConfig, ...]
    simulation_cache: SimulationCacheConfig

    @classmethod
    def load(
        cls,
        config_path: Path | str,
        apply_local_overrides: bool = True,
    ) -> "RuntimeConfig":
        resolved_config = Path(config_path).resolve()
        with resolved_config.open("rb") as config_file:
            data = tomllib.load(config_file)

        if apply_local_overrides:
            local_path = cls.local_config_path_for(resolved_config)
            if local_path.exists():
                try:
                    with local_path.open("rb") as local_file:
                        local_data = tomllib.load(local_file)
                except tomllib.TOMLDecodeError as error:
                    LOGGER.warning(
                        "Ignoring malformed local DTRS override %s: %s",
                        local_path,
                        error,
                    )
                else:
                    _merge_runtime_override(data, local_data)

        repo_root = resolved_config.parent.parent
        paths = data["paths"]
        app_root = (repo_root / paths["app_root"]).resolve()
        asset_root = (app_root / paths["asset_root"]).resolve()

        asset_entries = {
            asset_id: AssetEntry(
                asset_id=asset_id,
                label=entry["label"],
                path=entry["path"],
                kind=entry["kind"],
            )
            for asset_id, entry in data["assets"]["entries"].items()
        }

        default_asset_id = data["assets"]["default_asset_id"]
        if default_asset_id not in asset_entries:
            raise ValueError(f"Unknown default asset id: {default_asset_id}")

        lighting_data = data.get("lighting", {})
        rotation_data = lighting_data.get("rotation", {})
        lighting = LightingConfig(
            hdri_path=lighting_data.get(
                "default_hdri_path",
                "hdri/kloofendal_48d_partly_cloudy_puresky_4k.exr",
            ),
            exposure=float(lighting_data.get("exposure", 0.0)),
            intensity=float(lighting_data.get("intensity", 1.0)),
            show_hdri_background=bool(lighting_data.get("show_hdri_background", True)),
            review_key_light_enabled=bool(
                lighting_data.get("review_key_light_enabled", True)
            ),
            review_key_light_intensity=float(
                lighting_data.get("review_key_light_intensity", 1200.0)
            ),
            rotation=RotationConfig(
                x=float(rotation_data.get("x", 0.0)),
                y=float(rotation_data.get("y", 0.0)),
                z=float(rotation_data.get("z", 0.0)),
            ),
        )
        camera = _parse_camera_config(data.get("camera"))
        grid = _parse_grid_config(data.get("grid"))
        chassis_presentation = _parse_chassis_presentation_config(
            data.get("chassis_presentation")
        )
        fan_motion_bindings = _parse_fan_motion_bindings(data.get("motion"))
        simulation_cache = _parse_simulation_cache_config(data.get("simulation_cache"))

        return cls(
            app_name=data["app"]["name"],
            app_version=data["app"]["version"],
            config_path=resolved_config,
            repo_root=repo_root,
            app_root=app_root,
            asset_root=asset_root,
            default_asset_id=default_asset_id,
            assets=asset_entries,
            lighting=lighting,
            camera=camera,
            grid=grid,
            chassis_presentation=chassis_presentation,
            fan_motion_bindings=fan_motion_bindings,
            simulation_cache=simulation_cache,
        )

    @property
    def default_asset(self) -> AssetEntry:
        """Return the configured default asset."""

        return self.assets[self.default_asset_id]

    @property
    def default_asset_path(self) -> Path:
        """Return the resolved path for the configured default asset."""

        return (self.asset_root / self.default_asset.path).resolve()

    @property
    def default_hdri_path(self) -> Path:
        """Return the resolved path for the configured default HDRI."""

        return (self.asset_root / self.lighting.hdri_path).resolve()

    @property
    def simulation_cache_path(self) -> Path:
        """Return the resolved path for the configured IndeX cache wrapper."""

        return (self.asset_root / self.simulation_cache.wrapper_path).resolve()

    @property
    def velocity_vti_path(self) -> Path:
        """Return the first discovered VTI sample for compatibility consumers."""

        return self.resolve_airflow_dataset().velocity_vti_path

    @property
    def velocity_vti_sequence_paths(self) -> tuple[Path, ...]:
        """Return the manifest-discovered VTI samples in source-frame order."""

        return self.resolve_airflow_dataset().velocity_vti_sequence_paths

    def resolve_airflow_dataset(self) -> AirflowDataset:
        """Discover the configured external airflow dataset on demand."""

        return discover_airflow_dataset(
            self.asset_root,
            self.simulation_cache.airflow_dataset,
        )

    @property
    def local_config_path(self) -> Path:
        """Return the local operator override path for this config."""

        return self.local_config_path_for(self.config_path)

    @staticmethod
    def local_config_path_for(config_path: Path | str) -> Path:
        """Return the sibling .local.toml path for a runtime config."""

        path = Path(config_path).resolve()
        return path.with_name(f"{path.stem}.local{path.suffix}")


def format_runtime_override(
    lighting: LightingConfig,
    camera: CameraConfig | None = None,
    grid: GridConfig | None = None,
    smoke_tuning: SmokeTuningConfig | None = None,
    emitter_layout: EmitterLayoutConfig | None = None,
    chassis_presentation: ChassisPresentationConfig | None = None,
) -> str:
    """Serialize local operator overrides as minimal TOML."""

    text = (
        "# Local DTRS operator overrides. This file is intentionally ignored by git.\n"
        "\n"
        "[lighting]\n"
        f"default_hdri_path = {_toml_string(lighting.hdri_path)}\n"
        f"exposure = {lighting.exposure:.6g}\n"
        f"intensity = {lighting.intensity:.6g}\n"
        f"show_hdri_background = {_toml_bool(lighting.show_hdri_background)}\n"
        f"review_key_light_enabled = {_toml_bool(lighting.review_key_light_enabled)}\n"
        f"review_key_light_intensity = {lighting.review_key_light_intensity:.6g}\n"
        "\n"
        "[lighting.rotation]\n"
        f"x = {lighting.rotation.x:.6g}\n"
        f"y = {lighting.rotation.y:.6g}\n"
        f"z = {lighting.rotation.z:.6g}\n"
    )
    if camera:
        text += (
            "\n"
            "[camera.position]\n"
            f"x = {camera.position.x:.6g}\n"
            f"y = {camera.position.y:.6g}\n"
            f"z = {camera.position.z:.6g}\n"
            "\n"
            "[camera.rotation]\n"
            f"x = {camera.rotation.x:.6g}\n"
            f"y = {camera.rotation.y:.6g}\n"
            f"z = {camera.rotation.z:.6g}\n"
            f"order = {_toml_string(camera.rotation_order)}\n"
        )
        if camera.transform:
            values = ", ".join(f"{value:.9g}" for value in camera.transform)
            text += "\n" "[camera.transform]\n" f"matrix = [{values}]\n"
    if grid:
        text += (
            "\n"
            "[grid]\n"
            f"enabled = {_toml_bool(grid.enabled)}\n"
            f"step = {grid.step:.6g}\n"
            f"width = {grid.width:.6g}\n"
        )
    if smoke_tuning:
        text += (
            "\n"
            "[simulation_cache.smoke_tuning]\n"
            f"density = {smoke_tuning.density:.6g}\n"
            f"brightness = {smoke_tuning.brightness:.6g}\n"
            f"ambient = {smoke_tuning.ambient:.6g}\n"
            f"shadow_density = {smoke_tuning.shadow_density:.6g}\n"
            f"damping = {smoke_tuning.damping:.6g}\n"
            f"fade = {smoke_tuning.fade:.6g}\n"
            f"sharpness = {smoke_tuning.sharpness:.6g}\n"
            f"vorticity = {smoke_tuning.vorticity:.6g}\n"
            f"velocity_scale_multiplier = "
            f"{smoke_tuning.velocity_scale_multiplier:.6g}\n"
            f"time_scale = {smoke_tuning.time_scale:.6g}\n"
            f"raymarch_quality = {smoke_tuning.raymarch_quality:.6g}\n"
            "base_color = ["
            f"{smoke_tuning.base_color[0]:.6g}, "
            f"{smoke_tuning.base_color[1]:.6g}, "
            f"{smoke_tuning.base_color[2]:.6g}]\n"
        )
    if emitter_layout:
        text += (
            "\n"
            "[simulation_cache.emitter_layout]\n"
            f"emitters_per_row = {emitter_layout.emitters_per_row}\n"
            f"rows = {emitter_layout.rows}\n"
            f"depth = {emitter_layout.depth:.6g}\n"
            f"size = {emitter_layout.size:.6g}\n"
            f"horizontal_margin = {emitter_layout.horizontal_margin:.6g}\n"
            f"vertical_margin = {emitter_layout.vertical_margin:.6g}\n"
        )
    if chassis_presentation and (
        chassis_presentation.visibility_groups
        or chassis_presentation.face_panel.enabled
    ):
        text += "\n[chassis_presentation]\n"
        if chassis_presentation.face_panel.enabled:
            text += (
                "face_panel_open = "
                f"{_toml_bool(chassis_presentation.face_panel.default_open)}\n"
            )
        if chassis_presentation.visibility_groups:
            text += "\n[chassis_presentation.visibility]\n"
            text += "".join(
                f"{_toml_string(group.group_id)} = "
                f"{_toml_bool(group.default_visible)}\n"
                for group in chassis_presentation.visibility_groups
            )
    if chassis_presentation:
        text += (
            "\n[chassis_presentation.materials]\n"
            "normal_map_scale = "
            f"{chassis_presentation.materials.normal_map_scale:.6g}\n"
        )
        xray = chassis_presentation.materials.xray
        text += (
            "\n[chassis_presentation.materials.xray]\n"
            f"chassis_selected = {_toml_bool(xray.chassis_selected)}\n"
            "facing_color = "
            f"[{xray.facing_color[0]:.6g}, "
            f"{xray.facing_color[1]:.6g}, "
            f"{xray.facing_color[2]:.6g}]\n"
            "edge_color = "
            f"[{xray.edge_color[0]:.6g}, "
            f"{xray.edge_color[1]:.6g}, "
            f"{xray.edge_color[2]:.6g}]\n"
            f"edge_center = {xray.edge_center:.6g}\n"
            f"edge_softness = {xray.edge_softness:.6g}\n"
            f"edge_sharpness = {xray.edge_sharpness:.6g}\n"
            f"facing_roughness = {xray.facing_roughness:.6g}\n"
            f"edge_roughness = {xray.edge_roughness:.6g}\n"
            f"facing_opacity = {xray.facing_opacity:.6g}\n"
            f"edge_opacity = {xray.edge_opacity:.6g}\n"
            f"facing_emission = {xray.facing_emission:.6g}\n"
            f"edge_emission = {xray.edge_emission:.6g}\n"
            f"emission_scale = {xray.emission_scale:.6g}\n"
        )
    return text


def _merge_runtime_override(
    data: dict[str, Any],
    local_data: dict[str, Any],
) -> None:
    local_lighting = local_data.get("lighting")
    if isinstance(local_lighting, dict):
        lighting = dict(data.get("lighting", {}))
        for key in LIGHTING_OVERRIDE_KEYS:
            if key in local_lighting:
                lighting[key] = local_lighting[key]

        local_rotation = local_lighting.get("rotation")
        if isinstance(local_rotation, dict):
            rotation = dict(lighting.get("rotation", {}))
            for key in ("x", "y", "z"):
                if key in local_rotation:
                    rotation[key] = local_rotation[key]
            lighting["rotation"] = rotation

        data["lighting"] = lighting

    local_camera = local_data.get("camera")
    if isinstance(local_camera, dict):
        camera = dict(data.get("camera", {}))
        for section_name in ("position", "rotation", "transform"):
            section = local_camera.get(section_name)
            if isinstance(section, dict):
                camera_section = dict(camera.get(section_name, {}))
                if section_name == "transform":
                    if "matrix" in section:
                        camera_section["matrix"] = section["matrix"]
                else:
                    for key in ("x", "y", "z"):
                        if key in section:
                            camera_section[key] = section[key]
                    if section_name == "rotation" and "order" in section:
                        camera_section["order"] = section["order"]
                camera[section_name] = camera_section
        data["camera"] = camera

    local_grid = local_data.get("grid")
    if isinstance(local_grid, dict):
        grid = dict(data.get("grid", {}))
        for key in ("enabled", "step", "width"):
            if key in local_grid:
                grid[key] = local_grid[key]
        data["grid"] = grid

    local_chassis = local_data.get("chassis_presentation")
    if isinstance(local_chassis, dict):
        chassis = dict(data.get("chassis_presentation", {}))
        visibility_groups = chassis.get("visibility_groups")
        local_visibility = local_chassis.get("visibility")
        if local_visibility is not None and not isinstance(local_visibility, dict):
            LOGGER.warning(
                "Ignoring chassis_presentation.visibility local override: "
                "expected a table."
            )
        elif isinstance(local_visibility, dict) and isinstance(visibility_groups, dict):
            updated_groups = dict(visibility_groups)
            for group_id, visible in local_visibility.items():
                group = updated_groups.get(group_id)
                if not isinstance(group, dict):
                    LOGGER.warning(
                        "Ignoring unknown chassis visibility group local override: %s",
                        group_id,
                    )
                    continue
                if not isinstance(visible, bool):
                    LOGGER.warning(
                        "Ignoring chassis visibility override %s=%r; expected bool.",
                        group_id,
                        visible,
                    )
                    continue
                updated_group = dict(group)
                updated_group["default_visible"] = visible
                updated_groups[group_id] = updated_group
            chassis["visibility_groups"] = updated_groups
        elif isinstance(local_visibility, dict):
            LOGGER.warning(
                "Ignoring chassis visibility local override: no configured groups."
            )

        face_panel_open = local_chassis.get("face_panel_open")
        if face_panel_open is not None:
            face_panel = chassis.get("face_panel")
            if not isinstance(face_panel_open, bool):
                LOGGER.warning(
                    "Ignoring chassis face_panel_open=%r; expected bool.",
                    face_panel_open,
                )
            elif not isinstance(face_panel, dict) or not face_panel.get(
                "enabled", False
            ):
                LOGGER.warning(
                    "Ignoring chassis face_panel_open local override: "
                    "no hinge configured."
                )
            else:
                updated_face_panel = dict(face_panel)
                updated_face_panel["default_open"] = face_panel_open
                chassis["face_panel"] = updated_face_panel
        local_materials = local_chassis.get("materials")
        if isinstance(local_materials, dict):
            materials = dict(chassis.get("materials", {}))
            if "normal_map_scale" in local_materials:
                materials["normal_map_scale"] = local_materials["normal_map_scale"]
            local_xray = local_materials.get("xray")
            if isinstance(local_xray, dict):
                xray = dict(materials.get("xray", {}))
                xray.update(local_xray)
                materials["xray"] = xray
            elif local_xray is not None:
                LOGGER.warning(
                    "Ignoring chassis materials X-Ray local override: expected a table."
                )
            chassis["materials"] = materials
        elif local_materials is not None and not isinstance(local_materials, dict):
            LOGGER.warning(
                "Ignoring chassis materials local override: expected a table."
            )
        data["chassis_presentation"] = chassis

    local_simulation_cache = local_data.get("simulation_cache")
    if isinstance(local_simulation_cache, dict):
        base_simulation_cache = data.get("simulation_cache")
        simulation_cache = (
            dict(base_simulation_cache)
            if isinstance(base_simulation_cache, dict)
            else {
                "enabled": any(
                    key in local_simulation_cache
                    for key in SIMULATION_CACHE_OVERRIDE_KEYS
                )
            }
        )
        for key in SIMULATION_CACHE_OVERRIDE_KEYS:
            if key in local_simulation_cache:
                simulation_cache[key] = local_simulation_cache[key]
        local_smoke_tuning = local_simulation_cache.get("smoke_tuning")
        if isinstance(local_smoke_tuning, dict):
            smoke_tuning = dict(simulation_cache.get("smoke_tuning", {}))
            for key in (*SMOKE_TUNING_VALUE_OPTIONS, "base_color"):
                if key in local_smoke_tuning:
                    smoke_tuning[key] = local_smoke_tuning[key]
            simulation_cache["smoke_tuning"] = smoke_tuning
        local_emitter_layout = local_simulation_cache.get("emitter_layout")
        if isinstance(local_emitter_layout, dict):
            emitter_layout = dict(simulation_cache.get("emitter_layout", {}))
            for key in EMITTER_LAYOUT_VALUE_OPTIONS:
                if key in local_emitter_layout:
                    emitter_layout[key] = local_emitter_layout[key]
            simulation_cache["emitter_layout"] = emitter_layout
        data["simulation_cache"] = simulation_cache


def _parse_camera_config(data: Any) -> CameraConfig | None:
    if not isinstance(data, dict):
        return None

    position = data.get("position")
    rotation = data.get("rotation")
    if not isinstance(position, dict) or not isinstance(rotation, dict):
        return None

    return CameraConfig(
        position=RotationConfig(
            x=float(position.get("x", 0.0)),
            y=float(position.get("y", 0.0)),
            z=float(position.get("z", 0.0)),
        ),
        rotation=RotationConfig(
            x=float(rotation.get("x", 0.0)),
            y=float(rotation.get("y", 0.0)),
            z=float(rotation.get("z", 0.0)),
        ),
        rotation_order=str(rotation.get("order", "YXZ")).upper(),
        transform=_parse_matrix(data.get("transform")),
    )


def _parse_grid_config(data: Any) -> GridConfig:
    if not isinstance(data, dict):
        return GridConfig()

    return GridConfig(
        enabled=bool(data.get("enabled", True)),
        step=float(data.get("step", 0.25)),
        width=float(data.get("width", 0.00075)),
    )


def _parse_chassis_presentation_config(data: Any) -> ChassisPresentationConfig:
    if not isinstance(data, dict):
        return ChassisPresentationConfig()

    raw_paths = data.get("cover_paths", ())
    if not isinstance(raw_paths, (list, tuple)):
        raise ValueError("chassis_presentation.cover_paths must be an array.")

    cover_paths = tuple(str(path).strip() for path in raw_paths if str(path).strip())
    if any(not path.startswith("/") for path in cover_paths):
        raise ValueError("chassis_presentation cover paths must be absolute USD paths.")

    return ChassisPresentationConfig(
        open_chassis=bool(data.get("open_chassis", False)),
        cover_paths=cover_paths,
        visibility_groups=_parse_visibility_groups(data.get("visibility_groups")),
        face_panel=_parse_face_panel_config(data.get("face_panel")),
        qled_display=_parse_qled_display_config(data.get("qled_display")),
        front_panel_indicators=_parse_front_panel_indicators_config(
            data.get("front_panel_indicators")
        ),
        materials=_parse_material_presentation_config(data.get("materials")),
    )


def _parse_material_presentation_config(data: Any) -> MaterialPresentationConfig:
    if not isinstance(data, dict):
        return MaterialPresentationConfig()

    normal_map_scale = float(data.get("normal_map_scale", 2.0))
    if not 0.0 <= normal_map_scale <= 4.0:
        raise ValueError("materials.normal_map_scale must be between 0 and 4.")
    return MaterialPresentationConfig(
        normal_map_scale=normal_map_scale,
        xray=_parse_xray_material_config(data.get("xray")),
    )


def _parse_xray_material_config(data: Any) -> XRayMaterialConfig:
    if not isinstance(data, dict):
        return XRayMaterialConfig()

    defaults = XRayMaterialConfig()
    selected = data.get("chassis_selected", defaults.chassis_selected)
    if not isinstance(selected, bool):
        raise ValueError("materials.xray.chassis_selected must be a bool.")

    def parse_color(field: str, default: tuple[float, float, float]):
        color = _parse_rgb(data.get(field), default, f"materials.xray.{field}")
        if any(component < 0.0 or component > 1.0 for component in color):
            raise ValueError(f"materials.xray.{field} values must be between 0 and 1.")
        return color

    values = {
        "edge_center": float(data.get("edge_center", defaults.edge_center)),
        "edge_softness": float(data.get("edge_softness", defaults.edge_softness)),
        "edge_sharpness": float(data.get("edge_sharpness", defaults.edge_sharpness)),
        "facing_roughness": float(
            data.get("facing_roughness", defaults.facing_roughness)
        ),
        "edge_roughness": float(data.get("edge_roughness", defaults.edge_roughness)),
        "facing_opacity": float(data.get("facing_opacity", defaults.facing_opacity)),
        "edge_opacity": float(data.get("edge_opacity", defaults.edge_opacity)),
        "facing_emission": float(data.get("facing_emission", defaults.facing_emission)),
        "edge_emission": float(data.get("edge_emission", defaults.edge_emission)),
        "emission_scale": float(data.get("emission_scale", defaults.emission_scale)),
    }
    for field, value in values.items():
        if not math.isfinite(value):
            raise ValueError(f"materials.xray.{field} must be finite.")
    if not 0.0 <= values["edge_center"] <= 1.0:
        raise ValueError("materials.xray.edge_center must be between 0 and 1.")
    if not 0.001 <= values["edge_softness"] <= 1.0:
        raise ValueError("materials.xray.edge_softness must be between 0.001 and 1.")
    if not 0.1 <= values["edge_sharpness"] <= 8.0:
        raise ValueError("materials.xray.edge_sharpness must be between 0.1 and 8.")
    for field in (
        "facing_roughness",
        "edge_roughness",
        "facing_opacity",
        "edge_opacity",
    ):
        if not 0.0 <= values[field] <= 1.0:
            raise ValueError(f"materials.xray.{field} must be between 0 and 1.")
    for field in ("facing_emission", "edge_emission", "emission_scale"):
        if values[field] < 0.0:
            raise ValueError(
                f"materials.xray.{field} must be greater than or equal to 0."
            )
    return XRayMaterialConfig(
        chassis_selected=selected,
        facing_color=parse_color("facing_color", defaults.facing_color),
        edge_color=parse_color("edge_color", defaults.edge_color),
        **values,
    )


def chassis_presentation_with_operator_state(
    presentation: ChassisPresentationConfig,
    visibility_by_group: dict[str, bool],
    face_panel_open: bool | None,
) -> ChassisPresentationConfig:
    """Validate and apply only operator-owned enclosure presentation state."""

    known_groups = {group.group_id for group in presentation.visibility_groups}
    if len(known_groups) != len(presentation.visibility_groups):
        raise ValueError("chassis visibility group ids must be unique.")
    unknown_groups = set(visibility_by_group) - known_groups
    if unknown_groups:
        names = ", ".join(sorted(unknown_groups))
        raise ValueError(f"unknown chassis visibility groups: {names}")
    if any(not isinstance(visible, bool) for visible in visibility_by_group.values()):
        raise ValueError("chassis visibility values must be boolean.")
    if face_panel_open is not None and not isinstance(face_panel_open, bool):
        raise ValueError("face panel state must be boolean.")
    if face_panel_open is not None and not presentation.face_panel.enabled:
        raise ValueError("no front-panel hinge is configured.")

    visibility_groups = tuple(
        replace(
            group,
            default_visible=visibility_by_group.get(
                group.group_id,
                group.default_visible,
            ),
        )
        for group in presentation.visibility_groups
    )
    face_panel = presentation.face_panel
    if face_panel_open is not None:
        face_panel = replace(face_panel, default_open=face_panel_open)
    return replace(
        presentation,
        visibility_groups=visibility_groups,
        face_panel=face_panel,
    )


def _parse_front_panel_indicators_config(data: Any) -> FrontPanelIndicatorsConfig:
    if not isinstance(data, dict):
        return FrontPanelIndicatorsConfig()

    enabled = bool(data.get("enabled", True))
    paths = {
        field: str(data.get(field, "")).strip()
        for field in ("power_path", "hdd_path", "lan_01_path", "lan_02_path")
    }
    if enabled:
        for field, path in paths.items():
            if not path or not path.startswith("/"):
                raise ValueError(
                    "chassis_presentation.front_panel_indicators paths must be "
                    f"absolute USD paths: {field}"
                )

    return FrontPanelIndicatorsConfig(
        enabled=enabled,
        power_path=paths["power_path"],
        hdd_path=paths["hdd_path"],
        lan_01_path=paths["lan_01_path"],
        lan_02_path=paths["lan_02_path"],
        power_color=_parse_rgb(
            data.get("power_color"),
            (0.95, 0.98, 1.0),
            "chassis_presentation.front_panel_indicators.power_color",
        ),
        hdd_color=_parse_rgb(
            data.get("hdd_color"),
            (0.95, 0.98, 1.0),
            "chassis_presentation.front_panel_indicators.hdd_color",
        ),
        lan_01_color=_parse_rgb(
            data.get("lan_01_color"),
            (0.95, 0.98, 1.0),
            "chassis_presentation.front_panel_indicators.lan_01_color",
        ),
        lan_02_color=_parse_rgb(
            data.get("lan_02_color"),
            (0.95, 0.98, 1.0),
            "chassis_presentation.front_panel_indicators.lan_02_color",
        ),
        off_color=_parse_rgb(
            data.get("off_color"),
            (0.62, 0.65, 0.68),
            "chassis_presentation.front_panel_indicators.off_color",
        ),
        emission_intensity=float(data.get("emission_intensity", 1.0)),
        storage_metric_id=str(
            data.get("storage_metric_id", "storage_activity_percent")
        ).strip()
        or "storage_activity_percent",
        lan_01_metric_id=str(
            data.get("lan_01_metric_id", "lan_1_activity_percent")
        ).strip()
        or "lan_1_activity_percent",
        lan_02_metric_id=str(
            data.get("lan_02_metric_id", "lan_2_activity_percent")
        ).strip()
        or "lan_2_activity_percent",
    )


def _parse_qled_display_config(data: Any) -> QledDisplayConfig:
    if not isinstance(data, dict):
        return QledDisplayConfig()

    enabled = bool(data.get("enabled", True))
    digits = _parse_qled_digits(data.get("digits"))
    if enabled and not digits:
        raise ValueError("chassis_presentation.qled_display.digits is required.")

    minimum_value = int(data.get("minimum_value", 0))
    maximum_value = int(data.get("maximum_value", 99))
    if minimum_value < 0 or maximum_value > 99 or minimum_value > maximum_value:
        raise ValueError(
            "chassis_presentation.qled_display range must stay inside 0..99."
        )

    return QledDisplayConfig(
        enabled=enabled,
        metric_id=str(data.get("metric_id", "cpu_temp_c")).strip() or "cpu_temp_c",
        warning_threshold_c=float(data.get("warning_threshold_c", 100.0)),
        minimum_value=minimum_value,
        maximum_value=maximum_value,
        normal_emission_color=_parse_rgb(
            data.get("normal_emission_color"),
            (0.9, 0.96, 1.0),
            "chassis_presentation.qled_display.normal_emission_color",
        ),
        warning_emission_color=_parse_rgb(
            data.get("warning_emission_color"),
            (1.0, 0.32, 0.04),
            "chassis_presentation.qled_display.warning_emission_color",
        ),
        off_color=_parse_rgb(
            data.get("off_color"),
            (0.015, 0.018, 0.022),
            "chassis_presentation.qled_display.off_color",
        ),
        emission_intensity=float(data.get("emission_intensity", 1.0)),
        digits=digits,
    )


def _parse_qled_digits(data: Any) -> dict[str, dict[str, str]] | None:
    if not isinstance(data, dict):
        return None

    parsed: dict[str, dict[str, str]] = {}
    for digit_name in ("tens", "units"):
        raw_digit = data.get(digit_name)
        if not isinstance(raw_digit, dict):
            raise ValueError(
                f"chassis_presentation.qled_display.digits.{digit_name} is required."
            )
        parsed[digit_name] = {}
        for segment in ("a", "b", "c", "d", "e", "f", "g"):
            path = str(raw_digit.get(segment, "")).strip()
            if not path or not path.startswith("/"):
                raise ValueError(
                    "QLED segment paths must be absolute USD paths: "
                    f"{digit_name}.{segment}"
                )
            parsed[digit_name][segment] = path
    return parsed


def _parse_rgb(data: Any, default: tuple[float, float, float], field: str):
    if data is None:
        return default
    if not isinstance(data, list) or len(data) != 3:
        raise ValueError(f"{field} must be an RGB array.")
    return tuple(float(value) for value in data)


def _parse_face_panel_config(data: Any) -> FacePanelConfig:
    if not isinstance(data, dict):
        return FacePanelConfig()

    enabled = bool(data.get("enabled", True))
    target_path = str(data.get("target_path", "")).strip()
    if enabled:
        if not target_path:
            raise ValueError("chassis_presentation.face_panel.target_path is required.")
        if not target_path.startswith("/"):
            raise ValueError(
                "chassis_presentation.face_panel.target_path must be an absolute "
                "USD path."
            )

    rotation_axis = str(data.get("rotation_axis", "X")).upper().strip()
    if rotation_axis not in {"X", "Y", "Z"}:
        raise ValueError(
            "chassis_presentation.face_panel.rotation_axis must be X, Y, or Z."
        )

    duration = float(data.get("animation_duration_seconds", 1.0))
    if duration < 0.0:
        raise ValueError(
            "chassis_presentation.face_panel.animation_duration_seconds must be "
            "non-negative."
        )

    return FacePanelConfig(
        enabled=enabled,
        label=str(data.get("label", "Front panel")).strip() or "Front panel",
        target_path=target_path,
        rotation_axis=rotation_axis,
        closed_angle_degrees=float(data.get("closed_angle_degrees", 0.0)),
        open_angle_degrees=float(data.get("open_angle_degrees", -90.0)),
        animation_duration_seconds=duration,
        default_open=bool(data.get("default_open", False)),
    )


def _parse_visibility_groups(data: Any) -> tuple[VisibilityGroupConfig, ...]:
    if not isinstance(data, dict):
        return ()

    groups: list[VisibilityGroupConfig] = []
    for group_id, entry in data.items():
        if not isinstance(entry, dict):
            continue
        label = str(entry.get("label", group_id)).strip()
        raw_paths = entry.get("paths", ())
        if not isinstance(raw_paths, (list, tuple)):
            raise ValueError(
                f"chassis_presentation.visibility_groups.{group_id}.paths "
                "must be an array."
            )
        paths = tuple(str(path).strip() for path in raw_paths if str(path).strip())
        if not paths:
            raise ValueError(
                f"chassis_presentation visibility group {group_id} has no paths."
            )
        if any(not path.startswith("/") for path in paths):
            raise ValueError(
                f"chassis_presentation visibility group {group_id} paths "
                "must be absolute USD paths."
            )
        groups.append(
            VisibilityGroupConfig(
                group_id=str(group_id).strip(),
                label=label,
                default_visible=bool(entry.get("default_visible", True)),
                paths=paths,
            )
        )
    return tuple(groups)


def _parse_fan_motion_bindings(data: Any) -> tuple[FanMotionBindingConfig, ...]:
    if not isinstance(data, dict) or data.get("enabled", True) is False:
        return ()

    raw_bindings = data.get("fan_bindings", ())
    if not isinstance(raw_bindings, list):
        return ()

    bindings: list[FanMotionBindingConfig] = []
    for index, entry in enumerate(raw_bindings, start=1):
        if not isinstance(entry, dict):
            continue
        binding_id = str(entry.get("id", f"fan_{index}")).strip()
        label = str(entry.get("label", binding_id)).strip()
        mesh_path = str(entry.get("mesh_path", "")).strip()
        rotation_target_path = str(entry.get("rotation_target_path", "")).strip()
        rotation_axis = str(entry.get("rotation_axis", "")).upper().strip()
        pivot_mode = str(entry.get("pivot_mode", "auto")).strip()
        metric_id = str(entry.get("metric_id", "")).strip()
        if not mesh_path or not rotation_target_path or not metric_id:
            raise ValueError(f"Incomplete fan motion binding: {binding_id}")
        if rotation_axis not in {"X", "Y", "Z"}:
            raise ValueError(
                f"Fan motion binding {binding_id} has unsupported axis: "
                f"{rotation_axis}"
            )
        if pivot_mode not in {"auto", "authored_origin", "topology_pivot"}:
            raise ValueError(
                f"Fan motion binding {binding_id} has unsupported pivot mode: "
                f"{pivot_mode}"
            )
        bindings.append(
            FanMotionBindingConfig(
                binding_id=binding_id,
                label=label,
                mesh_path=mesh_path,
                rotation_target_path=rotation_target_path,
                rotation_axis=rotation_axis,
                pivot_mode=pivot_mode,
                metric_id=metric_id,
                telemetry_min_rpm=float(entry.get("telemetry_min_rpm", 650.0)),
                telemetry_max_rpm=float(entry.get("telemetry_max_rpm", 2300.0)),
                visual_min_rpm=float(entry.get("visual_min_rpm", 40.0)),
                visual_max_rpm=float(entry.get("visual_max_rpm", 360.0)),
            )
        )
    return tuple(bindings)


def validate_smoke_tuning(tuning: SmokeTuningConfig) -> None:
    """Raise when a requested operator value is outside the supported menu."""

    for field_name, supported_values in SMOKE_TUNING_VALUE_OPTIONS.items():
        value = getattr(tuning, field_name)
        if value not in supported_values:
            allowed = ", ".join(f"{item:g}" for item in supported_values)
            raise ValueError(f"smoke_tuning.{field_name} must be one of: {allowed}.")
    if len(tuning.base_color) != 3 or any(
        not isinstance(component, (int, float))
        or isinstance(component, bool)
        or not 0.0 <= float(component) <= 1.0
        for component in tuning.base_color
    ):
        raise ValueError("smoke_tuning.base_color must be three RGB values in [0, 1].")


def _parse_smoke_tuning_config(data: Any) -> SmokeTuningConfig:
    defaults = SmokeTuningConfig()
    if not isinstance(data, dict):
        return defaults

    values: dict[str, float] = {}
    for field_name, supported_values in SMOKE_TUNING_VALUE_OPTIONS.items():
        default = getattr(defaults, field_name)
        raw_value = data.get(field_name, default)
        try:
            if isinstance(raw_value, bool):
                raise ValueError
            value = float(raw_value)
        except (TypeError, ValueError):
            LOGGER.warning(
                "Unsupported smoke_tuning.%s=%r; using installed Flow default %s.",
                field_name,
                raw_value,
                default,
            )
            value = default
        if value not in supported_values:
            LOGGER.warning(
                "Unsupported smoke_tuning.%s=%r; using installed Flow default %s.",
                field_name,
                raw_value,
                default,
            )
            value = default
        values[field_name] = value
    return SmokeTuningConfig(
        **values,
        base_color=_parse_smoke_base_color(data.get("base_color"), defaults.base_color),
    )


def _parse_smoke_base_color(
    data: Any,
    default: tuple[float, float, float],
) -> tuple[float, float, float]:
    try:
        color = _parse_rgb(data, default, "simulation_cache.smoke_tuning.base_color")
        if any(not 0.0 <= component <= 1.0 for component in color):
            raise ValueError
        return color
    except (TypeError, ValueError):
        LOGGER.warning(
            "Unsupported smoke_tuning.base_color=%r; using existing Flow color %s.",
            data,
            default,
        )
        return default


def validate_emitter_layout(layout: EmitterLayoutConfig) -> None:
    """Raise when a requested layout value is outside the supported menu."""

    for field_name, supported_values in EMITTER_LAYOUT_VALUE_OPTIONS.items():
        value = getattr(layout, field_name)
        if value not in supported_values:
            allowed = ", ".join(f"{item:g}" for item in supported_values)
            raise ValueError(f"emitter_layout.{field_name} must be one of: {allowed}.")


def _parse_emitter_layout_config(data: Any) -> EmitterLayoutConfig:
    defaults = EmitterLayoutConfig()
    if not isinstance(data, dict):
        return defaults

    values: dict[str, float | int] = {}
    for field_name, supported_values in EMITTER_LAYOUT_VALUE_OPTIONS.items():
        default = getattr(defaults, field_name)
        raw_value = data.get(field_name, default)
        try:
            if isinstance(raw_value, bool):
                raise ValueError
            if isinstance(default, int):
                numeric_value = float(raw_value)
                if not numeric_value.is_integer():
                    raise ValueError
                value = int(numeric_value)
            else:
                value = float(raw_value)
        except (TypeError, ValueError):
            LOGGER.warning(
                "Unsupported emitter_layout.%s=%r; using default %s.",
                field_name,
                raw_value,
                default,
            )
            value = default
        if value not in supported_values:
            LOGGER.warning(
                "Unsupported emitter_layout.%s=%r; using default %s.",
                field_name,
                raw_value,
                default,
            )
            value = default
        values[field_name] = value
    return EmitterLayoutConfig(**values)


def _parse_simulation_cache_config(data: Any) -> SimulationCacheConfig:
    if not isinstance(data, dict):
        return SimulationCacheConfig()

    enabled = bool(data.get("enabled", True))
    runtime_mode = str(data.get("runtime_mode", "index")).strip().lower()
    wrapper_path = str(data.get("wrapper_path", "")).strip()
    raw_airflow_dataset = data.get("airflow_dataset", {})
    if not isinstance(raw_airflow_dataset, dict):
        raise ValueError("simulation_cache.airflow_dataset must be a table.")
    airflow_dataset = AirflowDatasetSelector(
        root=str(raw_airflow_dataset.get("root", "")).strip(),
        scope=str(raw_airflow_dataset.get("scope", "")).strip(),
        state=str(raw_airflow_dataset.get("state", "")).strip(),
    )
    velocity_field_name = str(data.get("velocity_field_name", "vel")).strip()
    temporal_debug_logging = bool(data.get("temporal_debug_logging", False))
    smoke_tuning = _parse_smoke_tuning_config(data.get("smoke_tuning"))
    emitter_layout = _parse_emitter_layout_config(data.get("emitter_layout"))
    raw_intake_tracers = data.get("intake_tracers", {})
    if not isinstance(raw_intake_tracers, dict):
        raise ValueError("simulation_cache.intake_tracers must be a table.")
    intake_tracers = IntakeTracerConfig(
        count=int(raw_intake_tracers.get("count", 7)),
        radius=float(raw_intake_tracers.get("radius", 0.01)),
        front_offset=float(raw_intake_tracers.get("front_offset", 0.008)),
        smoke_target=float(raw_intake_tracers.get("smoke_target", 0.5)),
        smoke_couple_rate=float(raw_intake_tracers.get("smoke_couple_rate", 30.0)),
    )
    if runtime_mode not in {"index", "kit_cae"}:
        raise ValueError("simulation_cache.runtime_mode must be 'index' or 'kit_cae'.")
    if enabled and runtime_mode == "index" and not wrapper_path:
        raise ValueError("simulation_cache.wrapper_path is required when enabled.")
    if (
        enabled
        and runtime_mode == "kit_cae"
        and not all(
            (
                airflow_dataset.root,
                airflow_dataset.scope,
                airflow_dataset.state,
            )
        )
    ):
        raise ValueError(
            "simulation_cache.airflow_dataset root, scope, and state are required "
            "for the Kit-CAE route."
        )

    root_prim_path = str(data.get("root_prim_path", "/sim")).strip()
    volume_prim_path = str(
        data.get("volume_prim_path", "/sim/server_airflow_load_50")
    ).strip()
    field_name = str(data.get("field_name", "density")).strip()
    sampling_distance = float(data.get("sampling_distance", 0.012))
    resolution_scale = int(data.get("resolution_scale", 25))
    rendering_samples = int(data.get("rendering_samples", 1))
    filter_mode = str(data.get("filter_mode", "nearest")).strip().lower()
    for field_name_value, value in (
        ("root_prim_path", root_prim_path),
        ("volume_prim_path", volume_prim_path),
    ):
        if not value.startswith("/"):
            raise ValueError(
                f"simulation_cache.{field_name_value} must be an absolute USD path."
            )
    if not field_name:
        raise ValueError("simulation_cache.field_name must not be empty.")
    if not velocity_field_name:
        raise ValueError("simulation_cache.velocity_field_name must not be empty.")
    if intake_tracers.count != 7:
        raise ValueError("simulation_cache.intake_tracers.count must be 7.")
    if intake_tracers.radius <= 0:
        raise ValueError("simulation_cache.intake_tracers.radius must be positive.")
    if intake_tracers.front_offset <= 0:
        raise ValueError(
            "simulation_cache.intake_tracers.front_offset must be positive."
        )
    if intake_tracers.smoke_target <= 0:
        raise ValueError(
            "simulation_cache.intake_tracers.smoke_target must be positive."
        )
    if intake_tracers.smoke_couple_rate <= 0:
        raise ValueError(
            "simulation_cache.intake_tracers.smoke_couple_rate must be positive."
        )
    if sampling_distance <= 0:
        raise ValueError("simulation_cache.sampling_distance must be positive.")
    if not 1 <= resolution_scale <= 100:
        raise ValueError("simulation_cache.resolution_scale must be in 1..100.")
    if not 1 <= rendering_samples <= 32:
        raise ValueError("simulation_cache.rendering_samples must be in 1..32.")
    if filter_mode not in {"nearest", "trilinear"}:
        raise ValueError(
            "simulation_cache.filter_mode must be 'nearest' or 'trilinear'."
        )
    return SimulationCacheConfig(
        enabled=enabled,
        runtime_mode=runtime_mode,
        wrapper_path=wrapper_path,
        root_prim_path=root_prim_path,
        volume_prim_path=volume_prim_path,
        field_name=field_name,
        sampling_distance=sampling_distance,
        resolution_scale=resolution_scale,
        rendering_samples=rendering_samples,
        filter_mode=filter_mode,
        airflow_dataset=airflow_dataset,
        velocity_field_name=velocity_field_name,
        temporal_debug_logging=temporal_debug_logging,
        smoke_tuning=smoke_tuning,
        emitter_layout=emitter_layout,
        intake_tracers=intake_tracers,
    )


def _parse_matrix(data: Any) -> tuple[float, ...] | None:
    if not isinstance(data, dict):
        return None

    matrix = data.get("matrix")
    if not isinstance(matrix, list) or len(matrix) != 16:
        return None

    return tuple(float(value) for value in matrix)


def _toml_bool(value: bool) -> str:
    return "true" if value else "false"


def _toml_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'
