# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""Resolve persisted Heatmap calibration rules for discovered semantic targets."""

from __future__ import annotations

from dataclasses import dataclass

from .scalar import DeltaProfile
from .settings import CalibrationSettings, HeatmapSettings


@dataclass(frozen=True)
class ResolvedCalibration:
    """Runtime-ready symmetric delta and additive Celsius offset for one target."""

    calibration_id: str
    delta_profile: DeltaProfile
    temperature_offset_celsius: float


def resolve_calibration(
    settings: HeatmapSettings,
    calibration_id: str,
) -> ResolvedCalibration:
    """Resolve one explicit rule, defaulting only to neutral generic calibration."""

    rule = settings.calibration.get(calibration_id, CalibrationSettings())
    rule.validate()
    return ResolvedCalibration(
        calibration_id=calibration_id,
        delta_profile=DeltaProfile(-rule.delta_celsius, rule.delta_celsius),
        temperature_offset_celsius=rule.temperature_offset_celsius,
    )
