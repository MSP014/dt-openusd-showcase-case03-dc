# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""Raw source-velocity speed values for persisted Streamlines vertices."""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence

SPEED_PRIMVAR_NAME = "dtrs:speed"
SPEED_PRIMVAR_ATTRIBUTE = f"primvars:{SPEED_PRIMVAR_NAME}"


def speed_magnitudes_from_velocity_vectors(
    vectors: Iterable[Sequence[float]],
    *,
    expected_point_count: int,
) -> tuple[float, ...]:
    """Return unscaled vector magnitudes for exactly one curve-vertex set."""

    values = tuple(
        tuple(float(component) for component in vector) for vector in vectors
    )
    if len(values) != expected_point_count:
        raise ValueError(
            "Probed velocity vector count does not match Streamlines point count."
        )
    speeds = []
    for vector in values:
        if len(vector) != 3 or not all(math.isfinite(value) for value in vector):
            raise ValueError("Probed Streamlines velocity vector is invalid.")
        speeds.append(math.sqrt(sum(value * value for value in vector)))
    return tuple(speeds)


def validate_persisted_speed_magnitudes(
    values: Iterable[float],
    *,
    expected_point_count: int,
) -> tuple[float, ...]:
    """Require a finite non-negative raw speed at every cached curve vertex."""

    speeds = tuple(float(value) for value in values)
    if len(speeds) != expected_point_count:
        raise ValueError(
            "Persisted Streamlines speed count does not match curve point count."
        )
    if any(not math.isfinite(value) or value < 0.0 for value in speeds):
        raise ValueError("Persisted Streamlines speed values are invalid.")
    return speeds
