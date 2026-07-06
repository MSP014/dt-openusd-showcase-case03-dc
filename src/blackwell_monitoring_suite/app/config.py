"""Runtime configuration loading for Blackwell Monitoring Suite."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AssetEntry:
    """A configured runtime asset."""

    asset_id: str
    label: str
    path: str
    kind: str


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

    @classmethod
    def load(cls, config_path: Path | str) -> "RuntimeConfig":
        resolved_config = Path(config_path).resolve()
        with resolved_config.open("rb") as config_file:
            data = tomllib.load(config_file)

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

        return cls(
            app_name=data["app"]["name"],
            app_version=data["app"]["version"],
            config_path=resolved_config,
            repo_root=repo_root,
            app_root=app_root,
            asset_root=asset_root,
            default_asset_id=default_asset_id,
            assets=asset_entries,
        )

    @property
    def default_asset(self) -> AssetEntry:
        """Return the configured default asset."""

        return self.assets[self.default_asset_id]

    @property
    def default_asset_path(self) -> Path:
        """Return the resolved path for the configured default asset."""

        return (self.asset_root / self.default_asset.path).resolve()
