"""Focused plain-data coverage for the Stage 09 Package F cadence experiment."""

from pathlib import Path

from digital_twin_runtime_suite.app.flow.static_source import (
    StaticVelocitySourceDescriptor,
)
from digital_twin_runtime_suite.app.streamlines.cadence import (
    CadenceBoundaryObservation,
    build_cadence_feasibility_plan,
    build_cadence_performance_evidence,
    classify_cadence_feasibility,
    recovery_time_to_baseline_seconds,
)
from digital_twin_runtime_suite.app.streamlines.temporal import (
    StreamlinesGeometrySignature,
    TemporalVelocitySourceDescriptor,
)


def _source(sample_count: int = 80) -> TemporalVelocitySourceDescriptor:
    descriptor = StaticVelocitySourceDescriptor(
        workload="Nominal",
        dataset_identity="server/load_normal",
        sample_index=0,
        vti_path=Path("sample_000.vti"),
        dataset_prim_path="/DTRS_HoudiniVelocity/VTKImageData",
        velocity_field_prim_path="/DTRS_HoudiniVelocity/PointData/vel",
        world_bounds=((0.0, 0.0, 0.0), (1.0, 1.0, 1.0)),
        dimensions=(2, 2, 2),
        spacing=(1.0, 1.0, 1.0),
        origin=(0.0, 0.0, 0.0),
        source_origin=(0.0, 0.0, 0.0),
        stage_meters_per_unit=1.0,
    )
    return TemporalVelocitySourceDescriptor(
        static_descriptor=descriptor,
        velocity_paths=tuple(
            Path(f"sample_{index:03}.vti") for index in range(sample_count)
        ),
        sample_time_codes=tuple(float(index) * 4.8 for index in range(sample_count)),
        time_codes_per_second=24.0,
        sample_interval_seconds=0.2,
    )


def _record(
    *, total_ms: float = 180.0, queue_depth: int = 0
) -> CadenceBoundaryObservation:
    sample = build_cadence_feasibility_plan(_source()).burst_samples[0]
    signature = StreamlinesGeometrySignature(
        curve_count=256,
        point_count=51200,
        bounds=((0.0, 0.0, 0.0), (1.0, 1.0, 1.0)),
        point_head=((0.0, 0.0, 0.0),),
        point_tail=((1.0, 1.0, 1.0),),
    )
    return CadenceBoundaryObservation(
        scenario="5hz_burst",
        sample=sample,
        requested_at_seconds=1.0,
        processing_started_at_seconds=1.0,
        completed_visible_at_seconds=1.0 + total_ms / 1000.0,
        source_transition_ms=10.0,
        operator_rebuild_ms=100.0,
        usdrt_ready_ms=120.0,
        preview_update_ms=60.0,
        total_visible_update_ms=total_ms,
        begin_count_before=0,
        begin_count_after=1,
        completion_count_before=0,
        completion_count_after=1,
        fresh_execution=True,
        execution_success=True,
        curve_count=256,
        point_count=51200,
        bounds=signature.bounds,
        geometry_replaced=True,
        preview_matches_runtime=True,
        signature=signature,
        scheduled_at_seconds=1.0,
        queue_depth_at_request=queue_depth,
        queue_depth_at_start=queue_depth,
    )


def test_cadence_plan_derives_all_windows_from_manifest_time_mapping():
    plan = build_cadence_feasibility_plan(_source())

    assert plan.source_period_ms == 200.0
    assert tuple(sample.sample_index for sample in plan.sequential_samples) == (
        20,
        21,
        22,
        23,
        24,
    )
    assert tuple(sample.sample_index for sample in plan.repeated_samples) == (
        20,
        20,
    )
    assert tuple(sample.sample_index for sample in plan.loop_boundary_samples) == (
        78,
        79,
        0,
        1,
    )
    assert tuple(sample.sample_index for sample in plan.burst_samples) == tuple(
        range(20, 30)
    )
    assert plan.burst_samples[2].source_vti == Path("sample_022.vti")
    assert plan.burst_samples[2].time_code == 105.6


def test_cadence_classification_distinguishes_viable_backlogged_and_unstable_runs():
    viable = classify_cadence_feasibility(
        source_period_ms=200.0,
        burst_records=(_record(total_ms=180.0),),
        requested_samples=1,
    )
    backlogged = classify_cadence_feasibility(
        source_period_ms=200.0,
        burst_records=(_record(total_ms=220.0, queue_depth=1),),
        requested_samples=1,
    )
    incomplete = classify_cadence_feasibility(
        source_period_ms=200.0,
        burst_records=(),
        requested_samples=1,
    )

    assert viable.value == "A"
    assert backlogged.value == "B"
    assert incomplete.value == "C"


class _Sample:
    def __init__(self, captured_at, fps, gpu_memory, process_memory) -> None:
        self.captured_at = captured_at
        self.fps = fps
        self.gpu_memory_used_gib = gpu_memory
        self.process_memory_used_gib = process_memory


def test_recovery_indicator_uses_raw_flow_style_hud_snapshots_without_threshold_claim():
    baseline = build_cadence_performance_evidence(
        (_Sample(10.0, 50.0, 4.0, 5.0), _Sample(11.0, 48.0, 4.0, 5.0))
    )
    recovery = build_cadence_performance_evidence(
        (_Sample(20.0, 30.0, 4.1, 5.1), _Sample(22.0, 45.0, 4.0, 5.0))
    )

    assert baseline.fps_median == 49.0
    assert (
        recovery_time_to_baseline_seconds(
            baseline,
            recovery,
            recovery_started_at_seconds=19.0,
        )
        == 3.0
    )
