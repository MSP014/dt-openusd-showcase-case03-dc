"""Runtime configuration loading for Blackwell Monitoring Suite."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
    "velocity_vti_path",
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
class ChassisPresentationConfig:
    """Runtime-only presentation state for the server enclosure."""

    open_chassis: bool = False
    cover_paths: tuple[str, ...] = ()
    visibility_groups: tuple[VisibilityGroupConfig, ...] = ()
    face_panel: FacePanelConfig = FacePanelConfig()
    qled_display: QledDisplayConfig = QledDisplayConfig()
    front_panel_indicators: FrontPanelIndicatorsConfig = FrontPanelIndicatorsConfig()


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
    velocity_vti_path: str = ""
    velocity_field_name: str = "vel"


@dataclass(frozen=True)
class RuntimeConfig:
    """Resolved runtime configuration for the current BMS slice."""

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
                with local_path.open("rb") as local_file:
                    local_data = tomllib.load(local_file)
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
        """Return the resolved Houdini-generated VTI velocity field."""

        return (self.asset_root / self.simulation_cache.velocity_vti_path).resolve()

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
) -> str:
    """Serialize local operator overrides as minimal TOML."""

    text = (
        "# Local BMS operator overrides. This file is intentionally ignored by git.\n"
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

    local_simulation_cache = local_data.get("simulation_cache")
    if isinstance(local_simulation_cache, dict):
        simulation_cache = dict(data.get("simulation_cache", {}))
        for key in SIMULATION_CACHE_OVERRIDE_KEYS:
            if key in local_simulation_cache:
                simulation_cache[key] = local_simulation_cache[key]
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
    if not isinstance(raw_paths, list):
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
        if not isinstance(raw_paths, list):
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


def _parse_simulation_cache_config(data: Any) -> SimulationCacheConfig:
    if not isinstance(data, dict):
        return SimulationCacheConfig()

    enabled = bool(data.get("enabled", True))
    runtime_mode = str(data.get("runtime_mode", "index")).strip().lower()
    wrapper_path = str(data.get("wrapper_path", "")).strip()
    velocity_vti_path = str(data.get("velocity_vti_path", "")).strip()
    velocity_field_name = str(data.get("velocity_field_name", "vel")).strip()
    if runtime_mode not in {"index", "kit_cae"}:
        raise ValueError("simulation_cache.runtime_mode must be 'index' or 'kit_cae'.")
    if enabled and runtime_mode == "index" and not wrapper_path:
        raise ValueError("simulation_cache.wrapper_path is required when enabled.")
    if enabled and runtime_mode == "kit_cae" and not velocity_vti_path:
        raise ValueError(
            "simulation_cache.velocity_vti_path is required for the Kit-CAE route."
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
        velocity_vti_path=velocity_vti_path,
        velocity_field_name=velocity_field_name,
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
