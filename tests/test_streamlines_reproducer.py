"""Focused pure contracts for the isolated Package B VTI compatibility bisect."""

from __future__ import annotations

from pathlib import Path

import pytest

from digital_twin_runtime_suite.app.streamlines.reproducer import (
    REPRODUCER_VTI_RELATIVE_PATH,
    StreamlinesIntegrationAcceptanceResult,
    StreamlinesIntegrationCaseResult,
    derive_isolated_reproducer_seed,
    isolated_reproducer_vti_path,
)


def test_isolated_reproducer_uses_the_exact_nominal_vti_path():
    asset_root = Path("assets/_external")

    path = isolated_reproducer_vti_path(asset_root)

    assert path.name == "server_airflow_velocity_normal_1001.vti"
    assert path.as_posix().endswith(REPRODUCER_VTI_RELATIVE_PATH.as_posix())


def test_isolated_reproducer_seed_is_derived_from_dataset_bounds():
    center, radius = derive_isolated_reproducer_seed(
        ((-0.2, 0.0, -0.5), (0.2, 0.2, 0.1)),
        (0.0025, 0.0025, 0.005),
    )

    assert center == pytest.approx((0.0, 0.1, -0.2))
    assert radius == pytest.approx(0.02)


def test_integration_acceptance_requires_isolated_root_cleanup():
    case = StreamlinesIntegrationCaseResult(
        case_id="A",
        input_label="fixture",
        passed=True,
        fresh_execution=True,
        completion_count_before=0,
        completion_count_after=1,
        completion_success=True,
        authored_basis_curves=True,
        runtime_basis_curves=True,
        curve_count=1,
        point_count=5,
        placeholder_geometry=False,
        curve_bounds=((0.0, 0.0, 0.0), (0.1, 0.1, 0.1)),
        source_bounds=((-1.0, -1.0, -1.0), (1.0, 1.0, 1.0)),
        curve_bounds_intersect_source=True,
        curve_bounds_within_source=True,
    )

    result = StreamlinesIntegrationAcceptanceResult(
        case_a=case,
        case_b=case,
        cleanup_passed=False,
        cleanup_reason="fixture cleanup failure",
    )

    assert not result.success
    assert "cleanup failed" in result.message
