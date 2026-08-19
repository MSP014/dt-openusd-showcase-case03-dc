"""Build deterministic fixed-topology tube Mesh data with installed VTK."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

DEFAULT_TUBE_SIDE_COUNT = 4
SOURCE_POINT_INDEX_ATTRIBUTE = "dtrs:sourcePointIndex"


@dataclass(frozen=True)
class StreamlinesTubeMeshTopology:
    """Static renderer topology and source-point mapping for one profile."""

    face_vertex_counts: np.ndarray
    face_vertex_indices: np.ndarray
    source_point_indices: np.ndarray
    curve_count: int
    centerline_points_per_curve: int
    side_count: int

    @property
    def point_count(self) -> int:
        return len(self.source_point_indices)


@dataclass(frozen=True)
class StreamlinesTubeMeshState:
    """One VTK-derived renderer state aligned to static Mesh topology."""

    points: np.ndarray
    speeds: np.ndarray
    extent: np.ndarray


def build_streamlines_tube_mesh_topology(
    *,
    curve_count: int,
    centerline_points_per_curve: int,
    side_count: int = DEFAULT_TUBE_SIDE_COUNT,
) -> StreamlinesTubeMeshTopology:
    """Use one installed VTK tube template, then replicate its static topology."""

    if curve_count <= 0 or centerline_points_per_curve < 2 or side_count < 3:
        raise ValueError("Streamlines Mesh topology dimensions are invalid.")
    template_points = np.column_stack(
        (
            np.zeros(centerline_points_per_curve),
            np.zeros(centerline_points_per_curve),
            np.arange(centerline_points_per_curve, dtype=np.float32),
        )
    ).astype(np.float32)
    template_counts = np.asarray([centerline_points_per_curve], dtype=np.int32)
    template_indices = np.arange(centerline_points_per_curve, dtype=np.int32)
    output = _run_vtk_tube_filter(
        template_points,
        template_counts,
        template_indices,
        np.zeros(centerline_points_per_curve, dtype=np.float32),
        radius=1.0,
        side_count=side_count,
    )
    template_mapping = output.source_point_indices
    expected_mapping = np.repeat(template_indices, side_count)
    if not np.array_equal(template_mapping, expected_mapping):
        raise RuntimeError("Installed VTK tube vertex ordering is incompatible.")
    points_per_curve = centerline_points_per_curve * side_count
    template_faces = output.face_vertex_indices.reshape((-1, 3))
    offsets = np.arange(curve_count, dtype=np.int64) * points_per_curve
    faces = (
        template_faces[np.newaxis, :, :] + offsets[:, np.newaxis, np.newaxis]
    ).reshape((-1, 3))
    mapping = np.repeat(
        np.arange(
            curve_count * centerline_points_per_curve,
            dtype=np.int32,
        ),
        side_count,
    )
    topology = StreamlinesTubeMeshTopology(
        face_vertex_counts=np.full(len(faces), 3, dtype=np.int32),
        face_vertex_indices=faces.reshape(-1).astype(np.int32),
        source_point_indices=mapping,
        curve_count=curve_count,
        centerline_points_per_curve=centerline_points_per_curve,
        side_count=side_count,
    )
    validate_streamlines_tube_mesh_topology(topology)
    return topology


def convert_streamlines_centerlines_to_tube_mesh(
    centerline_points,
    curve_vertex_counts,
    source_curve_vertex_counts,
    source_speeds,
    *,
    radius: float,
    topology: StreamlinesTubeMeshTopology,
) -> StreamlinesTubeMeshState:
    """Convert authentic centerlines with VTK and pad only terminal Mesh rings."""

    points = np.asarray(centerline_points, dtype=np.float32)
    renderer_counts = np.asarray(curve_vertex_counts, dtype=np.int32)
    source_counts = np.asarray(source_curve_vertex_counts, dtype=np.int32)
    speeds = np.asarray(source_speeds, dtype=np.float32)
    _validate_centerline_inputs(
        points,
        renderer_counts,
        source_counts,
        speeds,
        radius=radius,
        topology=topology,
    )
    points_per_curve = topology.centerline_points_per_curve
    authentic_indices = np.concatenate(
        [
            np.arange(
                curve * points_per_curve,
                curve * points_per_curve + count,
                dtype=np.int32,
            )
            for curve, count in enumerate(source_counts)
        ]
    )
    output = _run_vtk_tube_filter(
        points[authentic_indices],
        source_counts,
        authentic_indices,
        speeds[authentic_indices],
        radius=radius,
        side_count=topology.side_count,
    )
    mapped_rings = output.source_point_indices.reshape((-1, topology.side_count))
    if not np.all(mapped_rings == mapped_rings[:, :1]):
        raise RuntimeError("Installed VTK tube output mixed source-point rings.")
    ring_sources = mapped_rings[:, 0]
    if len(np.unique(ring_sources)) != len(authentic_indices):
        raise RuntimeError("Installed VTK tube output lost a source-point ring.")
    renderer_rings = np.empty((len(points), topology.side_count, 3), dtype=np.float32)
    renderer_rings[ring_sources] = output.points.reshape((-1, topology.side_count, 3))
    for curve, count in enumerate(source_counts):
        first = curve * points_per_curve
        terminal = first + int(count) - 1
        renderer_rings[first + int(count) : first + points_per_curve] = renderer_rings[
            terminal
        ]
    mesh_points = renderer_rings.reshape((-1, 3))
    mesh_speeds = speeds[topology.source_point_indices]
    state = StreamlinesTubeMeshState(
        points=mesh_points,
        speeds=mesh_speeds,
        extent=np.asarray(
            [mesh_points.min(axis=0), mesh_points.max(axis=0)],
            dtype=np.float32,
        ),
    )
    validate_streamlines_tube_mesh_state(state, topology=topology)
    return state


def validate_streamlines_tube_mesh_topology(
    topology: StreamlinesTubeMeshTopology,
) -> None:
    """Reject any static topology or mapping unsafe for renderer attachment."""

    if topology.point_count <= 0 or len(topology.face_vertex_counts) <= 0:
        raise ValueError("Streamlines Mesh topology is empty.")
    if not np.all(topology.face_vertex_counts == 3):
        raise ValueError("Streamlines Mesh topology must contain triangles only.")
    if len(topology.face_vertex_indices) != int(topology.face_vertex_counts.sum()):
        raise ValueError("Streamlines Mesh face arrays are inconsistent.")
    if (
        topology.face_vertex_indices.min(initial=0) < 0
        or topology.face_vertex_indices.max(initial=-1) >= topology.point_count
    ):
        raise ValueError("Streamlines Mesh topology has an out-of-range index.")
    source_point_count = topology.curve_count * topology.centerline_points_per_curve
    if (
        len(topology.source_point_indices) != topology.point_count
        or topology.source_point_indices.min(initial=0) < 0
        or topology.source_point_indices.max(initial=-1) >= source_point_count
    ):
        raise ValueError("Streamlines Mesh source-point mapping is invalid.")


def validate_streamlines_tube_mesh_state(
    state: StreamlinesTubeMeshState,
    *,
    topology: StreamlinesTubeMeshTopology,
) -> None:
    """Require one complete finite temporal state before persistence."""

    if len(state.points) != topology.point_count:
        raise ValueError("Streamlines Mesh temporal point count drifted.")
    if len(state.speeds) != len(state.points):
        raise ValueError("Streamlines Mesh speed count differs from points.")
    if state.extent.shape != (2, 3):
        raise ValueError("Streamlines Mesh extent is invalid.")
    if not np.isfinite(state.points).all() or not np.isfinite(state.speeds).all():
        raise ValueError("Streamlines Mesh temporal state contains non-finite data.")
    if not np.isfinite(state.extent).all():
        raise ValueError("Streamlines Mesh extent contains non-finite data.")


@dataclass(frozen=True)
class _VtkTubeOutput:
    points: np.ndarray
    face_vertex_indices: np.ndarray
    source_point_indices: np.ndarray
    speeds: np.ndarray


def _run_vtk_tube_filter(
    points: np.ndarray,
    curve_counts: np.ndarray,
    source_indices: np.ndarray,
    speeds: np.ndarray,
    *,
    radius: float,
    side_count: int,
) -> _VtkTubeOutput:
    """Execute the installed supported VTK tube and triangle filters."""

    from vtkmodules.util.numpy_support import (
        numpy_to_vtk,
        numpy_to_vtkIdTypeArray,
        vtk_to_numpy,
    )
    from vtkmodules.vtkCommonCore import vtkPoints
    from vtkmodules.vtkCommonDataModel import vtkCellArray, vtkPolyData
    from vtkmodules.vtkFiltersCore import vtkTriangleFilter, vtkTubeFilter

    vtk_points = vtkPoints()
    vtk_points.SetData(numpy_to_vtk(points, deep=True))
    offsets = np.concatenate(
        (
            np.asarray([0], dtype=np.int64),
            np.cumsum(curve_counts, dtype=np.int64),
        )
    )
    lines = vtkCellArray()
    lines.SetData(
        numpy_to_vtkIdTypeArray(offsets, deep=True),
        numpy_to_vtkIdTypeArray(np.arange(len(points), dtype=np.int64), deep=True),
    )
    polydata = vtkPolyData()
    polydata.SetPoints(vtk_points)
    polydata.SetLines(lines)
    source_array = numpy_to_vtk(source_indices, deep=True)
    source_array.SetName(SOURCE_POINT_INDEX_ATTRIBUTE)
    polydata.GetPointData().AddArray(source_array)
    speed_array = numpy_to_vtk(speeds, deep=True)
    speed_array.SetName("dtrs:speed")
    polydata.GetPointData().AddArray(speed_array)
    tube = vtkTubeFilter()
    tube.SetInputData(polydata)
    tube.SetRadius(float(radius))
    tube.SetNumberOfSides(int(side_count))
    tube.CappingOff()
    tube.Update()
    triangles = vtkTriangleFilter()
    triangles.SetInputConnection(tube.GetOutputPort())
    triangles.Update()
    output = triangles.GetOutput()
    return _VtkTubeOutput(
        points=np.asarray(vtk_to_numpy(output.GetPoints().GetData()), dtype=np.float32),
        face_vertex_indices=np.asarray(
            vtk_to_numpy(output.GetPolys().GetConnectivityArray()),
            dtype=np.int32,
        ),
        source_point_indices=np.asarray(
            vtk_to_numpy(output.GetPointData().GetArray(SOURCE_POINT_INDEX_ATTRIBUTE)),
            dtype=np.int32,
        ),
        speeds=np.asarray(
            vtk_to_numpy(output.GetPointData().GetArray("dtrs:speed")),
            dtype=np.float32,
        ),
    )


def _validate_centerline_inputs(
    points: np.ndarray,
    renderer_counts: np.ndarray,
    source_counts: np.ndarray,
    speeds: np.ndarray,
    *,
    radius: float,
    topology: StreamlinesTubeMeshTopology,
) -> None:
    expected_points = topology.curve_count * topology.centerline_points_per_curve
    if points.shape != (expected_points, 3) or len(speeds) != expected_points:
        raise ValueError("Streamlines centerline point/speed count is invalid.")
    if len(renderer_counts) != topology.curve_count or not np.all(
        renderer_counts == topology.centerline_points_per_curve
    ):
        raise ValueError("Streamlines renderer centerline topology is invalid.")
    if len(source_counts) != topology.curve_count or np.any(source_counts < 2):
        raise ValueError("Streamlines authentic curve topology is invalid.")
    if np.any(source_counts > topology.centerline_points_per_curve):
        raise ValueError("Streamlines authentic curve exceeds the fixed budget.")
    if not np.isfinite(points).all() or not np.isfinite(speeds).all():
        raise ValueError("Streamlines centerline input contains non-finite data.")
    if not np.isfinite(radius) or radius <= 0.0:
        raise ValueError("Streamlines tube radius must be finite and positive.")
