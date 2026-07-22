"""Runtime front-panel LED indicator helpers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IndicatorBlinkConfig:
    """Blink curve for activity-driven front-panel LEDs."""

    minimum_frequency_hz: float = 0.18
    maximum_frequency_hz: float = 1.4
    minimum_duty_cycle: float = 0.18
    maximum_duty_cycle: float = 0.72


@dataclass(frozen=True)
class FrontPanelIndicatorState:
    """Resolved on/off state for the front-panel indicator LEDs."""

    power: bool
    hdd: bool
    lan_01: bool
    lan_02: bool


def activity_blink_state(
    activity_percent: float,
    now_seconds: float,
    *,
    phase_offset: float = 0.0,
    config: IndicatorBlinkConfig = IndicatorBlinkConfig(),
) -> bool:
    """Map activity percentage to deterministic blink state."""

    activity = max(0.0, min(100.0, float(activity_percent))) / 100.0
    if activity <= 0.0:
        return False

    frequency = config.minimum_frequency_hz + (
        (config.maximum_frequency_hz - config.minimum_frequency_hz) * activity
    )
    duty_cycle = config.minimum_duty_cycle + (
        (config.maximum_duty_cycle - config.minimum_duty_cycle) * activity
    )
    phase = ((float(now_seconds) * frequency) + phase_offset) % 1.0
    return phase < duty_cycle


def front_panel_indicator_state(
    metrics,
    now_seconds: float,
    *,
    storage_metric_id: str = "storage_activity_percent",
    lan_01_metric_id: str = "lan_1_activity_percent",
    lan_02_metric_id: str = "lan_2_activity_percent",
) -> FrontPanelIndicatorState:
    """Resolve front-panel LED states from telemetry metrics."""

    return FrontPanelIndicatorState(
        power=True,
        hdd=activity_blink_state(
            _metric_value(metrics, storage_metric_id),
            now_seconds,
            phase_offset=0.13,
        ),
        lan_01=activity_blink_state(
            _metric_value(metrics, lan_01_metric_id),
            now_seconds,
            phase_offset=0.37,
        ),
        lan_02=activity_blink_state(
            _metric_value(metrics, lan_02_metric_id),
            now_seconds,
            phase_offset=0.61,
        ),
    )


def _metric_value(metrics, metric_id: str) -> float:
    metric = metrics.get(metric_id)
    if metric is None:
        return 0.0
    return float(getattr(metric, "value", metric))
