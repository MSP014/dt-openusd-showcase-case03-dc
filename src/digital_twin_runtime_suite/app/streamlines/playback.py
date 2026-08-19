"""Plain cached-state contracts for exact Streamlines presentation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from digital_twin_runtime_suite.app.airflow_state.temporal import (
    TemporalSampleResolution,
    TemporalSourceSample,
    resolve_manifest_sample,
)
from digital_twin_runtime_suite.app.streamlines.cache import (
    StreamlinesCacheMetadata,
    source_signature_from_temporal_source,
)
from digital_twin_runtime_suite.app.streamlines.temporal import (
    TemporalVelocitySourceDescriptor,
)


@dataclass(frozen=True)
class CachedPlaybackContract:
    """Validated real cache states available for presentation, never synthesis."""

    workload: str
    dataset_identity: str
    sample_interval_seconds: float
    samples: tuple[TemporalSourceSample, ...]
    profile_id: str = "volume_coverage"
    cache_identity: str = ""

    @property
    def sample_count(self) -> int:
        """Return the exact number of persisted real cache states."""

        return len(self.samples)

    @property
    def loop_duration_seconds(self) -> float:
        """Return the manifest-derived duration used for normalized playback."""

        return self.sample_count * self.sample_interval_seconds


def cached_playback_contract_from_validated_cache(
    metadata: StreamlinesCacheMetadata,
    source: TemporalVelocitySourceDescriptor,
) -> CachedPlaybackContract:
    """Bind a validated cache receipt to the same authoritative source contract.

    This is a plain identity guard, not an import path. It rejects an unloaded,
    partial, stale, or differently-bound cache before Kit geometry switching.
    """

    if not metadata.valid:
        raise ValueError("Cached playback requires a valid persisted cache.")
    if metadata.workload != source.workload:
        raise ValueError("Cached playback workload does not match the source.")
    if metadata.dataset_identity != source.dataset_identity:
        raise ValueError("Cached playback dataset does not match the source.")
    if metadata.sample_count != source.sample_count:
        raise ValueError("Cached playback sample count does not match the source.")
    if metadata.source_signature != source_signature_from_temporal_source(source):
        raise ValueError("Cached playback source signature is stale.")
    if len(metadata.states) != source.sample_count:
        raise ValueError("Cached playback state count does not match the source.")

    samples = []
    for expected, state in zip(_source_samples(source), metadata.states):
        if state.sample_index != expected.sample_index:
            raise ValueError("Cached playback state index does not match the source.")
        if Path(state.source_vti).resolve() != expected.source_vti.resolve():
            raise ValueError("Cached playback VTI identity does not match the source.")
        if state.source_time_seconds != expected.source_time_seconds:
            raise ValueError("Cached playback source time does not match the source.")
        if state.time_code != expected.time_code:
            raise ValueError("Cached playback time code does not match the source.")
        samples.append(expected)
    return CachedPlaybackContract(
        workload=metadata.workload,
        dataset_identity=metadata.dataset_identity,
        sample_interval_seconds=source.sample_interval_seconds,
        samples=tuple(samples),
        profile_id=metadata.profile_id,
        cache_identity=metadata.geometry_sha256,
    )


def resolve_cached_playback_state(
    contract: CachedPlaybackContract,
    phase_seconds: float,
    *,
    active_sample_index: int | None = None,
) -> TemporalSampleResolution:
    """Resolve a current phase directly to one exact persisted cache state."""

    return resolve_manifest_sample(
        contract.samples,
        sample_interval_seconds=contract.sample_interval_seconds,
        phase_seconds=phase_seconds,
        active_sample_index=active_sample_index,
    )


def _source_samples(
    source: TemporalVelocitySourceDescriptor,
) -> tuple[TemporalSourceSample, ...]:
    """Expose real manifest identities without introducing a second resolver."""

    return tuple(
        TemporalSourceSample(
            ordinal=index + 1,
            total=source.sample_count,
            sample_index=index,
            source_vti=source.velocity_paths[index],
            source_time_seconds=(
                source.sample_time_codes[index] / source.time_codes_per_second
            ),
            time_code=source.sample_time_codes[index],
        )
        for index in range(source.sample_count)
    )
