"""Focused contracts for the Phase 4.4A front-intake point rake."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from digital_twin_runtime_suite.app.flow.static_source import (
    StaticVelocitySourceDescriptor,
)
from digital_twin_runtime_suite.app.streamlines.cache_runtime import (
    StreamlinesCacheRuntimeMixin,
)
from digital_twin_runtime_suite.app.streamlines.proof import (
    build_streamlines_preview_operator_request,
)
from digital_twin_runtime_suite.app.streamlines.seed_layout import (
    PRODUCTION_STREAMLINES_SEED_LAYOUT,
    STREAMLINES_FRONT_INTAKE_SEED_PATH,
    build_point_rake_quad_topology,
    canonicalize_point3f_points,
    derive_front_intake_seed_layout,
    validate_point3f_seed_round_trip,
)


def test_production_layout_is_one_unique_16_by_8_grid() -> None:
    layout = _layout()

    assert layout.columns == 16
    assert layout.rows == 8
    assert layout.seed_count == 128
    assert len(set(layout.points)) == 128


def test_grid_spacing_border_and_centre_follow_domain_formula() -> None:
    minimum, maximum = _bounds()
    layout = _layout()
    x_values = sorted({point[0] for point in layout.points})
    y_values = sorted({point[1] for point in layout.points})
    expected_x = (maximum[0] - minimum[0]) / 17
    expected_y = (maximum[1] - minimum[1]) / 9

    assert layout.horizontal_spacing == pytest.approx(expected_x)
    assert x_values[0] - minimum[0] == pytest.approx(expected_x)
    assert maximum[0] - x_values[-1] == pytest.approx(expected_x)
    assert x_values[-1] - x_values[0] == pytest.approx(
        maximum[0] - minimum[0] - 2 * expected_x
    )
    assert layout.vertical_spacing == pytest.approx(expected_y)
    assert y_values[0] - minimum[1] == pytest.approx(expected_y)
    assert maximum[1] - y_values[-1] == pytest.approx(expected_y)
    assert y_values[-1] - y_values[0] == pytest.approx(
        maximum[1] - minimum[1] - 2 * expected_y
    )
    assert layout.centre[:2] == pytest.approx(
        (
            (minimum[0] + maximum[0]) / 2,
            (minimum[1] + maximum[1]) / 2,
        )
    )


def test_all_points_share_one_plane_strictly_inside_the_domain() -> None:
    minimum, maximum = _bounds()
    layout = _layout()

    assert {point[2] for point in layout.points} == {layout.seed_plane_z}
    assert layout.seed_plane_z == pytest.approx(8.0)
    assert minimum[2] < layout.seed_plane_z < maximum[2]
    assert all(
        minimum[0] < point[0] < maximum[0] and minimum[1] < point[1] < maximum[1]
        for point in layout.points
    )


@pytest.mark.parametrize(
    "bounds",
    (
        ((0.0, 0.0, 0.0), (0.0, 1.0, 1.0)),
        ((0.0, 0.0, 0.0), (1.0, 0.0, 1.0)),
        ((0.0, 0.0, 0.0), (1.0, 1.0, 0.0)),
    ),
)
def test_degenerate_domain_fails_explicitly(bounds) -> None:
    with pytest.raises(ValueError, match="positive extent"):
        derive_front_intake_seed_layout(
            bounds,
            front_intake_z=0.9,
            max_cell_spacing=0.01,
        )


def test_invalid_front_plane_fails_instead_of_seeding_outside() -> None:
    with pytest.raises(ValueError, match="strictly inside"):
        derive_front_intake_seed_layout(
            _bounds(),
            front_intake_z=-9.9,
            max_cell_spacing=0.25,
        )


def test_preview_request_binds_point_rake_and_authoritative_velocity() -> None:
    descriptor = _descriptor()
    layout = _layout()

    request = build_streamlines_preview_operator_request(descriptor, layout)

    assert request.seed_path == STREAMLINES_FRONT_INTAKE_SEED_PATH
    assert "UnitSphere" not in request.seed_path
    assert request.seed_type == "point_grid"
    assert request.seed_points == layout.points
    assert request.seed_radius == 0.0
    assert request.seed_resolution == 0
    assert request.operator_type == "standard"
    assert request.velocity_field_prim_path == descriptor.velocity_field_prim_path
    assert request.seed_layout_signature == (
        PRODUCTION_STREAMLINES_SEED_LAYOUT.settings_signature
    )


def test_seed_authoring_creates_one_mesh_with_exact_vertices_and_quads() -> None:
    stage = object()
    mesh_schema = _MeshSchema()
    usd_geom = SimpleNamespace(
        Mesh=SimpleNamespace(
            Define=lambda received_stage, path: mesh_schema.define(
                received_stage,
                path,
            )
        )
    )
    layout = _layout()

    StreamlinesCacheRuntimeMixin._author_streamlines_point_rake_in_kit(
        stage,
        layout=layout,
        UsdGeom=usd_geom,
    )

    assert mesh_schema.define_calls == [(stage, STREAMLINES_FRONT_INTAKE_SEED_PATH)]
    assert tuple(mesh_schema.points.value) == canonicalize_point3f_points(layout.points)
    assert len(mesh_schema.points.value) == 128
    assert tuple(mesh_schema.face_counts.value) == (4,) * 105
    assert len(mesh_schema.face_indices.value) == 105 * 4


def test_point_rake_quad_topology_is_deterministic_and_bounded() -> None:
    face_counts, face_indices = build_point_rake_quad_topology(16, 8)

    assert len(face_counts) == 105
    assert face_counts == (4,) * 105
    assert len(face_indices) == 420
    assert face_indices[:8] == (0, 1, 17, 16, 1, 2, 18, 17)
    assert face_indices[-4:] == (110, 111, 127, 126)
    assert min(face_indices) == 0
    assert max(face_indices) == 127


def test_point_rake_survives_usd_style_float32_canonicalization() -> None:
    layout = _precision_layout()
    canonical = canonicalize_point3f_points(layout.points)

    assert canonical != layout.points
    assert validate_point3f_seed_round_trip(layout, canonical) == canonical
    assert len(canonical) == 128
    assert len(set(canonical)) == 128


def test_round_trip_rejects_a_genuinely_changed_coordinate() -> None:
    layout = _precision_layout()
    changed = list(canonicalize_point3f_points(layout.points))
    point = changed[37]
    changed[37] = (point[0] + 0.125, point[1], point[2])

    with pytest.raises(RuntimeError, match="authoring changed seed points"):
        validate_point3f_seed_round_trip(layout, changed)


def test_round_trip_rejects_wrong_point_count() -> None:
    layout = _precision_layout()
    canonical = canonicalize_point3f_points(layout.points)

    with pytest.raises(RuntimeError, match="authoring changed seed points"):
        validate_point3f_seed_round_trip(layout, canonical[:-1])


@pytest.mark.parametrize("mutation", ("duplicate", "outside"))
def test_round_trip_rejects_invalid_point_rake(mutation: str) -> None:
    layout = _precision_layout()
    changed = list(canonicalize_point3f_points(layout.points))
    if mutation == "duplicate":
        changed[1] = changed[0]
    else:
        point = changed[0]
        changed[0] = (layout.domain_bounds[0][0], point[1], point[2])

    with pytest.raises(RuntimeError, match="authoring changed seed points"):
        validate_point3f_seed_round_trip(layout, changed)


def test_layout_profile_signature_changes_with_grid_contract() -> None:
    baseline = PRODUCTION_STREAMLINES_SEED_LAYOUT
    changed = type(baseline)(columns=15, rows=8)

    assert baseline.settings_signature != changed.settings_signature


def _bounds():
    return ((-17.0, -9.0, -10.0), (17.0, 9.0, 10.0))


def _layout():
    return derive_front_intake_seed_layout(
        _bounds(),
        front_intake_z=9.0,
        max_cell_spacing=0.25,
    )


def _precision_layout():
    return derive_front_intake_seed_layout(
        ((-17.3, -9.7, -10.2), (17.9, 9.4, 10.6)),
        front_intake_z=9.13,
        max_cell_spacing=0.23,
    )


def _descriptor() -> StaticVelocitySourceDescriptor:
    return StaticVelocitySourceDescriptor(
        workload="Nominal",
        dataset_identity="server/load_normal",
        sample_index=0,
        vti_path=Path("nominal.vti"),
        dataset_prim_path="/DTRS_HoudiniVelocity/VTKImageData",
        velocity_field_prim_path="/DTRS_HoudiniVelocity/PointData/vel",
        world_bounds=_bounds(),
        dimensions=(2, 2, 2),
        spacing=(0.25, 0.25, 0.25),
        origin=_bounds()[0],
        source_origin=_bounds()[0],
        stage_meters_per_unit=1.0,
    )


class _Attribute:
    def __init__(self) -> None:
        self.value = None

    def Set(self, value) -> None:
        self.value = value

    def Get(self):
        return self.value


class _MeshSchema:
    def __init__(self) -> None:
        self.define_calls = []
        self.points = _Attribute()
        self.extent = _Attribute()
        self.face_counts = _Attribute()
        self.face_indices = _Attribute()

    def define(self, stage, path):
        self.define_calls.append((stage, path))
        return self

    def CreatePointsAttr(self):
        return self.points

    def GetPointsAttr(self):
        return self.points

    def CreateExtentAttr(self):
        return self.extent

    def CreateFaceVertexCountsAttr(self):
        return self.face_counts

    def GetFaceVertexCountsAttr(self):
        return self.face_counts

    def CreateFaceVertexIndicesAttr(self):
        return self.face_indices

    def GetFaceVertexIndicesAttr(self):
        return self.face_indices
