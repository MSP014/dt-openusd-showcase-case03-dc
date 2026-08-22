"""Build and own one generic Heatmap presentation for any selector union."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .calibration import resolve_calibration
from .catalog import HeatmapCatalog
from .material import HeatmapMaterialPresenter, HeatmapMaterialTarget
from .scalar import (
    normalize_thermal_weight_group,
    resolve_server_wide_celsius_scale,
)
from .settings import HeatmapSettings


@dataclass(frozen=True)
class HeatmapPresentationPlan:
    """Complete candidate prepared before isolation/material Session mutation."""

    settings: HeatmapSettings
    selected_target_paths: tuple[str, ...]
    material_targets: tuple[HeatmapMaterialTarget, ...]
    scale: object
    unavailable_target_paths: tuple[str, ...]

    @property
    def enabled(self) -> bool:
        """Return whether this plan has renderable selected Heatmap geometry."""

        return bool(self.material_targets)

    def telemetry_by_material_key(self) -> dict[str, float]:
        """Return one current telemetry input for each shared material group."""

        return {
            target.material_key: target.telemetry_celsius
            for target in self.material_targets
        }


def build_heatmap_presentation_plan(
    catalog: HeatmapCatalog,
    settings: HeatmapSettings,
    telemetry_snapshot,
    telemetry_config,
) -> HeatmapPresentationPlan:
    """Prepare a universal candidate without USD or Session-layer mutation."""

    settings.validate()
    catalog.validate_selection(settings.isolation_selectors)
    if not catalog.ready:
        raise ValueError("Heatmap catalog is not ready for presentation.")
    selected = catalog.selected_targets(settings.isolation_selectors)
    if not selected:
        return HeatmapPresentationPlan(settings, (), (), None, ())
    if telemetry_snapshot is None:
        raise ValueError("Heatmap telemetry is unavailable.")
    scale = resolve_heatmap_global_celsius_scale(catalog, telemetry_config)
    normalized_weights = _normalized_thermal_weights(catalog)
    material_targets: list[HeatmapMaterialTarget] = []
    unavailable: list[str] = []
    for target in selected:
        telemetry = telemetry_snapshot.for_prim(target.prim_path)
        if (
            telemetry is None
            or not telemetry.available
            or not isinstance(telemetry.value, (int, float))
        ):
            unavailable.append(target.prim_path)
            continue
        calibration = resolve_calibration(settings, target.calibration_id)
        metric_id = target.binding.telemetry_binding.metric_id
        if metric_id is None:
            unavailable.append(target.prim_path)
            continue
        material_targets.append(
            HeatmapMaterialTarget(
                material_key=_material_key(target.calibration_id, metric_id),
                prim_path=target.prim_path,
                thermal_weights=normalized_weights[target.prim_path],
                telemetry_celsius=float(telemetry.value),
                delta_profile=calibration.delta_profile,
                temperature_offset_celsius=calibration.temperature_offset_celsius,
            )
        )
    if not material_targets:
        raise ValueError("Selected Heatmap targets have no current telemetry values.")
    return HeatmapPresentationPlan(
        settings=settings,
        selected_target_paths=tuple(target.prim_path for target in selected),
        material_targets=tuple(material_targets),
        scale=scale,
        unavailable_target_paths=tuple(sorted(unavailable)),
    )


def resolve_heatmap_global_celsius_scale(
    catalog: HeatmapCatalog,
    telemetry_config,
):
    """Resolve the one server-wide scale shared by plans and read-only UI."""

    metric_ids = tuple(
        target.binding.telemetry_binding.metric_id
        for target in catalog.targets
        if target.binding.telemetry_binding.metric_id is not None
    )
    if not metric_ids:
        raise ValueError("Heatmap targets have no documented telemetry metrics.")
    if telemetry_config is None:
        raise ValueError("Heatmap telemetry configuration is unavailable.")
    return resolve_server_wide_celsius_scale(telemetry_config, metric_ids).scale


class HeatmapPresentation:
    """Own the material presenter and its active generic plan, not UI or settings IO."""

    def __init__(self) -> None:
        self._presenter = HeatmapMaterialPresenter()
        self._plan: HeatmapPresentationPlan | None = None

    @property
    def active(self) -> bool:
        """Return whether this owner has an active Session material presentation."""

        return self._presenter.active

    @property
    def plan(self) -> HeatmapPresentationPlan | None:
        """Expose the immutable active plan for smoothing and transaction rollback."""

        return self._plan

    @property
    def write_counts(self):
        """Expose owned material writes without leaking the material presenter."""

        return self._presenter.write_counts

    def apply(self, stage, plan: HeatmapPresentationPlan):
        """Apply one prepared generic plan and retain it only on material success."""

        result = self._presenter.enable(
            stage,
            targets=plan.material_targets,
            scale=plan.scale,
            palette=plan.settings.color_scale,
        )
        if result.success and result.enabled:
            self._plan = plan
        return result

    def restore(self, stage):
        """Restore exact prior material state and forget only active plan ownership."""

        result = self._presenter.disable(stage)
        if result.success:
            self._plan = None
        return result

    def update_telemetry(self, stage, values: dict[str, float]):
        """Update only dynamic material telemetry inputs at the shared cadence."""

        return self._presenter.update_telemetry(stage, values)

    def discard_stale_stage(self, stage) -> None:
        """Forget old-session plan state after a successful stage replacement."""

        self._presenter.discard_stale_stage(stage)
        if not self._presenter.active:
            self._plan = None


def _thermal_weights(catalog: HeatmapCatalog, prim_path: str) -> tuple[object, ...]:
    metadata = next(
        target
        for target in catalog.preflight.valid_targets
        if target.prim_path == prim_path
    )
    return metadata.thermal_weight or ()


def _normalized_thermal_weights(
    catalog: HeatmapCatalog,
) -> dict[str, tuple[float, ...]]:
    groups: dict[str, dict[str, tuple[float, ...]]] = {}
    for target in catalog.targets:
        groups.setdefault(target.calibration_id, {})[target.prim_path] = tuple(
            float(value) for value in _thermal_weights(catalog, target.prim_path)
        )
    return {
        prim_path: weights
        for group in groups.values()
        for prim_path, weights in normalize_thermal_weight_group(group).items()
    }


def _material_key(calibration_id: str, metric_id: str) -> str:
    raw = f"{calibration_id}_{metric_id}"
    return re.sub(r"[^A-Za-z0-9_]", "_", raw)
