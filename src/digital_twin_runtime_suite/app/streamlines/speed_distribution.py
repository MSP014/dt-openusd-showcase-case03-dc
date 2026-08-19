"""Memory-bounded statistics over persisted raw Streamlines speed samples."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

from digital_twin_runtime_suite.app.streamlines.cache import (
    CACHE_PLAYBACK_CURVES_PATH,
    StreamlinesCacheMetadata,
)
from digital_twin_runtime_suite.app.streamlines.constant_topology import (
    SOURCE_CURVE_VERTEX_COUNTS_ATTRIBUTE,
    authentic_values_from_padded_curves,
    renderer_topology_for_profile,
)
from digital_twin_runtime_suite.app.streamlines.speed import (
    SPEED_PRIMVAR_ATTRIBUTE,
    validate_persisted_speed_magnitudes,
)


@dataclass(frozen=True)
class SpeedDistribution:
    """Bounded-sample percentile evidence plus exact range/count."""

    value_count: int
    minimum: float
    p01: float
    p05: float
    p50: float
    p95: float
    p99: float
    maximum: float


@dataclass(frozen=True)
class SpeedScaleCoverage:
    """Exact fixed-scale coverage percentages for one cache."""

    below_percent: float
    inside_percent: float
    above_percent: float


class SpeedDistributionAccumulator:
    """Keep exact extrema/count and a deterministic bounded percentile sample."""

    def __init__(self, max_samples: int = 65536) -> None:
        if max_samples <= 0:
            raise ValueError("Speed distribution sample budget must be positive.")
        self._max_samples = max_samples
        self._sample: list[float] = []
        self._count = 0
        self._minimum = math.inf
        self._maximum = -math.inf

    def add(self, values: Iterable[float]) -> None:
        """Consume a chunk without retaining the complete cache payload."""

        for raw in values:
            value = float(raw)
            if not math.isfinite(value) or value < 0.0:
                raise ValueError("Persisted Streamlines speed is invalid.")
            self._count += 1
            self._minimum = min(self._minimum, value)
            self._maximum = max(self._maximum, value)
            if len(self._sample) < self._max_samples:
                self._sample.append(value)
            else:
                # Deterministic reservoir replacement without retaining the
                # complete temporal payload. The masked LCG value avoids the
                # degenerate ``count * constant % count == 0`` case.
                slot = ((self._count * 1103515245 + 12345) & 0x7FFFFFFF) % self._count
                if slot < self._max_samples:
                    self._sample[slot] = value

    def finish(self) -> SpeedDistribution:
        """Return deterministic percentile evidence after at least one value."""

        if not self._count:
            raise ValueError("Speed distribution contains no values.")
        ordered = sorted(self._sample)
        return SpeedDistribution(
            value_count=self._count,
            minimum=self._minimum,
            p01=_percentile(ordered, 0.01),
            p05=_percentile(ordered, 0.05),
            p50=_percentile(ordered, 0.50),
            p95=_percentile(ordered, 0.95),
            p99=_percentile(ordered, 0.99),
            maximum=self._maximum,
        )


def fixed_scale_coverage(
    chunks: Iterable[Iterable[float]],
    *,
    minimum: float,
    maximum: float,
) -> SpeedScaleCoverage:
    """Count exact coverage without retaining cache values."""

    if not math.isfinite(minimum) or not math.isfinite(maximum) or maximum <= minimum:
        raise ValueError("Speed coverage range is invalid.")
    below = inside = above = 0
    for values in chunks:
        for raw in values:
            value = float(raw)
            if not math.isfinite(value) or value < 0.0:
                raise ValueError("Persisted Streamlines speed is invalid.")
            if value < minimum:
                below += 1
            elif value > maximum:
                above += 1
            else:
                inside += 1
    total = below + inside + above
    if not total:
        raise ValueError("Speed coverage contains no values.")
    return SpeedScaleCoverage(
        below_percent=100.0 * below / total,
        inside_percent=100.0 * inside / total,
        above_percent=100.0 * above / total,
    )


def proposed_speed_max(
    distributions: Iterable[SpeedDistribution],
) -> float:
    """Use the largest Volume Coverage p99 as one fixed upper bound."""

    values = tuple(item.p99 for item in distributions)
    if not values:
        raise ValueError("At least one Volume Coverage distribution is required.")
    return max(values)


def persisted_speed_chunks(
    geometry_path,
    metadata: StreamlinesCacheMetadata,
):
    """Yield one strongly validated USD temporal sample at a time."""

    from pxr import Usd

    stage = Usd.Stage.Open(str(geometry_path))
    if not stage:
        raise ValueError("Persisted Streamlines geometry cannot be opened.")
    curves = stage.GetPrimAtPath(CACHE_PLAYBACK_CURVES_PATH)
    if not curves or not curves.IsValid():
        raise ValueError("Persisted Streamlines curves are missing.")
    attribute = curves.GetAttribute(SPEED_PRIMVAR_ATTRIBUTE)
    if not attribute or not attribute.IsValid():
        raise ValueError("Persisted Streamlines raw speed primvar is missing.")
    actual_times = tuple(float(value) for value in attribute.GetTimeSamples())
    expected_times = tuple(state.time_code for state in metadata.states)
    if actual_times != expected_times:
        raise ValueError("Persisted speed time samples do not match metadata.")
    source_counts_attribute = curves.GetAttribute(SOURCE_CURVE_VERTEX_COUNTS_ATTRIBUTE)
    if not source_counts_attribute or not source_counts_attribute.IsValid():
        raise ValueError("Persisted source curve topology is missing.")
    source_count_times = tuple(
        float(value) for value in source_counts_attribute.GetTimeSamples()
    )
    if source_count_times != expected_times:
        raise ValueError("Persisted source topology time samples do not match.")
    topology = renderer_topology_for_profile(metadata.profile_id)
    for state in metadata.states:
        time_code = Usd.TimeCode(state.time_code)
        values = attribute.Get(time_code)
        padded = validate_persisted_speed_magnitudes(
            () if values is None else values,
            expected_point_count=state.point_count,
        )
        source_counts = tuple(source_counts_attribute.Get(time_code) or ())
        authentic = authentic_values_from_padded_curves(
            padded,
            source_counts,
            vertices_per_curve=topology.vertices_per_curve,
        )
        if len(authentic) != state.source_point_count:
            raise ValueError("Authentic speed count differs from cache metadata.")
        yield authentic


def persisted_speed_distribution(
    geometry_path,
    metadata: StreamlinesCacheMetadata,
    *,
    max_samples: int = 65536,
) -> SpeedDistribution:
    """Calculate bounded distribution evidence from one final cache."""

    accumulator = SpeedDistributionAccumulator(max_samples=max_samples)
    for chunk in persisted_speed_chunks(geometry_path, metadata):
        accumulator.add(chunk)
    return accumulator.finish()


def validate_persisted_speed_cache(
    geometry_path,
    metadata: StreamlinesCacheMetadata,
) -> int:
    """Strongly validate every raw-speed state without retaining its payload."""

    value_count = 0
    for chunk in persisted_speed_chunks(geometry_path, metadata):
        value_count += len(chunk)
    if value_count <= 0:
        raise ValueError("Persisted Streamlines cache contains no raw speed values.")
    return value_count


def persisted_speed_coverage(
    geometry_path,
    metadata: StreamlinesCacheMetadata,
    *,
    minimum: float,
    maximum: float,
) -> SpeedScaleCoverage:
    return fixed_scale_coverage(
        persisted_speed_chunks(geometry_path, metadata),
        minimum=minimum,
        maximum=maximum,
    )


def _percentile(values: list[float], fraction: float) -> float:
    if len(values) == 1:
        return values[0]
    position = fraction * (len(values) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    weight = position - lower
    return values[lower] + (values[upper] - values[lower]) * weight
