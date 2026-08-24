# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""Resolve authored Heatmap semantics to stable hardware and telemetry identity."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Mapping

from digital_twin_runtime_suite.app.telemetry.model import TelemetrySnapshot

from .diagnostics import (
    HeatmapBindingDiagnostic,
    ambiguous_hardware_identity,
    unavailable_telemetry_binding,
)
from .discovery import ThermalPrimMetadata


@dataclass(frozen=True)
class HardwareIdentity:
    """Stable hardware identity derived independently from Heatmap semantics."""

    family: str
    instance: int | str | None = None

    @property
    def label(self) -> str:
        """Return the deterministic compact identity used in semantic keys."""

        return (
            self.family if self.instance is None else f"{self.family}_{self.instance}"
        )


@dataclass(frozen=True)
class SemanticKey:
    """One reusable hardware-plus-authored-thermal semantic identity."""

    hardware: HardwareIdentity
    thermal_zone: str
    thermal_component: str

    @property
    def label(self) -> str:
        """Return a concise deterministic human-readable key."""

        return "/".join(
            (self.hardware.label, self.thermal_zone, self.thermal_component)
        )


@dataclass(frozen=True)
class TelemetryBinding:
    """Static source-controlled semantic-target-to-metric contract."""

    metric_id: str | None
    unavailable_reason: str | None = None

    @property
    def available(self) -> bool:
        """Return whether a documented truthful metric was resolved."""

        return self.metric_id is not None

    @property
    def status(self) -> str:
        """Return the explicit static binding state used by later presentation."""

        return "AVAILABLE" if self.available else "UNAVAILABLE"


@dataclass(frozen=True)
class HeatmapTargetBinding:
    """One valid prim's semantic identity and telemetry metric resolution."""

    prim_path: str
    semantic_key: SemanticKey
    telemetry_binding: TelemetryBinding


@dataclass(frozen=True)
class ResolvedTelemetryValue:
    """Current value state, deliberately separate from its static binding."""

    metric_id: str | None
    available: bool
    value: float | bool | str | None
    unit: str | None
    quality: str
    reason: str | None = None


@dataclass(frozen=True)
class HeatmapTelemetrySnapshot:
    """Immutable current values resolved through an unchanged semantic registry."""

    timestamp: datetime | None
    values_by_prim_path: Mapping[str, ResolvedTelemetryValue]

    def for_prim(self, prim_path: str) -> ResolvedTelemetryValue | None:
        """Return the current resolved value without exposing mutable state."""

        return self.values_by_prim_path.get(prim_path)


@dataclass(frozen=True)
class HeatmapSemanticRegistry:
    """Deterministic prim-to-semantic-to-binding registry for later presentation."""

    targets: tuple[HeatmapTargetBinding, ...]
    targets_by_prim_path: Mapping[str, HeatmapTargetBinding]
    semantic_groups: Mapping[SemanticKey, tuple[str, ...]]
    diagnostics: tuple[HeatmapBindingDiagnostic, ...]
    unavailable_diagnostics: tuple[HeatmapBindingDiagnostic, ...]

    @property
    def success(self) -> bool:
        """Return false only for deterministic identity construction errors."""

        return not self.diagnostics

    @property
    def target_count(self) -> int:
        """Return the valid Heatmap-target count represented by this registry."""

        return len(self.targets)

    @property
    def semantic_group_count(self) -> int:
        """Return the number of shared semantic keys."""

        return len(self.semantic_groups)

    @property
    def bound_group_count(self) -> int:
        """Return semantic groups with documented telemetry."""

        return sum(
            self.targets_by_prim_path[paths[0]].telemetry_binding.available
            for paths in self.semantic_groups.values()
        )

    @property
    def unavailable_group_count(self) -> int:
        """Return semantic groups that truthfully have no documented metric."""

        return self.semantic_group_count - self.bound_group_count

    @property
    def fingerprint(self) -> tuple[HeatmapTargetBinding, ...]:
        """Expose deterministic static identity for workload comparisons."""

        return self.targets

    def for_prim(self, prim_path: str) -> HeatmapTargetBinding | None:
        """Resolve a stable binding record for one prim path."""

        return self.targets_by_prim_path.get(prim_path)

    def resolve_telemetry(
        self,
        snapshot: TelemetrySnapshot | None,
    ) -> HeatmapTelemetrySnapshot:
        """Resolve current values without changing registry identity or bindings."""

        values = {
            target.prim_path: _resolve_telemetry_value(
                target.telemetry_binding,
                snapshot,
            )
            for target in self.targets
        }
        return HeatmapTelemetrySnapshot(
            timestamp=snapshot.timestamp if snapshot else None,
            values_by_prim_path=MappingProxyType(values),
        )


def build_heatmap_semantic_registry(
    targets: tuple[ThermalPrimMetadata, ...],
) -> HeatmapSemanticRegistry:
    """Build static semantic evidence from validated discovery records only."""

    bindings: list[HeatmapTargetBinding] = []
    diagnostics: list[HeatmapBindingDiagnostic] = []
    unavailable_by_key: dict[SemanticKey, HeatmapBindingDiagnostic] = {}
    for target in sorted(targets, key=lambda item: item.prim_path):
        identity, diagnostic = resolve_hardware_identity(target.prim_path)
        if diagnostic is not None:
            diagnostics.append(diagnostic)
            continue
        key = SemanticKey(
            hardware=identity,
            thermal_zone=target.thermal_zone or "",
            thermal_component=target.thermal_component or "",
        )
        telemetry_binding = resolve_telemetry_binding(key)
        if not telemetry_binding.available:
            unavailable_by_key.setdefault(
                key,
                unavailable_telemetry_binding(
                    target.prim_path,
                    telemetry_binding.unavailable_reason or "Telemetry unavailable.",
                ),
            )
        bindings.append(
            HeatmapTargetBinding(
                prim_path=target.prim_path,
                semantic_key=key,
                telemetry_binding=telemetry_binding,
            )
        )

    bindings.sort(key=lambda item: item.prim_path)
    grouped: dict[SemanticKey, list[str]] = defaultdict(list)
    for binding in bindings:
        grouped[binding.semantic_key].append(binding.prim_path)
    ordered_groups = {
        key: tuple(sorted(paths))
        for key, paths in sorted(
            grouped.items(),
            key=lambda item: _semantic_sort_key(item[0]),
        )
    }
    return HeatmapSemanticRegistry(
        targets=tuple(bindings),
        targets_by_prim_path=MappingProxyType(
            {binding.prim_path: binding for binding in bindings}
        ),
        semantic_groups=MappingProxyType(ordered_groups),
        diagnostics=tuple(sorted(diagnostics, key=lambda item: item.prim_path)),
        unavailable_diagnostics=tuple(
            unavailable_by_key[key]
            for key in sorted(unavailable_by_key, key=_semantic_sort_key)
        ),
    )


def resolve_hardware_identity(
    prim_path: str,
) -> tuple[HardwareIdentity, HeatmapBindingDiagnostic | None]:
    """Resolve stable topology ancestry without individual mesh-path rules."""

    parts = tuple(part for part in prim_path.split("/") if part)
    try:
        root_index = parts.index("blackwell_rig")
    except ValueError:
        return HardwareIdentity("unclassified"), None
    ancestry = parts[root_index + 1 :]
    gpu_candidates = tuple(
        ancestry[index + 1]
        for index, part in enumerate(ancestry[:-1])
        if part == "compute" and ancestry[index + 1] in {"gpu_01", "gpu_02", "gpu_03"}
    )
    if len(set(gpu_candidates)) > 1:
        return HardwareIdentity("ambiguous"), ambiguous_hardware_identity(
            prim_path,
            tuple(sorted(set(gpu_candidates))),
        )
    if gpu_candidates:
        return (
            HardwareIdentity("gpu", int(gpu_candidates[0].removeprefix("gpu_"))),
            None,
        )
    if not ancestry:
        return HardwareIdentity("server"), None
    top_level = ancestry[0]
    if top_level == "cpu_cooler":
        return HardwareIdentity("cpu"), None
    if top_level == "connectx_7":
        return HardwareIdentity("nic"), None
    if ancestry[:2] == ("power", "psu"):
        return HardwareIdentity("psu"), None
    if top_level == "motherboard":
        dimm_slot_instance = _motherboard_dimm_slot_instance(ancestry)
        if dimm_slot_instance is not None:
            return HardwareIdentity("ram", dimm_slot_instance), None
        return HardwareIdentity("motherboard"), None
    if top_level == "ram" and len(ancestry) > 1:
        instance_name = ancestry[1]
        if instance_name.startswith("ram_") and instance_name[4:].isdigit():
            instance = int(instance_name.removeprefix("ram_"))
            if 1 <= instance <= 8:
                return HardwareIdentity("ram", instance), None
    if top_level == "fans" and len(ancestry) > 1:
        return HardwareIdentity("fan", ancestry[1]), None
    return HardwareIdentity(top_level), None


def resolve_telemetry_binding(key: SemanticKey) -> TelemetryBinding:
    """Map only documented production semantic combinations to metrics."""

    hardware = key.hardware
    if hardware.family == "gpu":
        metric_suffix = _gpu_metric_suffix(key)
        if metric_suffix is not None and isinstance(hardware.instance, int):
            return TelemetryBinding(
                metric_id=f"gpu_{hardware.instance}_{metric_suffix}"
            )
    elif hardware.family == "cpu":
        return TelemetryBinding(metric_id="cpu_temp_c")
    elif hardware.family == "nic":
        return TelemetryBinding(metric_id="nic_temp_c")
    elif hardware.family == "psu":
        return TelemetryBinding(metric_id="psu_temp_estimate_c")
    elif hardware.family == "motherboard":
        metric_id = _motherboard_metric_id(key)
        if metric_id is not None:
            return TelemetryBinding(metric_id=metric_id)
    elif hardware.family == "ram" and isinstance(hardware.instance, int):
        if 1 <= hardware.instance <= 8:
            return TelemetryBinding(metric_id=f"ram_{hardware.instance}_temp_c")
    return TelemetryBinding(
        metric_id=None,
        unavailable_reason=(
            "No documented telemetry metric for "
            f"{key.hardware.label}/{key.thermal_zone}/{key.thermal_component}."
        ),
    )


def _motherboard_dimm_slot_instance(ancestry: tuple[str, ...]) -> int | None:
    """Resolve the authored DIMM-slot instance without a leaf-mesh rule."""

    if not ancestry or ancestry[0] != "motherboard" or "ram_slots" not in ancestry:
        return None
    instances = tuple(
        int(part.removeprefix("dimm_"))
        for part in ancestry
        if part.startswith("dimm_") and part[5:].isdigit()
    )
    if len(instances) != 1 or not 1 <= instances[0] <= 8:
        return None
    return instances[0]


def _gpu_metric_suffix(key: SemanticKey) -> str | None:
    """Classify the authored GPU vocabulary without relying on mesh topology."""

    if key.thermal_zone == "gpu_core" and key.thermal_component == "gb203_die":
        return "hotspot_temp_c"
    if key.thermal_zone == "vram":
        return "memory_temp_c"
    if key.thermal_zone == "gpu_body" and key.thermal_component == "plug":
        return "temp_c"
    if key.thermal_zone in {"board", "gpu_core", "vrm"} or (
        key.thermal_zone,
        key.thermal_component,
    ) in {
        ("gpu_body", "shroud"),
        ("gpu_cooling", "blower"),
    }:
        return "temp_c"
    return None


def _motherboard_metric_id(key: SemanticKey) -> str | None:
    """Apply authored motherboard specificity before the general board anchor."""

    if key.thermal_zone == "cpu" and key.thermal_component == "cpu_package":
        return "chipset_temp_c"
    if key.thermal_zone == "cpu" and key.thermal_component == "socket":
        return "cpu_temp_c"
    if key.thermal_zone == "vrm_east" and key.thermal_component == "vrm_heatsink":
        return "vrm_e_temp_c"
    if key.thermal_zone == "vrm_west" and key.thermal_component == "vrm_heatsink":
        return "vrm_w_temp_c"
    if key.thermal_zone == "mb_nvme":
        return {
            "nvme_heatsink_a": "nvme_1_temp_c",
            "nvme_heatsink_b": "nvme_2_temp_c",
        }.get(key.thermal_component)
    if key.thermal_zone in {
        "mb_base",
        "mb_capacitors",
        "mb_chips",
        "mb_chokes",
        "mb_pcie_gpu",
        "mb_resistors",
        "memory",
        "motherboard_passive",
        "motherboard_power",
    }:
        return "motherboard_temp_c"
    return None


def _resolve_telemetry_value(
    binding: TelemetryBinding,
    snapshot: TelemetrySnapshot | None,
) -> ResolvedTelemetryValue:
    if not binding.available:
        return ResolvedTelemetryValue(
            metric_id=None,
            available=False,
            value=None,
            unit=None,
            quality="unavailable",
            reason=binding.unavailable_reason,
        )
    if snapshot is None:
        return ResolvedTelemetryValue(
            metric_id=binding.metric_id,
            available=False,
            value=None,
            unit=None,
            quality="unavailable",
            reason="No current telemetry snapshot.",
        )
    metric = snapshot.metrics.get(binding.metric_id or "")
    if metric is None:
        return ResolvedTelemetryValue(
            metric_id=binding.metric_id,
            available=False,
            value=None,
            unit=None,
            quality="unavailable",
            reason=f"Current telemetry snapshot is missing {binding.metric_id}.",
        )
    return ResolvedTelemetryValue(
        metric_id=binding.metric_id,
        available=True,
        value=metric.value,
        unit=metric.unit,
        quality=metric.quality,
    )


def _semantic_sort_key(key: SemanticKey) -> tuple[str, str, str]:
    return (key.hardware.label, key.thermal_zone, key.thermal_component)
