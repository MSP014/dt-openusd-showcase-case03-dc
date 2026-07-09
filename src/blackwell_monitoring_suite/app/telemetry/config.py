"""Configuration loading for the synthetic telemetry provider."""

from __future__ import annotations

import copy
import json
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .model import HEALTH_STATES, METRIC_UNITS, WORKLOAD_MODES

STRING_METRICS = {"health_state", "link_state"}
MODE_BOOLEAN_SETTINGS = {"throttling_allowed"}
DERIVED_BOOLEAN_METRICS = {"throttling_active"}
DERIVED_NUMERIC_METRICS = {
    "gpu_temp_c_max",
    "gpu_memory_temp_c_max",
    "gpu_hotspot_temp_c_max",
    "gpu_power_w_total",
    "gpu_memory_used_gb_total",
    "gpu_1_memory_util_percent",
    "gpu_2_memory_util_percent",
    "gpu_3_memory_util_percent",
    "thermal_headroom_percent",
    "psu_output_power_estimate_w",
    "platform_residual_power_w",
    "psu_conversion_loss_w",
    "psu_temp_estimate_c",
    "psu_load_percent",
}
NUMERIC_METRICS = (
    set(METRIC_UNITS)
    - STRING_METRICS
    - DERIVED_BOOLEAN_METRICS
    - DERIVED_NUMERIC_METRICS
)
COMPONENT_TUNING_GROUPS = {
    "gpu_temp_c": tuple(f"gpu_{index}_temp_c" for index in range(1, 4)),
    "gpu_memory_temp_c": tuple(f"gpu_{index}_memory_temp_c" for index in range(1, 4)),
    "gpu_hotspot_temp_c": tuple(f"gpu_{index}_hotspot_temp_c" for index in range(1, 4)),
    "gpu_power_w": tuple(f"gpu_{index}_power_w" for index in range(1, 4)),
    "gpu_fan_rpm": tuple(f"gpu_{index}_fan_rpm" for index in range(1, 4)),
    "gpu_memory_used_gb": tuple(f"gpu_{index}_memory_used_gb" for index in range(1, 4)),
    "front_intake_fan_rpm": tuple(f"front_fan_{index}_rpm" for index in range(1, 4)),
    "rear_exhaust_fan_rpm": tuple(f"rear_fan_{index}_rpm" for index in range(1, 3)),
}
COMPONENT_METRICS = {
    metric_id
    for metric_ids in COMPONENT_TUNING_GROUPS.values()
    for metric_id in metric_ids
}
FIXED_NUMERIC_METRICS = {"link_speed_gbps"}
TUNING_METRICS = (NUMERIC_METRICS - COMPONENT_METRICS - FIXED_NUMERIC_METRICS) | set(
    COMPONENT_TUNING_GROUPS
)
TUNING_METRIC_LABELS = {
    "gpu_temp_c": "GPU temperature",
    "gpu_memory_temp_c": "GPU memory",
    "gpu_hotspot_temp_c": "GPU hotspot",
    "gpu_power_w": "GPU power",
    "gpu_fan_rpm": "GPU blower",
    "gpu_memory_used_gb": "GPU memory used",
    "front_intake_fan_rpm": "Front intake fans",
    "rear_exhaust_fan_rpm": "Rear exhaust fans",
}


@dataclass(frozen=True)
class NumericMetricConfig:
    """Target and safe range for a generated numeric metric."""

    target: float
    jitter: float
    minimum: float
    maximum: float


@dataclass(frozen=True)
class ModeConfig:
    """Configured values for one workload mode."""

    numeric: dict[str, NumericMetricConfig]
    strings: dict[str, str]
    booleans: dict[str, bool]


@dataclass(frozen=True)
class TelemetryConfig:
    """Resolved provider configuration."""

    config_path: Path
    schema_version: str
    provider_id: str
    provider_type: str
    default_mode: str
    provider_tick_seconds: float
    default_refresh_interval_s: int
    allowed_refresh_intervals_s: tuple[int, ...]
    interpolation_factor: float
    psu_capacity_w: float
    psu_efficiency: float
    platform_residual_min_w: float
    node_inlet_temp_c: float
    cpu_temp_limit_c: float
    gpu_hotspot_temp_limit_c: float
    throttling_cpu_trigger_c: float
    throttling_gpu_hotspot_trigger_c: float
    throttling_psu_load_trigger_percent: float
    throttling_episode_min_s: float
    throttling_episode_max_s: float
    throttling_recovery_min_s: float
    throttling_recovery_max_s: float
    psu_inlet_temp_c: float
    psu_thermal_resistance_c_per_w: float
    psu_temp_limit_c: float
    modes: dict[str, ModeConfig]

    @classmethod
    def load(
        cls,
        config_path: Path | str,
        apply_local_overrides: bool = True,
    ) -> "TelemetryConfig":
        """Load the packaged provider config and optional local override."""

        resolved_path = Path(config_path).resolve()
        with resolved_path.open("rb") as config_file:
            data = tomllib.load(config_file)

        if apply_local_overrides:
            local_path = cls.local_config_path_for(resolved_path)
            if local_path.exists():
                with local_path.open("rb") as local_file:
                    local_data = tomllib.load(local_file)
                data = _deep_merge(data, local_data)

        provider = data.get("provider", {})
        default_mode = str(provider.get("default_mode", "Nominal"))
        if default_mode not in WORKLOAD_MODES:
            raise ValueError(f"Invalid default workload mode: {default_mode}")

        allowed_intervals = tuple(
            int(value)
            for value in provider.get("allowed_refresh_intervals_s", [1, 5, 10, 30])
        )
        default_interval = int(provider.get("default_refresh_interval_s", 1))
        if not allowed_intervals or any(value <= 0 for value in allowed_intervals):
            raise ValueError("Refresh intervals must be positive integers.")
        if default_interval not in allowed_intervals:
            raise ValueError(
                "Default refresh interval must be included in allowed intervals."
            )

        tick_seconds = float(provider.get("tick_seconds", 1.0))
        interpolation_factor = float(provider.get("interpolation_factor", 0.35))
        psu_capacity_w = float(provider.get("psu_capacity_w", 1600.0))
        psu_efficiency = float(provider.get("psu_efficiency", 0.94))
        platform_residual_min_w = float(provider.get("platform_residual_min_w", 40.0))
        node_inlet_temp_c = float(provider.get("node_inlet_temp_c", 24.0))
        cpu_temp_limit_c = float(provider.get("cpu_temp_limit_c", 95.0))
        gpu_hotspot_temp_limit_c = float(
            provider.get("gpu_hotspot_temp_limit_c", 110.0)
        )
        throttling_cpu_trigger_c = float(provider.get("throttling_cpu_trigger_c", 82.0))
        throttling_gpu_trigger_c = float(
            provider.get("throttling_gpu_hotspot_trigger_c", 100.0)
        )
        throttling_psu_trigger_percent = float(
            provider.get("throttling_psu_load_trigger_percent", 65.0)
        )
        throttling_episode_min_s = float(provider.get("throttling_episode_min_s", 2.0))
        throttling_episode_max_s = float(provider.get("throttling_episode_max_s", 5.0))
        throttling_recovery_min_s = float(
            provider.get("throttling_recovery_min_s", 6.0)
        )
        throttling_recovery_max_s = float(
            provider.get("throttling_recovery_max_s", 12.0)
        )
        psu_inlet_temp_c = float(provider.get("psu_inlet_temp_c", 24.0))
        psu_thermal_resistance = float(
            provider.get("psu_thermal_resistance_c_per_w", 0.4)
        )
        psu_temp_limit_c = float(provider.get("psu_temp_limit_c", 90.0))
        if tick_seconds <= 0:
            raise ValueError("Provider tick must be greater than zero.")
        if not 0 < interpolation_factor <= 1:
            raise ValueError("Interpolation factor must be in the range (0, 1].")
        if psu_capacity_w <= 0:
            raise ValueError("PSU capacity must be greater than zero.")
        if not 0 < psu_efficiency <= 1:
            raise ValueError("PSU efficiency must be in the range (0, 1].")
        if platform_residual_min_w < 0:
            raise ValueError("Platform residual minimum must not be negative.")
        if cpu_temp_limit_c <= node_inlet_temp_c:
            raise ValueError(
                "CPU temperature limit must exceed node inlet temperature."
            )
        if gpu_hotspot_temp_limit_c <= throttling_gpu_trigger_c:
            raise ValueError("GPU hotspot limit must exceed its throttle trigger.")
        if cpu_temp_limit_c <= throttling_cpu_trigger_c:
            raise ValueError("CPU temperature limit must exceed its throttle trigger.")
        if not 0 <= throttling_psu_trigger_percent < 100:
            raise ValueError("PSU load throttle trigger must be in the range [0, 100).")
        if not 0 < throttling_episode_min_s <= throttling_episode_max_s:
            raise ValueError("Invalid throttling episode duration range.")
        if not 0 <= throttling_recovery_min_s <= throttling_recovery_max_s:
            raise ValueError("Invalid throttling recovery duration range.")
        if psu_thermal_resistance < 0:
            raise ValueError("PSU thermal resistance must not be negative.")
        if psu_temp_limit_c < psu_inlet_temp_c:
            raise ValueError(
                "PSU temperature limit must not be below inlet temperature."
            )

        raw_modes = data.get("modes", {})
        modes = {
            mode: _parse_mode(mode, raw_modes.get(mode)) for mode in WORKLOAD_MODES
        }
        _validate_power_balance(
            modes,
            psu_efficiency,
            platform_residual_min_w,
        )

        return cls(
            config_path=resolved_path,
            schema_version=str(provider.get("schema_version", "1.0")),
            provider_id=str(provider.get("provider_id", "bms.synthetic.node")),
            provider_type=str(provider.get("provider_type", "synthetic")),
            default_mode=default_mode,
            provider_tick_seconds=tick_seconds,
            default_refresh_interval_s=default_interval,
            allowed_refresh_intervals_s=allowed_intervals,
            interpolation_factor=interpolation_factor,
            psu_capacity_w=psu_capacity_w,
            psu_efficiency=psu_efficiency,
            platform_residual_min_w=platform_residual_min_w,
            node_inlet_temp_c=node_inlet_temp_c,
            cpu_temp_limit_c=cpu_temp_limit_c,
            gpu_hotspot_temp_limit_c=gpu_hotspot_temp_limit_c,
            throttling_cpu_trigger_c=throttling_cpu_trigger_c,
            throttling_gpu_hotspot_trigger_c=throttling_gpu_trigger_c,
            throttling_psu_load_trigger_percent=throttling_psu_trigger_percent,
            throttling_episode_min_s=throttling_episode_min_s,
            throttling_episode_max_s=throttling_episode_max_s,
            throttling_recovery_min_s=throttling_recovery_min_s,
            throttling_recovery_max_s=throttling_recovery_max_s,
            psu_inlet_temp_c=psu_inlet_temp_c,
            psu_thermal_resistance_c_per_w=psu_thermal_resistance,
            psu_temp_limit_c=psu_temp_limit_c,
            modes=modes,
        )

    @staticmethod
    def local_config_path_for(config_path: Path | str) -> Path:
        """Return the sibling local override path."""

        path = Path(config_path).resolve()
        return path.with_name(f"{path.stem}.local{path.suffix}")

    def save_local_override(self) -> Path:
        """Persist the resolved provider settings as a local TOML override."""

        _validate_power_balance(
            self.modes,
            self.psu_efficiency,
            self.platform_residual_min_w,
        )
        local_path = self.local_config_path_for(self.config_path)
        local_path.write_text(_serialise_config(self), encoding="utf-8")
        return local_path


def _parse_mode(mode: str, data: Any) -> ModeConfig:
    if not isinstance(data, dict):
        raise ValueError(f"Missing telemetry mode config: {mode}")

    numeric: dict[str, NumericMetricConfig] = {}
    for metric_id in sorted(NUMERIC_METRICS):
        metric = data.get(metric_id)
        if not isinstance(metric, dict):
            raise ValueError(f"Missing numeric metric {mode}.{metric_id}")
        target = float(metric["target"])
        jitter = float(metric.get("jitter", 0.0))
        minimum = float(metric["min"])
        maximum = float(metric["max"])
        if minimum > maximum:
            raise ValueError(f"Invalid range for {mode}.{metric_id}")
        if not minimum <= target <= maximum:
            raise ValueError(f"Target outside range for {mode}.{metric_id}")
        if jitter < 0:
            raise ValueError(f"Jitter must not be negative for {mode}.{metric_id}")
        numeric[metric_id] = NumericMetricConfig(
            target=target,
            jitter=jitter,
            minimum=minimum,
            maximum=maximum,
        )

    strings = {}
    for metric_id in STRING_METRICS:
        value = str(data.get(metric_id, ""))
        if metric_id == "health_state" and value not in HEALTH_STATES:
            raise ValueError(f"Invalid health state for {mode}: {value}")
        if metric_id == "link_state" and value not in {"Up", "Down", "Degraded"}:
            raise ValueError(f"Invalid link state for {mode}: {value}")
        strings[metric_id] = value

    booleans = {
        setting_id: bool(data.get(setting_id, False))
        for setting_id in MODE_BOOLEAN_SETTINGS
    }
    return ModeConfig(numeric=numeric, strings=strings, booleans=booleans)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _validate_power_balance(
    modes: dict[str, ModeConfig],
    psu_efficiency: float,
    platform_residual_min_w: float,
) -> None:
    for mode_name, mode in modes.items():
        maximum_component_power = mode.numeric["cpu_power_w"].maximum + sum(
            mode.numeric[f"gpu_{index}_power_w"].maximum for index in range(1, 4)
        )
        required_pdu_input = (
            maximum_component_power + platform_residual_min_w
        ) / psu_efficiency
        if required_pdu_input > mode.numeric["pdu_outlet_power_w"].maximum:
            raise ValueError(
                f"PDU range cannot balance maximum component power in {mode_name}."
            )


def _serialise_config(config: TelemetryConfig) -> str:
    lines = [
        "[provider]",
        f"default_mode = {json.dumps(config.default_mode)}",
        f"tick_seconds = {config.provider_tick_seconds}",
        f"default_refresh_interval_s = {config.default_refresh_interval_s}",
        f"interpolation_factor = {config.interpolation_factor}",
        f"psu_capacity_w = {config.psu_capacity_w}",
        f"psu_efficiency = {config.psu_efficiency}",
        f"platform_residual_min_w = {config.platform_residual_min_w}",
        f"node_inlet_temp_c = {config.node_inlet_temp_c}",
        f"cpu_temp_limit_c = {config.cpu_temp_limit_c}",
        f"gpu_hotspot_temp_limit_c = {config.gpu_hotspot_temp_limit_c}",
        f"throttling_cpu_trigger_c = {config.throttling_cpu_trigger_c}",
        "throttling_gpu_hotspot_trigger_c = "
        f"{config.throttling_gpu_hotspot_trigger_c}",
        "throttling_psu_load_trigger_percent = "
        f"{config.throttling_psu_load_trigger_percent}",
        f"throttling_episode_min_s = {config.throttling_episode_min_s}",
        f"throttling_episode_max_s = {config.throttling_episode_max_s}",
        f"throttling_recovery_min_s = {config.throttling_recovery_min_s}",
        f"throttling_recovery_max_s = {config.throttling_recovery_max_s}",
        f"psu_inlet_temp_c = {config.psu_inlet_temp_c}",
        "psu_thermal_resistance_c_per_w = " f"{config.psu_thermal_resistance_c_per_w}",
        f"psu_temp_limit_c = {config.psu_temp_limit_c}",
    ]

    for mode_name, mode in config.modes.items():
        lines.extend(
            [
                "",
                f"[modes.{mode_name}]",
                f"health_state = {json.dumps(mode.strings['health_state'])}",
                f"link_state = {json.dumps(mode.strings['link_state'])}",
                "throttling_allowed = "
                f"{str(mode.booleans['throttling_allowed']).lower()}",
            ]
        )
        for metric_id, metric in mode.numeric.items():
            lines.extend(
                [
                    "",
                    f"[modes.{mode_name}.{metric_id}]",
                    f"target = {metric.target}",
                    f"jitter = {metric.jitter}",
                    f"min = {metric.minimum}",
                    f"max = {metric.maximum}",
                ]
            )

    return "\n".join(lines) + "\n"
