# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
import pytest

from digital_twin_runtime_suite.app.config import (
    EMITTER_LAYOUT_VALUE_OPTIONS,
    EmitterLayoutConfig,
)
from digital_twin_runtime_suite.app.flow.smoke import (
    derive_emitter_layout,
    inset_emitter_layout_panel_bounds,
)

FLOW_BOUNDS = ((0.0, 0.0, 0.0), (10.0, 10.0, 10.0))
INTAKE_BOUNDS = ((1.0, 1.0, 0.0), (9.0, 9.0, 10.0))


def _derive(**changes):
    return derive_emitter_layout(
        EmitterLayoutConfig(**changes),
        flow_world_bounds=FLOW_BOUNDS,
        intake_world_bounds=INTAKE_BOUNDS,
        component_front_z=2.0,
        minimum_radius=0.1,
        front_inward_offset=0.1,
    )


def test_emitter_layout_dropdowns_preserve_even_and_odd_counts():
    assert EMITTER_LAYOUT_VALUE_OPTIONS["emitters_per_row"] == (5, 6, 7, 8, 9, 10)
    assert EMITTER_LAYOUT_VALUE_OPTIONS["rows"] == (1, 2, 3, 4, 5)
    assert EMITTER_LAYOUT_VALUE_OPTIONS["horizontal_margin"] == (0.02, 0.04, 0.08, 0.1)
    assert EMITTER_LAYOUT_VALUE_OPTIONS["vertical_margin"] == (0.02, 0.04, 0.08, 0.1)


def test_odd_grid_has_a_central_emitter_and_even_grid_centers_between_emitters():
    odd = _derive(emitters_per_row=9, rows=3)
    assert (5.0, 5.0, odd.depth_world_plane) in odd.positions

    even = _derive(emitters_per_row=8, rows=4)
    assert not any(
        x == pytest.approx(5.0) and y == pytest.approx(5.0)
        for x, y, _ in even.positions
    )
    x_positions = sorted({x for x, _, _ in even.positions})
    y_positions = sorted({y for _, y, _ in even.positions})
    assert x_positions[3] < 5.0 < x_positions[4]
    assert y_positions[1] < 5.0 < y_positions[2]


def test_emitter_layout_count_depth_and_flow_bounds():
    for depth in EMITTER_LAYOUT_VALUE_OPTIONS["depth"]:
        derived = _derive(emitters_per_row=10, rows=5, depth=depth)
        assert len(derived.positions) == 50
        assert derived.depth_world_plane == pytest.approx(
            derived.deep_world_plane
            + depth * (derived.front_world_plane - derived.deep_world_plane)
        )
        for position in derived.positions:
            assert all(
                FLOW_BOUNDS[0][axis] <= position[axis] - derived.radius
                and position[axis] + derived.radius <= FLOW_BOUNDS[1][axis]
                for axis in range(3)
            )


def test_emitter_size_respects_voxel_minimum_and_spacing_limited_maximum():
    minimum = _derive(size=0.0)
    sparse = _derive(emitters_per_row=5, rows=1, size=1.0)
    dense = _derive(emitters_per_row=10, rows=5, size=1.0)

    assert minimum.radius == pytest.approx(0.1)
    assert minimum.minimum_radius == pytest.approx(0.1)
    assert dense.maximum_radius < sparse.maximum_radius
    assert dense.radius == pytest.approx(dense.maximum_radius)
    x_positions = sorted({x for x, _, _ in dense.positions})
    y_positions = sorted({y for _, y, _ in dense.positions})
    assert (
        min(right - left for left, right in zip(x_positions, x_positions[1:]))
        >= 2 * dense.radius
    )
    assert (
        min(upper - lower for lower, upper in zip(y_positions, y_positions[1:]))
        >= 2 * dense.radius
    )


def test_emitter_surfaces_cover_the_layout_envelope_without_exceeding_it():
    derived = _derive(emitters_per_row=7, rows=4, size=1.0)
    x_positions = sorted({x for x, _, _ in derived.positions})
    y_positions = sorted({y for _, y, _ in derived.positions})

    assert x_positions[0] - derived.radius == pytest.approx(INTAKE_BOUNDS[0][0])
    assert x_positions[-1] + derived.radius == pytest.approx(INTAKE_BOUNDS[1][0])
    assert y_positions[0] - derived.radius == pytest.approx(INTAKE_BOUNDS[0][1])
    assert y_positions[-1] + derived.radius == pytest.approx(INTAKE_BOUNDS[1][1])


def test_emitter_layout_margins_inset_each_panel_side_and_bound_maximum_spheres():
    panel_bounds = ((0.0, 0.0, 0.0), (10.0, 10.0, 10.0))
    margin_bounds = inset_emitter_layout_panel_bounds(
        panel_bounds,
        horizontal_margin=0.04,
        vertical_margin=0.02,
        minimum_inset=0.0,
    )
    derived = derive_emitter_layout(
        EmitterLayoutConfig(emitters_per_row=7, rows=4, size=1.0),
        flow_world_bounds=FLOW_BOUNDS,
        intake_world_bounds=margin_bounds,
        component_front_z=2.0,
        minimum_radius=0.1,
        front_inward_offset=0.1,
    )
    x_positions = sorted({x for x, _, _ in derived.positions})
    y_positions = sorted({y for _, y, _ in derived.positions})

    assert margin_bounds[0][:2] == pytest.approx((0.4, 0.2))
    assert margin_bounds[1][:2] == pytest.approx((9.6, 9.8))
    assert x_positions[0] - derived.radius == pytest.approx(0.4)
    assert x_positions[-1] + derived.radius == pytest.approx(9.6)
    assert y_positions[0] - derived.radius == pytest.approx(0.2)
    assert y_positions[-1] + derived.radius == pytest.approx(9.8)
