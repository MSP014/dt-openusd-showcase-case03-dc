"""Plain manifest-backed temporal source contracts for Streamlines.

The Kit-facing runtime owns VTI import, USD time-sample authoring, and CAE
execution. This module deliberately contains only deterministic source
selection rules, so the temporal behaviour can be tested without Kit.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from dataclasses import dataclass
from pathlib import Path

from digital_twin_runtime_suite.app.flow.static_source import (
    StaticVelocitySourceDescriptor,
)


@dataclass(frozen=True)
class TemporalVelocitySourceDescriptor:
    """One logical ``vel`` source with manifest-derived USD time samples.

    ``static_descriptor`` records the accepted spatial import of sample zero.
    Every later source change is a time selection on its same imported field;
    it is never a new VTI import contract.
    """

    static_descriptor: StaticVelocitySourceDescriptor
    velocity_paths: tuple[Path, ...]
    sample_time_codes: tuple[float, ...]
    time_codes_per_second: float
    sample_interval_seconds: float

    @property
    def workload(self) -> str:
        """Return the semantic workload that selected this manifest."""

        return self.static_descriptor.workload

    @property
    def dataset_identity(self) -> str:
        """Return the manifest dataset identity without exposing Kit state."""

        return self.static_descriptor.dataset_identity

    @property
    def sample_count(self) -> int:
        """Return the manifest-derived number of real VTI samples."""

        return len(self.velocity_paths)

    @property
    def source_cadence_hz(self) -> float:
        """Return cadence computed from the manifest interval."""

        return 1.0 / self.sample_interval_seconds


@dataclass(frozen=True)
class TemporalSourceSample:
    """One exact manifest source selection for cache generation or playback."""

    ordinal: int
    total: int
    sample_index: int
    source_vti: Path
    source_time_seconds: float
    time_code: float


@dataclass(frozen=True)
class TemporalSampleResolution:
    """Exact manifest sample chosen for one looping presentation phase."""

    phase_seconds: float
    normalized_phase_seconds: float
    loop_duration_seconds: float
    sample: TemporalSourceSample
    decision: str

    @property
    def is_no_op(self) -> bool:
        """Return whether the active sample already matches this resolution."""

        return self.decision == "NO_OP"


def manifest_samples(
    source: TemporalVelocitySourceDescriptor,
) -> tuple[TemporalSourceSample, ...]:
    """Return exact source identities in manifest order without Kit access."""

    _validate_temporal_source(source)
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


def resolve_temporal_source_sample(
    source: TemporalVelocitySourceDescriptor,
    phase_seconds: float,
    *,
    active_sample_index: int | None = None,
) -> TemporalSampleResolution:
    """Resolve the latest real manifest sample at or before a loop phase.

    The resolver never interpolates, averages, or invents source states.  A
    repeated resolution of the active manifest identity is explicitly a NO_OP.
    """

    return resolve_manifest_sample(
        manifest_samples(source),
        sample_interval_seconds=source.sample_interval_seconds,
        phase_seconds=phase_seconds,
        active_sample_index=active_sample_index,
    )


def resolve_manifest_sample(
    samples: tuple[TemporalSourceSample, ...],
    *,
    sample_interval_seconds: float,
    phase_seconds: float,
    active_sample_index: int | None = None,
) -> TemporalSampleResolution:
    """Resolve exact cached or source manifest identities at a loop phase."""

    if not samples:
        raise ValueError("Temporal manifest requires at least one real sample.")
    if not math.isfinite(sample_interval_seconds) or sample_interval_seconds <= 0.0:
        raise ValueError("Temporal manifest sample interval must be positive.")
    if not math.isfinite(phase_seconds):
        raise ValueError("Temporal phase must be a finite number of seconds.")

    loop_duration_seconds = len(samples) * sample_interval_seconds
    normalized_phase_seconds = phase_seconds % loop_duration_seconds
    if math.isclose(
        normalized_phase_seconds,
        loop_duration_seconds,
        rel_tol=0.0,
        abs_tol=1e-9,
    ):
        normalized_phase_seconds = 0.0
    source_times = tuple(sample.source_time_seconds for sample in samples)
    if source_times[0] != 0.0:
        raise ValueError("Temporal manifest must include a sample at phase zero.")
    if any(later <= earlier for earlier, later in zip(source_times, source_times[1:])):
        raise ValueError("Temporal manifest source times must be strictly increasing.")
    selected_index = bisect_right(source_times, normalized_phase_seconds) - 1
    if selected_index < 0:
        raise ValueError("Temporal manifest must include a sample at phase zero.")
    sample = samples[selected_index]
    decision = "NO_OP" if sample.sample_index == active_sample_index else "SELECT"
    return TemporalSampleResolution(
        phase_seconds=phase_seconds,
        normalized_phase_seconds=normalized_phase_seconds,
        loop_duration_seconds=loop_duration_seconds,
        sample=sample,
        decision=decision,
    )


def _validate_temporal_source(source: TemporalVelocitySourceDescriptor) -> None:
    """Reject temporal descriptors that cannot represent exact manifest time."""

    if source.sample_count == 0:
        raise ValueError("Temporal source requires at least one manifest sample.")
    if source.sample_count != len(source.sample_time_codes):
        raise ValueError("Temporal source paths and time codes must have equal length.")
    if (
        not math.isfinite(source.time_codes_per_second)
        or source.time_codes_per_second <= 0
    ):
        raise ValueError("Temporal source time codes per second must be positive.")
    if (
        not math.isfinite(source.sample_interval_seconds)
        or source.sample_interval_seconds <= 0
    ):
        raise ValueError("Temporal source sample interval must be positive.")
    source_times = tuple(
        time_code / source.time_codes_per_second
        for time_code in source.sample_time_codes
    )
    if source_times[0] != 0.0:
        raise ValueError("Temporal manifest must start at source time zero.")
    if any(later <= earlier for earlier, later in zip(source_times, source_times[1:])):
        raise ValueError("Temporal manifest source times must be strictly increasing.")
