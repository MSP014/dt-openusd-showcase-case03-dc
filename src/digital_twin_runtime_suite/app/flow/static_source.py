"""One-sample airflow source preparation reused before any Flow consumer exists."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from digital_twin_runtime_suite.app.airflow_dataset import (
    AirflowDataset,
    AirflowDatasetError,
    discover_airflow_dataset,
    validate_airflow_dataset_grid,
)
from digital_twin_runtime_suite.app.airflow_validation import (
    preflight as airflow_preflight,
)
from digital_twin_runtime_suite.app.workload_binding.runtime import (
    WorkloadAirflowBinding,
)

WorldBounds = tuple[tuple[float, float, float], tuple[float, float, float]]


@dataclass(frozen=True)
class ResolvedStaticVelocitySample:
    """One manifest-validated VTI sample before it is imported into Kit-CAE."""

    workload: str
    dataset_identity: str
    sample_index: int
    vti_path: Path
    velocity_field_name: str
    dimensions: tuple[int, int, int]
    spacing: tuple[float, float, float]
    source_origin: tuple[float, float, float]
    source_world_bounds: WorldBounds


@dataclass(frozen=True)
class StaticVelocitySourceDescriptor:
    """Plain spatial source contract available to a future Streamlines consumer."""

    workload: str
    dataset_identity: str
    sample_index: int
    vti_path: Path
    dataset_prim_path: str
    velocity_field_prim_path: str
    world_bounds: WorldBounds
    dimensions: tuple[int, int, int]
    spacing: tuple[float, float, float]
    origin: tuple[float, float, float]
    source_origin: tuple[float, float, float]
    stage_meters_per_unit: float


@dataclass(frozen=True)
class StaticVelocitySourceCleanup:
    """Result of replacing the DTRS-owned static source across USD layers."""

    previous_source_present: bool
    success: bool


def resolve_static_velocity_sample(
    asset_root: Path,
    binding: WorkloadAirflowBinding,
    velocity_field_name: str,
    sample_index: int = 0,
) -> ResolvedStaticVelocitySample:
    """Resolve and preflight one deterministic VTI without creating USD or Flow."""

    airflow_dataset = discover_airflow_dataset(asset_root, binding.dataset)
    return resolve_static_velocity_sample_from_airflow_dataset(
        airflow_dataset,
        binding,
        velocity_field_name,
        sample_index,
    )


def resolve_static_velocity_sample_from_airflow_dataset(
    airflow_dataset: AirflowDataset,
    binding: WorkloadAirflowBinding,
    velocity_field_name: str,
    sample_index: int = 0,
) -> ResolvedStaticVelocitySample:
    """Preflight one VTI from an already resolved authoritative dataset."""

    if (
        airflow_dataset.manifest.scope,
        airflow_dataset.manifest.state,
    ) != (binding.dataset.scope, binding.dataset.state):
        raise AirflowDatasetError(
            "Resolved airflow dataset does not match the requested workload binding."
        )
    velocity_paths = airflow_dataset.velocity_vti_sequence_paths
    if not 0 <= sample_index < len(velocity_paths):
        raise AirflowDatasetError(
            "Static airflow sample index is outside the manifest-backed sequence: "
            f"index={sample_index}, sample_count={len(velocity_paths)}, "
            f"dataset={binding.dataset_identity}."
        )
    velocity_path = velocity_paths[sample_index]
    if not velocity_path.is_file():
        raise AirflowDatasetError(f"Static airflow VTI is missing: {velocity_path}")

    metadata = airflow_preflight.read_kit_cae_vti_metadata(
        velocity_path,
        velocity_field_name,
    )
    dimensions = tuple(int(value) for value in metadata["dimensions"])
    validate_airflow_dataset_grid(airflow_dataset, dimensions)
    spacing = tuple(float(value) for value in metadata["spacing"])
    source_origin = tuple(float(value) for value in metadata["vti_header_origin"])
    source_world_bounds = _world_bounds_from_grid(
        source_origin,
        dimensions,
        spacing,
    )
    return ResolvedStaticVelocitySample(
        workload=binding.workload_mode,
        dataset_identity=binding.dataset_identity,
        sample_index=sample_index,
        vti_path=velocity_path,
        velocity_field_name=velocity_field_name,
        dimensions=dimensions,
        spacing=spacing,
        source_origin=source_origin,
        source_world_bounds=source_world_bounds,
    )


def describe_imported_static_velocity_source(
    sample: ResolvedStaticVelocitySample,
    *,
    dataset_prim_path: str,
    velocity_field_prim_path: str,
    imported_grid: dict[str, object],
    stage_meters_per_unit: float,
) -> StaticVelocitySourceDescriptor:
    """Verify the imported VTI preserved the source spatial contract."""

    if not math.isfinite(stage_meters_per_unit) or stage_meters_per_unit <= 0.0:
        raise RuntimeError("Stage metersPerUnit must be finite and positive.")
    imported_origin = tuple(float(value) for value in imported_grid["origin"])
    imported_spacing = tuple(float(value) for value in imported_grid["spacing"])
    imported_world_bounds = _normalise_world_bounds(imported_grid["world_bounds"])
    if not _vector_match(imported_origin, sample.source_origin):
        raise RuntimeError(
            "Kit-CAE VTI origin does not match the Houdini VTI source origin."
        )
    if not _vector_match(imported_spacing, sample.spacing):
        raise RuntimeError(
            "Kit-CAE VTI spacing does not match the Houdini VTI source spacing."
        )
    if not _world_bounds_match(imported_world_bounds, sample.source_world_bounds):
        raise RuntimeError(
            "Kit-CAE VTI world bounds do not match the Houdini VTI source bounds."
        )
    return StaticVelocitySourceDescriptor(
        workload=sample.workload,
        dataset_identity=sample.dataset_identity,
        sample_index=sample.sample_index,
        vti_path=sample.vti_path,
        dataset_prim_path=dataset_prim_path,
        velocity_field_prim_path=velocity_field_prim_path,
        world_bounds=imported_world_bounds,
        dimensions=sample.dimensions,
        spacing=sample.spacing,
        origin=imported_origin,
        source_origin=sample.source_origin,
        stage_meters_per_unit=stage_meters_per_unit,
    )


def clear_static_velocity_source_from_stage(
    stage,
    source_root_path: str,
) -> StaticVelocitySourceCleanup:
    """Remove a prior importer source from Session and root layers before reuse.

    The local Kit-CAE VTK importer copies its source spec into the root layer,
    while DTRS restores the ImageData origin in the session layer. Removing
    only one of those opinions would leave stale state on a repeated static
    test, so Package A deliberately clears both DTRS-owned opinions.
    """

    previous_source_present = stage.GetPrimAtPath(source_root_path).IsValid()
    previous_target = stage.GetEditTarget()
    try:
        stage.SetEditTarget(stage.GetSessionLayer())
        if stage.GetPrimAtPath(source_root_path).IsValid():
            stage.RemovePrim(source_root_path)
        stage.SetEditTarget(stage.GetRootLayer())
        if stage.GetPrimAtPath(source_root_path).IsValid():
            stage.RemovePrim(source_root_path)
    finally:
        stage.SetEditTarget(previous_target)
    return StaticVelocitySourceCleanup(
        previous_source_present=previous_source_present,
        success=not stage.GetPrimAtPath(source_root_path).IsValid(),
    )


def _world_bounds_from_grid(
    origin: tuple[float, float, float],
    dimensions: tuple[int, int, int],
    spacing: tuple[float, float, float],
) -> WorldBounds:
    maximum = tuple(
        origin[index] + (dimensions[index] - 1) * spacing[index] for index in range(3)
    )
    return origin, maximum


def _normalise_world_bounds(value: object) -> WorldBounds:
    try:
        minimum, maximum = value
        return (
            tuple(float(component) for component in minimum),
            tuple(float(component) for component in maximum),
        )
    except (TypeError, ValueError) as error:
        raise RuntimeError("Kit-CAE VTI world bounds are unavailable.") from error


def _world_bounds_match(actual: WorldBounds, expected: WorldBounds) -> bool:
    return all(
        math.isclose(actual[bound][axis], expected[bound][axis], abs_tol=1e-6)
        for bound in range(2)
        for axis in range(3)
    )


def _vector_match(
    actual: tuple[float, float, float],
    expected: tuple[float, float, float],
) -> bool:
    return all(
        math.isclose(actual[index], expected[index], abs_tol=1e-6) for index in range(3)
    )
