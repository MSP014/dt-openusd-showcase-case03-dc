"""Synthetic latest-snapshot telemetry provider."""

from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import Callable

from .config import TelemetryConfig
from .model import METRIC_UNITS, WORKLOAD_MODES, MetricValue, TelemetrySnapshot

WallClock = Callable[[], datetime]


class SyntheticTelemetryProvider:
    """Generate bounded node telemetry for the selected workload mode."""

    def __init__(
        self,
        config: TelemetryConfig,
        *,
        seed: int | None = None,
        wall_clock: WallClock | None = None,
    ) -> None:
        self.config = config
        # This generator drives visual jitter and is not used for security.
        self._random = random.Random(seed)  # nosec B311
        self._wall_clock = wall_clock or (lambda: datetime.now(timezone.utc))
        self._mode = config.default_mode
        self._refresh_interval_s = config.default_refresh_interval_s
        self._throttling_active = False
        self._throttling_remaining_s = 0.0
        self._throttling_recovery_remaining_s = 0.0
        self._current_numeric = {
            metric_id: metric.target + self._gpu_component_bias(metric_id)
            for metric_id, metric in config.modes[self._mode].numeric.items()
        }
        self._latest_snapshot: TelemetrySnapshot | None = None
        self.tick()

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def latest_snapshot(self) -> TelemetrySnapshot:
        if self._latest_snapshot is None:
            raise RuntimeError("Telemetry provider has not produced a snapshot.")
        return self._latest_snapshot

    def set_mode(self, mode: str) -> None:
        """Select the global synthetic workload mode."""

        if mode not in WORKLOAD_MODES:
            raise ValueError(f"Unsupported workload mode: {mode}")
        self._mode = mode

    def set_refresh_interval(self, interval_s: int) -> None:
        """Set the UI sampling interval reported in snapshots."""

        if interval_s not in self.config.allowed_refresh_intervals_s:
            raise ValueError(f"Unsupported refresh interval: {interval_s}")
        self._refresh_interval_s = interval_s

    def tick(self) -> TelemetrySnapshot:
        """Advance generated values by one fixed provider step."""

        mode = self.config.modes[self._mode]
        metrics: dict[str, MetricValue] = {}
        for metric_id, metric_config in mode.numeric.items():
            bias = self._gpu_component_bias(metric_id)
            target = metric_config.target + bias
            current = self._current_numeric.get(metric_id, target)
            interpolated = current + (
                (target - current) * self.config.interpolation_factor
            )
            jitter = self._random.uniform(
                -metric_config.jitter,
                metric_config.jitter,
            )
            transition_minimum = min(metric_config.minimum, current)
            transition_maximum = max(metric_config.maximum, current)
            value = min(
                transition_maximum,
                max(transition_minimum, interpolated + jitter),
            )
            self._current_numeric[metric_id] = value
            metrics[metric_id] = MetricValue(
                value=value,
                unit=METRIC_UNITS[metric_id],
            )

        for metric_id, value in mode.strings.items():
            metrics[metric_id] = MetricValue(
                value=value,
                unit=METRIC_UNITS[metric_id],
            )
        self._normalise_gpu_thermals(metrics)
        self._add_thermal_headroom(metrics)
        self._add_gpu_aggregates(metrics)
        self._add_power_metrics(metrics)
        self._update_throttling(metrics, mode.booleans["throttling_allowed"])

        self._latest_snapshot = TelemetrySnapshot.create(
            schema_version=self.config.schema_version,
            provider_id=self.config.provider_id,
            provider_type=self.config.provider_type,
            timestamp=self._wall_clock(),
            operational_state=self._mode,
            refresh_interval_s=self._refresh_interval_s,
            metrics=metrics,
        )
        return self._latest_snapshot

    @staticmethod
    def _gpu_component_bias(metric_id: str) -> float:
        if not metric_id.startswith("gpu_") or metric_id[4:5] not in {"1", "2", "3"}:
            return 0.0
        gpu_index = int(metric_id[4])
        if metric_id.endswith(("_temp_c", "_memory_temp_c", "_hotspot_temp_c")):
            return {1: 2.0, 2: 0.0, 3: -2.0}[gpu_index]
        if metric_id.endswith("_fan_rpm"):
            return {1: 100.0, 2: 0.0, 3: -100.0}[gpu_index]
        return 0.0

    def _normalise_gpu_thermals(
        self,
        metrics: dict[str, MetricValue],
    ) -> None:
        thermal_suffixes = ("temp_c", "memory_temp_c", "hotspot_temp_c")

        for gpu_index in range(1, 4):
            metric_ids = [f"gpu_{gpu_index}_{suffix}" for suffix in thermal_suffixes]
            ordered_values = sorted(
                float(metrics[metric_id].value) for metric_id in metric_ids
            )
            for metric_id, value in zip(metric_ids, ordered_values):
                self._set_numeric_metric(metrics, metric_id, value)

        for suffix in thermal_suffixes:
            metric_ids = [f"gpu_{index}_{suffix}" for index in range(1, 4)]
            ordered_values = sorted(
                (float(metrics[metric_id].value) for metric_id in metric_ids),
                reverse=True,
            )
            for metric_id, value in zip(metric_ids, ordered_values):
                self._set_numeric_metric(metrics, metric_id, value)

    def _add_thermal_headroom(
        self,
        metrics: dict[str, MetricValue],
    ) -> None:
        cpu_temp = float(metrics["cpu_temp_c"].value)
        available_span = self.config.cpu_temp_limit_c - self.config.node_inlet_temp_c
        headroom = min(
            100.0,
            max(
                0.0,
                ((self.config.cpu_temp_limit_c - cpu_temp) / available_span) * 100.0,
            ),
        )
        metrics["thermal_headroom_percent"] = MetricValue(
            value=headroom,
            unit=METRIC_UNITS["thermal_headroom_percent"],
            quality="derived",
        )

    def _set_numeric_metric(
        self,
        metrics: dict[str, MetricValue],
        metric_id: str,
        value: float,
    ) -> None:
        self._current_numeric[metric_id] = value
        metrics[metric_id] = MetricValue(
            value=value,
            unit=METRIC_UNITS[metric_id],
        )

    @staticmethod
    def _add_gpu_aggregates(metrics: dict[str, MetricValue]) -> None:
        aggregate_sources = {
            "gpu_temp_c_max": [f"gpu_{index}_temp_c" for index in range(1, 4)],
            "gpu_memory_temp_c_max": [
                f"gpu_{index}_memory_temp_c" for index in range(1, 4)
            ],
            "gpu_hotspot_temp_c_max": [
                f"gpu_{index}_hotspot_temp_c" for index in range(1, 4)
            ],
        }
        for metric_id, source_ids in aggregate_sources.items():
            metrics[metric_id] = MetricValue(
                value=max(float(metrics[source_id].value) for source_id in source_ids),
                unit=METRIC_UNITS[metric_id],
                quality="derived",
            )

        metrics["gpu_power_w_total"] = MetricValue(
            value=sum(
                float(metrics[f"gpu_{index}_power_w"].value) for index in range(1, 4)
            ),
            unit=METRIC_UNITS["gpu_power_w_total"],
            quality="derived",
        )
        memory_values = [
            float(metrics[f"gpu_{index}_memory_used_gb"].value) for index in range(1, 4)
        ]
        for index, memory_used_gb in enumerate(memory_values, start=1):
            metric_id = f"gpu_{index}_memory_util_percent"
            metrics[metric_id] = MetricValue(
                value=(memory_used_gb / 32.0) * 100.0,
                unit=METRIC_UNITS[metric_id],
                quality="derived",
            )
        metrics["gpu_memory_used_gb_total"] = MetricValue(
            value=sum(memory_values),
            unit=METRIC_UNITS["gpu_memory_used_gb_total"],
            quality="derived",
        )

    def _add_power_metrics(self, metrics: dict[str, MetricValue]) -> None:
        cpu_power = float(metrics["cpu_power_w"].value)
        gpu_power = float(metrics["gpu_power_w_total"].value)
        minimum_pdu_input = (
            cpu_power + gpu_power + self.config.platform_residual_min_w
        ) / self.config.psu_efficiency
        pdu_input = max(
            float(metrics["pdu_outlet_power_w"].value),
            minimum_pdu_input,
        )
        self._set_numeric_metric(metrics, "pdu_outlet_power_w", pdu_input)
        psu_output = pdu_input * self.config.psu_efficiency
        platform_residual = psu_output - cpu_power - gpu_power
        conversion_loss = max(0.0, pdu_input - psu_output)
        psu_temp_estimate = min(
            self.config.psu_temp_limit_c,
            self.config.psu_inlet_temp_c
            + conversion_loss * self.config.psu_thermal_resistance_c_per_w,
        )
        psu_load = min(
            100.0,
            (psu_output / self.config.psu_capacity_w) * 100.0,
        )
        derived_values = {
            "psu_output_power_estimate_w": psu_output,
            "platform_residual_power_w": platform_residual,
            "psu_conversion_loss_w": conversion_loss,
            "psu_temp_estimate_c": psu_temp_estimate,
            "psu_load_percent": psu_load,
        }
        for metric_id, value in derived_values.items():
            metrics[metric_id] = MetricValue(
                value=value,
                unit=METRIC_UNITS[metric_id],
                quality="derived",
            )

    def _update_throttling(
        self,
        metrics: dict[str, MetricValue],
        throttling_allowed: bool,
    ) -> None:
        tick_seconds = self.config.provider_tick_seconds
        if not throttling_allowed:
            self._throttling_active = False
            self._throttling_remaining_s = 0.0
            self._throttling_recovery_remaining_s = 0.0
        elif self._throttling_active:
            self._throttling_remaining_s -= tick_seconds
            if self._throttling_remaining_s <= 0:
                self._throttling_active = False
                self._throttling_recovery_remaining_s = self._random.uniform(
                    self.config.throttling_recovery_min_s,
                    self.config.throttling_recovery_max_s,
                )
        elif self._throttling_recovery_remaining_s > 0:
            self._throttling_recovery_remaining_s = max(
                0.0,
                self._throttling_recovery_remaining_s - tick_seconds,
            )
        else:
            pressure = self._throttling_pressure(metrics)
            if pressure > 0 and self._random.random() < pressure:
                self._throttling_active = True
                self._throttling_remaining_s = self._random.uniform(
                    self.config.throttling_episode_min_s,
                    self.config.throttling_episode_max_s,
                )

        metrics["throttling_active"] = MetricValue(
            value=self._throttling_active,
            unit=METRIC_UNITS["throttling_active"],
        )

    def _throttling_pressure(
        self,
        metrics: dict[str, MetricValue],
    ) -> float:
        pressures = (
            self._normalised_pressure(
                float(metrics["cpu_temp_c"].value),
                self.config.throttling_cpu_trigger_c,
                self.config.cpu_temp_limit_c,
            ),
            self._normalised_pressure(
                float(metrics["gpu_hotspot_temp_c_max"].value),
                self.config.throttling_gpu_hotspot_trigger_c,
                self.config.gpu_hotspot_temp_limit_c,
            ),
            self._normalised_pressure(
                float(metrics["psu_load_percent"].value),
                self.config.throttling_psu_load_trigger_percent,
                100.0,
            ),
        )
        return sum(pressures) / len(pressures)

    @staticmethod
    def _normalised_pressure(value: float, trigger: float, limit: float) -> float:
        return min(1.0, max(0.0, (value - trigger) / (limit - trigger)))


class SnapshotLatch:
    """Keep a stable display snapshot while the provider continues updating."""

    def __init__(self) -> None:
        self._frozen_snapshot: TelemetrySnapshot | None = None

    @property
    def is_frozen(self) -> bool:
        return self._frozen_snapshot is not None

    def freeze(self, snapshot: TelemetrySnapshot) -> TelemetrySnapshot:
        self._frozen_snapshot = snapshot
        return snapshot

    def resume(self) -> None:
        self._frozen_snapshot = None

    def displayed(self, latest: TelemetrySnapshot) -> TelemetrySnapshot:
        return self._frozen_snapshot or latest
