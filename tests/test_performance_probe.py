"""Finite PerformanceProbe lifecycle and aggregation coverage."""

from __future__ import annotations

import asyncio

from digital_twin_runtime_suite.app.flow.performance import (
    ViewportPerformanceSample,
)
from digital_twin_runtime_suite.app.performance_probe import PerformanceProbe


def test_probe_aggregates_only_measurement_samples() -> None:
    async def run() -> None:
        samples = iter(
            (
                _sample(99.0, 10.0, 9.0, 19.0),
                _sample(10.0, 20.0, 1.0, 2.0),
                _sample(20.0, 10.0, 2.0, 3.0),
                _sample(30.0, 30.0, 3.0, 4.0),
                _sample(40.0, 40.0, 4.0, 5.0),
                _sample(50.0, 50.0, 5.0, 6.0),
            )
        )
        probe = _probe(sample_reader=lambda: next(samples))

        result = await probe.run(label="MOTHERBOARD_BASE_BINDING")

        assert result.completed and not result.cancelled
        assert result.settle_sample is not None and result.settle_sample.fps == 99.0
        assert len(result.measurement_samples) == 5
        assert (result.fps.minimum, result.fps.average, result.fps.maximum) == (
            10.0,
            30.0,
            50.0,
        )
        assert (
            result.frame_time_ms.minimum,
            result.frame_time_ms.average,
            result.frame_time_ms.maximum,
        ) == (10.0, 30.0, 50.0)
        assert (
            result.gpu_memory_used_gib.minimum,
            result.gpu_memory_used_gib.average,
            result.gpu_memory_used_gib.maximum,
        ) == (1.0, 3.0, 5.0)
        assert (
            result.process_memory_used_gib.minimum,
            result.process_memory_used_gib.average,
            result.process_memory_used_gib.maximum,
        ) == (2.0, 4.0, 6.0)
        assert not probe.active

    asyncio.run(run())


def test_probe_preserves_unavailable_measurements_without_inventing_values() -> None:
    async def run() -> None:
        samples = iter(
            (
                _sample(None, None, None, None),
                _sample(None, 20.0, None, 2.0),
                _sample(None, None, None, None),
                _sample(None, 40.0, None, 4.0),
                _sample(None, None, None, None),
                _sample(None, None, None, None),
            )
        )
        result = await _probe(sample_reader=lambda: next(samples)).run(label="NONE")

        assert result.fps.minimum is None
        assert result.gpu_memory_used_gib.maximum is None
        assert result.frame_time_ms.average == 30.0
        assert result.process_memory_used_gib.minimum == 2.0
        assert result.process_memory_used_gib.maximum == 4.0

    asyncio.run(run())


def test_probe_cancellation_has_no_complete_record_or_active_task() -> None:
    async def run() -> None:
        gate = asyncio.Event()

        async def wait(_seconds: float) -> None:
            await gate.wait()

        messages: list[str] = []
        probe = _probe(sleep=wait, messages=messages)
        task = probe.run(label="CANCELLED")
        await asyncio.sleep(0)
        assert probe.active

        probe.cancel()
        result = await task

        assert result.cancelled and not result.completed
        assert not probe.active
        assert "DTRS PERFORMANCE PROBE | START" in "\n".join(messages)
        assert "DTRS PERFORMANCE PROBE | COMPLETE" not in "\n".join(messages)

    asyncio.run(run())


def test_new_probe_run_supersedes_the_unfinished_predecessor() -> None:
    async def run() -> None:
        first_wait_entered = asyncio.Event()
        waits = 0

        async def wait(_seconds: float) -> None:
            nonlocal waits
            waits += 1
            if waits == 1:
                first_wait_entered.set()
                await asyncio.Event().wait()

        samples = iter(_sample(10.0, 20.0, 1.0, 2.0) for _ in range(6))
        probe = _probe(sample_reader=lambda: next(samples), sleep=wait)
        first = probe.run(label="FIRST")
        await first_wait_entered.wait()
        second = probe.run(label="SECOND")

        first_result = await first
        second_result = await second

        assert first_result.cancelled and not first_result.completed
        assert second_result.completed and not second_result.cancelled
        assert second_result.label == "SECOND"
        assert not probe.active

    asyncio.run(run())


def _probe(
    *,
    sample_reader=lambda: _sample(None, None, None, None),
    sleep=None,
    messages: list[str] | None = None,
) -> PerformanceProbe:
    async def no_wait(_seconds: float) -> None:
        await asyncio.sleep(0)

    return PerformanceProbe(
        log_status=messages.append if messages is not None else None,
        append_local_timestamp=lambda text: text,
        settle_delay_seconds=0.0,
        measurement_delay_seconds=0.0,
        sample_count=5,
        sample_interval_seconds=0.0,
        sample_reader=sample_reader,
        sleep=sleep or no_wait,
        monotonic=lambda: 1.0,
    )


def _sample(
    fps: float | None,
    frame_time_ms: float | None,
    gpu_memory_used_gib: float | None,
    process_memory_used_gib: float | None,
) -> ViewportPerformanceSample:
    return ViewportPerformanceSample(
        captured_at=1.0,
        fps=fps,
        frame_time_ms=frame_time_ms,
        gpu_memory_used_gib=gpu_memory_used_gib,
        process_memory_used_gib=process_memory_used_gib,
    )
