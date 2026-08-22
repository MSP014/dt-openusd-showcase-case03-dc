"""Thin Kit-facing coordinator for generic settings-driven Heatmap presentation."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from .catalog import HeatmapCatalog, build_heatmap_catalog
from .isolation import HeatmapIsolation
from .presentation import (
    HeatmapPresentation,
    build_heatmap_presentation_plan,
    resolve_heatmap_global_celsius_scale,
)
from .settings import SETTINGS_FILENAME, HeatmapSettings, HeatmapSettingsStore
from .smoothing import (
    HEATMAP_PRESENTATION_CADENCE_HZ,
    HEATMAP_PRESENTATION_TRANSITION_DURATION_SECONDS,
    HeatmapPresentationSmoother,
)


@dataclass(frozen=True)
class HeatmapRuntimeResult:
    """Outcome of one Test, Restore, or Apply request through the runtime facade."""

    success: bool
    enabled: bool
    message: str
    target_paths: tuple[str, ...] = ()
    unavailable_target_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class HeatmapPresentationDiagnostics:
    """Compact preserved-cadence evidence for the currently active presentation."""

    active: bool
    cadence_hz: int
    transition_duration_seconds: float
    scheduler_ticks: int
    target_changes: int
    material_group_count: int


@dataclass(frozen=True)
class HeatmapCelsiusScaleSnapshot:
    """Read-only current global scale for Heatmap UI information only."""

    minimum_celsius: float
    maximum_celsius: float


class HeatmapRuntimeMixin:
    """Coordinate prepared catalog, settings, isolation, material, and smoothing."""

    HEATMAP_SERVER_ROOT_PATH = "/blackwell_rig"

    def prepare_heatmaps_for_open_stage(self) -> HeatmapCatalog | None:
        """Build a read-only catalog after the production stage-open success barrier."""

        stage = self._heatmap_stage()
        if stage is None:
            self._heatmap_catalog = None
            self._heatmap_telemetry_snapshot = None
            return None
        self._stop_heatmap_presentation_scheduler()
        self._heatmap_isolation.discard_stale_stage(stage)
        self._heatmap_presentation.discard_stale_stage(stage)
        self._heatmap_applied_settings = self._heatmap_settings_store.load()
        self._heatmap_catalog = build_heatmap_catalog(
            stage,
            root_path=self.HEATMAP_SERVER_ROOT_PATH,
        )
        self._refresh_heatmap_telemetry_resolution()
        return self._heatmap_catalog

    def heatmap_catalog_snapshot(self) -> HeatmapCatalog | None:
        """Expose the latest stage-driven catalog for UI draft construction only."""

        return self._heatmap_catalog

    def heatmap_applied_settings_snapshot(self) -> HeatmapSettings:
        """Expose last successfully persisted settings, never an unsaved UI draft."""

        return self._heatmap_applied_settings

    def heatmap_settings_snapshot(self) -> HeatmapSettings:
        """Retain a concise compatibility name for UI settings population."""

        return self.heatmap_applied_settings_snapshot()

    def heatmap_test_active(self) -> bool:
        """Return whether generic Heatmap presentation currently owns Session state."""

        return self._heatmap_presentation.active

    def heatmap_global_celsius_scale_snapshot(
        self,
    ) -> HeatmapCelsiusScaleSnapshot | None:
        """Expose the plan's existing global scale without preparing presentation."""

        catalog = self._heatmap_catalog
        if catalog is None or self._heatmap_telemetry_config is None:
            return None
        try:
            scale = resolve_heatmap_global_celsius_scale(
                catalog,
                self._heatmap_telemetry_config,
            )
        except ValueError:
            return None
        return HeatmapCelsiusScaleSnapshot(
            minimum_celsius=scale.minimum,
            maximum_celsius=scale.maximum,
        )

    def configure_heatmap_telemetry_config(self, telemetry_config) -> None:
        """Accept provider configuration without changing USD or active settings."""

        self._heatmap_telemetry_config = telemetry_config

    def refresh_heatmap_telemetry_snapshot(self, snapshot) -> None:
        """Resolve fresh telemetry and retarget only an already active presentation."""

        self._heatmap_current_telemetry_snapshot = snapshot
        self._refresh_heatmap_telemetry_resolution()
        plan = self._heatmap_presentation.plan
        telemetry = self._heatmap_telemetry_snapshot
        if plan is None or telemetry is None:
            return
        values: dict[str, float] = {}
        for target in plan.material_targets:
            current = telemetry.for_prim(target.prim_path)
            if current is None or not current.available:
                continue
            if not isinstance(current.value, (int, float)):
                continue
            values[target.material_key] = float(current.value)
        if values:
            self._heatmap_presentation_target_changes += (
                self._heatmap_presentation_smoother.set_targets(
                    values,
                    now=time.monotonic(),
                )
            )

    def test_heatmaps_in_kit(self) -> HeatmapRuntimeResult:
        """Activate last applied settings; unsaved UI controls cannot affect it."""

        stage = self._heatmap_stage()
        if stage is None:
            return self._result(
                False,
                "Heatmap test requires an open production stage.",
            )
        settings = self._heatmap_applied_settings
        if not settings.isolation_selectors:
            return self.restore_heatmap_test_in_kit()
        try:
            plan = self._prepare_plan(settings)
        except ValueError as error:
            return self._result(False, str(error))
        if self._heatmap_presentation.active:
            return self._result(True, "Heatmap test is already active.")
        return self._activate_plan(stage, plan)

    def restore_heatmap_test_in_kit(self) -> HeatmapRuntimeResult:
        """Restore exact Heatmap-owned state without saving configuration."""

        stage = self._heatmap_stage()
        if stage is None:
            return self._result(True, "Heatmap test is already restored.")
        return self._restore_active_presentation(stage)

    def apply_heatmap_settings_in_kit(
        self,
        candidate: HeatmapSettings,
    ) -> HeatmapRuntimeResult:
        """Validate, transactionally replace active presentation, then persist."""

        try:
            candidate.validate()
            catalog = self._require_heatmap_catalog()
            catalog.validate_selection(candidate.isolation_selectors)
        except ValueError as error:
            return self._result(False, str(error))
        stage = self._heatmap_stage()
        active = self._heatmap_presentation.active
        if not active:
            try:
                self._heatmap_settings_store.save(candidate)
            except OSError as error:
                return self._result(
                    False,
                    f"Heatmap settings could not be saved: {error}",
                )
            self._heatmap_applied_settings = candidate
            return self._result(
                True,
                "Heatmap settings applied; presentation remains off.",
            )
        if stage is None:
            return self._result(
                False,
                "Heatmap Apply requires an open production stage.",
            )
        try:
            plan = (
                self._prepare_plan(candidate) if candidate.isolation_selectors else None
            )
        except ValueError as error:
            return self._result(False, str(error))
        previous = self._heatmap_applied_settings
        restored = self._restore_active_presentation(stage)
        if not restored.success:
            return restored
        candidate_result = (
            self._activate_plan(stage, plan)
            if plan is not None
            else self._result(True, "Heatmap selection cleared; presentation restored.")
        )
        if not candidate_result.success:
            rollback = self._restore_previous_after_failed_apply(stage, previous)
            return self._failed_apply_result(candidate_result.message, rollback)
        try:
            self._heatmap_settings_store.save(candidate)
        except OSError as error:
            cleanup = self._restore_active_presentation(stage)
            rollback = self._restore_previous_after_failed_apply(stage, previous)
            message = f"Heatmap settings could not be saved: {error}"
            if not cleanup.success:
                message += f" Candidate presentation cleanup failed: {cleanup.message}"
            return self._failed_apply_result(message, rollback)
        self._heatmap_applied_settings = candidate
        return candidate_result

    def set_heatmap_presentation_cadence_hz(self, cadence_hz: int) -> None:
        """Allow tests to request the existing 2 Hz cadence and reject other values."""

        if cadence_hz != HEATMAP_PRESENTATION_CADENCE_HZ:
            raise ValueError("Heatmap presentation cadence is fixed at 2 Hz.")
        self._heatmap_presentation_cadence_hz = cadence_hz

    def heatmap_presentation_cadence_hz(self) -> int:
        """Return the preserved Heatmap scheduler cadence."""

        return self._heatmap_presentation_cadence_hz

    def heatmap_presentation_transition_duration_seconds(self) -> float:
        """Return the preserved shared 2.0-second smoothing transition."""

        return self._heatmap_presentation_smoother.transition_duration_seconds

    def heatmap_presentation_diagnostics_snapshot(
        self,
    ) -> HeatmapPresentationDiagnostics:
        """Expose bounded timing evidence without exposing implementation owners."""

        return HeatmapPresentationDiagnostics(
            active=self._heatmap_presentation.active,
            cadence_hz=self._heatmap_presentation_cadence_hz,
            transition_duration_seconds=(
                self._heatmap_presentation_smoother.transition_duration_seconds
            ),
            scheduler_ticks=self._heatmap_presentation_scheduler_ticks,
            target_changes=self._heatmap_presentation_target_changes,
            material_group_count=self._heatmap_presentation_smoother.group_count,
        )

    def advance_heatmap_presentation_in_kit(self, now: float | None = None) -> bool:
        """Write only changed smoothed telemetry inputs for one scheduler tick."""

        stage = self._heatmap_stage()
        if stage is None or not self._heatmap_presentation.active:
            self._stop_heatmap_presentation_scheduler()
            return False
        self._heatmap_presentation_scheduler_ticks += 1
        changed = self._heatmap_presentation_smoother.tick(
            now=time.monotonic() if now is None else now
        )
        if not changed:
            return True
        return self._heatmap_presentation.update_telemetry(stage, dict(changed)).success

    def _prepare_plan(self, settings: HeatmapSettings):
        catalog = self._require_heatmap_catalog()
        return build_heatmap_presentation_plan(
            catalog,
            settings,
            self._heatmap_telemetry_snapshot,
            self._heatmap_telemetry_config,
        )

    def _activate_plan(self, stage, plan) -> HeatmapRuntimeResult:
        isolation = self._heatmap_isolation.apply(stage, plan.selected_target_paths)
        if not isolation.success:
            return self._result(False, isolation.message)
        presentation = self._heatmap_presentation.apply(stage, plan)
        if not presentation.success:
            self._heatmap_isolation.restore(stage)
            return self._result(False, presentation.message)
        self._activate_heatmap_smoothing(plan)
        return self._result(
            True,
            "Heatmap presentation applied.",
            target_paths=presentation.target_paths,
            unavailable_target_paths=plan.unavailable_target_paths,
        )

    def _restore_active_presentation(self, stage) -> HeatmapRuntimeResult:
        self._stop_heatmap_presentation_scheduler()
        presentation = self._heatmap_presentation.restore(stage)
        if not presentation.success:
            return self._result(False, presentation.message)
        isolation = self._heatmap_isolation.restore(stage)
        if not isolation.success:
            return self._result(False, isolation.message)
        return self._result(True, "Heatmap test restored the prior scene presentation.")

    def _restore_previous_after_failed_apply(
        self,
        stage,
        settings: HeatmapSettings,
    ) -> HeatmapRuntimeResult:
        """Restore the prior valid plan and report a rollback failure explicitly."""

        if not settings.isolation_selectors:
            return self._result(True, "Previous Heatmap presentation was already off.")
        try:
            plan = self._prepare_plan(settings)
        except ValueError as error:
            return self._result(
                False,
                f"Previous Heatmap presentation could not be prepared: {error}",
            )
        return self._activate_plan(stage, plan)

    def _failed_apply_result(
        self,
        candidate_message: str,
        rollback: HeatmapRuntimeResult,
    ) -> HeatmapRuntimeResult:
        """Preserve a candidate failure while making rollback failure actionable."""

        if rollback.success:
            return self._result(False, candidate_message)
        return self._result(
            False,
            "Candidate apply failed: "
            f"{candidate_message} AND previous presentation rollback failed: "
            f"{rollback.message}",
        )

    def _activate_heatmap_smoothing(self, plan) -> None:
        values = plan.telemetry_by_material_key()
        self._heatmap_presentation_smoother.reset(values, now=time.monotonic())
        self._ensure_heatmap_presentation_scheduler()

    def _ensure_heatmap_presentation_scheduler(self) -> None:
        task = self._heatmap_presentation_task
        if task is not None and not task.done():
            return
        self._heatmap_presentation_scheduler_id += 1
        scheduler_id = self._heatmap_presentation_scheduler_id
        self._heatmap_presentation_task = asyncio.ensure_future(
            self._run_heatmap_presentation_scheduler(scheduler_id)
        )

    async def _run_heatmap_presentation_scheduler(self, scheduler_id: int) -> None:
        try:
            import omni.kit.app

            app = omni.kit.app.get_app()
            next_tick = time.monotonic()
            while scheduler_id == self._heatmap_presentation_scheduler_id:
                await app.next_update_async()
                now = time.monotonic()
                if now < next_tick:
                    continue
                next_tick = now + (1.0 / self._heatmap_presentation_cadence_hz)
                if not self.advance_heatmap_presentation_in_kit(now):
                    return
        except asyncio.CancelledError:
            return
        finally:
            if scheduler_id == self._heatmap_presentation_scheduler_id:
                self._heatmap_presentation_task = None

    def _stop_heatmap_presentation_scheduler(self) -> None:
        self._heatmap_presentation_scheduler_id += 1
        task = self._heatmap_presentation_task
        self._heatmap_presentation_task = None
        if task is not None and not task.done():
            task.cancel()
        self._heatmap_presentation_smoother.reset({}, now=time.monotonic())

    def _refresh_heatmap_telemetry_resolution(self) -> None:
        catalog = self._heatmap_catalog
        if catalog is None:
            self._heatmap_telemetry_snapshot = None
            return
        self._heatmap_telemetry_snapshot = catalog.registry.resolve_telemetry(
            self._heatmap_current_telemetry_snapshot
        )

    def _require_heatmap_catalog(self) -> HeatmapCatalog:
        catalog = self._heatmap_catalog
        if catalog is None:
            raise ValueError("Heatmap catalog is unavailable until the stage is ready.")
        return catalog

    @staticmethod
    def _heatmap_stage():
        try:
            import omni.usd
        except ImportError:
            return None
        return omni.usd.get_context().get_stage()

    def _result(
        self,
        success: bool,
        message: str,
        *,
        target_paths: tuple[str, ...] = (),
        unavailable_target_paths: tuple[str, ...] = (),
    ) -> HeatmapRuntimeResult:
        return HeatmapRuntimeResult(
            success=success,
            enabled=self._heatmap_presentation.active,
            message=message,
            target_paths=target_paths,
            unavailable_target_paths=unavailable_target_paths,
        )


def initialise_heatmap_runtime(controller, config_path) -> None:
    """Install Heatmap owners on RuntimeController without a cooperative mixin init."""

    store = HeatmapSettingsStore(config_path.with_name(SETTINGS_FILENAME))
    controller._heatmap_settings_store = store
    controller._heatmap_applied_settings = store.load()
    controller._heatmap_catalog = None
    controller._heatmap_current_telemetry_snapshot = None
    controller._heatmap_telemetry_snapshot = None
    controller._heatmap_telemetry_config = None
    controller._heatmap_isolation = HeatmapIsolation(
        root_path=HeatmapRuntimeMixin.HEATMAP_SERVER_ROOT_PATH
    )
    controller._heatmap_presentation = HeatmapPresentation()
    controller._heatmap_presentation_smoother = HeatmapPresentationSmoother(
        transition_duration_seconds=HEATMAP_PRESENTATION_TRANSITION_DURATION_SECONDS
    )
    controller._heatmap_presentation_cadence_hz = HEATMAP_PRESENTATION_CADENCE_HZ
    controller._heatmap_presentation_task = None
    controller._heatmap_presentation_scheduler_id = 0
    controller._heatmap_presentation_scheduler_ticks = 0
    controller._heatmap_presentation_target_changes = 0
