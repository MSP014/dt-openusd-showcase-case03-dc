"""UI-bound orchestration for primary visualization and workload requests."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from digital_twin_runtime_suite.app.status_log import format_dtrs_diagnostic_block


class VisualizationWorkflow:
    """Own UI request tasks while RuntimeController owns mode transactions.

    The workflow deliberately does not inspect rendering state.  It forwards
    controller outcomes to UI callbacks and lets the controller enforce
    transaction supersession and authoritative mode state.
    """

    def __init__(
        self,
        controller,
        validation_receipts,
        *,
        report_status: Callable[[str], None],
        refresh_cache_selector: Callable[[], None],
        refresh_visualization_controls: Callable[[], None],
        airflow_operation_active: Callable[[], bool] | None = None,
        log_warning: Callable[[str], None] | None = None,
        append_local_timestamp: Callable[[str], str] | None = None,
        on_mode_complete: Callable[[object, object], None] | None = None,
        on_mode_committed: Callable[[object], None] | None = None,
        on_workload_complete: Callable[[str, object], None] | None = None,
    ) -> None:
        self._controller = controller
        self._validation_receipts = validation_receipts
        self._report_status = report_status
        self._refresh_cache_selector = refresh_cache_selector
        self._refresh_visualization_controls = refresh_visualization_controls
        self._airflow_operation_active = airflow_operation_active
        self._log_warning = log_warning
        self._append_local_timestamp = append_local_timestamp
        self._on_mode_complete = on_mode_complete
        self._on_mode_committed = on_mode_committed
        self._on_workload_complete = on_workload_complete
        self._visualization_task = None
        self._scheduled_mode = None
        self._workload_transition_task = None

    @property
    def workload_transition_task(self):
        """Expose the task only for legacy attach-cancellation coordination."""

        return self._workload_transition_task

    def request_mode_from_ui(self, mode) -> bool:
        """Validate current readiness, then schedule one user-requested mode."""

        if self._airflow_operation_active and self._airflow_operation_active():
            detail = (
                "Wait for the active airflow cache operation before changing "
                "Visualization."
            )
            self._report_mode_transition(
                "REJECTED",
                mode,
                readiness="BUSY",
                detail=detail,
            )
            self._report_status(f"{mode.value} unavailable: {detail}")
            self._refresh_visualization_controls()
            return False
        readiness = self._controller.visualization_readiness().for_mode(mode)
        self._report_mode_transition(
            "REQUEST",
            mode,
            readiness=readiness.state,
            detail=readiness.message,
        )
        if not readiness.activation_available:
            self._report_mode_transition(
                "REJECTED",
                mode,
                readiness=readiness.state,
                detail=readiness.message,
            )
            self._report_status(f"{mode.value} unavailable: {readiness.message}")
            self._refresh_visualization_controls()
            return False
        self._validation_receipts.begin_consumer_action(mode)
        self.schedule_mode(mode)
        return True

    def schedule_mode(self, mode) -> None:
        """Own one task for one pending primary presentation request."""

        task = self._visualization_task
        pending = self._controller.visualization_snapshot().pending
        if (
            task is not None
            and not task.done()
            and (
                self._scheduled_mode is mode
                or (pending is not None and pending.target is mode)
            )
        ):
            return
        self._scheduled_mode = mode
        self._visualization_task = asyncio.ensure_future(self._request_mode(mode))

    def schedule_workload_transition(self, workload_mode: str) -> None:
        """Forward every newer workload request to controller supersession."""

        task = self._workload_transition_task
        coroutine = self._request_workload_transition(workload_mode)
        if task is not None and not task.done():
            self._workload_transition_task = asyncio.ensure_future(coroutine)
            return
        self._workload_transition_task = asyncio.ensure_future(coroutine)

    def cancel(self) -> None:
        """Cancel UI-owned tasks and the controller-owned pending transaction."""

        for name in ("_visualization_task", "_workload_transition_task"):
            task = getattr(self, name)
            if task is not None:
                task.cancel()
            setattr(self, name, None)
        self._scheduled_mode = None
        self._controller.cancel_visualization_transition()

    async def _request_mode(self, mode) -> None:
        committed_before = self._controller.visualization_snapshot().committed
        try:
            result = await self._controller.request_visualization_mode_in_kit(
                mode,
                status_callback=self._report_progress,
            )
        finally:
            if self._scheduled_mode is mode:
                self._scheduled_mode = None
        self._refresh_cache_selector()
        self._report_status(result.message)
        self._refresh_visualization_controls()
        self._validation_receipts.complete_consumer_action(mode, result)
        if self._on_mode_complete is not None:
            self._on_mode_complete(mode, result)
        # The controller snapshot is authoritative after the transaction: Kit
        # adapters may return a legacy result without ``committed_mode``.
        committed = self._controller.visualization_snapshot().committed
        if (
            self._on_mode_committed is not None
            and result.success
            and committed is not None
            and committed is not committed_before
        ):
            self._on_mode_committed(committed)
        self._report_mode_transition(
            "COMPLETE" if result.success else "FAIL",
            mode,
            committed_mode=committed.value if committed is not None else "unknown",
            detail=result.message,
        )

    async def _request_workload_transition(self, workload_mode: str) -> None:
        result = await self._controller.request_workload_transition_in_kit(
            workload_mode,
            status_callback=self._report_status,
        )
        self._report_status(result.message)
        self._refresh_cache_selector()
        self._refresh_visualization_controls()
        if self._on_workload_complete is not None:
            self._on_workload_complete(workload_mode, result)

    def _report_progress(self, message: str) -> None:
        self._report_status(message)

    def _report_mode_transition(self, state: str, mode, **details) -> None:
        """Emit readable UI-request and terminal mode-transition evidence."""

        if self._log_warning is None or self._append_local_timestamp is None:
            return
        self._log_warning(
            format_dtrs_diagnostic_block(
                owner="VISUALIZATION",
                process="MODE TRANSITION",
                state=state,
                details={"requested_mode": mode.value, **details},
                append_local_timestamp=self._append_local_timestamp,
            )
        )
