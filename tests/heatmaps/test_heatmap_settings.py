"""Focused persistence coverage for settings-driven Heatmaps."""

from __future__ import annotations

from pathlib import Path

import pytest

from digital_twin_runtime_suite.app.heatmaps.settings import (
    CalibrationSettings,
    ColorScaleSettings,
    ColorStopSettings,
    HeatmapSettings,
    HeatmapSettingsStore,
    diff_heatmap_settings,
)


def test_settings_round_trip_preserves_complete_applied_snapshot(tmp_path) -> None:
    store = HeatmapSettingsStore(tmp_path / "heatmap_settings.toml")
    settings = HeatmapSettings(
        isolation_selectors=("motherboard", "ram", "gpu_01_housing"),
        xray_overlay_group_ids=("chassis", "gpu_shrouds"),
        calibration={
            "ram/memory/dimm_slot": CalibrationSettings(6.5, -8.0),
        },
        color_scale=ColorScaleSettings(minimum_clamp_percent=5.0),
    )

    store.save(settings)

    assert store.load() == settings


def test_settings_reject_invalid_palette_before_persistence(tmp_path) -> None:
    store = HeatmapSettingsStore(tmp_path / "heatmap_settings.toml")
    invalid = HeatmapSettings(
        color_scale=ColorScaleSettings(
            minimum_clamp_percent=95.0,
            maximum_clamp_percent=5.0,
        )
    )

    with pytest.raises(ValueError, match="minimum < maximum"):
        store.save(invalid)

    assert not store.path.exists()


def test_failed_atomic_save_keeps_prior_persisted_settings(
    tmp_path,
    monkeypatch,
) -> None:
    store = HeatmapSettingsStore(tmp_path / "heatmap_settings.toml")
    first = HeatmapSettings(isolation_selectors=("motherboard",))
    second = HeatmapSettings(isolation_selectors=("ram",))
    store.save(first)
    before = store.path.read_bytes()

    def fail_replace(source, destination) -> None:
        raise OSError("injected replace failure")

    monkeypatch.setattr(
        "digital_twin_runtime_suite.app.heatmaps.settings.os.replace",
        fail_replace,
    )

    with pytest.raises(OSError, match="injected replace failure"):
        store.save(second)

    assert store.path.read_bytes() == before
    assert store.load() == first


def test_settings_diff_reports_only_the_applied_parameter_values() -> None:
    previous = HeatmapSettings(
        isolation_selectors=("motherboard",),
        calibration={"motherboard/vrm_west/vrm_heatsink": CalibrationSettings()},
        color_scale=_color_scale(0.0, 100.0, True, 0.0, True, 100.0),
    )
    candidate = HeatmapSettings(
        isolation_selectors=("ram",),
        xray_overlay_group_ids=("chassis",),
        calibration={
            "motherboard/vrm_west/vrm_heatsink": CalibrationSettings(40.0, 2.0)
        },
        color_scale=_color_scale(5.0, 95.0, True, 5.0, False, 90.0),
    )

    assert diff_heatmap_settings(previous, candidate) == (
        ("isolation.selectors", "[ram]"),
        ("xray_overlay.selected_group_ids", "[chassis]"),
        ("calibration.motherboard/vrm_west/vrm_heatsink.delta_celsius", "40"),
        (
            "calibration.motherboard/vrm_west/vrm_heatsink."
            "temperature_offset_celsius",
            "2",
        ),
        ("color_scale.minimum_clamp_percent", "5"),
        ("color_scale.maximum_clamp_percent", "95"),
        ("color_scale.stops.blue.position_percent", "5"),
        ("color_scale.stops.red.enabled", "false"),
        ("color_scale.stops.red.position_percent", "90"),
    )


def _color_scale(
    minimum: float,
    maximum: float,
    blue_enabled: bool,
    blue_position: float,
    red_enabled: bool,
    red_position: float,
) -> ColorScaleSettings:
    return ColorScaleSettings(
        minimum_clamp_percent=minimum,
        maximum_clamp_percent=maximum,
        stops=(
            ColorStopSettings("blue", blue_enabled, blue_position, (0.0, 0.0, 1.0)),
            ColorStopSettings("green", True, 50.0, (0.0, 1.0, 0.0)),
            ColorStopSettings("red", red_enabled, red_position, (1.0, 0.0, 0.0)),
        ),
    )


def test_heatmap_save_never_changes_telemetry_provider_config(tmp_path) -> None:
    repository = Path(__file__).parents[2]
    provider_path = repository / "configs" / "telemetry_provider.toml"
    provider_before = provider_path.read_bytes()
    HeatmapSettingsStore(tmp_path / "heatmap_settings.toml").save(HeatmapSettings())

    assert provider_path.read_bytes() == provider_before
