"""Structured diagnostics for DTRS velocity-source and operator state."""

from __future__ import annotations

from dataclasses import dataclass

from digital_twin_runtime_suite.app.flow.static_source import (
    StaticVelocitySourceCleanup,
    StaticVelocitySourceDescriptor,
)
from digital_twin_runtime_suite.app.streamlines.proof import (
    StreamlinesOperatorCleanup,
    StreamlinesOperatorRequest,
    is_create_command_placeholder_geometry,
)


@dataclass(frozen=True)
class StaticSourceRuntimeEvidence:
    """Programmatic runtime-state evidence without manual USD tree inspection."""

    authored_prims: tuple[str, ...]
    duplicate_runtime_prim_count: int
    flow_environment: str
    dataset_emitter: str
    boundary_emitter: str
    smoke_injectors: str
    streamlines_operator: str
    temporal_sequence: str
    timeline_playback: str

    @property
    def clean(self) -> bool:
        """Return whether forbidden runtime state is absent after VTI import."""

        return (
            self.duplicate_runtime_prim_count == 0
            and self.flow_environment == "ABSENT"
            and self.dataset_emitter == "ABSENT"
            and self.boundary_emitter == "ABSENT"
            and self.smoke_injectors == "ABSENT"
            and self.streamlines_operator == "ABSENT"
            and self.temporal_sequence == "ABSENT"
            and self.timeline_playback == "INACTIVE"
        )


def require_clean_static_source_runtime(
    evidence: StaticSourceRuntimeEvidence,
) -> None:
    """Reject forbidden runtime state independently of diagnostic formatting."""

    if not evidence.clean:
        raise RuntimeError(
            "Velocity-source import detected forbidden runtime state; "
            "review the DTRS STREAMLINES acceptance block."
        )


@dataclass(frozen=True)
class StreamlinesOperatorEvidence:
    """Programmatic evidence that one source produced real BasisCurves."""

    authored_prims: tuple[str, ...]
    duplicate_runtime_prim_count: int
    operator_type: str
    operator_completion_count_before: int
    operator_completion_count: int
    fresh_execution: bool
    operator_execution_success: bool | None
    authored_usd_point_count: int
    authored_usd_curve_vertex_counts: tuple[int, ...]
    authored_usd_placeholder_geometry: bool
    runtime_usdrt_basis_curves: bool
    runtime_curve_count: int
    runtime_point_count: int
    runtime_curve_vertex_counts: tuple[int, ...]
    runtime_point_positions: tuple[tuple[float, float, float], ...]
    source_binding: tuple[str, ...]
    seed_binding: tuple[str, ...]
    velocity_binding: tuple[str, ...]
    direction: str
    configured_width: float
    render_width_range: tuple[float, float] | None
    runtime_curve_bounds: (
        tuple[tuple[float, float, float], tuple[float, float, float]] | None
    )
    source_world_bounds: tuple[tuple[float, float, float], tuple[float, float, float]]
    runtime_curve_bounds_within_source: bool
    runtime_placeholder_geometry: bool
    point_head: tuple[tuple[float, float, float], ...]
    point_tail: tuple[tuple[float, float, float], ...]
    first_curve_start: tuple[float, float, float] | None
    first_curve_end: tuple[float, float, float] | None
    first_curve_travel: tuple[float, float, float] | None
    first_curve_seed_endpoint: str
    first_curve_seed_distance: float | None
    flow_environment: str
    dataset_emitter: str
    boundary_emitter: str
    smoke_injectors: str
    temporal_sequence: str
    timeline_playback: str
    authored_usd_fallback_visibility: str = "UNKNOWN"
    runtime_usdrt_visibility: str = "UNKNOWN"
    viewport_preview_path: str | None = None
    viewport_preview_curve_count: int = 0
    viewport_preview_point_count: int = 0
    viewport_preview_matches_runtime: bool = False

    def is_valid_for(self, request: StreamlinesOperatorRequest) -> bool:
        """Return whether one completed operator has the required bindings."""

        return (
            self.operator_type == "BasisCurves"
            and self.fresh_execution
            and self.operator_execution_success is True
            and self.runtime_usdrt_basis_curves
            and self.runtime_curve_count > 0
            and self.runtime_point_count > 4
            and not self.runtime_placeholder_geometry
            and self.runtime_curve_bounds_within_source
            and self.authored_usd_fallback_visibility == "invisible"
            and self.runtime_usdrt_visibility == "inherited"
            and self.viewport_preview_path is not None
            and self.viewport_preview_curve_count == self.runtime_curve_count
            and self.viewport_preview_point_count == self.runtime_point_count
            and self.viewport_preview_matches_runtime
            and self.source_binding == (request.dataset_prim_path,)
            and self.seed_binding == (request.seed_path,)
            and self.velocity_binding == (request.velocity_field_prim_path,)
            and self.direction == request.direction
            and self.duplicate_runtime_prim_count == 0
            and self.flow_environment == "ABSENT"
            and self.dataset_emitter == "ABSENT"
            and self.boundary_emitter == "ABSENT"
            and self.smoke_injectors == "ABSENT"
            and self.temporal_sequence == "ABSENT"
            and self.timeline_playback == "INACTIVE"
        )


@dataclass(frozen=True)
class StreamlinesBindingEvidence:
    """Effective input contract captured before enabling the operator."""

    operator_enabled: bool
    source_relationship: str
    source_targets: tuple[str, ...]
    seed_relationship: str
    seed_targets: tuple[str, ...]
    velocity_relationship: str
    velocity_targets: tuple[str, ...]
    velocity_mode: str
    resolved_velocity_field_names: tuple[str, ...]


def inspect_streamlines_bindings(
    stage,
    *,
    operator_prim,
    dataset_prim,
    cae_viz,
    cae_usd_utils,
) -> StreamlinesBindingEvidence:
    """Capture the exact relationship-based selection contract before enable.

    The installed Kit-CAE FieldSelectionAPI resolves target prims to dataset
    field names. It does not use a separate ``fieldNames`` attribute.
    """

    source_api = cae_viz.DatasetSelectionAPI(operator_prim, "source")
    seed_api = cae_viz.DatasetSelectionAPI(operator_prim, "seeds")
    velocity_api = cae_viz.FieldSelectionAPI(operator_prim, "velocities")
    velocity_targets = _relation_target_paths(velocity_api.GetTargetRel())
    field_names = tuple(
        cae_usd_utils.get_field_name(
            dataset_prim,
            stage.GetPrimAtPath(target_path),
        )
        for target_path in velocity_targets
    )
    return StreamlinesBindingEvidence(
        operator_enabled=bool(
            cae_viz.OperatorAPI(operator_prim).GetEnabledAttr().Get()
        ),
        source_relationship=str(source_api.GetTargetRel().GetName()),
        source_targets=_relation_target_paths(source_api.GetTargetRel()),
        seed_relationship=str(seed_api.GetTargetRel().GetName()),
        seed_targets=_relation_target_paths(seed_api.GetTargetRel()),
        velocity_relationship=str(velocity_api.GetTargetRel().GetName()),
        velocity_targets=velocity_targets,
        velocity_mode=str(velocity_api.GetModeAttr().Get()),
        resolved_velocity_field_names=field_names,
    )


def format_streamlines_binding_evidence(
    evidence: StreamlinesBindingEvidence,
) -> str:
    """Format the pre-enable input contract without requiring USD tree inspection."""

    return "\n".join(
        (
            "DTRS STREAMLINES | OPERATOR_BINDINGS | READY",
            "",
            f"operator_enabled={evidence.operator_enabled}",
            "",
            "source:",
            f"  relationship={evidence.source_relationship}",
            f"  targets={evidence.source_targets}",
            "seeds:",
            f"  relationship={evidence.seed_relationship}",
            f"  targets={evidence.seed_targets}",
            "velocities:",
            f"  relationship={evidence.velocity_relationship}",
            f"  targets={evidence.velocity_targets}",
            f"  mode={evidence.velocity_mode}",
            f"  resolved_dataset_fields={evidence.resolved_velocity_field_names}",
            "  fieldNames_attribute=NOT_AUTHORED (relationship target contract)",
        )
    )


def inspect_static_source_runtime(
    stage,
    *,
    import_root_path: str,
    field_prim,
    cae_vtk,
    timeline,
) -> StaticSourceRuntimeEvidence:
    """Collect the static-source acceptance state from live DTRS-owned paths.

    The authored list deliberately traverses only this test's import root. The
    separate checks below still query each forbidden runtime owner directly.
    """

    source_root = stage.GetPrimAtPath(import_root_path)
    authored_prims = _runtime_subtree_paths(source_root)
    temporal_sequence = _temporal_sequence_state(field_prim, cae_vtk)
    return StaticSourceRuntimeEvidence(
        authored_prims=authored_prims,
        duplicate_runtime_prim_count=len(authored_prims) - len(set(authored_prims)),
        flow_environment=_prim_state(stage, "/DTRS_KitCAE/FlowSimulation"),
        dataset_emitter=_prim_state(stage, "/DTRS_KitCAE/DataSetEmitter"),
        boundary_emitter=_prim_state(stage, "/DTRS_KitCAE/BoundaryEmitter"),
        smoke_injectors=_prim_state(
            stage,
            "/DTRS_KitCAE/AirflowTracerEmitters",
        ),
        streamlines_operator=_prim_state(stage, "/DTRS_KitCAE/Streamlines"),
        temporal_sequence=temporal_sequence,
        timeline_playback="ACTIVE" if timeline.is_playing() else "INACTIVE",
    )


def format_static_source_acceptance(
    descriptor: StaticVelocitySourceDescriptor,
    cleanup: StaticVelocitySourceCleanup,
    evidence: StaticSourceRuntimeEvidence,
) -> str:
    """Format one concise human-readable imported-source diagnostic block."""

    cleanup_result = (
        "PASS (previous static source replaced)"
        if cleanup.previous_source_present
        else "PASS (no previous static source)"
    )
    result = "PASS" if cleanup.success and evidence.clean else "FAIL"
    return "\n".join(
        (
            f"DTRS STREAMLINES | STATIC_SOURCE_TEST | {result}",
            "",
            f"workload={descriptor.workload}",
            f"dataset={descriptor.dataset_identity}",
            f"sample_index={descriptor.sample_index}",
            f"source_vti={descriptor.vti_path}",
            f"dataset_prim_path={descriptor.dataset_prim_path}",
            f"velocity_field_prim_path={descriptor.velocity_field_prim_path}",
            "",
            "spatial:",
            f"  dimensions={descriptor.dimensions}",
            f"  spacing={descriptor.spacing}",
            f"  source_origin={descriptor.source_origin}",
            f"  effective_origin={descriptor.origin}",
            f"  world_bounds={descriptor.world_bounds}",
            f"  stage_meters_per_unit={descriptor.stage_meters_per_unit:g}",
            "",
            "runtime:",
            f"  authored_prims={evidence.authored_prims}",
            f"  FlowEnvironment={evidence.flow_environment}",
            f"  DataSetEmitter={evidence.dataset_emitter}",
            f"  BoundaryEmitter={evidence.boundary_emitter}",
            f"  SmokeInjectors={evidence.smoke_injectors}",
            f"  StreamlinesOperator={evidence.streamlines_operator}",
            f"  TemporalSequence={evidence.temporal_sequence}",
            f"  TimelinePlayback={evidence.timeline_playback}",
            "",
            "cleanup:",
            f"  previous_static_runtime_cleanup={cleanup_result}",
            f"  duplicate_runtime_prim_count={evidence.duplicate_runtime_prim_count}",
            "",
            f"result={result}",
        )
    )


def inspect_streamlines_operator(
    stage,
    *,
    request: StreamlinesOperatorRequest,
    field_prim,
    cae_viz,
    cae_vtk,
    cae_usd_utils,
    UsdGeom,
    UsdGeomRT,
    wp,
    timeline,
    operator_completion_count_before: int,
    operator_completion_count: int,
    fresh_execution: bool,
    operator_execution_success: bool | None,
    source_world_bounds: tuple[tuple[float, float, float], tuple[float, float, float]],
) -> StreamlinesOperatorEvidence:
    """Read authored diagnostics and computed UsdRT geometry from known paths.

    Kit-CAE deliberately leaves the creation command's four-point USD value in
    place. The Streamlines operator writes its computed points into Fabric, so
    Runtime code accepts only the UsdRT snapshot captured after ``operator_end``.
    """

    operator_prim = stage.GetPrimAtPath(request.operator_path)
    seed_prim = stage.GetPrimAtPath(request.seed_path)
    if not operator_prim or not operator_prim.IsValid():
        raise RuntimeError(
            f"Streamlines operator is unavailable: {request.operator_path}."
        )
    if not seed_prim or not seed_prim.IsValid():
        raise RuntimeError(f"Streamlines seed is unavailable: {request.seed_path}.")
    authored_curves = UsdGeom.BasisCurves(operator_prim)
    authored_points = authored_curves.GetPointsAttr().Get() or ()
    authored_vertex_counts = authored_curves.GetCurveVertexCountsAttr().Get() or ()
    authored_point_positions = _point_positions(authored_points)
    authored_counts = tuple(int(count) for count in authored_vertex_counts)
    runtime_curves = UsdGeomRT.BasisCurves(cae_usd_utils.get_prim_rt(operator_prim))
    runtime_usdrt_basis_curves = runtime_curves.GetPrim().IsValid()
    runtime_point_positions = (
        _usdrt_point_positions(runtime_curves.GetPointsAttr(), wp)
        if runtime_usdrt_basis_curves
        else ()
    )
    runtime_vertex_counts = (
        _usdrt_curve_vertex_counts(runtime_curves.GetCurveVertexCountsAttr(), wp)
        if runtime_usdrt_basis_curves
        else ()
    )
    runtime_curve_bounds = _point_bounds(runtime_point_positions)
    first_curve = (
        runtime_point_positions[: runtime_vertex_counts[0]]
        if runtime_vertex_counts
        else ()
    )
    first_curve_start = first_curve[0] if first_curve else None
    first_curve_end = first_curve[-1] if first_curve else None
    first_curve_travel = (
        _subtract_points(first_curve_end, first_curve_start)
        if first_curve_start and first_curve_end
        else None
    )
    seed_endpoint, seed_distance = _nearest_seed_endpoint(
        request.seed_points or (request.seed_center,),
        first_curve_start,
        first_curve_end,
    )
    widths = _primvar_values(UsdGeom.PrimvarsAPI(operator_prim).GetPrimvar("widths"))
    source_binding = _relation_target_paths(
        cae_viz.DatasetSelectionAPI(operator_prim, "source").GetTargetRel()
    )
    seed_binding = _relation_target_paths(
        cae_viz.DatasetSelectionAPI(operator_prim, "seeds").GetTargetRel()
    )
    velocity_binding = _relation_target_paths(
        cae_viz.FieldSelectionAPI(operator_prim, "velocities").GetTargetRel()
    )
    authored_prims = (
        *_runtime_subtree_paths(
            stage.GetPrimAtPath(request.operator_path.rsplit("/", 1)[0])
        ),
        *_runtime_subtree_paths(
            stage.GetPrimAtPath(request.seed_path.rsplit("/", 1)[0])
        ),
    )
    return StreamlinesOperatorEvidence(
        authored_prims=authored_prims,
        duplicate_runtime_prim_count=(len(authored_prims) - len(set(authored_prims))),
        operator_type=str(operator_prim.GetTypeName()),
        operator_completion_count_before=operator_completion_count_before,
        operator_completion_count=operator_completion_count,
        fresh_execution=fresh_execution,
        operator_execution_success=operator_execution_success,
        authored_usd_point_count=len(authored_point_positions),
        authored_usd_curve_vertex_counts=authored_counts,
        authored_usd_placeholder_geometry=is_create_command_placeholder_geometry(
            authored_point_positions,
            authored_counts,
        ),
        runtime_usdrt_basis_curves=runtime_usdrt_basis_curves,
        runtime_curve_count=len(runtime_vertex_counts),
        runtime_point_count=len(runtime_point_positions),
        runtime_curve_vertex_counts=runtime_vertex_counts,
        runtime_point_positions=runtime_point_positions,
        source_binding=source_binding,
        seed_binding=seed_binding,
        velocity_binding=velocity_binding,
        direction=str(cae_viz.StreamlinesAPI(operator_prim).GetDirectionAttr().Get()),
        configured_width=float(
            cae_viz.StreamlinesAPI(operator_prim).GetWidthAttr().Get()
        ),
        render_width_range=_value_range(widths),
        runtime_curve_bounds=runtime_curve_bounds,
        source_world_bounds=source_world_bounds,
        runtime_curve_bounds_within_source=_bounds_within_source(
            runtime_curve_bounds,
            source_world_bounds,
        ),
        runtime_placeholder_geometry=is_create_command_placeholder_geometry(
            runtime_point_positions,
            runtime_vertex_counts,
        ),
        point_head=runtime_point_positions[:3],
        point_tail=runtime_point_positions[-3:],
        first_curve_start=first_curve_start,
        first_curve_end=first_curve_end,
        first_curve_travel=first_curve_travel,
        first_curve_seed_endpoint=seed_endpoint,
        first_curve_seed_distance=seed_distance,
        flow_environment=_prim_state(stage, "/DTRS_KitCAE/FlowSimulation"),
        dataset_emitter=_prim_state(stage, "/DTRS_KitCAE/DataSetEmitter"),
        boundary_emitter=_prim_state(stage, "/DTRS_KitCAE/BoundaryEmitter"),
        smoke_injectors=_prim_state(
            stage,
            "/DTRS_KitCAE/AirflowTracerEmitters",
        ),
        temporal_sequence=_temporal_sequence_state(field_prim, cae_vtk),
        timeline_playback="ACTIVE" if timeline.is_playing() else "INACTIVE",
    )


def format_streamlines_operator_evidence(
    descriptor: StaticVelocitySourceDescriptor,
    request: StreamlinesOperatorRequest,
    cleanup: StreamlinesOperatorCleanup,
    evidence: StreamlinesOperatorEvidence,
    *,
    verbose: bool = False,
) -> str:
    """Format concise operator evidence; expose point arrays only on request."""

    result = "PASS" if cleanup.success and evidence.is_valid_for(request) else "FAIL"
    cleanup_result = (
        "PASS (previous proof replaced)"
        if cleanup.previous_runtime_present
        else "PASS (no previous proof)"
    )
    lines = [
        f"DTRS STREAMLINES | STATIC_OPERATOR_PROOF | {result}",
        "",
        f"workload={descriptor.workload}",
        f"dataset={descriptor.dataset_identity}",
        f"sample_index={descriptor.sample_index}",
        "",
        "operator:",
        f"  path={request.operator_path}",
        f"  direction={evidence.direction}",
        f"  completion_count_before={evidence.operator_completion_count_before}",
        f"  completion_count_after={evidence.operator_completion_count}",
        f"  fresh_execution={evidence.fresh_execution}",
        f"  execution_success={evidence.operator_execution_success}",
        "",
        "geometry:",
        (
            "  authored_usd_placeholder_geometry="
            f"{evidence.authored_usd_placeholder_geometry}"
        ),
        (
            "  authored_usd_fallback_visibility="
            f"{evidence.authored_usd_fallback_visibility}"
        ),
        f"  runtime_usdrt_basis_curves={evidence.runtime_usdrt_basis_curves}",
        f"  runtime_usdrt_visibility={evidence.runtime_usdrt_visibility}",
        f"  runtime_curve_count={evidence.runtime_curve_count}",
        f"  runtime_point_count={evidence.runtime_point_count}",
        (
            "  points_per_curve_min_mean_max="
            f"{_points_per_curve_summary(evidence.runtime_curve_vertex_counts)}"
        ),
        f"  runtime_bounds={evidence.runtime_curve_bounds}",
        f"  bounds_within_source={evidence.runtime_curve_bounds_within_source}",
        f"  configured_width={evidence.configured_width:.6g}",
        "",
        "viewport_preview:",
        "  source=confirmed UsdRT snapshot",
        f"  path={evidence.viewport_preview_path}",
        f"  curve_count={evidence.viewport_preview_curve_count}",
        f"  point_count={evidence.viewport_preview_point_count}",
        f"  matches_runtime={evidence.viewport_preview_matches_runtime}",
        "",
        "direction:",
        f"  first_curve_start={evidence.first_curve_start}",
        f"  first_curve_end={evidence.first_curve_end}",
        f"  direction_first_curve={evidence.first_curve_travel}",
        f"  seed_nearest_endpoint={evidence.first_curve_seed_endpoint}",
        f"  seed_nearest_distance={evidence.first_curve_seed_distance}",
        "",
        "runtime:",
        f"  FlowEnvironment={evidence.flow_environment}",
        f"  DataSetEmitter={evidence.dataset_emitter}",
        f"  BoundaryEmitter={evidence.boundary_emitter}",
        f"  SmokeInjectors={evidence.smoke_injectors}",
        f"  TemporalSequence={evidence.temporal_sequence}",
        f"  TimelinePlayback={evidence.timeline_playback}",
        "",
        "cleanup:",
        f"  previous_proof_runtime_cleanup={cleanup_result}",
        f"  duplicate_runtime_prim_count={evidence.duplicate_runtime_prim_count}",
    ]
    if verbose:
        lines.extend(
            (
                "",
                "verbose_geometry:",
                (
                    "  authored_usd_curve_vertex_counts="
                    f"{evidence.authored_usd_curve_vertex_counts}"
                ),
                "  runtime_curve_vertex_counts="
                f"{evidence.runtime_curve_vertex_counts}",
                f"  runtime_point_head={evidence.point_head}",
                f"  runtime_point_tail={evidence.point_tail}",
            )
        )
    lines.extend(("", f"result={result}"))
    return "\n".join(lines)


def _points_per_curve_summary(
    curve_vertex_counts: tuple[int, ...],
) -> tuple[int, int | float, int] | None:
    """Summarize repeated curve sizes without flooding a human acceptance log."""

    if not curve_vertex_counts:
        return None
    minimum = min(curve_vertex_counts)
    maximum = max(curve_vertex_counts)
    mean = sum(curve_vertex_counts) / len(curve_vertex_counts)
    return minimum, int(mean) if mean.is_integer() else round(mean, 3), maximum


def _prim_state(stage, path: str) -> str:
    prim = stage.GetPrimAtPath(path)
    return "PRESENT" if prim and prim.IsValid() else "ABSENT"


def _runtime_subtree_paths(root_prim) -> tuple[str, ...]:
    """Return one DTRS-owned prim root and its descendants via supported USD APIs.

    ``Usd.Prim`` exposes ``GetChildren()`` but not ``GetDescendants()`` in the
    installed bindings.  A small recursive walk also avoids traversing unrelated
    scene content when the VTI import reports only its own source state.
    """

    if not root_prim or not root_prim.IsValid():
        return ()

    paths: list[str] = []

    def visit(prim) -> None:
        if not prim or not prim.IsValid():
            return
        paths.append(str(prim.GetPath()))
        for child in prim.GetChildren():
            visit(child)

    visit(root_prim)
    return tuple(paths)


def _relation_target_paths(relation) -> tuple[str, ...]:
    """Return sorted relationship targets for stable DTRS acceptance evidence."""

    return tuple(sorted(str(target) for target in relation.GetTargets()))


def _point_positions(points) -> tuple[tuple[float, float, float], ...]:
    """Normalize Kit vector values so diagnostics and tests stay serializable."""

    return tuple(tuple(float(component) for component in point) for point in points)


def _usdrt_point_positions(attribute, wp) -> tuple[tuple[float, float, float], ...]:
    """Read Kit-CAE's Fabric points using the same path as NVIDIA's test suite."""

    if not attribute.IsValid():
        return ()
    if attribute.IsGpuDataValid():
        data = wp.array(attribute.Get()).numpy()
    elif attribute.IsCpuDataValid():
        attribute.SyncDataToGpu()
        data = wp.array(attribute.Get()).numpy()
    else:
        return ()
    return tuple(tuple(float(component) for component in point) for point in data)


def _usdrt_curve_vertex_counts(attribute, wp) -> tuple[int, ...]:
    """Read Fabric curve counts without falling back to authored USD attributes."""

    if not attribute.IsValid():
        return ()
    if attribute.IsGpuDataValid():
        data = wp.array(attribute.Get()).numpy()
    elif attribute.IsCpuDataValid():
        attribute.SyncDataToGpu()
        data = wp.array(attribute.Get()).numpy()
    else:
        return ()
    return tuple(int(count) for count in data.reshape(-1))


def _point_bounds(
    points: tuple[tuple[float, float, float], ...],
) -> tuple[tuple[float, float, float], tuple[float, float, float]] | None:
    """Return axis-aligned bounds for generated curve points, when present."""

    if not points:
        return None
    return (
        tuple(min(point[index] for point in points) for index in range(3)),
        tuple(max(point[index] for point in points) for index in range(3)),
    )


def _bounds_within_source(
    curve_bounds: tuple[tuple[float, float, float], tuple[float, float, float]] | None,
    source_bounds: tuple[tuple[float, float, float], tuple[float, float, float]],
) -> bool:
    """Allow only a small numerical tolerance at the VTI domain edge."""

    if curve_bounds is None:
        return False
    minimum, maximum = source_bounds
    extent = max(maximum[index] - minimum[index] for index in range(3))
    tolerance = max(extent * 1e-6, 1e-6)
    return all(
        minimum[index] - tolerance <= curve_bounds[0][index]
        and curve_bounds[1][index] <= maximum[index] + tolerance
        for index in range(3)
    )


def _subtract_points(
    end: tuple[float, float, float],
    start: tuple[float, float, float],
) -> tuple[float, float, float]:
    """Return the point-order travel vector for the first generated curve."""

    return tuple(end[index] - start[index] for index in range(3))


def _nearest_seed_endpoint(
    seed_points: tuple[tuple[float, float, float], ...],
    start: tuple[float, float, float] | None,
    end: tuple[float, float, float] | None,
) -> tuple[str, float | None]:
    """State which endpoint lies nearest any authored seed point."""

    if start is None or end is None:
        return "UNAVAILABLE", None
    start_distance = min(_point_distance(seed, start) for seed in seed_points)
    end_distance = min(_point_distance(seed, end) for seed in seed_points)
    if start_distance <= end_distance:
        return "first_curve_start", start_distance
    return "first_curve_end", end_distance


def _point_distance(
    first: tuple[float, float, float],
    second: tuple[float, float, float],
) -> float:
    return sum((first[index] - second[index]) ** 2 for index in range(3)) ** 0.5


def _primvar_values(primvar) -> tuple[float, ...]:
    """Read numeric widths defensively; operators may replace them asynchronously."""

    if not primvar or not primvar.IsDefined():
        return ()
    values = primvar.Get() or ()
    if isinstance(values, (float, int)):
        return (float(values),)
    return tuple(float(value) for value in values)


def _value_range(values: tuple[float, ...]) -> tuple[float, float] | None:
    return (min(values), max(values)) if values else None


def _temporal_sequence_state(field_prim, cae_vtk) -> str:
    file_names_attr = cae_vtk.FieldArray(field_prim).GetFileNamesAttr()
    time_samples = file_names_attr.GetTimeSamples() if file_names_attr else ()
    return "PRESENT" if time_samples else "ABSENT"
