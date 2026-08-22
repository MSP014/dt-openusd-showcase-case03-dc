"""Pure Heatmap thermal math, provider-derived scale, and fixed palette."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from types import MappingProxyType
from typing import Mapping

THERMAL_WEIGHT_REMAP_LINEAR = "linear"
THERMAL_WEIGHT_REMAP_COLD_BIASED = "cold_biased"
_COLD_BIASED_WEIGHT_PIVOT = 0.75


@dataclass(frozen=True)
class CelsiusScale:
    """One absolute Celsius range shared by the resolved DTRS server."""

    minimum: float
    maximum: float

    def normalize(self, temperature_celsius: float) -> float:
        """Clamp one derived temperature into the fixed server-wide scale."""

        if self.maximum <= self.minimum:
            raise ValueError("Heatmap Celsius scale must have a positive span.")
        normalized = (temperature_celsius - self.minimum) / (
            self.maximum - self.minimum
        )
        return min(1.0, max(0.0, normalized))


@dataclass(frozen=True)
class PaletteStop:
    """One source-controlled colour point in the fixed full-spectrum ramp."""

    position: float
    color: tuple[float, float, float]


@dataclass(frozen=True)
class HeatmapPalette:
    """Absolute scalar-to-colour mapping independent of thermal semantics."""

    stops: tuple[PaletteStop, ...]

    def color_at(self, normalized_scalar: float) -> tuple[float, float, float]:
        """Interpolate the fixed ramp after scalar clamping."""

        scalar = min(1.0, max(0.0, normalized_scalar))
        for lower, upper in zip(self.stops, self.stops[1:]):
            if scalar <= upper.position:
                span = upper.position - lower.position
                factor = 0.0 if span <= 0.0 else (scalar - lower.position) / span
                return tuple(
                    lower.color[index]
                    + (upper.color[index] - lower.color[index]) * factor
                    for index in range(3)
                )
        return self.stops[-1].color


FULL_SPECTRUM_HEATMAP_PALETTE = HeatmapPalette(
    (
        PaletteStop(0.0, (0.29, 0.0, 0.51)),
        PaletteStop(1.0 / 6.0, (0.0, 0.0, 1.0)),
        PaletteStop(2.0 / 6.0, (0.0, 1.0, 1.0)),
        PaletteStop(3.0 / 6.0, (0.0, 1.0, 0.0)),
        PaletteStop(4.0 / 6.0, (1.0, 1.0, 0.0)),
        PaletteStop(5.0 / 6.0, (1.0, 0.5, 0.0)),
        PaletteStop(1.0, (1.0, 0.0, 0.0)),
    )
)


@dataclass(frozen=True)
class DeltaProfile:
    """One semantic spatial offset profile measured in degrees Celsius."""

    minimum_celsius: float
    maximum_celsius: float

    def __post_init__(self) -> None:
        """Reject reversed spatial temperature intervals."""

        if self.minimum_celsius > self.maximum_celsius:
            raise ValueError("minimum_celsius must not exceed maximum_celsius.")


DEFAULT_HEATMAP_DELTA_PROFILE = DeltaProfile(
    minimum_celsius=-10.0,
    maximum_celsius=10.0,
)


@dataclass(frozen=True)
class ProviderMetricEnvelope:
    """Resolved provider bounds retained as scale derivation evidence."""

    metric_id: str
    minimum: float
    maximum: float
    derived: bool = False


@dataclass(frozen=True)
class ThermalScaleResolution:
    """Fixed scale plus the resolved provider evidence that produced it."""

    scale: CelsiusScale
    metric_envelopes: tuple[ProviderMetricEnvelope, ...]


@dataclass(frozen=True)
class ScalarResult:
    """Derived spatial temperature and presentation scalar for one vertex weight."""

    available: bool
    display_temperature_celsius: float | None
    normalized_scalar: float | None
    color: tuple[float, float, float] | None
    quality: str
    reason: str | None = None


def _validate_weight_range(weight_minimum: float, weight_maximum: float) -> None:
    """Reject invalid authored ranges before applying a spatial profile."""

    if not 0.0 <= weight_minimum <= weight_maximum <= 1.0:
        raise ValueError("Heatmap weight range must stay within [0, 1].")


def remap_thermal_weight(
    thermal_weight: float,
    *,
    weight_minimum: float,
    weight_maximum: float,
    mode: str = THERMAL_WEIGHT_REMAP_LINEAR,
) -> float:
    """Map authored weight for presentation without modifying its USD value."""

    if not 0.0 <= thermal_weight <= 1.0:
        raise ValueError("thermal_weight must be within [0, 1].")
    _validate_weight_range(weight_minimum, weight_maximum)
    if mode == THERMAL_WEIGHT_REMAP_LINEAR or weight_minimum == weight_maximum:
        return float(thermal_weight)
    if mode != THERMAL_WEIGHT_REMAP_COLD_BIASED:
        raise ValueError(f"Unknown Heatmap thermal-weight remap: {mode}.")
    span = weight_maximum - weight_minimum
    normalized = min(1.0, max(0.0, (thermal_weight - weight_minimum) / span))
    if normalized <= _COLD_BIASED_WEIGHT_PIVOT:
        remapped = 0.5 * (normalized / _COLD_BIASED_WEIGHT_PIVOT)
    else:
        remapped = 0.5 + 0.5 * (
            (normalized - _COLD_BIASED_WEIGHT_PIVOT) / (1.0 - _COLD_BIASED_WEIGHT_PIVOT)
        )
    return weight_minimum + (span * min(1.0, max(0.0, remapped)))


def effective_delta_range(
    profile: DeltaProfile,
    *,
    weight_minimum: float,
    weight_maximum: float,
) -> tuple[float, float]:
    """Return the delta interval reachable by the authored weight range."""

    _validate_weight_range(weight_minimum, weight_maximum)
    span = profile.maximum_celsius - profile.minimum_celsius
    return (
        profile.minimum_celsius + span * weight_minimum,
        profile.minimum_celsius + span * weight_maximum,
    )


def recalibrate_effective_delta_span(
    profile: DeltaProfile,
    *,
    weight_minimum: float,
    weight_maximum: float,
    effective_span_celsius: float,
) -> DeltaProfile:
    """Fit a requested effective span while preserving the current centre."""

    _validate_weight_range(weight_minimum, weight_maximum)
    if effective_span_celsius < 0.0:
        raise ValueError("Heatmap effective delta span must be non-negative.")
    weight_span = weight_maximum - weight_minimum
    if weight_span == 0.0:
        return profile
    current_low, current_high = effective_delta_range(
        profile,
        weight_minimum=weight_minimum,
        weight_maximum=weight_maximum,
    )
    centre = (current_low + current_high) / 2.0
    slope = effective_span_celsius / weight_span
    midpoint = (weight_minimum + weight_maximum) / 2.0
    minimum = centre - slope * midpoint
    return DeltaProfile(minimum, minimum + slope)


def recalibrate_effective_delta_range(
    *,
    weight_minimum: float,
    weight_maximum: float,
    desired_minimum_celsius: float,
    desired_maximum_celsius: float,
) -> DeltaProfile:
    """Fit raw endpoints so authored weights reach an explicit delta range."""

    _validate_weight_range(weight_minimum, weight_maximum)
    if desired_minimum_celsius > desired_maximum_celsius:
        raise ValueError("Heatmap effective delta range is reversed.")
    weight_span = weight_maximum - weight_minimum
    if weight_span == 0.0:
        raise ValueError("Cannot fit a non-flat range to uniform Heatmap weights.")
    slope = (desired_maximum_celsius - desired_minimum_celsius) / weight_span
    minimum = desired_minimum_celsius - slope * weight_minimum
    return DeltaProfile(minimum, minimum + slope)


def build_delta_profile_matrix(
    workloads: tuple[str, ...],
    *,
    thermal_zone: str,
    thermal_component: str,
    calibration: DeltaProfile,
) -> Mapping[tuple[str, str, str], DeltaProfile]:
    """Assign one immutable profile to each workload for one semantic role."""

    return MappingProxyType(
        {
            (workload, thermal_zone, thermal_component): calibration
            for workload in workloads
        }
    )


def evaluate_heatmap_scalar(
    *,
    component_telemetry_celsius: float | None,
    telemetry_quality: str,
    thermal_weight: float,
    delta_profile: DeltaProfile | None,
    scale: CelsiusScale,
    thermal_weight_minimum: float = 0.0,
    thermal_weight_maximum: float = 1.0,
    thermal_weight_remap: str = THERMAL_WEIGHT_REMAP_LINEAR,
) -> ScalarResult:
    """Derive a truthful spatial temperature without telemetry fabrication."""

    if component_telemetry_celsius is None:
        return ScalarResult(
            False, None, None, None, telemetry_quality, "missing telemetry"
        )
    if delta_profile is None:
        return ScalarResult(
            False, None, None, None, telemetry_quality, "missing delta profile"
        )
    if not isfinite(component_telemetry_celsius):
        return ScalarResult(
            False, None, None, None, telemetry_quality, "non-finite telemetry"
        )
    weight = remap_thermal_weight(
        thermal_weight,
        weight_minimum=thermal_weight_minimum,
        weight_maximum=thermal_weight_maximum,
        mode=thermal_weight_remap,
    )
    display_temperature = component_telemetry_celsius + (
        delta_profile.minimum_celsius
        + (delta_profile.maximum_celsius - delta_profile.minimum_celsius) * weight
    )
    normalized = scale.normalize(display_temperature)
    return ScalarResult(
        True,
        display_temperature,
        normalized,
        FULL_SPECTRUM_HEATMAP_PALETTE.color_at(normalized),
        telemetry_quality,
    )


def _configured_metric_envelope(
    telemetry_config,
    metric_id: str,
) -> tuple[float, float]:
    """Read the resolved configured envelope across provider workloads."""

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
    """Mirror the provider's documented PSU estimate from configured PDU power."""

    pdu_value = float(getattr(profile.numeric["pdu_outlet_power_w"], source))
    conversion_loss = pdu_value * (1.0 - telemetry_config.psu_efficiency)
    return min(
        telemetry_config.psu_temp_limit_c,
        telemetry_config.psu_inlet_temp_c
        + conversion_loss * telemetry_config.psu_thermal_resistance_c_per_w,
    )


def _psu_temperature_envelope(telemetry_config) -> ProviderMetricEnvelope:
    """Retain the derived PSU envelope as explicit scale evidence."""

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
    """Derive one scale from the resolved provider envelope, not constants."""

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
        scale=CelsiusScale(
            minimum=min(item.minimum for item in envelopes),
            maximum=max(item.maximum for item in envelopes),
        ),
        metric_envelopes=tuple(envelopes),
    )


def resolve_provider_temperature_profile(
    telemetry_config,
    metric_id: str,
    workload: str,
) -> tuple[float, float, float, float]:
    """Resolve configured or derived provider evidence for one workload."""

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
