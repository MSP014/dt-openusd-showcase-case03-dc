# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""Build stage-driven Heatmap selectors and calibration descriptors."""

from __future__ import annotations

from dataclasses import dataclass

from .bindings import (
    HeatmapSemanticRegistry,
    HeatmapTargetBinding,
    build_heatmap_semantic_registry,
)
from .preflight import (
    HEATMAP_SERVER_ROOT_PATH,
    HeatmapAssetPreflightResult,
    run_heatmap_asset_preflight,
)


@dataclass(frozen=True)
class IsolationSelector:
    """One UI-visible set member in the arbitrary Heatmap isolation union."""

    selector_id: str
    label: str
    parent_id: str | None = None
    parent_label: str | None = None


@dataclass(frozen=True)
class HeatmapCatalogTarget:
    """One preflight-valid prim with its UI, isolation, and calibration identity."""

    binding: HeatmapTargetBinding
    asset_id: str
    asset_label: str
    calibration_id: str
    selector_ids: tuple[str, ...]

    @property
    def prim_path(self) -> str:
        """Return the stable production target path without duplicating binding data."""

        return self.binding.prim_path


@dataclass(frozen=True)
class CalibrationDescriptor:
    """One dynamic Asset/zone/component calibration row."""

    calibration_id: str
    asset_id: str
    asset_label: str
    thermal_zone: str
    thermal_component: str
    display_zone: str
    display_component: str


@dataclass(frozen=True)
class HeatmapCatalog:
    """Immutable bridge from production USD metadata to generic Heatmap controls."""

    preflight: HeatmapAssetPreflightResult
    registry: HeatmapSemanticRegistry
    selectors: tuple[IsolationSelector, ...]
    targets: tuple[HeatmapCatalogTarget, ...]
    calibration: tuple[CalibrationDescriptor, ...]

    @property
    def ready(self) -> bool:
        """Require deterministic discovery and semantic identity before presentation."""

        return self.preflight.success and self.registry.success

    @property
    def selector_ids(self) -> tuple[str, ...]:
        """Expose the canonical persisted selector vocabulary."""

        return tuple(selector.selector_id for selector in self.selectors)

    @property
    def calibration_ids(self) -> tuple[str, ...]:
        """Expose all stage-driven settings rows in deterministic UI order."""

        return tuple(item.calibration_id for item in self.calibration)

    def validate_selection(self, selectors: tuple[str, ...]) -> None:
        """Reject stale or unknown persisted selector ids before USD mutation."""

        unknown = tuple(sorted(set(selectors) - set(self.selector_ids)))
        if unknown:
            raise ValueError(
                "Unknown Heatmap Isolation selectors: " + ", ".join(unknown)
            )

    def selected_targets(
        self,
        selectors: tuple[str, ...],
    ) -> tuple[HeatmapCatalogTarget, ...]:
        """Resolve an arbitrary selector union without special-purpose scopes."""

        self.validate_selection(selectors)
        selected = frozenset(selectors)
        return tuple(
            target
            for target in self.targets
            if selected.intersection(target.selector_ids)
        )


def build_heatmap_catalog(
    stage,
    *,
    root_path: str = HEATMAP_SERVER_ROOT_PATH,
) -> HeatmapCatalog:
    """Discover the ready production stage through preflight and semantic binding."""

    preflight = run_heatmap_asset_preflight(stage, root_path=root_path)
    return build_heatmap_catalog_from_preflight(preflight)


def build_heatmap_catalog_from_preflight(
    preflight: HeatmapAssetPreflightResult,
) -> HeatmapCatalog:
    """Create deterministic UI descriptors from already observed preflight evidence."""

    registry = build_heatmap_semantic_registry(preflight.valid_targets)
    targets = tuple(_catalog_target(binding) for binding in registry.targets)
    return HeatmapCatalog(
        preflight=preflight,
        registry=registry,
        selectors=_selectors(),
        targets=targets,
        calibration=_calibration_descriptors(targets),
    )


def _selectors() -> tuple[IsolationSelector, ...]:
    return (
        IsolationSelector("motherboard", "Motherboard"),
        IsolationSelector("connectx_7", "ConnectX-7"),
        IsolationSelector(
            "gpu_01_internals",
            "Internals",
            parent_id="gpu_01",
            parent_label="GPU 01",
        ),
        IsolationSelector(
            "gpu_01_housing",
            "Housing",
            parent_id="gpu_01",
            parent_label="GPU 01",
        ),
        IsolationSelector(
            "gpu_02_internals",
            "Internals",
            parent_id="gpu_02",
            parent_label="GPU 02",
        ),
        IsolationSelector(
            "gpu_02_housing",
            "Housing",
            parent_id="gpu_02",
            parent_label="GPU 02",
        ),
        IsolationSelector(
            "gpu_03_internals",
            "Internals",
            parent_id="gpu_03",
            parent_label="GPU 03",
        ),
        IsolationSelector(
            "gpu_03_housing",
            "Housing",
            parent_id="gpu_03",
            parent_label="GPU 03",
        ),
        IsolationSelector("cpu_cooler", "CPU Cooler"),
        IsolationSelector("ram", "RAM"),
        IsolationSelector("psu", "PSU"),
    )


def _catalog_target(binding: HeatmapTargetBinding) -> HeatmapCatalogTarget:
    asset_id, asset_label, calibration_id = _asset_identity(binding)
    return HeatmapCatalogTarget(
        binding=binding,
        asset_id=asset_id,
        asset_label=asset_label,
        calibration_id=calibration_id,
        selector_ids=_selector_ids(binding),
    )


def _asset_identity(binding: HeatmapTargetBinding) -> tuple[str, str, str]:
    key = binding.semantic_key
    hardware = key.hardware
    zone = key.thermal_zone
    component = key.thermal_component
    if _is_motherboard_dimm(binding):
        instance = _dimm_instance(binding.prim_path)
        asset_id = "motherboard"
        return (
            asset_id,
            "Motherboard",
            f"{asset_id}/dimm_{instance:02d}/{zone}/{component}",
        )
    if hardware.family == "gpu" and isinstance(hardware.instance, int):
        asset_id = f"gpu_{hardware.instance:02d}"
        return (
            asset_id,
            f"GPU {hardware.instance:02d}",
            f"{asset_id}/{zone}/{component}",
        )
    if hardware.family == "ram":
        return "ram", "RAM", f"ram/{zone}/{component}"
    labels = {
        "motherboard": "Motherboard",
        "cpu": "CPU Cooler",
        "nic": "ConnectX-7",
        "psu": "PSU",
    }
    asset_id = hardware.family
    return (
        asset_id,
        labels.get(asset_id, asset_id.replace("_", " ").title()),
        (f"{asset_id}/{zone}/{component}"),
    )


def _selector_ids(binding: HeatmapTargetBinding) -> tuple[str, ...]:
    hardware = binding.semantic_key.hardware
    if hardware.family == "gpu" and isinstance(hardware.instance, int):
        gpu_id = f"gpu_{hardware.instance:02d}"
        if _is_gpu_housing(binding):
            return (f"{gpu_id}_housing",)
        return (f"{gpu_id}_internals",)
    if _is_motherboard_dimm(binding) or hardware.family == "motherboard":
        return ("motherboard",)
    return {
        "cpu": ("cpu_cooler",),
        "nic": ("connectx_7",),
        "psu": ("psu",),
        "ram": ("ram",),
    }.get(hardware.family, ())


def _is_gpu_housing(binding: HeatmapTargetBinding) -> bool:
    return (
        binding.semantic_key.thermal_zone,
        binding.semantic_key.thermal_component,
    ) in {("gpu_body", "shroud"), ("gpu_cooling", "blower")}


def _is_motherboard_dimm(binding: HeatmapTargetBinding) -> bool:
    return "/motherboard/" in binding.prim_path and "/ram_slots/" in binding.prim_path


def _dimm_instance(path: str) -> int:
    for part in path.split("/"):
        if part.startswith("dimm_") and part[5:].isdigit():
            value = int(part[5:])
            if 1 <= value <= 8:
                return value
    raise ValueError(f"Motherboard DIMM target has no DIMM identity: {path}")


def _calibration_descriptors(
    targets: tuple[HeatmapCatalogTarget, ...],
) -> tuple[CalibrationDescriptor, ...]:
    descriptors = {
        target.calibration_id: CalibrationDescriptor(
            calibration_id=target.calibration_id,
            asset_id=target.asset_id,
            asset_label=target.asset_label,
            thermal_zone=target.binding.semantic_key.thermal_zone,
            thermal_component=target.binding.semantic_key.thermal_component,
            display_zone=_calibration_display_zone(target),
            display_component=_calibration_display_component(target),
        )
        for target in targets
    }
    return tuple(
        descriptors[identifier]
        for identifier in sorted(
            descriptors,
            key=lambda item: (
                descriptors[item].asset_label,
                descriptors[item].thermal_zone,
                descriptors[item].thermal_component,
                item,
            ),
        )
    )


def _calibration_display_zone(target: HeatmapCatalogTarget) -> str:
    if target.calibration_id.startswith("motherboard/dimm_"):
        return "DIMM " + target.calibration_id.split("/")[1].removeprefix("dimm_")
    return target.binding.semantic_key.thermal_zone


def _calibration_display_component(target: HeatmapCatalogTarget) -> str:
    if target.calibration_id.startswith("motherboard/dimm_"):
        return "/".join(
            (
                target.binding.semantic_key.thermal_zone,
                target.binding.semantic_key.thermal_component,
            )
        )
    return target.binding.semantic_key.thermal_component
