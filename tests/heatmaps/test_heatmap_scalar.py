# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""Focused direct-thermal-weight scalar contract coverage."""

from __future__ import annotations

import pytest

from digital_twin_runtime_suite.app.heatmaps.scalar import (
    CelsiusScale,
    DeltaProfile,
    evaluate_heatmap_scalar,
    normalize_thermal_weight_group,
)


@pytest.mark.parametrize(
    ("weight", "expected"),
    ((0.0, 42.0), (0.5, 52.0), (1.0, 62.0)),
)
def test_authored_weight_directly_selects_symmetric_spatial_delta(
    weight: float,
    expected: float,
) -> None:
    result = evaluate_heatmap_scalar(
        component_telemetry_celsius=50.0,
        telemetry_quality="measured",
        thermal_weight=weight,
        delta_profile=DeltaProfile(-10.0, 10.0),
        temperature_offset_celsius=2.0,
        scale=CelsiusScale(20.0, 100.0),
    )

    assert result.display_temperature_celsius == expected


def test_scalar_has_no_temperature_preview_input() -> None:
    result = evaluate_heatmap_scalar(
        component_telemetry_celsius=60.0,
        telemetry_quality="measured",
        thermal_weight=0.5,
        delta_profile=DeltaProfile(-5.0, 5.0),
        scale=CelsiusScale(20.0, 100.0),
    )

    assert result.display_temperature_celsius == 60.0
    assert result.normalized_scalar == 0.5


def test_semantic_component_normalization_shares_one_range_across_meshes() -> None:
    normalized = normalize_thermal_weight_group(
        {
            "/motherboard/vrm_west/radiator": (0.56, 0.85),
            "/motherboard/vrm_west/top": (0.56, 0.655),
        }
    )

    assert normalized["/motherboard/vrm_west/radiator"] == pytest.approx((0.0, 1.0))
    assert normalized["/motherboard/vrm_west/top"] == pytest.approx(
        (0.0, 0.3275862068965517)
    )


def test_constant_semantic_component_weights_stay_neutral() -> None:
    normalized = normalize_thermal_weight_group(
        {"/motherboard/vrm_west/cover": (0.6, 0.6)}
    )

    assert normalized["/motherboard/vrm_west/cover"] == (0.5, 0.5)


def test_scalar_rejects_out_of_range_authored_thermal_weight() -> None:
    with pytest.raises(ValueError, match="thermal_weight"):
        evaluate_heatmap_scalar(
            component_telemetry_celsius=60.0,
            telemetry_quality="measured",
            thermal_weight=1.01,
            delta_profile=DeltaProfile(-5.0, 5.0),
            scale=CelsiusScale(20.0, 100.0),
        )
