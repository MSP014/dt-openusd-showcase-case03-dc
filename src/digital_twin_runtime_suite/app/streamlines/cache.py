"""Derived-cache contracts for persisted, manifest-exact Streamlines states."""

from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from digital_twin_runtime_suite.app.streamlines.constant_topology import (
    SOURCE_CURVE_VERTEX_COUNTS_ATTRIBUTE,
    renderer_topology_for_profile,
)
from digital_twin_runtime_suite.app.streamlines.lifecycle import (
    STREAMLINES_CACHE_PLAYBACK_ROOT,
)
from digital_twin_runtime_suite.app.streamlines.profile import (
    StreamlinesProfileId,
)
from digital_twin_runtime_suite.app.streamlines.proof import (
    StreamlinesOperatorRequest,
)
from digital_twin_runtime_suite.app.streamlines.temporal import (
    TemporalVelocitySourceDescriptor,
)

CACHE_SCHEMA_VERSION = 5
CACHE_DIRECTORY_NAME = "streamlines"
CACHE_PLAYBACK_ROOT_PATH = STREAMLINES_CACHE_PLAYBACK_ROOT
CACHE_PLAYBACK_SOURCE_PATH = f"{CACHE_PLAYBACK_ROOT_PATH}/Source"
CACHE_PLAYBACK_SOURCE_CURVES_PATH = f"{CACHE_PLAYBACK_SOURCE_PATH}/Geometry"
CACHE_PLAYBACK_CURVES_PATH = f"{CACHE_PLAYBACK_ROOT_PATH}/Geometry"
CACHE_BUILD_OPERATOR_PATH = "/DTRS_KitCAE/Streamlines/CacheBuilder"
CACHE_BUILD_SEED_PATH = "/DTRS_KitCAE/StreamlineSeeds/CacheBuildProfileGrid"
SPEED_EVIDENCE_QUANTILE_COUNT = 101


@dataclass(frozen=True)
class StreamlinesCacheOwnership:
    """Stable workload, dataset, and geometry-profile cache ownership."""

    workload: str
    dataset_identity: str
    profile_id: str = StreamlinesProfileId.GLOBAL_FLOW_PATH.value

    def __post_init__(self) -> None:
        """Reject a cache path that cannot identify its authoritative owner."""

        if (
            not self.workload.strip()
            or not self.dataset_identity.strip()
            or not self.profile_id.strip()
        ):
            raise ValueError(
                "Streamlines cache ownership requires workload, dataset, and profile."
            )

    @property
    def identity(self) -> str:
        """Return the human-readable ownership key persisted in metadata."""

        return f"{self.workload}|{self.dataset_identity}|{self.profile_id}"

    @property
    def path_components(self) -> tuple[str, str, str]:
        """Return filesystem-safe components derived only from ownership."""

        return (
            _cache_path_component(self.workload),
            _cache_path_component(self.dataset_identity),
            _cache_path_component(self.profile_id),
        )


@dataclass(frozen=True)
class StreamlinesCachePaths:
    """Canonical on-disk locations for one ownership-specific cache."""

    ownership: StreamlinesCacheOwnership
    directory: Path
    metadata_path: Path
    geometry_path: Path
    partial_metadata_path: Path
    partial_geometry_path: Path
    previous_metadata_path: Path
    previous_geometry_path: Path


@dataclass(frozen=True)
class StreamlinesCacheSettings:
    """Canonical geometry-affecting Streamlines settings kept with a cache."""

    operator_type: str
    direction: str
    seed_azimuth_samples: int
    seed_polar_samples: int
    seed_center: tuple[float, float, float]
    seed_radius: float
    min_step_size: float
    initial_step_size: float
    max_step_size: float
    max_steps: int
    width: float
    seed_resolution: int
    profile_name: str
    profile_id: str
    profile_signature: str
    seed_layout_signature: str
    persisted_attributes: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        """Return the portable, deterministic payload covered by the signature."""

        return {
            "operator_type": self.operator_type,
            "direction": self.direction,
            "seed_azimuth_samples": self.seed_azimuth_samples,
            "seed_polar_samples": self.seed_polar_samples,
            "seed_center": list(self.seed_center),
            "seed_radius": self.seed_radius,
            "min_step_size": self.min_step_size,
            "initial_step_size": self.initial_step_size,
            "max_step_size": self.max_step_size,
            "max_steps": self.max_steps,
            "width": self.width,
            "seed_resolution": self.seed_resolution,
            "profile_name": self.profile_name,
            "profile_id": self.profile_id,
            "profile_signature": self.profile_signature,
            "seed_layout_signature": self.seed_layout_signature,
            "persisted_attributes": list(self.persisted_attributes),
        }

    @classmethod
    def from_dict(cls, data: object) -> "StreamlinesCacheSettings":
        """Parse persisted canonical settings before cache playback."""

        if not isinstance(data, dict):
            raise ValueError("Cache settings must be an object.")
        seed_center = data.get("seed_center")
        if not isinstance(seed_center, list) or len(seed_center) != 3:
            raise ValueError("Cache seed centre must contain three values.")
        return cls(
            operator_type=_normalise_token(data["operator_type"]),
            direction=_normalise_token(data["direction"]),
            seed_azimuth_samples=int(data["seed_azimuth_samples"]),
            seed_polar_samples=int(data["seed_polar_samples"]),
            seed_center=tuple(_normalise_float(value) for value in seed_center),
            seed_radius=_normalise_float(data["seed_radius"]),
            min_step_size=_normalise_float(data["min_step_size"]),
            initial_step_size=_normalise_float(data["initial_step_size"]),
            max_step_size=_normalise_float(data["max_step_size"]),
            max_steps=int(data["max_steps"]),
            width=_normalise_float(data["width"]),
            seed_resolution=int(data["seed_resolution"]),
            profile_name=_normalise_token(data["profile_name"]),
            profile_id=_normalise_token(data["profile_id"]),
            profile_signature=_normalise_token(data["profile_signature"]),
            seed_layout_signature=_normalise_token(data["seed_layout_signature"]),
            persisted_attributes=_normalise_persisted_attributes(
                data["persisted_attributes"]
            ),
        )


@dataclass(frozen=True)
class StreamlinesCacheState:
    """Exact source provenance and geometry summary for one cached state."""

    sample_index: int
    source_time_seconds: float
    time_code: float
    source_vti: str
    source_vti_identity: str
    curve_count: int
    point_count: int
    topology_signature: str
    geometry_signature: str
    generation_ms: float
    bounds: tuple[tuple[float, float, float], tuple[float, float, float]]
    source_point_count: int = 0
    source_topology_signature: str = ""

    def to_dict(self) -> dict[str, object]:
        """Return JSON-safe state metadata without duplicating curve points."""

        return {
            "sample_index": self.sample_index,
            "source_time_seconds": self.source_time_seconds,
            "time_code": self.time_code,
            "source_vti": self.source_vti,
            "source_vti_identity": self.source_vti_identity,
            "curve_count": self.curve_count,
            "point_count": self.point_count,
            "topology_signature": self.topology_signature,
            "geometry_signature": self.geometry_signature,
            "generation_ms": self.generation_ms,
            "bounds": [list(bound) for bound in self.bounds],
            "source_point_count": self.source_point_count,
            "source_topology_signature": self.source_topology_signature,
        }

    @classmethod
    def from_dict(cls, data: object) -> "StreamlinesCacheState":
        """Parse one persisted state while rejecting incomplete provenance."""

        if not isinstance(data, dict):
            raise ValueError("Cache state must be an object.")
        bounds = _normalise_bounds(data.get("bounds"))
        return cls(
            sample_index=int(data["sample_index"]),
            source_time_seconds=float(data["source_time_seconds"]),
            time_code=float(data["time_code"]),
            source_vti=str(data["source_vti"]),
            source_vti_identity=str(data["source_vti_identity"]),
            curve_count=int(data["curve_count"]),
            point_count=int(data["point_count"]),
            topology_signature=str(data["topology_signature"]),
            geometry_signature=str(data["geometry_signature"]),
            generation_ms=float(data["generation_ms"]),
            bounds=bounds,
            source_point_count=int(data.get("source_point_count", data["point_count"])),
            source_topology_signature=str(
                data.get("source_topology_signature", data["topology_signature"])
            ),
        )


@dataclass(frozen=True)
class StreamlinesCacheSpeedEvidence:
    """Compact authentic-vertex speed evidence authored during a Volume build."""

    value_count: int
    minimum: float
    p01: float
    p05: float
    p50: float
    p95: float
    p99: float
    maximum: float
    quantile_values: tuple[float, ...]

    def to_dict(self) -> dict[str, object]:
        """Return a compact JSON-safe cache-side presentation evidence record."""

        return {
            "value_count": self.value_count,
            "minimum": self.minimum,
            "p01": self.p01,
            "p05": self.p05,
            "p50": self.p50,
            "p95": self.p95,
            "p99": self.p99,
            "maximum": self.maximum,
            "quantile_values": list(self.quantile_values),
        }

    @classmethod
    def from_dict(cls, data: object) -> "StreamlinesCacheSpeedEvidence":
        """Parse build-time speed evidence without loading any USD arrays."""

        if not isinstance(data, dict):
            raise ValueError("Cache speed evidence must be an object.")
        # Accepted caches can contain retired Critical/Volume state-p99 audit
        # keys. Pooled Volume quantiles are now authoritative, so unknown keys
        # remain deliberately ignored instead of forcing a cache rebuild.
        quantiles = tuple(float(value) for value in data["quantile_values"])
        evidence = cls(
            value_count=int(data["value_count"]),
            minimum=float(data["minimum"]),
            p01=float(data["p01"]),
            p05=float(data["p05"]),
            p50=float(data["p50"]),
            p95=float(data["p95"]),
            p99=float(data["p99"]),
            maximum=float(data["maximum"]),
            quantile_values=quantiles,
        )
        evidence._validate()
        return evidence

    def _validate(self) -> None:
        """Reject malformed compact evidence before it can choose a palette scale."""

        values = (
            self.minimum,
            self.p01,
            self.p05,
            self.p50,
            self.p95,
            self.p99,
            self.maximum,
            *self.quantile_values,
        )
        if self.value_count <= 0 or any(
            not math.isfinite(value) or value < 0.0 for value in values
        ):
            raise ValueError("Cache speed evidence contains invalid values.")
        if len(self.quantile_values) != SPEED_EVIDENCE_QUANTILE_COUNT:
            raise ValueError("Cache speed evidence quantile count is invalid.")
        if tuple(sorted(self.quantile_values)) != self.quantile_values:
            raise ValueError("Cache speed evidence quantiles are not ordered.")
        if not (
            self.minimum
            <= self.p01
            <= self.p05
            <= self.p50
            <= self.p95
            <= self.p99
            <= self.maximum
        ):
            raise ValueError("Cache speed evidence percentiles are inconsistent.")


@dataclass(frozen=True)
class StreamlinesCacheMetadata:
    """Persistent identity and completeness receipt for a derived cache."""

    schema_version: int
    state: str
    workload: str
    dataset_identity: str
    source_signature: str
    settings_signature: str
    settings: StreamlinesCacheSettings | None
    sample_count: int
    sample_interval_seconds: float
    time_codes_per_second: float
    topology_consistent: bool
    geometry_file_name: str
    geometry_sha256: str
    states: tuple[StreamlinesCacheState, ...]
    profile_id: str = StreamlinesProfileId.GLOBAL_FLOW_PATH.value
    speed_evidence: StreamlinesCacheSpeedEvidence | None = None

    @property
    def valid(self) -> bool:
        """Return whether this receipt represents a complete cache only."""

        return self.state == "VALID"

    def to_dict(self) -> dict[str, object]:
        """Return the portable cache receipt persisted beside the USDC file."""

        return {
            "schema_version": self.schema_version,
            "state": self.state,
            "workload": self.workload,
            "dataset_identity": self.dataset_identity,
            "profile_id": self.profile_id,
            "source_signature": self.source_signature,
            "settings_signature": self.settings_signature,
            "settings": self.settings.to_dict() if self.settings else None,
            "sample_count": self.sample_count,
            "sample_interval_seconds": self.sample_interval_seconds,
            "time_codes_per_second": self.time_codes_per_second,
            "topology_consistent": self.topology_consistent,
            "geometry_file_name": self.geometry_file_name,
            "geometry_sha256": self.geometry_sha256,
            "states": [state.to_dict() for state in self.states],
            "speed_evidence": (
                self.speed_evidence.to_dict() if self.speed_evidence else None
            ),
        }

    @classmethod
    def from_dict(cls, data: object) -> "StreamlinesCacheMetadata":
        """Parse a cache receipt before any geometry is attached to DTRS."""

        if not isinstance(data, dict):
            raise ValueError("Streamlines cache metadata must be an object.")
        raw_states = data.get("states")
        if not isinstance(raw_states, list):
            raise ValueError("Streamlines cache metadata states must be a list.")
        return cls(
            schema_version=int(data["schema_version"]),
            state=str(data["state"]),
            workload=str(data["workload"]),
            dataset_identity=str(data["dataset_identity"]),
            profile_id=str(data["profile_id"]),
            source_signature=str(data["source_signature"]),
            settings_signature=str(data["settings_signature"]),
            settings=(
                StreamlinesCacheSettings.from_dict(data["settings"])
                if data.get("settings") is not None
                else None
            ),
            sample_count=int(data["sample_count"]),
            sample_interval_seconds=float(data["sample_interval_seconds"]),
            time_codes_per_second=float(data["time_codes_per_second"]),
            topology_consistent=bool(data["topology_consistent"]),
            geometry_file_name=str(data["geometry_file_name"]),
            geometry_sha256=str(data["geometry_sha256"]),
            states=tuple(
                StreamlinesCacheState.from_dict(state) for state in raw_states
            ),
            speed_evidence=(
                StreamlinesCacheSpeedEvidence.from_dict(data["speed_evidence"])
                if data.get("speed_evidence") is not None
                else None
            ),
        )


@dataclass(frozen=True)
class StreamlinesCacheValidation:
    """Plain validation outcome used before loading a persistent cache layer."""

    valid: bool
    message: str
    geometry_sha256_recomputed: bool = False


def streamlines_cache_paths(
    repo_root: Path,
    ownership: StreamlinesCacheOwnership,
) -> StreamlinesCachePaths:
    """Return one stable ownership-derived cache path without creating it."""

    workload_component, dataset_component, profile_component = ownership.path_components
    directory = (
        repo_root
        / "cache"
        / CACHE_DIRECTORY_NAME
        / workload_component
        / dataset_component
        / profile_component
    )
    stem = "streamlines_cache"
    return StreamlinesCachePaths(
        ownership=ownership,
        directory=directory,
        metadata_path=directory / f"{stem}.json",
        geometry_path=directory / f"{stem}.usdc",
        partial_metadata_path=directory / f"{stem}.partial.json",
        partial_geometry_path=directory / f"{stem}.partial.usdc",
        previous_metadata_path=directory / f"{stem}.previous.json",
        previous_geometry_path=directory / f"{stem}.previous.usdc",
    )


def source_signature_from_temporal_source(
    source: TemporalVelocitySourceDescriptor,
) -> str:
    """Hash manifest identity and real VTI identities for cache invalidation."""

    return source_signature_from_values(
        workload=source.workload,
        dataset_identity=source.dataset_identity,
        velocity_paths=source.velocity_paths,
        sample_time_codes=source.sample_time_codes,
        time_codes_per_second=source.time_codes_per_second,
        sample_interval_seconds=source.sample_interval_seconds,
    )


def source_signature_from_values(
    *,
    workload: str,
    dataset_identity: str,
    velocity_paths: tuple[Path, ...],
    sample_time_codes: tuple[float, ...],
    time_codes_per_second: float,
    sample_interval_seconds: float,
) -> str:
    """Hash the manifest clock and file identities without Kit/USD state."""

    if len(velocity_paths) != len(sample_time_codes):
        raise ValueError("Cache source paths and time codes must have equal length.")
    payload = {
        "workload": workload,
        "dataset_identity": dataset_identity,
        "sample_interval_seconds": float(sample_interval_seconds),
        "time_codes_per_second": float(time_codes_per_second),
        "samples": [
            {
                "sample_index": index,
                "time_code": float(time_code),
                "source_vti_identity": vti_file_identity(path),
            }
            for index, (path, time_code) in enumerate(
                zip(velocity_paths, sample_time_codes)
            )
        ],
    }
    return _signature(payload)


def streamlines_cache_settings(
    request: StreamlinesOperatorRequest,
) -> StreamlinesCacheSettings:
    """Extract only deterministic settings that affect generated geometry."""

    return StreamlinesCacheSettings(
        operator_type=_normalise_token(request.operator_type),
        direction=_normalise_token(request.direction),
        seed_azimuth_samples=int(request.seed_resolution),
        seed_polar_samples=int(request.seed_resolution),
        seed_center=tuple(_normalise_float(value) for value in request.seed_center),
        seed_radius=_normalise_float(request.seed_radius),
        min_step_size=_normalise_float(request.min_step_size),
        initial_step_size=_normalise_float(request.initial_step_size),
        max_step_size=_normalise_float(request.max_step_size),
        max_steps=int(request.max_steps),
        width=_normalise_float(request.width),
        seed_resolution=int(request.seed_resolution),
        profile_name=_normalise_token(request.profile_name),
        profile_id=_normalise_token(request.profile_id),
        profile_signature=_normalise_token(request.profile_signature),
        seed_layout_signature=_normalise_token(request.seed_layout_signature),
        persisted_attributes=_normalise_persisted_attributes(
            request.persisted_attributes
        ),
    )


def streamlines_settings_signature(
    request: StreamlinesOperatorRequest,
) -> str:
    """Hash the canonical geometry settings, never transient runtime paths."""

    return _signature(streamlines_cache_settings(request).to_dict())


def cache_settings_payload_signature(settings: StreamlinesCacheSettings) -> str:
    """Return the signature covered by one persisted settings payload."""

    return _signature(settings.to_dict())


def build_streamlines_cache_metadata(
    source: TemporalVelocitySourceDescriptor,
    request: StreamlinesOperatorRequest,
    states: Iterable[StreamlinesCacheState],
    *,
    geometry_file_name: str,
    geometry_sha256: str,
    speed_evidence: StreamlinesCacheSpeedEvidence | None = None,
) -> StreamlinesCacheMetadata:
    """Create a VALID receipt only when every real manifest sample is cached."""

    ordered_states = tuple(sorted(states, key=lambda state: state.sample_index))
    _validate_complete_state_sequence(source, ordered_states)
    topology_consistent = (
        len({state.topology_signature for state in ordered_states}) == 1
    )
    return StreamlinesCacheMetadata(
        schema_version=CACHE_SCHEMA_VERSION,
        state="VALID",
        workload=source.workload,
        dataset_identity=source.dataset_identity,
        profile_id=request.profile_id,
        source_signature=source_signature_from_temporal_source(source),
        settings_signature=streamlines_settings_signature(request),
        settings=streamlines_cache_settings(request),
        sample_count=source.sample_count,
        sample_interval_seconds=source.sample_interval_seconds,
        time_codes_per_second=source.time_codes_per_second,
        topology_consistent=topology_consistent,
        geometry_file_name=geometry_file_name,
        geometry_sha256=geometry_sha256,
        states=ordered_states,
        speed_evidence=speed_evidence,
    )


def validate_streamlines_cache(
    metadata: StreamlinesCacheMetadata,
    *,
    source: TemporalVelocitySourceDescriptor,
    settings_signature: str,
    geometry_path: Path,
) -> StreamlinesCacheValidation:
    """Reject a cache that diverges from the same resolved source contract."""

    if metadata.schema_version != CACHE_SCHEMA_VERSION:
        return StreamlinesCacheValidation(False, "Cache schema version is stale.")
    if not metadata.valid:
        return StreamlinesCacheValidation(False, "Cache is not marked VALID.")
    if (
        metadata.workload != source.workload
        or metadata.dataset_identity != source.dataset_identity
    ):
        return StreamlinesCacheValidation(False, "Cache workload or dataset differs.")
    if metadata.source_signature != source_signature_from_temporal_source(source):
        return StreamlinesCacheValidation(False, "Cache source manifest is stale.")
    if metadata.settings is None:
        return StreamlinesCacheValidation(
            False,
            "Cache canonical settings provenance is unavailable; "
            "explicit rebuild required.",
        )
    if metadata.profile_id != metadata.settings.profile_id:
        return StreamlinesCacheValidation(False, "Cache profile identity differs.")
    if _signature(metadata.settings.to_dict()) != metadata.settings_signature:
        return StreamlinesCacheValidation(
            False,
            "Cache settings payload does not match its signature.",
        )
    if metadata.settings_signature != settings_signature:
        return StreamlinesCacheValidation(False, "Cache settings or seed are stale.")
    if (
        metadata.sample_count != source.sample_count
        or len(metadata.states) != source.sample_count
    ):
        return StreamlinesCacheValidation(False, "Cache state count is incomplete.")
    if metadata.sample_interval_seconds != source.sample_interval_seconds:
        return StreamlinesCacheValidation(False, "Cache sample timing is stale.")
    if metadata.time_codes_per_second != source.time_codes_per_second:
        return StreamlinesCacheValidation(False, "Cache time-code rate is stale.")
    topology = renderer_topology_for_profile(metadata.profile_id)
    expected_topology_signature = topology_signature(topology.curve_vertex_counts)
    if not metadata.topology_consistent or any(
        state.curve_count != topology.curve_count
        or state.point_count != topology.point_count
        or state.topology_signature != expected_topology_signature
        or state.source_point_count <= 0
        or state.source_point_count > topology.point_count
        or not state.source_topology_signature
        for state in metadata.states
    ):
        return StreamlinesCacheValidation(
            False,
            "Cache renderer topology is incompatible.",
        )
    if SOURCE_CURVE_VERTEX_COUNTS_ATTRIBUTE.lower() not in (
        metadata.settings.persisted_attributes
    ):
        return StreamlinesCacheValidation(
            False,
            "Cache source topology provenance is unavailable.",
        )
    if geometry_path.name != metadata.geometry_file_name:
        return StreamlinesCacheValidation(False, "Cache geometry path is unexpected.")
    if not geometry_path.is_file():
        return StreamlinesCacheValidation(False, "Cache geometry file is missing.")
    if file_sha256(geometry_path) != metadata.geometry_sha256:
        return StreamlinesCacheValidation(
            False,
            "Cache geometry file is stale.",
            geometry_sha256_recomputed=True,
        )
    try:
        _validate_complete_state_sequence(source, metadata.states)
    except ValueError as error:
        return StreamlinesCacheValidation(
            False,
            str(error),
            geometry_sha256_recomputed=True,
        )
    if any(
        state.curve_count <= 0 or state.point_count <= 0 for state in metadata.states
    ):
        return StreamlinesCacheValidation(
            False,
            "Cache contains empty geometry.",
            geometry_sha256_recomputed=True,
        )
    return StreamlinesCacheValidation(
        True,
        "Cache matches the active manifest.",
        geometry_sha256_recomputed=True,
    )


def streamlines_cache_build_mode(paths: StreamlinesCachePaths) -> str:
    """Classify an explicit build without validating or selecting any cache."""

    artifact_paths = (
        paths.metadata_path,
        paths.geometry_path,
        paths.partial_metadata_path,
        paths.partial_geometry_path,
        paths.previous_metadata_path,
        paths.previous_geometry_path,
    )
    if any(path.exists() for path in artifact_paths):
        return "REBUILD"
    return "NEW"


def replace_streamlines_cache_artifacts(paths: StreamlinesCachePaths) -> None:
    """Replace a complete staged cache while restoring prior finals on failure."""

    staged_paths = (paths.partial_geometry_path, paths.partial_metadata_path)
    if not all(path.is_file() for path in staged_paths):
        raise RuntimeError("Complete staged Streamlines cache artifacts are required.")

    final_paths = (paths.geometry_path, paths.metadata_path)
    previous_paths = (paths.previous_geometry_path, paths.previous_metadata_path)
    existing = tuple(path.is_file() for path in final_paths)
    for final_path, previous_path, exists in zip(
        final_paths,
        previous_paths,
        existing,
    ):
        previous_path.unlink(missing_ok=True)
        if exists:
            shutil.copy2(final_path, previous_path)
    try:
        paths.partial_geometry_path.replace(paths.geometry_path)
        paths.partial_metadata_path.replace(paths.metadata_path)
    except Exception:
        for final_path, previous_path, existed in zip(
            final_paths,
            previous_paths,
            existing,
        ):
            if existed:
                previous_path.replace(final_path)
            else:
                final_path.unlink(missing_ok=True)
        raise
    finally:
        for previous_path in previous_paths:
            previous_path.unlink(missing_ok=True)


def discard_streamlines_cache_staging(paths: StreamlinesCachePaths) -> None:
    """Remove only incomplete artifacts; completed cache files are untouched."""

    paths.partial_geometry_path.unlink(missing_ok=True)
    paths.partial_metadata_path.unlink(missing_ok=True)


def cache_settings_differences(
    cached: StreamlinesCacheSettings | None,
    current: StreamlinesCacheSettings,
) -> tuple[str, ...]:
    """Identify only geometry-setting differences after signature mismatch."""

    if cached is None:
        return ("canonical settings payload unavailable",)
    cached_payload = cached.to_dict()
    current_payload = current.to_dict()
    return tuple(
        field_name
        for field_name in cached_payload
        if cached_payload[field_name] != current_payload[field_name]
    )


def serialise_streamlines_cache_metadata(
    metadata: StreamlinesCacheMetadata,
) -> str:
    """Return deterministic JSON so cache receipts are diffable when needed."""

    return json.dumps(metadata.to_dict(), indent=2, sort_keys=True)


def load_streamlines_cache_metadata(path: Path) -> StreamlinesCacheMetadata:
    """Load only the lightweight receipt; it never starts a Kit operator."""

    with path.open("r", encoding="utf-8") as stream:
        return StreamlinesCacheMetadata.from_dict(json.load(stream))


def vti_file_identity(path: Path) -> str:
    """Return a stable local identity that invalidates replaced VTI inputs."""

    resolved = path.resolve()
    stats = resolved.stat()
    return f"{resolved.as_posix()}|size={stats.st_size}|mtime_ns={stats.st_mtime_ns}"


def file_sha256(path: Path) -> str:
    """Return a content digest for a completed derived geometry artifact."""

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def topology_signature(curve_vertex_counts: Iterable[int]) -> str:
    """Hash curve topology without retaining a second copy of the full array."""

    return _signature(tuple(int(count) for count in curve_vertex_counts))


def geometry_signature(
    *,
    curve_count: int,
    point_count: int,
    bounds: tuple[tuple[float, float, float], tuple[float, float, float]],
    point_head: Iterable[tuple[float, float, float]],
    point_tail: Iterable[tuple[float, float, float]],
) -> str:
    """Hash bounded geometry evidence used to detect wrong cached states."""

    return _signature(
        {
            "curve_count": int(curve_count),
            "point_count": int(point_count),
            "bounds": bounds,
            "point_head": tuple(point_head),
            "point_tail": tuple(point_tail),
        }
    )


def _validate_complete_state_sequence(
    source: TemporalVelocitySourceDescriptor,
    states: tuple[StreamlinesCacheState, ...],
) -> None:
    if len(states) != source.sample_count:
        raise ValueError("Partial Streamlines cache cannot be marked VALID.")
    for index, state in enumerate(states):
        expected_path = source.velocity_paths[index].resolve().as_posix()
        expected_time_code = source.sample_time_codes[index]
        if state.sample_index != index:
            raise ValueError("Cache states must have contiguous manifest indices.")
        if state.source_vti != expected_path:
            raise ValueError("Cache state VTI does not match the manifest.")
        if state.source_vti_identity != vti_file_identity(source.velocity_paths[index]):
            raise ValueError("Cache state VTI identity does not match the manifest.")
        if state.time_code != expected_time_code:
            raise ValueError("Cache state time code does not match the manifest.")
        if state.source_time_seconds != (
            expected_time_code / source.time_codes_per_second
        ):
            raise ValueError("Cache state source time does not match the manifest.")


def _cache_path_component(value: str) -> str:
    """Make an ownership component portable without consulting cache contents."""

    normalised = re.sub(r"[^a-z0-9._-]+", "_", value.strip().lower())
    if not normalised:
        raise ValueError("Streamlines cache path component is empty.")
    return normalised


def _normalise_bounds(
    value: object,
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    try:
        minimum, maximum = value
        return (
            tuple(float(component) for component in minimum),
            tuple(float(component) for component in maximum),
        )
    except (TypeError, ValueError) as error:
        raise ValueError("Cache geometry bounds are unavailable.") from error


def _normalise_token(value: object) -> str:
    """Return one comparable spelling for a string or enum setting."""

    candidate = getattr(value, "value", value)
    token = str(candidate).strip().lower()
    if not token:
        raise ValueError("Cache setting token cannot be empty.")
    return token


def _normalise_float(value: object) -> float:
    """Reject non-finite values and collapse signed zero before JSON hashing."""

    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Cache numeric setting must be finite.")
    return 0.0 if number == 0.0 else number


def _normalise_persisted_attributes(value: object) -> tuple[str, ...]:
    """Keep one deterministic non-empty list of persisted cache attributes."""

    if not isinstance(value, (list, tuple)) or not value:
        raise ValueError("Cache persisted attributes must be a non-empty list.")
    attributes = tuple(_normalise_token(item) for item in value)
    if len(set(attributes)) != len(attributes):
        raise ValueError("Cache persisted attributes must be unique.")
    return attributes


def _signature(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
