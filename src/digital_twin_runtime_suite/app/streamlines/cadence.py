"""Plain Package F contracts for measuring real temporal Streamlines cadence.

Kit-facing code owns temporal selection, operator recreation, and the
FSD-safe RuntimePreview.  This module only derives manifest-backed scenarios,
retains compact observations, and classifies their measured outcome.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from statistics import median

from digital_twin_runtime_suite.app.streamlines.temporal import (
    StreamlinesGeometrySignature,
    TemporalVelocitySourceDescriptor,
)

CADENCE_BURST_SAMPLE_COUNT = 10
CADENCE_PERFORMANCE_SNAPSHOT_COUNT = 5
CADENCE_PERFORMANCE_SETTLE_SECONDS = 5.0
# Match the accepted Package C practice: independent HUD snapshots are spaced
# far enough apart to describe recovered viewport behaviour rather than the
# transient frame that happens to coincide with a Kit-CAE rebuild.
CADENCE_PERFORMANCE_SNAPSHOT_INTERVAL_SECONDS = 5.0
CADENCE_OPERATOR_PATH = "/DTRS_KitCAE/Streamlines/CadenceFeasibility"
CADENCE_RUNTIME_PREVIEW_PATH = (
    "/DTRS_KitCAE/Streamlines/CadenceFeasibilityRuntimePreview"
)
CADENCE_SEED_PATH = "/DTRS_KitCAE/StreamlineSeeds/CadenceFeasibilitySphere"


@dataclass(frozen=True)
class CadenceSample:
    """One exact manifest VTI/timecode selected by a Package F scenario."""

    sample_index: int
    source_vti: Path
    source_time_seconds: float
    time_code: float


@dataclass(frozen=True)
class CadenceFeasibilityPlan:
    """Deterministic real-source scenarios used by the Package F experiment."""

    initial_sample: CadenceSample
    sequential_samples: tuple[CadenceSample, ...]
    repeated_samples: tuple[CadenceSample, ...]
    loop_boundary_samples: tuple[CadenceSample, ...]
    burst_samples: tuple[CadenceSample, ...]
    source_period_ms: float


@dataclass(frozen=True)
class CadenceBoundaryObservation:
    """One source-boundary observation with execution and visibility milestones."""

    scenario: str
    sample: CadenceSample
    requested_at_seconds: float
    processing_started_at_seconds: float
    completed_visible_at_seconds: float
    source_transition_ms: float
    operator_rebuild_ms: float
    usdrt_ready_ms: float
    preview_update_ms: float
    total_visible_update_ms: float
    begin_count_before: int
    begin_count_after: int
    completion_count_before: int
    completion_count_after: int
    fresh_execution: bool
    execution_success: bool | None
    curve_count: int
    point_count: int
    bounds: tuple[tuple[float, float, float], tuple[float, float, float]] | None
    geometry_replaced: bool
    preview_matches_runtime: bool
    signature: StreamlinesGeometrySignature
    scheduled_at_seconds: float | None = None
    queue_depth_at_request: int | None = None
    queue_depth_at_start: int | None = None

    @property
    def start_lateness_ms(self) -> float | None:
        """Return request-to-consumer lateness only for scheduled burst work."""

        if self.scheduled_at_seconds is None:
            return None
        return max(
            0.0,
            (self.processing_started_at_seconds - self.scheduled_at_seconds) * 1000.0,
        )

    @property
    def completion_lateness_ms(self) -> float | None:
        """Return source-deadline lateness when the visible preview completed."""

        if self.scheduled_at_seconds is None:
            return None
        return max(
            0.0,
            (self.completed_visible_at_seconds - self.scheduled_at_seconds) * 1000.0,
        )


@dataclass(frozen=True)
class CadencePerformanceEvidence:
    """Independent Kit-HUD snapshots for baseline, burst, or recovery state."""

    captured_at_seconds: tuple[float, ...]
    fps_snapshots: tuple[float | None, ...]
    gpu_memory_snapshots_gib: tuple[float | None, ...]
    process_memory_snapshots_gib: tuple[float | None, ...]

    @property
    def fps_median(self) -> float | None:
        """Return the median only from actual HUD values."""

        return _median(self.fps_snapshots)

    @property
    def fps_min(self) -> float | None:
        values = tuple(value for value in self.fps_snapshots if value is not None)
        return min(values) if values else None

    @property
    def fps_max(self) -> float | None:
        values = tuple(value for value in self.fps_snapshots if value is not None)
        return max(values) if values else None

    @property
    def gpu_memory_median_gib(self) -> float | None:
        return _median(self.gpu_memory_snapshots_gib)

    @property
    def process_memory_median_gib(self) -> float | None:
        return _median(self.process_memory_snapshots_gib)


@dataclass(frozen=True)
class CadenceClassification:
    """One evidence-based conclusion without applying any cadence optimization."""

    value: str
    reason: str


def build_cadence_feasibility_plan(
    source: TemporalVelocitySourceDescriptor,
) -> CadenceFeasibilityPlan:
    """Derive all Package F source windows solely from the active manifest."""

    if source.sample_count < CADENCE_BURST_SAMPLE_COUNT:
        raise ValueError(
            "Cadence Feasibility requires at least "
            f"{CADENCE_BURST_SAMPLE_COUNT} manifest samples."
        )
    if source.sample_interval_seconds <= 0.0:
        raise ValueError("Cadence Feasibility requires a positive source interval.")

    # Start the contiguous windows near the first quarter, but retain ten real
    # consecutive samples inside the manifest without wrapping the benchmark.
    quarter_index = round((source.sample_count - 1) * 0.25)
    window_start = min(quarter_index, source.sample_count - CADENCE_BURST_SAMPLE_COUNT)
    sequential_indices = tuple(range(window_start, window_start + 5))
    return CadenceFeasibilityPlan(
        initial_sample=resolve_cadence_sample(source, 0),
        sequential_samples=tuple(
            resolve_cadence_sample(source, index) for index in sequential_indices
        ),
        repeated_samples=(
            resolve_cadence_sample(source, window_start),
            resolve_cadence_sample(source, window_start),
        ),
        loop_boundary_samples=(
            resolve_cadence_sample(source, source.sample_count - 2),
            resolve_cadence_sample(source, source.sample_count - 1),
            resolve_cadence_sample(source, 0),
            resolve_cadence_sample(source, 1),
        ),
        burst_samples=tuple(
            resolve_cadence_sample(source, index)
            for index in range(window_start, window_start + CADENCE_BURST_SAMPLE_COUNT)
        ),
        source_period_ms=source.sample_interval_seconds * 1000.0,
    )


def resolve_cadence_sample(
    source: TemporalVelocitySourceDescriptor,
    sample_index: int,
) -> CadenceSample:
    """Resolve one source index to its exact manifest VTI and time mapping."""

    if not 0 <= sample_index < source.sample_count:
        raise IndexError(
            f"Cadence sample index {sample_index} is outside "
            f"0..{source.sample_count - 1}."
        )
    if len(source.velocity_paths) != len(source.sample_time_codes):
        raise ValueError("Temporal source paths and time codes must have equal length.")
    return CadenceSample(
        sample_index=sample_index,
        source_vti=source.velocity_paths[sample_index],
        source_time_seconds=(
            source.sample_time_codes[sample_index] / source.time_codes_per_second
        ),
        time_code=source.sample_time_codes[sample_index],
    )


def build_cadence_performance_evidence(samples) -> CadencePerformanceEvidence:
    """Retain raw Flow-style HUD snapshots without fabricating unavailable data."""

    observations = tuple(samples)
    return CadencePerformanceEvidence(
        captured_at_seconds=tuple(sample.captured_at for sample in observations),
        fps_snapshots=tuple(sample.fps for sample in observations),
        gpu_memory_snapshots_gib=tuple(
            sample.gpu_memory_used_gib for sample in observations
        ),
        process_memory_snapshots_gib=tuple(
            sample.process_memory_used_gib for sample in observations
        ),
    )


def classify_cadence_feasibility(
    *,
    source_period_ms: float,
    burst_records: tuple[CadenceBoundaryObservation, ...],
    requested_samples: int,
) -> CadenceClassification:
    """Classify measured serial processing; never change cadence behaviour.

    Classification A requires every visible result to meet the actual source
    period with no queue.  B preserves correct but backlogged processing.  C
    is reserved for an invalid or unstable rebuild result.
    """

    if len(burst_records) != requested_samples or any(
        not (
            record.fresh_execution
            and record.execution_success is True
            and record.geometry_replaced
            and record.preview_matches_runtime
        )
        for record in burst_records
    ):
        return CadenceClassification(
            "C",
            "A requested temporal boundary did not produce a stable confirmed result.",
        )
    max_queue_depth = max(
        max(
            record.queue_depth_at_request or 0,
            record.queue_depth_at_start or 0,
        )
        for record in burst_records
    )
    max_visible_update = max(record.total_visible_update_ms for record in burst_records)
    if max_queue_depth == 0 and max_visible_update <= source_period_ms:
        return CadenceClassification(
            "A",
            "Every requested boundary completed visibly within the source period "
            "without backlog.",
        )
    return CadenceClassification(
        "B",
        "All real samples completed, but visible serial processing exceeded the "
        "source cadence or accumulated backlog.",
    )


def median_and_max(
    records: tuple[CadenceBoundaryObservation, ...],
    attribute: str,
) -> tuple[float | None, float | None]:
    """Reduce one measured duration family while retaining raw records elsewhere."""

    values = tuple(
        float(value)
        for record in records
        if (value := getattr(record, attribute)) is not None
    )
    return (_median(values), max(values) if values else None)


def recovery_time_to_baseline_seconds(
    baseline: CadencePerformanceEvidence,
    recovery: CadencePerformanceEvidence,
    *,
    recovery_started_at_seconds: float,
    fraction: float = 0.9,
) -> float | None:
    """Return first recovery sample reaching 90% of baseline HUD FPS.

    This is a recovery indicator, not an acceptance threshold and not a
    substitute for the cadence queue measurements.
    """

    baseline_fps = baseline.fps_median
    if baseline_fps is None:
        return None
    threshold = baseline_fps * fraction
    for captured_at, fps in zip(recovery.captured_at_seconds, recovery.fps_snapshots):
        if fps is not None and fps >= threshold:
            return max(0.0, captured_at - recovery_started_at_seconds)
    return None


def _median(values) -> float | None:
    values = tuple(value for value in values if value is not None)
    return float(median(values)) if values else None
