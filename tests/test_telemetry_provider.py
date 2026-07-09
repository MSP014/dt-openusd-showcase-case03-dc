from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# isort: off
from blackwell_monitoring_suite.app.telemetry.config import TelemetryConfig
from blackwell_monitoring_suite.app.telemetry.model import METRIC_UNITS
from blackwell_monitoring_suite.app.telemetry.model import TELEMETRY_GROUPS
from blackwell_monitoring_suite.app.telemetry.provider import SnapshotLatch
from blackwell_monitoring_suite.app.telemetry.provider import SyntheticTelemetryProvider

# isort: on

CONFIG_PATH = Path("src/blackwell_monitoring_suite/configs/telemetry_provider.toml")


class AdvancingClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 7, 8, 20, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        value = self.current
        self.current += timedelta(seconds=1)
        return value


def test_provider_snapshot_has_expected_metrics_units_and_quality():
    provider = _provider(seed=7)

    snapshot = provider.latest_snapshot

    assert snapshot.operational_state == "Nominal"
    assert set(snapshot.metrics) == set(METRIC_UNITS)
    assert {metric.quality for metric in snapshot.metrics.values()} == {
        "synthetic",
        "derived",
    }
    assert snapshot.metrics["pdu_outlet_power_w"].quality == "synthetic"
    assert snapshot.metrics["psu_output_power_estimate_w"].quality == "derived"
    assert snapshot.metrics["gpu_power_w_total"].quality == "derived"
    assert snapshot.metrics["thermal_headroom_percent"].quality == "derived"
    assert all(
        metric.unit == METRIC_UNITS[metric_id]
        for metric_id, metric in snapshot.metrics.items()
    )
    assert all(
        unit == "\N{DEGREE SIGN}C"
        for metric_id, unit in METRIC_UNITS.items()
        if "temp" in metric_id
    )


def test_seeded_provider_output_is_deterministic():
    first = _provider(seed=42)
    second = _provider(seed=42)

    first_values = {key: metric.value for key, metric in first.tick().metrics.items()}
    second_values = {key: metric.value for key, metric in second.tick().metrics.items()}

    assert first_values == second_values


def test_mode_change_moves_values_towards_new_target_without_jumping():
    provider = _provider(seed=3)
    nominal = float(provider.latest_snapshot.metrics["cpu_temp_c"].value)
    critical_target = provider.config.modes["Critical"].numeric["cpu_temp_c"].target

    provider.set_mode("Critical")
    changed = float(provider.tick().metrics["cpu_temp_c"].value)

    assert nominal < changed < critical_target
    assert provider.latest_snapshot.operational_state == "Critical"


def test_mode_change_can_cross_disjoint_mode_ranges_smoothly():
    provider = _provider(seed=3)
    provider.set_mode("Critical")
    for _ in range(12):
        provider.tick()
    critical = float(provider.latest_snapshot.metrics["cpu_temp_c"].value)

    provider.set_mode("Idle")
    changed = float(provider.tick().metrics["cpu_temp_c"].value)
    idle_maximum = provider.config.modes["Idle"].numeric["cpu_temp_c"].maximum

    assert idle_maximum < changed < critical


def test_gpu_summary_metrics_are_derived_from_three_gpu_values():
    provider = _provider(seed=4)
    metrics = provider.latest_snapshot.metrics

    assert metrics["gpu_temp_c_max"].value == max(
        metrics[f"gpu_{index}_temp_c"].value for index in range(1, 4)
    )
    assert metrics["gpu_power_w_total"].value == pytest.approx(
        sum(metrics[f"gpu_{index}_power_w"].value for index in range(1, 4))
    )
    assert len({metrics[f"gpu_{index}_fan_rpm"].value for index in range(1, 4)}) == 3
    assert (
        metrics["gpu_1_temp_c"].value
        > metrics["gpu_2_temp_c"].value
        > metrics["gpu_3_temp_c"].value
    )


def test_total_gpu_power_is_present_in_array_and_power_groups():
    occurrences = sum(
        metric_ids.count("gpu_power_w_total")
        for metric_ids in TELEMETRY_GROUPS.values()
    )

    assert occurrences == 2


def test_gpu_thermal_values_keep_component_and_sensor_order():
    provider = _provider(seed=14)

    for mode in provider.config.modes:
        provider.set_mode(mode)
        for _ in range(30):
            metrics = provider.tick().metrics
            for suffix in ("temp_c", "memory_temp_c", "hotspot_temp_c"):
                assert (
                    metrics[f"gpu_1_{suffix}"].value
                    >= metrics[f"gpu_2_{suffix}"].value
                    >= metrics[f"gpu_3_{suffix}"].value
                )
            for gpu_index in range(1, 4):
                assert (
                    metrics[f"gpu_{gpu_index}_temp_c"].value
                    <= metrics[f"gpu_{gpu_index}_memory_temp_c"].value
                    <= metrics[f"gpu_{gpu_index}_hotspot_temp_c"].value
                )


def test_connectx7_metrics_respect_link_and_pcie_limits():
    provider = _provider(seed=5)
    provider.set_mode("Critical")
    for _ in range(20):
        metrics = provider.tick().metrics

    assert metrics["link_state"].value == "Up"
    assert metrics["link_speed_gbps"].value == 400.0
    assert metrics["network_rx_gbps"].value + metrics["network_tx_gbps"].value <= 512.0
    assert metrics["nic_temp_c"].value < 105.0


def test_gpu_memory_usage_never_exceeds_card_or_node_capacity():
    provider = _provider(seed=7)
    provider.set_mode("Critical")

    for _ in range(30):
        metrics = provider.tick().metrics
        per_gpu = [
            metrics[f"gpu_{index}_memory_used_gb"].value for index in range(1, 4)
        ]
        assert all(0.0 <= value <= 32.0 for value in per_gpu)
        assert metrics["gpu_memory_used_gb_total"].value == pytest.approx(sum(per_gpu))
        assert metrics["gpu_memory_used_gb_total"].value <= 96.0


def test_chassis_fans_have_independent_bounded_rpm_values():
    provider = _provider(seed=9)
    provider.set_mode("Critical")
    metrics = provider.tick().metrics

    front_values = [metrics[f"front_fan_{index}_rpm"].value for index in range(1, 4)]
    rear_values = [metrics[f"rear_fan_{index}_rpm"].value for index in range(1, 3)]
    assert len(set(front_values)) == 3
    assert len(set(rear_values)) == 2
    assert all(value <= 2100.0 for value in front_values)
    assert all(value <= 5000.0 for value in rear_values)


def test_power_metrics_are_derived_from_pdu_cpu_and_gpu_values():
    provider = _provider(seed=10)
    metrics = provider.latest_snapshot.metrics
    pdu_input = metrics["pdu_outlet_power_w"].value
    psu_output = metrics["psu_output_power_estimate_w"].value
    cpu_power = metrics["cpu_power_w"].value
    gpu_power = metrics["gpu_power_w_total"].value

    assert psu_output == pytest.approx(pdu_input * 0.94)
    assert metrics["platform_residual_power_w"].value == pytest.approx(
        psu_output - cpu_power - gpu_power
    )
    assert metrics["platform_residual_power_w"].value >= 40.0
    assert metrics["psu_conversion_loss_w"].value == pytest.approx(
        pdu_input - psu_output
    )
    assert metrics["psu_temp_estimate_c"].value == pytest.approx(
        24.0 + metrics["psu_conversion_loss_w"].value * 0.4
    )
    assert metrics["psu_temp_estimate_c"].quality == "derived"
    assert metrics["psu_load_percent"].value == pytest.approx(
        (psu_output / 1600.0) * 100.0
    )


def test_power_balance_remains_consistent_across_modes_and_jitter():
    provider = _provider(seed=18)

    for mode in provider.config.modes:
        provider.set_mode(mode)
        for _ in range(50):
            metrics = provider.tick().metrics
            assert metrics["psu_output_power_estimate_w"].value == pytest.approx(
                metrics["cpu_power_w"].value
                + metrics["gpu_power_w_total"].value
                + metrics["platform_residual_power_w"].value
            )
            assert metrics["platform_residual_power_w"].value >= 40.0


def test_derived_metrics_remain_consistent_across_mode_transitions():
    provider = _provider(seed=19)

    for mode in ("Critical", "Idle", "Surge", "Nominal"):
        provider.set_mode(mode)
        for _ in range(50):
            metrics = provider.tick().metrics
            gpu_powers = [
                metrics[f"gpu_{index}_power_w"].value for index in range(1, 4)
            ]
            gpu_memory = [
                metrics[f"gpu_{index}_memory_used_gb"].value for index in range(1, 4)
            ]

            assert metrics["gpu_power_w_total"].value == pytest.approx(sum(gpu_powers))
            assert metrics["gpu_memory_used_gb_total"].value == pytest.approx(
                sum(gpu_memory)
            )
            assert all(
                metrics[f"gpu_{index}_memory_util_percent"].value
                == pytest.approx((gpu_memory[index - 1] / 32.0) * 100.0)
                for index in range(1, 4)
            )
            assert 0.0 <= metrics["thermal_headroom_percent"].value <= 100.0
            assert 0.0 <= metrics["psu_load_percent"].value <= 100.0
            assert (
                provider.config.psu_inlet_temp_c
                <= metrics["psu_temp_estimate_c"].value
                <= provider.config.psu_temp_limit_c
            )


def test_thermal_headroom_is_derived_from_cpu_temperature():
    provider = _provider(seed=20)
    metrics = provider.latest_snapshot.metrics

    expected = ((95.0 - metrics["cpu_temp_c"].value) / (95.0 - 24.0)) * 100.0

    assert metrics["thermal_headroom_percent"].value == pytest.approx(expected)


def test_throttling_stays_inactive_outside_critical_mode():
    provider = _provider(seed=21)

    for mode in ("Idle", "Nominal", "Surge"):
        provider.set_mode(mode)
        assert all(
            provider.tick().metrics["throttling_active"].value is False
            for _ in range(30)
        )


def test_critical_throttling_occurs_in_bounded_episodes():
    provider = _provider(seed=22)
    provider.set_mode("Critical")

    for _ in range(60):
        provider.tick()
    states = [
        bool(provider.tick().metrics["throttling_active"].value) for _ in range(1000)
    ]
    active_ratio = sum(states) / len(states)

    assert 0.15 <= active_ratio <= 0.25
    assert any(states)
    assert not all(states)


def test_invalid_mode_and_refresh_interval_are_rejected():
    provider = _provider(seed=1)

    with pytest.raises(ValueError, match="Unsupported workload mode"):
        provider.set_mode("Turbo")
    with pytest.raises(ValueError, match="Unsupported refresh interval"):
        provider.set_refresh_interval(2)


def test_refresh_interval_is_reported_without_changing_provider_values():
    provider = _provider(seed=5)

    provider.set_refresh_interval(10)
    snapshot = provider.tick()

    assert snapshot.refresh_interval_s == 10


def test_generated_numeric_values_stay_inside_configured_ranges():
    provider = _provider(seed=11)
    global_ranges = {
        metric_id: (
            min(
                mode.numeric[metric_id].minimum
                for mode in provider.config.modes.values()
            ),
            max(
                mode.numeric[metric_id].maximum
                for mode in provider.config.modes.values()
            ),
        )
        for metric_id in provider.config.modes["Nominal"].numeric
    }

    for mode_name, mode_config in provider.config.modes.items():
        provider.set_mode(mode_name)
        for _ in range(30):
            snapshot = provider.tick()
            for metric_id in mode_config.numeric:
                value = float(snapshot.metrics[metric_id].value)
                minimum, maximum = global_ranges[metric_id]
                assert minimum <= value <= maximum


def test_freeze_keeps_display_snapshot_while_provider_advances():
    provider = _provider(seed=13)
    latch = SnapshotLatch()
    frozen = latch.freeze(provider.latest_snapshot)

    advanced = provider.tick()

    assert latch.is_frozen is True
    assert advanced.timestamp > frozen.timestamp
    assert latch.displayed(advanced) is frozen


def test_resume_displays_latest_snapshot_with_newer_timestamp():
    provider = _provider(seed=17)
    latch = SnapshotLatch()
    frozen = latch.freeze(provider.latest_snapshot)
    latest = provider.tick()

    latch.resume()

    assert latch.is_frozen is False
    assert latch.displayed(latest) is latest
    assert latest.timestamp > frozen.timestamp


def _provider(seed: int) -> SyntheticTelemetryProvider:
    config = TelemetryConfig.load(CONFIG_PATH, apply_local_overrides=False)
    return SyntheticTelemetryProvider(
        config,
        seed=seed,
        wall_clock=AdvancingClock(),
    )
