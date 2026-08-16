"""Package C contracts and compact reporting for Streamlines type selection."""

from __future__ import annotations

from dataclasses import dataclass, replace
from math import ceil, floor, isclose
from statistics import median

from digital_twin_runtime_suite.app.flow.static_source import (
    StaticVelocitySourceDescriptor,
)
from digital_twin_runtime_suite.app.streamlines.proof import (
    STREAMLINES_COMPARISON_OPERATOR_ROOT,
    STREAMLINES_COMPARISON_SEED_ROOT,
    StaticStreamlinesProofRequest,
    build_static_streamlines_proof_request,
)

OPERATOR_TYPES = ("standard", "nanovdb")
WARMUP_RUN_COUNT = 1
MEASURED_RUN_COUNT = 3
# NanoVDB's grid is an additional representation of the regular VTI source.
# Keep it at least as fine as the 2.55 mm Houdini sample rather than allowing
# the command default (128) to turn this comparison into a fidelity trade-off.
NANOVDB_MAX_RESOLUTION = 256
# A preview mirror needs time to reach the normal USD renderer after its Kit
# owner is gone.  Capture independent HUD snapshots only after that recovery;
# consecutive Kit update ticks can expose the same cached frame statistic.
PACKAGE_C_RENDER_QUIESCENCE_UPDATE_COUNT = 30
# Preserve the original visible-update timing window (30 quiescence updates
# plus the former 15-sample loop) without misreporting those adjacent frames as
# independent FPS observations.
PACKAGE_C_TOTAL_VISIBLE_UPDATE_SETTLE_COUNT = 45
PACKAGE_C_STEADY_SNAPSHOT_INITIAL_DELAY_SECONDS = 5.0
PACKAGE_C_STEADY_SNAPSHOT_INTERVAL_SECONDS = 5.0
PACKAGE_C_STEADY_SNAPSHOT_COUNT = 5
COMPARISON_SHARED_SEED_PATH = (
    f"{STREAMLINES_COMPARISON_SEED_ROOT}/SharedDiagnosticUnitSphere"
)


@dataclass(frozen=True)
class StreamlinesOperatorExecutionReceipt:
    """One causally linked Kit begin/end result for a benchmark execution."""

    begin_count_before: int
    begin_count_after: int
    completion_count_before: int
    completion_count_after: int
    completion_begin_count: int | None
    completion_success: bool | None

    @property
    def fresh_execution(self) -> bool:
        """Require both a new begin and its causally paired later end event."""

        return (
            self.begin_count_after > self.begin_count_before
            and self.completion_count_after > self.completion_count_before
            and self.completion_begin_count is not None
            and self.completion_begin_count >= self.begin_count_after
        )

    @property
    def accepted(self) -> bool:
        """Keep geometry inspection supplementary to Kit's lifecycle receipt."""

        return self.fresh_execution and self.completion_success is True


@dataclass(frozen=True)
class NanoVdbEffectiveGrid:
    """Effective uniform NanoVDB grid derived with this Kit build's formula."""

    max_resolution: int
    dimensions: tuple[int, int, int]
    voxel_size_m: float
    source_max_spacing_m: float

    @property
    def preserves_source_fidelity(self) -> bool:
        """Reject a voxel grid that is coarser than the imported VTI spacing."""

        return self.voxel_size_m <= self.source_max_spacing_m


@dataclass(frozen=True)
class StreamlinesSteadyPerformanceEvidence:
    """Independent post-preview Kit-HUD snapshots for one visible review state."""

    sample_count: int
    fps_snapshots: tuple[float | None, ...]
    gpu_memory_snapshots: tuple[float | None, ...]
    process_memory_snapshots: tuple[float | None, ...]

    @property
    def fps_median(self) -> float | None:
        """Return the median only from actual Kit-HUD FPS observations."""

        return _median(self.fps_snapshots)

    @property
    def fps_min(self) -> float | None:
        """Expose the recovery-series low point without inventing a zero."""

        values = tuple(value for value in self.fps_snapshots if value is not None)
        return min(values) if values else None

    @property
    def fps_max(self) -> float | None:
        """Expose the recovery-series high point without inventing a zero."""

        values = tuple(value for value in self.fps_snapshots if value is not None)
        return max(values) if values else None

    @property
    def gpu_memory_median_gib(self) -> float | None:
        """Return available GPU-memory evidence from the same recovery series."""

        return _median(self.gpu_memory_snapshots)

    @property
    def process_memory_median_gib(self) -> float | None:
        """Return available process-memory evidence from the same recovery series."""

        return _median(self.process_memory_snapshots)

    @property
    def has_complete_fps_series(self) -> bool:
        """Require five usable snapshots before accepting the steady-FPS evidence."""

        return (
            self.sample_count == PACKAGE_C_STEADY_SNAPSHOT_COUNT
            and len(self.fps_snapshots) == PACKAGE_C_STEADY_SNAPSHOT_COUNT
            and all(value is not None and value > 0.0 for value in self.fps_snapshots)
        )


@dataclass(frozen=True)
class StreamlinesOperatorTypeComparisonCase:
    """One type-specific operator that shares every input with its challenger."""

    operator_type: str
    request: StaticStreamlinesProofRequest
    preview_path: str


@dataclass(frozen=True)
class StreamlinesOperatorTypeBenchmarkSample:
    """One measured visible update after the single warm-up run has completed."""

    operator_creation_ms: float | None
    operator_rebuild_ms: float | None
    preview_mirror_ms: float | None
    total_visible_update_ms: float | None
    runtime_curve_count: int
    runtime_point_count: int
    points_per_curve_min_mean_max: tuple[int, int | float, int] | None
    runtime_bounds: tuple[tuple[float, float, float], tuple[float, float, float]] | None
    bounds_within_source: bool
    execution_receipt: StreamlinesOperatorExecutionReceipt


@dataclass(frozen=True)
class StreamlinesOperatorTypeComparisonCaseResult:
    """All Package C evidence for one type, including exactly three measured runs."""

    operator_type: str
    operator_path: str
    preview_path: str
    creation_duration_ms: float | None
    warmup_rebuild_ms: float | None
    warmup_succeeded: bool
    warmup_receipt: StreamlinesOperatorExecutionReceipt | None
    measured_samples: tuple[StreamlinesOperatorTypeBenchmarkSample, ...]
    steady_performance: StreamlinesSteadyPerformanceEvidence | None
    source_binding: tuple[str, ...]
    seed_binding: tuple[str, ...]
    velocity_binding: tuple[str, ...]
    integration_settings: tuple[tuple[str, str], ...]
    source_processing_mode: str
    nanovdb_voxelization_ms: float | None
    voxelization_settings: tuple[tuple[str, str], ...]
    nanovdb_effective_grid: NanoVdbEffectiveGrid | None
    warnings_errors: str
    passed: bool
    reason: str | None = None

    @property
    def rebuild_median_ms(self) -> float | None:
        """Return the median of the three post-warm-up operator executions."""

        return _median(sample.operator_rebuild_ms for sample in self.measured_samples)

    @property
    def creation_median_ms(self) -> float | None:
        """Expose clean-operator authoring cost separately from Kit execution."""

        return _median(sample.operator_creation_ms for sample in self.measured_samples)

    @property
    def preview_median_ms(self) -> float | None:
        """Return the median cost of the FSD-safe viewport mirror."""

        return _median(sample.preview_mirror_ms for sample in self.measured_samples)

    @property
    def total_visible_update_median_ms(self) -> float | None:
        """Return the median from operator enable through visible preview update."""

        return _median(
            sample.total_visible_update_ms for sample in self.measured_samples
        )

    @property
    def steady_viewport_fps_median(self) -> float | None:
        """Return the post-recovery FPS median for the visible review preview."""

        return self.steady_performance.fps_median if self.steady_performance else None

    @property
    def steady_viewport_fps_min(self) -> float | None:
        """Return the minimum of the independent steady-FPS recovery snapshots."""

        return self.steady_performance.fps_min if self.steady_performance else None

    @property
    def steady_viewport_fps_max(self) -> float | None:
        """Return the maximum of the independent steady-FPS recovery snapshots."""

        return self.steady_performance.fps_max if self.steady_performance else None

    @property
    def gpu_memory_used_gib_median(self) -> float | None:
        """Return Kit HUD GPU-memory evidence when the current runtime exposes it."""

        return (
            self.steady_performance.gpu_memory_median_gib
            if self.steady_performance
            else None
        )

    @property
    def process_memory_used_gib_median(self) -> float | None:
        """Return process-memory evidence when Kit exposes it through the HUD."""

        return (
            self.steady_performance.process_memory_median_gib
            if self.steady_performance
            else None
        )

    @property
    def final_sample(self) -> StreamlinesOperatorTypeBenchmarkSample | None:
        """Return the third measured result left available for human review."""

        return self.measured_samples[-1] if self.measured_samples else None


@dataclass(frozen=True)
class StreamlinesOperatorTypeComparisonResult:
    """Package C evidence and review state; production selection remains explicit."""

    standard: StreamlinesOperatorTypeComparisonCaseResult
    nanovdb: StreamlinesOperatorTypeComparisonCaseResult
    identical_non_type_inputs: bool
    previous_comparison_cleanup_success: bool
    active_review_type: str

    @property
    def success(self) -> bool:
        """Require both three-run cases and a clean replacement of prior evidence."""

        return (
            self.identical_non_type_inputs
            and self.previous_comparison_cleanup_success
            and self.standard.passed
            and self.nanovdb.passed
        )

    @property
    def message(self) -> str:
        """Describe the review boundary without choosing a production path."""

        if not self.identical_non_type_inputs:
            return "Type comparison failed: non-type inputs diverged."
        if not self.previous_comparison_cleanup_success:
            return "Type comparison failed: prior comparison roots were not removed."
        if not self.standard.passed:
            return "Standard comparison case failed; inspect its compact evidence."
        if not self.nanovdb.passed:
            return "NanoVDB comparison case failed; inspect its compact evidence."
        return "Type comparison complete; select a preview for human review."


def build_streamlines_operator_type_comparison_cases(
    descriptor: StaticVelocitySourceDescriptor | None,
) -> tuple[StreamlinesOperatorTypeComparisonCase, ...]:
    """Build standard and NanoVDB cases from the exact Package B setup."""

    base_request = build_static_streamlines_proof_request(descriptor)
    return tuple(
        StreamlinesOperatorTypeComparisonCase(
            operator_type=operator_type,
            request=replace(
                base_request,
                operator_type=operator_type,
                operator_path=(
                    f"{STREAMLINES_COMPARISON_OPERATOR_ROOT}/{operator_type}"
                ),
                seed_path=COMPARISON_SHARED_SEED_PATH,
            ),
            preview_path=(
                f"{STREAMLINES_COMPARISON_OPERATOR_ROOT}/{operator_type}RuntimePreview"
            ),
        )
        for operator_type in OPERATOR_TYPES
    )


def comparison_cases_share_non_type_inputs(
    cases: tuple[StreamlinesOperatorTypeComparisonCase, ...],
) -> bool:
    """Prove Package C changes only the operator implementation type."""

    if tuple(case.operator_type for case in cases) != OPERATOR_TYPES:
        return False
    requests = tuple(case.request for case in cases)
    if len(requests) != len(OPERATOR_TYPES):
        return False
    baseline = requests[0]
    fields = (
        "dataset_prim_path",
        "velocity_field_prim_path",
        "seed_path",
        "direction",
        "seed_center",
        "seed_radius",
        "min_step_size",
        "initial_step_size",
        "max_step_size",
        "max_steps",
        "width",
    )
    return all(
        all(getattr(request, field) == getattr(baseline, field) for field in fields)
        for request in requests[1:]
    )


def clear_streamlines_operator_type_comparison_from_stage(stage) -> bool:
    """Replace only a prior Package C review state; preserve Package B proof roots."""

    paths = (
        STREAMLINES_COMPARISON_OPERATOR_ROOT,
        STREAMLINES_COMPARISON_SEED_ROOT,
    )
    previous_target = stage.GetEditTarget()
    try:
        for layer in (stage.GetSessionLayer(), stage.GetRootLayer()):
            stage.SetEditTarget(layer)
            for path in paths:
                if stage.GetPrimAtPath(path).IsValid():
                    stage.RemovePrim(path)
    finally:
        stage.SetEditTarget(previous_target)
    return not any(stage.GetPrimAtPath(path).IsValid() for path in paths)


def format_streamlines_operator_type_comparison(
    descriptor: StaticVelocitySourceDescriptor,
    cases: tuple[StreamlinesOperatorTypeComparisonCase, ...],
    result: StreamlinesOperatorTypeComparisonResult,
) -> str:
    """Format the requested Standard/NanoVDB decision table without invented data."""

    state = "PASS" if result.success else "FAIL"
    shared_request = cases[0].request
    standard_steady = result.standard.steady_performance
    nanovdb_steady = result.nanovdb.steady_performance
    standard_fps_snapshots = _format_snapshots(
        standard_steady.fps_snapshots if standard_steady else ()
    )
    standard_gpu_snapshots = _format_snapshots(
        standard_steady.gpu_memory_snapshots if standard_steady else (),
        suffix=" GiB",
    )
    standard_process_snapshots = _format_snapshots(
        standard_steady.process_memory_snapshots if standard_steady else (),
        suffix=" GiB",
    )
    nanovdb_fps_snapshots = _format_snapshots(
        nanovdb_steady.fps_snapshots if nanovdb_steady else ()
    )
    nanovdb_gpu_snapshots = _format_snapshots(
        nanovdb_steady.gpu_memory_snapshots if nanovdb_steady else (),
        suffix=" GiB",
    )
    nanovdb_process_snapshots = _format_snapshots(
        nanovdb_steady.process_memory_snapshots if nanovdb_steady else (),
        suffix=" GiB",
    )
    standard_fps_metrics = (
        _format_value(result.standard.steady_viewport_fps_median, "", "NOT_AVAILABLE"),
        _format_value(result.standard.steady_viewport_fps_min, "", "NOT_AVAILABLE"),
        _format_value(result.standard.steady_viewport_fps_max, "", "NOT_AVAILABLE"),
    )
    nanovdb_fps_metrics = (
        _format_value(result.nanovdb.steady_viewport_fps_median, "", "NOT_AVAILABLE"),
        _format_value(result.nanovdb.steady_viewport_fps_min, "", "NOT_AVAILABLE"),
        _format_value(result.nanovdb.steady_viewport_fps_max, "", "NOT_AVAILABLE"),
    )
    lines = [
        f"DTRS STREAMLINES | OPERATOR_TYPE_COMPARISON | {state}",
        "",
        "setup:",
        f"  workload={descriptor.workload}",
        f"  sample_index={descriptor.sample_index}",
        f"  source_vti={descriptor.vti_path}",
        f"  velocity_field={shared_request.velocity_field_prim_path}",
        "  fsd=false",
        f"  warmup_runs={WARMUP_RUN_COUNT}",
        f"  measured_runs={MEASURED_RUN_COUNT}",
        "",
        "shared_contract:",
        f"  dataset_prim_path={shared_request.dataset_prim_path}",
        f"  seed_path={shared_request.seed_path}",
        f"  seed_center={shared_request.seed_center}",
        f"  seed_radius={shared_request.seed_radius}",
        f"  direction={shared_request.direction}",
        f"  min_step_size={shared_request.min_step_size}",
        f"  initial_step_size={shared_request.initial_step_size}",
        f"  max_step_size={shared_request.max_step_size}",
        f"  max_steps={shared_request.max_steps}",
        f"  width={shared_request.width}",
        f"  identical_non_type_inputs={result.identical_non_type_inputs}",
        f"  render_quiescence_updates={PACKAGE_C_RENDER_QUIESCENCE_UPDATE_COUNT}",
        (
            "  total_visible_update_settle_updates="
            f"{PACKAGE_C_TOTAL_VISIBLE_UPDATE_SETTLE_COUNT}"
        ),
        (
            "  steady_snapshot_initial_delay_seconds="
            f"{PACKAGE_C_STEADY_SNAPSHOT_INITIAL_DELAY_SECONDS:.1f}"
        ),
        (
            "  steady_snapshot_interval_seconds="
            f"{PACKAGE_C_STEADY_SNAPSHOT_INTERVAL_SECONDS:.1f}"
        ),
        f"  steady_snapshot_count={PACKAGE_C_STEADY_SNAPSHOT_COUNT}",
        "",
        "metric                         STANDARD                 NANOVDB",
        _table_row(
            "operator_rebuild_ms median",
            result.standard.rebuild_median_ms,
            result.nanovdb.rebuild_median_ms,
            suffix=" ms",
        ),
        _table_row(
            "operator_creation_ms median",
            result.standard.creation_median_ms,
            result.nanovdb.creation_median_ms,
            suffix=" ms",
        ),
        _table_row(
            "preview_mirror_ms median",
            result.standard.preview_median_ms,
            result.nanovdb.preview_median_ms,
            suffix=" ms",
        ),
        _table_row(
            "total_visible_update median",
            result.standard.total_visible_update_median_ms,
            result.nanovdb.total_visible_update_median_ms,
            suffix=" ms",
        ),
        _table_row(
            "steady_viewport_fps median",
            result.standard.steady_viewport_fps_median,
            result.nanovdb.steady_viewport_fps_median,
        ),
        _table_row(
            "steady_viewport_fps min",
            result.standard.steady_viewport_fps_min,
            result.nanovdb.steady_viewport_fps_min,
        ),
        _table_row(
            "steady_viewport_fps max",
            result.standard.steady_viewport_fps_max,
            result.nanovdb.steady_viewport_fps_max,
        ),
        _table_row(
            "gpu_memory_used_gib median",
            result.standard.gpu_memory_used_gib_median,
            result.nanovdb.gpu_memory_used_gib_median,
            suffix=" GiB",
        ),
        _table_row(
            "process_memory_gib median",
            result.standard.process_memory_used_gib_median,
            result.nanovdb.process_memory_used_gib_median,
            suffix=" GiB",
        ),
        _table_row(
            "nanovdb_voxelization_ms",
            None,
            result.nanovdb.nanovdb_voxelization_ms,
            unavailable="NOT_SEPARATELY_OBSERVABLE",
        ),
        _table_row(
            "runtime_curve_count",
            _final_value(result.standard, "runtime_curve_count"),
            _final_value(result.nanovdb, "runtime_curve_count"),
        ),
        _table_row(
            "runtime_point_count",
            _final_value(result.standard, "runtime_point_count"),
            _final_value(result.nanovdb, "runtime_point_count"),
        ),
        _table_row(
            "points_per_curve min/mean/max",
            _final_value(result.standard, "points_per_curve_min_mean_max"),
            _final_value(result.nanovdb, "points_per_curve_min_mean_max"),
        ),
        _table_row(
            "runtime_bounds",
            _final_value(result.standard, "runtime_bounds"),
            _final_value(result.nanovdb, "runtime_bounds"),
        ),
        _table_row(
            "bounds_within_source",
            _final_value(result.standard, "bounds_within_source"),
            _final_value(result.nanovdb, "bounds_within_source"),
        ),
        _table_row(
            "warnings/errors",
            result.standard.warnings_errors,
            result.nanovdb.warnings_errors,
        ),
        "",
        "type_specific:",
        f"  standard_source_processing={result.standard.source_processing_mode}",
        f"  nanovdb_source_processing={result.nanovdb.source_processing_mode}",
        f"  nanovdb_voxelization_settings={result.nanovdb.voxelization_settings}",
        (
            "  nanovdb_effective_grid="
            f"{_format_nanovdb_grid(result.nanovdb.nanovdb_effective_grid)}"
        ),
        "  nanovdb_voxelization_ms=NOT_SEPARATELY_OBSERVABLE (included in rebuild)",
        "",
        "execution_receipts:",
        f"  standard={_format_execution_receipts(result.standard)}",
        f"  nanovdb={_format_execution_receipts(result.nanovdb)}",
        "",
        "steady_performance:",
        "  camera=unchanged_by_benchmark",
        (
            "  initial_recovery_delay_seconds="
            f"{PACKAGE_C_STEADY_SNAPSHOT_INITIAL_DELAY_SECONDS:.1f}"
        ),
        (
            "  snapshot_interval_seconds="
            f"{PACKAGE_C_STEADY_SNAPSHOT_INTERVAL_SECONDS:.1f}"
        ),
        f"  snapshot_count={PACKAGE_C_STEADY_SNAPSHOT_COUNT}",
        "  standard:",
        f"    fps_snapshots={standard_fps_snapshots}",
        f"    fps_median={standard_fps_metrics[0]}",
        f"    fps_min={standard_fps_metrics[1]}",
        f"    fps_max={standard_fps_metrics[2]}",
        f"    gpu_memory_snapshots={standard_gpu_snapshots}",
        f"    process_memory_snapshots={standard_process_snapshots}",
        "  nanovdb:",
        f"    fps_snapshots={nanovdb_fps_snapshots}",
        f"    fps_median={nanovdb_fps_metrics[0]}",
        f"    fps_min={nanovdb_fps_metrics[1]}",
        f"    fps_max={nanovdb_fps_metrics[2]}",
        f"    gpu_memory_snapshots={nanovdb_gpu_snapshots}",
        f"    process_memory_snapshots={nanovdb_process_snapshots}",
        "",
        "review_state:",
        f"  active_preview_type={result.active_review_type}",
        f"  standard_preview_path={result.standard.preview_path}",
        f"  nanovdb_preview_path={result.nanovdb.preview_path}",
        "  presentation=confirmed UsdRT RuntimePreview under FSD=false",
        "  production_selection=DEFERRED (review measured evidence first)",
        f"result={state}",
    ]
    return "\n".join(lines)


def _median(values) -> float | None:
    """Reduce only available Kit samples; unavailable instrumentation stays absent."""

    available = tuple(value for value in values if value is not None)
    return float(median(available)) if available else None


def calculate_nanovdb_effective_grid(
    world_bounds: tuple[tuple[float, float, float], tuple[float, float, float]],
    source_spacing: tuple[float, float, float],
    *,
    max_resolution: int = NANOVDB_MAX_RESOLUTION,
) -> NanoVdbEffectiveGrid:
    """Mirror local Kit-CAE's max-resolution voxel-size calculation for logging.

    The local implementation creates an origin-aligned grid and can enlarge the
    initial voxel size to keep the final integer grid inside `max_resolution`.
    Reporting that effective result prevents the requested setting from being
    mistaken for actual spatial fidelity.
    """

    if max_resolution <= 0:
        raise ValueError("NanoVDB max_resolution must be positive.")
    minimum, maximum = world_bounds
    extent = tuple(
        float(upper) - float(lower) for lower, upper in zip(minimum, maximum)
    )
    if any(value <= 0.0 for value in extent):
        raise ValueError("NanoVDB requires non-empty source bounds.")

    voxel_size = max(extent) / max_resolution
    dimensions: tuple[int, int, int] | None = None
    for _ in range(10):
        index_min = [floor(value / voxel_size) for value in minimum]
        index_max = [ceil(value / voxel_size) for value in maximum]
        for axis, (lower, upper) in enumerate(zip(minimum, maximum)):
            lower_grid = lower / voxel_size
            upper_grid = upper / voxel_size
            if isclose(lower_grid, index_min[axis], rel_tol=1e-5, abs_tol=1e-8):
                index_min[axis] -= 1
            if isclose(upper_grid, index_max[axis], rel_tol=1e-5, abs_tol=1e-8):
                index_max[axis] += 1
        candidate = tuple(upper - lower for lower, upper in zip(index_min, index_max))
        if max(candidate) <= max_resolution:
            dimensions = candidate
            break
        voxel_size *= (max(candidate) / max_resolution) * 1.01
    if dimensions is None:
        raise RuntimeError("Could not derive the local Kit NanoVDB effective grid.")

    return NanoVdbEffectiveGrid(
        max_resolution=max_resolution,
        dimensions=dimensions,
        voxel_size_m=voxel_size,
        source_max_spacing_m=max(float(value) for value in source_spacing),
    )


def build_streamlines_steady_performance_evidence(
    samples,
) -> StreamlinesSteadyPerformanceEvidence:
    """Keep five independent Flow-style HUD snapshots without cached frame reads."""

    observations = tuple(samples)
    return StreamlinesSteadyPerformanceEvidence(
        sample_count=len(observations),
        fps_snapshots=tuple(sample.fps for sample in observations),
        gpu_memory_snapshots=tuple(
            sample.gpu_memory_used_gib for sample in observations
        ),
        process_memory_snapshots=tuple(
            sample.process_memory_used_gib for sample in observations
        ),
    )


def _final_value(
    result: StreamlinesOperatorTypeComparisonCaseResult,
    attribute: str,
):
    """Read the third measured sample without fabricating a value after failure."""

    sample = result.final_sample
    return getattr(sample, attribute) if sample else None


def _table_row(
    label: str,
    standard,
    nanovdb,
    *,
    suffix: str = "",
    unavailable: str = "NOT_AVAILABLE",
) -> str:
    """Keep both columns compact and honest when Kit cannot supply a metric."""

    standard_text = _format_value(standard, suffix, unavailable)
    nanovdb_text = _format_value(nanovdb, suffix, unavailable)
    return f"{label:<30} {standard_text:<24}" f" {nanovdb_text}"


def _format_value(value, suffix: str, unavailable: str) -> str:
    """Avoid converting unavailable Kit metrics into plausible-looking zeros."""

    if value is None:
        return unavailable
    if isinstance(value, float):
        return f"{value:.1f}{suffix}"
    return f"{value}{suffix}"


def _format_nanovdb_grid(grid: NanoVdbEffectiveGrid | None) -> str:
    """Keep effective NanoVDB fidelity evidence readable in the compact report."""

    if grid is None:
        return "NOT_APPLICABLE"
    return (
        f"dimensions={grid.dimensions}; voxel_size_m={grid.voxel_size_m:.6f}; "
        f"source_max_spacing_m={grid.source_max_spacing_m:.6f}; "
        f"preserves_source_fidelity={grid.preserves_source_fidelity}"
    )


def _format_execution_receipts(
    result: StreamlinesOperatorTypeComparisonCaseResult,
) -> str:
    """Show the distinct warm-up and three measured Kit completion receipts."""

    def compact(receipt: StreamlinesOperatorExecutionReceipt | None) -> str:
        if receipt is None:
            return "unavailable"
        return (
            f"begin={receipt.begin_count_before}->{receipt.begin_count_after}; "
            f"end={receipt.completion_count_before}->{receipt.completion_count_after}; "
            f"end_begin={receipt.completion_begin_count}; "
            f"fresh={receipt.fresh_execution}; success={receipt.completion_success}"
        )

    measured = "; ".join(
        f"measured_{index}[{compact(sample.execution_receipt)}]"
        for index, sample in enumerate(result.measured_samples, start=1)
    )
    return f"warmup[{compact(result.warmup_receipt)}]; {measured}"


def _format_snapshots(values, *, suffix: str = "") -> str:
    """Keep the five recovery observations visible without a per-frame log dump."""

    if not values:
        return "NOT_AVAILABLE"
    return (
        "("
        + ", ".join(
            "NOT_AVAILABLE" if value is None else f"{value:.1f}{suffix}"
            for value in values
        )
        + ")"
    )
