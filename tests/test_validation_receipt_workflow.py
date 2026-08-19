"""Focused two-session validation-receipt workflow contracts."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace

from digital_twin_runtime_suite.app.manual_acceptance import GuidedAcceptanceSession
from digital_twin_runtime_suite.app.visualization_mode import VisualizationMode


def test_session_one_persists_checkpoint_without_test_complete():
    controller = _AcceptanceController()
    workflow, messages = _workflow(controller)
    workflow._acceptance = GuidedAcceptanceSession(("SESSION_1",))
    workflow._acceptance.begin()

    asyncio.run(workflow.run_acceptance_session1())

    events = "\n".join(messages)
    assert "| COMPLETE" in events
    assert "TEST COMPLETE" not in events
    assert controller.checkpoint["phase"] == "AWAITING_RESTART"


def test_session_two_restores_receipts_without_requesting_visualization():
    controller = _AcceptanceController()
    workflow, messages = _workflow(controller)
    workflow._checkpoint = {"baseline_identities": controller.identities}

    asyncio.run(workflow.run_acceptance_session2())

    events = "\n".join(messages)
    assert "Persisted receipts restored through the cheap path" in events
    assert "expensive_preflight_calls=0" in events
    assert "geometry_sha256_recomputed=0" in events
    assert 'Select "Smoke" in "Visualization"' in events
    assert "TEST COMPLETE" not in events
    assert controller.visualization_requests == []
    assert controller.visualization_snapshot().committed is VisualizationMode.NORMAL


def test_session_two_rejects_unexpected_expensive_validation():
    controller = _AcceptanceController(expensive_vti_calls=1)
    workflow, messages = _workflow(controller)
    workflow._checkpoint = {"baseline_identities": controller.identities}

    asyncio.run(workflow.run_acceptance_session2())

    events = "\n".join(messages)
    assert "| FAIL" in events
    assert "expensive VTI preflight" in events
    assert "TEST COMPLETE" not in events


def test_consumer_check_starts_only_after_explicit_smoke_selection():
    controller = _AcceptanceController()
    workflow, messages = _workflow(controller)
    workflow._checkpoint = {"baseline_identities": controller.identities}

    asyncio.run(workflow.run_acceptance_session2())
    assert "Verifying persisted VTI receipt" not in "\n".join(messages)

    workflow.begin_consumer_action(VisualizationMode.SMOKE)

    assert "Verifying persisted VTI receipt" in "\n".join(messages)
    assert controller.visualization_requests == []


def test_session_two_completes_only_after_smoke_and_normal():
    controller = _AcceptanceController()
    workflow, messages = _workflow(controller)
    workflow._checkpoint = {"baseline_identities": controller.identities}

    async def run_sequence() -> None:
        await workflow.run_acceptance_session2()
        workflow.begin_consumer_action(VisualizationMode.SMOKE)
        smoke_result = await controller.request_visualization_mode_in_kit(
            VisualizationMode.SMOKE
        )
        workflow.complete_consumer_action(VisualizationMode.SMOKE, smoke_result)
        assert "TEST COMPLETE" not in "\n".join(messages)

        workflow.begin_consumer_action(VisualizationMode.NORMAL)
        normal_result = await controller.request_visualization_mode_in_kit(
            VisualizationMode.NORMAL
        )
        workflow.complete_consumer_action(VisualizationMode.NORMAL, normal_result)

    asyncio.run(run_sequence())

    events = "\n".join(messages)
    assert events.count("TEST COMPLETE") == 1
    assert controller.flow_lifecycle_state() == "DETACHED"
    assert controller.checkpoint_cleared is True


def test_normal_cleanup_uses_public_lifecycle_query():
    controller = _AcceptanceController(normal_cleanup_pass=False)
    workflow, messages = _workflow(controller)
    workflow._checkpoint = {"baseline_identities": controller.identities}

    async def run_sequence() -> None:
        await workflow.run_acceptance_session2()
        workflow.begin_consumer_action(VisualizationMode.SMOKE)
        smoke_result = await controller.request_visualization_mode_in_kit(
            VisualizationMode.SMOKE
        )
        workflow.complete_consumer_action(VisualizationMode.SMOKE, smoke_result)
        workflow.begin_consumer_action(VisualizationMode.NORMAL)
        normal_result = await controller.request_visualization_mode_in_kit(
            VisualizationMode.NORMAL
        )
        workflow.complete_consumer_action(VisualizationMode.NORMAL, normal_result)

    asyncio.run(run_sequence())

    assert "Flow lifecycle is not detached" in "\n".join(messages)
    assert controller.checkpoint_cleared is False


def test_cancel_clears_only_workflow_owned_tasks():
    controller = _AcceptanceController()
    workflow, _messages = _workflow(controller)
    task = _Task()
    workflow._summary_task = task

    workflow.cancel()

    assert task.cancelled is True
    assert controller.background_validation_stopped is True


def _workflow(controller):
    module = _load_workflow()
    messages = []
    workflow = module.ValidationReceiptWorkflow(
        controller,
        current_workload=lambda: "Nominal",
        normal_selected=lambda: True,
        log_warning=messages.append,
        log_error=messages.append,
        include_airflow_diagnostics=False,
    )

    async def finished(_session_name: str) -> bool:
        return True

    workflow._wait_for_validation_tasks = finished
    workflow.start_background_work = lambda: None
    return workflow, messages


class _Task:
    def __init__(self) -> None:
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class _AcceptanceController:
    def __init__(
        self,
        *,
        expensive_vti_calls: int = 0,
        normal_cleanup_pass: bool = True,
    ) -> None:
        self.identities = {
            "vti": {f"server/load_{index}": f"vti-{index}" for index in range(4)},
            "streamlines": {
                f"workload-{index}|server/load_{index}": {
                    "resource_fingerprint": [f"metadata-{index}", f"geometry-{index}"],
                    "dependency_identity": [f"vti-{index}", "profile"],
                }
                for index in range(4)
            },
        }
        self.config = SimpleNamespace(
            validation_receipts=SimpleNamespace(
                reuse_verified_vti_receipts=True,
                reuse_verified_streamlines_cache_receipts=True,
            )
        )
        self.checkpoint = None
        self.checkpoint_cleared = False
        self.background_validation_stopped = False
        self.normal_cleanup_pass = normal_cleanup_pass
        self.visualization_requests = []
        self._visualization_mode = VisualizationMode.NORMAL
        self._flow_lifecycle = "DETACHED"
        self._metrics = SimpleNamespace(
            vti=SimpleNamespace(
                persisted_reused=4,
                session_reused=0,
                fresh_validated=0,
                invalidated=0,
                expensive_validation_calls=expensive_vti_calls,
            ),
            streamlines=SimpleNamespace(
                persisted_reused=4,
                session_reused=0,
                fresh_validated=0,
                invalidated=0,
                expensive_validation_calls=0,
                geometry_sha256_recomputed=0,
            ),
        )

    def validation_receipt_identity_snapshot(self):
        return self.identities

    def validation_receipt_coverage_snapshot(self, _identities):
        return {
            "vti_valid": 4,
            "vti_total": 4,
            "streamlines_valid": 4,
            "streamlines_total": 4,
        }

    def validation_receipt_metrics_snapshot(self):
        return self._metrics

    async def request_visualization_mode_in_kit(self, mode, status_callback=None):
        self.visualization_requests.append(mode)
        if mode is VisualizationMode.SMOKE:
            self._visualization_mode = mode
            self._flow_lifecycle = "ATTACHED"
        elif mode is VisualizationMode.NORMAL and self.normal_cleanup_pass:
            self._visualization_mode = mode
            self._flow_lifecycle = "DETACHED"
        if status_callback:
            status_callback("Importing initial Nominal VTI through Kit-CAE")
        return SimpleNamespace(
            success=(
                True if mode is VisualizationMode.SMOKE else self.normal_cleanup_pass
            ),
            message="Visualization transition passed.",
        )

    def visualization_snapshot(self):
        return SimpleNamespace(committed=self._visualization_mode, pending=None)

    def primary_visualization_presentation_snapshot_in_kit(self):
        smoke_active = self._flow_lifecycle == "ATTACHED"
        return SimpleNamespace(
            flow_source_prepared=smoke_active,
            smoke_presentation_visible=smoke_active,
            streamlines_presentation_visible=False,
            streamlines_scheduler_tasks=0,
        )

    def xray_target_snapshot(self):
        return SimpleNamespace(override_owner=None)

    def vti_receipt_consumer_check_snapshot(self):
        return SimpleNamespace(
            selector="server/load_normal",
            receipt_source="PERSISTED",
            kit_cae_grid_contract_passed=True,
            flow_initial_readiness_passed=True,
        )

    def flow_lifecycle_state(self) -> str:
        return self._flow_lifecycle

    def write_validation_receipt_acceptance_checkpoint(self, payload):
        self.checkpoint = payload

    def clear_validation_receipt_acceptance_checkpoint(self):
        self.checkpoint_cleared = True

    def stop_background_airflow_validation(self) -> None:
        self.background_validation_stopped = True


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
        / "validation_receipts.py"
    )
    spec = importlib.util.spec_from_file_location("validation_receipt_workflow", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
