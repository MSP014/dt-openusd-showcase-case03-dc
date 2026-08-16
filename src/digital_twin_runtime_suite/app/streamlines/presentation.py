"""Plain Package G contracts for time-based Streamlines presentation policy.

The Kit-facing runtime owns temporal selection and the explicit Streamlines
consumer rebuild. This module only maps a 16-second presentation-loop phase to
an exact manifest source and assesses scheduler evidence without assuming a
particular workload's source cadence or sample count.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from statistics import median

from digital_twin_runtime_suite.app.streamlines.temporal import (
    StreamlinesGeometrySignature,
    TemporalVelocitySourceDescriptor,
)

PRESENTATION_LOOP_DURATION_SECONDS = 16.0
PRESENTATION_SCREENING_TICK_COUNT = 6
PRESENTATION_FINAL_CONFIRMATION_TICK_COUNT = 12
PRESENTATION_COARSE_PERIODS_SECONDS = (2.6, 2.8, 3.0, 3.2, 3.4, 3.6)
PRESENTATION_MIN_HEADROOM_FLOOR_MS = 250.0
PRESENTATION_HEADROOM_FRACTION = 0.10
PRESENTATION_OPERATOR_PATH = "/DTRS_KitCAE/Streamlines/PresentationCadence"
PRESENTATION_RUNTIME_PREVIEW_PATH = (
    "/DTRS_KitCAE/Streamlines/PresentationCadenceRuntimePreview"
)
PRESENTATION_SEED_PATH = "/DTRS_KitCAE/StreamlineSeeds/PresentationCadenceSphere"


@dataclass(frozen=True)
class PresentationResolvedSample:
    """One exact real manifest sample selected for a presentation-loop phase."""

    presentation_phase_seconds: float
    sample_index: int
    source_vti: Path
    source_time_seconds: float
    time_code: float


@dataclass(frozen=True)
class PresentationTickObservation:
    """One scheduled presentation tick, including its no-op or rebuild result."""

    candidate_period_seconds: float
    tick_ordinal: int
    scheduled_at_seconds: float
    requested_at_seconds: float
    processing_started_at_seconds: float
    completed_visible_at_seconds: float
    resolved_sample: PresentationResolvedSample
    previously_presented_sample_index: int | None
    action: str
    pending_presentation_requests_at_request: int
    pending_presentation_requests_at_start: int
    selected_vti_matches_expected: bool
    fresh_execution: bool | None
    execution_success: bool | None
    geometry_replaced: bool | None
    preview_matches_runtime: bool | None
    source_transition_ms: float | None
    operator_rebuild_ms: float | None
    usdrt_ready_ms: float | None
    preview_update_ms: float | None
    total_visible_update_ms: float | None
    curve_count: int | None
    point_count: int | None
    bounds: tuple[tuple[float, float, float], tuple[float, float, float]] | None
    signature: StreamlinesGeometrySignature | None

    @property
    def start_lateness_ms(self) -> float:
        """Return scheduling lateness before serial consumer work begins."""

        return max(
            0.0,
            (self.processing_started_at_seconds - self.scheduled_at_seconds) * 1000.0,
        )

    @property
    def completion_deadline_lateness_ms(self) -> float:
        """Return late completion against this tick's next presentation deadline."""

        deadline = self.scheduled_at_seconds + self.candidate_period_seconds
        return max(0.0, (self.completed_visible_at_seconds - deadline) * 1000.0)

    @property
    def headroom_before_next_tick_ms(self) -> float | None:
        """Return visible-update slack only for a real Streamlines rebuild."""

        if self.total_visible_update_ms is None:
            return None
        return self.candidate_period_seconds * 1000.0 - self.total_visible_update_ms

    @property
    def is_no_op(self) -> bool:
        """Return whether this tick deliberately preserved its current geometry."""

        return self.action == "NO_OP"


@dataclass(frozen=True)
class PresentationCandidateAssessment:
    """One compact decision for a time-based candidate period."""

    period_seconds: float
    viable: bool
    reason: str
    rebuilt_ticks: int
    no_op_ticks: int
    missed_deadlines: int
    max_pending_presentation_requests: int
    total_visible_update_median_ms: float | None
    total_visible_update_max_ms: float | None
    headroom_median_ms: float | None
    headroom_min_ms: float | None
    lateness_drift: str
    scheduling_lateness_drift: str


@dataclass(frozen=True)
class PresentationCandidateResult:
    """History of one candidate's short screen and optional sustained result."""

    screening: PresentationCandidateAssessment
    final_confirmation: PresentationCandidateAssessment | None = None

    @property
    def state(self) -> str:
        """Return a terminally honest candidate state for the Package G log."""

        if not self.screening.viable:
            return "SCREEN_REJECTED"
        if self.final_confirmation is None:
            return "SCREEN_PASS"
        return "FINAL_PASS" if self.final_confirmation.viable else "FINAL_REJECTED"

    @property
    def reason(self) -> str:
        """Return the final known reason without conflating screen and sustained
        runs."""

        return (
            self.final_confirmation.reason
            if self.final_confirmation is not None
            else self.screening.reason
        )


def resolve_presentation_sample(
    source: TemporalVelocitySourceDescriptor,
    presentation_phase_seconds: float,
    *,
    loop_duration_seconds: float = PRESENTATION_LOOP_DURATION_SECONDS,
) -> PresentationResolvedSample:
    """Resolve the latest real source sample at or before a loop phase.

    A presentation scheduler must never select a future velocity field merely
    because it is numerically nearer. The source descriptor remains the single
    authority for paths, source times, and USD time codes.
    """

    if loop_duration_seconds <= 0.0:
        raise ValueError("Presentation loop duration must be positive.")
    if source.sample_count <= 0:
        raise ValueError(
            "Presentation resolution requires at least one manifest sample."
        )
    if len(source.velocity_paths) != len(source.sample_time_codes):
        raise ValueError("Temporal source paths and time codes must have equal length.")
    if source.time_codes_per_second <= 0.0:
        raise ValueError("Temporal source timeCodesPerSecond must be positive.")

    phase = presentation_phase_seconds % loop_duration_seconds
    source_times = tuple(
        time_code / source.time_codes_per_second
        for time_code in source.sample_time_codes
    )
    if any(right < left for left, right in zip(source_times, source_times[1:])):
        raise ValueError("Manifest source times must be monotonically increasing.")
    if source_times[0] > 1e-9 or source_times[-1] >= loop_duration_seconds + 1e-9:
        raise ValueError(
            "Manifest source times must begin at loop phase zero and stay within "
            "the loop."
        )

    sample_index = 0
    for index, source_time in enumerate(source_times):
        if source_time <= phase + 1e-9:
            sample_index = index
        else:
            break
    return PresentationResolvedSample(
        presentation_phase_seconds=phase,
        sample_index=sample_index,
        source_vti=source.velocity_paths[sample_index],
        source_time_seconds=source_times[sample_index],
        time_code=source.sample_time_codes[sample_index],
    )


def build_presentation_tick_phases(
    period_seconds: float,
    tick_count: int,
    *,
    start_phase_seconds: float = 0.0,
    loop_duration_seconds: float = PRESENTATION_LOOP_DURATION_SECONDS,
) -> tuple[float, ...]:
    """Derive presentation ticks from elapsed seconds, never source indices."""

    if period_seconds <= 0.0:
        raise ValueError("Presentation period must be positive.")
    if tick_count <= 0:
        raise ValueError("Presentation tick count must be positive.")
    if loop_duration_seconds <= 0.0:
        raise ValueError("Presentation loop duration must be positive.")
    return tuple(
        (start_phase_seconds + ordinal * period_seconds) % loop_duration_seconds
        for ordinal in range(tick_count)
    )


def presentation_tick_action(
    resolved_sample_index: int,
    currently_presented_sample_index: int | None,
) -> str:
    """Return the no-op decision that prevents unnecessary consumer rebuilds."""

    return (
        "NO_OP"
        if resolved_sample_index == currently_presented_sample_index
        else "REBUILD"
    )


def presentation_headroom_guard_ms(period_seconds: float) -> float:
    """Return Package G's non-SLA scheduling margin for a candidate period."""

    if period_seconds <= 0.0:
        raise ValueError("Presentation period must be positive.")
    return max(
        PRESENTATION_MIN_HEADROOM_FLOOR_MS,
        period_seconds * 1000.0 * PRESENTATION_HEADROOM_FRACTION,
    )


def assess_presentation_candidate(
    period_seconds: float,
    observations: tuple[PresentationTickObservation, ...],
) -> PresentationCandidateAssessment:
    """Accept only a correct serial schedule with real visible-update headroom."""

    if not observations:
        return PresentationCandidateAssessment(
            period_seconds,
            False,
            "NO_TICKS",
            0,
            0,
            0,
            0,
            None,
            None,
            None,
            None,
            "NONE",
            "NONE",
        )
    rebuilds = tuple(record for record in observations if not record.is_no_op)
    no_op_ticks = len(observations) - len(rebuilds)
    pending_request_depth = max(
        max(
            record.pending_presentation_requests_at_request,
            record.pending_presentation_requests_at_start,
        )
        for record in observations
    )
    missed_deadlines = sum(
        record.completion_deadline_lateness_ms > 0.0 for record in observations
    )
    total_updates = tuple(
        record.total_visible_update_ms
        for record in rebuilds
        if record.total_visible_update_ms is not None
    )
    headrooms = tuple(
        record.headroom_before_next_tick_ms
        for record in rebuilds
        if record.headroom_before_next_tick_ms is not None
    )
    completion_lateness = tuple(
        record.completion_deadline_lateness_ms for record in observations
    )
    scheduling_lateness = tuple(record.start_lateness_ms for record in observations)
    valid_rebuilds = all(
        record.selected_vti_matches_expected
        and record.fresh_execution is True
        and record.execution_success is True
        and record.geometry_replaced is True
        and record.preview_matches_runtime is True
        for record in rebuilds
    )
    valid_no_ops = all(
        record.selected_vti_matches_expected
        and record.fresh_execution is None
        and record.geometry_replaced is None
        and record.preview_matches_runtime is None
        for record in observations
        if record.is_no_op
    )
    guard_band = presentation_headroom_guard_ms(period_seconds)
    drift = _lateness_drift(completion_lateness)
    result = PresentationCandidateAssessment(
        period_seconds=period_seconds,
        viable=False,
        reason="UNASSESSED",
        rebuilt_ticks=len(rebuilds),
        no_op_ticks=no_op_ticks,
        missed_deadlines=missed_deadlines,
        max_pending_presentation_requests=pending_request_depth,
        total_visible_update_median_ms=_median(total_updates),
        total_visible_update_max_ms=(max(total_updates) if total_updates else None),
        headroom_median_ms=_median(headrooms),
        headroom_min_ms=min(headrooms) if headrooms else None,
        lateness_drift=drift,
        scheduling_lateness_drift=_lateness_drift(scheduling_lateness),
    )
    if not rebuilds:
        return _replace_assessment_reason(result, "NO_REBUILD_TICKS")
    if not valid_rebuilds or not valid_no_ops:
        return _replace_assessment_reason(result, "INCORRECT_SOURCE_OR_GEOMETRY")
    if missed_deadlines:
        return _replace_assessment_reason(result, "MISSED_PRESENTATION_DEADLINE")
    # These counts exclude the current dequeued tick and the scheduler has no
    # sentinel item. Any remaining item is therefore a real prior/future
    # presentation request that the serial consumer has not yet serviced.
    if pending_request_depth:
        return _replace_assessment_reason(result, "PRESENTATION_BACKLOG")
    if result.scheduling_lateness_drift == "GROWING":
        return _replace_assessment_reason(result, "SCHEDULING_LATENESS_DRIFT")
    if drift != "NONE":
        return _replace_assessment_reason(result, "POSITIVE_LATENESS_DRIFT")
    if result.headroom_min_ms is None or result.headroom_min_ms < guard_band:
        return _replace_assessment_reason(result, "INSUFFICIENT_HEADROOM")
    return replace(result, viable=True, reason="PASS")


def refinement_period_seconds(
    last_failed_period_seconds: float,
    first_passing_period_seconds: float,
) -> float | None:
    """Return one 0.1-second refinement between the final fail and first pass."""

    if first_passing_period_seconds <= last_failed_period_seconds:
        raise ValueError("Refinement requires an ascending fail/pass bracket.")
    candidate = round(
        (last_failed_period_seconds + first_passing_period_seconds) / 2.0, 1
    )
    if candidate in (last_failed_period_seconds, first_passing_period_seconds):
        return None
    return candidate


def _replace_assessment_reason(
    result: PresentationCandidateAssessment,
    reason: str,
) -> PresentationCandidateAssessment:
    return replace(result, reason=reason)


def _lateness_drift(values: tuple[float, ...]) -> str:
    positive_pairs = tuple(
        (previous, current)
        for previous, current in zip(values, values[1:])
        if previous > 0.0 and current > 0.0
    )
    if not positive_pairs:
        return "NONE"
    return (
        "GROWING"
        if any(current > previous for previous, current in positive_pairs)
        else "PRESENT"
    )


def _median(values: tuple[float, ...]) -> float | None:
    return float(median(values)) if values else None
