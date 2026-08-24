# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""Plain manifest-backed temporal source contracts for Streamlines.

The Kit-facing runtime owns VTI import, USD time-sample authoring, and CAE
execution. This module deliberately contains only deterministic source
selection rules, so the temporal behaviour can be tested without Kit.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from digital_twin_runtime_suite.app.airflow_dataset import AirflowDataset
from digital_twin_runtime_suite.app.airflow_state.temporal import (
    TemporalSampleResolution,
    TemporalSourceSample,
    resolve_manifest_sample,
)
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
    def loop_duration_seconds(self) -> float:
        """Return the exact logical loop duration declared by the manifest."""

        return self.sample_count * self.sample_interval_seconds

    @property
    def source_cadence_hz(self) -> float:
        """Return cadence computed from the manifest interval."""

        return 1.0 / self.sample_interval_seconds


def temporal_source_from_airflow_dataset(
    airflow_dataset: AirflowDataset,
    *,
    workload: str,
    static_descriptor: StaticVelocitySourceDescriptor,
    time_codes_per_second: float,
) -> TemporalVelocitySourceDescriptor:
    """Build exact Streamlines temporal truth from one resolved dataset.

    This plain contract deliberately preserves every real VTI identity and the
    registry's manifest clock. Presentation cadence has no input here.
    """

    manifest = airflow_dataset.manifest
    dataset_identity = f"{manifest.scope}/{manifest.state}"
    if static_descriptor.workload != workload:
        raise ValueError("Static Streamlines source workload changed during setup.")
    if static_descriptor.dataset_identity != dataset_identity:
        raise ValueError(
            "Static Streamlines source dataset identity changed during setup."
        )
    velocity_paths = airflow_dataset.velocity_vti_sequence_paths
    if len(velocity_paths) != manifest.sample_count:
        raise ValueError("Resolved airflow dataset sample count is inconsistent.")
    if (
        not velocity_paths
        or static_descriptor.vti_path.resolve() != velocity_paths[0].resolve()
    ):
        raise ValueError("Static Streamlines source must be manifest sample zero.")
    if not math.isfinite(time_codes_per_second) or time_codes_per_second <= 0.0:
        raise ValueError("Temporal source time codes per second must be positive.")
    time_codes = tuple(
        index * time_codes_per_second * airflow_dataset.sample_interval_seconds
        for index in range(manifest.sample_count)
    )
    source = TemporalVelocitySourceDescriptor(
        static_descriptor=static_descriptor,
        velocity_paths=velocity_paths,
        sample_time_codes=time_codes,
        time_codes_per_second=time_codes_per_second,
        sample_interval_seconds=airflow_dataset.sample_interval_seconds,
    )
    _validate_temporal_source(source)
    if not math.isclose(
        source.loop_duration_seconds,
        airflow_dataset.loop_duration_seconds,
        rel_tol=0.0,
        abs_tol=1e-9,
    ):
        raise ValueError("Resolved airflow dataset loop duration is inconsistent.")
    return source


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
    for index, time_code in enumerate(source.sample_time_codes):
        expected_time_code = (
            index * source.sample_interval_seconds * source.time_codes_per_second
        )
        if not math.isclose(
            time_code,
            expected_time_code,
            rel_tol=0.0,
            abs_tol=1e-9,
        ):
            raise ValueError(
                "Temporal manifest time codes must match its sample interval."
            )
