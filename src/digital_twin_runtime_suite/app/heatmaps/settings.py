# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""Persisted Heatmap settings and their validation boundary."""

from __future__ import annotations

import math
import os
import tempfile
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

SETTINGS_FILENAME = "heatmap_settings.toml"


@dataclass(frozen=True)
class CalibrationSettings:
    """One asset-zone-component spatial temperature rule."""

    delta_celsius: float = 10.0
    temperature_offset_celsius: float = 0.0

    def validate(self) -> None:
        """Reject non-finite or negative symmetric spatial deltas."""

        if not math.isfinite(self.delta_celsius) or self.delta_celsius < 0.0:
            raise ValueError("Calibration Delta must be finite and non-negative.")
        if not math.isfinite(self.temperature_offset_celsius):
            raise ValueError("Calibration Temperature Offset must be finite.")


@dataclass(frozen=True)
class ColorStopSettings:
    """One persisted palette stop; colour is intentionally read-only in the UI."""

    stop_id: str
    enabled: bool
    position_percent: float
    color: tuple[float, float, float]

    def validate(self) -> None:
        """Validate persisted colour and interval-relative stop position."""

        if not self.stop_id:
            raise ValueError("Heatmap colour-stop id must not be empty.")
        if not (
            math.isfinite(self.position_percent)
            and 0.0 <= self.position_percent <= 100.0
        ):
            raise ValueError("Heatmap colour-stop position must be within [0, 100].")
        if len(self.color) != 3 or any(
            not math.isfinite(channel) or not 0.0 <= channel <= 1.0
            for channel in self.color
        ):
            raise ValueError(
                "Heatmap colour-stop colour must be RGB values within [0, 1]."
            )


DEFAULT_COLOR_STOPS = (
    ColorStopSettings("blue", True, 0.0, (0.0, 0.0, 1.0)),
    ColorStopSettings("cyan", True, 20.0, (0.0, 1.0, 1.0)),
    ColorStopSettings("green", True, 40.0, (0.0, 1.0, 0.0)),
    ColorStopSettings("yellow", True, 60.0, (1.0, 1.0, 0.0)),
    ColorStopSettings("orange", True, 80.0, (1.0, 0.5, 0.0)),
    ColorStopSettings("red", True, 100.0, (1.0, 0.0, 0.0)),
)


@dataclass(frozen=True)
class ColorScaleSettings:
    """Palette interval and stops applied after absolute Celsius normalisation."""

    minimum_clamp_percent: float = 0.0
    maximum_clamp_percent: float = 100.0
    stops: tuple[ColorStopSettings, ...] = DEFAULT_COLOR_STOPS

    def validate(self) -> None:
        """Require a usable palette before any USD or material mutation."""

        if not (
            math.isfinite(self.minimum_clamp_percent)
            and math.isfinite(self.maximum_clamp_percent)
            and 0.0 <= self.minimum_clamp_percent < self.maximum_clamp_percent <= 100.0
        ):
            raise ValueError(
                "Heatmap clamp must satisfy 0 <= minimum < maximum <= 100."
            )
        if not 2 <= len(self.stops) <= 6:
            raise ValueError("Heatmap palette must contain between 2 and 6 stops.")
        ids = tuple(stop.stop_id for stop in self.stops)
        if len(set(ids)) != len(ids):
            raise ValueError("Heatmap colour-stop ids must be unique.")
        for stop in self.stops:
            stop.validate()
        active_positions = tuple(
            stop.position_percent for stop in self.stops if stop.enabled
        )
        if len(active_positions) < 2:
            raise ValueError("Heatmap palette requires at least two active stops.")
        if any(
            upper <= lower
            for lower, upper in zip(active_positions, active_positions[1:])
        ):
            raise ValueError("Active Heatmap colour-stop positions must increase.")


@dataclass(frozen=True)
class HeatmapSettings:
    """One complete settings candidate, separate from UI draft and active state."""

    isolation_selectors: tuple[str, ...] = ()
    xray_overlay_group_ids: tuple[str, ...] = ()
    calibration: Mapping[str, CalibrationSettings] = field(
        default_factory=lambda: MappingProxyType({})
    )
    color_scale: ColorScaleSettings = ColorScaleSettings()

    def __post_init__(self) -> None:
        """Freeze mapping ownership so saved and active snapshots cannot drift."""

        object.__setattr__(
            self,
            "calibration",
            MappingProxyType(dict(self.calibration)),
        )

    def validate(self) -> None:
        """Validate the complete candidate without touching runtime presentation."""

        if len(set(self.isolation_selectors)) != len(self.isolation_selectors):
            raise ValueError("Heatmap Isolation selectors must be unique.")
        if any(not selector for selector in self.isolation_selectors):
            raise ValueError("Heatmap Isolation selectors must not be empty.")
        if len(set(self.xray_overlay_group_ids)) != len(self.xray_overlay_group_ids):
            raise ValueError("Heatmap X-Ray Overlay groups must be unique.")
        if any(not group_id for group_id in self.xray_overlay_group_ids):
            raise ValueError("Heatmap X-Ray Overlay groups must not be empty.")
        for calibration_id, rule in self.calibration.items():
            if not calibration_id:
                raise ValueError("Heatmap calibration id must not be empty.")
            rule.validate()
        self.color_scale.validate()


def default_heatmap_settings() -> HeatmapSettings:
    """Return an off-by-default palette configuration with no hidden selection."""

    return HeatmapSettings()


def diff_heatmap_settings(
    previous: HeatmapSettings,
    candidate: HeatmapSettings,
) -> tuple[tuple[str, str], ...]:
    """Describe only changed persisted settings for one operator-facing audit log."""

    changes: list[tuple[str, str]] = []
    if previous.isolation_selectors != candidate.isolation_selectors:
        changes.append(
            ("isolation.selectors", _format_sequence(candidate.isolation_selectors))
        )
    if previous.xray_overlay_group_ids != candidate.xray_overlay_group_ids:
        changes.append(
            (
                "xray_overlay.selected_group_ids",
                _format_sequence(candidate.xray_overlay_group_ids),
            )
        )
    _append_calibration_changes(changes, previous.calibration, candidate.calibration)
    _append_color_scale_changes(changes, previous.color_scale, candidate.color_scale)
    return tuple(changes)


class HeatmapSettingsStore:
    """Own atomic TOML round trips; it never owns active presentation state."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def load(self) -> HeatmapSettings:
        """Load a validated snapshot, using defaults only before the first save."""

        if not self.path.exists():
            return default_heatmap_settings()
        with self.path.open("rb") as stream:
            document = tomllib.load(stream)
        settings = _settings_from_document(document)
        settings.validate()
        return settings

    def has_explicit_xray_overlay_selection(self) -> bool:
        """Distinguish migrated-empty overlay selection from an older settings file."""

        if not self.path.exists():
            return False
        with self.path.open("rb") as handle:
            document = tomllib.load(handle)
        overlay = document.get("xray_overlay")
        return isinstance(overlay, Mapping) and "selected_group_ids" in overlay

    def save(self, settings: HeatmapSettings) -> None:
        """Atomically replace the persisted snapshot only after full validation."""

        settings.validate()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self.path.stem}.",
            suffix=".tmp",
            dir=self.path.parent,
            text=True,
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(_settings_to_toml(settings))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, self.path)
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise


def _settings_from_document(document: Mapping[str, object]) -> HeatmapSettings:
    isolation = _mapping(document.get("isolation"))
    xray_overlay = _mapping(document.get("xray_overlay"))
    color_scale = _mapping(document.get("color_scale"))
    stop_documents = color_scale.get("stops", ())
    if not isinstance(stop_documents, list):
        raise ValueError("Heatmap colour stops must be a TOML array.")
    stops = tuple(_stop_from_document(_mapping(stop)) for stop in stop_documents)
    calibration_document = _mapping(document.get("calibration"))
    calibration = {
        str(identifier): _calibration_from_document(_mapping(value))
        for identifier, value in calibration_document.items()
    }
    selectors = isolation.get("selectors", ())
    if not isinstance(selectors, list) or not all(
        isinstance(selector, str) for selector in selectors
    ):
        raise ValueError("Heatmap Isolation selectors must be a TOML string array.")
    group_ids = xray_overlay.get("selected_group_ids", [])
    if not isinstance(group_ids, list) or not all(
        isinstance(group_id, str) for group_id in group_ids
    ):
        raise ValueError(
            "Heatmap X-Ray Overlay selected_group_ids must be a TOML string array."
        )
    return HeatmapSettings(
        isolation_selectors=tuple(selectors),
        xray_overlay_group_ids=tuple(group_ids),
        calibration=calibration,
        color_scale=ColorScaleSettings(
            minimum_clamp_percent=float(color_scale.get("minimum_clamp_percent", 0.0)),
            maximum_clamp_percent=float(
                color_scale.get("maximum_clamp_percent", 100.0)
            ),
            stops=stops or DEFAULT_COLOR_STOPS,
        ),
    )


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        return {}
    return value


def _stop_from_document(document: Mapping[str, object]) -> ColorStopSettings:
    color = document.get("color")
    if not isinstance(color, list) or len(color) != 3:
        raise ValueError("Heatmap colour stop must contain three RGB values.")
    return ColorStopSettings(
        stop_id=str(document.get("id", "")),
        enabled=bool(document.get("enabled", False)),
        position_percent=float(document.get("position_percent", 0.0)),
        color=tuple(float(channel) for channel in color),
    )


def _calibration_from_document(document: Mapping[str, object]) -> CalibrationSettings:
    return CalibrationSettings(
        delta_celsius=float(document.get("delta_celsius", 10.0)),
        temperature_offset_celsius=float(
            document.get("temperature_offset_celsius", 0.0)
        ),
    )


def _append_calibration_changes(
    changes: list[tuple[str, str]],
    previous: Mapping[str, CalibrationSettings],
    candidate: Mapping[str, CalibrationSettings],
) -> None:
    for identifier in sorted(set(previous) | set(candidate)):
        before = previous.get(identifier)
        after = candidate.get(identifier)
        prefix = f"calibration.{identifier}"
        if after is None:
            changes.append((prefix, "removed"))
            continue
        if before is None or before.delta_celsius != after.delta_celsius:
            changes.append((f"{prefix}.delta_celsius", f"{after.delta_celsius:g}"))
        if (
            before is None
            or before.temperature_offset_celsius != after.temperature_offset_celsius
        ):
            changes.append(
                (
                    f"{prefix}.temperature_offset_celsius",
                    f"{after.temperature_offset_celsius:g}",
                )
            )


def _append_color_scale_changes(
    changes: list[tuple[str, str]],
    previous: ColorScaleSettings,
    candidate: ColorScaleSettings,
) -> None:
    for field_name in ("minimum_clamp_percent", "maximum_clamp_percent"):
        if getattr(previous, field_name) != getattr(candidate, field_name):
            changes.append(
                (
                    f"color_scale.{field_name}",
                    f"{getattr(candidate, field_name):g}",
                )
            )
    before_stops = {stop.stop_id: stop for stop in previous.stops}
    candidate_stops = {stop.stop_id: stop for stop in candidate.stops}
    for stop_id in sorted(set(before_stops) | set(candidate_stops)):
        before = before_stops.get(stop_id)
        after = candidate_stops.get(stop_id)
        prefix = f"color_scale.stops.{stop_id}"
        if after is None:
            changes.append((prefix, "removed"))
            continue
        if before is None or before.enabled != after.enabled:
            changes.append((f"{prefix}.enabled", str(after.enabled).lower()))
        if before is None or before.position_percent != after.position_percent:
            changes.append(
                (f"{prefix}.position_percent", f"{after.position_percent:g}")
            )
        if before is None or before.color != after.color:
            changes.append((f"{prefix}.color", _format_color(after.color)))


def _format_sequence(values: tuple[str, ...]) -> str:
    return "[" + ", ".join(values) + "]"


def _format_color(color: tuple[float, float, float]) -> str:
    return "[" + ", ".join(f"{channel:g}" for channel in color) + "]"


def _settings_to_toml(settings: HeatmapSettings) -> str:
    lines = ["version = 1", "", "[isolation]"]
    selectors = ", ".join(_toml_string(item) for item in settings.isolation_selectors)
    group_ids = ", ".join(
        _toml_string(item) for item in settings.xray_overlay_group_ids
    )
    lines.extend(
        (
            f"selectors = [{selectors}]",
            "",
            "[xray_overlay]",
            f"selected_group_ids = [{group_ids}]",
            "",
            "[color_scale]",
        )
    )
    lines.append(
        f"minimum_clamp_percent = {settings.color_scale.minimum_clamp_percent:g}"
    )
    lines.append(
        f"maximum_clamp_percent = {settings.color_scale.maximum_clamp_percent:g}"
    )
    for stop in settings.color_scale.stops:
        colour = ", ".join(f"{channel:g}" for channel in stop.color)
        lines.extend(
            (
                "",
                "[[color_scale.stops]]",
                f"id = {_toml_string(stop.stop_id)}",
                f"enabled = {'true' if stop.enabled else 'false'}",
                f"position_percent = {stop.position_percent:g}",
                f"color = [{colour}]",
            )
        )
    for identifier, rule in sorted(settings.calibration.items()):
        lines.extend(
            (
                "",
                f"[calibration.{_toml_string(identifier)}]",
                f"delta_celsius = {rule.delta_celsius:g}",
                "temperature_offset_celsius = " f"{rule.temperature_offset_celsius:g}",
            )
        )
    return "\n".join(lines) + "\n"


def _toml_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
