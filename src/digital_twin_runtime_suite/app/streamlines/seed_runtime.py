# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""Author converter-compatible Streamlines seed meshes from pure layouts."""

from __future__ import annotations

from dataclasses import dataclass

from digital_twin_runtime_suite.app.streamlines.seed_layout import (
    STREAMLINES_FRONT_INTAKE_SEED_PATH,
    StratifiedSeedLayout,
    canonicalize_point3f_points,
)


@dataclass(frozen=True)
class SeedMeshTopology:
    """Hold deterministic faces over existing semantic seed vertices only."""

    face_vertex_counts: tuple[int, ...]
    face_vertex_indices: tuple[int, ...]


def build_stratified_seed_mesh_topology(
    layout: StratifiedSeedLayout,
) -> SeedMeshTopology:
    """Triangulate each section independently without adding seed vertices."""

    counts = []
    indices = []
    rows = layout.rows_per_section
    for section, section_offset in enumerate(layout.section_point_offsets):
        row_counts = layout.row_counts[section * rows : (section + 1) * rows]
        row_offsets = []
        offset = section_offset
        for count in row_counts:
            row_offsets.append(offset)
            offset += count
        for row in range(rows - 1):
            strip = _triangulate_row_pair(
                row_offsets[row],
                row_counts[row],
                row_offsets[row + 1],
                row_counts[row + 1],
            )
            for face in strip:
                counts.append(len(face))
                indices.extend(face)
    topology = SeedMeshTopology(tuple(counts), tuple(indices))
    if topology.face_vertex_indices and (
        min(topology.face_vertex_indices) < 0
        or max(topology.face_vertex_indices) >= layout.seed_count
    ):
        raise ValueError("Streamlines seed topology references a missing vertex.")
    return topology


def author_streamlines_seed_mesh_in_kit(
    stage,
    *,
    layout: StratifiedSeedLayout,
    UsdGeom,
    seed_path: str = STREAMLINES_FRONT_INTAKE_SEED_PATH,
) -> None:
    """Author and verify one float32-safe Mesh accepted by Kit-CAE."""

    topology = build_stratified_seed_mesh_topology(layout)
    points = canonicalize_point3f_points(layout.points)
    seed = UsdGeom.Mesh.Define(stage, seed_path)
    seed.CreatePointsAttr().Set(list(points))
    seed.CreateFaceVertexCountsAttr().Set(list(topology.face_vertex_counts))
    seed.CreateFaceVertexIndicesAttr().Set(list(topology.face_vertex_indices))
    seed.CreateExtentAttr().Set(
        [
            tuple(min(point[axis] for point in points) for axis in range(3)),
            tuple(max(point[axis] for point in points) for axis in range(3)),
        ]
    )
    authored_points = tuple(
        tuple(float(component) for component in point)
        for point in (seed.GetPointsAttr().Get() or ())
    )
    authored_counts = tuple(seed.GetFaceVertexCountsAttr().Get() or ())
    authored_indices = tuple(seed.GetFaceVertexIndicesAttr().Get() or ())
    if authored_points != points:
        raise RuntimeError("Streamlines seed Mesh changed canonical points.")
    if (
        authored_counts != topology.face_vertex_counts
        or authored_indices != topology.face_vertex_indices
    ):
        raise RuntimeError("Streamlines seed Mesh topology changed.")


def topology_connects_sections(
    layout: StratifiedSeedLayout,
    topology: SeedMeshTopology,
) -> bool:
    """Detect a face that crosses two Volume Coverage section ranges."""

    cursor = 0
    seeds_per_section = layout.seeds_per_section
    for count in topology.face_vertex_counts:
        face = topology.face_vertex_indices[cursor : cursor + count]
        cursor += count
        sections = {index // seeds_per_section for index in face}
        if len(sections) > 1:
            return True
    return False


def _triangulate_row_pair(
    first_offset: int,
    first_count: int,
    second_offset: int,
    second_count: int,
) -> tuple[tuple[int, ...], ...]:
    """Connect centred rows deterministically with quads and edge triangles."""

    first = second = 0
    faces = []
    while first < first_count - 1 or second < second_count - 1:
        first_progress = (
            (first + 1) / (first_count - 1) if first < first_count - 1 else float("inf")
        )
        second_progress = (
            (second + 1) / (second_count - 1)
            if second < second_count - 1
            else float("inf")
        )
        if first_progress == second_progress:
            faces.append(
                (
                    first_offset + first,
                    first_offset + first + 1,
                    second_offset + second + 1,
                    second_offset + second,
                )
            )
            first += 1
            second += 1
        elif first_progress < second_progress:
            faces.append(
                (
                    first_offset + first,
                    first_offset + first + 1,
                    second_offset + second,
                )
            )
            first += 1
        else:
            faces.append(
                (
                    first_offset + first,
                    second_offset + second + 1,
                    second_offset + second,
                )
            )
            second += 1
    return tuple(faces)
