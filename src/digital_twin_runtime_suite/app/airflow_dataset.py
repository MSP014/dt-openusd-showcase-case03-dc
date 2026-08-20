"""Manifest-driven discovery and validation for external airflow datasets."""

from __future__ import annotations

import math
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

_KNOWN_AIRFLOW_STATE_ORDER = {
    "load_idle": 0,
    "load_normal": 1,
    "load_surge": 2,
    "load_critical": 3,
}


class AirflowDatasetError(ValueError):
    """Raised when an external airflow dataset violates its portable contract."""


@dataclass(frozen=True)
class AirflowDatasetSelector:
    """Configured identity of one external airflow dataset."""

    root: str
    scope: str
    state: str


@dataclass(frozen=True)
class AirflowDatasetManifest:
    """Typed temporal and spatial contract declared beside VTI samples."""

    scope: str
    state: str
    source_fps: float
    sample_step_frames: int
    sample_rate_hz: float
    sample_count: int
    grid: tuple[int, int, int]
    duration_seconds: float | None = None

    @property
    def sample_interval_seconds(self) -> float:
        return self.sample_step_frames / self.source_fps

    @property
    def loop_duration_seconds(self) -> float:
        return (
            self.duration_seconds
            if self.duration_seconds is not None
            else self.sample_count * self.sample_interval_seconds
        )


@dataclass(frozen=True)
class AirflowDataset:
    """One discovered VTI sequence with validated manifest timing metadata."""

    root: Path
    directory: Path
    manifest_path: Path
    manifest: AirflowDatasetManifest
    velocity_vti_sequence_paths: tuple[Path, ...]
    source_frames: tuple[int, ...]

    @property
    def velocity_vti_path(self) -> Path:
        return self.velocity_vti_sequence_paths[0]

    @property
    def sample_interval_seconds(self) -> float:
        return self.manifest.sample_interval_seconds

    @property
    def loop_duration_seconds(self) -> float:
        return self.manifest.loop_duration_seconds


def discover_airflow_dataset_registry(
    asset_root: Path,
    dataset_root: str,
) -> tuple[AirflowDataset, ...]:
    """Discover every valid airflow dataset by manifest identity.

    Directory names organise the hydrated asset package only. The stable runtime
    identity is the ``(scope, state)`` pair declared in each manifest.
    """

    root = _resolve_dataset_root(asset_root, dataset_root)
    datasets: dict[tuple[str, str], AirflowDataset] = {}
    for manifest_path in sorted(
        root.rglob("manifest.toml"), key=lambda path: str(path)
    ):
        manifest = parse_airflow_dataset_manifest(manifest_path)
        identity = (manifest.scope, manifest.state)
        existing = datasets.get(identity)
        if existing:
            paths = ", ".join(
                str(path)
                for path in sorted(
                    (existing.manifest_path.parent, manifest_path.parent)
                )
            )
            raise AirflowDatasetError(
                "Airflow dataset identity is ambiguous: "
                f"scope={manifest.scope}, state={manifest.state}; matches={paths}"
            )
        datasets[identity] = _build_airflow_dataset(root, manifest_path, manifest)
    return tuple(
        datasets[identity]
        for identity in sorted(datasets, key=_registry_identity_sort_key)
    )


def format_airflow_dataset_registry(datasets: tuple[AirflowDataset, ...]) -> str:
    """Return content for the isolated startup dataset-registry diagnostic."""

    lines = [
        "DTRS AIRFLOW DATASET REGISTRY",
        f"Discovered: {len(datasets)}",
    ]
    lines.extend(
        f"{dataset.manifest.scope}/{dataset.manifest.state}" for dataset in datasets
    )
    return "\n".join(lines)


def discover_airflow_dataset(
    asset_root: Path,
    selector: AirflowDatasetSelector,
) -> AirflowDataset:
    """Discover the registry once, then resolve one manifest identity from it."""

    registry = discover_airflow_dataset_registry(asset_root, selector.root)
    return resolve_airflow_dataset_from_registry(registry, selector)


def resolve_airflow_dataset_from_registry(
    registry: tuple[AirflowDataset, ...],
    selector: AirflowDatasetSelector,
) -> AirflowDataset:
    """Resolve one selector from already discovered authoritative datasets."""

    _validate_selector(selector)
    matches = tuple(
        dataset
        for dataset in registry
        if (dataset.manifest.scope, dataset.manifest.state)
        == (selector.scope, selector.state)
    )
    if not matches:
        raise AirflowDatasetError(
            "Airflow dataset not found:\n"
            f"scope={selector.scope}\n"
            f"state={selector.state}"
        )
    if len(matches) > 1:
        paths = ", ".join(str(dataset.directory) for dataset in matches)
        raise AirflowDatasetError(
            "Airflow dataset identity is ambiguous: "
            f"scope={selector.scope}, state={selector.state}; matches={paths}"
        )
    return matches[0]


def parse_airflow_dataset_manifest(manifest_path: Path) -> AirflowDatasetManifest:
    """Parse and validate the manifest colocated with one VTI dataset."""

    try:
        with manifest_path.open("rb") as stream:
            data = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise AirflowDatasetError(
            f"Malformed airflow dataset manifest: {manifest_path}: {error}"
        ) from error
    if not isinstance(data, dict):
        raise AirflowDatasetError(
            f"Malformed airflow dataset manifest: {manifest_path}"
        )

    try:
        scope = _required_string(data, "scope", manifest_path)
        state = _required_string(data, "state", manifest_path)
        source_fps = _positive_float(data, "source_fps", manifest_path)
        sample_step_frames = _positive_int(data, "sample_step_frames", manifest_path)
        sample_rate_hz = _positive_float(data, "sample_rate_hz", manifest_path)
        sample_count = _positive_int(data, "sample_count", manifest_path)
        grid = _grid(data.get("grid"), manifest_path)
        duration_seconds = (
            _positive_float(data, "duration", manifest_path)
            if "duration" in data
            else None
        )
    except (TypeError, ValueError) as error:
        raise AirflowDatasetError(
            f"Malformed airflow dataset manifest: {manifest_path}: {error}"
        ) from error

    derived_rate_hz = source_fps / sample_step_frames
    if not math.isclose(sample_rate_hz, derived_rate_hz, rel_tol=1e-6, abs_tol=1e-6):
        raise AirflowDatasetError(
            "Airflow dataset sample rate disagrees with source timing: "
            f"manifest={sample_rate_hz:g} Hz, derived={derived_rate_hz:g} Hz, "
            f"manifest={manifest_path}"
        )
    derived_duration_seconds = sample_count * sample_step_frames / source_fps
    if duration_seconds is not None and not math.isclose(
        duration_seconds,
        derived_duration_seconds,
        rel_tol=1e-6,
        abs_tol=1e-6,
    ):
        raise AirflowDatasetError(
            "Airflow dataset duration disagrees with source timing: "
            f"manifest={duration_seconds:g} s, derived={derived_duration_seconds:g} s, "
            f"manifest={manifest_path}"
        )
    return AirflowDatasetManifest(
        scope=scope,
        state=state,
        source_fps=source_fps,
        sample_step_frames=sample_step_frames,
        sample_rate_hz=sample_rate_hz,
        sample_count=sample_count,
        grid=grid,
        duration_seconds=duration_seconds,
    )


def validate_airflow_dataset_grid(
    dataset: AirflowDataset,
    actual_grid: tuple[int, int, int],
) -> None:
    """Require the imported VTI dimensions to match the manifest contract."""

    if tuple(actual_grid) != dataset.manifest.grid:
        raise AirflowDatasetError(
            "Airflow dataset grid mismatch: "
            f"manifest={dataset.manifest.grid}, actual={tuple(actual_grid)}, "
            f"manifest={dataset.manifest_path}"
        )


def _resolve_dataset_root(asset_root: Path, dataset_root: str) -> Path:
    root = (asset_root / dataset_root).resolve()
    if not root.is_dir():
        raise AirflowDatasetError(f"Airflow dataset root does not exist: {root}")
    return root


def _registry_identity_sort_key(identity: tuple[str, str]) -> tuple[str, int, str]:
    scope, state = identity
    return (
        scope,
        _KNOWN_AIRFLOW_STATE_ORDER.get(state, len(_KNOWN_AIRFLOW_STATE_ORDER)),
        state,
    )


def _build_airflow_dataset(
    root: Path,
    manifest_path: Path,
    manifest: AirflowDatasetManifest,
) -> AirflowDataset:
    samples = _discover_velocity_samples(manifest_path.parent)
    _validate_velocity_samples(manifest_path, manifest, samples)
    return AirflowDataset(
        root=root,
        directory=manifest_path.parent,
        manifest_path=manifest_path,
        manifest=manifest,
        velocity_vti_sequence_paths=tuple(path for _, path in samples),
        source_frames=tuple(frame for frame, _ in samples),
    )


def _discover_velocity_samples(directory: Path) -> tuple[tuple[int, Path], ...]:
    candidates = tuple(directory.glob("*.vti"))
    if not candidates:
        raise AirflowDatasetError(
            f"Airflow dataset VTI samples are absent: {directory}"
        )
    samples = []
    for path in candidates:
        match = re.search(r"(\d+)$", path.stem)
        if not match:
            raise AirflowDatasetError(
                f"Airflow VTI sample has no numeric source-frame suffix: {path.name}"
            )
        samples.append((int(match.group(1)), path))
    return tuple(sorted(samples, key=lambda item: item[0]))


def _validate_velocity_samples(
    manifest_path: Path,
    manifest: AirflowDatasetManifest,
    samples: tuple[tuple[int, Path], ...],
) -> None:
    frames = tuple(frame for frame, _ in samples)
    if len(samples) != manifest.sample_count:
        raise AirflowDatasetError(
            "Airflow dataset sample count mismatch: "
            f"manifest={manifest.sample_count}, actual={len(samples)}, "
            f"manifest={manifest_path}"
        )
    if len(set(frames)) != len(frames):
        raise AirflowDatasetError(
            f"Airflow dataset contains duplicate source frames: {manifest_path}"
        )
    if any(later <= earlier for earlier, later in zip(frames, frames[1:])):
        raise AirflowDatasetError(
            "Airflow dataset source frames are not strictly increasing: "
            f"{manifest_path}"
        )
    if any(
        later - earlier != manifest.sample_step_frames
        for earlier, later in zip(frames, frames[1:])
    ):
        raise AirflowDatasetError(
            "Airflow dataset source-frame spacing does not match manifest "
            f"sample_step_frames={manifest.sample_step_frames}: {manifest_path}"
        )


def _validate_selector(selector: AirflowDatasetSelector) -> None:
    if not (
        selector.root.strip() and selector.scope.strip() and selector.state.strip()
    ):
        raise AirflowDatasetError(
            "Airflow dataset root, scope, and state must be configured."
        )


def _required_string(data: dict, key: str, manifest_path: Path) -> str:
    value = str(data.get(key, "")).strip()
    if not value:
        raise ValueError(f"{key} is required in {manifest_path}")
    return value


def _positive_float(data: dict, key: str, manifest_path: Path) -> float:
    value = data.get(key)
    if isinstance(value, bool):
        raise ValueError(f"{key} must be positive in {manifest_path}")
    numeric = float(value)
    if not math.isfinite(numeric) or numeric <= 0:
        raise ValueError(f"{key} must be positive in {manifest_path}")
    return numeric


def _positive_int(data: dict, key: str, manifest_path: Path) -> int:
    value = _positive_float(data, key, manifest_path)
    if not value.is_integer():
        raise ValueError(f"{key} must be an integer in {manifest_path}")
    return int(value)


def _grid(value, manifest_path: Path) -> tuple[int, int, int]:
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(
            f"grid must contain three positive integers in {manifest_path}"
        )
    parsed = tuple(
        _positive_int({"grid": component}, "grid", manifest_path) for component in value
    )
    return parsed
