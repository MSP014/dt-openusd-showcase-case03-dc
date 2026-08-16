"""Plain contracts and cleanup ownership for the first static Streamlines proof."""

from __future__ import annotations

from dataclasses import dataclass
from math import isclose

from digital_twin_runtime_suite.app.flow.static_source import (
    StaticVelocitySourceDescriptor,
)

STREAMLINES_OPERATOR_ROOT = "/DTRS_KitCAE/Streamlines"
STREAMLINES_SEED_ROOT = "/DTRS_KitCAE/StreamlineSeeds"
STREAMLINES_COMPARISON_OPERATOR_ROOT = "/DTRS_KitCAE/StreamlinesComparison"
STREAMLINES_COMPARISON_SEED_ROOT = "/DTRS_KitCAE/StreamlinesComparisonSeeds"
STATIC_PROOF_OPERATOR_PATH = f"{STREAMLINES_OPERATOR_ROOT}/StaticVelocityProof"
STATIC_PROOF_RUNTIME_PREVIEW_PATH = (
    f"{STREAMLINES_OPERATOR_ROOT}/StaticVelocityRuntimePreview"
)
STATIC_PROOF_SEED_PATH = f"{STREAMLINES_SEED_ROOT}/DiagnosticUnitSphere"
STATIC_PROOF_OPERATOR_TYPE = "standard"
STATIC_PROOF_DIRECTION = "forward"
CREATE_COMMAND_PLACEHOLDER_POINTS = (
    (0.0, 0.0, 0.0),
    (0.1, 0.0, 0.0),
    (0.2, 0.0, 0.0),
    (0.3, 0.0, 0.0),
)
CREATE_COMMAND_PLACEHOLDER_CURVE_VERTEX_COUNTS = (4,)


class StaticStreamlinesProofError(RuntimeError):
    """Raised when Package B cannot consume the accepted Package A source."""


@dataclass(frozen=True)
class StaticStreamlinesProofRequest:
    """Deterministic binding and geometry contract for one diagnostic operator."""

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


@dataclass(frozen=True)
class StaticStreamlinesProofCleanup:
    """Result of replacing the two DTRS-owned Package B runtime roots."""

    previous_runtime_present: bool
    success: bool


def build_static_streamlines_proof_request(
    descriptor: StaticVelocitySourceDescriptor | None,
) -> StaticStreamlinesProofRequest:
    """Derive one reproducible seed just inside the source's front domain face.

    Stage 6 establishes positive-Z as the server-front side.  Keeping the
    sphere a few VTI cells inside that face makes this diagnostic independent of
    presentation geometry while ensuring it remains in the accepted airflow
    bounds.
    """

    if descriptor is None:
        raise StaticStreamlinesProofError(
            "Run Static Test successfully before creating the Streamlines proof."
        )
    minimum, maximum = descriptor.world_bounds
    extent = tuple(maximum[index] - minimum[index] for index in range(3))
    if any(value <= 0.0 for value in extent):
        raise StaticStreamlinesProofError(
            "Static source bounds must have positive extent."
        )
    max_spacing = max(descriptor.spacing)
    seed_radius = min(min(extent) * 0.1, max_spacing * 4.0)
    front_inset = max(seed_radius * 1.5, max_spacing * 4.0)
    if front_inset >= extent[2]:
        raise StaticStreamlinesProofError(
            "Static source depth is too small for the diagnostic Streamlines seed."
        )
    return StaticStreamlinesProofRequest(
        dataset_prim_path=descriptor.dataset_prim_path,
        velocity_field_prim_path=descriptor.velocity_field_prim_path,
        operator_path=STATIC_PROOF_OPERATOR_PATH,
        seed_path=STATIC_PROOF_SEED_PATH,
        operator_type=STATIC_PROOF_OPERATOR_TYPE,
        direction=STATIC_PROOF_DIRECTION,
        seed_center=(
            (minimum[0] + maximum[0]) / 2.0,
            (minimum[1] + maximum[1]) / 2.0,
            maximum[2] - front_inset,
        ),
        seed_radius=seed_radius,
        min_step_size=max_spacing * 0.5,
        initial_step_size=max_spacing * 2.0,
        max_step_size=max_spacing * 4.0,
        max_steps=200,
        width=max_spacing * 0.4,
    )


def validate_static_streamlines_source(
    descriptor: StaticVelocitySourceDescriptor | None,
    *,
    dataset_available: bool,
    velocity_field_available: bool,
) -> StaticStreamlinesProofRequest:
    """Reject a missing static dataset or field before authoring Package B prims."""

    request = build_static_streamlines_proof_request(descriptor)
    if not dataset_available:
        raise StaticStreamlinesProofError(
            f"Accepted static dataset is unavailable: {request.dataset_prim_path}."
        )
    if not velocity_field_available:
        raise StaticStreamlinesProofError(
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
        raise StaticStreamlinesProofError(
            "Streamlines operator completed without generated BasisCurves geometry."
        )
    if is_create_command_placeholder_geometry(
        point_positions,
        curve_vertex_counts,
    ):
        raise StaticStreamlinesProofError(
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
    successful streamline would make the Package B proof misleading.
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


def clear_static_streamlines_proof_from_stage(
    stage,
) -> StaticStreamlinesProofCleanup:
    """Remove prior Package B roots from Session and root layers before a retry."""

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
    return StaticStreamlinesProofCleanup(
        previous_runtime_present=previous_runtime_present,
        success=not any(stage.GetPrimAtPath(path).IsValid() for path in paths),
    )
