"""Coordinator contracts that do not require launching a Kit application."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from digital_twin_runtime_suite.app.commands import RuntimeController
from digital_twin_runtime_suite.app.heatmaps import runtime
from digital_twin_runtime_suite.app.heatmaps.runtime import (
    HeatmapRuntimeMixin,
    HeatmapRuntimeResult,
    initialise_heatmap_runtime,
)
from digital_twin_runtime_suite.app.heatmaps.settings import (
    HeatmapSettings,
    HeatmapSettingsStore,
)
from digital_twin_runtime_suite.app.visualization_mode.model import VisualizationMode


class _Controller(HeatmapRuntimeMixin):
    def commit_normal_after_heatmap_selection_cleared_in_kit(self):
        self.normal_commit_count = getattr(self, "normal_commit_count", 0) + 1
        return SimpleNamespace(
            success=True, message="Visualization returned to Normal."
        )


class _Catalog:
    def __init__(self, targets=()) -> None:
        self.selections: list[tuple[str, ...]] = []
        self._targets = tuple(targets)

    def validate_selection(self, selectors: tuple[str, ...]) -> None:
        self.selections.append(selectors)
        unknown = set(selectors) - {
            "motherboard",
            "ram",
            "gpu_01_housing",
        }
        if unknown:
            raise ValueError("Unknown Heatmap Isolation selectors")

    def selected_targets(self, selectors):
        selected = frozenset(selectors)
        return tuple(
            target
            for target in self._targets
            if selected.intersection(target.selector_ids)
        )


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


def test_zero_selection_apply_restores_the_debug_harness_owner(tmp_path) -> None:
    controller = _Controller()
    initialise_heatmap_runtime(controller, tmp_path / "runtime.toml")
    controller._heatmap_catalog = _Catalog()
    controller._heatmap_stage = lambda: object()
    controller._heatmap_presentation = _ActivePresentation()
    controller._heatmap_isolation = _Isolation()
    controller._heatmap_presentation_owner = controller._HEATMAP_DEBUG_OWNER

    result = controller.apply_heatmap_settings_in_kit(HeatmapSettings())

    assert result.success
    assert not controller.heatmap_test_active()
    assert not controller._heatmap_presentation.active


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


def test_failed_active_apply_reports_when_previous_rollback_also_fails(
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

    controller._prepare_plan = lambda settings: SimpleNamespace(settings=settings)
    controller._activate_plan = lambda _stage, plan: HeatmapRuntimeResult(
        False,
        False,
        f"{plan.settings.isolation_selectors[0]} activation failed",
    )

    result = controller.apply_heatmap_settings_in_kit(candidate)

    assert not result.success
    assert "Candidate apply failed" in result.message
    assert "ram activation failed" in result.message
    assert "previous presentation rollback failed" in result.message
    assert "motherboard activation failed" in result.message
    assert controller.heatmap_applied_settings_snapshot() == previous
    assert controller._heatmap_settings_store.load() == previous


def test_stage_preparation_reloads_persisted_heatmap_settings(
    tmp_path, monkeypatch
) -> None:
    controller = _Controller()
    initialise_heatmap_runtime(controller, tmp_path / "runtime.toml")
    persisted = HeatmapSettings(isolation_selectors=("ram",))
    controller._heatmap_settings_store.save(persisted)
    controller._heatmap_applied_settings = HeatmapSettings(
        isolation_selectors=("motherboard",)
    )
    controller._heatmap_stage = lambda: object()
    controller._heatmap_isolation = _StageOwner()
    controller._heatmap_presentation = _StageOwner()
    catalog = SimpleNamespace(registry=_Registry())
    monkeypatch.setattr(
        runtime, "build_heatmap_catalog", lambda *_args, **_kwargs: catalog
    )

    prepared = controller.prepare_heatmaps_for_open_stage()

    assert prepared is catalog
    assert controller.heatmap_applied_settings_snapshot() == persisted


def test_stage_preparation_seeds_legacy_overlay_with_all_xray_groups(
    tmp_path,
    monkeypatch,
) -> None:
    controller = _Controller()
    initialise_heatmap_runtime(controller, tmp_path / "runtime.toml")
    persisted = HeatmapSettings(isolation_selectors=("motherboard",))
    controller._heatmap_settings_store.save(persisted)
    legacy_text = controller._heatmap_settings_store.path.read_text(encoding="utf-8")
    controller._heatmap_settings_store.path.write_text(
        legacy_text.replace("[xray_overlay]\nselected_group_ids = []\n\n", ""),
        encoding="utf-8",
    )
    controller.config = SimpleNamespace(
        chassis_presentation=SimpleNamespace(
            xray_target_groups=(
                SimpleNamespace(group_id="chassis"),
                SimpleNamespace(group_id="gpu_shrouds"),
            ),
        ),
    )
    controller._heatmap_stage = lambda: object()
    controller._heatmap_isolation = _StageOwner()
    controller._heatmap_presentation = _StageOwner()
    catalog = SimpleNamespace(registry=_Registry())
    monkeypatch.setattr(
        runtime, "build_heatmap_catalog", lambda *_args, **_kwargs: catalog
    )

    controller.prepare_heatmaps_for_open_stage()

    assert controller.heatmap_applied_settings_snapshot().xray_overlay_group_ids == (
        "chassis",
        "gpu_shrouds",
    )
    assert controller._heatmap_settings_store.load().xray_overlay_group_ids == (
        "chassis",
        "gpu_shrouds",
    )


def test_stage_preparation_keeps_an_explicit_empty_overlay_selection(
    tmp_path,
    monkeypatch,
) -> None:
    controller = _Controller()
    initialise_heatmap_runtime(controller, tmp_path / "runtime.toml")
    persisted = HeatmapSettings(isolation_selectors=("motherboard",))
    controller._heatmap_settings_store.save(persisted)
    controller.config = SimpleNamespace(
        chassis_presentation=SimpleNamespace(
            xray_target_groups=(SimpleNamespace(group_id="chassis"),),
        ),
    )
    controller._heatmap_stage = lambda: object()
    controller._heatmap_isolation = _StageOwner()
    controller._heatmap_presentation = _StageOwner()
    catalog = SimpleNamespace(registry=_Registry())
    monkeypatch.setattr(
        runtime, "build_heatmap_catalog", lambda *_args, **_kwargs: catalog
    )

    controller.prepare_heatmaps_for_open_stage()

    assert controller.heatmap_applied_settings_snapshot().xray_overlay_group_ids == ()


def test_production_apply_recomposes_xray_housing_precedence(tmp_path) -> None:
    controller, calls = _production_controller(tmp_path)
    previous = HeatmapSettings(
        isolation_selectors=("motherboard",),
        xray_overlay_group_ids=("gpu_shrouds",),
    )
    housing_on = HeatmapSettings(
        isolation_selectors=("gpu_01_housing",),
        xray_overlay_group_ids=("gpu_shrouds",),
    )
    controller._heatmap_applied_settings = previous
    controller._heatmap_settings_store.save(previous)
    controller._heatmap_presentation_owner = controller._HEATMAP_PRODUCTION_OWNER

    applied = controller.apply_heatmap_settings_in_kit(housing_on)

    assert applied.success
    assert controller.heatmap_production_active()
    assert calls["released"] == 1
    assert calls["xray"][-1] == (
        frozenset({"gpu_shrouds"}),
        ("/blackwell_rig/compute/gpu_01/shroud",),
    )

    applied = controller.apply_heatmap_settings_in_kit(previous)

    assert applied.success
    assert calls["xray"][-1] == (frozenset({"gpu_shrouds"}), ())


def test_zero_production_selection_returns_mode_ownership_to_normal(tmp_path) -> None:
    controller = RuntimeController(_runtime_config_path())
    controller._heatmap_settings_store = HeatmapSettingsStore(
        tmp_path / "heatmap_settings.toml"
    )
    controller._heatmap_catalog = _Catalog()
    controller._heatmap_stage = lambda: object()
    controller._heatmap_presentation = _ActivePresentation()
    controller._heatmap_isolation = _Isolation()
    previous = HeatmapSettings(isolation_selectors=("motherboard",))
    controller._heatmap_applied_settings = previous
    controller._heatmap_presentation_owner = controller._HEATMAP_PRODUCTION_OWNER
    assert controller._xray_target_state.activate_override(
        "heatmap_preview",
        frozenset({"chassis"}),
    )

    def release_heatmap_xray_override():
        assert controller._xray_target_state.release_override("heatmap_preview")
        return SimpleNamespace(success=True, message="X-Ray restored.")

    controller.release_heatmap_xray_override_in_kit = release_heatmap_xray_override
    transition = controller._visualization_mode_state.begin(VisualizationMode.HEATMAP)
    assert transition is not None
    assert controller._visualization_mode_state.commit(transition.transition_id)

    result = controller.apply_heatmap_settings_in_kit(HeatmapSettings())

    assert result.success
    assert controller.visualization_snapshot().committed is VisualizationMode.NORMAL
    assert not controller.heatmap_production_active()
    assert controller.xray_target_snapshot().override_owner is None
    assert controller._heatmap_presentation_task is None


def test_heatmaps_runtime_does_not_mutate_visualization_state_directly() -> None:
    source = Path(runtime.__file__).read_text(encoding="utf-8")

    assert "_visualization_mode_state" not in source


def test_production_activation_uses_persisted_overlay_group_ids(tmp_path) -> None:
    controller, calls = _production_controller(tmp_path)
    settings = HeatmapSettings(
        isolation_selectors=("gpu_01_housing",),
        xray_overlay_group_ids=("gpu_shrouds",),
    )
    controller._heatmap_applied_settings = settings
    controller._heatmap_settings_store.save(settings)
    controller._heatmap_presentation.active = False

    result = controller.activate_heatmap_production_in_kit()

    assert result.success
    assert controller.heatmap_production_active()
    assert calls["xray"] == [
        (
            frozenset({"gpu_shrouds"}),
            ("/blackwell_rig/compute/gpu_01/shroud",),
        )
    ]


def test_failed_production_apply_restores_previous_complete_composition(
    tmp_path,
) -> None:
    controller, calls = _production_controller(tmp_path)
    previous = HeatmapSettings(
        isolation_selectors=("motherboard",),
        xray_overlay_group_ids=("gpu_shrouds",),
    )
    candidate = HeatmapSettings(
        isolation_selectors=("gpu_01_housing",),
        xray_overlay_group_ids=("gpu_shrouds",),
    )
    controller._heatmap_applied_settings = previous
    controller._heatmap_settings_store.save(previous)
    controller._heatmap_presentation_owner = controller._HEATMAP_PRODUCTION_OWNER

    def activate(_stage, plan, *, visibility_target_paths=None):
        calls["visibility"].append(visibility_target_paths)
        if plan.settings == candidate:
            return HeatmapRuntimeResult(False, False, "candidate presentation failed")
        controller._heatmap_presentation.active = True
        return HeatmapRuntimeResult(True, True, "presentation applied")

    controller._activate_plan = activate

    result = controller.apply_heatmap_settings_in_kit(candidate)

    assert not result.success
    assert controller.heatmap_production_active()
    assert controller.heatmap_applied_settings_snapshot() == previous
    assert controller._heatmap_settings_store.load() == previous
    assert calls["xray"][-1] == (frozenset({"gpu_shrouds"}), ())


def _production_controller(tmp_path):
    controller = _Controller()
    initialise_heatmap_runtime(controller, tmp_path / "runtime.toml")
    target = SimpleNamespace(
        prim_path="/blackwell_rig/compute/gpu_01/shroud/thermal_mesh",
        selector_ids=("gpu_01_housing",),
    )
    controller._heatmap_catalog = _Catalog((target,))
    controller.config = SimpleNamespace(
        chassis_presentation=SimpleNamespace(
            xray_target_groups=(
                SimpleNamespace(
                    group_id="gpu_shrouds",
                    paths=("/blackwell_rig/compute/gpu_01/shroud",),
                ),
            ),
        ),
    )
    controller._heatmap_stage = lambda: object()
    controller._heatmap_presentation = _ActivePresentation()
    controller._heatmap_isolation = _Isolation()
    calls = {"released": 0, "xray": [], "visibility": []}

    def prepare(settings):
        return SimpleNamespace(settings=settings)

    def activate(_stage, plan, *, visibility_target_paths=None):
        calls["visibility"].append(visibility_target_paths)
        controller._heatmap_presentation.active = True
        return HeatmapRuntimeResult(True, True, "presentation applied")

    def apply_xray(group_ids, excluded_paths):
        calls["xray"].append((group_ids, excluded_paths))
        return HeatmapRuntimeResult(True, True, "X-Ray applied")

    def release_xray():
        calls["released"] += 1
        return HeatmapRuntimeResult(True, False, "X-Ray released")

    controller._prepare_plan = prepare
    controller._activate_plan = activate
    controller.apply_heatmap_xray_override_in_kit = apply_xray
    controller.release_heatmap_xray_override_in_kit = release_xray
    return controller, calls


class _StageOwner:
    active = False

    @staticmethod
    def discard_stale_stage(_stage) -> None:
        return None


class _Registry:
    @staticmethod
    def resolve_telemetry(_snapshot):
        return None


class _ActivePresentation:
    def __init__(self) -> None:
        self.active = True

    def restore(self, _stage):
        self.active = False
        return SimpleNamespace(success=True, message="restored")


class _Isolation:
    def restore(self, _stage):
        return SimpleNamespace(success=True, message="restored")


def _runtime_config_path() -> Path:
    return Path(__file__).parents[2] / "configs" / "digital_twin_runtime_suite.toml"
