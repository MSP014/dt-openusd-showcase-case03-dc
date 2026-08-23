"""Bounded Stage 10 guidance over existing DTRS runtime transactions."""

from __future__ import annotations

import asyncio
from dataclasses import replace

from digital_twin_runtime_suite.app.flow.performance import (
    capture_viewport_performance_sample,
)
from digital_twin_runtime_suite.app.heatmaps.composition import (
    build_heatmap_composition_plan,
)
from digital_twin_runtime_suite.app.manual_acceptance import (
    GuidedAcceptanceSession,
    format_manual_acceptance_event,
)
from digital_twin_runtime_suite.app.performance_probe import PerformanceProbe
from digital_twin_runtime_suite.app.status_log import format_dtrs_status_block
from digital_twin_runtime_suite.app.visualization_mode import VisualizationMode

_HEATMAP_XRAY_OWNER = "heatmap_preview"
_STREAMLINES_XRAY_OWNER = "streamlines_xray"
_WORKLOAD_SEQUENCE = ("Nominal", "Surge", "Critical", "Nominal")
_MANUAL_MILESTONES = (
    "HEATMAP",
    "NOMINAL",
    "SURGE",
    "CRITICAL",
    "NOMINAL_RESTORED",
    "GPU01_HOUSING_ON",
    "GPU01_HOUSING_OFF",
    "XRAY_APPLY",
    "STREAMLINES_XRAY",
    "HEATMAP_RESTORED",
)


class Stage10AcceptanceWorkflow:
    """Verify one ordered manual path and finite existing performance samples."""

    def __init__(
        self,
        controller,
        *,
        log_warning,
        append_local_timestamp,
        performance_probe: PerformanceProbe | None = None,
    ) -> None:
        self._controller = controller
        self._log_warning = log_warning
        self._append_local_timestamp = append_local_timestamp
        self._performance_probe = performance_probe or PerformanceProbe(
            log_status=log_warning,
            append_local_timestamp=append_local_timestamp,
        )
        self._acceptance: GuidedAcceptanceSession | None = None
        self._initial_settings = None
        self._heatmap_target_paths: tuple[str, ...] = ()
        self._heatmap_xray_snapshot = None
        self._workload_index = 0
        self._automation_task = None
        self._performance_results = ()

    @property
    def active(self) -> bool:
        """Return whether guidance or its finite completion work is active."""

        session = self._acceptance
        task = self._automation_task
        return bool(
            session
            and not session.failed
            and not session.terminal_emitted
            or task is not None
            and not task.done()
        )

    def begin_if_ready(self) -> bool:
        """Emit one READY gate only after the clean production stage is available."""

        if self.active or not self._start_ready():
            return False
        self._acceptance = GuidedAcceptanceSession(_MANUAL_MILESTONES)
        self._acceptance.begin()
        self._initial_settings = self._controller.heatmap_applied_settings_snapshot()
        self._workload_index = 0
        self._report(
            "READY",
            "Stage 10 production Heatmap acceptance is ready.",
            next_action="Select Heatmap.",
        )
        return True

    def cancel(self) -> None:
        """Cancel only finite measurement work during extension shutdown."""

        task = self._automation_task
        if task is not None and not task.done():
            task.cancel()
        self._automation_task = None
        self._performance_probe.cancel()

    def observe_mode_complete(self, mode, result) -> None:
        """Advance exactly the two user-selected primary-mode milestones."""

        session = self._acceptance
        if session is None or session.failed or session.terminal_emitted:
            return
        expected = session.expected_milestone
        if expected == "HEATMAP":
            self._complete_initial_heatmap(mode, result)
        elif expected == "STREAMLINES_XRAY":
            self._complete_streamlines_xray(mode, result)
        elif expected == "HEATMAP_RESTORED":
            self._complete_restored_heatmap(mode, result)
        elif mode is not VisualizationMode.HEATMAP:
            self._fail(f"Unexpected Visualization selection: {mode.value}.")

    def observe_workload_complete(self, workload_mode: str, result) -> None:
        """Verify each requested workload change leaves Heatmap composition intact."""

        session = self._acceptance
        if session is None or session.failed or session.terminal_emitted:
            return
        expected = session.expected_milestone
        if expected not in _MANUAL_MILESTONES[1:5]:
            return
        required_workload = _WORKLOAD_SEQUENCE[self._workload_index]
        if workload_mode != required_workload:
            self._fail(
                "Unexpected workload selection: expected "
                f"{required_workload}, got {workload_mode}."
            )
            return
        if not getattr(result, "success", False):
            self._fail(f"{workload_mode} workload transition failed: {result.message}")
            return
        failure = self._heatmap_failure_reason()
        if failure:
            self._fail(f"{workload_mode} invalidated Heatmap: {failure}")
            return
        if not session.record(expected):
            self._fail("Workload acceptance order was invalid.")
            return
        self._workload_index += 1
        if self._workload_index < len(_WORKLOAD_SEQUENCE):
            next_workload = _WORKLOAD_SEQUENCE[self._workload_index]
            self._report(
                "COMPLETE",
                f"{workload_mode} retained Heatmap composition.",
                next_action=f"Switch workload to {next_workload}.",
            )
            return
        self._report(
            "COMPLETE",
            "Workload round trip retained Heatmap composition.",
            next_action="Enable GPU01 Housing and Apply Heatmaps Settings.",
        )

    def observe_heatmap_settings_apply(self, candidate, result) -> None:
        """Verify the two GPU01 housing precedence actions after their Apply calls."""

        session = self._acceptance
        if session is None or session.failed or session.terminal_emitted:
            return
        expected = session.expected_milestone
        if expected not in {"GPU01_HOUSING_ON", "GPU01_HOUSING_OFF"}:
            return
        selected = set(candidate.isolation_selectors)
        gpu01_enabled = "gpu_01_housing" in selected
        required = expected == "GPU01_HOUSING_ON"
        if gpu01_enabled != required:
            requested = "enabled" if required else "disabled"
            self._fail(f"GPU01 Housing must be {requested} for this acceptance step.")
            return
        if not result.success or not result.enabled:
            self._fail(f"GPU01 Housing Apply failed: {result.message}")
            return
        failure = self._gpu_housing_failure_reason(candidate)
        if failure:
            self._fail(f"GPU Housing precedence failed: {failure}")
            return
        if not session.record(expected):
            self._fail("GPU Housing acceptance order was invalid.")
            return
        if expected == "GPU01_HOUSING_ON":
            self._report(
                "COMPLETE",
                "GPU01 shroud/blower is Heatmap-owned and excluded from X-Ray.",
                next_action="Disable GPU01 Housing and Apply Heatmaps Settings.",
            )
            return
        restored = self._restore_initial_settings()
        if restored is not None:
            self._fail(restored)
            return
        self._heatmap_xray_snapshot = self._controller.xray_target_snapshot()
        self._report(
            "COMPLETE",
            "GPU01 X-Ray exclusion was restored and initial settings were reapplied.",
            next_action=(
                "Press Apply in the normal X-Ray material controls without "
                "changing values."
            ),
        )

    def observe_xray_material_apply(self, result) -> None:
        """Confirm ordinary Fresnel Apply preserved Heatmap temporary ownership."""

        session = self._acceptance
        if (
            session is None
            or session.failed
            or session.terminal_emitted
            or session.expected_milestone != "XRAY_APPLY"
        ):
            return
        if not result.success:
            self._fail(f"X-Ray Apply failed: {result.message}")
            return
        before = self._heatmap_xray_snapshot
        after = self._controller.xray_target_snapshot()
        if before is None or (
            after.override_owner != before.override_owner
            or after.override_excluded_paths != before.override_excluded_paths
            or after.manual_target_ids != before.manual_target_ids
        ):
            self._fail("Ordinary X-Ray Apply changed Heatmap composition ownership.")
            return
        failure = self._heatmap_failure_reason()
        if failure:
            self._fail(f"X-Ray Apply invalidated Heatmap: {failure}")
            return
        if not session.record("XRAY_APPLY"):
            self._fail("X-Ray Apply acceptance order was invalid.")
            return
        self._report(
            "COMPLETE",
            "Ordinary X-Ray Apply preserved Heatmap ownership and exclusions.",
            next_action="Select Streamlines + X-Ray.",
        )

    def _complete_initial_heatmap(self, mode, result) -> None:
        if mode is not VisualizationMode.HEATMAP:
            self._fail(f"Expected Heatmap, got {mode.value}.")
            return
        failure = self._heatmap_failure_reason()
        if not getattr(result, "success", False) or failure:
            detail = (
                result.message if not getattr(result, "success", False) else failure
            )
            self._fail(f"Heatmap activation failed: {detail}")
            return
        session = self._acceptance
        if session is None or not session.record("HEATMAP"):
            self._fail("Heatmap acceptance order was invalid.")
            return
        self._heatmap_target_paths = (
            self._controller.heatmap_presentation_snapshot().target_paths
        )
        self._heatmap_xray_snapshot = self._controller.xray_target_snapshot()
        self._report(
            "COMPLETE",
            "Production Heatmap and its X-Ray overlay are active.",
            next_action=(
                "Inspect the Heatmap/X-Ray result. If visually correct, switch "
                "workload Nominal → Surge → Critical → Nominal."
            ),
        )

    def _complete_streamlines_xray(self, mode, result) -> None:
        if mode is not VisualizationMode.STREAMLINES_XRAY:
            self._fail(f"Expected Streamlines + X-Ray, got {mode.value}.")
            return
        failure = self._streamlines_xray_failure_reason()
        if not getattr(result, "success", False) or failure:
            detail = (
                result.message if not getattr(result, "success", False) else failure
            )
            self._fail(f"Streamlines + X-Ray transition failed: {detail}")
            return
        session = self._acceptance
        if session is None or not session.record("STREAMLINES_XRAY"):
            self._fail("Streamlines acceptance order was invalid.")
            return
        self._report(
            "COMPLETE",
            "Streamlines + X-Ray owns one presentation and one scheduler.",
            next_action="Select Heatmap.",
        )

    def _complete_restored_heatmap(self, mode, result) -> None:
        if mode is not VisualizationMode.HEATMAP:
            self._fail(f"Expected Heatmap, got {mode.value}.")
            return
        failure = self._heatmap_failure_reason()
        if not getattr(result, "success", False) or failure:
            detail = (
                result.message if not getattr(result, "success", False) else failure
            )
            self._fail(f"Heatmap return failed: {detail}")
            return
        session = self._acceptance
        if session is None or not session.record("HEATMAP_RESTORED"):
            self._fail("Heatmap return acceptance order was invalid.")
            return
        self._report("START", "Running bounded performance and repeat checks.")
        self._automation_task = asyncio.ensure_future(self._run_automatic_checks())

    async def _run_automatic_checks(self) -> None:
        try:
            await self._request_mode(VisualizationMode.NORMAL)
            normal_result = await self._measure("Normal")
            await self._request_mode(VisualizationMode.HEATMAP)
            self._require_heatmap_healthy()
            heatmap_result = await self._measure("Production Heatmap")
            full_result = await self._measure_full_server_heatmap()
            repeated_samples = await self._repeat_activation_check()
            self._restore_initial_or_raise()
            self._require_heatmap_healthy()
            self._require_no_progressive_memory_growth(repeated_samples)
            self._performance_results = (normal_result, heatmap_result, full_result)
        except asyncio.CancelledError:
            return
        except (
            Exception
        ) as error:  # noqa: BLE001 - acceptance must terminate truthfully.
            self._fail(f"Automatic Stage 10 acceptance failed: {error}")
            return
        session = self._acceptance
        if session is None or not session.complete():
            self._fail("Stage 10 acceptance milestones did not complete in order.")
            return
        self._emit_receipt()

    async def _measure_full_server_heatmap(self):
        catalog = self._controller.heatmap_catalog_snapshot()
        initial = self._initial_settings
        if catalog is None or initial is None:
            raise RuntimeError(
                "Full-server Heatmap measurement has no catalog/settings."
            )
        full_settings = replace(initial, isolation_selectors=catalog.selector_ids)
        result = self._controller.apply_heatmap_settings_in_kit(full_settings)
        if not result.success or not result.enabled:
            raise RuntimeError(f"Full-server Heatmap Apply failed: {result.message}")
        self._require_heatmap_healthy()
        result = await self._measure("Full-server Heatmap")
        self._restore_initial_or_raise()
        return result

    async def _repeat_activation_check(self):
        samples = []
        for _index in range(3):
            await self._request_mode(VisualizationMode.NORMAL)
            await self._request_mode(VisualizationMode.HEATMAP)
            self._require_heatmap_healthy()
            samples.append(
                (
                    self._resource_identity(),
                    capture_viewport_performance_sample(),
                )
            )
        if len({identity for identity, _sample in samples}) != 1:
            raise RuntimeError(
                "Repeated activation retained different runtime ownership."
            )
        return tuple(sample for _identity, sample in samples)

    async def _request_mode(self, mode: VisualizationMode) -> None:
        result = await self._controller.request_visualization_mode_in_kit(mode)
        if not result.success or result.committed_mode is not mode:
            raise RuntimeError(f"{mode.value} transition failed: {result.message}")
        if mode is VisualizationMode.NORMAL:
            primary = (
                self._controller.primary_visualization_presentation_snapshot_in_kit()
            )
            if primary.normal_failure_reason() is not None:
                raise RuntimeError(primary.normal_failure_reason())

    async def _measure(self, label: str):
        result = await self._performance_probe.run(label=label)
        if not result.completed or result.cancelled:
            raise RuntimeError(f"{label} performance sample did not complete.")
        return result

    def _restore_initial_or_raise(self) -> None:
        reason = self._restore_initial_settings()
        if reason is not None:
            raise RuntimeError(reason)

    def _restore_initial_settings(self) -> str | None:
        initial = self._initial_settings
        if initial is None:
            return "Initial Heatmap settings are unavailable."
        result = self._controller.apply_heatmap_settings_in_kit(initial)
        if not result.success or not result.enabled:
            return f"Initial Heatmap settings restore failed: {result.message}"
        if self._controller.heatmap_applied_settings_snapshot() != initial:
            return "Initial Heatmap settings did not restore exactly."
        return None

    def _start_ready(self) -> bool:
        catalog = self._controller.heatmap_catalog_snapshot()
        visualization = self._controller.visualization_snapshot()
        try:
            settings = self._controller.heatmap_applied_settings_snapshot()
            settings.validate()
        except ValueError:
            return False
        return bool(
            catalog
            and catalog.ready
            and visualization.committed is VisualizationMode.NORMAL
            and visualization.pending is None
            and not self._controller.heatmap_test_active()
            and not self._controller.heatmap_production_active()
        )

    def _heatmap_failure_reason(self) -> str | None:
        visualization = self._controller.visualization_snapshot()
        primary = self._controller.primary_visualization_presentation_snapshot_in_kit()
        heatmap = self._controller.heatmap_presentation_snapshot()
        xray = self._controller.xray_target_snapshot()
        if (
            visualization.committed is not VisualizationMode.HEATMAP
            or visualization.pending
        ):
            return "VisualizationMode is not committed Heatmap."
        if not heatmap.production_active or heatmap.debug_active:
            return "Heatmap production ownership is invalid."
        diagnostics = heatmap.diagnostics
        if (
            not diagnostics.active
            or diagnostics.scheduler_tasks != 1
            or not diagnostics.dynamic_transport_active
            or not diagnostics.last_dynamic_update_success
            or diagnostics.unavailable_material_groups
        ):
            return "Heatmap dynamic presentation health is invalid."
        if (
            primary.smoke_presentation_visible
            or primary.streamlines_presentation_visible
            or primary.streamlines_scheduler_tasks
        ):
            return "Another primary presentation remains active."
        if xray.override_owner != _HEATMAP_XRAY_OWNER:
            return "Heatmap X-Ray override owner is missing."
        if (
            self._heatmap_target_paths
            and heatmap.target_paths != self._heatmap_target_paths
        ):
            return "Heatmap target topology changed."
        return None

    def _streamlines_xray_failure_reason(self) -> str | None:
        visualization = self._controller.visualization_snapshot()
        primary = self._controller.primary_visualization_presentation_snapshot_in_kit()
        xray = self._controller.xray_target_snapshot()
        if (
            visualization.committed is not VisualizationMode.STREAMLINES_XRAY
            or visualization.pending
        ):
            return "VisualizationMode is not committed Streamlines + X-Ray."
        if (
            primary.smoke_presentation_visible
            or primary.heatmap_presentation_active
            or not primary.streamlines_presentation_visible
            or primary.streamlines_scheduler_tasks != 1
        ):
            return "Primary presentation ownership is invalid."
        if xray.override_owner != _STREAMLINES_XRAY_OWNER:
            return "Streamlines X-Ray override owner is missing."
        return None

    def _gpu_housing_failure_reason(self, settings) -> str | None:
        catalog = self._controller.heatmap_catalog_snapshot()
        if catalog is None:
            return "Heatmap catalog is unavailable."
        composition = build_heatmap_composition_plan(
            settings,
            catalog,
            self._controller.heatmap_xray_overlay_groups_snapshot(),
        )
        heatmap = self._controller.heatmap_presentation_snapshot()
        xray = self._controller.xray_target_snapshot()
        if heatmap.target_paths != composition.heatmap_target_paths:
            return "Heatmap target topology does not match the prepared plan."
        if xray.override_excluded_paths != frozenset(composition.xray_excluded_paths):
            return "X-Ray exclusions do not match the prepared plan."
        selected = set(settings.isolation_selectors)
        for gpu_index in (1, 2, 3):
            roots = self._gpu_shroud_blower_roots(gpu_index)
            expected = gpu_index in {
                int(item.removeprefix("gpu_0").removesuffix("_housing"))
                for item in selected
                if item.startswith("gpu_0") and item.endswith("_housing")
            }
            if bool(set(roots) & set(composition.xray_excluded_paths)) != expected:
                return f"GPU{gpu_index:02d} shroud/blower precedence is incorrect."
        unrelated = self._unrelated_gpu_shroud_paths()
        if set(unrelated) & set(composition.xray_excluded_paths):
            return "GPU power, IO, or cable paths were excluded from X-Ray."
        return self._heatmap_failure_reason()

    def _gpu_shroud_blower_roots(self, gpu_index: int) -> tuple[str, ...]:
        needle = f"/gpu_{gpu_index:02d}/"
        return tuple(
            path
            for group in self._controller.heatmap_xray_overlay_groups_snapshot()
            if group.group_id == "gpu_shrouds"
            for path in group.paths
            if needle in path and path.endswith(("/shroud", "/blower"))
        )

    def _unrelated_gpu_shroud_paths(self) -> tuple[str, ...]:
        return tuple(
            path
            for group in self._controller.heatmap_xray_overlay_groups_snapshot()
            if group.group_id == "gpu_shrouds"
            for path in group.paths
            if path.endswith(("/power", "/io/ports")) or "cables_gpu_" in path
        )

    def _require_heatmap_healthy(self) -> None:
        failure = self._heatmap_failure_reason()
        if failure:
            raise RuntimeError(failure)

    def _resource_identity(self):
        heatmap = self._controller.heatmap_presentation_snapshot()
        xray = self._controller.xray_target_snapshot()
        return (
            heatmap.target_paths,
            heatmap.diagnostics.material_group_count,
            heatmap.diagnostics.scheduler_tasks,
            heatmap.diagnostics.dynamic_transport_active,
            xray.override_owner,
            xray.override_target_ids,
            xray.override_excluded_paths,
        )

    @staticmethod
    def _require_no_progressive_memory_growth(samples) -> None:
        for attribute in ("gpu_memory_used_gib", "process_memory_used_gib"):
            values = [getattr(sample, attribute) for sample in samples]
            observed = [value for value in values if value is not None]
            if len(observed) == len(samples) and all(
                earlier < later for earlier, later in zip(observed, observed[1:])
            ):
                raise RuntimeError(f"{attribute} grew on every repeated activation.")

    def _fail(self, reason: str) -> None:
        session = self._acceptance
        if session is None or session.terminal_emitted:
            return
        session.mark_failed()
        self._emit(
            "\n".join(
                (
                    "DTRS STAGE 10 | ACCEPTANCE | TEST COMPLETE",
                    "TEST COMPLETE",
                    "FAIL",
                    f"reason={reason}",
                )
            )
        )

    def _report(
        self,
        event: str,
        status: str,
        *,
        next_action: str | None = None,
    ) -> None:
        self._emit(
            format_manual_acceptance_event(
                area="STAGE 10 | ACCEPTANCE",
                event=event,
                status=status,
                next_action=next_action,
            )
        )

    def _emit_receipt(self) -> None:
        self._emit(
            "\n".join(
                (
                    "DTRS STAGE 10 | ACCEPTANCE | TEST COMPLETE",
                    "TEST COMPLETE",
                    "PASS",
                    "thermal_presentation=PASS",
                    "workload_round_trip=PASS",
                    "gpu_housing_precedence=PASS",
                    "xray_apply_preservation=PASS",
                    "heatmap_streamlines_round_trip=PASS",
                    "performance=PASS",
                    "repeated_activation=PASS",
                )
            )
        )

    def _emit(self, content: str) -> None:
        self._log_warning(
            format_dtrs_status_block(
                content,
                append_local_timestamp=self._append_local_timestamp,
            )
        )
