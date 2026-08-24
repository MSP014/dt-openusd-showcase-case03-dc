# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""Dependency-free logical airflow phase and exact real-sample resolution."""

from __future__ import annotations

import math
from bisect import bisect_right
from dataclasses import dataclass
from pathlib import Path

from digital_twin_runtime_suite.app.airflow_dataset import AirflowDataset


@dataclass(frozen=True)
class TemporalSourceSample:
    """One exact manifest source identity available to every airflow consumer."""

    ordinal: int
    total: int
    sample_index: int
    source_vti: Path
    source_time_seconds: float
    time_code: float


@dataclass(frozen=True)
class TemporalSampleResolution:
    """The latest real source sample at or before one normalized loop phase."""

    phase_seconds: float
    normalized_phase_seconds: float
    loop_duration_seconds: float
    sample: TemporalSourceSample
    decision: str

    @property
    def is_no_op(self) -> bool:
        """Return whether the active real sample already satisfies this phase."""

        return self.decision == "NO_OP"


def temporal_samples_from_airflow_dataset(
    dataset: AirflowDataset,
    *,
    time_codes_per_second: float = 1.0,
) -> tuple[TemporalSourceSample, ...]:
    """Return every real manifest sample without importing, averaging, or synthesis."""

    if not math.isfinite(time_codes_per_second) or time_codes_per_second <= 0.0:
        raise ValueError("Airflow time codes per second must be positive.")
    paths = dataset.velocity_vti_sequence_paths
    if len(paths) != dataset.manifest.sample_count:
        raise ValueError("Resolved airflow dataset sample count is inconsistent.")
    interval = dataset.sample_interval_seconds
    return tuple(
        TemporalSourceSample(
            ordinal=index + 1,
            total=len(paths),
            sample_index=index,
            source_vti=path,
            source_time_seconds=index * interval,
            time_code=index * interval * time_codes_per_second,
        )
        for index, path in enumerate(paths)
    )


def normalize_airflow_phase(
    phase_seconds: float,
    *,
    loop_duration_seconds: float,
) -> float:
    """Normalize a finite logical phase while preserving the exact loop wrap."""

    if not math.isfinite(phase_seconds):
        raise ValueError("Temporal phase must be a finite number of seconds.")
    if not math.isfinite(loop_duration_seconds) or loop_duration_seconds <= 0.0:
        raise ValueError("Temporal loop duration must be positive.")
    normalized = phase_seconds % loop_duration_seconds
    if math.isclose(normalized, loop_duration_seconds, abs_tol=1e-9):
        return 0.0
    return normalized


def resolve_manifest_sample(
    samples: tuple[TemporalSourceSample, ...],
    *,
    sample_interval_seconds: float,
    phase_seconds: float,
    active_sample_index: int | None = None,
) -> TemporalSampleResolution:
    """Resolve latest-real-sample selection with explicit NO_OP semantics."""

    if not samples:
        raise ValueError("Temporal manifest requires at least one real sample.")
    if not math.isfinite(sample_interval_seconds) or sample_interval_seconds <= 0.0:
        raise ValueError("Temporal manifest sample interval must be positive.")
    loop_duration_seconds = len(samples) * sample_interval_seconds
    normalized_phase_seconds = normalize_airflow_phase(
        phase_seconds,
        loop_duration_seconds=loop_duration_seconds,
    )
    source_times = tuple(sample.source_time_seconds for sample in samples)
    if source_times[0] != 0.0:
        raise ValueError("Temporal manifest must include a sample at phase zero.")
    if any(later <= earlier for earlier, later in zip(source_times, source_times[1:])):
        raise ValueError("Temporal manifest source times must be strictly increasing.")
    selected_index = bisect_right(source_times, normalized_phase_seconds) - 1
    if selected_index < 0:
        raise ValueError("Temporal manifest must include a sample at phase zero.")
    sample = samples[selected_index]
    return TemporalSampleResolution(
        phase_seconds=phase_seconds,
        normalized_phase_seconds=normalized_phase_seconds,
        loop_duration_seconds=loop_duration_seconds,
        sample=sample,
        decision="NO_OP" if sample.sample_index == active_sample_index else "SELECT",
    )
