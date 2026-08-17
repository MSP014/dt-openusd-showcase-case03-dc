"""Focused two-session persisted-receipt acceptance contracts."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace

from digital_twin_runtime_suite.app.manual_acceptance import GuidedAcceptanceSession
from digital_twin_runtime_suite.app.visualization_mode import VisualizationMode


def test_session_one_persists_checkpoint_without_test_complete(monkeypatch):
    module = _load_extension(monkeypatch)
    messages = []
    module.carb.log_warn = messages.append
    controller = _AcceptanceController()
    extension = _acceptance_extension(module, controller)
    extension._validation_receipt_acceptance = GuidedAcceptanceSession(("SESSION_1",))
    extension._validation_receipt_acceptance.begin()

    asyncio.run(extension._run_validation_receipt_acceptance_session1())

    events = "\n".join(messages)
    assert "| COMPLETE" in events
    assert "TEST COMPLETE" not in events
    assert controller.checkpoint["phase"] == "AWAITING_RESTART"


def test_session_two_restores_receipts_without_requesting_a_visualization(monkeypatch):
    module = _load_extension(monkeypatch)
    messages = []
    module.carb.log_warn = messages.append
    controller = _AcceptanceController()
    extension = _acceptance_extension(module, controller)
    extension._validation_receipt_checkpoint = {
        "baseline_identities": controller.identities
    }

    asyncio.run(extension._run_validation_receipt_acceptance_session2())

    events = "\n".join(messages)
    assert "Persisted receipts restored through the cheap path" in events
    assert "expensive_preflight_calls=0" in events
    assert "geometry_sha256_recomputed=0" in events
    assert 'Select "Smoke" in "Visualization"' in events
    assert "TEST COMPLETE" not in events
    assert controller.visualization_requests == []
    assert controller.visualization_snapshot().committed is VisualizationMode.NORMAL
    assert controller.checkpoint_cleared is False


def test_session_two_cannot_pass_after_unexpected_fresh_validation(monkeypatch):
    module = _load_extension(monkeypatch)
    messages = []
    module.carb.log_warn = messages.append
    controller = _AcceptanceController(expensive_vti_calls=1)
    extension = _acceptance_extension(module, controller)
    extension._validation_receipt_checkpoint = {
        "baseline_identities": controller.identities
    }

    asyncio.run(extension._run_validation_receipt_acceptance_session2())

    events = "\n".join(messages)
    assert "| FAIL" in events
    assert "expensive VTI preflight" in events
    assert "TEST COMPLETE" not in events
    assert controller.checkpoint_cleared is False


def test_consumer_check_starts_only_after_explicit_smoke_selection(monkeypatch):
    module = _load_extension(monkeypatch)
    messages = []
    module.carb.log_warn = messages.append
    controller = _AcceptanceController()
    extension = _acceptance_extension(module, controller)
    extension._validation_receipt_checkpoint = {
        "baseline_identities": controller.identities
    }

    asyncio.run(extension._run_validation_receipt_acceptance_session2())
    assert "| START\nstatus=Verifying persisted VTI receipt" not in "\n".join(messages)

    extension._begin_validation_receipt_consumer_action(VisualizationMode.SMOKE)

    events = "\n".join(messages)
    assert (
        "Verifying persisted VTI receipt through the production Flow consumer" in events
    )
    assert controller.visualization_requests == []
    assert "TEST COMPLETE" not in events


def test_visualization_selector_starts_the_user_driven_consumer_check(monkeypatch):
    module = _load_extension(monkeypatch)
    messages = []
    module.carb.log_warn = messages.append
    controller = _AcceptanceController()
    extension = _acceptance_extension(module, controller)
    extension._validation_receipt_checkpoint = {
        "baseline_identities": controller.identities
    }
    controller.visualization_readiness = lambda: SimpleNamespace(
        for_mode=lambda _mode: SimpleNamespace(
            activation_available=True,
            message="Ready",
        )
    )
    scheduled = []
    extension._schedule_visualization_mode_request = scheduled.append

    asyncio.run(extension._run_validation_receipt_acceptance_session2())
    extension._on_visualization_mode_changed(_IndexModel(1))

    assert scheduled == [VisualizationMode.SMOKE]
    assert controller.visualization_requests == []
    assert "| START\nstatus=Verifying persisted VTI receipt" in "\n".join(messages)


def test_session_two_completes_only_after_explicit_smoke_and_normal(monkeypatch):
    module = _load_extension(monkeypatch)
    messages = []
    module.carb.log_warn = messages.append
    controller = _AcceptanceController()
    extension = _acceptance_extension(module, controller)
    extension._validation_receipt_checkpoint = {
        "baseline_identities": controller.identities
    }
    combo_model = _IndexModel(0)
    extension._visualization_combo = _Combo(combo_model)

    async def run_sequence():
        await extension._run_validation_receipt_acceptance_session2()
        extension._begin_validation_receipt_consumer_action(VisualizationMode.SMOKE)
        smoke_result = await controller.request_visualization_mode_in_kit(
            VisualizationMode.SMOKE
        )
        extension._complete_validation_receipt_consumer_action(
            VisualizationMode.SMOKE, smoke_result
        )
        assert "TEST COMPLETE" not in "\n".join(messages)

        combo_model.set_value(0)
        extension._begin_validation_receipt_consumer_action(VisualizationMode.NORMAL)
        normal_result = await controller.request_visualization_mode_in_kit(
            VisualizationMode.NORMAL
        )
        extension._complete_validation_receipt_consumer_action(
            VisualizationMode.NORMAL, normal_result
        )

    asyncio.run(run_sequence())

    events = "\n".join(messages)
    assert events.count("TEST COMPLETE") == 1
    assert "persisted_receipt_consumer_check=PASS" in events
    assert 'Select "Normal" in "Visualization"' in events
    assert controller.visualization_snapshot().committed is VisualizationMode.NORMAL
    assert controller._flow_lifecycle_state == "DETACHED"
    assert combo_model.get_value_as_int() == 0
    assert controller.checkpoint_cleared is True


def test_failed_smoke_consumer_check_cannot_complete(monkeypatch):
    module = _load_extension(monkeypatch)
    messages = []
    module.carb.log_warn = messages.append
    controller = _AcceptanceController(consumer_pass=False)
    extension = _acceptance_extension(module, controller)
    extension._validation_receipt_checkpoint = {
        "baseline_identities": controller.identities
    }

    async def run_failure():
        await extension._run_validation_receipt_acceptance_session2()
        extension._begin_validation_receipt_consumer_action(VisualizationMode.SMOKE)
        result = await controller.request_visualization_mode_in_kit(
            VisualizationMode.SMOKE
        )
        extension._complete_validation_receipt_consumer_action(
            VisualizationMode.SMOKE, result
        )

    asyncio.run(run_failure())

    events = "\n".join(messages)
    assert "real Smoke Attach failed" in events
    assert "TEST COMPLETE" not in events
    assert controller.checkpoint_cleared is False


def test_normal_cleanup_must_succeed_before_test_complete(monkeypatch):
    module = _load_extension(monkeypatch)
    messages = []
    module.carb.log_warn = messages.append
    controller = _AcceptanceController(normal_cleanup_pass=False)
    extension = _acceptance_extension(module, controller)
    extension._validation_receipt_checkpoint = {
        "baseline_identities": controller.identities
    }
    extension._visualization_combo = _Combo(_IndexModel(0))

    async def run_sequence():
        await extension._run_validation_receipt_acceptance_session2()
        extension._begin_validation_receipt_consumer_action(VisualizationMode.SMOKE)
        smoke_result = await controller.request_visualization_mode_in_kit(
            VisualizationMode.SMOKE
        )
        extension._complete_validation_receipt_consumer_action(
            VisualizationMode.SMOKE, smoke_result
        )
        extension._begin_validation_receipt_consumer_action(VisualizationMode.NORMAL)
        normal_result = await controller.request_visualization_mode_in_kit(
            VisualizationMode.NORMAL
        )
        extension._complete_validation_receipt_consumer_action(
            VisualizationMode.NORMAL, normal_result
        )

    asyncio.run(run_sequence())

    events = "\n".join(messages)
    assert "Flow lifecycle is not detached" in events
    assert "TEST COMPLETE" not in events


def test_session_two_rejects_resource_identity_change_before_validation(monkeypatch):
    module = _load_extension(monkeypatch)
    messages = []
    module.carb.log_warn = messages.append
    controller = _AcceptanceController()
    extension = _acceptance_extension(module, controller)
    extension._validation_receipt_checkpoint = {
        "baseline_identities": {"vti": {"server/load_normal": "changed"}}
    }
    starts = []
    extension._start_validation_receipt_background_work = lambda: starts.append(True)

    asyncio.run(extension._run_validation_receipt_acceptance_session2())

    events = "\n".join(messages)
    assert "Acceptance input changed between sessions" in events
    assert "TEST COMPLETE" not in events
    assert starts == []


def test_session_two_is_not_ready_when_persisted_store_is_incomplete(monkeypatch):
    module = _load_extension(monkeypatch)
    messages = []
    module.carb.log_warn = messages.append
    controller = _AcceptanceController(coverage_valid=False)
    extension = _acceptance_extension(module, controller)
    extension._validation_receipt_checkpoint = {
        "baseline_identities": controller.identities
    }

    asyncio.run(extension._run_validation_receipt_acceptance_session2())

    events = "\n".join(messages)
    assert "Persisted receipt store does not cover" in events
    assert "| READY" not in events
    assert "TEST COMPLETE" not in events


def test_phase42_guidance_is_silent_while_receipt_acceptance_owns_actions(
    monkeypatch,
):
    module = _load_extension(monkeypatch)
    messages = []
    module.carb.log_warn = messages.append
    extension = module.DigitalTwinRuntimeSuiteExtension()
    extension._validation_receipt_acceptance_owns_actions = True
    extension._visualization_acceptance = None

    extension._announce_visualization_acceptance_when_ready(SimpleNamespace())

    assert extension._visualization_acceptance is None
    assert messages == []


def test_startup_summary_counts_persisted_origin_once(monkeypatch):
    module = _load_extension(monkeypatch)
    messages = []
    module.carb.log_warn = messages.append
    controller = _AcceptanceController()
    extension = _acceptance_extension(module, controller)
    extension._streamlines_cache_validation_task = None

    asyncio.run(extension._report_validation_receipt_startup_summary())

    summary = "\n".join(messages)
    assert "persisted_reused=4" in summary
    assert "session_reused=0" in summary


def test_next_clean_restart_stays_normal_without_primary_request(monkeypatch):
    module = _load_extension(monkeypatch)
    controller = _AcceptanceController()
    extension = _acceptance_extension(module, controller)
    extension._validation_receipt_checkpoint = None
    extension._validation_receipt_acceptance_owns_actions = False

    extension._initialize_validation_receipt_acceptance()

    assert controller.visualization_requests == []
    assert controller.visualization_snapshot().committed is VisualizationMode.NORMAL
    assert controller.visualization_snapshot().pending is None
    assert controller._flow_lifecycle_state == "DETACHED"


def _acceptance_extension(module, controller):
    extension = module.DigitalTwinRuntimeSuiteExtension()
    extension._controller = controller
    extension._airflow_background_validation_task = None
    extension._streamlines_receipt_sweep_task = None
    extension._validation_receipt_acceptance_owns_actions = True
    extension._updating_visualization_mode = False
    extension._visualization_combo = _Combo(_IndexModel(0))
    extension._start_validation_receipt_background_work = lambda: None

    async def finished(_session_name):
        return True

    extension._wait_for_validation_receipt_tasks = finished
    return extension


class _AcceptanceController:
    def __init__(
        self,
        *,
        expensive_vti_calls: int = 0,
        coverage_valid: bool = True,
        consumer_pass: bool = True,
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
        self.coverage_valid = coverage_valid
        self.consumer_pass = consumer_pass
        self.normal_cleanup_pass = normal_cleanup_pass
        self.smoke_attach_calls = 0
        self.visualization_requests = []
        self._visualization_mode = VisualizationMode.NORMAL
        self._flow_lifecycle_state = "DETACHED"
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
        valid_count = 4 if self.coverage_valid else 3
        return {
            "vti_valid": valid_count,
            "vti_total": 4,
            "streamlines_valid": valid_count,
            "streamlines_total": 4,
        }

    def validation_receipt_metrics_snapshot(self):
        return self._metrics

    async def request_visualization_mode_in_kit(
        self,
        mode,
        status_callback=None,
    ):
        mode = mode if isinstance(mode, VisualizationMode) else VisualizationMode(mode)
        self.visualization_requests.append(mode)
        if mode is VisualizationMode.SMOKE:
            self.smoke_attach_calls += 1
            if self.consumer_pass:
                self._visualization_mode = mode
                self._flow_lifecycle_state = "ATTACHED"
        elif mode is VisualizationMode.NORMAL:
            self._visualization_mode = mode
            if self.normal_cleanup_pass:
                self._flow_lifecycle_state = "DETACHED"
        if status_callback:
            status_callback("Importing initial Nominal VTI through Kit-CAE")
        return SimpleNamespace(
            success=(
                self.consumer_pass
                if mode is VisualizationMode.SMOKE
                else self.normal_cleanup_pass
            ),
            message=(
                "Visualization transition passed."
                if self.consumer_pass and self.normal_cleanup_pass
                else "Visualization transition failed."
            ),
        )

    def visualization_snapshot(self):
        return SimpleNamespace(committed=self._visualization_mode, pending=None)

    def primary_visualization_presentation_snapshot_in_kit(self):
        smoke_active = self._flow_lifecycle_state == "ATTACHED"
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
            kit_cae_grid_contract_passed=self.consumer_pass,
            flow_initial_readiness_passed=self.consumer_pass,
        )

    def write_validation_receipt_acceptance_checkpoint(self, payload):
        self.checkpoint = payload

    def clear_validation_receipt_acceptance_checkpoint(self):
        self.checkpoint_cleared = True


class _IndexModel:
    def __init__(self, value: int) -> None:
        self._value = value

    def get_value_as_int(self):
        return self._value

    def set_value(self, value):
        self._value = int(value)


class _ComboModel:
    def __init__(self, index_model) -> None:
        self._index_model = index_model

    def get_item_value_model(self, _item):
        return self._index_model


class _Combo:
    def __init__(self, index_model) -> None:
        self.model = _ComboModel(index_model)


def _load_extension(monkeypatch):
    carb = types.ModuleType("carb")
    carb.log_warn = lambda _message: None
    carb.log_error = lambda _message: None
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
    spec = importlib.util.spec_from_file_location(
        "validation_receipt_acceptance_extension",
        path,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
