"""Extension-level Phase 3.3 manual-acceptance wiring tests."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from dataclasses import dataclass
from pathlib import Path

from digital_twin_runtime_suite.app.airflow_acceptance import (
    Phase33AcceptanceState,
)


@dataclass(frozen=True)
class _Result:
    success: bool
    message: str


class _Controller:
    def __init__(self, *, transition_success: bool = True) -> None:
        self._transition_success = transition_success

    async def attach_simulation_cache_in_kit(self, *, status_callback):
        status_callback("foreground validation")
        return _Result(True, "Attach complete.")

    async def request_attached_workload_transition_in_kit(
        self,
        workload_mode: str,
        *,
        status_callback,
    ):
        status_callback("runtime consumption")
        return _Result(
            self._transition_success,
            f"{workload_mode} transition "
            f"{'complete' if self._transition_success else 'failed'}.",
        )

    async def detach_simulation_cache_in_kit(self):
        return _Result(True, "Detach complete.")


def _load_extension(monkeypatch, messages: list[str]):
    carb = types.ModuleType("carb")
    carb.log_warn = messages.append
    carb.log_error = messages.append
    monkeypatch.setitem(sys.modules, "carb", carb)
    for name in ("settings", "tokens", "windowing"):
        child = types.ModuleType(f"carb.{name}")
        setattr(carb, name, child)
        monkeypatch.setitem(sys.modules, f"carb.{name}", child)

    omni = types.ModuleType("omni")
    omni.__path__ = []
    monkeypatch.setitem(sys.modules, "omni", omni)
    for name in ("appwindow", "ext", "ui"):
        child = types.ModuleType(f"omni.{name}")
        setattr(omni, name, child)
        monkeypatch.setitem(sys.modules, f"omni.{name}", child)
    omni.ext.IExt = object

    path = (
        Path(__file__).parents[1]
        / "src"
        / "digital_twin_runtime_suite"
        / "ext"
        / "msp.dtrs"
        / "msp"
        / "dtrs"
        / "extension.py"
    )
    spec = importlib.util.spec_from_file_location("phase33_extension_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.PHASE33_MANUAL_ACCEPTANCE_ENABLED = True
    return module


def _build_extension(monkeypatch, *, transition_success: bool = True):
    messages: list[str] = []
    module = _load_extension(monkeypatch, messages)
    extension = module.DigitalTwinRuntimeSuiteExtension()
    extension._controller = _Controller(transition_success=transition_success)
    extension._phase33_airflow_acceptance = Phase33AcceptanceState()
    extension._airflow_task = None
    extension._airflow_transition_task = None
    extension._airflow_detach_requested = False
    extension._refresh_airflow_cache_selector_label = lambda: None
    extension._set_airflow_status = lambda _message: None

    async def suppress_waiting(**_kwargs) -> None:
        return None

    extension._report_airflow_waiting = suppress_waiting
    return extension, messages


async def _run_full_manual_sequence(extension) -> None:
    extension._schedule_attach_airflow()
    await extension._airflow_task
    for workload in ("Critical", "Nominal"):
        extension._schedule_attached_workload_transition(workload)
        await extension._airflow_transition_task
    extension._schedule_detach_airflow()
    await extension._airflow_task


def _terminal_count(messages: list[str]) -> int:
    return sum(
        "TEST COMPLETE | Phase 3.3 shared airflow state acceptance passed." in message
        for message in messages
    )


def test_extension_full_manual_sequence_logs_terminal_once(monkeypatch) -> None:
    extension, messages = _build_extension(monkeypatch)

    asyncio.run(_run_full_manual_sequence(extension))

    assert _terminal_count(messages) == 1
    assert (
        sum("No further manual action required." in message for message in messages)
        == 1
    )


def test_extension_incomplete_sequence_never_logs_terminal(monkeypatch) -> None:
    extension, messages = _build_extension(monkeypatch)

    async def scenario() -> None:
        extension._schedule_attach_airflow()
        await extension._airflow_task
        extension._schedule_detach_airflow()
        await extension._airflow_task

    asyncio.run(scenario())

    assert _terminal_count(messages) == 0


def test_extension_failed_transition_never_logs_terminal(monkeypatch) -> None:
    extension, messages = _build_extension(monkeypatch, transition_success=False)

    async def scenario() -> None:
        extension._schedule_attach_airflow()
        await extension._airflow_task
        extension._schedule_attached_workload_transition("Critical")
        await extension._airflow_transition_task
        extension._schedule_detach_airflow()
        await extension._airflow_task

    asyncio.run(scenario())

    assert _terminal_count(messages) == 0


def test_extension_new_session_resets_terminal_eligibility(monkeypatch) -> None:
    extension, messages = _build_extension(monkeypatch)

    async def scenario() -> None:
        await _run_full_manual_sequence(extension)
        extension._schedule_attach_airflow()
        await extension._airflow_task
        extension._schedule_detach_airflow()
        await extension._airflow_task

    asyncio.run(scenario())

    assert _terminal_count(messages) == 1
