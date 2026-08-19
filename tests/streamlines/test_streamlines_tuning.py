"""Focused contracts for the transient Phase 4.4A tuning harness."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from digital_twin_runtime_suite.app.flow.static_source import (
    StaticVelocitySourceDescriptor,
)
from digital_twin_runtime_suite.app.streamlines.cache_runtime import (
    StreamlinesCacheRuntimeMixin,
    StreamlinesProfilePreviewResult,
)
from digital_twin_runtime_suite.app.streamlines.profile import (
    PRODUCTION_STREAMLINES_PROFILE,
)
from digital_twin_runtime_suite.app.streamlines.proof import (
    build_streamlines_preview_operator_request,
)
from digital_twin_runtime_suite.app.streamlines.seed_layout import (
    derive_front_intake_seed_layout,
)
from digital_twin_runtime_suite.app.streamlines.tuning import (
    MAX_STEPS_OPTIONS,
    PHASE44A_STREAMLINES_CANDIDATE,
    PREVIEW_WORKLOAD_OPTIONS,
    STEP_SCALE_LABELS,
    STEP_SCALE_OPTIONS,
    StreamlinesGeometryTuning,
    StreamlinesTuningEvidence,
    calculate_streamlines_geometry_metrics,
    format_streamlines_tuning_complete,
    source_cell_diagonal_m,
    streamlines_preview_workload_from_index,
    streamlines_tuning_from_indices,
)


def test_tuning_dropdown_options_map_to_exact_values() -> None:
    assert MAX_STEPS_OPTIONS == (200, 400, 800, 1600)
    assert STEP_SCALE_OPTIONS == (0.25, 0.5, 1.0, 2.0)
    assert STEP_SCALE_LABELS == ("0.25x", "0.5x", "1.0x", "2.0x")
    assert PREVIEW_WORKLOAD_OPTIONS == ("Idle", "Nominal", "Surge", "Critical")
    assert streamlines_tuning_from_indices(2, 3) == (
        StreamlinesGeometryTuning(max_steps=800, step_scale=2.0)
    )
    assert (
        tuple(streamlines_preview_workload_from_index(index) for index in range(4))
        == PREVIEW_WORKLOAD_OPTIONS
    )


@pytest.mark.parametrize("scale", STEP_SCALE_OPTIONS)
def test_step_scale_preserves_profile_ratios_without_mutating_profile(
    scale: float,
) -> None:
    profile_before = PRODUCTION_STREAMLINES_PROFILE
    descriptor = _descriptor()
    layout = derive_front_intake_seed_layout(
        descriptor.world_bounds,
        front_intake_z=9.0,
        max_cell_spacing=max(descriptor.spacing),
    )
    request = build_streamlines_preview_operator_request(
        descriptor,
        layout,
        tuning=StreamlinesGeometryTuning(800, scale),
    )
    assert request.min_step_size == pytest.approx(0.01 * scale)
    assert request.initial_step_size == pytest.approx(0.2 * scale)
    assert request.max_step_size == pytest.approx(0.5 * scale)
    assert request.initial_step_size / request.min_step_size == 20.0
    assert request.max_step_size / request.initial_step_size == 2.5
    assert request.max_steps == 800
    assert PRODUCTION_STREAMLINES_PROFILE is profile_before
    assert PRODUCTION_STREAMLINES_PROFILE.max_steps == 200


@pytest.mark.parametrize(
    ("scale", "expected"),
    (
        (0.25, (0.0025, 0.05, 0.125)),
        (0.5, (0.005, 0.1, 0.25)),
        (1.0, (0.01, 0.2, 0.5)),
        (2.0, (0.02, 0.4, 1.0)),
    ),
)
def test_step_presets_author_exact_cell_relative_values(
    scale: float,
    expected: tuple[float, float, float],
) -> None:
    descriptor = _descriptor()
    layout = _layout(descriptor)

    request = build_streamlines_preview_operator_request(
        descriptor,
        layout,
        tuning=StreamlinesGeometryTuning(200, scale),
    )

    assert (
        request.min_step_size,
        request.initial_step_size,
        request.max_step_size,
    ) == pytest.approx(expected)


def test_vti_spacing_does_not_change_authored_step_values() -> None:
    first = _descriptor()
    second = replace(first, spacing=(0.5, 0.75, 1.0))

    first_request = build_streamlines_preview_operator_request(
        first,
        _layout(first),
        tuning=StreamlinesGeometryTuning(200, 1.0),
    )
    second_request = build_streamlines_preview_operator_request(
        second,
        _layout(second),
        tuning=StreamlinesGeometryTuning(200, 1.0),
    )

    assert first_request.min_step_size == second_request.min_step_size == 0.01
    assert first_request.initial_step_size == second_request.initial_step_size == 0.2
    assert first_request.max_step_size == second_request.max_step_size == 0.5


def test_step_correction_changes_the_cache_settings_signature() -> None:
    corrected = PRODUCTION_STREAMLINES_PROFILE
    legacy = replace(
        corrected,
        name="dtrs_standard_streamlines_v2",
        min_step_cell_multiplier=0.5,
        initial_step_cell_multiplier=2.0,
        max_step_cell_multiplier=4.0,
    )

    assert corrected.settings_signature != legacy.settings_signature


def test_seed_layout_contract_remains_16_by_8_with_128_points() -> None:
    layout = _layout(_descriptor())

    assert (layout.columns, layout.rows, layout.seed_count) == (16, 8, 128)


def test_phase44a_candidate_is_200_steps_at_two_x() -> None:
    descriptor = _descriptor()
    request = build_streamlines_preview_operator_request(
        descriptor,
        _layout(descriptor),
        tuning=PHASE44A_STREAMLINES_CANDIDATE,
    )

    assert request.max_steps == 200
    assert request.min_step_size == 0.02
    assert request.initial_step_size == 0.4
    assert request.max_step_size == 1.0


def test_quarter_scale_receipt_identity_is_exact() -> None:
    assert StreamlinesGeometryTuning(200, 0.25).step_scale_label == "0.25x"


def test_geometry_metrics_are_deterministic_and_use_negative_z_as_rearward() -> None:
    points = (
        (0.0, 0.0, 9.0),
        (0.0, 0.0, 5.0),
        (0.0, 0.0, 2.0),
        (0.0, 0.0, 9.0),
        (10.0, 0.0, 8.0),
    )
    metrics = calculate_streamlines_geometry_metrics(
        points,
        (3, 2),
        ((-20.0, -10.0, 0.0), (20.0, 10.0, 10.0)),
    )

    assert metrics.points_per_curve_min == 2
    assert metrics.points_per_curve_median == 2.5
    assert metrics.points_per_curve_max == 3
    assert metrics.arc_length_median == pytest.approx((7.0 + 10.05) / 2.0, 0.01)
    assert metrics.arc_length_max == pytest.approx(10.05, 0.01)
    assert metrics.rearward_reach_median == 4.0
    assert metrics.curves_reaching_75pct_domain_depth == 1
    assert metrics.curves_reaching_90pct_domain_depth == 0


def test_unavailable_max_step_metric_is_reported_explicitly() -> None:
    metrics = calculate_streamlines_geometry_metrics(
        ((0.0, 0.0, 9.0), (0.0, 0.0, 8.0)),
        (2,),
        ((-1.0, -1.0, 0.0), (1.0, 1.0, 10.0)),
    )
    evidence = StreamlinesTuningEvidence(
        workload="Nominal",
        dataset_identity="server/load_normal",
        sample_index=0,
        source_vti="nominal.vti",
        seed_columns=16,
        seed_rows=8,
        seed_points=128,
        selection=PHASE44A_STREAMLINES_CANDIDATE,
        authored_min_step=0.02,
        authored_initial_step=0.4,
        authored_max_step=1.0,
        source_cell_diagonal_m=0.25,
        metrics=metrics,
        operator_execution_ms=10.0,
        preview_total_ms=12.0,
        viewport_fps=None,
        gpu_used_gib=None,
        process_used_gib=None,
    )

    receipt = format_streamlines_tuning_complete(evidence)
    quarter_receipt = format_streamlines_tuning_complete(
        replace(
            evidence,
            selection=StreamlinesGeometryTuning(200, 0.25),
            authored_min_step=0.0025,
            authored_initial_step=0.05,
            authored_max_step=0.125,
        )
    )

    assert "curves_hitting_max_steps=unavailable" in receipt
    assert "PROFILE_CANDIDATE | COMPLETE" in receipt
    assert "viewport_fps=unavailable" in receipt
    assert "authored_cell_relative:" in receipt
    assert "source_cell_diagonal_m=0.25" in receipt
    assert "  min=0.005" in receipt
    assert "  initial=0.1" in receipt
    assert "  max=0.25" in receipt
    assert "not measured displacement" in receipt
    assert "step_scale=0.25x" in quarter_receipt
    assert "step_scale=0.2x" not in quarter_receipt
    assert evidence.approximate_min_step_m == pytest.approx(0.005)
    assert evidence.approximate_initial_step_m == pytest.approx(0.1)
    assert evidence.approximate_max_step_m == pytest.approx(0.25)


def test_physical_step_diagnostics_apply_cell_diagonal_exactly_once() -> None:
    spacing = (0.25, 0.5, 0.75)
    diagonal = source_cell_diagonal_m(
        spacing,
        stage_meters_per_unit=1.0,
    )

    assert diagonal == pytest.approx(sum(value * value for value in spacing) ** 0.5)


def test_profile_preview_contract_never_builds_or_rebuilds_cache() -> None:
    result = StreamlinesProfilePreviewResult(
        workload="Nominal",
        dataset_identity="server/load_normal",
        sample_index=0,
        source_vti="nominal.vti",
        curve_count=128,
        point_count=256,
        generation_ms=1.0,
        seed_type="point_grid",
        seed_columns=16,
        seed_rows=8,
        seed_points=128,
        horizontal_spacing=1.0,
        vertical_spacing=1.0,
        edge_margin_x=1.0,
        edge_margin_y=1.0,
        seed_plane_z=9.0,
        operator_type="standard",
    )

    assert result.cache_build_count == 0
    assert result.cache_rebuild_count == 0


def test_each_preview_run_cleans_previous_disposable_runtime() -> None:
    runtime = _CleanupRuntime()

    asyncio.run(runtime._clear_previous_streamlines_profile_preview_in_kit())
    asyncio.run(runtime._clear_previous_streamlines_profile_preview_in_kit())

    assert runtime.cleanup_calls == 2


class _CleanupRuntime(StreamlinesCacheRuntimeMixin):
    def __init__(self) -> None:
        self.cleanup_calls = 0

    async def clear_streamlines_static_runtime_in_kit(self):
        self.cleanup_calls += 1
        return SimpleNamespace(clean=True)


def _descriptor() -> StaticVelocitySourceDescriptor:
    bounds = ((-17.0, -9.0, -10.0), (17.0, 9.0, 10.0))
    return StaticVelocitySourceDescriptor(
        workload="Nominal",
        dataset_identity="server/load_normal",
        sample_index=0,
        vti_path=Path("nominal.vti"),
        dataset_prim_path="/DTRS_HoudiniVelocity/VTKImageData",
        velocity_field_prim_path="/DTRS_HoudiniVelocity/PointData/vel",
        world_bounds=bounds,
        dimensions=(2, 2, 2),
        spacing=(0.25, 0.25, 0.25),
        origin=bounds[0],
        source_origin=bounds[0],
        stage_meters_per_unit=1.0,
    )


def _layout(descriptor: StaticVelocitySourceDescriptor):
    return derive_front_intake_seed_layout(
        descriptor.world_bounds,
        front_intake_z=9.0,
        max_cell_spacing=max(descriptor.spacing),
    )
