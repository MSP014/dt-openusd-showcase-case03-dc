"""Memory-bounded statistics over persisted raw Streamlines speed samples."""

from __future__ import annotations

import math
from bisect import bisect_right
from dataclasses import dataclass
from statistics import median
from typing import Iterable

from digital_twin_runtime_suite.app.streamlines.cache import (
    CACHE_PLAYBACK_CURVES_PATH,
    SPEED_EVIDENCE_QUANTILE_COUNT,
    StreamlinesCacheMetadata,
    StreamlinesCacheSpeedEvidence,
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


@dataclass(frozen=True)
class SpeedScaleProposalEvidence:
    """Manifest-selected Critical/Volume p99 evidence for one shared scale."""

    state_indices: tuple[int, ...]
    state_p99_values: tuple[float, ...]
    candidate_maximum: float


@dataclass(frozen=True)
class PersistedSpeedDistributionEvidence:
    """One bounded persisted-cache audit over selected real manifest states."""

    distribution: SpeedDistribution
    state_distributions: tuple[SpeedDistribution, ...]
    sampled_values: tuple[float, ...]


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

    @property
    def sampled_values(self) -> tuple[float, ...]:
        """Expose only the bounded deterministic percentile sample."""

        return tuple(self._sample)

    def quantile_values(
        self,
        *,
        count: int = SPEED_EVIDENCE_QUANTILE_COUNT,
    ) -> tuple[float, ...]:
        """Return a fixed quantile sketch for compact future clipping audits."""

        if count < 2:
            raise ValueError("Speed-evidence quantile count must be at least two.")
        if not self._sample:
            raise ValueError("Speed distribution contains no values.")
        ordered = sorted(self._sample)
        return tuple(
            _percentile(ordered, index / (count - 1)) for index in range(count)
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


def distributed_manifest_state_indices(
    metadata: StreamlinesCacheMetadata,
    *,
    count: int = 5,
) -> tuple[int, ...]:
    """Select evenly distributed real manifest states without cadence assumptions."""

    sample_count = metadata.sample_count
    if len(metadata.states) != sample_count:
        raise ValueError("Cache metadata state count is inconsistent.")
    return distributed_state_indices(sample_count, count=count)


def distributed_state_indices(
    sample_count: int,
    *,
    count: int = 5,
) -> tuple[int, ...]:
    """Select evenly distributed state indexes without a metadata dependency."""

    if count <= 0:
        raise ValueError("Distributed state count must be positive.")
    if sample_count < count:
        raise ValueError(
            "Persisted cache has too few manifest states for speed-scale analysis."
        )
    return tuple(
        round(index * (sample_count - 1) / (count - 1)) for index in range(count)
    )


def speed_scale_candidate_from_critical_volume(
    state_distributions: Iterable[SpeedDistribution],
    *,
    state_indices: Iterable[int],
) -> SpeedScaleProposalEvidence:
    """Derive one fixed maximum from five Critical/Volume state p99 values."""

    distributions = tuple(state_distributions)
    indices = tuple(state_indices)
    if len(distributions) != len(indices) or not distributions:
        raise ValueError("Critical/Volume speed-scale evidence is incomplete.")
    p99_values = tuple(item.p99 for item in distributions)
    candidate = float(median(p99_values))
    if not math.isfinite(candidate) or candidate <= 0.0:
        raise ValueError("Critical/Volume speed-scale candidate is invalid.")
    return SpeedScaleProposalEvidence(indices, p99_values, candidate)


def build_streamlines_cache_speed_evidence(
    accumulator: SpeedDistributionAccumulator,
    *,
    critical_state_indices: Iterable[int] = (),
    critical_state_accumulators: Iterable[SpeedDistributionAccumulator] = (),
) -> StreamlinesCacheSpeedEvidence:
    """Freeze Volume build evidence from raw speeds already held by the builder."""

    distribution = accumulator.finish()
    state_accumulators = tuple(critical_state_accumulators)
    state_indices = tuple(critical_state_indices)
    if len(state_indices) != len(state_accumulators):
        raise ValueError("Critical speed-state accumulators are incomplete.")
    return StreamlinesCacheSpeedEvidence(
        value_count=distribution.value_count,
        minimum=distribution.minimum,
        p01=distribution.p01,
        p05=distribution.p05,
        p50=distribution.p50,
        p95=distribution.p95,
        p99=distribution.p99,
        maximum=distribution.maximum,
        quantile_values=accumulator.quantile_values(),
        critical_state_indices=state_indices,
        critical_state_p99_values=tuple(
            state_accumulator.finish().p99 for state_accumulator in state_accumulators
        ),
    )


def speed_distribution_from_cache_evidence(
    evidence: StreamlinesCacheSpeedEvidence,
) -> SpeedDistribution:
    """Adapt compact persisted evidence to the ordinary audit presentation."""

    return SpeedDistribution(
        value_count=evidence.value_count,
        minimum=evidence.minimum,
        p01=evidence.p01,
        p05=evidence.p05,
        p50=evidence.p50,
        p95=evidence.p95,
        p99=evidence.p99,
        maximum=evidence.maximum,
    )


def volume_scale_from_cache_evidence(
    evidences: Iterable[StreamlinesCacheSpeedEvidence],
) -> tuple[float, float]:
    """Choose shared physical p05/p95 limits from Volume-only quantile sketches."""

    values = tuple(evidences)
    if not values:
        raise ValueError("At least one Volume speed evidence record is required.")
    minimum = _pooled_evidence_quantile(values, 0.05)
    maximum = _pooled_evidence_quantile(values, 0.95)
    if not math.isfinite(minimum) or not math.isfinite(maximum) or maximum <= minimum:
        raise ValueError("Volume speed p05/p95 scale is invalid.")
    return minimum, maximum


def fixed_scale_coverage_from_cache_evidence(
    evidence: StreamlinesCacheSpeedEvidence,
    *,
    minimum: float,
    maximum: float,
) -> SpeedScaleCoverage:
    """Estimate fixed-scale clipping from the persisted fixed quantile sketch."""

    if maximum <= minimum:
        raise ValueError("Speed coverage range is invalid.")
    below = _evidence_cdf(evidence.quantile_values, minimum)
    above = 1.0 - _evidence_cdf(evidence.quantile_values, maximum)
    return SpeedScaleCoverage(
        below_percent=100.0 * below,
        inside_percent=100.0 * max(0.0, 1.0 - below - above),
        above_percent=100.0 * above,
    )


def _pooled_evidence_quantile(
    evidences: tuple[StreamlinesCacheSpeedEvidence, ...],
    fraction: float,
) -> float:
    """Invert the value-count-weighted CDF from fixed per-cache sketches."""

    if not 0.0 <= fraction <= 1.0:
        raise ValueError("Pooled speed quantile must be between zero and one.")
    lower = min(evidence.quantile_values[0] for evidence in evidences)
    upper = max(evidence.quantile_values[-1] for evidence in evidences)
    total_count = sum(evidence.value_count for evidence in evidences)
    for _ in range(40):
        midpoint = (lower + upper) / 2.0
        cdf = (
            sum(
                evidence.value_count * _evidence_cdf(evidence.quantile_values, midpoint)
                for evidence in evidences
            )
            / total_count
        )
        if cdf < fraction:
            lower = midpoint
        else:
            upper = midpoint
    return (lower + upper) / 2.0


def _evidence_cdf(quantile_values: tuple[float, ...], value: float) -> float:
    """Interpolate one compact fixed-quantile sketch as an approximate CDF."""

    if value <= quantile_values[0]:
        return 0.0
    if value >= quantile_values[-1]:
        return 1.0
    right = bisect_right(quantile_values, value)
    left = right - 1
    left_value = quantile_values[left]
    right_value = quantile_values[right]
    left_fraction = left / (len(quantile_values) - 1)
    if right_value <= left_value:
        return right / (len(quantile_values) - 1)
    local_fraction = (value - left_value) / (right_value - left_value)
    return left_fraction + local_fraction / (len(quantile_values) - 1)


def persisted_speed_chunks(
    geometry_path,
    metadata: StreamlinesCacheMetadata,
):
    """Yield one strongly validated USD temporal sample at a time."""

    for _state_index, values in _persisted_speed_chunks_indexed(
        geometry_path,
        metadata,
    ):
        yield values


def _persisted_speed_chunks_indexed(
    geometry_path,
    metadata: StreamlinesCacheMetadata,
    *,
    state_indices: Iterable[int] | None = None,
):
    """Yield authentic values for selected real states from one opened cache."""

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
    selected = _selected_state_indices(metadata, state_indices)
    for state_index, state in enumerate(metadata.states):
        if state_index not in selected:
            continue
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
        yield state_index, authentic


def persisted_speed_header_available(
    geometry_path,
    metadata: StreamlinesCacheMetadata,
) -> bool:
    """Check the persisted speed temporal contract without reading vertex values."""

    from pxr import Usd

    stage = Usd.Stage.Open(str(geometry_path))
    if not stage:
        return False
    curves = stage.GetPrimAtPath(CACHE_PLAYBACK_CURVES_PATH)
    attribute = curves.GetAttribute(SPEED_PRIMVAR_ATTRIBUTE) if curves else None
    if not attribute or not attribute.IsValid():
        return False
    expected_times = tuple(state.time_code for state in metadata.states)
    return tuple(float(value) for value in attribute.GetTimeSamples()) == expected_times


def persisted_speed_state_distribution(
    geometry_path,
    metadata: StreamlinesCacheMetadata,
    state_index: int,
    *,
    max_samples: int = 65536,
) -> SpeedDistribution:
    """Calculate authentic-vertex statistics for one real manifest state."""

    if not 0 <= state_index < metadata.sample_count:
        raise ValueError("Persisted speed state index is outside the manifest.")
    for index, values in _persisted_speed_chunks_indexed(
        geometry_path,
        metadata,
        state_indices=(state_index,),
    ):
        if index == state_index:
            accumulator = SpeedDistributionAccumulator(max_samples=max_samples)
            accumulator.add(values)
            return accumulator.finish()
    raise ValueError("Persisted speed state is missing from the cache.")


def persisted_speed_distribution_for_states(
    geometry_path,
    metadata: StreamlinesCacheMetadata,
    *,
    state_indices: Iterable[int],
    max_samples: int = 65536,
) -> PersistedSpeedDistributionEvidence:
    """Audit selected real states once, without reopening or rescanning a cache."""

    indices = _selected_state_indices(metadata, state_indices)
    aggregate = SpeedDistributionAccumulator(max_samples=max_samples)
    per_state = {
        index: SpeedDistributionAccumulator(max_samples=max_samples)
        for index in indices
    }
    for index, values in _persisted_speed_chunks_indexed(
        geometry_path,
        metadata,
        state_indices=indices,
    ):
        aggregate.add(values)
        per_state[index].add(values)
    return PersistedSpeedDistributionEvidence(
        distribution=aggregate.finish(),
        state_distributions=tuple(per_state[index].finish() for index in indices),
        sampled_values=aggregate.sampled_values,
    )


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


def _selected_state_indices(
    metadata: StreamlinesCacheMetadata,
    state_indices: Iterable[int] | None,
) -> tuple[int, ...]:
    """Validate optional manifest-state selection while retaining source order."""

    if state_indices is None:
        return tuple(range(metadata.sample_count))
    indices = tuple(dict.fromkeys(int(index) for index in state_indices))
    if not indices:
        raise ValueError("At least one manifest state must be selected.")
    if any(index < 0 or index >= metadata.sample_count for index in indices):
        raise ValueError("Persisted speed state index is outside the manifest.")
    return tuple(sorted(indices))
