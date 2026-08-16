"""Plain Package E contracts for one manifest-backed Streamlines time probe.

The Kit-facing runtime owns VTI import, USD time-sample authoring, and CAE
execution.  This module deliberately contains only deterministic selection and
comparison rules, so the temporal behaviour can be tested without Kit.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from digital_twin_runtime_suite.app.flow.static_source import (
    StaticVelocitySourceDescriptor,
)

TEMPORAL_PROBE_OPERATOR_PATH = "/DTRS_KitCAE/Streamlines/TemporalVelocityProbe"
TEMPORAL_PROBE_RUNTIME_PREVIEW_PATH = (
    "/DTRS_KitCAE/Streamlines/TemporalVelocityRuntimePreview"
)
TEMPORAL_PROBE_SEED_PATH = "/DTRS_KitCAE/StreamlineSeeds/TemporalProbeSphere"


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
class TemporalProbeSample:
    """One exact manifest source selection within the guided probe."""

    ordinal: int
    total: int
    sample_index: int
    source_vti: Path
    source_time_seconds: float
    time_code: float


@dataclass(frozen=True)
class StreamlinesGeometrySignature:
    """Small UsdRT signature used to detect stale temporal output."""

    curve_count: int
    point_count: int
    bounds: tuple[tuple[float, float, float], tuple[float, float, float]] | None
    point_head: tuple[tuple[float, float, float], ...]
    point_tail: tuple[tuple[float, float, float], ...]


def build_temporal_probe_indices(sample_count: int) -> tuple[int, ...]:
    """Choose deterministic early, quarter, half, final, and loop samples.

    Coincident indices are removed for short manifest sequences.  The final
    return to index zero is intentionally retained even for a one-sample
    dataset because it is the explicit loop-boundary check.
    """

    if sample_count <= 0:
        raise ValueError("Temporal probe requires at least one manifest sample.")
    candidates = (
        0,
        1,
        2,
        round((sample_count - 1) * 0.25),
        round((sample_count - 1) * 0.5),
        sample_count - 1,
    )
    unique = []
    for index in candidates:
        if 0 <= index < sample_count and index not in unique:
            unique.append(index)
    return tuple((*unique, 0))


def build_temporal_probe_samples(
    source: TemporalVelocitySourceDescriptor,
) -> tuple[TemporalProbeSample, ...]:
    """Resolve the guided probe entirely from the manifest temporal contract."""

    if source.time_codes_per_second <= 0.0:
        raise ValueError("Temporal probe timeCodesPerSecond must be positive.")
    if source.sample_interval_seconds <= 0.0:
        raise ValueError("Temporal probe sample interval must be positive.")
    if len(source.velocity_paths) != len(source.sample_time_codes):
        raise ValueError("Temporal source paths and time codes must have equal length.")

    indices = build_temporal_probe_indices(source.sample_count)
    total = len(indices)
    return tuple(
        TemporalProbeSample(
            ordinal=ordinal,
            total=total,
            sample_index=index,
            source_vti=source.velocity_paths[index],
            source_time_seconds=(
                source.sample_time_codes[index] / source.time_codes_per_second
            ),
            time_code=source.sample_time_codes[index],
        )
        for ordinal, index in enumerate(indices, start=1)
    )


def geometry_signature_from_evidence(evidence) -> StreamlinesGeometrySignature:
    """Capture bounded UsdRT facts without retaining a Kit/Fabric reference."""

    return StreamlinesGeometrySignature(
        curve_count=int(evidence.runtime_curve_count),
        point_count=int(evidence.runtime_point_count),
        bounds=evidence.runtime_curve_bounds,
        point_head=tuple(evidence.point_head),
        point_tail=tuple(evidence.point_tail),
    )


def geometry_signatures_match(
    first: StreamlinesGeometrySignature,
    second: StreamlinesGeometrySignature,
    *,
    tolerance: float = 1e-6,
) -> bool:
    """Compare compact temporal geometry evidence with float tolerance."""

    if (
        first.curve_count != second.curve_count
        or first.point_count != second.point_count
        or (first.bounds is None) != (second.bounds is None)
    ):
        return False
    return (
        _vectors_match(first.bounds, second.bounds, tolerance)
        and _vectors_match(
            first.point_head,
            second.point_head,
            tolerance,
        )
        and _vectors_match(first.point_tail, second.point_tail, tolerance)
    )


def _vectors_match(first, second, tolerance: float) -> bool:
    if first is None or second is None:
        return first is second
    try:
        return all(
            abs(float(left) - float(right)) <= tolerance
            for left_point, right_point in zip(first, second)
            for left, right in zip(left_point, right_point)
        ) and len(first) == len(second)
    except (TypeError, ValueError):
        return False
