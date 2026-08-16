"""Focused plain-data coverage for Stage 09 Package G presentation policy."""

from pathlib import Path

import pytest

from digital_twin_runtime_suite.app.flow.static_source import (
    StaticVelocitySourceDescriptor,
)
from digital_twin_runtime_suite.app.streamlines.presentation import (
    PRESENTATION_LOOP_DURATION_SECONDS,
    PresentationCandidateResult,
    PresentationTickObservation,
    assess_presentation_candidate,
    build_presentation_tick_phases,
    presentation_tick_action,
    refinement_period_seconds,
    resolve_presentation_sample,
)
from digital_twin_runtime_suite.app.streamlines.temporal import (
    StreamlinesGeometrySignature,
    TemporalVelocitySourceDescriptor,
)


def _source(cadence_hz: float) -> TemporalVelocitySourceDescriptor:
    sample_count = int(PRESENTATION_LOOP_DURATION_SECONDS * cadence_hz)
    interval = 1.0 / cadence_hz
    descriptor = StaticVelocitySourceDescriptor(
        workload="Nominal",
        dataset_identity=f"server/{cadence_hz:g}hz",
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
            Path(f"{cadence_hz:g}hz_{index:03}.vti") for index in range(sample_count)
        ),
        sample_time_codes=tuple(
            float(index) * interval * 24.0 for index in range(sample_count)
        ),
        time_codes_per_second=24.0,
        sample_interval_seconds=interval,
    )


def _rebuild_record(
    *,
    candidate_period_seconds: float,
    total_visible_update_ms: float = 2400.0,
    pending_requests_at_start: int = 0,
    start_lateness_ms: float = 0.0,
) -> PresentationTickObservation:
    resolved = resolve_presentation_sample(_source(5.0), 3.0)
    signature = StreamlinesGeometrySignature(
        curve_count=256,
        point_count=51200,
        bounds=((0.0, 0.0, 0.0), (1.0, 1.0, 1.0)),
        point_head=((0.0, 0.0, 0.0),),
        point_tail=((1.0, 1.0, 1.0),),
    )
    return PresentationTickObservation(
        candidate_period_seconds=candidate_period_seconds,
        tick_ordinal=1,
        scheduled_at_seconds=10.0,
        requested_at_seconds=10.0,
        processing_started_at_seconds=10.0 + start_lateness_ms / 1000.0,
        completed_visible_at_seconds=10.0 + total_visible_update_ms / 1000.0,
        resolved_sample=resolved,
        previously_presented_sample_index=resolved.sample_index - 1,
        action="REBUILD",
        pending_presentation_requests_at_request=0,
        pending_presentation_requests_at_start=pending_requests_at_start,
        selected_vti_matches_expected=True,
        fresh_execution=True,
        execution_success=True,
        geometry_replaced=True,
        preview_matches_runtime=True,
        source_transition_ms=20.0,
        operator_rebuild_ms=1200.0,
        usdrt_ready_ms=1400.0,
        preview_update_ms=1000.0,
        total_visible_update_ms=total_visible_update_ms,
        curve_count=256,
        point_count=51200,
        bounds=signature.bounds,
        signature=signature,
    )


def test_time_based_resolver_uses_each_manifest_cadence_without_future_selection():
    two_point_five = resolve_presentation_sample(_source(2.5), 3.1)
    five = resolve_presentation_sample(_source(5.0), 3.1)
    ten = resolve_presentation_sample(_source(10.0), 3.1)

    assert two_point_five.sample_index == 7
    assert two_point_five.source_time_seconds == pytest.approx(2.8)
    assert five.sample_index == 15
    assert five.source_time_seconds == pytest.approx(3.0)
    assert ten.sample_index == 31
    assert ten.source_time_seconds == pytest.approx(3.1)
    assert two_point_five.source_vti == Path("2.5hz_007.vti")
    assert five.source_vti == Path("5hz_015.vti")
    assert ten.source_vti == Path("10hz_031.vti")


def test_resolver_handles_exact_between_and_loop_edge_phases():
    source = _source(5.0)

    assert resolve_presentation_sample(source, 3.0).sample_index == 15
    assert resolve_presentation_sample(source, 3.19).sample_index == 15
    assert resolve_presentation_sample(source, 15.999).sample_index == 79
    assert resolve_presentation_sample(source, 16.0).sample_index == 0
    assert resolve_presentation_sample(source, -0.01).sample_index == 79


def test_presentation_ticks_wrap_by_16_second_loop_phase_not_source_index():
    assert build_presentation_tick_phases(3.0, 7) == (
        0.0,
        3.0,
        6.0,
        9.0,
        12.0,
        15.0,
        2.0,
    )


def test_same_resolved_sample_is_a_no_op_without_consumer_rebuild():
    assert presentation_tick_action(15, 15) == "NO_OP"
    assert presentation_tick_action(16, 15) == "REBUILD"


def test_candidate_requires_guard_band_and_one_refinement_bracket():
    insufficient_headroom = assess_presentation_candidate(
        2.6,
        (
            _rebuild_record(
                candidate_period_seconds=2.6, total_visible_update_ms=2400.0
            ),
        ),
    )
    viable = assess_presentation_candidate(
        3.0,
        (
            _rebuild_record(
                candidate_period_seconds=3.0, total_visible_update_ms=2400.0
            ),
        ),
    )

    assert insufficient_headroom.reason == "INSUFFICIENT_HEADROOM"
    assert viable.viable
    assert refinement_period_seconds(2.8, 3.0) == 2.9


def test_candidate_rejects_only_a_real_pending_presentation_request():
    backlog = assess_presentation_candidate(
        3.0,
        (
            _rebuild_record(
                candidate_period_seconds=3.0,
                pending_requests_at_start=1,
            ),
        ),
    )

    assert backlog.reason == "PRESENTATION_BACKLOG"
    assert backlog.max_pending_presentation_requests == 1


def test_isolated_scheduler_jitter_is_not_reported_as_lateness_drift():
    observations = (
        _rebuild_record(candidate_period_seconds=3.0, start_lateness_ms=0.0),
        _rebuild_record(candidate_period_seconds=3.0, start_lateness_ms=9.0),
        _rebuild_record(candidate_period_seconds=3.0, start_lateness_ms=0.0),
    )

    assessment = assess_presentation_candidate(3.0, observations)

    assert assessment.scheduling_lateness_drift == "NONE"


def test_candidate_history_distinguishes_screen_from_sustained_confirmation():
    screen = assess_presentation_candidate(
        2.6,
        (
            _rebuild_record(
                candidate_period_seconds=2.6, total_visible_update_ms=2000.0
            ),
        ),
    )
    final = assess_presentation_candidate(
        2.6,
        (
            _rebuild_record(
                candidate_period_seconds=2.6, total_visible_update_ms=2400.0
            ),
        ),
    )

    result = PresentationCandidateResult(screen, final_confirmation=final)

    assert screen.viable
    assert not final.viable
    assert result.state == "FINAL_REJECTED"
    assert result.reason == "INSUFFICIENT_HEADROOM"
