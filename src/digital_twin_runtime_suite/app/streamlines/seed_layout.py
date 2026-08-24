# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""Deterministic front-intake point-rake derivation for Streamlines previews."""

from __future__ import annotations

import hashlib
import json
import math
import struct
from dataclasses import dataclass

from digital_twin_runtime_suite.app.streamlines.profile import (
    StreamlinesProfileId,
)

STREAMLINES_FRONT_INTAKE_SEED_PATH = "/DTRS_KitCAE/StreamlineSeeds/FrontIntakeGrid"
STREAMLINES_SERVER_ROOT_PATH = "/blackwell_rig"
_POINT3F = struct.Struct("<fff")
_FLOAT32_REL_TOLERANCE = 2.0**-21
_FLOAT32_ABS_TOLERANCE = 1.0e-6


@dataclass(frozen=True)
class StreamlinesSeedLayoutProfile:
    """Source-controlled candidate settings for one deterministic point rake."""

    columns: int = 16
    rows: int = 8
    front_inward_cell_multiplier: float = 4.0
    seed_type: str = "point_grid"

    def __post_init__(self) -> None:
        """Reject a layout that cannot produce a bounded seed grid."""

        if (
            self.columns <= 0
            or self.rows <= 0
            or self.seed_type != "point_grid"
            or not math.isfinite(self.front_inward_cell_multiplier)
            or self.front_inward_cell_multiplier <= 0.0
        ):
            raise ValueError("Streamlines seed-layout profile is invalid.")

    def to_dict(self) -> dict[str, object]:
        """Return the future cache-signature payload for this candidate."""

        return {
            "columns": self.columns,
            "rows": self.rows,
            "front_inward_cell_multiplier": (self.front_inward_cell_multiplier),
            "seed_type": self.seed_type,
        }

    @property
    def settings_signature(self) -> str:
        """Identify the complete point-rake layout contract deterministically."""

        payload = json.dumps(
            self.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


PRODUCTION_STREAMLINES_SEED_LAYOUT = StreamlinesSeedLayoutProfile()


@dataclass(frozen=True)
class FrontIntakeSeedLayout:
    """Resolved 3D seed points and their verifiable spacing evidence."""

    points: tuple[tuple[float, float, float], ...]
    columns: int
    rows: int
    horizontal_spacing: float
    vertical_spacing: float
    seed_plane_z: float
    edge_margin_x: float
    edge_margin_y: float
    centre: tuple[float, float, float]
    profile_signature: str
    domain_bounds: tuple[
        tuple[float, float, float],
        tuple[float, float, float],
    ]

    @property
    def seed_count(self) -> int:
        """Return the exact number of authored point seeds."""

        return len(self.points)


@dataclass(frozen=True)
class StratifiedSeedLayout:
    """Describe exact-budget seed rows on one or more disconnected planes."""

    profile_id: StreamlinesProfileId
    points: tuple[tuple[float, float, float], ...]
    row_counts: tuple[int, ...]
    rows_per_section: int
    section_planes: tuple[float, ...]
    section_point_offsets: tuple[int, ...]
    y_spacing: float
    domain_bounds: tuple[
        tuple[float, float, float],
        tuple[float, float, float],
    ]

    @property
    def seed_count(self) -> int:
        return len(self.points)

    @property
    def section_count(self) -> int:
        return len(self.section_planes)

    @property
    def seeds_per_section(self) -> int:
        return sum(self.row_counts[: self.rows_per_section])


def derive_global_flow_path_layout(
    domain_bounds: tuple[
        tuple[float, float, float],
        tuple[float, float, float],
    ],
    *,
    seed_count: int,
    front_intake_z: float,
    max_cell_spacing: float,
    front_inward_cell_multiplier: float = 4.0,
) -> StratifiedSeedLayout:
    """Derive one exact-budget seed plane at the accepted front intake."""

    minimum, maximum = _validated_bounds(domain_bounds)
    if max_cell_spacing <= 0.0:
        raise ValueError("Streamlines seed cell spacing must be positive.")
    plane_z = min(float(front_intake_z), maximum[2]) - (
        max_cell_spacing * front_inward_cell_multiplier
    )
    if not minimum[2] < plane_z < maximum[2]:
        raise ValueError("Global seed plane must remain inside the domain.")
    return _derive_stratified_layout(
        profile_id=StreamlinesProfileId.GLOBAL_FLOW_PATH,
        domain_bounds=(minimum, maximum),
        seed_count=seed_count,
        section_planes=(plane_z,),
    )


def derive_volume_coverage_layout(
    domain_bounds: tuple[
        tuple[float, float, float],
        tuple[float, float, float],
    ],
    *,
    section_count: int,
    seeds_per_section: int,
) -> StratifiedSeedLayout:
    """Distribute identical exact-budget planes through the domain depth."""

    minimum, maximum = _validated_bounds(domain_bounds)
    if section_count <= 0:
        raise ValueError("Volume Coverage requires at least one section.")
    spacing = (maximum[2] - minimum[2]) / (section_count + 1)
    planes = tuple(
        maximum[2] - spacing * (section + 1) for section in range(section_count)
    )
    return _derive_stratified_layout(
        profile_id=StreamlinesProfileId.VOLUME_COVERAGE,
        domain_bounds=(minimum, maximum),
        seed_count=seeds_per_section,
        section_planes=planes,
    )


def exact_budget_row_counts(seed_count: int) -> tuple[int, ...]:
    """Split an exact budget into deterministic near-2:1 centred rows."""

    if seed_count < 4:
        raise ValueError("Streamlines seed budget must contain at least four points.")
    rows = max(2, round(math.sqrt(seed_count / 2.0)))
    base, extra = divmod(seed_count, rows)
    if base < 2:
        raise ValueError("Each Streamlines seed row requires at least two points.")
    centred_order = sorted(
        range(rows),
        key=lambda row: (abs(row - (rows - 1) / 2.0), row),
    )
    extra_rows = set(centred_order[:extra])
    return tuple(base + (row in extra_rows) for row in range(rows))


def _derive_stratified_layout(
    *,
    profile_id: StreamlinesProfileId,
    domain_bounds: tuple[
        tuple[float, float, float],
        tuple[float, float, float],
    ],
    seed_count: int,
    section_planes: tuple[float, ...],
) -> StratifiedSeedLayout:
    minimum, maximum = domain_bounds
    row_counts = exact_budget_row_counts(seed_count)
    rows = len(row_counts)
    y_spacing = (maximum[1] - minimum[1]) / (rows + 1)
    plane_points = []
    for row, count in enumerate(row_counts):
        x_spacing = (maximum[0] - minimum[0]) / (count + 1)
        y = minimum[1] + y_spacing * (row + 1)
        plane_points.extend(
            (
                minimum[0] + x_spacing * (column + 1),
                y,
            )
            for column in range(count)
        )
    points = tuple(
        (float(x), float(y), float(z)) for z in section_planes for x, y in plane_points
    )
    expected = seed_count * len(section_planes)
    if len(points) != expected or len(set(points)) != expected:
        raise ValueError("Streamlines stratified layout is not exact and unique.")
    if any(
        not (
            minimum[0] < x < maximum[0]
            and minimum[1] < y < maximum[1]
            and minimum[2] < z < maximum[2]
        )
        for x, y, z in points
    ):
        raise ValueError("Streamlines stratified layout crosses domain bounds.")
    offsets = tuple(section * seed_count for section in range(len(section_planes)))
    return StratifiedSeedLayout(
        profile_id=profile_id,
        points=points,
        row_counts=row_counts * len(section_planes),
        rows_per_section=rows,
        section_planes=tuple(float(value) for value in section_planes),
        section_point_offsets=offsets,
        y_spacing=y_spacing,
        domain_bounds=domain_bounds,
    )


def _validated_bounds(
    domain_bounds: tuple[
        tuple[float, float, float],
        tuple[float, float, float],
    ],
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    minimum = tuple(float(value) for value in domain_bounds[0])
    maximum = tuple(float(value) for value in domain_bounds[1])
    if (
        len(minimum) != 3
        or len(maximum) != 3
        or any(not math.isfinite(value) for value in (*minimum, *maximum))
        or any(maximum[axis] <= minimum[axis] for axis in range(3))
    ):
        raise ValueError("Streamlines seed bounds must have finite positive extent.")
    return minimum, maximum


def derive_front_intake_seed_layout(
    domain_bounds: tuple[
        tuple[float, float, float],
        tuple[float, float, float],
    ],
    *,
    front_intake_z: float,
    max_cell_spacing: float,
    profile: StreamlinesSeedLayoutProfile = PRODUCTION_STREAMLINES_SEED_LAYOUT,
) -> FrontIntakeSeedLayout:
    """Place one bordered X/Y grid behind the real front-intake plane."""

    minimum, maximum = domain_bounds
    values = (*minimum, *maximum, front_intake_z, max_cell_spacing)
    if any(not math.isfinite(float(value)) for value in values):
        raise ValueError("Streamlines seed bounds must contain finite values.")
    extents = tuple(maximum[axis] - minimum[axis] for axis in range(3))
    if any(extent <= 0.0 for extent in extents):
        raise ValueError("Streamlines seed bounds must have positive extent.")
    if max_cell_spacing <= 0.0:
        raise ValueError("Streamlines seed cell spacing must be positive.")

    horizontal_spacing = extents[0] / (profile.columns + 1)
    vertical_spacing = extents[1] / (profile.rows + 1)
    inward_offset = max_cell_spacing * profile.front_inward_cell_multiplier
    front_limit = min(float(front_intake_z), float(maximum[2]))
    seed_plane_z = front_limit - inward_offset
    if not minimum[2] < seed_plane_z < maximum[2]:
        raise ValueError(
            "Front-intake seed plane must remain strictly inside the domain."
        )

    x_values = tuple(
        minimum[0] + horizontal_spacing * (column + 1)
        for column in range(profile.columns)
    )
    y_values = tuple(
        minimum[1] + vertical_spacing * (row + 1) for row in range(profile.rows)
    )
    points = tuple(
        (float(x), float(y), float(seed_plane_z)) for y in y_values for x in x_values
    )
    if len(points) != profile.columns * profile.rows or len(set(points)) != len(points):
        raise ValueError("Streamlines seed grid must contain unique points.")
    if any(
        not (
            minimum[0] < point[0] < maximum[0]
            and minimum[1] < point[1] < maximum[1]
            and minimum[2] < point[2] < maximum[2]
        )
        for point in points
    ):
        raise ValueError("Streamlines seed grid extends outside the domain.")

    return FrontIntakeSeedLayout(
        points=points,
        columns=profile.columns,
        rows=profile.rows,
        horizontal_spacing=horizontal_spacing,
        vertical_spacing=vertical_spacing,
        seed_plane_z=seed_plane_z,
        edge_margin_x=horizontal_spacing,
        edge_margin_y=vertical_spacing,
        centre=(
            (minimum[0] + maximum[0]) / 2.0,
            (minimum[1] + maximum[1]) / 2.0,
            seed_plane_z,
        ),
        profile_signature=profile.settings_signature,
        domain_bounds=(
            tuple(float(value) for value in minimum),
            tuple(float(value) for value in maximum),
        ),
    )


def canonicalize_point3f_points(
    points: tuple[tuple[float, float, float], ...],
) -> tuple[tuple[float, float, float], ...]:
    """Round positions to the exact representation stored by ``point3f[]``."""

    return tuple(
        tuple(float(component) for component in _POINT3F.unpack(_POINT3F.pack(*point)))
        for point in points
    )


def build_point_rake_quad_topology(
    columns: int,
    rows: int,
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Connect a row-major point rake with deterministic counter-clockwise quads."""

    if columns < 2 or rows < 2:
        raise ValueError("Streamlines point-rake mesh requires at least a 2x2 grid.")
    face_count = (columns - 1) * (rows - 1)
    face_vertex_counts = (4,) * face_count
    face_vertex_indices = tuple(
        vertex
        for row in range(rows - 1)
        for column in range(columns - 1)
        for vertex in (
            row * columns + column,
            row * columns + column + 1,
            (row + 1) * columns + column + 1,
            (row + 1) * columns + column,
        )
    )
    return face_vertex_counts, face_vertex_indices


def validate_point3f_seed_round_trip(
    layout: FrontIntakeSeedLayout,
    authored_points,
) -> tuple[tuple[float, float, float], ...]:
    """Require authored USD points to equal the valid canonical float32 rake."""

    expected = canonicalize_point3f_points(layout.points)
    authored = tuple(
        tuple(float(component) for component in point) for point in authored_points
    )
    if not _canonical_point_rake_is_valid(layout, authored):
        raise RuntimeError("Streamlines point-rake authoring changed seed points.")
    if authored != expected:
        raise RuntimeError("Streamlines point-rake authoring changed seed points.")
    return authored


def _canonical_point_rake_is_valid(
    layout: FrontIntakeSeedLayout,
    points: tuple[tuple[float, float, float], ...],
) -> bool:
    """Preserve layout invariants after the intentional float32 conversion."""

    expected_count = layout.columns * layout.rows
    if len(points) != expected_count or len(set(points)) != expected_count:
        return False
    minimum, maximum = layout.domain_bounds
    if any(
        not (
            minimum[0] < point[0] < maximum[0]
            and minimum[1] < point[1] < maximum[1]
            and minimum[2] < point[2] < maximum[2]
        )
        for point in points
    ):
        return False
    x_values = sorted({point[0] for point in points})
    y_values = sorted({point[1] for point in points})
    z_values = {point[2] for point in points}
    if (
        len(x_values) != layout.columns
        or len(y_values) != layout.rows
        or len(z_values) != 1
    ):
        return False
    comparisons = (
        ((x_values[0] + x_values[-1]) / 2.0, layout.centre[0]),
        ((y_values[0] + y_values[-1]) / 2.0, layout.centre[1]),
        (x_values[0] - minimum[0], layout.edge_margin_x),
        (maximum[0] - x_values[-1], layout.edge_margin_x),
        (y_values[0] - minimum[1], layout.edge_margin_y),
        (maximum[1] - y_values[-1], layout.edge_margin_y),
        (next(iter(z_values)), layout.seed_plane_z),
    )
    return all(
        math.isclose(
            actual,
            expected,
            rel_tol=_FLOAT32_REL_TOLERANCE,
            abs_tol=_FLOAT32_ABS_TOLERANCE,
        )
        for actual, expected in comparisons
    )
