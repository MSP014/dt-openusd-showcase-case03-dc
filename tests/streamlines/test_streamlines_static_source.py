"""Focused regression coverage for static Streamlines source cleanliness."""

from __future__ import annotations

from pathlib import Path

import pytest

from digital_twin_runtime_suite.app.flow.static_source import (
    StaticVelocitySourceCleanup,
    StaticVelocitySourceDescriptor,
)
from digital_twin_runtime_suite.app.streamlines.diagnostics import (
    StaticSourceRuntimeEvidence,
    format_static_source_acceptance,
    require_clean_static_source_runtime,
)


def _descriptor(tmp_path: Path) -> StaticVelocitySourceDescriptor:
    source_vti = tmp_path / "velocity_0000.vti"
    source_vti.write_bytes(b"vti")
    return StaticVelocitySourceDescriptor(
        workload="Nominal",
        dataset_identity="server/load_normal",
        sample_index=0,
        vti_path=source_vti,
        dataset_prim_path="/DTRS_HoudiniVelocity/VTKImageData",
        velocity_field_prim_path="/DTRS_HoudiniVelocity/PointData/vel",
        world_bounds=((0.0, 0.0, 0.0), (1.0, 1.0, 1.0)),
        dimensions=(2, 2, 2),
        spacing=(1.0, 1.0, 1.0),
        origin=(0.0, 0.0, 0.0),
        source_origin=(0.0, 0.0, 0.0),
        stage_meters_per_unit=1.0,
    )


def _evidence(*, flow_environment: str = "ABSENT") -> StaticSourceRuntimeEvidence:
    return StaticSourceRuntimeEvidence(
        authored_prims=("/DTRS_HoudiniVelocity",),
        duplicate_runtime_prim_count=0,
        flow_environment=flow_environment,
        dataset_emitter="ABSENT",
        boundary_emitter="ABSENT",
        smoke_injectors="ABSENT",
        streamlines_operator="ABSENT",
        temporal_sequence="ABSENT",
        timeline_playback="NOT_OWNED",
    )


def test_static_source_formatter_uses_current_clean_contract(tmp_path: Path) -> None:
    report = format_static_source_acceptance(
        _descriptor(tmp_path),
        StaticVelocitySourceCleanup(previous_source_present=False, success=True),
        _evidence(),
    )

    assert "DTRS STREAMLINES | STATIC_SOURCE_TEST | PASS" in report


def test_dirty_static_runtime_is_rejected_before_diagnostics_boundary() -> None:
    evidence = _evidence(flow_environment="PRESENT")

    assert evidence.clean is False
    with pytest.raises(RuntimeError, match="forbidden runtime state"):
        require_clean_static_source_runtime(evidence)
