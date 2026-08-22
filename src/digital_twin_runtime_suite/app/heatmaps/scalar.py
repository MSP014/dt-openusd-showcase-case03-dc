"""Pure Heatmap scalar calculation and semantic-group spatial normalization."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True)
class CelsiusScale:
    """One absolute Celsius range shared by every active Heatmap target."""

    minimum: float
    maximum: float

    def normalize(self, temperature_celsius: float) -> float:
        """Clamp one displayed Celsius value into the global server scale."""

        if self.maximum <= self.minimum:
            raise ValueError("Heatmap Celsius scale must have a positive span.")
        scalar = (temperature_celsius - self.minimum) / (self.maximum - self.minimum)
        return min(1.0, max(0.0, scalar))


@dataclass(frozen=True)
class DeltaProfile:
    """One authored-spatial Celsius interval applied directly to thermal weight."""

    minimum_celsius: float
    maximum_celsius: float

    def __post_init__(self) -> None:
        """Reject reversed or non-finite runtime spatial temperature intervals."""

        if not (
            isfinite(self.minimum_celsius)
            and isfinite(self.maximum_celsius)
            and self.minimum_celsius <= self.maximum_celsius
        ):
            raise ValueError("Heatmap Delta endpoints must be finite and ordered.")


DEFAULT_HEATMAP_DELTA_PROFILE = DeltaProfile(-10.0, 10.0)


@dataclass(frozen=True)
class ProviderMetricEnvelope:
    """Resolved provider bounds retained as scale derivation evidence."""

    metric_id: str
    minimum: float
    maximum: float
    derived: bool = False


@dataclass(frozen=True)
class ThermalScaleResolution:
    """Fixed scale plus the provider evidence that produced it."""

    scale: CelsiusScale
    metric_envelopes: tuple[ProviderMetricEnvelope, ...]


@dataclass(frozen=True)
class ScalarResult:
    """Displayed Celsius and global scalar, deliberately without palette policy."""

    available: bool
    display_temperature_celsius: float | None
    normalized_scalar: float | None
    quality: str
    reason: str | None = None


def evaluate_heatmap_scalar(
    *,
    component_telemetry_celsius: float | None,
    telemetry_quality: str,
    thermal_weight: float,
    delta_profile: DeltaProfile | None,
    temperature_offset_celsius: float = 0.0,
    scale: CelsiusScale,
) -> ScalarResult:
    """Apply telemetry, offset, and normalized spatial Delta to one vertex."""

    if component_telemetry_celsius is None:
        return ScalarResult(False, None, None, telemetry_quality, "missing telemetry")
    if delta_profile is None:
        return ScalarResult(
            False,
            None,
            None,
            telemetry_quality,
            "missing delta profile",
        )
    if not isfinite(component_telemetry_celsius):
        return ScalarResult(
            False,
            None,
            None,
            telemetry_quality,
            "non-finite telemetry",
        )
    if not isfinite(temperature_offset_celsius):
        return ScalarResult(False, None, None, telemetry_quality, "non-finite offset")
    if not isfinite(thermal_weight) or not 0.0 <= thermal_weight <= 1.0:
        raise ValueError("thermal_weight must be finite and within [0, 1].")
    delta = delta_profile.minimum_celsius + (
        (delta_profile.maximum_celsius - delta_profile.minimum_celsius) * thermal_weight
    )
    display_temperature = (
        component_telemetry_celsius + temperature_offset_celsius + delta
    )
    return ScalarResult(
        True,
        display_temperature,
        scale.normalize(display_temperature),
        telemetry_quality,
    )


def normalize_thermal_weight_group(
    weights_by_prim: Mapping[str, tuple[float, ...]],
) -> Mapping[str, tuple[float, ...]]:
    """Normalize one semantic component's mesh weights into the full 0..1 range."""

    values = tuple(weight for weights in weights_by_prim.values() for weight in weights)
    if not values:
        raise ValueError("Heatmap thermal-weight group has no values.")
    if any(not isfinite(weight) or not 0.0 <= weight <= 1.0 for weight in values):
        raise ValueError("thermal_weight must be finite and within [0, 1].")
    minimum = min(values)
    maximum = max(values)
    if minimum == maximum:
        return MappingProxyType(
            {
                prim_path: tuple(0.5 for _ in weights)
                for prim_path, weights in weights_by_prim.items()
            }
        )
    span = maximum - minimum
    return MappingProxyType(
        {
            prim_path: tuple((weight - minimum) / span for weight in weights)
            for prim_path, weights in weights_by_prim.items()
        }
    )


def build_delta_profile_matrix(
    workloads: tuple[str, ...],
    *,
    thermal_zone: str,
    thermal_component: str,
    calibration: DeltaProfile,
) -> Mapping[tuple[str, str, str], DeltaProfile]:
    """Retain workload-independent calibration evidence for diagnostics."""

    return MappingProxyType(
        {
            (workload, thermal_zone, thermal_component): calibration
            for workload in workloads
        }
    )


def _configured_metric_envelope(
    telemetry_config,
    metric_id: str,
) -> tuple[float, float]:
    metrics = [
        mode.numeric[metric_id]
        for mode in telemetry_config.modes.values()
        if metric_id in mode.numeric
    ]
    if not metrics:
        raise ValueError(f"Provider has no thermal envelope for {metric_id}.")
    return (
        min(float(metric.minimum) for metric in metrics),
        max(float(metric.maximum) for metric in metrics),
    )


def _psu_temperature_for_values(telemetry_config, profile, *, source: str) -> float:
    pdu_value = float(getattr(profile.numeric["pdu_outlet_power_w"], source))
    conversion_loss = pdu_value * (1.0 - telemetry_config.psu_efficiency)
    return min(
        telemetry_config.psu_temp_limit_c,
        telemetry_config.psu_inlet_temp_c
        + conversion_loss * telemetry_config.psu_thermal_resistance_c_per_w,
    )


def _psu_temperature_envelope(telemetry_config) -> ProviderMetricEnvelope:
    values = [
        _psu_temperature_for_values(telemetry_config, mode, source=source)
        for mode in telemetry_config.modes.values()
        for source in ("minimum", "maximum")
    ]
    return ProviderMetricEnvelope(
        "psu_temp_estimate_c",
        min(values),
        max(values),
        derived=True,
    )


def resolve_server_wide_celsius_scale(
    telemetry_config,
    metric_ids: tuple[str, ...],
) -> ThermalScaleResolution:
    """Derive one global Celsius scale from documented provider envelopes."""

    envelopes = []
    for metric_id in sorted(set(metric_ids)):
        if metric_id == "psu_temp_estimate_c":
            envelopes.append(_psu_temperature_envelope(telemetry_config))
            continue
        minimum, maximum = _configured_metric_envelope(telemetry_config, metric_id)
        envelopes.append(ProviderMetricEnvelope(metric_id, minimum, maximum))
    if not envelopes:
        raise ValueError("No Heatmap-bound temperature metrics were provided.")
    return ThermalScaleResolution(
        CelsiusScale(
            minimum=min(item.minimum for item in envelopes),
            maximum=max(item.maximum for item in envelopes),
        ),
        tuple(envelopes),
    )


def resolve_provider_temperature_profile(
    telemetry_config,
    metric_id: str,
    workload: str,
) -> tuple[float, float, float, float]:
    """Resolve configured or PSU-derived provider evidence for one workload."""

    profile = telemetry_config.modes.get(workload)
    if profile is None:
        raise ValueError(f"Provider has no {workload} workload profile.")
    metric = profile.numeric.get(metric_id)
    if metric is not None:
        return (
            float(metric.target),
            float(metric.jitter),
            float(metric.minimum),
            float(metric.maximum),
        )
    if metric_id != "psu_temp_estimate_c":
        raise ValueError(f"Provider has no thermal profile for {metric_id}.")
    target = _psu_temperature_for_values(telemetry_config, profile, source="target")
    minimum = _psu_temperature_for_values(telemetry_config, profile, source="minimum")
    maximum = _psu_temperature_for_values(telemetry_config, profile, source="maximum")
    return target, max(target - minimum, maximum - target), minimum, maximum
