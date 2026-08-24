# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""Settings-owned calibration resolution coverage."""

from __future__ import annotations

from pathlib import Path

from digital_twin_runtime_suite.app.heatmaps.calibration import resolve_calibration
from digital_twin_runtime_suite.app.heatmaps.settings import (
    CalibrationSettings,
    HeatmapSettings,
    HeatmapSettingsStore,
)


def test_calibration_resolves_symmetric_delta_and_additive_offset() -> None:
    settings = HeatmapSettings(
        calibration={
            "gpu_01/gpu_core/gb203_die": CalibrationSettings(7.0, 1.5),
        }
    )

    resolved = resolve_calibration(settings, "gpu_01/gpu_core/gb203_die")

    assert resolved.delta_profile.minimum_celsius == -7.0
    assert resolved.delta_profile.maximum_celsius == 7.0
    assert resolved.temperature_offset_celsius == 1.5


def test_semantic_offsets_remain_owned_by_heatmap_settings() -> None:
    repository = Path(__file__).parents[2]
    settings = HeatmapSettingsStore(
        repository / "configs" / "heatmap_settings.toml"
    ).load()

    assert (
        settings.calibration[
            "motherboard/motherboard_passive/heatsink"
        ].temperature_offset_celsius
        == 4.0
    )
    assert (
        settings.calibration[
            "ram/ram_memory_chips/memory_chip"
        ].temperature_offset_celsius
        == 16.0
    )
    assert (
        settings.calibration[
            "psu/psu_main_radiator/radiator"
        ].temperature_offset_celsius
        == 28.0
    )
