# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""Pure fixed-scale velocity-presentation contracts for Streamlines."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass


@dataclass(frozen=True)
class PhysicalSpeedScale:
    """One workload/profile-independent range in source velocity units."""

    minimum: float
    maximum: float
    units: str = "source velocity units"

    def __post_init__(self) -> None:
        if (
            not math.isfinite(self.minimum)
            or not math.isfinite(self.maximum)
            or self.maximum <= self.minimum
            or not self.units.strip()
        ):
            raise ValueError("Streamlines physical speed scale is invalid.")


@dataclass(frozen=True)
class PaletteStop:
    """One ordered fixed-scale engineering palette stop."""

    position: float
    color: tuple[float, float, float]

    def __post_init__(self) -> None:
        if (
            not math.isfinite(self.position)
            or not 0.0 <= self.position <= 1.0
            or len(self.color) != 3
            or any(
                not math.isfinite(value) or not 0.0 <= value <= 1.0
                for value in self.color
            )
        ):
            raise ValueError("Streamlines palette stop is invalid.")


@dataclass(frozen=True)
class StreamlinesPresentation:
    """Cache-independent production material settings."""

    speed_scale: PhysicalSpeedScale
    palette: tuple[PaletteStop, ...]
    opacity: float
    emission_intensity: float
    lighting_influence: float

    def __post_init__(self) -> None:
        positions = tuple(stop.position for stop in self.palette)
        if (
            len(self.palette) != 5
            or positions != tuple(sorted(positions))
            or positions[0] != 0.0
            or positions[-1] != 1.0
            or len(set(positions)) != len(positions)
            or not math.isfinite(self.opacity)
            or not 0.0 <= self.opacity <= 1.0
            or not math.isfinite(self.emission_intensity)
            or self.emission_intensity < 0.0
            or not math.isfinite(self.lighting_influence)
            or not 0.0 <= self.lighting_influence <= 1.0
        ):
            raise ValueError("Streamlines presentation contract is invalid.")

    @property
    def signature(self) -> str:
        """Hash presentation only; geometry/cache identity is intentionally absent."""

        payload = {
            "speed_min": self.speed_scale.minimum,
            "speed_max": self.speed_scale.maximum,
            "speed_units": self.speed_scale.units,
            "palette": [
                {"position": stop.position, "color": list(stop.color)}
                for stop in self.palette
            ],
            "opacity": self.opacity,
            "emission_intensity": self.emission_intensity,
            "lighting_influence": self.lighting_influence,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


def normalize_speed(value: float, scale: PhysicalSpeedScale) -> float:
    """Clamp one raw speed into the shared normalized presentation range."""

    value = float(value)
    if not math.isfinite(value) or value < 0.0:
        raise ValueError("Raw Streamlines speed must be finite and non-negative.")
    return min(1.0, max(0.0, (value - scale.minimum) / (scale.maximum - scale.minimum)))


def palette_color(
    value: float,
    presentation: StreamlinesPresentation,
) -> tuple[float, float, float]:
    """Interpolate the fixed palette for one raw physical speed."""

    normalized = normalize_speed(value, presentation.speed_scale)
    for left, right in zip(presentation.palette, presentation.palette[1:]):
        if normalized <= right.position:
            span = right.position - left.position
            weight = (normalized - left.position) / span
            return tuple(
                left.color[index] + (right.color[index] - left.color[index]) * weight
                for index in range(3)
            )
    return presentation.palette[-1].color
