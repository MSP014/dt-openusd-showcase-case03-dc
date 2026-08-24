# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""Validate the authored full-server Heatmap metadata contract."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .discovery import (
    PROPERTY_ABSENT,
    PROPERTY_DECLARED_NO_VALUE,
    PROPERTY_EMPTY,
    ThermalPrimMetadata,
    discover_thermal_geometry,
)

HEATMAP_SERVER_ROOT_PATH = "/blackwell_rig"
USABLE_WEIGHT_INTERPOLATIONS = frozenset(
    {"constant", "uniform", "vertex", "varying", "faceVarying"}
)
CORE_HEATMAP_ATTRIBUTES = (
    "thermal_zone",
    "thermal_component",
    "primvars:thermal_weight",
)


@dataclass(frozen=True)
class HeatmapPreflightDiagnostic:
    """One definite Heatmap-contract failure for a geometry prim."""

    prim_path: str
    reason: str
    core_attributes_present: tuple[str, ...] = ()
    core_attributes_missing: tuple[str, ...] = ()


@dataclass(frozen=True)
class HeatmapAssetPreflightResult:
    """Immutable full-server Heatmap asset-contract evidence."""

    success: bool
    root_path: str
    thermal_target_count: int
    valid_target_count: int
    malformed_target_count: int
    review_target_count: int
    observed_weight_min: float | None
    observed_weight_max: float | None
    xray_overlap_targets: tuple[str, ...]
    diagnostics: tuple[HeatmapPreflightDiagnostic, ...]
    review_targets: tuple[str, ...]
    valid_targets: tuple[ThermalPrimMetadata, ...] = ()

    @property
    def status(self) -> str:
        """Return the compact PASS/FAIL status used by DTRS evidence."""

        return "PASS" if self.success else "FAIL"


def run_heatmap_asset_preflight(
    stage,
    *,
    root_path: str = HEATMAP_SERVER_ROOT_PATH,
    xray_target_paths: tuple[str, ...] = (),
) -> HeatmapAssetPreflightResult:
    """Validate thermal geometry beneath the complete production server root."""

    root = stage.GetPrimAtPath(root_path)
    if not root or not root.IsValid():
        diagnostic = HeatmapPreflightDiagnostic(root_path, "missing server root")
        return HeatmapAssetPreflightResult(
            success=False,
            root_path=root_path,
            thermal_target_count=0,
            valid_target_count=0,
            malformed_target_count=1,
            review_target_count=0,
            observed_weight_min=None,
            observed_weight_max=None,
            xray_overlap_targets=(),
            diagnostics=(diagnostic,),
            review_targets=(),
        )

    geometry = discover_thermal_geometry(stage, root_path)
    diagnostics: list[HeatmapPreflightDiagnostic] = []
    observed_weights: list[float] = []
    valid_targets: list[ThermalPrimMetadata] = []
    review_targets: list[str] = []
    thermal_target_count = 0
    valid_target_count = 0
    for asset_geometry in _group_by_asset(geometry).values():
        unannotated_paths: list[str] = []
        valid_in_asset = False
        for target in asset_geometry:
            if _is_explicitly_excluded(target):
                continue

            present, missing = _core_attribute_presence(target)
            if not present:
                unannotated_paths.append(target.prim_path)
                continue

            thermal_target_count += 1
            reasons, weights = _validate_thermal_target(target, missing)
            observed_weights.extend(weights)
            if reasons:
                diagnostics.append(
                    HeatmapPreflightDiagnostic(
                        target.prim_path,
                        "; ".join(reasons),
                        present,
                        missing,
                    )
                )
                continue
            valid_target_count += 1
            valid_in_asset = True
            valid_targets.append(target)

        if valid_in_asset:
            review_targets.extend(unannotated_paths)

    diagnostics.sort(key=lambda diagnostic: diagnostic.prim_path)
    review_targets.sort()
    valid_targets.sort(key=lambda target: target.prim_path)

    return HeatmapAssetPreflightResult(
        success=not diagnostics,
        root_path=root_path,
        thermal_target_count=thermal_target_count,
        valid_target_count=valid_target_count,
        malformed_target_count=len(diagnostics),
        review_target_count=len(review_targets),
        observed_weight_min=min(observed_weights) if observed_weights else None,
        observed_weight_max=max(observed_weights) if observed_weights else None,
        xray_overlap_targets=_xray_overlap_targets(valid_targets, xray_target_paths),
        diagnostics=tuple(diagnostics),
        review_targets=tuple(review_targets),
        valid_targets=tuple(valid_targets),
    )


def _validate_thermal_target(
    target: ThermalPrimMetadata,
    missing_attributes: tuple[str, ...],
) -> tuple[list[str], list[float]]:
    ignore_pair_error = _ignore_pair_error(target)
    if missing_attributes:
        reasons = [f"missing {attribute}" for attribute in missing_attributes]
        return ([*ignore_pair_error, *reasons], [])

    reasons = list(ignore_pair_error)
    if target.thermal_zone_state == PROPERTY_DECLARED_NO_VALUE:
        reasons.append("thermal_zone declared with no value")
    elif target.thermal_zone_state == PROPERTY_EMPTY or not _usable_text(
        target.thermal_zone
    ):
        reasons.append("empty thermal_zone")
    if target.thermal_component_state == PROPERTY_DECLARED_NO_VALUE:
        reasons.append("thermal_component declared with no value")
    elif target.thermal_component_state == PROPERTY_EMPTY or not _usable_text(
        target.thermal_component
    ):
        reasons.append("empty thermal_component")
    if target.thermal_weight_state == PROPERTY_DECLARED_NO_VALUE:
        reasons.append("primvars:thermal_weight declared with no value")
        return reasons, []
    if target.thermal_weight_state == PROPERTY_EMPTY:
        reasons.append("empty primvars:thermal_weight")
        return reasons, []
    if target.thermal_weight is None:
        reasons.append("unusable primvars:thermal_weight value")
        return reasons, []
    if not target.thermal_weight:
        reasons.append("empty primvars:thermal_weight")
    if target.thermal_weight_interpolation not in USABLE_WEIGHT_INTERPOLATIONS:
        reasons.append(
            "unsupported thermal_weight interpolation "
            f"{target.thermal_weight_interpolation or '<missing>'}"
        )

    weights = []
    invalid_weight = False
    for value in target.thermal_weight:
        try:
            weight = float(value)
        except (TypeError, ValueError):
            invalid_weight = True
            continue
        if not math.isfinite(weight):
            invalid_weight = True
            continue
        weights.append(weight)
        if not 0.0 <= weight <= 1.0:
            invalid_weight = True
    if invalid_weight:
        reasons.append("thermal_weight must be finite and within [0, 1]")
    return reasons, weights


def _is_explicitly_excluded(target: ThermalPrimMetadata) -> bool:
    """Recognise Houdini's paired opt-out before core-contract validation."""

    return target.thermal_zone == "ignore" and target.thermal_component == "ignore"


def _ignore_pair_error(target: ThermalPrimMetadata) -> tuple[str, ...]:
    """Require the opt-out sentinel to be authored as one exact pair."""

    zone_is_ignore = target.thermal_zone == "ignore"
    component_is_ignore = target.thermal_component == "ignore"
    if zone_is_ignore == component_is_ignore:
        return ()
    return ("thermal_zone and thermal_component must both be 'ignore'",)


def _usable_text(value: str | None) -> bool:
    """Treat authored whitespace as unusable without changing USD property state."""

    return bool(value and value.strip())


def _core_attribute_presence(
    target: ThermalPrimMetadata,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    authored = (
        target.thermal_zone_state != PROPERTY_ABSENT,
        target.thermal_component_state != PROPERTY_ABSENT,
        target.thermal_weight_state != PROPERTY_ABSENT,
    )
    present = tuple(
        attribute
        for attribute, is_present in zip(CORE_HEATMAP_ATTRIBUTES, authored)
        if is_present
    )
    missing = tuple(
        attribute
        for attribute, is_present in zip(CORE_HEATMAP_ATTRIBUTES, authored)
        if not is_present
    )
    return present, missing


def _group_by_asset(
    geometry: tuple[ThermalPrimMetadata, ...],
) -> dict[str, list[ThermalPrimMetadata]]:
    groups: dict[str, list[ThermalPrimMetadata]] = {}
    for target in geometry:
        groups.setdefault(_asset_path(target.prim_path), []).append(target)
    return groups


def _asset_path(prim_path: str) -> str:
    """Keep GPU and power subassemblies distinct for Heatmap-intent review."""

    parts = prim_path.removeprefix(f"{HEATMAP_SERVER_ROOT_PATH}/").split("/")
    return "/".join(parts[:2] if parts[0] in {"compute", "power"} else parts[:1])


def _xray_overlap_targets(
    targets: tuple[ThermalPrimMetadata, ...],
    xray_target_paths: tuple[str, ...],
) -> tuple[str, ...]:
    overlaps = []
    for target in targets:
        if any(
            target.prim_path == path or target.prim_path.startswith(f"{path}/")
            for path in xray_target_paths
        ):
            overlaps.append(target.prim_path)
    return tuple(overlaps)
