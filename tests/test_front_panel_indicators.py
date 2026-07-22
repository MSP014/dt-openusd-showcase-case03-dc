from types import SimpleNamespace

from blackwell_monitoring_suite.app.front_panel_indicators import (
    activity_blink_state,
    front_panel_indicator_state,
)


def test_activity_blink_state_is_off_for_zero_activity():
    assert activity_blink_state(0.0, 0.0) is False


def test_activity_blink_state_pulses_for_positive_activity():
    assert activity_blink_state(100.0, 0.0) is True


def test_activity_blink_state_has_dark_phase_even_at_high_activity():
    assert activity_blink_state(100.0, 0.55) is False


def test_activity_blink_state_clamps_activity_range():
    assert activity_blink_state(-10.0, 0.0) is False
    assert activity_blink_state(120.0, 0.0) is True


def test_front_panel_indicator_state_reads_metric_values():
    metrics = {
        "storage_activity_percent": SimpleNamespace(value=0.0),
        "lan_1_activity_percent": SimpleNamespace(value=100.0),
        "lan_2_activity_percent": SimpleNamespace(value=0.0),
    }

    state = front_panel_indicator_state(metrics, 0.0)

    assert state.power is True
    assert state.hdd is False
    assert state.lan_01 is True
    assert state.lan_02 is False


def test_front_panel_indicator_state_treats_missing_metrics_as_inactive():
    state = front_panel_indicator_state({}, 0.0)

    assert state.power is True
    assert state.hdd is False
    assert state.lan_01 is False
    assert state.lan_02 is False
