"""Application-lifetime periodic viewport performance reporting."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

from digital_twin_runtime_suite.app.performance_probe import PerformanceProbe


class PeriodicPerformanceWorkflow:
    """Measure after committed mode changes, then once per idle minute."""

    INTERVAL_SECONDS = 60.0
    LABEL = "APPLICATION_RUNTIME"
    MODE_SETTLE_SECONDS = 10.0

    def __init__(
        self,
        *,
        log_status: Callable[[str], None],
        append_local_timestamp: Callable[[str], str],
        performance_probe: PerformanceProbe | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._performance_probe = performance_probe or PerformanceProbe(
            log_status=log_status,
            append_local_timestamp=append_local_timestamp,
            settle_delay_seconds=0.0,
            measurement_delay_seconds=0.0,
        )
        self._sleep = sleep
        self._monotonic = monotonic
        self._task: asyncio.Task[None] | None = None

    @property
    def active(self) -> bool:
        """Report whether the application-lifetime periodic task is running."""

        return self._task is not None and not self._task.done()

    def start(self) -> asyncio.Task[None]:
        """Arm the initial idle-minute measurement once at application startup."""

        task = self._task
        if task is not None and not task.done():
            return task
        self._task = asyncio.ensure_future(
            self._run_after_delay(self.LABEL, self.INTERVAL_SECONDS)
        )
        return self._task

    def observe_committed_mode(self, mode) -> None:
        """Restart the measurement cycle after a real primary-mode commit."""

        self._performance_probe.cancel()
        task = self._task
        if task is not None and not task.done():
            task.cancel()
        self._task = asyncio.ensure_future(
            self._run_after_delay(mode.value, self.MODE_SETTLE_SECONDS)
        )

    def cancel(self) -> None:
        """Stop pending measurement and its application-lifetime owner."""

        self._performance_probe.cancel()
        task = self._task
        self._task = None
        if task is not None and not task.done():
            task.cancel()

    async def _run_after_delay(self, label: str, delay_seconds: float) -> None:
        try:
            await self._sleep(delay_seconds)
            while True:
                cycle_started_at = self._monotonic()
                await self._performance_probe.run(label=label)
                remaining = self.INTERVAL_SECONDS - (
                    self._monotonic() - cycle_started_at
                )
                await self._sleep(max(remaining, 0.0))
        except asyncio.CancelledError:
            return
        finally:
            if self._task is asyncio.current_task():
                self._task = None
