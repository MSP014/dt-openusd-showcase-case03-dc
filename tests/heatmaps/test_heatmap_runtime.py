"""Coordinator contracts that do not require launching a Kit application."""

from __future__ import annotations

from types import SimpleNamespace

from digital_twin_runtime_suite.app.heatmaps.runtime import (
    HeatmapRuntimeMixin,
    HeatmapRuntimeResult,
    initialise_heatmap_runtime,
)
from digital_twin_runtime_suite.app.heatmaps.settings import HeatmapSettings


class _Controller(HeatmapRuntimeMixin):
    pass


class _Catalog:
    def __init__(self) -> None:
        self.selections: list[tuple[str, ...]] = []

    def validate_selection(self, selectors: tuple[str, ...]) -> None:
        self.selections.append(selectors)
        unknown = set(selectors) - {"motherboard", "ram"}
        if unknown:
            raise ValueError("Unknown Heatmap Isolation selectors")


def test_apply_while_off_persists_settings_without_stage_mutation(tmp_path) -> None:
    controller = _Controller()
    initialise_heatmap_runtime(controller, tmp_path / "runtime.toml")
    controller._heatmap_catalog = _Catalog()
    controller._heatmap_stage = lambda: None
    candidate = HeatmapSettings(isolation_selectors=("motherboard",))

    result = controller.apply_heatmap_settings_in_kit(candidate)

    assert result.success
    assert not result.enabled
    assert controller.heatmap_applied_settings_snapshot() == candidate
    assert controller._heatmap_settings_store.load() == candidate


def test_test_uses_applied_settings_not_an_unsaved_draft(tmp_path) -> None:
    controller = _Controller()
    initialise_heatmap_runtime(controller, tmp_path / "runtime.toml")
    controller._heatmap_catalog = _Catalog()
    applied = HeatmapSettings(isolation_selectors=("motherboard",))
    draft = HeatmapSettings(isolation_selectors=("ram",))
    controller._heatmap_applied_settings = applied
    observed: list[HeatmapSettings] = []
    plan = SimpleNamespace(selected_target_paths=("/blackwell_rig/motherboard",))
    controller._heatmap_stage = lambda: object()
    controller._prepare_plan = lambda settings: observed.append(settings) or plan
    controller._activate_plan = lambda stage, candidate: HeatmapRuntimeResult(
        True,
        True,
        "applied",
    )

    result = controller.test_heatmaps_in_kit()

    assert result.success
    assert observed == [applied]
    assert observed != [draft]


def test_restore_does_not_modify_persisted_settings_when_stage_is_gone(
    tmp_path,
) -> None:
    controller = _Controller()
    initialise_heatmap_runtime(controller, tmp_path / "runtime.toml")
    controller._heatmap_catalog = _Catalog()
    controller.apply_heatmap_settings_in_kit(
        HeatmapSettings(isolation_selectors=("motherboard",))
    )
    before = controller._heatmap_settings_store.path.read_bytes()
    controller._heatmap_stage = lambda: None

    result = controller.restore_heatmap_test_in_kit()

    assert result.success
    assert controller._heatmap_settings_store.path.read_bytes() == before


def test_zero_selection_apply_persists_off_state_without_viewport_work(
    tmp_path,
) -> None:
    controller = _Controller()
    initialise_heatmap_runtime(controller, tmp_path / "runtime.toml")
    controller._heatmap_catalog = _Catalog()
    controller._heatmap_stage = lambda: None

    result = controller.apply_heatmap_settings_in_kit(HeatmapSettings())

    assert result.success
    assert controller.heatmap_applied_settings_snapshot().isolation_selectors == ()


def test_failed_active_apply_restores_old_presentation_and_keeps_old_config(
    tmp_path,
) -> None:
    controller = _Controller()
    initialise_heatmap_runtime(controller, tmp_path / "runtime.toml")
    controller._heatmap_catalog = _Catalog()
    previous = HeatmapSettings(isolation_selectors=("motherboard",))
    candidate = HeatmapSettings(isolation_selectors=("ram",))
    controller._heatmap_settings_store.save(previous)
    controller._heatmap_applied_settings = previous
    controller._heatmap_stage = lambda: object()
    controller._heatmap_presentation = _ActivePresentation()
    controller._heatmap_isolation = _Isolation()
    prepared: list[HeatmapSettings] = []
    activated: list[HeatmapSettings] = []

    def prepare(settings):
        prepared.append(settings)
        return SimpleNamespace(settings=settings)

    def activate(_stage, plan):
        activated.append(plan.settings)
        if plan.settings == candidate:
            return HeatmapRuntimeResult(False, False, "candidate failure")
        controller._heatmap_presentation.active = True
        return HeatmapRuntimeResult(True, True, "restored")

    controller._prepare_plan = prepare
    controller._activate_plan = activate

    result = controller.apply_heatmap_settings_in_kit(candidate)

    assert not result.success
    assert controller.heatmap_applied_settings_snapshot() == previous
    assert controller._heatmap_settings_store.load() == previous
    assert activated == [candidate, previous]


class _ActivePresentation:
    def __init__(self) -> None:
        self.active = True

    def restore(self, _stage):
        self.active = False
        return SimpleNamespace(success=True, message="restored")


class _Isolation:
    def restore(self, _stage):
        return SimpleNamespace(success=True, message="restored")
