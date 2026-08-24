# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""Bounded validation-receipt work and its guided acceptance sequence."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from digital_twin_runtime_suite.app.manual_acceptance import (
    GuidedAcceptanceSession,
    format_manual_acceptance_event,
    format_manual_acceptance_test_complete,
)
from digital_twin_runtime_suite.app.observability import (
    ProgressReporter,
    ProgressState,
)
from digital_twin_runtime_suite.app.status_log import (
    format_dtrs_diagnostic_content,
    format_dtrs_status_block,
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
        append_local_timestamp: Callable[[str], str],
        log_error: Callable[[str], None],
        include_airflow_diagnostics: bool,
        progress_reporter: ProgressReporter | None = None,
        guided_actions_allowed: Callable[[], bool] = lambda: True,
    ) -> None:
        self._controller = controller
        self._current_workload = current_workload
        self._normal_selected = normal_selected
        self._log_warning = log_warning
        self._append_local_timestamp = append_local_timestamp
        self._log_error = log_error
        self._include_airflow_diagnostics = include_airflow_diagnostics
        self._progress_reporter = progress_reporter
        self._guided_actions_allowed = guided_actions_allowed
        self._airflow_background_validation_task = None
        self._streamlines_cache_validation_task = None
        self._streamlines_cache_validation_workload = None
        self._streamlines_receipt_sweep_task = None
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

        preferences = self._controller.config.validation_receipts
        if self._checkpoint is not None and not (
            preferences.reuse_verified_vti_receipts
            and preferences.reuse_verified_streamlines_cache_receipts
        ):
            # Reuse was explicitly disabled after Session 1.  Its controlled
            # restart proof cannot apply to a fresh-validation startup.
            self._reset_acceptance_for_fresh_validation()
        if not self._guided_actions_allowed():
            return
        if self._checkpoint is not None:
            self._acceptance_owns_actions = True
            self._acceptance_task = asyncio.ensure_future(
                self.run_acceptance_session2()
            )
            return
        self._acceptance = GuidedAcceptanceSession(("SESSION_1",))
        self._acceptance.begin()
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
        else:
            self._reset_acceptance_for_fresh_validation()
            self.start_background_work()
        return path

    def _reset_acceptance_for_fresh_validation(self) -> None:
        """Discard only stale restart guidance, retaining reusable receipts."""

        task = self._acceptance_task
        if task is not None and not task.done():
            task.cancel()
        self._acceptance_task = None
        self._controller.clear_validation_receipt_acceptance_checkpoint()
        self._checkpoint = None
        self._acceptance = None
        self._acceptance_owns_actions = False

    def begin_acceptance_session1(self) -> None:
        """Persist controlled evidence after both receipt-reuse settings are saved."""

        if not self._guided_actions_allowed():
            return
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

    def invalidate_streamlines_receipts_after_cache_rebuild(self) -> None:
        """Discard cache receipts whose resources were replaced by a build.

        This is invoked only after the cache-set action successfully rebuilt at
        least one target.  VTI receipts remain valid: their source datasets did
        not change.
        """

        self._reset_streamlines_receipt_sweep()
        self._reset_acceptance_for_fresh_validation()
        preferences = self._controller.config.validation_receipts
        if (
            preferences.reuse_verified_vti_receipts
            and preferences.reuse_verified_streamlines_cache_receipts
        ):
            self.begin_acceptance_session1()
            return
        self.start_background_work()

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

    def _reset_streamlines_receipt_sweep(self) -> None:
        """Cancel stale workflow work before resetting controller receipts."""

        for name in (
            "_streamlines_cache_validation_task",
            "_streamlines_receipt_sweep_task",
        ):
            task = getattr(self, name)
            if task is not None and not task.done():
                task.cancel()
            setattr(self, name, None)
        self._streamlines_cache_validation_workload = None
        self._controller.reset_streamlines_cache_validation_receipts()

    def begin_consumer_action(self, mode: VisualizationMode) -> None:
        """Start guidance only for the explicitly selected production mode."""

        if not self._guided_actions_allowed():
            return
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

        if not self._guided_actions_allowed():
            return
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
        self._emit_status_block(
            format_manual_acceptance_test_complete(
                "Persisted VTI and Streamlines validation receipt reuse passed."
            )
        )
        self._controller.clear_validation_receipt_acceptance_checkpoint()
        self._checkpoint = None
        self._acceptance_owns_actions = False

    async def run_acceptance_session1(self) -> None:
        """Persist four VTI and eight Streamlines receipts, then request restart."""

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
        if coverage["streamlines_total"] != 8 or coverage["streamlines_valid"] != 8:
            missing = coverage.get("streamlines_missing_or_mismatched", ())
            detail = ", ".join(missing) if missing else "unknown owner"
            self._fail(
                "Streamlines persisted receipts incomplete: "
                f"valid={coverage['streamlines_valid']}/"
                f"{coverage['streamlines_total']}; missing_or_mismatched={detail}."
            )
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
            or coverage_before["streamlines_total"] != 8
            or coverage_before["streamlines_valid"] != 8
        ):
            self._fail(
                "Persisted receipt store does not cover the four VTI datasets and "
                "eight Streamlines profile caches."
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
            coverage["streamlines_valid"] != 8
            or metrics.streamlines.persisted_reused != 8
        ):
            failures.append("Streamlines persisted reuse was not 8/8")
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
            "expensive_preflight_calls=0; Streamlines persisted_reused=8/8; "
            "fresh_validated=0; invalidated=0; geometry_sha256_recomputed=0; "
            "strong_validation_calls=0.",
            next_action=(
                'Select "Smoke" in "Visualization" to verify the persisted VTI '
                "receipt through the production Flow consumer."
            ),
        )

    def cancel(self) -> None:
        """Cancel only workflow-owned tasks during extension teardown."""

        for name in (
            "_airflow_background_validation_task",
            "_streamlines_cache_validation_task",
            "_streamlines_receipt_sweep_task",
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
        loop = asyncio.get_running_loop()

        def progress(
            selector: str,
            completed: int,
            total: int,
            filename: str,
        ) -> None:
            loop.call_soon_threadsafe(
                self._report_airflow_preflight_progress,
                selector,
                completed,
                total,
                filename,
            )

        try:
            await self._controller.run_background_airflow_validation(
                self._report_airflow_validation_event,
                progress_callback=progress,
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._log_error(
                "DTRS AIRFLOW BACKGROUND VALIDATION | ABORTED | " f"{error}"
            )
        finally:
            self._finish_live_progress()

    def _report_airflow_validation_event(self, content: str) -> None:
        """Keep only VTI lifecycle boundaries and abnormal diagnostics in history."""

        if "process=DATASET PREFLIGHT | state=START" in content:
            self._emit_status_block(content)
            return
        if "process=DATASET PREFLIGHT | state=COMPLETE" in content:
            self._emit_status_block(content)
            return
        if any(
            state in content
            for state in (
                "state=FAILED",
                "state=TERMINAL FAILURE",
                "state=REQUEUED",
            )
        ):
            self._emit_status_block(content)
            return
        if "DTRS AIRFLOW DATASET FAMILY" in content and "state=PASS" not in content:
            self._emit_status_block(content)

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
        total = len(
            self._controller.streamlines_production_cache_matrix_readiness_snapshot()
        )
        completed = 0
        classifications: list[str] = []
        receipt_sources: list[str] = []
        self._emit_status_block(
            format_dtrs_diagnostic_content(
                owner="STREAMLINES CACHE VALIDATION",
                process="PERSISTED CACHE RECEIPTS",
                state="START",
                details={"cache_count": total},
            )
        )

        def status(message: str) -> None:
            nonlocal completed
            details = self._streamlines_receipt_details(message)
            classification = details.get("status")
            workload = details.get("workload", "unknown")
            profile = details.get("profile", "unknown")
            if classification != "CHECKING":
                completed += 1
                classifications.append(classification or "UNKNOWN")
                receipt_sources.append(details.get("receipt_source", "NONE"))
            self._report_streamlines_receipt_progress(
                workload=workload,
                profile=profile,
                classification=classification or "UNKNOWN",
                completed=completed,
                total=total,
            )
            if classification not in {"CHECKING", "VALID"}:
                self._emit_status_block(
                    format_dtrs_diagnostic_content(
                        owner="STREAMLINES CACHE VALIDATION",
                        process="PERSISTED CACHE RECEIPTS",
                        state="WARNING",
                        details=details,
                    )
                )

        try:
            ensure_configured_validations = getattr(
                self._controller,
                "ensure_configured_streamlines_cache_validations_in_background",
            )
            receipts = await ensure_configured_validations(status_callback=status)
            valid = sum(classification == "VALID" for classification in classifications)
            fresh = sum(source == "FRESH" for source in receipt_sources)
            reused = sum(source != "FRESH" for source in receipt_sources)
            self._emit_status_block(
                format_dtrs_diagnostic_content(
                    owner="STREAMLINES CACHE VALIDATION",
                    process="PERSISTED CACHE RECEIPTS",
                    state="COMPLETE",
                    details={
                        "caches_valid": f"{valid}/{len(receipts)}",
                        "fresh_validated": fresh,
                        "reused": reused,
                    },
                )
            )
            return receipts
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._log_error(
                "DTRS VALIDATION RECEIPTS | STREAMLINES | FAIL | " f"reason={error}"
            )
            return ()
        finally:
            self._finish_live_progress()

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
        """Wait for bounded work without turning unchanged state into log spam."""

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
        if not self._guided_actions_allowed():
            return
        self._emit_status_block(
            format_manual_acceptance_event(
                area="VALIDATION RECEIPTS | ACCEPTANCE",
                event=event,
                status=status,
                next_action=next_action,
            )
        )

    def _emit_status_block(self, content: str) -> None:
        """Isolate user guidance and multi-line summaries from startup diagnostics."""

        self._log_warning(
            format_dtrs_status_block(
                content,
                append_local_timestamp=self._append_local_timestamp,
            )
        )

    @staticmethod
    def _streamlines_receipt_details(message: str) -> dict[str, str]:
        """Read the existing cache callback without making cache code UI-aware."""

        details = {}
        prefix = "Streamlines receipt: "
        if message.startswith(prefix):
            for field in message.removeprefix(prefix).split("; "):
                name, separator, value = field.partition("=")
                if separator:
                    details[name] = value
        if not details:
            details["message"] = message
        return details

    def _report_airflow_preflight_progress(
        self,
        selector: str,
        completed: int,
        total: int,
        filename: str,
    ) -> None:
        """Publish per-file VTI preflight state without creating log history."""

        reporter = self._progress_reporter
        if reporter is None:
            return
        fraction = completed / total if total else None
        reporter.progress(
            ProgressState(
                operation_id="Airflow VTI validation",
                phase="DATASET PREFLIGHT",
                message="Reading VTI metadata.",
                fraction=fraction,
                current=completed,
                total=total,
                metadata={
                    "terminal_context": f"{selector} | {filename}",
                    "dataset": selector,
                    "filename": filename,
                },
            )
        )

    def _report_streamlines_receipt_progress(
        self,
        *,
        workload: str,
        profile: str,
        classification: str,
        completed: int,
        total: int,
    ) -> None:
        """Publish cache-set state while retaining only terminal diagnostics."""

        reporter = self._progress_reporter
        if reporter is None:
            return
        fraction = completed / total if total else None
        reporter.progress(
            ProgressState(
                operation_id="Streamlines cache validation",
                phase="CACHE VALIDATION",
                message=f"{classification}: {workload} / {profile}",
                fraction=fraction,
                current=completed,
                total=total,
                metadata={
                    "terminal_context": f"{workload} / {profile}",
                    "workload": workload,
                    "profile": profile,
                    "classification": classification,
                },
            )
        )

    def _finish_live_progress(self) -> None:
        """Clean up optional terminal rendering after a bounded worker settles."""

        if self._progress_reporter is not None:
            self._progress_reporter.finish()
