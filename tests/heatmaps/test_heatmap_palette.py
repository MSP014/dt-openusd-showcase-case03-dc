"""Pure configurable Heatmap palette coverage."""

from __future__ import annotations

import pytest

from digital_twin_runtime_suite.app.heatmaps.palette import (
    active_stops,
    color_at,
    palette_scalar,
)
from digital_twin_runtime_suite.app.heatmaps.settings import (
    DEFAULT_COLOR_STOPS,
    ColorScaleSettings,
    ColorStopSettings,
)


def test_default_palette_has_blue_to_red_stops_and_no_violet() -> None:
    palette = ColorScaleSettings()

    assert tuple(stop.stop_id for stop in palette.stops) == (
        "blue",
        "cyan",
        "green",
        "yellow",
        "orange",
        "red",
    )
    assert (0.29, 0.0, 0.51) not in tuple(stop.color for stop in palette.stops)


@pytest.mark.parametrize("active_count", (2, 3, 4, 5, 6))
def test_palette_supports_every_allowed_active_stop_count(active_count: int) -> None:
    stops = tuple(
        ColorStopSettings(
            stop.stop_id,
            index < active_count,
            stop.position_percent,
            stop.color,
        )
        for index, stop in enumerate(DEFAULT_COLOR_STOPS)
    )
    settings = ColorScaleSettings(stops=stops)

    assert len(active_stops(settings)) == active_count
    assert color_at(0.5, settings) == color_at(0.5, settings)


def test_disabled_stops_are_skipped_for_interpolation() -> None:
    settings = ColorScaleSettings(
        stops=(
            ColorStopSettings("blue", True, 0.0, (0.0, 0.0, 1.0)),
            ColorStopSettings("cyan", False, 20.0, (0.0, 1.0, 1.0)),
            ColorStopSettings("red", True, 100.0, (1.0, 0.0, 0.0)),
        )
    )

    assert color_at(0.5, settings) == pytest.approx((0.5, 0.0, 0.5))


def test_active_stop_order_and_clamp_interval_are_validated() -> None:
    invalid = ColorScaleSettings(
        stops=(
            ColorStopSettings("blue", True, 50.0, (0.0, 0.0, 1.0)),
            ColorStopSettings("red", True, 10.0, (1.0, 0.0, 0.0)),
        )
    )

    with pytest.raises(ValueError, match="positions must increase"):
        active_stops(invalid)


def test_color_clamp_saturates_to_first_and_last_active_colours() -> None:
    settings = ColorScaleSettings(
        minimum_clamp_percent=5.0,
        maximum_clamp_percent=95.0,
    )

    assert palette_scalar(0.05, settings) == 0.0
    assert palette_scalar(0.95, settings) == 1.0
    assert color_at(0.0, settings) == (0.0, 0.0, 1.0)
    assert color_at(1.0, settings) == (1.0, 0.0, 0.0)
