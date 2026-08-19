"""Transient Phase 4.4A Streamlines geometry-tuning contracts."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from statistics import median

from digital_twin_runtime_suite.app.streamlines.profile import (
    FINAL_GLOBAL_FLOW_PATH_GEOMETRY_CONTRACT,
    FINAL_VOLUME_COVERAGE_GEOMETRY_CONTRACT,
    PRODUCTION_STREAMLINES_PROFILE,
    StreamlinesGeometryContract,
    StreamlinesProfileId,
)

GLOBAL_SEED_COUNT_OPTIONS = (64, 128, 256)
GLOBAL_MAX_STEPS_OPTIONS = (200, 400, 800, 1600)
VOLUME_SECTION_COUNT_OPTIONS = (8, 12, 16, 24)
VOLUME_SEEDS_PER_SECTION_OPTIONS = (64, 128, 256)
VOLUME_MAX_STEPS_OPTIONS = (10, 15, 20, 25)
STEP_SCALE_OPTIONS = (0.25, 0.5, 1.0, 2.0)
PREVIEW_WORKLOAD_OPTIONS = ("Idle", "Nominal", "Surge", "Critical")
STEP_SCALE_LABELS = (
    "0.25x",
    "0.5x",
    "1.0x",
    "2.0x",
)
MAX_STEPS_OPTIONS = GLOBAL_MAX_STEPS_OPTIONS

BASE_MIN_STEP = 0.01
BASE_INITIAL_STEP = 0.2
BASE_MAX_STEP = 0.5


class StreamlinesPreviewWorkloadMismatchError(RuntimeError):
    """Describe a user selection that does not match the guided next step."""

    def __init__(self, *, expected: str, selected: str) -> None:
        self.expected = expected
        self.selected = selected
        super().__init__(
            "Unexpected 4.4A preview workload: "
            f"expected={expected}; selected={selected}."
        )


class StreamlinesPreviewSelectionMismatchError(RuntimeError):
    """Describe a Test B profile/workload choice without ending the session."""

    def __init__(
        self,
        *,
        expected_profile: StreamlinesProfileId,
        selected_profile: StreamlinesProfileId,
        expected_workload: str,
        selected_workload: str,
    ) -> None:
        self.expected_profile = expected_profile
        self.selected_profile = selected_profile
        self.expected_workload = expected_workload
        self.selected_workload = selected_workload
        super().__init__(
            f"expected_profile={expected_profile.value}; "
            f"selected_profile={selected_profile.value}; "
            f"expected_workload={expected_workload}; "
            f"selected_workload={selected_workload}"
        )


@dataclass(frozen=True)
class StreamlinesGeometryTuning:
    """One transient preview choice that never mutates the frozen profile."""

    max_steps: int = 200
    step_scale: float = 1.0

    def __post_init__(self) -> None:
        """Accept only the bounded options exposed by the tuning UI."""

        if self.max_steps not in MAX_STEPS_OPTIONS:
            raise ValueError("Unsupported Streamlines max-steps tuning value.")
        if self.step_scale not in STEP_SCALE_OPTIONS:
            raise ValueError("Unsupported Streamlines step-scale tuning value.")

    @property
    def step_scale_label(self) -> str:
        """Return the compact scale token used by diagnostic receipts."""

        index = STEP_SCALE_OPTIONS.index(self.step_scale)
        return STEP_SCALE_LABELS[index]

    @property
    def profile_id(self) -> StreamlinesProfileId:
        """Keep the legacy preview seam mapped to Global Flow Path."""

        return StreamlinesProfileId.GLOBAL_FLOW_PATH

    @property
    def geometry_contract(self) -> StreamlinesGeometryContract:
        """Return the effective Global contract represented by legacy callers."""

        return GlobalFlowPathTuning(
            seed_count=256,
            max_steps=self.max_steps,
            step_scale=self.step_scale,
        ).geometry_contract


@dataclass(frozen=True)
class GlobalFlowPathTuning:
    """Transient controls for one front-intake Global Flow Path preview."""

    seed_count: int = 256
    max_steps: int = 200
    step_scale: float = 2.0

    def __post_init__(self) -> None:
        if (
            self.seed_count not in GLOBAL_SEED_COUNT_OPTIONS
            or self.max_steps not in GLOBAL_MAX_STEPS_OPTIONS
            or self.step_scale not in STEP_SCALE_OPTIONS
        ):
            raise ValueError("Unsupported Global Flow Path tuning selection.")

    @property
    def profile_id(self) -> StreamlinesProfileId:
        return StreamlinesProfileId.GLOBAL_FLOW_PATH

    @property
    def step_scale_label(self) -> str:
        return STEP_SCALE_LABELS[STEP_SCALE_OPTIONS.index(self.step_scale)]

    @property
    def geometry_contract(self) -> StreamlinesGeometryContract:
        return _geometry_contract(
            profile_id=self.profile_id,
            seed_count=self.seed_count,
            section_count=1,
            max_steps=self.max_steps,
            step_scale=self.step_scale,
        )


@dataclass(frozen=True)
class VolumeCoverageTuning:
    """Transient controls for a multi-plane Volume Coverage preview."""

    section_count: int = 24
    seeds_per_section: int = 256
    max_steps: int = 20
    step_scale: float = 1.0

    def __post_init__(self) -> None:
        if (
            self.section_count not in VOLUME_SECTION_COUNT_OPTIONS
            or self.seeds_per_section not in VOLUME_SEEDS_PER_SECTION_OPTIONS
            or self.max_steps not in VOLUME_MAX_STEPS_OPTIONS
            or self.step_scale not in STEP_SCALE_OPTIONS
        ):
            raise ValueError("Unsupported Volume Coverage tuning selection.")

    @property
    def profile_id(self) -> StreamlinesProfileId:
        return StreamlinesProfileId.VOLUME_COVERAGE

    @property
    def step_scale_label(self) -> str:
        return STEP_SCALE_LABELS[STEP_SCALE_OPTIONS.index(self.step_scale)]

    @property
    def geometry_contract(self) -> StreamlinesGeometryContract:
        return _geometry_contract(
            profile_id=self.profile_id,
            seed_count=self.seeds_per_section,
            section_count=self.section_count,
            max_steps=self.max_steps,
            step_scale=self.step_scale,
        )


StreamlinesProfileTuning = GlobalFlowPathTuning | VolumeCoverageTuning
FINAL_GLOBAL_FLOW_PATH_CANDIDATE = GlobalFlowPathTuning()
FINAL_VOLUME_COVERAGE_CANDIDATE = VolumeCoverageTuning()
DEFAULT_GLOBAL_FLOW_PATH_TUNING = FINAL_GLOBAL_FLOW_PATH_CANDIDATE
DEFAULT_VOLUME_COVERAGE_TUNING = FINAL_VOLUME_COVERAGE_CANDIDATE


@dataclass(frozen=True)
class AcceptedStreamlinesCandidate:
    """Immutable session evidence used to reproduce one accepted Test B target."""

    profile_id: StreamlinesProfileId
    selection: StreamlinesProfileTuning
    geometry_contract: StreamlinesGeometryContract
    operator_type: str
    direction: str
    width_cell_multiplier: float
    signature: str

    @classmethod
    def capture(
        cls,
        selection: StreamlinesProfileTuning,
    ) -> "AcceptedStreamlinesCandidate":
        """Snapshot effective geometry values, independent of later UI changes."""

        contract = selection.geometry_contract
        payload = {
            "profile_id": contract.profile_id.value,
            "seed_count": contract.seed_count,
            "section_count": contract.section_count,
            "max_steps": contract.max_steps,
            "min_step_cell_multiplier": contract.min_step_cell_multiplier,
            "initial_step_cell_multiplier": contract.initial_step_cell_multiplier,
            "max_step_cell_multiplier": contract.max_step_cell_multiplier,
            "operator_type": PRODUCTION_STREAMLINES_PROFILE.operator_type,
            "direction": PRODUCTION_STREAMLINES_PROFILE.direction,
            "width_cell_multiplier": (
                PRODUCTION_STREAMLINES_PROFILE.width_cell_multiplier
            ),
        }
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return cls(
            profile_id=selection.profile_id,
            selection=selection,
            geometry_contract=contract,
            operator_type=PRODUCTION_STREAMLINES_PROFILE.operator_type,
            direction=PRODUCTION_STREAMLINES_PROFILE.direction,
            width_cell_multiplier=(
                PRODUCTION_STREAMLINES_PROFILE.width_cell_multiplier
            ),
            signature=hashlib.sha256(encoded).hexdigest(),
        )


class StreamlinesTuningState:
    """Keep the two developer selections independent for one UI session."""

    def __init__(self) -> None:
        self.global_flow_path = DEFAULT_GLOBAL_FLOW_PATH_TUNING
        self.volume_coverage = DEFAULT_VOLUME_COVERAGE_TUNING

    def selection_for(
        self,
        profile_id: StreamlinesProfileId,
    ) -> StreamlinesProfileTuning:
        profile_id = StreamlinesProfileId(profile_id)
        if profile_id is StreamlinesProfileId.GLOBAL_FLOW_PATH:
            return self.global_flow_path
        return self.volume_coverage

    def set_selection(self, selection: StreamlinesProfileTuning) -> None:
        if selection.profile_id is StreamlinesProfileId.GLOBAL_FLOW_PATH:
            self.global_flow_path = selection
        else:
            self.volume_coverage = selection


def _geometry_contract(
    *,
    profile_id: StreamlinesProfileId,
    seed_count: int,
    section_count: int,
    max_steps: int,
    step_scale: float,
) -> StreamlinesGeometryContract:
    return StreamlinesGeometryContract(
        profile_id=profile_id,
        seed_count=seed_count,
        section_count=section_count,
        max_steps=max_steps,
        min_step_cell_multiplier=BASE_MIN_STEP * step_scale,
        initial_step_cell_multiplier=BASE_INITIAL_STEP * step_scale,
        max_step_cell_multiplier=BASE_MAX_STEP * step_scale,
    )


if (
    FINAL_GLOBAL_FLOW_PATH_CANDIDATE.geometry_contract
    != FINAL_GLOBAL_FLOW_PATH_GEOMETRY_CONTRACT
    or FINAL_VOLUME_COVERAGE_CANDIDATE.geometry_contract
    != FINAL_VOLUME_COVERAGE_GEOMETRY_CONTRACT
):
    raise RuntimeError("Final Streamlines tuning candidates changed geometry contract.")


def global_tuning_from_indices(
    seed_count_index: int,
    max_steps_index: int,
    step_scale_index: int,
) -> GlobalFlowPathTuning:
    """Resolve one validated Global UI selection."""

    if not (
        0 <= seed_count_index < len(GLOBAL_SEED_COUNT_OPTIONS)
        and 0 <= max_steps_index < len(GLOBAL_MAX_STEPS_OPTIONS)
        and 0 <= step_scale_index < len(STEP_SCALE_OPTIONS)
    ):
        raise ValueError("Global Flow Path selection is out of range.")
    try:
        return GlobalFlowPathTuning(
            seed_count=GLOBAL_SEED_COUNT_OPTIONS[seed_count_index],
            max_steps=GLOBAL_MAX_STEPS_OPTIONS[max_steps_index],
            step_scale=STEP_SCALE_OPTIONS[step_scale_index],
        )
    except IndexError as error:
        raise ValueError("Global Flow Path selection is out of range.") from error


def volume_tuning_from_indices(
    section_count_index: int,
    seeds_per_section_index: int,
    max_steps_index: int,
    step_scale_index: int,
) -> VolumeCoverageTuning:
    """Resolve one validated Volume UI selection."""

    if not (
        0 <= section_count_index < len(VOLUME_SECTION_COUNT_OPTIONS)
        and 0 <= seeds_per_section_index < len(VOLUME_SEEDS_PER_SECTION_OPTIONS)
        and 0 <= max_steps_index < len(VOLUME_MAX_STEPS_OPTIONS)
        and 0 <= step_scale_index < len(STEP_SCALE_OPTIONS)
    ):
        raise ValueError("Volume Coverage selection is out of range.")
    try:
        return VolumeCoverageTuning(
            section_count=VOLUME_SECTION_COUNT_OPTIONS[section_count_index],
            seeds_per_section=(
                VOLUME_SEEDS_PER_SECTION_OPTIONS[seeds_per_section_index]
            ),
            max_steps=VOLUME_MAX_STEPS_OPTIONS[max_steps_index],
            step_scale=STEP_SCALE_OPTIONS[step_scale_index],
        )
    except IndexError as error:
        raise ValueError("Volume Coverage selection is out of range.") from error


PHASE44A_STREAMLINES_CANDIDATE = StreamlinesGeometryTuning(
    max_steps=200,
    step_scale=2.0,
)
BASELINE_STREAMLINES_TUNING = PHASE44A_STREAMLINES_CANDIDATE


def streamlines_tuning_from_indices(
    max_steps_index: int,
    step_scale_index: int,
) -> StreamlinesGeometryTuning:
    """Map the two OmniUI indices to one validated transient selection."""

    if not 0 <= max_steps_index < len(MAX_STEPS_OPTIONS):
        raise ValueError("Streamlines max-steps selection is out of range.")
    if not 0 <= step_scale_index < len(STEP_SCALE_OPTIONS):
        raise ValueError("Streamlines step-scale selection is out of range.")
    try:
        return StreamlinesGeometryTuning(
            max_steps=MAX_STEPS_OPTIONS[max_steps_index],
            step_scale=STEP_SCALE_OPTIONS[step_scale_index],
        )
    except IndexError as error:
        raise ValueError("Streamlines tuning selection is out of range.") from error


def streamlines_preview_workload_from_index(index: int) -> str:
    """Resolve one explicit four-workload preview selection."""

    if not 0 <= index < len(PREVIEW_WORKLOAD_OPTIONS):
        raise ValueError("Streamlines preview workload is out of range.")
    return PREVIEW_WORKLOAD_OPTIONS[index]


@dataclass(frozen=True)
class StreamlinesGeometryMetrics:
    """Geometry reach evidence calculated from one real BasisCurves snapshot."""

    curve_count: int
    point_count: int
    points_per_curve_min: int
    points_per_curve_median: float
    points_per_curve_max: int
    curves_hitting_max_steps: int | None
    arc_length_median: float
    arc_length_max: float
    rearward_reach_median: float
    curves_reaching_75pct_domain_depth: int
    curves_reaching_90pct_domain_depth: int
    arc_length_min: float = 0.0


@dataclass(frozen=True)
class StreamlinesTuningEvidence:
    """Complete geometry and bounded performance receipt for one preview."""

    workload: str
    dataset_identity: str
    sample_index: int
    source_vti: str
    seed_columns: int
    seed_rows: int
    seed_points: int
    selection: StreamlinesGeometryTuning | StreamlinesProfileTuning
    authored_min_step: float
    authored_initial_step: float
    authored_max_step: float
    source_cell_diagonal_m: float
    metrics: StreamlinesGeometryMetrics
    operator_execution_ms: float
    preview_total_ms: float
    viewport_fps: float | None = None
    gpu_used_gib: float | None = None
    process_used_gib: float | None = None
    performance_settle_seconds: float = 0.0
    performance_sample_window_seconds: float = 0.0
    performance_samples: int = 0
    viewport_fps_average: float | None = None
    viewport_fps_minimum: float | None = None
    frame_time_ms_current: float | None = None
    frame_time_ms_average: float | None = None
    candidate_source: str = "LIVE_TUNING"
    accepted_candidate_signature: str | None = None
    live_tuning_ignored: bool = False
    profile_id: StreamlinesProfileId = StreamlinesProfileId.GLOBAL_FLOW_PATH
    section_count: int = 1
    seeds_per_section: int = 0
    sections_with_curves: int | None = None
    curves_per_section_min: int | None = None
    curves_per_section_median: float | None = None
    curves_per_section_max: int | None = None

    @property
    def approximate_min_step_m(self) -> float:
        """Return the configured lower step bound for this uniform source."""

        return self.authored_min_step * self.source_cell_diagonal_m

    @property
    def approximate_initial_step_m(self) -> float:
        """Return the configured initial step for this uniform source."""

        return self.authored_initial_step * self.source_cell_diagonal_m

    @property
    def approximate_max_step_m(self) -> float:
        """Return the configured upper step bound for this uniform source."""

        return self.authored_max_step * self.source_cell_diagonal_m


def source_cell_diagonal_m(
    spacing: tuple[float, float, float],
    *,
    stage_meters_per_unit: float,
) -> float:
    """Convert one uniform-source cell diagonal from stage units to metres."""

    if (
        len(spacing) != 3
        or not math.isfinite(stage_meters_per_unit)
        or stage_meters_per_unit <= 0.0
        or any(not math.isfinite(value) or value <= 0.0 for value in spacing)
    ):
        raise ValueError("Streamlines source spacing must be finite and positive.")
    diagonal_stage_units = math.sqrt(sum(value * value for value in spacing))
    return diagonal_stage_units * stage_meters_per_unit


def calculate_streamlines_geometry_metrics(
    point_positions: tuple[tuple[float, float, float], ...],
    curve_vertex_counts: tuple[int, ...],
    domain_bounds: tuple[
        tuple[float, float, float],
        tuple[float, float, float],
    ],
) -> StreamlinesGeometryMetrics:
    """Measure curve density and reach along Case 03's front(+Z)-to-rear axis."""

    if (
        not curve_vertex_counts
        or any(count <= 0 for count in curve_vertex_counts)
        or sum(curve_vertex_counts) != len(point_positions)
    ):
        raise ValueError("Streamlines geometry topology is incomplete.")
    minimum, maximum = domain_bounds
    domain_depth = float(maximum[2]) - float(minimum[2])
    if not math.isfinite(domain_depth) or domain_depth <= 0.0:
        raise ValueError("Streamlines domain depth must be positive.")

    curves = []
    offset = 0
    for count in curve_vertex_counts:
        curves.append(point_positions[offset : offset + count])
        offset += count
    arc_lengths = tuple(_curve_arc_length(curve) for curve in curves)
    rearward_reaches = tuple(
        max(0.0, float(curve[0][2]) - min(point[2] for point in curve))
        for curve in curves
    )
    depth_75_z = float(maximum[2]) - 0.75 * domain_depth
    depth_90_z = float(maximum[2]) - 0.90 * domain_depth
    minimum_z_values = tuple(min(point[2] for point in curve) for curve in curves)
    return StreamlinesGeometryMetrics(
        curve_count=len(curves),
        point_count=len(point_positions),
        points_per_curve_min=min(curve_vertex_counts),
        points_per_curve_median=float(median(curve_vertex_counts)),
        points_per_curve_max=max(curve_vertex_counts),
        # Kit-CAE exposes vertices, not an authoritative per-curve step count.
        curves_hitting_max_steps=None,
        arc_length_min=min(arc_lengths),
        arc_length_median=float(median(arc_lengths)),
        arc_length_max=max(arc_lengths),
        rearward_reach_median=float(median(rearward_reaches)),
        curves_reaching_75pct_domain_depth=sum(
            value <= depth_75_z for value in minimum_z_values
        ),
        curves_reaching_90pct_domain_depth=sum(
            value <= depth_90_z for value in minimum_z_values
        ),
    )


def format_streamlines_tuning_complete(
    evidence: StreamlinesTuningEvidence,
) -> str:
    """Format one compact successful interactive tuning receipt."""

    selection = evidence.selection
    metrics = evidence.metrics
    common = (
        "DTRS STREAMLINES | PROFILE_CANDIDATE | COMPLETE",
        f"profile={evidence.profile_id.value}",
        f"workload={evidence.workload}",
        f"dataset={evidence.dataset_identity}",
        f"sample_index={evidence.sample_index}",
        f"source_vti={evidence.source_vti}",
        f"columns={evidence.seed_columns}",
        f"rows={evidence.seed_rows}",
        f"seed_points={evidence.seed_points}",
        f"section_count={evidence.section_count}",
        f"seeds_per_section={evidence.seeds_per_section}",
        f"max_steps={selection.max_steps}",
        f"step_scale={selection.step_scale_label}",
        "authored_cell_relative:",
        f"  min_step={evidence.authored_min_step:.9g}",
        f"  initial_step={evidence.authored_initial_step:.9g}",
        f"  max_step={evidence.authored_max_step:.9g}",
        f"source_cell_diagonal_m={evidence.source_cell_diagonal_m:.9g}",
        "approximate_physical_step_m:",
        f"  min={evidence.approximate_min_step_m:.9g}",
        f"  initial={evidence.approximate_initial_step_m:.9g}",
        f"  max={evidence.approximate_max_step_m:.9g}",
        (
            "physical_step_semantics=configured adaptive bounds; "
            "not measured displacement"
        ),
        f"curves={metrics.curve_count}",
        f"points={metrics.point_count}",
        f"points_per_curve_min={metrics.points_per_curve_min}",
        f"points_per_curve_median={metrics.points_per_curve_median:g}",
        f"points_per_curve_max={metrics.points_per_curve_max}",
        "curves_hitting_max_steps=" f"{_optional(metrics.curves_hitting_max_steps)}",
        f"arc_length_min={metrics.arc_length_min:.9g}",
        f"arc_length_median={metrics.arc_length_median:.9g}",
        f"arc_length_max={metrics.arc_length_max:.9g}",
        f"rearward_reach_median={metrics.rearward_reach_median:.9g}",
        "curves_reaching_75pct_domain_depth="
        f"{metrics.curves_reaching_75pct_domain_depth}",
        "curves_reaching_90pct_domain_depth="
        f"{metrics.curves_reaching_90pct_domain_depth}",
        f"operator_execution_ms={evidence.operator_execution_ms:.3f}",
        f"preview_total_ms={evidence.preview_total_ms:.3f}",
        "performance_settle_seconds=" f"{evidence.performance_settle_seconds:g}",
        "performance_sample_window_seconds="
        f"{evidence.performance_sample_window_seconds:g}",
        f"performance_samples={evidence.performance_samples}",
        f"viewport_fps={_optional(evidence.viewport_fps)}",
        f"viewport_fps_current={_optional(evidence.viewport_fps)}",
        "viewport_fps_average=" f"{_optional(evidence.viewport_fps_average)}",
        "viewport_fps_minimum=" f"{_optional(evidence.viewport_fps_minimum)}",
        "frame_time_ms_current=" f"{_optional(evidence.frame_time_ms_current)}",
        "frame_time_ms_average=" f"{_optional(evidence.frame_time_ms_average)}",
        f"candidate_source={evidence.candidate_source}",
        "accepted_candidate_signature="
        f"{_optional(evidence.accepted_candidate_signature)}",
        f"live_tuning_ignored={evidence.live_tuning_ignored}",
        f"gpu_used_gib={_optional(evidence.gpu_used_gib)}",
        f"process_used_gib={_optional(evidence.process_used_gib)}",
        "cache_build=0",
        "cache_rebuild=0",
    )
    if evidence.profile_id is StreamlinesProfileId.VOLUME_COVERAGE:
        profile_metrics = (
            f"sections_with_curves={_optional(evidence.sections_with_curves)}",
            "curves_per_section_min=" f"{_optional(evidence.curves_per_section_min)}",
            "curves_per_section_median="
            f"{_optional(evidence.curves_per_section_median)}",
            "curves_per_section_max=" f"{_optional(evidence.curves_per_section_max)}",
        )
    else:
        profile_metrics = ()
    return "\n".join((*common, *profile_metrics))


def curves_per_section_from_starts(
    point_positions: tuple[tuple[float, float, float], ...],
    curve_vertex_counts: tuple[int, ...],
    section_planes: tuple[float, ...],
) -> tuple[int, ...]:
    """Classify curves by nearest known section using each curve start Z."""

    if not section_planes:
        raise ValueError("Volume Coverage section planes are required.")
    starts = []
    offset = 0
    for count in curve_vertex_counts:
        if count <= 0 or offset >= len(point_positions):
            raise ValueError("Volume Coverage curve topology is incomplete.")
        starts.append(point_positions[offset])
        offset += count
    counts = [0] * len(section_planes)
    for point in starts:
        section = min(
            range(len(section_planes)),
            key=lambda index: abs(float(point[2]) - section_planes[index]),
        )
        counts[section] += 1
    return tuple(counts)


def format_streamlines_tuning_failure(
    selection: StreamlinesGeometryTuning,
    reason: str,
) -> str:
    """Format one exact failed interactive tuning receipt."""

    return "\n".join(
        (
            "DTRS STREAMLINES | PROFILE_TUNING | FAIL",
            f"max_steps={selection.max_steps}",
            f"step_scale={selection.step_scale_label}",
            f"reason={reason}",
        )
    )


def _curve_arc_length(
    curve: tuple[tuple[float, float, float], ...],
) -> float:
    """Sum Euclidean segment lengths without interpolating curve points."""

    return sum(
        math.dist(previous, current) for previous, current in zip(curve, curve[1:])
    )


def _optional(value: float | int | None) -> str:
    """Represent missing instrumentation honestly in a tuning receipt."""

    if value is None:
        return "unavailable"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)
