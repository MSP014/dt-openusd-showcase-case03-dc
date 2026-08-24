# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""Inspect persisted Streamlines geometry for real temporal movement."""

from __future__ import annotations

import hashlib
import math
import struct
from dataclasses import dataclass
from pathlib import Path

from digital_twin_runtime_suite.app.streamlines.cache import (
    CACHE_PLAYBACK_CURVES_PATH,
    StreamlinesCacheMetadata,
)
from digital_twin_runtime_suite.app.streamlines.constant_topology import (
    SOURCE_CURVE_VERTEX_COUNTS_ATTRIBUTE,
    authentic_values_from_padded_curves,
    renderer_topology_for_profile,
)


@dataclass(frozen=True)
class PersistedTemporalGeometryState:
    """One sampled cache state reduced to authentic geometry evidence."""

    sample_index: int
    source_time_seconds: float
    source_vti_identity: str
    source_point_count: int
    geometry_sha256: str


@dataclass(frozen=True)
class PersistedTemporalGeometryPair:
    """Authentic-vertex displacement between two persisted cache states."""

    previous_sample_index: int
    sample_index: int
    shared_source_point_count: int
    maximum_displacement: float

    @property
    def changed(self) -> bool:
        """Report whether authentic geometry moved between these states."""

        return self.maximum_displacement > 0.0


@dataclass(frozen=True)
class PersistedTemporalGeometryEvidence:
    """Renderer-independent liveness proof for one persisted cache."""

    workload: str
    profile_id: str
    sample_count: int
    sampled_states: tuple[PersistedTemporalGeometryState, ...]
    temporal_pairs: tuple[PersistedTemporalGeometryPair, ...]
    distinct_geometry_state_hashes: int

    @property
    def nonzero_temporal_pair_count(self) -> int:
        """Count sampled state pairs that moved before renderer padding."""

        return sum(pair.changed for pair in self.temporal_pairs)

    @property
    def passed(self) -> bool:
        """Require a changing authentic state, not only changing padding."""

        return (
            self.sample_count > 1
            and self.distinct_geometry_state_hashes > 1
            and self.nonzero_temporal_pair_count > 0
        )


def distributed_manifest_sample_indices(sample_count: int) -> tuple[int, ...]:
    """Select first, last, and evenly distributed real manifest states."""

    if sample_count <= 0:
        raise ValueError("Temporal geometry diagnosis requires manifest states.")
    last = sample_count - 1
    return tuple(dict.fromkeys((0, last // 4, last // 2, 3 * last // 4, last)))


def inspect_persisted_streamlines_temporal_geometry(
    geometry_path: Path,
    metadata: StreamlinesCacheMetadata,
) -> PersistedTemporalGeometryEvidence:
    """Read representative real states and reject a temporally static cache.

    Geometry is compared after removing fixed renderer padding.  The result is
    deliberately independent of snapshot authoring and scheduler activity.
    """

    from pxr import Usd

    if metadata.sample_count != len(metadata.states):
        raise ValueError("Cache metadata does not contain every manifest state.")
    stage = Usd.Stage.Open(str(geometry_path))
    if stage is None:
        raise ValueError("Persisted Streamlines geometry cannot be opened.")
    curves = stage.GetPrimAtPath(CACHE_PLAYBACK_CURVES_PATH)
    if not curves or not curves.IsValid():
        raise ValueError("Persisted Streamlines curves are unavailable.")
    points_attribute = curves.GetAttribute("points")
    source_counts_attribute = curves.GetAttribute(SOURCE_CURVE_VERTEX_COUNTS_ATTRIBUTE)
    if not points_attribute or not source_counts_attribute:
        raise ValueError("Persisted Streamlines temporal geometry is incomplete.")

    topology = renderer_topology_for_profile(metadata.profile_id)
    sampled_states = []
    authentic_states = []
    for sample_index in distributed_manifest_sample_indices(metadata.sample_count):
        state = metadata.states[sample_index]
        time_code = Usd.TimeCode(state.time_code)
        source_counts = tuple(source_counts_attribute.Get(time_code) or ())
        padded_points = tuple(points_attribute.Get(time_code) or ())
        authentic_points = authentic_values_from_padded_curves(
            padded_points,
            source_counts,
            vertices_per_curve=topology.vertices_per_curve,
        )
        sampled_states.append(
            PersistedTemporalGeometryState(
                sample_index=state.sample_index,
                source_time_seconds=state.source_time_seconds,
                source_vti_identity=state.source_vti_identity,
                source_point_count=len(authentic_points),
                geometry_sha256=_authentic_geometry_sha256(
                    authentic_points,
                    source_counts,
                ),
            )
        )
        authentic_states.append(authentic_points)

    pairs = tuple(
        PersistedTemporalGeometryPair(
            previous_sample_index=previous.sample_index,
            sample_index=current.sample_index,
            shared_source_point_count=min(
                len(previous_points),
                len(current_points),
            ),
            maximum_displacement=_maximum_displacement(
                previous_points,
                current_points,
            ),
        )
        for previous, current, previous_points, current_points in zip(
            sampled_states,
            sampled_states[1:],
            authentic_states,
            authentic_states[1:],
        )
    )
    return PersistedTemporalGeometryEvidence(
        workload=metadata.workload,
        profile_id=metadata.profile_id,
        sample_count=metadata.sample_count,
        sampled_states=tuple(sampled_states),
        temporal_pairs=pairs,
        distinct_geometry_state_hashes=len(
            {state.geometry_sha256 for state in sampled_states}
        ),
    )


def format_persisted_temporal_geometry_evidence(
    evidence: PersistedTemporalGeometryEvidence,
) -> str:
    """Render compact cache liveness evidence for the matrix readiness log."""

    states = ", ".join(
        f"{state.sample_index}:{state.geometry_sha256[:12]}"
        for state in evidence.sampled_states
    )
    maximum_displacement = max(
        (pair.maximum_displacement for pair in evidence.temporal_pairs),
        default=0.0,
    )
    return (
        f"workload={evidence.workload}; profile={evidence.profile_id}; "
        f"sample_count={evidence.sample_count}; states={states}; "
        f"distinct_geometry_hashes={evidence.distinct_geometry_state_hashes}; "
        f"nonzero_temporal_pairs={evidence.nonzero_temporal_pair_count}; "
        f"max_displacement={maximum_displacement:.8g}; "
        f"temporal_geometry={'PASS' if evidence.passed else 'FAIL'}."
    )


def _authentic_geometry_sha256(points, source_counts: tuple[int, ...]) -> str:
    """Hash genuine source vertices and their topology, never padded vertices."""

    digest = hashlib.sha256()
    digest.update(struct.pack(f"<{len(source_counts)}I", *source_counts))
    for point in points:
        digest.update(struct.pack("<fff", *(float(axis) for axis in point)))
    return digest.hexdigest()


def _maximum_displacement(previous_points, current_points) -> float:
    """Measure matching authentic vertices without inventing padded movement."""

    return max(
        (
            math.sqrt(
                sum(
                    (float(previous) - float(current)) ** 2
                    for previous, current in zip(previous_point, current_point)
                )
            )
            for previous_point, current_point in zip(previous_points, current_points)
        ),
        default=0.0,
    )
