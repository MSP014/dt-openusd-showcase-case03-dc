"""UI-bound orchestration for primary visualization and workload requests."""

from __future__ import annotations

import asyncio
from collections.abc import Callable


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
        sync_final_acceptance: Callable[[], None],
    ) -> None:
        self._controller = controller
        self._validation_receipts = validation_receipts
        self._report_status = report_status
        self._refresh_cache_selector = refresh_cache_selector
        self._refresh_visualization_controls = refresh_visualization_controls
        self._sync_final_acceptance = sync_final_acceptance
        self._visualization_task = None
        self._scheduled_mode = None
        self._workload_transition_task = None

    @property
    def workload_transition_task(self):
        """Expose the task only for legacy attach-cancellation coordination."""

        return self._workload_transition_task

    def request_mode_from_ui(self, mode) -> bool:
        """Validate current readiness, then schedule one user-requested mode."""

        readiness = self._controller.visualization_readiness().for_mode(mode)
        if not readiness.activation_available:
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
        start = getattr(
            self._controller,
            "start_streamlines_snapshot_playback_acceptance",
            None,
        )
        if start:
            start(mode)
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
        if getattr(mode, "value", mode) == "Streamlines":
            observe = getattr(
                self._controller,
                "observe_streamlines_snapshot_playback_acceptance_result",
                None,
            )
            if observe:
                await observe(mode, result)
        elif getattr(mode, "value", mode) == "Normal":
            observe = getattr(
                self._controller,
                "observe_streamlines_snapshot_playback_acceptance_normal_result",
                None,
            )
            if observe:
                observe(mode, result)
        self._sync_final_acceptance()

    async def _request_workload_transition(self, workload_mode: str) -> None:
        result = await self._controller.request_workload_transition_in_kit(
            workload_mode,
            status_callback=self._report_status,
        )
        self._report_status(result.message)
        self._refresh_cache_selector()
        self._refresh_visualization_controls()

    def _report_progress(self, message: str) -> None:
        self._report_status(message)
        report = getattr(
            self._controller,
            "report_streamlines_snapshot_playback_acceptance_progress",
            None,
        )
        if report:
            report(message)
