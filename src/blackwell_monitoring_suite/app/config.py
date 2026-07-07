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
    "review_key_light_enabled",
    "review_key_light_intensity",
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
