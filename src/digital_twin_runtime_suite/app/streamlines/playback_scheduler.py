"""Dependency-free monotonic scheduler for direct cached Streamlines playback."""

from __future__ import annotations

import asyncio
import math
import time
from contextlib import suppress
from dataclasses import dataclass
from typing import Awaitable, Callable

from digital_twin_runtime_suite.app.streamlines.temporal import (
    TemporalSampleResolution,
)

PhaseSource = Callable[[], float]
StateSelector = Callable[[float], Awaitable[TemporalSampleResolution]]
TickObserver = Callable[["CachedPlaybackTick"], None]


@dataclass(frozen=True)
class CachedPlaybackTick:
    """One deadline-driven presentation decision made from the current phase."""

    deadline_seconds: float
    phase_seconds: float
    resolution: TemporalSampleResolution
    started_at_seconds: float
    completed_at_seconds: float

    @property
    def switch_latency_seconds(self) -> float:
        """Return only the state-selection time for this current-phase tick."""

        return self.completed_at_seconds - self.started_at_seconds

    @property
    def scheduling_drift_seconds(self) -> float:
        """Return lateness relative to the immutable monotonic deadline."""

        return self.started_at_seconds - self.deadline_seconds


@dataclass(frozen=True)
class CachedPlaybackSchedulerReport:
    """Plain receipt for one scheduler lifetime or bounded characterization run."""

    period_seconds: float
    tick_count: int
    switch_count: int
    no_op_count: int
    missed_deadlines: int
    backlog_count: int
    maximum_drift_seconds: float
    maximum_switch_latency_seconds: float
    median_switch_latency_seconds: float
    loop_wrap_count: int
    cancelled: bool


class CachedPlaybackScheduler:
    """Run direct current-phase selection without a historical-state queue."""

    def __init__(
        self,
        *,
        period_seconds: float,
        phase_source: PhaseSource,
        state_selector: StateSelector,
        tick_observer: TickObserver | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[object]] = asyncio.sleep,
    ) -> None:
        """Create a scheduler whose next deadline never depends on completion."""

        if not math.isfinite(period_seconds) or period_seconds <= 0.0:
            raise ValueError("Cached playback period must be positive and finite.")
        self._period_seconds = period_seconds
        self._phase_source = phase_source
        self._state_selector = state_selector
        self._tick_observer = tick_observer
        self._monotonic = monotonic
        self._sleep = sleep
        self._task: asyncio.Task[None] | None = None
        self._started_at_seconds: float | None = None
        self._ticks: list[CachedPlaybackTick] = []
        self._missed_deadlines = 0
        self._loop_wrap_count = 0
        self._last_normalized_phase_seconds: float | None = None
        self._cancelled = False

    @property
    def active(self) -> bool:
        """Return whether this scheduler still owns a live presentation task."""

        return self._task is not None and not self._task.done()

    @property
    def active_task_count(self) -> int:
        """Expose the exact number of active tasks this single-flight owner has."""

        return int(self.active)

    @property
    def ticks(self) -> tuple[CachedPlaybackTick, ...]:
        """Return observed current-phase decisions without exposing mutation."""

        return tuple(self._ticks)

    async def start(self) -> None:
        """Start from an immutable monotonic origin; reject duplicate ownership."""

        if self.active:
            raise RuntimeError("Cached playback scheduler is already running.")
        self._reset_run_state()
        self._started_at_seconds = self._monotonic()
        self._task = asyncio.create_task(self._run())
        await asyncio.sleep(0)

    async def stop(self) -> CachedPlaybackSchedulerReport:
        """Cancel and await the only task owned by this scheduler."""

        task = self._task
        self.cancel()
        if task and not task.done():
            with suppress(asyncio.CancelledError):
                await task
        return self.report()

    def cancel(self) -> None:
        """Request cancellation immediately for synchronous stage teardown."""

        task = self._task
        if task and not task.done():
            self._cancelled = True
            task.cancel()

    async def restart(self) -> None:
        """Stop the prior task before beginning a fresh monotonic schedule."""

        await self.stop()
        await self.start()

    def report(self) -> CachedPlaybackSchedulerReport:
        """Return a stable summary with structural zero backlog."""

        latencies = sorted(tick.switch_latency_seconds for tick in self._ticks)
        midpoint = len(latencies) // 2
        median_latency = (
            0.0
            if not latencies
            else (
                latencies[midpoint]
                if len(latencies) % 2
                else (latencies[midpoint - 1] + latencies[midpoint]) / 2.0
            )
        )
        return CachedPlaybackSchedulerReport(
            period_seconds=self._period_seconds,
            tick_count=len(self._ticks),
            switch_count=sum(not tick.resolution.is_no_op for tick in self._ticks),
            no_op_count=sum(tick.resolution.is_no_op for tick in self._ticks),
            missed_deadlines=self._missed_deadlines,
            backlog_count=0,
            maximum_drift_seconds=max(
                (tick.scheduling_drift_seconds for tick in self._ticks),
                default=0.0,
            ),
            maximum_switch_latency_seconds=max(latencies, default=0.0),
            median_switch_latency_seconds=median_latency,
            loop_wrap_count=self._loop_wrap_count,
            cancelled=self._cancelled,
        )

    async def _run(self) -> None:
        """Select only the state for now, skipping expired deadlines by design."""

        started_at = self._started_at_seconds
        if started_at is None:
            raise RuntimeError("Cached playback scheduler has no start time.")
        deadline_index = 0
        while True:
            deadline = started_at + deadline_index * self._period_seconds
            delay_seconds = deadline - self._monotonic()
            if delay_seconds > 0.0:
                await self._sleep(delay_seconds)
            tick_started_at = self._monotonic()
            phase_seconds = self._phase_source()
            resolution = await self._state_selector(phase_seconds)
            tick_completed_at = self._monotonic()
            tick = CachedPlaybackTick(
                deadline_seconds=deadline,
                phase_seconds=phase_seconds,
                resolution=resolution,
                started_at_seconds=tick_started_at,
                completed_at_seconds=tick_completed_at,
            )
            self._record_tick(tick)
            if self._tick_observer:
                self._tick_observer(tick)
            elapsed_seconds = tick_completed_at - started_at
            next_deadline_index = max(
                deadline_index + 1,
                math.floor(elapsed_seconds / self._period_seconds) + 1,
            )
            self._missed_deadlines += max(
                0,
                next_deadline_index - deadline_index - 1,
            )
            deadline_index = next_deadline_index

    def _record_tick(self, tick: CachedPlaybackTick) -> None:
        """Record exact decisions and wraps without inventing unseen samples."""

        normalized_phase = tick.resolution.normalized_phase_seconds
        previous_phase = self._last_normalized_phase_seconds
        if previous_phase is not None and normalized_phase < previous_phase:
            self._loop_wrap_count += 1
        self._last_normalized_phase_seconds = normalized_phase
        self._ticks.append(tick)

    def _reset_run_state(self) -> None:
        """Clear a completed run before a deliberate scheduler restart."""

        self._ticks = []
        self._missed_deadlines = 0
        self._loop_wrap_count = 0
        self._last_normalized_phase_seconds = None
        self._cancelled = False
