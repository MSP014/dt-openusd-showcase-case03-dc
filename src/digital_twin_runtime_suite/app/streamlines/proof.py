"""Plain Streamlines operator request, geometry validation, and cleanup contracts."""

from __future__ import annotations

from dataclasses import dataclass, replace
from math import isclose

from digital_twin_runtime_suite.app.flow.static_source import (
    StaticVelocitySourceDescriptor,
)
from digital_twin_runtime_suite.app.streamlines.profile import (
    PRODUCTION_STREAMLINES_PROFILE,
    ProductionStreamlinesProfile,
    geometry_contract_signature,
)
from digital_twin_runtime_suite.app.streamlines.seed_layout import (
    STREAMLINES_FRONT_INTAKE_SEED_PATH,
    FrontIntakeSeedLayout,
    StratifiedSeedLayout,
)
from digital_twin_runtime_suite.app.streamlines.tuning import (
    BASELINE_STREAMLINES_TUNING,
    StreamlinesGeometryTuning,
    StreamlinesProfileTuning,
)

STREAMLINES_OPERATOR_ROOT = "/DTRS_KitCAE/Streamlines"
STREAMLINES_SEED_ROOT = "/DTRS_KitCAE/StreamlineSeeds"
STREAMLINES_OPERATOR_PATH = f"{STREAMLINES_OPERATOR_ROOT}/VelocityField"
STREAMLINES_RUNTIME_PREVIEW_PATH = (
    f"{STREAMLINES_OPERATOR_ROOT}/StaticVelocityRuntimePreview"
)
STREAMLINES_SEED_PATH = f"{STREAMLINES_SEED_ROOT}/UnitSphere"
STREAMLINES_OPERATOR_TYPE = "standard"
STREAMLINES_DIRECTION = "forward"
CREATE_COMMAND_PLACEHOLDER_POINTS = (
    (0.0, 0.0, 0.0),
    (0.1, 0.0, 0.0),
    (0.2, 0.0, 0.0),
    (0.3, 0.0, 0.0),
)
CREATE_COMMAND_PLACEHOLDER_CURVE_VERTEX_COUNTS = (4,)


class StreamlinesOperatorRequestError(RuntimeError):
    """Raised when the operator cannot consume the imported velocity source."""


@dataclass(frozen=True)
class StreamlinesOperatorRequest:
    """Deterministic binding and geometry contract for one operator execution.

    The three step-size values are dimensionless DAV cell-diagonal-relative
    multipliers. Width remains a world-space quantity derived from VTI spacing.
    """

    dataset_prim_path: str
    velocity_field_prim_path: str
    operator_path: str
    seed_path: str
    operator_type: str
    direction: str
    seed_center: tuple[float, float, float]
    seed_radius: float
    min_step_size: float
    initial_step_size: float
    max_step_size: float
    max_steps: int
    width: float
    seed_resolution: int = 16
    profile_name: str = "unprofiled"
    profile_signature: str = ""
    persisted_attributes: tuple[str, ...] = ()
    seed_type: str = "unit_sphere"
    seed_points: tuple[tuple[float, float, float], ...] = ()
    seed_columns: int = 0
    seed_rows: int = 0
    seed_horizontal_spacing: float = 0.0
    seed_vertical_spacing: float = 0.0
    seed_plane_z: float | None = None
    seed_layout_signature: str = ""
    profile_id: str = "global_flow_path"
    seed_section_count: int = 1
    seeds_per_section: int = 0


@dataclass(frozen=True)
class StreamlinesOperatorCleanup:
    """Result of replacing the DTRS-owned operator and seed roots."""

    previous_runtime_present: bool
    success: bool


def build_streamlines_operator_request(
    descriptor: StaticVelocitySourceDescriptor | None,
    *,
    profile: ProductionStreamlinesProfile = PRODUCTION_STREAMLINES_PROFILE,
) -> StreamlinesOperatorRequest:
    """Derive one reproducible seed just inside the source's front domain face.

    Stage 6 establishes positive-Z as the server-front side.  Keeping the
    sphere a few VTI cells inside that face makes this diagnostic independent of
    presentation geometry while ensuring it remains in the accepted airflow
    bounds.
    """

    if descriptor is None:
        raise StreamlinesOperatorRequestError(
            "Import a velocity source before creating Streamlines."
        )
    minimum, maximum = descriptor.world_bounds
    extent = tuple(maximum[index] - minimum[index] for index in range(3))
    if any(value <= 0.0 for value in extent):
        raise StreamlinesOperatorRequestError(
            "Static source bounds must have positive extent."
        )
    max_spacing = max(descriptor.spacing)
    seed_radius = min(
        min(extent) * profile.seed_radius_domain_fraction,
        max_spacing * profile.seed_radius_cell_multiplier,
    )
    front_inset = max(
        seed_radius * profile.seed_front_inset_radius_multiplier,
        max_spacing * profile.seed_front_inset_cell_multiplier,
    )
    if front_inset >= extent[2]:
        raise StreamlinesOperatorRequestError(
            "Velocity-source depth is too small for the Streamlines seed."
        )
    return StreamlinesOperatorRequest(
        dataset_prim_path=descriptor.dataset_prim_path,
        velocity_field_prim_path=descriptor.velocity_field_prim_path,
        operator_path=STREAMLINES_OPERATOR_PATH,
        seed_path=STREAMLINES_SEED_PATH,
        operator_type=profile.operator_type,
        direction=profile.direction,
        seed_center=(
            (minimum[0] + maximum[0]) / 2.0,
            (minimum[1] + maximum[1]) / 2.0,
            maximum[2] - front_inset,
        ),
        seed_radius=seed_radius,
        min_step_size=profile.min_step_cell_multiplier,
        initial_step_size=profile.initial_step_cell_multiplier,
        max_step_size=profile.max_step_cell_multiplier,
        max_steps=profile.max_steps,
        width=max_spacing * profile.width_cell_multiplier,
        seed_resolution=profile.seed_resolution,
        profile_name=profile.name,
        profile_signature=profile.settings_signature,
        persisted_attributes=profile.persisted_attributes,
        seed_layout_signature="unit_sphere_v1",
    )


def build_streamlines_preview_operator_request(
    descriptor: StaticVelocitySourceDescriptor | None,
    layout: FrontIntakeSeedLayout | StratifiedSeedLayout,
    *,
    profile: ProductionStreamlinesProfile = PRODUCTION_STREAMLINES_PROFILE,
    tuning: StreamlinesGeometryTuning | StreamlinesProfileTuning = (
        BASELINE_STREAMLINES_TUNING
    ),
) -> StreamlinesOperatorRequest:
    """Bind the standard operator to one exact developer seed layout."""

    request = build_streamlines_operator_request(descriptor, profile=profile)
    contract = tuning.geometry_contract
    if isinstance(layout, StratifiedSeedLayout):
        expected = contract.seed_count * contract.section_count
        if layout.seed_count != expected:
            raise StreamlinesOperatorRequestError(
                "Streamlines profile seed layout is incomplete."
            )
        columns = max(layout.row_counts[: layout.rows_per_section])
        rows = layout.rows_per_section
        horizontal_spacing = 0.0
        vertical_spacing = layout.y_spacing
        seed_plane_z = layout.section_planes[0]
        layout_signature = (
            f"{contract.profile_id.value}:{contract.seed_count}:"
            f"{contract.section_count}"
        )
        profile_id = contract.profile_id.value
        section_count = layout.section_count
        seeds_per_section = layout.seeds_per_section
        centre = (
            (layout.domain_bounds[0][0] + layout.domain_bounds[1][0]) / 2.0,
            (layout.domain_bounds[0][1] + layout.domain_bounds[1][1]) / 2.0,
            sum(layout.section_planes) / len(layout.section_planes),
        )
    else:
        if layout.seed_count != layout.columns * layout.rows:
            raise StreamlinesOperatorRequestError(
                "Streamlines preview seed layout is incomplete."
            )
        columns = layout.columns
        rows = layout.rows
        horizontal_spacing = layout.horizontal_spacing
        vertical_spacing = layout.vertical_spacing
        seed_plane_z = layout.seed_plane_z
        layout_signature = layout.profile_signature
        profile_id = "global_flow_path"
        section_count = 1
        seeds_per_section = layout.seed_count
        centre = layout.centre
    return replace(
        request,
        seed_path=STREAMLINES_FRONT_INTAKE_SEED_PATH,
        seed_center=centre,
        seed_radius=0.0,
        seed_resolution=0,
        seed_type="point_grid",
        seed_points=layout.points,
        seed_columns=columns,
        seed_rows=rows,
        seed_horizontal_spacing=horizontal_spacing,
        seed_vertical_spacing=vertical_spacing,
        seed_plane_z=seed_plane_z,
        seed_layout_signature=layout_signature,
        min_step_size=contract.min_step_cell_multiplier,
        initial_step_size=contract.initial_step_cell_multiplier,
        max_step_size=contract.max_step_cell_multiplier,
        max_steps=contract.max_steps,
        profile_signature=geometry_contract_signature(contract),
        profile_id=profile_id,
        seed_section_count=section_count,
        seeds_per_section=seeds_per_section,
    )


def validate_streamlines_source(
    descriptor: StaticVelocitySourceDescriptor | None,
    *,
    dataset_available: bool,
    velocity_field_available: bool,
) -> StreamlinesOperatorRequest:
    """Reject a missing dataset or field before authoring Streamlines prims."""

    request = build_streamlines_operator_request(descriptor)
    if not dataset_available:
        raise StreamlinesOperatorRequestError(
            f"Accepted static dataset is unavailable: {request.dataset_prim_path}."
        )
    if not velocity_field_available:
        raise StreamlinesOperatorRequestError(
            "Configured static velocity field is unavailable: "
            f"{request.velocity_field_prim_path}."
        )
    return request


def validate_generated_streamlines_geometry(
    curve_count: int,
    point_count: int,
    *,
    point_positions: tuple[tuple[float, float, float], ...] = (),
    curve_vertex_counts: tuple[int, ...] = (),
) -> None:
    """Reject empty or unchanged placeholder data from a UsdRT curve snapshot.

    ``CreateCaeVizStreamlines`` keeps its authored USD placeholder after a
    successful execution. Callers therefore pass only Fabric/UsdRT values here;
    authored USD remains diagnostic evidence and is never a failure condition.
    """

    if curve_count <= 0 or point_count <= 0:
        raise StreamlinesOperatorRequestError(
            "Streamlines operator completed without generated BasisCurves geometry."
        )
    if is_create_command_placeholder_geometry(
        point_positions,
        curve_vertex_counts,
    ):
        raise StreamlinesOperatorRequestError(
            "Streamlines operator completed but left the CreateCaeVizStreamlines "
            "placeholder geometry unchanged."
        )


def is_create_command_placeholder_geometry(
    point_positions: tuple[tuple[float, float, float], ...],
    curve_vertex_counts: tuple[int, ...],
) -> bool:
    """Identify the four-point visual placeholder authored by the Kit command.

    ``CreateCaeVizStreamlines`` creates a visible placeholder before its
    asynchronous operator has produced data.  Treating those points as a
    successful streamline would make the operator result misleading.
    """

    if curve_vertex_counts != CREATE_COMMAND_PLACEHOLDER_CURVE_VERTEX_COUNTS:
        return False
    if len(point_positions) != len(CREATE_COMMAND_PLACEHOLDER_POINTS):
        return False
    return all(
        isclose(actual, expected, rel_tol=0.0, abs_tol=1e-6)
        for point, placeholder in zip(
            point_positions, CREATE_COMMAND_PLACEHOLDER_POINTS
        )
        for actual, expected in zip(point, placeholder)
    )


def clear_streamlines_operator_from_stage(
    stage,
) -> StreamlinesOperatorCleanup:
    """Remove prior operator roots from Session and root layers before a retry."""

    paths = (STREAMLINES_OPERATOR_ROOT, STREAMLINES_SEED_ROOT)
    previous_runtime_present = any(
        stage.GetPrimAtPath(path).IsValid() for path in paths
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
    return StreamlinesOperatorCleanup(
        previous_runtime_present=previous_runtime_present,
        success=not any(stage.GetPrimAtPath(path).IsValid() for path in paths),
    )


def clear_streamlines_seed_from_stage(stage) -> bool:
    """Remove a disposable seed without deleting an accepted RuntimePreview.

    The explicit recompute fallback owns a short-lived Kit-CAE operator and
    seed, but its authored preview is the visible result. Clearing the whole
    Streamlines root here would make a successful fallback immediately vanish.
    """

    previous_target = stage.GetEditTarget()
    try:
        for layer in (stage.GetSessionLayer(), stage.GetRootLayer()):
            stage.SetEditTarget(layer)
            if stage.GetPrimAtPath(STREAMLINES_SEED_ROOT).IsValid():
                stage.RemovePrim(STREAMLINES_SEED_ROOT)
    finally:
        stage.SetEditTarget(previous_target)
    return not stage.GetPrimAtPath(STREAMLINES_SEED_ROOT).IsValid()
