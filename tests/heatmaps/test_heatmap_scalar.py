"""Focused pure-contract coverage for Stage 10.2 scalar mapping."""

from __future__ import annotations

from pathlib import Path

import pytest

from digital_twin_runtime_suite.app.heatmaps.scalar import (
    DEFAULT_HEATMAP_DELTA_PROFILE,
    FULL_SPECTRUM_HEATMAP_PALETTE,
    THERMAL_WEIGHT_REMAP_COLD_BIASED,
    CelsiusScale,
    DeltaProfile,
    build_delta_profile_matrix,
    effective_delta_range,
    evaluate_heatmap_scalar,
    recalibrate_effective_delta_range,
    recalibrate_effective_delta_span,
    remap_thermal_weight,
    resolve_server_wide_celsius_scale,
)
from digital_twin_runtime_suite.app.telemetry.config import TelemetryConfig


def test_plus_formula_preserves_spatial_weight_meaning() -> None:
    scale = CelsiusScale(20.0, 100.0)
    profile = DeltaProfile(-5.0, 5.0)

    values = tuple(
        evaluate_heatmap_scalar(
            component_telemetry_celsius=60.0,
            telemetry_quality="measured",
            thermal_weight=weight,
            delta_profile=profile,
            scale=scale,
        ).display_temperature_celsius
        for weight in (0.0, 0.5, 1.0)
    )

    assert values == (55.0, 60.0, 65.0)


def test_fixed_scale_clamps_and_same_temperature_has_same_colour() -> None:
    scale = CelsiusScale(30.0, 90.0)
    below = evaluate_heatmap_scalar(
        component_telemetry_celsius=10.0,
        telemetry_quality="estimated",
        thermal_weight=0.0,
        delta_profile=DeltaProfile(0.0, 0.0),
        scale=scale,
    )
    first = evaluate_heatmap_scalar(
        component_telemetry_celsius=60.0,
        telemetry_quality="measured",
        thermal_weight=0.0,
        delta_profile=DeltaProfile(0.0, 0.0),
        scale=scale,
    )
    second = evaluate_heatmap_scalar(
        component_telemetry_celsius=50.0,
        telemetry_quality="stale",
        thermal_weight=1.0,
        delta_profile=DeltaProfile(0.0, 10.0),
        scale=scale,
    )

    assert below.normalized_scalar == 0.0
    assert first.display_temperature_celsius == second.display_temperature_celsius
    assert first.color == second.color
    assert second.quality == "stale"


def test_unavailable_telemetry_and_missing_profile_have_no_fake_colour() -> None:
    missing_value = evaluate_heatmap_scalar(
        component_telemetry_celsius=None,
        telemetry_quality="unavailable",
        thermal_weight=0.4,
        delta_profile=DeltaProfile(0.0, 1.0),
        scale=CelsiusScale(20.0, 90.0),
    )
    missing_profile = evaluate_heatmap_scalar(
        component_telemetry_celsius=50.0,
        telemetry_quality="derived",
        thermal_weight=0.4,
        delta_profile=None,
        scale=CelsiusScale(20.0, 90.0),
    )

    assert not missing_value.available and missing_value.color is None
    assert not missing_profile.available and missing_profile.color is None
    with pytest.raises(ValueError, match="thermal_weight"):
        evaluate_heatmap_scalar(
            component_telemetry_celsius=50.0,
            telemetry_quality="measured",
            thermal_weight=1.1,
            delta_profile=DeltaProfile(0.0, 1.0),
            scale=CelsiusScale(20.0, 90.0),
        )


def test_provider_scale_includes_derived_psu_envelope() -> None:
    config = TelemetryConfig.load(_provider_config_path())
    resolution = resolve_server_wide_celsius_scale(
        config,
        (
            "cpu_temp_c",
            "gpu_1_hotspot_temp_c",
            "gpu_1_memory_temp_c",
            "gpu_2_hotspot_temp_c",
            "gpu_2_memory_temp_c",
            "gpu_3_hotspot_temp_c",
            "gpu_3_memory_temp_c",
            "gpu_3_temp_c",
            "nic_temp_c",
            "psu_temp_estimate_c",
        ),
    )

    assert resolution.scale.minimum == pytest.approx(30.96)
    assert resolution.scale.maximum == 108.0
    assert (
        next(item for item in resolution.metric_envelopes if item.derived).metric_id
        == "psu_temp_estimate_c"
    )
    assert FULL_SPECTRUM_HEATMAP_PALETTE.color_at(0.0) == (0.29, 0.0, 0.51)
    assert FULL_SPECTRUM_HEATMAP_PALETTE.color_at(1.0) == (1.0, 0.0, 0.0)


def test_profiles_change_delta_not_global_scale_or_palette() -> None:
    profile = DeltaProfile(3.0, 14.0)
    matrix = build_delta_profile_matrix(
        ("Idle", "Nominal", "Surge", "Critical"),
        thermal_zone="gpu_core",
        thermal_component="gb203_die",
        calibration=profile,
    )

    assert set(workload for workload, _, _ in matrix) == {
        "Idle",
        "Nominal",
        "Surge",
        "Critical",
    }
    assert set(matrix.values()) == {profile}


def test_reversed_delta_endpoints_are_rejected() -> None:
    with pytest.raises(ValueError, match="minimum_celsius"):
        DeltaProfile(14.0, 3.0)


def test_effective_span_recalibration_preserves_the_authored_range_centre() -> None:
    profile = DeltaProfile(3.0, 9.0)
    recalibrated = recalibrate_effective_delta_span(
        profile,
        weight_minimum=0.4,
        weight_maximum=0.6,
        effective_span_celsius=4.5,
    )

    before = effective_delta_range(
        profile,
        weight_minimum=0.4,
        weight_maximum=0.6,
    )
    after = effective_delta_range(
        recalibrated,
        weight_minimum=0.4,
        weight_maximum=0.6,
    )

    assert after[1] - after[0] == pytest.approx(4.5)
    assert sum(after) / 2.0 == pytest.approx(sum(before) / 2.0)


def test_effective_range_recalibration_matches_nvme_reference_endpoints() -> None:
    recalibrated = recalibrate_effective_delta_range(
        weight_minimum=0.51,
        weight_maximum=0.78,
        desired_minimum_celsius=-2.892,
        desired_maximum_celsius=9.055,
    )

    assert effective_delta_range(
        recalibrated,
        weight_minimum=0.51,
        weight_maximum=0.78,
    ) == pytest.approx((-2.892, 9.055))


def test_cold_biased_weight_remap_is_continuous_monotonic_and_clamped() -> None:
    weights = (0.4, 0.5, 0.6, 0.7, 0.8)
    linear = tuple(
        remap_thermal_weight(
            weight,
            weight_minimum=0.4,
            weight_maximum=0.8,
        )
        for weight in weights
    )
    cold_biased = tuple(
        remap_thermal_weight(
            weight,
            weight_minimum=0.4,
            weight_maximum=0.8,
            mode=THERMAL_WEIGHT_REMAP_COLD_BIASED,
        )
        for weight in weights
    )

    assert linear == weights
    assert cold_biased[0] == pytest.approx(0.4)
    assert cold_biased[3] == pytest.approx(0.6)
    assert cold_biased[-1] == pytest.approx(0.8)
    assert cold_biased == tuple(sorted(cold_biased))
    assert all(0.4 <= weight <= 0.8 for weight in cold_biased)


def test_cold_biased_remap_preserves_temperature_endpoints_and_envelope() -> None:
    kwargs = {
        "component_telemetry_celsius": 50.0,
        "telemetry_quality": "synthetic",
        "delta_profile": DeltaProfile(-4.0, 16.0),
        "scale": CelsiusScale(26.0, 108.0),
        "thermal_weight_minimum": 0.4,
        "thermal_weight_maximum": 0.8,
    }
    linear = tuple(
        evaluate_heatmap_scalar(thermal_weight=weight, **kwargs)
        for weight in (0.4, 0.6, 0.7, 0.8)
    )
    cold_biased = tuple(
        evaluate_heatmap_scalar(
            thermal_weight=weight,
            thermal_weight_remap=THERMAL_WEIGHT_REMAP_COLD_BIASED,
            **kwargs,
        )
        for weight in (0.4, 0.6, 0.7, 0.8)
    )

    assert cold_biased[0].display_temperature_celsius == pytest.approx(
        linear[0].display_temperature_celsius
    )
    assert cold_biased[-1].display_temperature_celsius == pytest.approx(
        linear[-1].display_temperature_celsius
    )
    assert (
        cold_biased[-1].display_temperature_celsius
        - cold_biased[0].display_temperature_celsius
    ) == pytest.approx(
        linear[-1].display_temperature_celsius - linear[0].display_temperature_celsius
    )
    assert cold_biased[2].display_temperature_celsius != pytest.approx(
        linear[2].display_temperature_celsius
    )


def _provider_config_path():
    return Path(__file__).parents[2] / "configs" / "telemetry_provider.toml"


def test_default_delta_profile_is_uniform_and_provider_independent() -> None:
    assert DEFAULT_HEATMAP_DELTA_PROFILE.minimum_celsius == -10.0
    assert DEFAULT_HEATMAP_DELTA_PROFILE.maximum_celsius == 10.0
