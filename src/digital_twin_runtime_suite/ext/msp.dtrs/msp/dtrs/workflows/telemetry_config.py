# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""Persist and reload telemetry-provider edits submitted by OmniUI."""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class TelemetryConfigEdit:
    """Validated scalar edit collected from the telemetry configuration panel."""

    default_mode: str
    default_refresh_interval_s: float
    provider_tick_seconds: float
    interpolation_factor: float
    mode_name: str
    metric_ids: tuple[str, ...]
    target: float
    jitter: float
    minimum: float
    maximum: float


class TelemetryConfigWorkflow:
    """Own telemetry configuration persistence, not OmniUI models or labels."""

    def __init__(self, telemetry_config_path) -> None:
        self._telemetry_config_path = telemetry_config_path

    def save(self, provider, edit: TelemetryConfigEdit):
        """Validate, persist, and reload an edit while preserving live choices."""

        self._validate(edit)
        from digital_twin_runtime_suite.app.telemetry import (
            SyntheticTelemetryProvider,
            TelemetryConfig,
        )
        from digital_twin_runtime_suite.app.telemetry.config import (
            NumericMetricConfig,
        )

        config = provider.config
        current_mode = config.modes[edit.mode_name]
        numeric = dict(current_mode.numeric)
        for metric_id in edit.metric_ids:
            numeric[metric_id] = NumericMetricConfig(
                target=edit.target,
                jitter=edit.jitter,
                minimum=edit.minimum,
                maximum=edit.maximum,
            )
        modes = dict(config.modes)
        modes[edit.mode_name] = replace(current_mode, numeric=numeric)
        updated = replace(
            config,
            default_mode=edit.default_mode,
            provider_tick_seconds=edit.provider_tick_seconds,
            default_refresh_interval_s=edit.default_refresh_interval_s,
            interpolation_factor=edit.interpolation_factor,
            modes=modes,
        )
        updated.save_local_override()
        reloaded = TelemetryConfig.load(self._telemetry_config_path)
        runtime_mode = provider.mode
        runtime_refresh = provider.latest_snapshot.refresh_interval_s
        replacement = SyntheticTelemetryProvider(reloaded)
        replacement.set_mode(runtime_mode)
        if runtime_refresh in reloaded.allowed_refresh_intervals_s:
            replacement.set_refresh_interval(runtime_refresh)
        return replacement

    @staticmethod
    def _validate(edit: TelemetryConfigEdit) -> None:
        if edit.provider_tick_seconds <= 0:
            raise ValueError("Provider tick must be greater than zero.")
        if not 0 < edit.interpolation_factor <= 1:
            raise ValueError("Interpolation must be in the range (0, 1].")
        if edit.minimum > edit.maximum:
            raise ValueError("Minimum must not exceed maximum.")
        if not edit.minimum <= edit.target <= edit.maximum:
            raise ValueError("Target must remain inside the safe range.")
        if edit.jitter < 0:
            raise ValueError("Jitter must not be negative.")
