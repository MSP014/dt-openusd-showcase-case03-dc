# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""Pure production Heatmap/X-Ray composition contracts."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from digital_twin_runtime_suite.app.heatmaps.composition import (
    build_heatmap_composition_plan,
)
from digital_twin_runtime_suite.app.heatmaps.settings import HeatmapSettings


class _Catalog:
    def __init__(self, targets) -> None:
        self._targets = tuple(targets)

    @staticmethod
    def validate_selection(_selectors) -> None:
        return None

    def selected_targets(self, selectors):
        selected = frozenset(selectors)
        return tuple(
            target
            for target in self._targets
            if selected.intersection(target.selector_ids)
        )


def _target(path: str, selector_id: str):
    return SimpleNamespace(prim_path=path, selector_ids=(selector_id,))


def _group(group_id: str, *paths: str):
    return SimpleNamespace(group_id=group_id, paths=paths)


def test_gpu_housing_precedence_is_resolved_per_gpu_path() -> None:
    gpu_root = "/blackwell_rig/compute"
    catalog = _Catalog(
        (
            _target(f"{gpu_root}/gpu_01/shroud/thermal_mesh", "gpu_01_housing"),
            _target(f"{gpu_root}/gpu_02/shroud/thermal_mesh", "gpu_02_housing"),
            _target(f"{gpu_root}/gpu_03/shroud/thermal_mesh", "gpu_03_housing"),
        )
    )
    groups = (
        _group(
            "gpu_shrouds",
            f"{gpu_root}/gpu_01/shroud",
            f"{gpu_root}/gpu_02/shroud",
            f"{gpu_root}/gpu_03/shroud",
        ),
        _group("chassis", "/blackwell_rig/chassis"),
    )
    settings = HeatmapSettings(
        isolation_selectors=("gpu_01_housing", "gpu_03_housing"),
        xray_overlay_group_ids=("gpu_shrouds", "chassis"),
    )

    plan = build_heatmap_composition_plan(settings, catalog, groups)

    assert plan.xray_excluded_paths == (
        f"{gpu_root}/gpu_01/shroud",
        f"{gpu_root}/gpu_03/shroud",
    )
    assert f"{gpu_root}/gpu_02/shroud" not in plan.xray_excluded_paths
    assert "/blackwell_rig/chassis" in plan.visibility_target_paths


def test_gpu_housing_off_leaves_its_xray_group_path_available() -> None:
    catalog = _Catalog(
        (_target("/blackwell_rig/compute/gpu_01/pcb/mesh", "gpu_01_internals"),)
    )
    groups = (_group("gpu_shrouds", "/blackwell_rig/compute/gpu_01/shroud"),)
    settings = HeatmapSettings(
        isolation_selectors=("gpu_01_internals",),
        xray_overlay_group_ids=("gpu_shrouds",),
    )

    plan = build_heatmap_composition_plan(settings, catalog, groups)

    assert plan.xray_excluded_paths == ()
    assert plan.xray_selected_group_ids == ("gpu_shrouds",)


def test_gpu_housing_exclusion_keeps_power_and_io_xray_paths_available() -> None:
    gpu_root = "/blackwell_rig/compute/gpu_01/geo/render/RTX4500"
    catalog = _Catalog(
        (
            _target(f"{gpu_root}/shroud/thermal_mesh", "gpu_01_housing"),
            _target(f"{gpu_root}/blower/thermal_mesh", "gpu_01_housing"),
            _target(f"{gpu_root}/power/thermal_mesh", "gpu_01_housing"),
            _target(f"{gpu_root}/io/ports/thermal_mesh", "gpu_01_housing"),
        )
    )
    groups = (
        _group(
            "gpu_shrouds",
            f"{gpu_root}/shroud",
            f"{gpu_root}/blower",
            f"{gpu_root}/power",
            f"{gpu_root}/io/ports",
            "/blackwell_rig/power/cables/geo/render/cables/cables_gpu_1",
        ),
    )
    settings = HeatmapSettings(
        isolation_selectors=("gpu_01_housing",),
        xray_overlay_group_ids=("gpu_shrouds",),
    )

    plan = build_heatmap_composition_plan(settings, catalog, groups)

    assert plan.xray_excluded_paths == (
        f"{gpu_root}/blower",
        f"{gpu_root}/shroud",
    )


@pytest.mark.parametrize(
    ("selectors", "excluded_gpu_ids"),
    (
        (("gpu_01_housing",), ("01",)),
        (("gpu_02_housing",), ("02",)),
        (("gpu_03_housing",), ("03",)),
        (
            ("gpu_01_housing", "gpu_02_housing", "gpu_03_housing"),
            ("01", "02", "03"),
        ),
    ),
)
def test_each_gpu_housing_is_excluded_without_affecting_other_groups(
    selectors,
    excluded_gpu_ids,
) -> None:
    gpu_root = "/blackwell_rig/compute"
    catalog = _Catalog(
        tuple(
            _target(
                f"{gpu_root}/gpu_{gpu_id}/shroud/thermal_mesh",
                f"gpu_{gpu_id}_housing",
            )
            for gpu_id in ("01", "02", "03")
        )
    )
    groups = (
        _group(
            "gpu_shrouds",
            *(f"{gpu_root}/gpu_{gpu_id}/shroud" for gpu_id in ("01", "02", "03")),
        ),
        _group("cables", "/blackwell_rig/cables"),
    )
    settings = HeatmapSettings(
        isolation_selectors=selectors,
        xray_overlay_group_ids=("gpu_shrouds", "cables"),
    )

    plan = build_heatmap_composition_plan(settings, catalog, groups)

    assert plan.xray_excluded_paths == tuple(
        f"{gpu_root}/gpu_{gpu_id}/shroud" for gpu_id in excluded_gpu_ids
    )
    assert "/blackwell_rig/cables" in plan.visibility_target_paths
