# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""Application-lifetime periodic PerformanceProbe coverage."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path


def _workflow_type():
    path = (
        Path(__file__).parents[1]
        / "src"
        / "digital_twin_runtime_suite"
        / "ext"
        / "msp.dtrs"
        / "msp"
        / "dtrs"
        / "workflows"
        / "performance.py"
    )
    spec = importlib.util.spec_from_file_location("periodic_performance_workflow", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.PeriodicPerformanceWorkflow


class _Probe:
    def __init__(self) -> None:
        self.labels: list[str] = []
        self.cancelled = False

    async def run(self, *, label: str) -> None:
        self.labels.append(label)

    def cancel(self) -> None:
        self.cancelled = True


def test_initial_probe_waits_one_idle_minute() -> None:
    async def run() -> None:
        workflow_type = _workflow_type()
        probe = _Probe()
        delays: list[float] = []

        async def sleep(delay: float) -> None:
            delays.append(delay)
            raise asyncio.CancelledError

        workflow = workflow_type(
            log_status=lambda _message: None,
            append_local_timestamp=lambda content: content,
            performance_probe=probe,
            sleep=sleep,
            monotonic=lambda: 10.0,
        )
        task = workflow.start()
        await task

        assert probe.labels == []
        assert delays == [60.0]
        assert not workflow.active

    asyncio.run(run())


def test_periodic_probe_cancellation_stops_its_measurement() -> None:
    async def run() -> None:
        workflow_type = _workflow_type()
        gate = asyncio.Event()
        probe = _Probe()

        async def sleep(_delay: float) -> None:
            await gate.wait()

        workflow = workflow_type(
            log_status=lambda _message: None,
            append_local_timestamp=lambda content: content,
            performance_probe=probe,
            sleep=sleep,
        )
        task = workflow.start()
        await asyncio.sleep(0)
        workflow.cancel()
        await task

        assert probe.cancelled
        assert not workflow.active

    asyncio.run(run())


def test_committed_mode_waits_to_settle_then_repeats_each_idle_minute() -> None:
    async def run() -> None:
        workflow_type = _workflow_type()
        probe = _Probe()
        delays: list[float] = []

        async def sleep(delay: float) -> None:
            delays.append(delay)
            if delay == 60.0:
                raise asyncio.CancelledError

        workflow = workflow_type(
            log_status=lambda _message: None,
            append_local_timestamp=lambda content: content,
            performance_probe=probe,
            sleep=sleep,
            monotonic=lambda: 10.0,
        )
        workflow.observe_committed_mode(_Mode("Heatmap"))
        assert workflow._task is not None
        await workflow._task

        assert probe.labels == ["Heatmap"]
        assert delays == [10.0, 60.0]
        assert not workflow.active

    asyncio.run(run())


def test_new_committed_mode_replaces_the_prior_settle_timer() -> None:
    async def run() -> None:
        workflow_type = _workflow_type()
        gate = asyncio.Event()
        workflow = workflow_type(
            log_status=lambda _message: None,
            append_local_timestamp=lambda content: content,
            performance_probe=_Probe(),
            sleep=lambda _delay: gate.wait(),
        )
        first = workflow.start()
        await asyncio.sleep(0)

        workflow.observe_committed_mode(_Mode("Smoke"))
        second = workflow._task
        await asyncio.sleep(0)
        workflow.cancel()
        await asyncio.gather(first, second, return_exceptions=True)

        assert first.done()
        assert second is not None and second.done()
        assert first is not second

    asyncio.run(run())


class _Mode:
    def __init__(self, value: str) -> None:
        self.value = value
