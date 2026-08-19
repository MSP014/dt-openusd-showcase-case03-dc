"""Read-only classification of workload-owned Streamlines cache artifacts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from digital_twin_runtime_suite.app.streamlines.cache import (
    CACHE_SCHEMA_VERSION,
    StreamlinesCacheMetadata,
    StreamlinesCacheOwnership,
    StreamlinesCachePaths,
    cache_settings_payload_signature,
    load_streamlines_cache_metadata,
    validate_streamlines_cache,
)
from digital_twin_runtime_suite.app.streamlines.temporal import (
    TemporalVelocitySourceDescriptor,
)


@dataclass(frozen=True)
class StreamlinesCacheInspection:
    """Read-only classification of one expected workload cache artifact."""

    ownership: StreamlinesCacheOwnership
    paths: StreamlinesCachePaths
    classification: str
    message: str
    metadata: StreamlinesCacheMetadata | None = None
    geometry_sha256_recomputed: bool = False

    @property
    def valid(self) -> bool:
        """Return whether the persisted cache matches its full expected contract."""

        return self.classification == "VALID"


@dataclass(frozen=True)
class StreamlinesCacheValidationReceipt:
    """One strongly validated cache result reusable for unchanged resources."""

    inspection: StreamlinesCacheInspection
    resource_fingerprint: tuple[str, str]
    compatibility_identity: tuple[int, str, str]
    source: TemporalVelocitySourceDescriptor | None = None
    dependency_identity: tuple[str, str] = ("", "")
    receipt_source: str = "FRESH"
    cache_location: str = "SESSION"
    validation_executed: bool = True
    geometry_sha256_recomputed: bool = True


def streamlines_cache_resource_fingerprint(
    paths: StreamlinesCachePaths,
) -> tuple[str, str]:
    """Describe cache artifacts for receipt invalidation, never for validity."""

    return (
        _resource_fingerprint(paths.metadata_path),
        _resource_fingerprint(paths.geometry_path),
    )


def _resource_fingerprint(path: Path) -> str:
    """Return a lightweight invalidation key for one cache resource."""

    try:
        stats = path.stat()
    except OSError:
        return f"{path.resolve().as_posix()}|missing"
    return (
        f"{path.resolve().as_posix()}|size={stats.st_size}|"
        f"mtime_ns={stats.st_mtime_ns}"
    )


def inspect_streamlines_cache(
    paths: StreamlinesCachePaths,
    ownership: StreamlinesCacheOwnership,
    *,
    source: TemporalVelocitySourceDescriptor | None = None,
    settings_signature: str | None = None,
) -> StreamlinesCacheInspection:
    """Classify one cache without building, importing, or mutating it.

    Missing artifacts take precedence. A parsed cache must then prove its
    supported schema and declared owner before source/settings/coverage drift
    may be classified as stale.
    """

    if not paths.metadata_path.is_file() or not paths.geometry_path.is_file():
        return StreamlinesCacheInspection(
            ownership=ownership,
            paths=paths,
            classification="MISSING",
            message="Expected cache metadata or geometry artifact is absent.",
        )
    try:
        metadata = load_streamlines_cache_metadata(paths.metadata_path)
    except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError) as error:
        return StreamlinesCacheInspection(
            ownership=ownership,
            paths=paths,
            classification="INCOMPATIBLE",
            message=f"Cache metadata is malformed: {error}",
        )
    incompatible_reason = _cache_incompatibility_reason(metadata, ownership)
    if incompatible_reason:
        return StreamlinesCacheInspection(
            ownership=ownership,
            paths=paths,
            classification="INCOMPATIBLE",
            message=incompatible_reason,
            metadata=metadata,
        )
    if source is None or settings_signature is None:
        raise ValueError("Cache inspection requires an expected source and settings.")
    validation = validate_streamlines_cache(
        metadata,
        source=source,
        settings_signature=settings_signature,
        geometry_path=paths.geometry_path,
    )
    classification = (
        "VALID"
        if validation.valid
        else (
            "STALE"
            if _cache_validation_is_stale(validation.message)
            else "INCOMPATIBLE"
        )
    )
    return StreamlinesCacheInspection(
        ownership=ownership,
        paths=paths,
        classification=classification,
        message=validation.message,
        metadata=metadata,
        geometry_sha256_recomputed=validation.geometry_sha256_recomputed,
    )


def _cache_incompatibility_reason(
    metadata: StreamlinesCacheMetadata,
    ownership: StreamlinesCacheOwnership,
) -> str | None:
    """Return structural/ownership failures before evaluating stale provenance."""

    if metadata.schema_version != CACHE_SCHEMA_VERSION:
        return "Cache schema version is unsupported."
    if not metadata.valid:
        return "Cache metadata is not marked VALID."
    if metadata.workload != ownership.workload:
        return "Cache workload ownership differs from the expected workload."
    if metadata.dataset_identity != ownership.dataset_identity:
        return "Cache dataset ownership differs from the expected dataset."
    if metadata.profile_id != ownership.profile_id:
        return "Cache profile ownership differs from the expected profile."
    if metadata.settings is None:
        return "Cache canonical settings provenance is unavailable."
    if (
        cache_settings_payload_signature(metadata.settings)
        != metadata.settings_signature
    ):
        return "Cache settings payload does not match its signature."
    return None


def _cache_validation_is_stale(message: str) -> bool:
    """Keep mutable source/settings/coverage drift distinct from bad structure."""

    return message.startswith(
        (
            "Cache source manifest is stale.",
            "Cache settings or seed are stale.",
            "Cache state count is incomplete.",
            "Cache sample timing is stale.",
            "Cache time-code rate is stale.",
            "Cache geometry file is stale.",
            "Cache states must have contiguous manifest indices.",
            "Cache state VTI does not match the manifest.",
            "Cache state VTI identity does not match the manifest.",
            "Cache state time code does not match the manifest.",
            "Cache state source time does not match the manifest.",
        )
    )
