# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""Run finite, feature-agnostic viewport performance measurements."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from digital_twin_runtime_suite.app.flow.performance import (
    ViewportPerformanceSample,
    capture_viewport_performance_sample,
)
from digital_twin_runtime_suite.app.status_log import format_dtrs_status_block


@dataclass(frozen=True)
class PerformanceProbeStatistics:
    """Immutable min/average/max evidence for one optional viewport metric."""

    minimum: float | None
    average: float | None
    maximum: float | None


@dataclass(frozen=True)
class PerformanceProbeResult:
    """One finite performance-probe outcome without inferred statistics."""

    label: str
    settle_sample: ViewportPerformanceSample | None
    measurement_samples: tuple[ViewportPerformanceSample, ...]
    fps: PerformanceProbeStatistics
    frame_time_ms: PerformanceProbeStatistics
    gpu_memory_used_gib: PerformanceProbeStatistics
    process_memory_used_gib: PerformanceProbeStatistics
    elapsed_seconds: float
    completed: bool
    cancelled: bool


class PerformanceProbe:
    """Own one cancellable finite sample run and no idle background work."""

    def __init__(
        self,
        *,
        log_status: Callable[[str], None] | None = None,
        append_local_timestamp: Callable[[str], str] | None = None,
        settle_delay_seconds: float = 5.0,
        measurement_delay_seconds: float = 5.0,
        sample_count: int = 5,
        sample_interval_seconds: float = 1.0,
        sample_reader: Callable[[], ViewportPerformanceSample] = (
            capture_viewport_performance_sample
        ),
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._log_status = log_status
        self._append_local_timestamp = append_local_timestamp
        self._settle_delay_seconds = settle_delay_seconds
        self._measurement_delay_seconds = measurement_delay_seconds
        self._sample_count = sample_count
        self._sample_interval_seconds = sample_interval_seconds
        self._sample_reader = sample_reader
        self._sleep = sleep
        self._monotonic = monotonic
        self._task: asyncio.Task[PerformanceProbeResult] | None = None
        self._last_result: PerformanceProbeResult | None = None

    @property
    def active(self) -> bool:
        """Return whether this probe currently owns one asynchronous run."""

        return self._task is not None and not self._task.done()

    @property
    def last_result(self) -> PerformanceProbeResult | None:
        """Expose completed or cancelled evidence without retaining live state."""

        return self._last_result

    def run(self, *, label: str) -> asyncio.Task[PerformanceProbeResult]:
        """Start one run; a newer request supersedes any unfinished predecessor."""

        self.cancel()
        task = asyncio.ensure_future(self._run(label))
        self._task = task
        return task

    def cancel(self) -> None:
        """Stop the active run without emitting a misleading completion record."""

        task = self._task
        self._task = None
        if task is not None and not task.done():
            task.cancel()

    async def _run(self, label: str) -> PerformanceProbeResult:
        started_at = self._monotonic()
        settle_sample: ViewportPerformanceSample | None = None
        measurement_samples: list[ViewportPerformanceSample] = []
        self._emit_start(label)
        try:
            await self._sleep(self._settle_delay_seconds)
            settle_sample = self._capture_sample()
            await self._sleep(self._measurement_delay_seconds)
            for index in range(self._sample_count):
                measurement_samples.append(self._capture_sample())
                if index + 1 < self._sample_count:
                    await self._sleep(self._sample_interval_seconds)
        except asyncio.CancelledError:
            result = self._result(
                label,
                settle_sample,
                measurement_samples,
                started_at,
                completed=False,
                cancelled=True,
            )
            self._last_result = result
            return result
        except Exception as error:  # noqa: BLE001 - instrumentation is non-invasive.
            result = self._result(
                label,
                settle_sample,
                measurement_samples,
                started_at,
                completed=False,
                cancelled=False,
            )
            self._last_result = result
            self._emit_failure(label, str(error))
            return result
        finally:
            if self._task is asyncio.current_task():
                self._task = None

        result = self._result(
            label,
            settle_sample,
            measurement_samples,
            started_at,
            completed=True,
            cancelled=False,
        )
        self._last_result = result
        self._emit_complete(result)
        return result

    def _capture_sample(self) -> ViewportPerformanceSample:
        """Downgrade an unexpected reader failure to unavailable measurements."""

        try:
            return self._sample_reader()
        except Exception:  # noqa: BLE001 - measurement must not affect runtime state.
            return ViewportPerformanceSample(
                captured_at=self._monotonic(),
                fps=None,
                frame_time_ms=None,
                gpu_memory_used_gib=None,
                process_memory_used_gib=None,
            )

    def _result(
        self,
        label: str,
        settle_sample: ViewportPerformanceSample | None,
        measurement_samples: list[ViewportPerformanceSample],
        started_at: float,
        *,
        completed: bool,
        cancelled: bool,
    ) -> PerformanceProbeResult:
        """Reduce measurement-only samples; the settle observation is excluded."""

        samples = tuple(measurement_samples)
        return PerformanceProbeResult(
            label=label,
            settle_sample=settle_sample,
            measurement_samples=samples,
            fps=_statistics(sample.fps for sample in samples),
            frame_time_ms=_statistics(sample.frame_time_ms for sample in samples),
            gpu_memory_used_gib=_statistics(
                sample.gpu_memory_used_gib for sample in samples
            ),
            process_memory_used_gib=_statistics(
                sample.process_memory_used_gib for sample in samples
            ),
            elapsed_seconds=self._monotonic() - started_at,
            completed=completed,
            cancelled=cancelled,
        )

    def _emit_start(self, label: str) -> None:
        """Log timing evidence before the finite probe starts waiting."""

        self._emit(
            "\n".join(
                (
                    "DTRS PERFORMANCE PROBE | START",
                    f"label={label}",
                    f"settle_delay_s={self._settle_delay_seconds:.1f}",
                    f"measurement_delay_s={self._measurement_delay_seconds:.1f}",
                    f"sample_count={self._sample_count}",
                    f"sample_interval_s={self._sample_interval_seconds:.1f}",
                )
            )
        )

    def _emit_complete(self, result: PerformanceProbeResult) -> None:
        """Log complete aggregate evidence using the shared DTRS status format."""

        settle = result.settle_sample
        settle_fps = _value(settle.fps) if settle else "unavailable"
        settle_frame_time = _value(settle.frame_time_ms) if settle else "unavailable"
        settle_gpu_memory = (
            _value(settle.gpu_memory_used_gib) if settle else "unavailable"
        )
        settle_process_memory = (
            _value(settle.process_memory_used_gib) if settle else "unavailable"
        )
        self._emit(
            "\n".join(
                (
                    "DTRS PERFORMANCE PROBE | COMPLETE",
                    f"label={result.label}",
                    f"elapsed_s={result.elapsed_seconds:.1f}",
                    "",
                    "FPS",
                    *_stat_lines(result.fps),
                    "",
                    "FRAME TIME",
                    *_stat_lines(result.frame_time_ms, suffix="_ms"),
                    "",
                    "GPU MEMORY",
                    *_stat_lines(result.gpu_memory_used_gib, suffix="_gib"),
                    "",
                    "PROCESS MEMORY",
                    *_stat_lines(result.process_memory_used_gib, suffix="_gib"),
                    "",
                    "SETTLE SAMPLE",
                    f"fps={settle_fps}",
                    f"frame_time_ms={settle_frame_time}",
                    f"gpu_memory_gib={settle_gpu_memory}",
                    f"process_memory_gib={settle_process_memory}",
                )
            )
        )

    def _emit_failure(self, label: str, reason: str) -> None:
        """Make an unexpected probe fault visible without presenting it as complete."""

        self._emit(
            "\n".join(
                (
                    "DTRS PERFORMANCE PROBE | FAIL",
                    f"label={label}",
                    f"reason={reason}",
                )
            )
        )

    def _emit(self, content: str) -> None:
        """Write only fully wrapped records when logging services are supplied."""

        if self._log_status is None or self._append_local_timestamp is None:
            return
        self._log_status(
            format_dtrs_status_block(
                content,
                append_local_timestamp=self._append_local_timestamp,
            )
        )


def _statistics(values) -> PerformanceProbeStatistics:
    """Aggregate only supplied observations so unavailable data remains truthful."""

    observed = tuple(value for value in values if value is not None)
    if not observed:
        return PerformanceProbeStatistics(None, None, None)
    return PerformanceProbeStatistics(
        minimum=min(observed),
        average=sum(observed) / len(observed),
        maximum=max(observed),
    )


def _stat_lines(
    statistics: PerformanceProbeStatistics,
    *,
    suffix: str = "",
) -> tuple[str, str, str]:
    """Keep all aggregate values explicit, including unavailable statistics."""

    return (
        f"minimum{suffix}={_value(statistics.minimum)}",
        f"average{suffix}={_value(statistics.average)}",
        f"maximum{suffix}={_value(statistics.maximum)}",
    )


def _value(value: float | None) -> str:
    """Format known metrics consistently without fabricating unavailable values."""

    return "unavailable" if value is None else f"{value:.1f}"
