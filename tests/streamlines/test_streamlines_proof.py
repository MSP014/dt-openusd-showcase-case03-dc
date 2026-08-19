"""Focused Streamlines operator-contract tests."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from digital_twin_runtime_suite.app.flow.static_source import (
    StaticVelocitySourceDescriptor,
)
from digital_twin_runtime_suite.app.streamlines.diagnostics import (
    StreamlinesBindingEvidence,
    StreamlinesOperatorEvidence,
    format_streamlines_binding_evidence,
    format_streamlines_operator_evidence,
)
from digital_twin_runtime_suite.app.streamlines.proof import (
    CREATE_COMMAND_PLACEHOLDER_CURVE_VERTEX_COUNTS,
    CREATE_COMMAND_PLACEHOLDER_POINTS,
    STREAMLINES_DIRECTION,
    STREAMLINES_OPERATOR_PATH,
    STREAMLINES_OPERATOR_ROOT,
    STREAMLINES_RUNTIME_PREVIEW_PATH,
    STREAMLINES_SEED_PATH,
    STREAMLINES_SEED_ROOT,
    StreamlinesOperatorCleanup,
    StreamlinesOperatorRequest,
    StreamlinesOperatorRequestError,
    build_streamlines_operator_request,
    clear_streamlines_operator_from_stage,
    validate_generated_streamlines_geometry,
    validate_streamlines_source,
)


def test_streamlines_request_has_deterministic_paths_bindings_and_seed():
    descriptor = _descriptor()

    request = build_streamlines_operator_request(descriptor)

    assert request.operator_path == STREAMLINES_OPERATOR_PATH
    assert request.seed_path == STREAMLINES_SEED_PATH
    assert request.dataset_prim_path == descriptor.dataset_prim_path
    assert request.velocity_field_prim_path == descriptor.velocity_field_prim_path
    assert request.direction == STREAMLINES_DIRECTION == "forward"
    assert request.seed_center == (0.0, 0.1, 0.07)
    assert request.seed_radius == pytest.approx(0.02)
    assert request.min_step_size == pytest.approx(0.01)
    assert request.initial_step_size == pytest.approx(0.2)
    assert request.max_step_size == pytest.approx(0.5)
    assert request.width == pytest.approx(0.002)


def test_streamlines_request_rejects_missing_source_or_velocity_field():
    descriptor = _descriptor()

    with pytest.raises(
        StreamlinesOperatorRequestError,
        match="dataset is unavailable",
    ):
        validate_streamlines_source(
            descriptor,
            dataset_available=False,
            velocity_field_available=True,
        )
    with pytest.raises(
        StreamlinesOperatorRequestError, match="velocity field is unavailable"
    ):
        validate_streamlines_source(
            descriptor,
            dataset_available=True,
            velocity_field_available=False,
        )


@pytest.mark.parametrize("curve_count, point_count", ((0, 4), (1, 0)))
def test_streamlines_request_rejects_completed_zero_geometry(
    curve_count,
    point_count,
):
    with pytest.raises(
        StreamlinesOperatorRequestError, match="without generated BasisCurves"
    ):
        validate_generated_streamlines_geometry(curve_count, point_count)


def test_streamlines_request_rejects_create_command_placeholder_geometry():
    with pytest.raises(StreamlinesOperatorRequestError, match="placeholder geometry"):
        validate_generated_streamlines_geometry(
            1,
            4,
            point_positions=CREATE_COMMAND_PLACEHOLDER_POINTS,
            curve_vertex_counts=CREATE_COMMAND_PLACEHOLDER_CURVE_VERTEX_COUNTS,
        )


def test_streamlines_request_rejects_float32_create_command_placeholder():
    with pytest.raises(StreamlinesOperatorRequestError, match="placeholder geometry"):
        validate_generated_streamlines_geometry(
            1,
            4,
            point_positions=(
                (0.0, 0.0, 0.0),
                (0.10000000149011612, 0.0, 0.0),
                (0.20000000298023224, 0.0, 0.0),
                (0.30000001192092896, 0.0, 0.0),
            ),
            curve_vertex_counts=(4,),
        )


def test_runtime_usdrt_geometry_passes_while_authored_usd_remains_placeholder():
    request = build_streamlines_operator_request(_descriptor())
    evidence = _runtime_evidence(request)

    assert evidence.authored_usd_point_count == 4
    assert evidence.authored_usd_placeholder_geometry is True
    assert evidence.runtime_usdrt_basis_curves is True
    assert evidence.runtime_point_count == 38400
    assert evidence.is_valid_for(request) is True
    assert (
        replace(evidence, runtime_placeholder_geometry=True).is_valid_for(request)
        is False
    )
    assert (
        replace(evidence, viewport_preview_matches_runtime=False).is_valid_for(request)
        is False
    )


def test_operator_evidence_compacts_curve_counts_by_default():
    """Keep operator diagnostics readable while allowing deep inspection."""

    descriptor = _descriptor()
    request = build_streamlines_operator_request(descriptor)
    evidence = _runtime_evidence(request)
    cleanup = StreamlinesOperatorCleanup(
        previous_runtime_present=False,
        success=True,
    )

    concise = format_streamlines_operator_evidence(
        descriptor,
        request,
        cleanup,
        evidence,
    )
    verbose = format_streamlines_operator_evidence(
        descriptor,
        request,
        cleanup,
        evidence,
        verbose=True,
    )

    assert "points_per_curve_min_mean_max=(150, 150, 150)" in concise
    assert "runtime_curve_vertex_counts=" not in concise
    assert "runtime_point_head=" not in concise
    assert f"path={STREAMLINES_RUNTIME_PREVIEW_PATH}" in concise
    assert "matches_runtime=True" in concise
    assert "result=PASS" in concise
    assert "runtime_curve_vertex_counts=" in verbose


def test_streamlines_binding_diagnostics_identify_relationship_field_contract():
    evidence = StreamlinesBindingEvidence(
        operator_enabled=False,
        source_relationship="cae:viz:datasetSelection:source:target",
        source_targets=("/DTRS_HoudiniVelocity/VTKImageData",),
        seed_relationship="cae:viz:datasetSelection:seeds:target",
        seed_targets=("/DTRS_KitCAE/StreamlineSeeds/DiagnosticUnitSphere",),
        velocity_relationship="cae:viz:fieldSelection:velocities:target",
        velocity_targets=("/DTRS_HoudiniVelocity/PointData/vel",),
        velocity_mode="unchanged",
        resolved_velocity_field_names=("vel",),
    )

    block = format_streamlines_binding_evidence(evidence)

    assert "operator_enabled=False" in block
    assert "resolved_dataset_fields=('vel',)" in block
    assert "fieldNames_attribute=NOT_AUTHORED" in block


def test_streamlines_operator_cleanup_removes_both_runtime_roots_from_layers():
    stage = _LayeredFakeStage(
        session_paths={STREAMLINES_OPERATOR_ROOT, STREAMLINES_SEED_ROOT},
        root_paths={STREAMLINES_OPERATOR_ROOT, STREAMLINES_SEED_ROOT},
    )

    cleanup = clear_streamlines_operator_from_stage(stage)

    assert cleanup.previous_runtime_present is True
    assert cleanup.success is True
    assert stage.session_paths == set()
    assert stage.root_paths == set()
    assert stage.edit_target is stage.original_target


def _descriptor() -> StaticVelocitySourceDescriptor:
    return StaticVelocitySourceDescriptor(
        workload="Nominal",
        dataset_identity="server/load_normal",
        sample_index=0,
        vti_path=Path("server_velocity.0000.vti"),
        dataset_prim_path="/DTRS_HoudiniVelocity/VTKImageData",
        velocity_field_prim_path="/DTRS_HoudiniVelocity/PointData/vel",
        world_bounds=((-0.2, 0.0, -0.5), (0.2, 0.2, 0.1)),
        dimensions=(81, 41, 121),
        spacing=(0.0025, 0.0025, 0.005),
        origin=(-0.2, 0.0, -0.5),
        source_origin=(-0.2, 0.0, -0.5),
        stage_meters_per_unit=1.0,
    )


def _runtime_evidence(
    request: StreamlinesOperatorRequest,
) -> StreamlinesOperatorEvidence:
    """Represent an accepted operator result without pretending USD owns it."""

    return StreamlinesOperatorEvidence(
        authored_prims=(request.operator_path, request.seed_path),
        duplicate_runtime_prim_count=0,
        operator_type="BasisCurves",
        operator_completion_count_before=1,
        operator_completion_count=2,
        fresh_execution=True,
        operator_execution_success=True,
        authored_usd_point_count=4,
        authored_usd_curve_vertex_counts=(4,),
        authored_usd_placeholder_geometry=True,
        runtime_usdrt_basis_curves=True,
        runtime_curve_count=256,
        runtime_point_count=38400,
        runtime_curve_vertex_counts=(150,) * 256,
        runtime_point_positions=((0.0, 0.1, 0.07),) * 38400,
        source_binding=(request.dataset_prim_path,),
        seed_binding=(request.seed_path,),
        velocity_binding=(request.velocity_field_prim_path,),
        direction=request.direction,
        configured_width=request.width,
        render_width_range=(request.width, request.width),
        runtime_curve_bounds=((-0.1, 0.0, -0.4), (0.1, 0.2, 0.05)),
        source_world_bounds=((-0.2, 0.0, -0.5), (0.2, 0.2, 0.1)),
        runtime_curve_bounds_within_source=True,
        runtime_placeholder_geometry=False,
        point_head=((0.0, 0.1, 0.07),),
        point_tail=((0.0, 0.1, 0.07),),
        first_curve_start=(0.0, 0.1, 0.07),
        first_curve_end=(0.1, 0.1, 0.05),
        first_curve_travel=(0.1, 0.0, -0.02),
        first_curve_seed_endpoint="first_curve_start",
        first_curve_seed_distance=0.0,
        flow_environment="ABSENT",
        dataset_emitter="ABSENT",
        boundary_emitter="ABSENT",
        smoke_injectors="ABSENT",
        temporal_sequence="ABSENT",
        timeline_playback="INACTIVE",
        authored_usd_fallback_visibility="invisible",
        runtime_usdrt_visibility="inherited",
        viewport_preview_path=STREAMLINES_RUNTIME_PREVIEW_PATH,
        viewport_preview_curve_count=256,
        viewport_preview_point_count=38400,
        viewport_preview_matches_runtime=True,
    )


class _LayeredFakeStage:
    """Small layered-stage double for operator replacement ownership."""

    def __init__(self, *, session_paths: set[str], root_paths: set[str]):
        self.session_paths = set(session_paths)
        self.root_paths = set(root_paths)
        self._session_layer = object()
        self._root_layer = object()
        self.original_target = self._root_layer
        self.edit_target = self.original_target

    def GetPrimAtPath(self, path: str):
        paths = self.session_paths | self.root_paths
        return _FakePrim(
            any(item == path or item.startswith(f"{path}/") for item in paths)
        )

    def GetEditTarget(self):
        return self.edit_target

    def SetEditTarget(self, layer) -> None:
        self.edit_target = layer

    def GetSessionLayer(self):
        return self._session_layer

    def GetRootLayer(self):
        return self._root_layer

    def RemovePrim(self, path: str) -> None:
        paths = (
            self.session_paths
            if self.edit_target is self._session_layer
            else self.root_paths
        )
        matching_paths = tuple(
            item for item in paths if item == path or item.startswith(f"{path}/")
        )
        paths.difference_update(matching_paths)


class _FakePrim:
    """Expose the one validity check used by layered-cleanup code."""

    def __init__(self, valid: bool):
        self._valid = valid

    def IsValid(self) -> bool:
        return self._valid
