"""Pure post-normalisation Heatmap palette policy."""

from __future__ import annotations

from dataclasses import dataclass

from .settings import ColorScaleSettings


@dataclass(frozen=True)
class ActivePaletteStop:
    """One enabled stop expressed inside the configured clamp interval."""

    position: float
    color: tuple[float, float, float]


def active_stops(settings: ColorScaleSettings) -> tuple[ActivePaletteStop, ...]:
    """Return only enabled stops after validating their persisted order."""

    settings.validate()
    return tuple(
        ActivePaletteStop(stop.position_percent / 100.0, stop.color)
        for stop in settings.stops
        if stop.enabled
    )


def palette_scalar(
    temperature_scalar: float,
    settings: ColorScaleSettings,
) -> float:
    """Clamp absolute Celsius normalisation into the palette interval."""

    settings.validate()
    minimum = settings.minimum_clamp_percent / 100.0
    maximum = settings.maximum_clamp_percent / 100.0
    return _clamp((temperature_scalar - minimum) / (maximum - minimum))


def color_at(
    temperature_scalar: float,
    settings: ColorScaleSettings,
) -> tuple[float, float, float]:
    """Interpolate active stops, saturating to their first and last colours."""

    stops = active_stops(settings)
    scalar = palette_scalar(temperature_scalar, settings)
    if scalar <= stops[0].position:
        return stops[0].color
    for lower, upper in zip(stops, stops[1:]):
        if scalar <= upper.position:
            factor = (scalar - lower.position) / (upper.position - lower.position)
            return tuple(
                lower.color[index] + (upper.color[index] - lower.color[index]) * factor
                for index in range(3)
            )
    return stops[-1].color


def compact_active_stops(
    settings: ColorScaleSettings,
) -> tuple[ActivePaletteStop, ...]:
    """Expose the 2–6 ordered stops used by one generic MDL material."""

    return active_stops(settings)


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))
