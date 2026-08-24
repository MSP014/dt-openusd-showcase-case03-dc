# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""Pure Heatmap and X-Ray target precedence planning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .catalog import HeatmapCatalog
from .settings import HeatmapSettings


@dataclass(frozen=True)
class HeatmapCompositionPlan:
    """Immutable production composition without Kit or USD mutation ownership."""

    heatmap_target_paths: tuple[str, ...]
    xray_selected_group_ids: tuple[str, ...]
    xray_excluded_paths: tuple[str, ...]
    visibility_target_paths: tuple[str, ...]


def build_heatmap_composition_plan(
    settings: HeatmapSettings,
    catalog: HeatmapCatalog,
    configured_xray_groups: Iterable[object],
) -> HeatmapCompositionPlan:
    """Resolve Heatmap ownership before X-Ray material reconciliation begins."""

    settings.validate()
    catalog.validate_selection(settings.isolation_selectors)
    groups = tuple(configured_xray_groups)
    groups_by_id = {group.group_id: group for group in groups}
    unknown_group_ids = tuple(
        sorted(set(settings.xray_overlay_group_ids) - set(groups_by_id))
    )
    if unknown_group_ids:
        raise ValueError(
            "Unknown Heatmap X-Ray Overlay groups: " + ", ".join(unknown_group_ids)
        )
    heatmap_targets = catalog.selected_targets(settings.isolation_selectors)
    heatmap_paths = tuple(target.prim_path for target in heatmap_targets)
    selected_group_ids = tuple(settings.xray_overlay_group_ids)
    selected_groups = tuple(groups_by_id[group_id] for group_id in selected_group_ids)
    excluded_paths = _housing_xray_excluded_paths(heatmap_targets, selected_groups)
    visibility_paths = tuple(
        sorted(
            set(heatmap_paths).union(
                path for group in selected_groups for path in group.paths
            )
        )
    )
    return HeatmapCompositionPlan(
        heatmap_target_paths=heatmap_paths,
        xray_selected_group_ids=selected_group_ids,
        xray_excluded_paths=excluded_paths,
        visibility_target_paths=visibility_paths,
    )


def _housing_xray_excluded_paths(
    heatmap_targets,
    selected_xray_groups: tuple[object, ...],
) -> tuple[str, ...]:
    """Exclude only selected GPU housing roots that contain Heatmap targets."""

    candidates = tuple(path for group in selected_xray_groups for path in group.paths)
    excluded: set[str] = set()
    for target in heatmap_targets:
        if not any(
            selector_id.endswith("_housing") for selector_id in target.selector_ids
        ):
            continue
        for path in candidates:
            if _is_gpu_housing_xray_root(path) and _is_ancestor_or_same(
                path,
                target.prim_path,
            ):
                excluded.add(path)
    return tuple(sorted(excluded))


def _is_ancestor_or_same(ancestor_path: str, path: str) -> bool:
    """Match a USD prim root and every descendant without string-prefix ambiguity."""

    return path == ancestor_path or path.startswith(f"{ancestor_path}/")


def _is_gpu_housing_xray_root(path: str) -> bool:
    """Retain non-housing GPU X-Ray roots when a housing selector is active."""

    return path.endswith(("/shroud", "/blower"))
