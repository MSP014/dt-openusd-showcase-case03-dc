"""Focused UI-bound visualization workflow sequencing contracts."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace

from digital_twin_runtime_suite.app.visualization_mode import VisualizationMode


def test_duplicate_pending_mode_creates_one_task(monkeypatch):
    workflow = _workflow()
    scheduled = []

    def capture(coroutine):
        scheduled.append(coroutine)
        return _Task()

    monkeypatch.setattr(asyncio, "ensure_future", capture)

    workflow.schedule_mode(VisualizationMode.STREAMLINES)
    workflow.schedule_mode(VisualizationMode.STREAMLINES)

    assert len(scheduled) == 1
    scheduled[0].close()


def test_unavailable_mode_is_not_scheduled(monkeypatch):
    controller = _Controller(available=False)
    workflow = _workflow(controller)
    scheduled = []
    monkeypatch.setattr(asyncio, "ensure_future", scheduled.append)

    accepted = workflow.request_mode_from_ui(VisualizationMode.STREAMLINES)

    assert accepted is False
    assert scheduled == []
    assert workflow.statuses == ["Streamlines unavailable: Cache missing"]


def test_completed_streamlines_request_preserves_workflow_sequence():
    controller = _Controller()
    workflow = _workflow(controller)

    asyncio.run(workflow._request_mode(VisualizationMode.STREAMLINES))

    assert controller.started == [VisualizationMode.STREAMLINES]
    assert workflow.validation.completed == [VisualizationMode.STREAMLINES]
    assert controller.observed == [VisualizationMode.STREAMLINES]
    assert workflow.refreshed_cache == 1
    assert workflow.refreshed_controls == 1
    assert workflow.final_syncs == 1


def test_new_workload_request_is_forwarded_for_controller_supersession(monkeypatch):
    workflow = _workflow()
    first_task = _Task()
    workflow._workload_transition_task = first_task
    scheduled = []

    def capture(coroutine):
        scheduled.append(coroutine)
        return _Task()

    monkeypatch.setattr(asyncio, "ensure_future", capture)

    workflow.schedule_workload_transition("Critical")

    assert first_task.cancelled is False
    assert len(scheduled) == 1
    scheduled[0].close()


def test_cancel_stops_only_workflow_tasks_and_controller_transition():
    controller = _Controller()
    workflow = _workflow(controller)
    visualization_task = _Task()
    workload_task = _Task()
    workflow._visualization_task = visualization_task
    workflow._workload_transition_task = workload_task

    workflow.cancel()

    assert visualization_task.cancelled is True
    assert workload_task.cancelled is True
    assert controller.cancelled is True


def _workflow(controller=None):
    module = _load_workflow()
    statuses = []
    state = SimpleNamespace(
        refreshed_cache=0,
        refreshed_controls=0,
        final_syncs=0,
    )
    validation = _ValidationWorkflow()
    workflow = module.VisualizationWorkflow(
        controller or _Controller(),
        validation,
        report_status=statuses.append,
        refresh_cache_selector=lambda: setattr(
            state,
            "refreshed_cache",
            state.refreshed_cache + 1,
        ),
        refresh_visualization_controls=lambda: setattr(
            state,
            "refreshed_controls",
            state.refreshed_controls + 1,
        ),
        sync_final_acceptance=lambda: setattr(
            state,
            "final_syncs",
            state.final_syncs + 1,
        ),
    )
    workflow.statuses = statuses
    workflow.validation = validation
    workflow.refreshed_cache = state.refreshed_cache
    workflow.refreshed_controls = state.refreshed_controls
    workflow.final_syncs = state.final_syncs
    original_cache = workflow._refresh_cache_selector
    original_controls = workflow._refresh_visualization_controls
    original_final = workflow._sync_final_acceptance

    def refresh_cache():
        original_cache()
        workflow.refreshed_cache = state.refreshed_cache

    def refresh_controls():
        original_controls()
        workflow.refreshed_controls = state.refreshed_controls

    def sync_final():
        original_final()
        workflow.final_syncs = state.final_syncs

    workflow._refresh_cache_selector = refresh_cache
    workflow._refresh_visualization_controls = refresh_controls
    workflow._sync_final_acceptance = sync_final
    return workflow


class _Task:
    def __init__(self) -> None:
        self.cancelled = False

    def done(self) -> bool:
        return False

    def cancel(self) -> None:
        self.cancelled = True


class _ValidationWorkflow:
    def __init__(self) -> None:
        self.started = []
        self.completed = []

    def begin_consumer_action(self, mode) -> None:
        self.started.append(mode)

    def complete_consumer_action(self, mode, _result) -> None:
        self.completed.append(mode)


class _Controller:
    def __init__(self, *, available: bool = True) -> None:
        self.available = available
        self.started = []
        self.observed = []
        self.cancelled = False

    def visualization_readiness(self):
        return SimpleNamespace(
            for_mode=lambda _mode: SimpleNamespace(
                activation_available=self.available,
                message="Ready" if self.available else "Cache missing",
            )
        )

    def visualization_snapshot(self):
        return SimpleNamespace(pending=None)

    def start_streamlines_snapshot_playback_acceptance(self, mode) -> None:
        self.started.append(mode)

    async def request_visualization_mode_in_kit(self, mode, status_callback):
        status_callback("Preparing snapshots")
        return SimpleNamespace(success=True, message=f"{mode.value} active")

    async def observe_streamlines_snapshot_playback_acceptance_result(
        self,
        mode,
        _result,
    ) -> None:
        self.observed.append(mode)

    async def request_workload_transition_in_kit(self, _mode, status_callback):
        status_callback("Switching workload")
        return SimpleNamespace(message="Workload active")

    def cancel_visualization_transition(self) -> None:
        self.cancelled = True


def _load_workflow():
    path = (
        Path(__file__).parents[1]
        / "src"
        / "digital_twin_runtime_suite"
        / "ext"
        / "msp.dtrs"
        / "msp"
        / "dtrs"
        / "workflows"
        / "visualization.py"
    )
    spec = importlib.util.spec_from_file_location("visualization_workflow", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
