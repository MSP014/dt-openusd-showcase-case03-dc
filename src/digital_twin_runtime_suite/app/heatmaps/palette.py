# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""Pure post-normalisation Heatmap palette policy."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from .scalar import CelsiusScale
from .settings import ColorScaleSettings, ColorStopSettings


@dataclass(frozen=True)
class ActivePaletteStop:
    """One enabled stop expressed inside the configured clamp interval."""

    position: float
    color: tuple[float, float, float]


@dataclass(frozen=True)
class ColorScaleStopDraft:
    """One editable colour-stop row before it becomes persisted RGB settings."""

    stop_id: str
    enabled: bool
    position_percent: float
    hex_color: str


@dataclass(frozen=True)
class ColorScaleStopDraftFeedback:
    """Read-only temperature label and preview colour for one draft row."""

    stop_id: str
    temperature_label: str
    preview_color: tuple[float, float, float] | None


def heatmap_rgb_to_hex(color: tuple[float, float, float]) -> str:
    """Format persisted normalized Heatmap RGB as strict operator-facing HEX."""

    _validate_heatmap_rgb(color)
    return "#" + "".join(f"{round(component * 255):02X}" for component in color)


def heatmap_hex_to_rgb(value: str) -> tuple[float, float, float]:
    """Parse one strict #RRGGBB Heatmap draft value into persisted RGB."""

    token = value.strip()
    if (
        len(token) != 7
        or not token.startswith("#")
        or any(character not in "0123456789abcdefABCDEF" for character in token[1:])
    ):
        raise ValueError("Heatmap color HEX must use #RRGGBB.")
    return tuple(int(token[index : index + 2], 16) / 255.0 for index in range(1, 7, 2))


def color_scale_settings_from_draft(
    *,
    minimum_clamp_percent: float,
    maximum_clamp_percent: float,
    stops: tuple[ColorScaleStopDraft, ...],
) -> ColorScaleSettings:
    """Validate draft HEX values before creating the existing persisted RGB form."""

    return ColorScaleSettings(
        minimum_clamp_percent=minimum_clamp_percent,
        maximum_clamp_percent=maximum_clamp_percent,
        stops=tuple(
            ColorStopSettings(
                stop_id=stop.stop_id,
                enabled=stop.enabled,
                position_percent=stop.position_percent,
                color=heatmap_hex_to_rgb(stop.hex_color),
            )
            for stop in stops
        ),
    )


def color_scale_draft_feedback(
    scale: CelsiusScale | None,
    *,
    minimum_clamp_percent: float,
    maximum_clamp_percent: float,
    stops: tuple[ColorScaleStopDraft, ...],
) -> tuple[ColorScaleStopDraftFeedback, ...]:
    """Project draft controls into live labels without validating or mutating them."""

    active_indexes = tuple(index for index, stop in enumerate(stops) if stop.enabled)
    first_active = active_indexes[0] if active_indexes else None
    last_active = active_indexes[-1] if active_indexes else None
    return tuple(
        ColorScaleStopDraftFeedback(
            stop_id=stop.stop_id,
            temperature_label=_draft_temperature_label(
                scale,
                minimum_clamp_percent,
                maximum_clamp_percent,
                stop.position_percent,
                first=position == first_active,
                last=position == last_active,
            ),
            preview_color=_draft_preview_color(stop.hex_color),
        )
        for position, stop in enumerate(stops)
    )


def _draft_temperature_label(
    scale: CelsiusScale | None,
    minimum_clamp_percent: float,
    maximum_clamp_percent: float,
    position_percent: float,
    *,
    first: bool,
    last: bool,
) -> str:
    if scale is None:
        return "Temperature scale unavailable"
    span = scale.maximum - scale.minimum
    clamp_minimum = scale.minimum + span * (minimum_clamp_percent / 100.0)
    clamp_maximum = scale.minimum + span * (maximum_clamp_percent / 100.0)
    temperature = clamp_minimum + (
        (clamp_maximum - clamp_minimum) * (position_percent / 100.0)
    )
    prefix = "Less " if first else "More " if last else ""
    return f"{prefix}{_format_celsius(temperature)}°C"


def _format_celsius(value: float) -> str:
    """Round display-only labels predictably at an exact tenth boundary."""

    return str(
        Decimal(str(value)).quantize(
            Decimal("0.1"),
            rounding=ROUND_HALF_UP,
        )
    )


def _draft_preview_color(value: str) -> tuple[float, float, float] | None:
    try:
        return heatmap_hex_to_rgb(value)
    except ValueError:
        return None


def _validate_heatmap_rgb(color: tuple[float, float, float]) -> None:
    if len(color) != 3 or any(not 0.0 <= component <= 1.0 for component in color):
        raise ValueError("Heatmap color must be three RGB values in [0, 1].")


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
