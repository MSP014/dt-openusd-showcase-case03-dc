# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""Discover immutable thermal metadata from authored USD geometry."""

from __future__ import annotations

from dataclasses import dataclass

PROPERTY_ABSENT = "ABSENT"
PROPERTY_DECLARED_NO_VALUE = "DECLARED_NO_VALUE"
PROPERTY_EMPTY = "EMPTY"
PROPERTY_VALUE = "VALUE"


@dataclass(frozen=True)
class ThermalPrimMetadata:
    """Heatmap metadata observed on one geometry prim."""

    prim_path: str
    thermal_zone: str | None
    thermal_component: str | None
    thermal_weight: tuple[object, ...] | None
    thermal_weight_interpolation: str | None
    temperature_preview: tuple[object, ...] | None
    temperature_preview_interpolation: str | None
    thermal_zone_state: str
    thermal_component_state: str
    thermal_weight_state: str


def discover_thermal_geometry(stage, root_path: str) -> tuple[ThermalPrimMetadata, ...]:
    """Return immutable Gprim metadata beneath ``root_path`` without USD edits."""

    from pxr import Usd, UsdGeom

    root = stage.GetPrimAtPath(root_path)
    if not root or not root.IsValid():
        return ()

    discovered = []
    for prim in Usd.PrimRange(root):
        if not prim.IsA(UsdGeom.Gprim) or _is_proxy_geometry(prim):
            continue
        zone = prim.GetAttribute("thermal_zone")
        component = prim.GetAttribute("thermal_component")
        weight = prim.GetAttribute("primvars:thermal_weight")
        preview = prim.GetAttribute("primvars:temperature_preview")
        if _is_explicitly_excluded(zone, component):
            continue
        discovered.append(
            ThermalPrimMetadata(
                prim_path=str(prim.GetPath()),
                thermal_zone=_optional_text(zone),
                thermal_component=_optional_text(component),
                thermal_weight=_optional_values(weight),
                thermal_weight_interpolation=_optional_interpolation(weight),
                temperature_preview=_optional_values(preview),
                temperature_preview_interpolation=_optional_interpolation(preview),
                thermal_zone_state=_property_state(zone),
                thermal_component_state=_property_state(component),
                thermal_weight_state=_property_state(weight),
            )
        )
    return tuple(sorted(discovered, key=lambda target: target.prim_path))


def _optional_text(attribute) -> str | None:
    if not attribute.IsValid() or not attribute.HasAuthoredValueOpinion():
        return None
    return attribute.Get()


def _optional_values(attribute) -> tuple[object, ...] | None:
    if not attribute.IsValid() or not attribute.HasAuthoredValueOpinion():
        return None
    value = attribute.Get()
    if value is None:
        return None
    if isinstance(value, (str, bytes)):
        return (value,)
    try:
        return tuple(value)
    except TypeError:
        return (value,)


def _optional_interpolation(attribute) -> str | None:
    if not attribute.IsValid():
        return None
    value = attribute.GetMetadata("interpolation")
    text = str(value or "").strip()
    return text or None


def _property_state(attribute) -> str:
    """Classify USD property presence before reading its resolved value."""

    if not attribute.IsValid():
        return PROPERTY_ABSENT
    if not attribute.HasAuthoredValueOpinion():
        return PROPERTY_DECLARED_NO_VALUE
    value = attribute.Get()
    if value == "":
        return PROPERTY_EMPTY
    if hasattr(value, "__len__") and not isinstance(value, str) and not len(value):
        return PROPERTY_EMPTY
    return PROPERTY_VALUE


def _is_proxy_geometry(prim) -> bool:
    """Exclude Houdini proxy subtrees from the production Heatmap contract."""

    return "/geo/proxy/" in f"{prim.GetPath()}/"


def _is_explicitly_excluded(zone, component) -> bool:
    """Keep paired Houdini Heatmap opt-outs outside semantic discovery."""

    return _optional_text(zone) == "ignore" and _optional_text(component) == "ignore"
