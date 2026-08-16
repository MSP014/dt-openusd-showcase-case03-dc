"""Focused Stage 09 Package C contracts for fixed-input operator selection."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from digital_twin_runtime_suite.app.flow.static_source import (
    StaticVelocitySourceDescriptor,
)
from digital_twin_runtime_suite.app.streamlines.comparison import (
    COMPARISON_SHARED_SEED_PATH,
    MEASURED_RUN_COUNT,
    NANOVDB_MAX_RESOLUTION,
    PACKAGE_C_STEADY_SNAPSHOT_COUNT,
    StreamlinesOperatorExecutionReceipt,
    StreamlinesOperatorTypeBenchmarkSample,
    StreamlinesOperatorTypeComparisonCaseResult,
    StreamlinesOperatorTypeComparisonResult,
    build_streamlines_operator_type_comparison_cases,
    build_streamlines_steady_performance_evidence,
    calculate_nanovdb_effective_grid,
    comparison_cases_share_non_type_inputs,
    format_streamlines_operator_type_comparison,
)
from digital_twin_runtime_suite.app.streamlines.runtime import (
    format_streamlines_visual_review,
    streamlines_review_workflow_state,
)


def test_package_c_changes_only_the_streamlines_operator_type():
    cases = build_streamlines_operator_type_comparison_cases(_descriptor())

    standard, nanovdb = cases
    assert tuple(case.operator_type for case in cases) == (
        "standard",
        "nanovdb",
    )
    assert (
        standard.request.seed_path
        == nanovdb.request.seed_path
        == COMPARISON_SHARED_SEED_PATH
    )
    assert standard.request.dataset_prim_path == nanovdb.request.dataset_prim_path
    assert (
        standard.request.velocity_field_prim_path
        == nanovdb.request.velocity_field_prim_path
    )
    assert standard.request.seed_center == nanovdb.request.seed_center
    assert standard.request.seed_radius == nanovdb.request.seed_radius
    assert standard.request.direction == nanovdb.request.direction
    assert standard.request.min_step_size == nanovdb.request.min_step_size
    assert standard.request.initial_step_size == nanovdb.request.initial_step_size
    assert standard.request.max_step_size == nanovdb.request.max_step_size
    assert standard.request.max_steps == nanovdb.request.max_steps
    assert standard.request.width == nanovdb.request.width
    assert comparison_cases_share_non_type_inputs(cases)


def test_package_c_rejects_a_changed_non_type_input():
    cases = build_streamlines_operator_type_comparison_cases(_descriptor())
    altered_nanovdb = replace(
        cases[1],
        request=replace(cases[1].request, width=cases[1].request.width * 2.0),
    )

    assert not comparison_cases_share_non_type_inputs((cases[0], altered_nanovdb))


def test_package_c_table_uses_three_run_medians_and_never_invents_nanovdb_timing():
    descriptor = _descriptor()
    cases = build_streamlines_operator_type_comparison_cases(descriptor)
    result = StreamlinesOperatorTypeComparisonResult(
        standard=_case_result("standard", cases[0], (10.0, 30.0, 20.0)),
        nanovdb=_case_result("nanovdb", cases[1], (40.0, 60.0, 50.0)),
        identical_non_type_inputs=True,
        previous_comparison_cleanup_success=True,
        active_review_type="standard",
    )

    report = format_streamlines_operator_type_comparison(descriptor, cases, result)

    assert MEASURED_RUN_COUNT == 3
    assert "operator_rebuild_ms median     20.0 ms" in report
    assert "50.0 ms" in report
    assert "nanovdb_voxelization_ms" in report
    assert "NOT_SEPARATELY_OBSERVABLE" in report
    assert "nanovdb_effective_grid=" in report
    assert "execution_receipts:" in report
    assert "measured_1[" in report
    assert "steady_performance:" in report
    assert "fps_snapshots=" in report
    assert "production_selection=DEFERRED" in report


def test_package_c_nanovdb_grid_is_not_coarser_than_the_static_vti():
    descriptor = _descriptor()

    grid = calculate_nanovdb_effective_grid(
        descriptor.world_bounds,
        descriptor.spacing,
    )

    assert grid.max_resolution == NANOVDB_MAX_RESOLUTION == 256
    assert max(grid.dimensions) <= NANOVDB_MAX_RESOLUTION
    assert grid.voxel_size_m <= max(descriptor.spacing)
    assert grid.preserves_source_fidelity


def test_package_c_accepts_only_a_causally_fresh_successful_completion():
    accepted = StreamlinesOperatorExecutionReceipt(
        begin_count_before=3,
        begin_count_after=4,
        completion_count_before=3,
        completion_count_after=4,
        completion_begin_count=4,
        completion_success=True,
    )
    stale_end = replace(accepted, completion_begin_count=3)
    failed_end = replace(accepted, completion_success=False)

    assert accepted.fresh_execution and accepted.accepted
    assert not stale_end.fresh_execution and not stale_end.accepted
    assert failed_end.fresh_execution and not failed_end.accepted


def test_package_c_steady_performance_uses_five_independent_hud_snapshots():
    samples = (
        _ViewportSample(58.0, 4.0, 5.9),
        _ViewportSample(60.0, 4.1, 6.0),
        _ViewportSample(59.0, 4.0, 5.8),
        _ViewportSample(61.0, 4.1, 5.9),
        _ViewportSample(57.0, 4.0, 5.8),
    )

    evidence = build_streamlines_steady_performance_evidence(samples)

    assert evidence.sample_count == PACKAGE_C_STEADY_SNAPSHOT_COUNT == 5
    assert evidence.fps_snapshots == (58.0, 60.0, 59.0, 61.0, 57.0)
    assert evidence.fps_median == 59.0
    assert evidence.fps_min == 57.0
    assert evidence.fps_max == 61.0
    assert evidence.gpu_memory_snapshots == (4.0, 4.1, 4.0, 4.1, 4.0)
    assert evidence.process_memory_snapshots == (5.9, 6.0, 5.8, 5.9, 5.8)
    assert evidence.has_complete_fps_series


def test_package_c_steady_performance_rejects_an_incomplete_fps_series():
    evidence = build_streamlines_steady_performance_evidence(
        tuple(_ViewportSample(None, 4.0, 5.9) for _ in range(5))
    )

    assert not evidence.has_complete_fps_series


def test_package_c_review_workflow_enforces_static_benchmark_then_ab_order():
    startup = streamlines_review_workflow_state("STARTUP")
    static_pass = streamlines_review_workflow_state("STATIC_PASS")
    benchmark_pass = streamlines_review_workflow_state("BENCHMARK_PASS")
    standard_active = streamlines_review_workflow_state("STANDARD_ACTIVE")

    assert startup == type(startup)(True, False, False, False)
    assert static_pass == type(static_pass)(True, True, False, False)
    assert benchmark_pass == type(benchmark_pass)(True, True, True, False)
    assert standard_active == type(standard_active)(True, True, True, True)


def test_package_c_visual_review_log_names_evidence_and_next_action():
    descriptor = _descriptor()
    cases = build_streamlines_operator_type_comparison_cases(descriptor)
    comparison = StreamlinesOperatorTypeComparisonResult(
        standard=_case_result("standard", cases[0], (10.0, 20.0, 30.0)),
        nanovdb=_case_result("nanovdb", cases[1], (40.0, 50.0, 60.0)),
        identical_non_type_inputs=True,
        previous_comparison_cleanup_success=True,
        active_review_type="none",
    )

    standard_log = format_streamlines_visual_review(comparison, "standard")
    nanovdb_log = format_streamlines_visual_review(comparison, "nanovdb")

    assert "VISUAL_REVIEW | STANDARD | ACTIVE" in standard_log
    assert "curves=256" in standard_log
    assert 'NEXT_ACTION | Inspect viewport, then press "Show NanoVDB"' in standard_log
    assert "VISUAL_REVIEW | NANOVDB | ACTIVE" in nanovdb_log
    assert (
        "VISUAL_REVIEW | COMPLETE | No further application action is required."
        in nanovdb_log
    )


def _case_result(operator_type, case, rebuild_ms):
    samples = tuple(
        StreamlinesOperatorTypeBenchmarkSample(
            operator_creation_ms=1.0,
            operator_rebuild_ms=value,
            preview_mirror_ms=2.0,
            total_visible_update_ms=value + 2.0,
            runtime_curve_count=256,
            runtime_point_count=51200,
            points_per_curve_min_mean_max=(200, 200, 200),
            runtime_bounds=((-0.01, 0.07, 0.01), (0.01, 0.10, 0.04)),
            bounds_within_source=True,
            execution_receipt=_accepted_receipt(),
        )
        for value in rebuild_ms
    )
    return StreamlinesOperatorTypeComparisonCaseResult(
        operator_type=operator_type,
        operator_path=case.request.operator_path,
        preview_path=case.preview_path,
        creation_duration_ms=1.0,
        warmup_rebuild_ms=1.0,
        warmup_succeeded=True,
        warmup_receipt=_accepted_receipt(),
        measured_samples=samples,
        steady_performance=build_streamlines_steady_performance_evidence(
            tuple(_ViewportSample(60.0, 4.0, 5.9) for _ in range(5))
        ),
        source_binding=(case.request.dataset_prim_path,),
        seed_binding=(case.request.seed_path,),
        velocity_binding=(case.request.velocity_field_prim_path,),
        integration_settings=(),
        source_processing_mode=(
            "subset" if operator_type == "standard" else "voxelized"
        ),
        nanovdb_voxelization_ms=None,
        voxelization_settings=(),
        nanovdb_effective_grid=(
            calculate_nanovdb_effective_grid(
                _descriptor().world_bounds,
                _descriptor().spacing,
            )
            if operator_type == "nanovdb"
            else None
        ),
        warnings_errors="NONE_OBSERVED_BY_DTRS",
        passed=True,
    )


def _descriptor() -> StaticVelocitySourceDescriptor:
    return StaticVelocitySourceDescriptor(
        workload="Nominal",
        dataset_identity="server/load_normal",
        sample_index=0,
        vti_path=Path("server_airflow_velocity_normal_1001.vti"),
        dataset_prim_path="/DTRS_HoudiniVelocity/VTKImageData",
        velocity_field_prim_path="/DTRS_HoudiniVelocity/PointData/vel",
        world_bounds=((-0.2, 0.0, -0.5), (0.2, 0.2, 0.1)),
        dimensions=(184, 72, 232),
        spacing=(0.005, 0.005, 0.005),
        origin=(-0.2, 0.0, -0.5),
        source_origin=(-0.2, 0.0, -0.5),
        stage_meters_per_unit=1.0,
    )


def _accepted_receipt() -> StreamlinesOperatorExecutionReceipt:
    return StreamlinesOperatorExecutionReceipt(
        begin_count_before=0,
        begin_count_after=1,
        completion_count_before=0,
        completion_count_after=1,
        completion_begin_count=1,
        completion_success=True,
    )


class _ViewportSample:
    """Minimal Flow-HUD-shaped data for Package C's pure snapshot contract."""

    def __init__(
        self,
        fps,
        gpu_memory_used_gib,
        process_memory_used_gib,
    ) -> None:
        self.fps = fps
        self.gpu_memory_used_gib = gpu_memory_used_gib
        self.process_memory_used_gib = process_memory_used_gib
