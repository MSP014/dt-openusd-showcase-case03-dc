"""Pure draft feedback and HEX-to-RGB boundary coverage for Color Scale UI."""

from __future__ import annotations

import pytest

from digital_twin_runtime_suite.app.heatmaps.palette import (
    ColorScaleStopDraft,
    color_scale_draft_feedback,
    color_scale_settings_from_draft,
    heatmap_hex_to_rgb,
    heatmap_rgb_to_hex,
)
from digital_twin_runtime_suite.app.heatmaps.scalar import CelsiusScale
from digital_twin_runtime_suite.app.heatmaps.settings import (
    HeatmapSettings,
    HeatmapSettingsStore,
)


def test_hex_draft_converts_to_existing_persisted_rgb_without_mutating_applied() -> (
    None
):
    applied = HeatmapSettings()
    candidate = color_scale_settings_from_draft(
        minimum_clamp_percent=0.0,
        maximum_clamp_percent=100.0,
        stops=_draft_stops("#D6F7FF"),
    )

    assert heatmap_hex_to_rgb("#00FFFF") == (0.0, 1.0, 1.0)
    assert heatmap_rgb_to_hex((0.0, 1.0, 1.0)) == "#00FFFF"
    assert candidate.stops[1].color == pytest.approx((214 / 255, 247 / 255, 1.0))
    assert applied.color_scale.stops[1].color == (0.0, 1.0, 1.0)


def test_invalid_hex_rejects_before_persisting_or_replacing_applied_settings(
    tmp_path,
) -> None:
    store = HeatmapSettingsStore(tmp_path / "heatmap_settings.toml")
    applied = HeatmapSettings()
    store.save(applied)

    with pytest.raises(ValueError, match="#RRGGBB"):
        color_scale_settings_from_draft(
            minimum_clamp_percent=0.0,
            maximum_clamp_percent=100.0,
            stops=_draft_stops("cyan"),
        )

    assert store.load() == applied


def test_preview_reflects_valid_draft_hex() -> None:
    feedback = _feedback(32.0, 125.0, 0.0, 100.0, _draft_stops("#D6F7FF"))

    assert feedback[1].preview_color == pytest.approx((214 / 255, 247 / 255, 1.0))


def test_draft_labels_use_the_current_global_scale_and_clamp_interval() -> None:
    full = _feedback(32.0, 125.0, 0.0, 100.0, _draft_stops("#00FFFF"))
    clamped = _feedback(32.0, 125.0, 5.0, 95.0, _draft_stops("#00FFFF"))

    assert _labels(full) == (
        "Less 32.0°C",
        "50.6°C",
        "69.2°C",
        "87.8°C",
        "106.4°C",
        "More 125.0°C",
    )
    assert _labels(clamped) == (
        "Less 36.7°C",
        "53.4°C",
        "70.1°C",
        "86.9°C",
        "103.6°C",
        "More 120.4°C",
    )


def test_disabled_boundaries_move_saturation_labels_to_active_stops() -> None:
    stops = list(_draft_stops("#00FFFF"))
    stops[0] = ColorScaleStopDraft("blue", False, 0.0, "#0000FF")
    stops[-1] = ColorScaleStopDraft("red", False, 100.0, "#FF0000")

    assert _labels(_feedback(32.0, 125.0, 5.0, 95.0, tuple(stops))) == (
        "36.7°C",
        "Less 53.4°C",
        "70.1°C",
        "86.9°C",
        "More 103.6°C",
        "120.4°C",
    )


def test_draft_clamp_and_position_feedback_does_not_change_applied_settings() -> None:
    applied = HeatmapSettings()
    stops = list(_draft_stops("#00FFFF"))
    stops[2] = ColorScaleStopDraft("green", True, 50.0, "#00FF00")

    feedback = _feedback(32.0, 125.0, 5.0, 95.0, tuple(stops))

    assert feedback[2].temperature_label == "78.5°C"
    assert applied.color_scale.minimum_clamp_percent == 0.0
    assert applied.color_scale.stops[2].position_percent == 40.0


def _feedback(
    minimum: float,
    maximum: float,
    clamp_minimum: float,
    clamp_maximum: float,
    stops: tuple[ColorScaleStopDraft, ...],
):
    return color_scale_draft_feedback(
        CelsiusScale(minimum, maximum),
        minimum_clamp_percent=clamp_minimum,
        maximum_clamp_percent=clamp_maximum,
        stops=stops,
    )


def _draft_stops(cyan_hex: str) -> tuple[ColorScaleStopDraft, ...]:
    return (
        ColorScaleStopDraft("blue", True, 0.0, "#0000FF"),
        ColorScaleStopDraft("cyan", True, 20.0, cyan_hex),
        ColorScaleStopDraft("green", True, 40.0, "#00FF00"),
        ColorScaleStopDraft("yellow", True, 60.0, "#FFFF00"),
        ColorScaleStopDraft("orange", True, 80.0, "#FF8000"),
        ColorScaleStopDraft("red", True, 100.0, "#FF0000"),
    )


def _labels(feedback) -> tuple[str, ...]:
    return tuple(item.temperature_label for item in feedback)
