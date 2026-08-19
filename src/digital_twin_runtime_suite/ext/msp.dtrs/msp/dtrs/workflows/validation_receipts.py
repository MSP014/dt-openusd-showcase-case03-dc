"""Bounded validation-receipt work and its guided acceptance sequence."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

from digital_twin_runtime_suite.app.manual_acceptance import (
    GuidedAcceptanceSession,
    format_manual_acceptance_event,
    format_manual_acceptance_test_complete,
)
from digital_twin_runtime_suite.app.visualization_mode import VisualizationMode


class ValidationReceiptWorkflow:
    """Own validation tasks and receipt-reuse acceptance, not Kit UI state.

    The workflow starts bounded validation work and observes only real product
    visualization requests.  It receives tiny UI/log callbacks so neither the
    workflow nor the receipt acceptance state needs an OmniUI dependency.
    """

    def __init__(
        self,
        controller,
        *,
        current_workload: Callable[[], str | None],
        normal_selected: Callable[[], bool],
        log_warning: Callable[[str], None],
        log_error: Callable[[str], None],
        include_airflow_diagnostics: bool,
    ) -> None:
        self._controller = controller
        self._current_workload = current_workload
        self._normal_selected = normal_selected
        self._log_warning = log_warning
        self._log_error = log_error
        self._include_airflow_diagnostics = include_airflow_diagnostics
        self._airflow_background_validation_task = None
        self._streamlines_cache_validation_task = None
        self._streamlines_cache_validation_workload = None
        self._streamlines_receipt_sweep_task = None
        self._summary_task = None
        self._acceptance_task = None
        self._acceptance = None
        self._checkpoint = None
        self._acceptance_owns_actions = False
        self._user_requested_mode = None

    @property
    def checkpoint(self):
        """Return the persisted restart checkpoint without exposing mutation."""

        return self._checkpoint

    @property
    def acceptance_owns_actions(self) -> bool:
        """Report whether temporary receipt guidance owns the next user action."""

        return self._acceptance_owns_actions

    def load_checkpoint(self) -> None:
        """Load one persisted checkpoint before startup work is scheduled."""

        self._checkpoint = (
            self._controller.load_validation_receipt_acceptance_checkpoint()
        )

    def initialize_acceptance(self) -> None:
        """Resume Session 2 or expose the opt-in Session 1 instruction."""

        if self._checkpoint is not None:
            self._acceptance_owns_actions = True
            self._acceptance_task = asyncio.ensure_future(
                self.run_acceptance_session2()
            )
            return
        self._acceptance = GuidedAcceptanceSession(("SESSION_1",))
        self._acceptance.begin()
        preferences = self._controller.config.validation_receipts
        if (
            preferences.reuse_verified_vti_receipts
            and preferences.reuse_verified_streamlines_cache_receipts
        ):
            return
        self._acceptance_owns_actions = True
        self._report(
            "READY",
            "View validation-reuse settings are available.",
            next_action=(
                'Enable "Reuse verified VTI receipts" and '
                '"Reuse verified Streamlines cache receipts".'
            ),
        )

    def save_reuse_settings(
        self,
        *,
        reuse_vti: bool,
        reuse_streamlines: bool,
    ):
        """Persist receipt preferences and start only the required bounded work."""

        path = self._controller.save_validation_receipt_reuse_override(
            reuse_verified_vti_receipts=reuse_vti,
            reuse_verified_streamlines_cache_receipts=reuse_streamlines,
        )
        if reuse_vti and reuse_streamlines:
            self.begin_acceptance_session1()
        elif reuse_streamlines:
            self.start_background_work()
        return path

    def begin_acceptance_session1(self) -> None:
        """Persist controlled evidence after both receipt-reuse settings are saved."""

        task = self._acceptance_task
        if task is not None and not task.done():
            return
        self._acceptance_owns_actions = True
        self._report(
            "START",
            "Establishing persisted validation receipts for VTI datasets and "
            "Streamlines caches.",
        )
        self.start_background_work()
        self._acceptance_task = asyncio.ensure_future(self.run_acceptance_session1())

    def schedule_current_streamlines_cache_validation(self) -> None:
        """Schedule one cache receipt when the telemetry workload changes."""

        workload = self._current_workload()
        if workload is None:
            return
        task = self._streamlines_cache_validation_task
        if (
            workload == self._streamlines_cache_validation_workload
            and task is not None
            and not task.done()
        ):
            return
        self._streamlines_cache_validation_workload = workload
        self._streamlines_cache_validation_task = asyncio.ensure_future(
            self._run_current_streamlines_cache_validation()
        )

    def start_background_work(self) -> None:
        """Start bounded validation work; never create a permanent poller."""

        if self._include_airflow_diagnostics:
            task = self._airflow_background_validation_task
            if task is None or task.done():
                self._start_background_airflow_validation()
        task = self._streamlines_receipt_sweep_task
        if task is None or task.done():
            self._streamlines_receipt_sweep_task = asyncio.ensure_future(
                self._run_streamlines_receipt_sweep()
            )
        task = self._summary_task
        if task is None or task.done():
            self._summary_task = asyncio.ensure_future(self.report_startup_summary())

    def begin_consumer_action(self, mode: VisualizationMode) -> None:
        """Start guidance only for the explicitly selected production mode."""

        session = self._acceptance
        if (
            session is None
            or session.failed
            or session.terminal_emitted
            or session.expected_milestone not in {"Smoke", "Normal"}
        ):
            return
        if session.expected_milestone != mode.value:
            self._fail(
                "Unexpected Visualization selection: expected "
                f"{session.expected_milestone}, got {mode.value}."
            )
            return
        self._user_requested_mode = mode
        status = (
            "Verifying persisted VTI receipt through the production Flow consumer."
            if mode.value == "Smoke"
            else "Verifying return to clean Normal visualization state."
        )
        self._report("START", status)

    def complete_consumer_action(self, mode: VisualizationMode, result) -> None:
        """Record one completed product transition against the active session."""

        if self._user_requested_mode is not mode:
            return
        self._user_requested_mode = None
        session = self._acceptance
        if session is None or session.failed or session.terminal_emitted:
            return
        if mode.value == "Smoke":
            failures = self._smoke_failures(result)
            completion = (
                "Persisted VTI receipt accepted by the production Flow consumer. "
                "persisted_receipt_consumer_check=PASS; "
                "KitCAE_grid_contract=PASS."
            )
            next_action = 'Select "Normal" in "Visualization".'
        else:
            failures = self._normal_failures(result)
            completion = (
                "Production visualization returned to Normal; Flow and "
                "Streamlines are clean."
            )
            next_action = None
        if failures:
            self._fail("; ".join(failures) + ".")
            return
        if not session.record(mode.value):
            self._fail("Receipt acceptance action could not be recorded in order.")
            return
        self._report("COMPLETE", completion, next_action=next_action)
        if next_action is not None or not session.complete():
            return
        self._log_warning(
            format_manual_acceptance_test_complete(
                "Persisted VTI and Streamlines validation receipt reuse passed."
            )
        )
        self._controller.clear_validation_receipt_acceptance_checkpoint()
        self._checkpoint = None
        self._acceptance_owns_actions = False

    async def run_acceptance_session1(self) -> None:
        """Persist four VTI and four Streamlines receipts, then request restart."""

        if not await self._wait_for_validation_tasks("SESSION_1"):
            return
        try:
            identities = await asyncio.to_thread(
                self._controller.validation_receipt_identity_snapshot
            )
            coverage = self._controller.validation_receipt_coverage_snapshot(identities)
        except Exception as error:
            self._fail(str(error))
            return
        preferences = self._controller.config.validation_receipts
        if not (
            preferences.reuse_verified_vti_receipts
            and preferences.reuse_verified_streamlines_cache_receipts
        ):
            self._fail("Receipt reuse settings were not persisted.")
            return
        if coverage["vti_total"] != 4 or coverage["vti_valid"] != 4:
            self._fail("Not all configured VTI preflight receipts were persisted.")
            return
        if coverage["streamlines_total"] != 4 or coverage["streamlines_valid"] != 4:
            self._fail("Not all configured Streamlines VALID receipts were persisted.")
            return
        self._controller.write_validation_receipt_acceptance_checkpoint(
            {"phase": "AWAITING_RESTART", "baseline_identities": identities}
        )
        session = self._acceptance
        if session is None or not session.record("SESSION_1"):
            return
        self._report(
            "COMPLETE",
            "Persisted validation baseline established. "
            f"VTI persisted_receipts={coverage['vti_valid']}/"
            f"{coverage['vti_total']}; Streamlines persisted_receipts="
            f"{coverage['streamlines_valid']}/{coverage['streamlines_total']}; "
            "settings_persisted=True.",
            next_action=(
                "Restart DTRS without changing VTI datasets, Streamlines caches, "
                "or validation settings."
            ),
        )

    async def run_acceptance_session2(self) -> None:
        """Prove cheap reuse, then wait for explicit production UI actions."""

        self._acceptance = GuidedAcceptanceSession(("RESTORED", "Smoke", "Normal"))
        self._acceptance.begin()
        try:
            identities = await asyncio.to_thread(
                self._controller.validation_receipt_identity_snapshot
            )
        except Exception as error:
            self._fail(str(error))
            return
        baseline = (self._checkpoint or {}).get("baseline_identities")
        if identities != baseline:
            self._fail(
                "Acceptance input changed between sessions; persisted-reuse "
                "proof is no longer a controlled comparison."
            )
            return
        preferences = self._controller.config.validation_receipts
        if not (
            preferences.reuse_verified_vti_receipts
            and preferences.reuse_verified_streamlines_cache_receipts
        ):
            self._fail("Receipt reuse settings did not survive restart.")
            return
        coverage_before = self._controller.validation_receipt_coverage_snapshot(
            identities
        )
        if (
            coverage_before["vti_total"] != 4
            or coverage_before["vti_valid"] != 4
            or coverage_before["streamlines_total"] != 4
            or coverage_before["streamlines_valid"] != 4
        ):
            self._fail(
                "Persisted receipt store does not cover the four controlled VTI "
                "datasets and Streamlines caches."
            )
            return
        failures = self._normal_failures()
        if failures:
            self._fail(
                "Session 2 did not start in clean Normal state: "
                + "; ".join(failures)
                + "."
            )
            return
        self._report(
            "READY",
            "Persisted receipt store and controlled resource identities match.",
            next_action="Wait for persisted receipt reuse verification.",
        )
        self._report(
            "START",
            "Verifying persisted receipt reuse without expensive validators.",
        )
        self.start_background_work()
        if not await self._wait_for_validation_tasks("SESSION_2"):
            return
        coverage = self._controller.validation_receipt_coverage_snapshot(identities)
        metrics = self._controller.validation_receipt_metrics_snapshot()
        failures = []
        if coverage["vti_valid"] != 4 or metrics.vti.persisted_reused != 4:
            failures.append("VTI persisted reuse was not 4/4")
        if metrics.vti.fresh_validated or metrics.vti.expensive_validation_calls:
            failures.append("an expensive VTI preflight ran unexpectedly")
        if (
            coverage["streamlines_valid"] != 4
            or metrics.streamlines.persisted_reused != 4
        ):
            failures.append("Streamlines persisted reuse was not 4/4")
        if (
            metrics.streamlines.fresh_validated
            or metrics.streamlines.expensive_validation_calls
            or metrics.streamlines.geometry_sha256_recomputed
        ):
            failures.append("Streamlines strong validation ran unexpectedly")
        if metrics.vti.invalidated or metrics.streamlines.invalidated:
            failures.append("a controlled resource identity was invalidated")
        if failures:
            self._fail("; ".join(failures) + ".")
            return
        session = self._acceptance
        if session is None or not session.record("RESTORED"):
            return
        self._report(
            "COMPLETE",
            "Persisted receipts restored through the cheap path. "
            "VTI persisted_reused=4/4; fresh_validated=0; invalidated=0; "
            "expensive_preflight_calls=0; Streamlines persisted_reused=4/4; "
            "fresh_validated=0; invalidated=0; geometry_sha256_recomputed=0; "
            "strong_validation_calls=0.",
            next_action=(
                'Select "Smoke" in "Visualization" to verify the persisted VTI '
                "receipt through the production Flow consumer."
            ),
        )

    async def report_startup_summary(self) -> None:
        """Emit one compact metrics summary after bounded startup work settles."""

        tasks = tuple(
            task
            for task in (
                self._airflow_background_validation_task,
                self._streamlines_receipt_sweep_task,
                self._streamlines_cache_validation_task,
            )
            if task is not None
        )
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        metrics = self._controller.validation_receipt_metrics_snapshot()
        self._log_warning(
            "\n".join(
                (
                    "DTRS VALIDATION RECEIPTS | STARTUP SUMMARY",
                    "VTI:",
                    f"  persisted_reused={metrics.vti.persisted_reused}",
                    f"  session_reused={metrics.vti.session_reused}",
                    f"  fresh_validated={metrics.vti.fresh_validated}",
                    f"  invalidated={metrics.vti.invalidated}",
                    "Streamlines:",
                    "  persisted_reused=" f"{metrics.streamlines.persisted_reused}",
                    f"  session_reused={metrics.streamlines.session_reused}",
                    f"  fresh_validated={metrics.streamlines.fresh_validated}",
                    f"  invalidated={metrics.streamlines.invalidated}",
                )
            )
        )

    def cancel(self) -> None:
        """Cancel only workflow-owned tasks during extension teardown."""

        for name in (
            "_airflow_background_validation_task",
            "_streamlines_cache_validation_task",
            "_streamlines_receipt_sweep_task",
            "_summary_task",
            "_acceptance_task",
        ):
            task = getattr(self, name)
            if task is not None:
                task.cancel()
            setattr(self, name, None)
        self._controller.stop_background_airflow_validation()

    def _start_background_airflow_validation(self) -> None:
        try:
            self._controller.start_background_airflow_validation()
        except Exception as error:
            self._log_error(
                "DTRS AIRFLOW BACKGROUND VALIDATION | START FAILED | " f"{error}"
            )
            return
        self._airflow_background_validation_task = asyncio.ensure_future(
            self._run_background_airflow_validation()
        )

    async def _run_background_airflow_validation(self) -> None:
        try:
            await self._controller.run_background_airflow_validation(self._log_warning)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._log_error(
                "DTRS AIRFLOW BACKGROUND VALIDATION | ABORTED | " f"{error}"
            )

    async def _run_current_streamlines_cache_validation(self) -> None:
        try:
            ensure_current_validation = getattr(
                self._controller,
                "ensure_current_streamlines_cache_validation_in_background",
            )
            await ensure_current_validation()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._log_warning(
                "DTRS STREAMLINES | CACHE_VALIDATION | FAILED | " f"{error}"
            )

    async def _run_streamlines_receipt_sweep(self):
        def status(message: str) -> None:
            self._log_warning("DTRS VALIDATION RECEIPTS | PROGRESS | " + message)

        try:
            ensure_configured_validations = getattr(
                self._controller,
                "ensure_configured_streamlines_cache_validations_in_background",
            )
            return await ensure_configured_validations(status_callback=status)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._log_error(
                "DTRS VALIDATION RECEIPTS | STREAMLINES | FAIL | " f"reason={error}"
            )
            return ()

    def _smoke_failures(self, result) -> list[str]:
        consumer = self._controller.vti_receipt_consumer_check_snapshot()
        metrics = self._controller.validation_receipt_metrics_snapshot()
        snapshot = self._controller.visualization_snapshot()
        failures = []
        if not result.success:
            failures.append(f"real Smoke Attach failed: {result.message}")
        if snapshot.committed.value != "Smoke" or snapshot.pending is not None:
            failures.append("Smoke was not committed cleanly")
        if consumer.receipt_source != "PERSISTED":
            failures.append("Nominal Flow consumer did not use PERSISTED evidence")
        if consumer.selector != "server/load_normal":
            failures.append("consumer check did not attach the Nominal VTI dataset")
        if not consumer.kit_cae_grid_contract_passed:
            failures.append("Kit-CAE imported grid contract failed")
        if not consumer.flow_initial_readiness_passed:
            failures.append("Flow initial readiness failed")
        if metrics.vti.expensive_validation_calls:
            failures.append("consumer check unexpectedly ran expensive VTI preflight")
        return failures

    def _normal_failures(self, result=None) -> list[str]:
        snapshot = self._controller.visualization_snapshot()
        presentation = (
            self._controller.primary_visualization_presentation_snapshot_in_kit()
        )
        xray = self._controller.xray_target_snapshot()
        failures = []
        if result is not None and not result.success:
            failures.append(f"Normal transition failed: {result.message}")
        if snapshot.committed is not VisualizationMode.NORMAL or snapshot.pending:
            failures.append("Normal was not committed cleanly")
        if self._controller.flow_lifecycle_state() != "DETACHED":
            failures.append("Flow lifecycle is not detached")
        if presentation.flow_source_prepared:
            failures.append("Flow source remains prepared")
        if presentation.smoke_presentation_visible:
            failures.append("Smoke renderer remains active")
        if presentation.streamlines_presentation_visible:
            failures.append("Streamlines presentation remains active")
        if presentation.streamlines_scheduler_tasks:
            failures.append("Streamlines scheduler remains active")
        if xray.override_owner is not None:
            failures.append("a visualization-owned X-Ray override remains active")
        if not self._normal_selected():
            failures.append("Visualization ComboBox does not display Normal")
        return failures

    async def _wait_for_validation_tasks(self, session_name: str) -> bool:
        started_at = time.monotonic()
        next_waiting_at = started_at + 5.0
        while True:
            tasks = tuple(
                task
                for task in (
                    self._airflow_background_validation_task,
                    self._streamlines_receipt_sweep_task,
                )
                if task is not None and not task.done()
            )
            if not tasks:
                return True
            now = time.monotonic()
            if now >= next_waiting_at:
                self._report(
                    "WAITING",
                    f"{session_name} validation remains active; "
                    f"elapsed_s={now - started_at:.1f}.",
                )
                next_waiting_at = now + 5.0
            await asyncio.sleep(0.1)

    def _fail(self, reason: str) -> None:
        session = self._acceptance
        if session is not None:
            session.mark_failed()
        self._report("FAIL", reason)
        self._acceptance_owns_actions = False

    def _report(
        self,
        event: str,
        status: str,
        next_action: str | None = None,
    ) -> None:
        self._log_warning(
            format_manual_acceptance_event(
                area="VALIDATION RECEIPTS | ACCEPTANCE",
                event=event,
                status=status,
                next_action=next_action,
            )
        )
