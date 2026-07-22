from dataclasses import replace
from pathlib import Path

import pytest

from blackwell_monitoring_suite.app.telemetry.config import (
    NUMERIC_METRICS,
    TUNING_METRICS,
    TelemetryConfig,
)

CONFIG_PATH = Path("src/blackwell_monitoring_suite/configs/telemetry_provider.toml")


def test_packaged_telemetry_config_loads_all_modes_and_metrics():
    config = TelemetryConfig.load(CONFIG_PATH, apply_local_overrides=False)

    assert config.default_mode == "Nominal"
    assert config.provider_tick_seconds == 1.0
    assert config.psu_capacity_w == 1600.0
    assert config.psu_efficiency == 0.94
    assert config.platform_residual_min_w == 40.0
    assert config.node_inlet_temp_c == 24.0
    assert config.cpu_temp_limit_c == 95.0
    assert config.gpu_hotspot_temp_limit_c == 110.0
    assert config.throttling_cpu_trigger_c == 82.0
    assert config.throttling_gpu_hotspot_trigger_c == 100.0
    assert config.throttling_psu_load_trigger_percent == 65.0
    assert config.throttling_episode_min_s == 2.0
    assert config.throttling_episode_max_s == 5.0
    assert config.throttling_recovery_min_s == 6.0
    assert config.throttling_recovery_max_s == 12.0
    assert config.psu_inlet_temp_c == 24.0
    assert config.psu_thermal_resistance_c_per_w == 0.4
    assert config.psu_temp_limit_c == 90.0
    assert config.default_refresh_interval_s == 1
    assert config.allowed_refresh_intervals_s == (1, 5, 10, 30)
    assert set(config.modes) == {"Idle", "Nominal", "Surge", "Critical"}
    assert config.modes["Critical"].booleans["throttling_allowed"] is True
    assert config.modes["Surge"].booleans["throttling_allowed"] is False
    assert config.modes["Nominal"].strings["health_state"] == "OK"
    assert set(config.modes["Nominal"].numeric) == NUMERIC_METRICS
    assert "gpu_power_w_total" not in NUMERIC_METRICS
    assert len(TUNING_METRICS) == 23
    for mode in config.modes.values():
        assert (
            len({mode.numeric[f"gpu_{index}_temp_c"].target for index in range(1, 4)})
            == 1
        )
        assert all(
            mode.numeric[f"gpu_{index}_power_w"].maximum <= 200.0
            for index in range(1, 4)
        )
        assert mode.numeric["link_speed_gbps"].target == 400.0
        assert mode.numeric["nic_temp_c"].maximum < 105.0
        assert mode.numeric["storage_activity_percent"].maximum <= 100.0
        assert mode.numeric["lan_1_activity_percent"].maximum <= 100.0
        assert mode.numeric["lan_2_activity_percent"].maximum <= 100.0
        assert all(
            mode.numeric[f"gpu_{index}_memory_used_gb"].maximum <= 32.0
            for index in range(1, 4)
        )
        assert all(
            mode.numeric[f"front_fan_{index}_rpm"].maximum <= 2100.0
            for index in range(1, 4)
        )
        assert all(
            mode.numeric[f"rear_fan_{index}_rpm"].maximum <= 5000.0
            for index in range(1, 3)
        )


def test_local_override_merges_without_replacing_other_mode_values(tmp_path):
    config_path = _copy_config(tmp_path)
    local_path = TelemetryConfig.local_config_path_for(config_path)
    local_path.write_text(
        "\n".join(
            [
                "[provider]",
                'default_mode = "Surge"',
                "",
                "[modes.Surge.cpu_temp_c]",
                "target = 74.0",
            ]
        ),
        encoding="utf-8",
    )

    config = TelemetryConfig.load(config_path)

    assert config.default_mode == "Surge"
    assert config.modes["Surge"].numeric["cpu_temp_c"].target == 74.0
    assert config.modes["Surge"].numeric["cpu_temp_c"].minimum == 64.0
    assert config.modes["Nominal"].numeric["cpu_temp_c"].target == 57.0


def test_invalid_default_mode_is_rejected(tmp_path):
    config_path = _copy_config(tmp_path)
    text = config_path.read_text(encoding="utf-8")
    config_path.write_text(
        text.replace('default_mode = "Nominal"', 'default_mode = "Turbo"'),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Invalid default workload mode"):
        TelemetryConfig.load(config_path, apply_local_overrides=False)


def test_default_refresh_interval_must_be_allowed(tmp_path):
    config_path = _copy_config(tmp_path)
    text = config_path.read_text(encoding="utf-8")
    config_path.write_text(
        text.replace(
            "default_refresh_interval_s = 1",
            "default_refresh_interval_s = 2",
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Default refresh interval"):
        TelemetryConfig.load(config_path, apply_local_overrides=False)


def test_metric_target_must_stay_inside_safe_range(tmp_path):
    config_path = _copy_config(tmp_path)
    text = config_path.read_text(encoding="utf-8")
    config_path.write_text(
        text.replace(
            "[modes.Idle.cpu_temp_c]\ntarget = 43.0",
            "[modes.Idle.cpu_temp_c]\ntarget = 99.0",
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Target outside range"):
        TelemetryConfig.load(config_path, apply_local_overrides=False)


def test_local_override_round_trip_preserves_provider_and_mode_values(tmp_path):
    config_path = _copy_config(tmp_path)
    config = TelemetryConfig.load(config_path, apply_local_overrides=False)

    local_path = config.save_local_override()
    reloaded = TelemetryConfig.load(config_path)

    assert local_path.name == "telemetry_provider.local.toml"
    assert reloaded.default_mode == config.default_mode
    assert reloaded.provider_tick_seconds == config.provider_tick_seconds
    assert reloaded.interpolation_factor == config.interpolation_factor
    assert reloaded.modes == config.modes


def test_invalid_power_balance_is_rejected_before_override_is_written(tmp_path):
    config_path = _copy_config(tmp_path)
    config = TelemetryConfig.load(config_path, apply_local_overrides=False)
    mode = config.modes["Nominal"]
    numeric = dict(mode.numeric)
    numeric["pdu_outlet_power_w"] = replace(
        numeric["pdu_outlet_power_w"],
        target=800.0,
        jitter=0.0,
        minimum=780.0,
        maximum=800.0,
    )
    invalid = replace(
        config,
        modes={
            **config.modes,
            "Nominal": replace(mode, numeric=numeric),
        },
    )

    with pytest.raises(ValueError, match="PDU range cannot balance"):
        invalid.save_local_override()

    assert not TelemetryConfig.local_config_path_for(config_path).exists()


def _copy_config(tmp_path: Path) -> Path:
    config_path = tmp_path / "telemetry_provider.toml"
    config_path.write_text(CONFIG_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    return config_path
