"""Convert real Streamlines curves into an RTX-safe fixed cache topology."""

from __future__ import annotations

import hashlib
import math
import struct
from dataclasses import dataclass
from typing import Iterable, Sequence, TypeVar

from digital_twin_runtime_suite.app.streamlines.profile import (
    StreamlinesProfileId,
    final_geometry_contract,
)

SOURCE_CURVE_VERTEX_COUNTS_ATTRIBUTE = "dtrs:sourceCurveVertexCounts"
MIN_CUBIC_CURVE_VERTEX_COUNT = 4
Value = TypeVar("Value")


@dataclass(frozen=True)
class StreamlinesRendererTopology:
    """One profile's immutable renderer-facing curve and point budget."""

    profile_id: StreamlinesProfileId
    curve_count: int
    vertices_per_curve: int

    @property
    def point_count(self) -> int:
        return self.curve_count * self.vertices_per_curve

    @property
    def curve_vertex_counts(self) -> tuple[int, ...]:
        return (self.vertices_per_curve,) * self.curve_count


@dataclass(frozen=True)
class PaddedStreamlinesSample:
    """Keep authentic topology beside fixed renderer points and speeds."""

    topology: StreamlinesRendererTopology
    points: tuple[object, ...]
    speeds: tuple[float, ...]
    source_curve_vertex_counts: tuple[int, ...]


@dataclass(frozen=True)
class PersistedConstantTopologyProof:
    """Exact persisted-array counts for one renderer-safe temporal sample."""

    sample_index: int
    time_code: float
    curve_count: int
    point_count: int
    speed_count: int
    source_curve_count: int
    source_point_count: int
    terminal_points_repeated: bool
    terminal_speeds_repeated: bool

    @property
    def passed(self) -> bool:
        return self.terminal_points_repeated and self.terminal_speeds_repeated


@dataclass(frozen=True)
class StreamlinesPointArraySignature:
    """Bounded deterministic evidence for one exact USD points array."""

    point_count: int
    sha256: str
    first_points: tuple[tuple[float, float, float], ...]
    bounds: tuple[tuple[float, float, float], tuple[float, float, float]]


@dataclass(frozen=True)
class PersistedStreamlinesPointProbe:
    """One exact persisted temporal state's renderer-point signature."""

    sample_index: int
    time_code: float
    points: StreamlinesPointArraySignature


def streamlines_point_array_signature(
    points: Sequence[object],
) -> StreamlinesPointArraySignature:
    """Hash canonical float32 positions without retaining a second full array."""

    if not points:
        raise ValueError("Streamlines point signature requires non-empty geometry.")
    digest = hashlib.sha256()
    minimum = [math.inf, math.inf, math.inf]
    maximum = [-math.inf, -math.inf, -math.inf]
    first_points = []
    for index, point in enumerate(points):
        coordinates = tuple(float(value) for value in point)
        if len(coordinates) != 3 or any(
            not math.isfinite(value) for value in coordinates
        ):
            raise ValueError("Streamlines points must contain finite float3 values.")
        digest.update(struct.pack("<fff", *coordinates))
        if index < 3:
            first_points.append(coordinates)
        for axis, value in enumerate(coordinates):
            minimum[axis] = min(minimum[axis], value)
            maximum[axis] = max(maximum[axis], value)
    return StreamlinesPointArraySignature(
        point_count=len(points),
        sha256=digest.hexdigest(),
        first_points=tuple(first_points),
        bounds=(tuple(minimum), tuple(maximum)),
    )


def probe_persisted_streamlines_point_signatures(
    geometry_path,
    metadata,
    *,
    sample_indices: Iterable[int],
) -> tuple[PersistedStreamlinesPointProbe, ...]:
    """Read selected exact point samples from the persisted cache only."""

    from pxr import Usd

    from digital_twin_runtime_suite.app.streamlines.cache import (
        CACHE_PLAYBACK_CURVES_PATH,
    )

    stage = Usd.Stage.Open(str(geometry_path))
    if not stage:
        raise ValueError("Persisted Streamlines geometry cannot be opened.")
    prim = stage.GetPrimAtPath(CACHE_PLAYBACK_CURVES_PATH)
    if not prim or not prim.IsValid():
        raise ValueError("Persisted Streamlines curves are missing.")
    points_attr = prim.GetAttribute("points")
    states = {state.sample_index: state for state in metadata.states}
    probes = []
    for sample_index in tuple(int(value) for value in sample_indices):
        state = states.get(sample_index)
        if state is None:
            raise ValueError("Requested persisted point sample is unavailable.")
        points = tuple(points_attr.Get(Usd.TimeCode(state.time_code)) or ())
        probes.append(
            PersistedStreamlinesPointProbe(
                sample_index=sample_index,
                time_code=state.time_code,
                points=streamlines_point_array_signature(points),
            )
        )
    return tuple(probes)


def renderer_topology_for_profile(
    profile_id: StreamlinesProfileId,
) -> StreamlinesRendererTopology:
    """Derive fixed topology only from the frozen production geometry contract."""

    profile_id = StreamlinesProfileId(profile_id)
    contract = final_geometry_contract(profile_id)
    return StreamlinesRendererTopology(
        profile_id=profile_id,
        curve_count=contract.seed_count * contract.section_count,
        vertices_per_curve=contract.max_steps,
    )


def pad_streamlines_sample_for_renderer(
    *,
    profile_id: StreamlinesProfileId,
    points: Sequence[object],
    curve_vertex_counts: Iterable[int],
    speeds: Sequence[float],
) -> PaddedStreamlinesSample:
    """Repeat only each curve's terminal point and speed to its fixed budget."""

    topology = renderer_topology_for_profile(profile_id)
    source_counts = tuple(int(value) for value in curve_vertex_counts)
    if len(source_counts) != topology.curve_count:
        raise ValueError(
            "Source Streamlines curve count does not match the frozen profile."
        )
    if any(
        count < MIN_CUBIC_CURVE_VERTEX_COUNT or count > topology.vertices_per_curve
        for count in source_counts
    ):
        raise ValueError(
            "Source Streamlines curve vertex count is outside the frozen profile."
        )
    source_point_count = sum(source_counts)
    if len(points) != source_point_count or len(speeds) != source_point_count:
        raise ValueError(
            "Source Streamlines points, speeds, and curve topology are misaligned."
        )

    padded_points = []
    padded_speeds = []
    offset = 0
    for count in source_counts:
        curve_points = tuple(points[offset : offset + count])
        curve_speeds = tuple(float(value) for value in speeds[offset : offset + count])
        offset += count
        padding = topology.vertices_per_curve - count
        padded_points.extend(curve_points)
        padded_points.extend((curve_points[-1],) * padding)
        padded_speeds.extend(curve_speeds)
        padded_speeds.extend((curve_speeds[-1],) * padding)

    if (
        len(padded_points) != topology.point_count
        or len(padded_speeds) != topology.point_count
    ):
        raise RuntimeError("Fixed Streamlines renderer topology is incomplete.")
    return PaddedStreamlinesSample(
        topology=topology,
        points=tuple(padded_points),
        speeds=tuple(padded_speeds),
        source_curve_vertex_counts=source_counts,
    )


def authentic_values_from_padded_curves(
    values: Sequence[Value],
    source_curve_vertex_counts: Iterable[int],
    *,
    vertices_per_curve: int,
) -> tuple[Value, ...]:
    """Return only real values and exclude repeated curve-terminal padding."""

    counts = tuple(int(value) for value in source_curve_vertex_counts)
    if vertices_per_curve <= 0 or any(
        count < MIN_CUBIC_CURVE_VERTEX_COUNT or count > vertices_per_curve
        for count in counts
    ):
        raise ValueError("Source curve topology is invalid for padded values.")
    if len(values) != len(counts) * vertices_per_curve:
        raise ValueError("Padded value count does not match renderer topology.")
    authentic = []
    for curve_index, count in enumerate(counts):
        start = curve_index * vertices_per_curve
        authentic.extend(values[start : start + count])
    return tuple(authentic)


def terminal_padding_is_exact(
    values: Sequence[Value],
    source_curve_vertex_counts: Iterable[int],
    *,
    vertices_per_curve: int,
) -> bool:
    """Prove padding exactly repeats each curve's final authentic value."""

    counts = tuple(int(value) for value in source_curve_vertex_counts)
    if (
        vertices_per_curve <= 0
        or any(
            count < MIN_CUBIC_CURVE_VERTEX_COUNT or count > vertices_per_curve
            for count in counts
        )
        or len(values) != len(counts) * vertices_per_curve
    ):
        return False
    for curve_index, count in enumerate(counts):
        start = curve_index * vertices_per_curve
        terminal = values[start + count - 1]
        if any(
            value != terminal
            for value in values[start + count : start + vertices_per_curve]
        ):
            return False
    return True


def validate_persisted_constant_topology_cache(
    geometry_path,
    metadata,
    *,
    sample_indices: Iterable[int] | None = None,
) -> tuple[PersistedConstantTopologyProof, ...]:
    """Strongly verify constant topology and truthful per-state source counts."""

    from pxr import Usd

    from digital_twin_runtime_suite.app.streamlines.cache import (
        CACHE_PLAYBACK_CURVES_PATH,
        topology_signature,
    )
    from digital_twin_runtime_suite.app.streamlines.speed import (
        SPEED_PRIMVAR_ATTRIBUTE,
    )

    stage = Usd.Stage.Open(str(geometry_path))
    if not stage:
        raise ValueError("Persisted Streamlines geometry cannot be opened.")
    curves = stage.GetPrimAtPath(CACHE_PLAYBACK_CURVES_PATH)
    if not curves or not curves.IsValid():
        raise ValueError("Persisted Streamlines curves are missing.")
    topology = renderer_topology_for_profile(metadata.profile_id)
    renderer_counts_attr = curves.GetAttribute("curveVertexCounts")
    if renderer_counts_attr.GetTimeSamples():
        raise ValueError("Renderer curve topology must be authored only once.")
    renderer_counts = tuple(renderer_counts_attr.Get() or ())
    if renderer_counts != topology.curve_vertex_counts:
        raise ValueError("Persisted renderer topology differs from the profile.")

    points_attr = curves.GetAttribute("points")
    speed_attr = curves.GetAttribute(SPEED_PRIMVAR_ATTRIBUTE)
    source_counts_attr = curves.GetAttribute(SOURCE_CURVE_VERTEX_COUNTS_ATTRIBUTE)
    expected_times = tuple(state.time_code for state in metadata.states)
    for attribute, label in (
        (points_attr, "points"),
        (speed_attr, "speed"),
        (source_counts_attr, "source topology"),
    ):
        if not attribute or not attribute.IsValid():
            raise ValueError(f"Persisted Streamlines {label} is missing.")
        times = tuple(float(value) for value in attribute.GetTimeSamples())
        if times != expected_times:
            raise ValueError(
                f"Persisted Streamlines {label} time samples are incomplete."
            )

    requested = (
        set(range(len(metadata.states)))
        if sample_indices is None
        else {int(value) for value in sample_indices}
    )
    proofs = []
    for sample_index in sorted(requested):
        if not 0 <= sample_index < len(metadata.states):
            raise ValueError("Requested cache sample index is unavailable.")
        state = metadata.states[sample_index]
        time_code = Usd.TimeCode(state.time_code)
        points = tuple(points_attr.Get(time_code) or ())
        speeds = tuple(speed_attr.Get(time_code) or ())
        source_counts = tuple(source_counts_attr.Get(time_code) or ())
        if len(points) != topology.point_count:
            raise ValueError("Persisted renderer point count is invalid.")
        if len(speeds) != topology.point_count:
            raise ValueError("Persisted renderer speed count is invalid.")
        if len(source_counts) != topology.curve_count or any(
            count < MIN_CUBIC_CURVE_VERTEX_COUNT or count > topology.vertices_per_curve
            for count in source_counts
        ):
            raise ValueError("Persisted source curve topology is invalid.")
        source_point_count = sum(source_counts)
        if source_point_count != state.source_point_count:
            raise ValueError("Persisted source point count differs from metadata.")
        if topology_signature(source_counts) != state.source_topology_signature:
            raise ValueError("Persisted source topology differs from metadata.")
        point_padding_valid = terminal_padding_is_exact(
            points,
            source_counts,
            vertices_per_curve=topology.vertices_per_curve,
        )
        speed_padding_valid = terminal_padding_is_exact(
            speeds,
            source_counts,
            vertices_per_curve=topology.vertices_per_curve,
        )
        if not point_padding_valid or not speed_padding_valid:
            raise ValueError("Persisted terminal padding is not an exact repeat.")
        proofs.append(
            PersistedConstantTopologyProof(
                sample_index=sample_index,
                time_code=state.time_code,
                curve_count=topology.curve_count,
                point_count=len(points),
                speed_count=len(speeds),
                source_curve_count=len(source_counts),
                source_point_count=source_point_count,
                terminal_points_repeated=point_padding_valid,
                terminal_speeds_repeated=speed_padding_valid,
            )
        )
    return tuple(proofs)
