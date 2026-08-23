"""Focused Stage 08 attached workload-transition contracts."""

from __future__ import annotations

import asyncio
import re
import sys
import types

import pytest

from digital_twin_runtime_suite.app.airflow_validation import family as airflow_family
from digital_twin_runtime_suite.app.commands import RuntimeController
from digital_twin_runtime_suite.app.flow import runtime as flow_runtime
from digital_twin_runtime_suite.app.flow import smoke as flow_smoke
from digital_twin_runtime_suite.app.flow import temporal
from digital_twin_runtime_suite.app.flow import validation as flow_validation
from digital_twin_runtime_suite.app.flow import workload_transition
from digital_twin_runtime_suite.app.flow.progress import (
    TemporalProofProgress,
    TemporalProofState,
)
from digital_twin_runtime_suite.app.flow.runtime import SimulationCacheResult
from digital_twin_runtime_suite.app.smoke import runtime as smoke_runtime
from digital_twin_runtime_suite.app.workload_binding.background_validation import (
    BackgroundValidationError,
)


def test_detached_workload_change_does_not_auto_attach():
    controller = RuntimeController("configs/digital_twin_runtime_suite.toml")
    controller.set_workload_source(lambda: "Nominal")

    result = asyncio.run(
        controller.request_attached_workload_transition_in_kit("Critical")
    )

    assert result.success is True
    assert controller._flow_lifecycle_state == "DETACHED"
    assert controller._flow_session_workload_binding is None
    assert controller._flow_pending_workload_binding is None


def test_attached_transition_preserves_playback_intent_until_resume():
    async def scenario():
        controller = _attached_transition_controller()
        target = controller.resolve_workload_airflow_binding("Critical")
        controller._flow_pending_workload_binding = target
        controller._flow_active_transition_id = "T0001"
        timeline = _FakeTimeline(playing=False)
        update_entered = asyncio.Event()
        allow_update = asyncio.Event()
        updates = 0

        async def next_update_async():
            nonlocal updates
            updates += 1
            update_entered.set()
            await allow_update.wait()

        waiting = asyncio.create_task(
            controller._wait_for_attached_airflow_playback(
                timeline, next_update_async, "T0001", target
            )
        )
        await update_entered.wait()
        assert not waiting.done()
        assert timeline.is_playing() is False

        timeline.playing = True
        allow_update.set()
        assert await waiting is True
        assert updates == 1
        assert timeline.is_playing() is True

        async def unexpected_update():
            raise AssertionError("Playing transition must not wait or pause timeline.")

        assert (
            await controller._wait_for_attached_airflow_playback(
                timeline, unexpected_update, "T0001", target
            )
            is True
        )

    asyncio.run(scenario())


def test_superseded_transition_cannot_resume_from_paused_playback_wait():
    async def scenario():
        controller = _attached_transition_controller()
        controller.set_workload_source(lambda: "Idle")
        surge = controller.resolve_workload_airflow_binding("Surge")
        idle = controller.resolve_workload_airflow_binding("Idle")
        controller._flow_pending_workload_binding = surge
        controller._flow_active_transition_id = "T0001"
        timeline = _FakeTimeline(playing=False)
        update_entered = asyncio.Event()
        allow_update = asyncio.Event()

        async def next_update_async():
            update_entered.set()
            await allow_update.wait()

        waiting = asyncio.create_task(
            controller._wait_for_attached_airflow_playback(
                timeline, next_update_async, "T0001", surge
            )
        )
        await update_entered.wait()
        controller._flow_active_transition_id = "T0002"
        controller._flow_pending_workload_binding = idle
        timeline.playing = True
        allow_update.set()

        assert await waiting is False
        assert controller.airflow_transition_state() == {
            "semantic_workload": "Idle",
            "active_airflow_selector": "server/load_normal",
            "pending_airflow_selector": "server/load_idle",
        }

    asyncio.run(scenario())


def test_normalized_phase_mapper_preserves_same_count_boundary_behavior():
    assert airflow_family.next_normalized_phase_target_sample_index(64, 80, 80) == 65
    assert airflow_family.next_normalized_phase_target_sample_index(65, 80, 80) == 66
    assert airflow_family.next_normalized_phase_target_sample_index(79, 80, 80) == 0


def test_normalized_phase_mapper_maps_unequal_sample_counts_deterministically():
    assert airflow_family.normalized_phase_target_sample_index(40, 80, 160) == 80
    assert airflow_family.normalized_phase_target_sample_index(40, 80, 96) == 48
    assert airflow_family.normalized_phase_target_sample_index(48, 96, 112) == 56
    assert airflow_family.normalized_phase_target_sample_index(79, 80, 96) == 95
    assert airflow_family.normalized_phase_target_sample_index(0, 80, 128) == 0


def test_retargeted_sequence_keeps_target_dataset_after_the_commit_boundary(tmp_path):
    stage = _FakeStage()
    field_prim = _FakeFieldPrim()
    source_paths = tuple(tmp_path / f"source_{index}.vti" for index in range(4))
    target_paths = tuple(tmp_path / f"target_{index}.vti" for index in range(4))
    time_codes = (0.0, 10.0, 20.0, 30.0)
    active_index = 3
    target_index = temporal.next_temporal_sample_index(active_index, len(time_codes))
    for path, time_code in zip(source_paths, time_codes):
        field_prim.file_names.values[time_code] = [_FakeAssetPath(path)]

    stage.SetEditTarget(stage.GetSessionLayer())
    temporal.author_kit_cae_temporal_velocity_samples_except_index(
        field_prim,
        target_paths,
        time_codes,
        active_index,
        _FakeCaeVtk,
        _FakeSdf,
        _FakeUsd,
    )
    stage.SetEditTarget(stage.GetEditTarget())

    async def sync_active_controller():
        return True

    result = asyncio.run(
        temporal.retarget_kit_cae_temporal_source_in_place(
            stage,
            field_prim,
            target_paths[target_index],
            time_codes[target_index],
            _FakeCaeVtk,
            _FakeSdf,
            _FakeUsd,
            sync_active_controller=sync_active_controller,
        )
    )
    asyncio.run(
        temporal.retarget_kit_cae_temporal_source_in_place(
            stage,
            field_prim,
            target_paths[active_index],
            time_codes[active_index],
            _FakeCaeVtk,
            _FakeSdf,
            _FakeUsd,
            sync_active_controller=sync_active_controller,
        )
    )

    assert result.resolved_source == target_paths[target_index]
    assert [
        field_prim.file_names.values[time_code][0].path for time_code in time_codes
    ] == [path.as_posix() for path in target_paths]


def test_commit_requires_runtime_consumption_and_never_invokes_lifecycle():
    controller = RuntimeController("configs/digital_twin_runtime_suite.toml")
    active = controller.resolve_workload_airflow_binding("Nominal")
    target = controller.resolve_workload_airflow_binding("Critical")
    controller._flow_session_workload_binding = active
    controller._flow_pending_workload_binding = target

    assert controller._commit_attached_workload_transition(target, False) is False
    assert controller._flow_session_workload_binding == active
    assert controller._flow_pending_workload_binding == target
    assert controller._commit_attached_workload_transition(target, True) is True
    assert controller._flow_session_workload_binding == target
    assert controller._flow_pending_workload_binding is None


def test_active_pending_and_semantic_state_are_truthful_after_transition_commit():
    controller = RuntimeController("configs/digital_twin_runtime_suite.toml")
    controller.set_workload_source(lambda: "Critical")
    controller._flow_session_workload_binding = (
        controller.resolve_workload_airflow_binding("Nominal")
    )
    controller._flow_pending_workload_binding = (
        controller.resolve_workload_airflow_binding("Critical")
    )

    assert controller.airflow_transition_state() == {
        "semantic_workload": "Critical",
        "active_airflow_selector": "server/load_normal",
        "pending_airflow_selector": "server/load_critical",
    }
    controller._commit_attached_workload_transition(
        controller._flow_pending_workload_binding, True
    )

    assert controller.airflow_transition_state() == {
        "semantic_workload": "Critical",
        "active_airflow_selector": "server/load_critical",
        "pending_airflow_selector": None,
    }


def test_attached_target_failure_keeps_previous_airflow_and_clears_pending():
    controller = RuntimeController("configs/digital_twin_runtime_suite.toml")
    controller.set_workload_source(lambda: "Critical")
    active = controller.resolve_workload_airflow_binding("Nominal")
    target = controller.resolve_workload_airflow_binding("Critical")
    controller._flow_lifecycle_state = "ATTACHED"
    controller._flow_session_workload_binding = active
    controller._flow_pending_workload_binding = target

    logs: list[str] = []
    result = controller._finalize_airflow_failure(
        semantic_workload="Critical",
        requested_binding=target,
        reason="VTI validation failed",
        failure_stage="validation",
        logger=logs.append,
    )

    assert result.success is False
    assert controller.airflow_transition_state() == {
        "semantic_workload": "Critical",
        "active_airflow_selector": "server/load_normal",
        "pending_airflow_selector": None,
    }
    assert controller.airflow_failure_state() == {
        "semantic_workload": "Critical",
        "requested_airflow_selector": "server/load_critical",
        "active_airflow_selector": "server/load_normal",
        "reason": "VTI validation failed",
        "failure_stage": "validation",
        "action": "kept_previous_safe_dataset",
    }
    assert "DTRS AIRFLOW TRANSITION" in logs[0]
    assert "process=WORKLOAD | state=FAILED" in logs[0]
    assert "telemetry_rolled_back=" in logs[0]
    assert "pending_cleared=" in logs[0]
    assert "flow_reset=" in logs[0]
    assert "result=FAIL" in logs[0]


def test_detached_attach_failure_remains_detached_without_workload_rollback():
    controller = RuntimeController("configs/digital_twin_runtime_suite.toml")
    controller.set_workload_source(lambda: "Surge")
    target = controller.resolve_workload_airflow_binding("Surge")

    result = controller._finalize_airflow_failure(
        semantic_workload="Surge",
        requested_binding=target,
        reason="manifest is invalid",
        failure_stage="dataset_discovery",
    )

    assert result.success is False
    assert controller._flow_lifecycle_state == "DETACHED"
    assert controller._flow_session_workload_binding is None
    assert controller._flow_pending_workload_binding is None
    assert controller.airflow_transition_state()["semantic_workload"] == "Surge"
    assert controller.airflow_failure_state()["action"] == "remained_detached"


def test_failure_does_not_invoke_lifecycle_and_next_matching_request_is_accepted(
    monkeypatch,
):
    controller = RuntimeController("configs/digital_twin_runtime_suite.toml")
    active = controller.resolve_workload_airflow_binding("Nominal")
    target = controller.resolve_workload_airflow_binding("Critical")
    controller._flow_lifecycle_state = "ATTACHED"
    controller._flow_session_workload_binding = active
    controller._flow_pending_workload_binding = target
    controller.detach_simulation_cache_in_kit = lambda: (_ for _ in ()).throw(
        AssertionError()
    )
    controller.reset_simulation_cache_in_kit = lambda: (_ for _ in ()).throw(
        AssertionError()
    )

    controller._finalize_airflow_failure(
        semantic_workload="Critical",
        requested_binding=target,
        reason="target cannot proceed safely",
        failure_stage="runtime_transition",
    )

    monkeypatch.setitem(sys.modules, "carb", types.SimpleNamespace())
    controller._live_flow_consumer_matches_dataset = lambda _dataset: (
        True,
        "normal_0.vti",
    )
    result = asyncio.run(
        controller.request_attached_workload_transition_in_kit("Nominal")
    )
    assert result.success is True
    assert controller._flow_pending_workload_binding is None


def test_attached_validation_failure_never_retargets_or_mutates_safe_runtime(
    monkeypatch,
):
    controller = _attached_transition_controller()
    _install_fake_carb(monkeypatch)
    _mock_transition_dataset_signature(monkeypatch, controller)
    retarget_calls: list[object] = []
    lifecycle_calls: list[str] = []

    async def validation_failure(_binding):
        raise BackgroundValidationError("critical VTI checksum mismatch")

    async def retarget(*_args):
        retarget_calls.append(object())
        return SimulationCacheResult(True, "unexpected")

    controller.acquire_airflow_validation_for_transition = validation_failure
    controller._retarget_attached_workload_in_kit = retarget
    controller.detach_simulation_cache_in_kit = lambda: lifecycle_calls.append("detach")
    controller.reset_simulation_cache_in_kit = lambda: lifecycle_calls.append("reset")
    monkeypatch.setattr(
        smoke_runtime.smoke_flow,
        "apply_kit_cae_direct_attach_velocity_scale",
        lambda *_args, **_kwargs: lifecycle_calls.append("velocityScale"),
    )

    statuses: list[str] = []
    result = asyncio.run(
        controller.request_attached_workload_transition_in_kit(
            "Critical", statuses.append
        )
    )

    assert result.success is False
    assert "critical VTI checksum mismatch" in result.message
    assert statuses == [result.message]
    assert retarget_calls == []
    assert lifecycle_calls == []
    assert controller.airflow_transition_state() == {
        "semantic_workload": "Critical",
        "active_airflow_selector": "server/load_normal",
        "pending_airflow_selector": None,
    }
    assert controller.airflow_failure_state()["failure_stage"] == "validation"


def test_cache_miss_can_validate_and_continue_to_normal_transition(monkeypatch):
    controller = _attached_transition_controller()
    target = controller.resolve_workload_airflow_binding("Critical")
    _install_fake_carb(monkeypatch)
    _mock_transition_dataset_signature(monkeypatch, controller)
    validation_calls: list[str] = []
    retarget_calls: list[str] = []

    async def validation_pass(binding):
        validation_calls.append(binding.dataset_identity)
        return _FakeValidationLease()

    async def transition_pass(active, requested, *_args):
        retarget_calls.append(requested.dataset_identity)
        assert controller._commit_attached_workload_transition(requested, True)
        return SimulationCacheResult(True, "transition committed")

    controller.acquire_airflow_validation_for_transition = validation_pass
    controller._retarget_attached_workload_in_kit = transition_pass

    result = asyncio.run(
        controller.request_attached_workload_transition_in_kit("Critical")
    )

    assert result.success is True
    assert validation_calls == [target.dataset_identity]
    assert retarget_calls == [target.dataset_identity]
    assert controller.airflow_transition_state() == {
        "semantic_workload": "Critical",
        "active_airflow_selector": "server/load_critical",
        "pending_airflow_selector": None,
    }
    assert controller.airflow_failure_state() is None


def test_transition_is_gated_by_active_target_pair_compatibility(monkeypatch):
    controller = _attached_transition_controller()
    _install_fake_carb(monkeypatch)
    _mock_transition_dataset_signature(monkeypatch, controller)
    retarget_calls: list[object] = []

    async def validation_pass(_binding):
        return _FakeValidationLease()

    async def unexpected_retarget(*_args):
        retarget_calls.append(object())
        return SimulationCacheResult(True, "unexpected")

    def incompatible_pair(**_kwargs):
        raise flow_runtime.AirflowDatasetFamilyCompatibilityError(
            "Airflow family compatibility mismatch: dataset=server/load_critical; "
            "property=spacing; expected=(0.01, 0.01, 0.01); "
            "actual=(0.02, 0.01, 0.01)."
        )

    controller.acquire_airflow_validation_for_transition = validation_pass
    controller.validate_attached_airflow_transition_pair = incompatible_pair
    controller.validate_registered_airflow_dataset_family = lambda: (
        _ for _ in ()
    ).throw(AssertionError("Live pair transitions must not require global readiness."))
    controller._retarget_attached_workload_in_kit = unexpected_retarget

    result = asyncio.run(
        controller.request_attached_workload_transition_in_kit("Critical")
    )

    assert result.success is False
    assert "dataset=server/load_critical; property=spacing" in result.message
    assert retarget_calls == []
    assert controller.airflow_transition_state() == {
        "semantic_workload": "Critical",
        "active_airflow_selector": "server/load_normal",
        "pending_airflow_selector": None,
    }
    assert controller.airflow_failure_state()["failure_stage"] == "family_compatibility"


def test_missing_transition_target_reports_dataset_discovery_failure(monkeypatch):
    controller = _attached_transition_controller()
    _install_fake_carb(monkeypatch)
    target = controller.resolve_workload_airflow_binding("Critical")
    retarget_calls: list[object] = []

    def missing_dataset(*_args):
        raise flow_runtime.AirflowDatasetError("server/load_critical is absent")

    async def retarget(*_args):
        retarget_calls.append(object())
        return SimulationCacheResult(True, "unexpected")

    monkeypatch.setattr(controller._airflow_state, "resolve_target", missing_dataset)
    controller._retarget_attached_workload_in_kit = retarget

    result = asyncio.run(
        controller.request_attached_workload_transition_in_kit("Critical")
    )

    assert result.success is False
    assert "server/load_critical is absent" in result.message
    assert retarget_calls == []
    assert controller.airflow_failure_state() == {
        "semantic_workload": "Critical",
        "requested_airflow_selector": target.dataset_identity,
        "active_airflow_selector": "server/load_normal",
        "reason": "server/load_critical is absent",
        "failure_stage": "dataset_discovery",
        "action": "kept_previous_safe_dataset",
    }
    assert controller._flow_pending_workload_binding is None


def test_detached_attach_validation_failure_remains_detached_without_partial_runtime(
    monkeypatch,
):
    controller = RuntimeController("configs/digital_twin_runtime_suite.toml")
    controller.set_workload_source(lambda: "Surge")
    _install_fake_carb(monkeypatch)
    lifecycle_calls: list[str] = []

    async def validation_failure(_binding):
        raise BackgroundValidationError("surge preflight failed")

    controller.acquire_airflow_validation_for_attach = validation_failure
    controller.detach_simulation_cache_in_kit = lambda: lifecycle_calls.append("detach")
    controller.reset_simulation_cache_in_kit = lambda: lifecycle_calls.append("reset")

    result = asyncio.run(controller._attach_kit_cae_airflow_in_kit())

    assert result.success is False
    assert "surge preflight failed" in result.message
    assert controller._flow_lifecycle_state == "DETACHED"
    assert controller._flow_session_workload_binding is None
    assert controller._flow_pending_workload_binding is None
    assert controller.airflow_transition_state()["semantic_workload"] == "Surge"
    assert controller.airflow_failure_state()["failure_stage"] == "validation"
    assert lifecycle_calls == []


def test_detached_attach_reconciles_streamlines_committed_target(monkeypatch):
    """Attach must not skip Flow when Streamlines already proved the target."""

    controller = RuntimeController("configs/digital_twin_runtime_suite.toml")
    controller.set_workload_source(lambda: "Nominal")
    _install_fake_carb(monkeypatch)
    target = controller._airflow_state.resolve_target(
        controller.resolve_workload_airflow_binding("Nominal")
    )
    assert controller._airflow_state.commit_target(target) is True
    calls: list[str] = []

    async def validation_pass(_binding):
        calls.append("validation")
        return _FakeValidationLease()

    async def attach_pass(binding, _dataset, _status_callback):
        calls.append("attach")
        assert binding == target.binding
        return SimulationCacheResult(True, "Flow attached")

    controller.acquire_airflow_validation_for_attach = validation_pass
    controller._attach_kit_cae_airflow_after_validation_in_kit = attach_pass

    result = asyncio.run(controller._attach_kit_cae_airflow_in_kit())

    assert result.success is True
    assert calls == ["validation", "attach"]
    assert controller._airflow_state.committed == target
    assert controller._airflow_state.pending is None


def test_successful_recovery_after_failure_accepts_the_same_target(monkeypatch):
    controller = _attached_transition_controller()
    _install_fake_carb(monkeypatch)
    _mock_transition_dataset_signature(monkeypatch, controller)

    async def validation_failure(_binding):
        raise BackgroundValidationError("first request failed")

    controller.acquire_airflow_validation_for_transition = validation_failure
    failed = asyncio.run(
        controller.request_attached_workload_transition_in_kit("Critical")
    )
    assert failed.success is False
    assert controller._flow_pending_workload_binding is None

    async def validation_pass(_binding):
        return _FakeValidationLease()

    async def transition_pass(_active, requested, *_args):
        assert controller._commit_attached_workload_transition(requested, True)
        return SimulationCacheResult(True, "transition committed")

    controller.acquire_airflow_validation_for_transition = validation_pass
    controller._retarget_attached_workload_in_kit = transition_pass
    recovered = asyncio.run(
        controller.request_attached_workload_transition_in_kit("Critical")
    )

    assert recovered.success is True
    assert controller.airflow_transition_state()["active_airflow_selector"] == (
        "server/load_critical"
    )
    assert controller.airflow_transition_state()["pending_airflow_selector"] is None
    assert controller.airflow_failure_state() is None


def test_already_active_request_does_not_start_validation_or_retarget(monkeypatch):
    controller = _attached_transition_controller(workload="Nominal")
    _install_fake_carb(monkeypatch)
    calls: list[str] = []

    async def unexpected_validation(_binding):
        calls.append("validation")
        return _FakeValidationLease()

    async def unexpected_retarget(*_args):
        calls.append("retarget")
        return SimulationCacheResult(True, "unexpected")

    controller.acquire_airflow_validation_for_transition = unexpected_validation
    controller._retarget_attached_workload_in_kit = unexpected_retarget
    controller._live_flow_consumer_matches_dataset = lambda _dataset: (
        True,
        "normal_0.vti",
    )

    result = asyncio.run(
        controller.request_attached_workload_transition_in_kit("Nominal")
    )

    assert result.success is True
    assert calls == []
    assert controller._flow_pending_workload_binding is None


def test_same_workload_with_live_mismatch_enters_reconciliation(monkeypatch):
    controller = _attached_transition_controller(workload="Nominal")
    _install_fake_carb(monkeypatch)
    _mock_transition_dataset_signature(monkeypatch, controller)
    calls: list[str] = []

    async def validation(_binding):
        calls.append("validation")
        return _FakeValidationLease()

    async def repair(_active, requested, *_args):
        calls.append("retarget")
        assert controller._commit_attached_workload_transition(requested, True)
        return SimulationCacheResult(True, "Normal runtime reconciled")

    controller._live_flow_consumer_matches_dataset = lambda _dataset: (
        False,
        "critical_1081.vti",
    )
    controller.acquire_airflow_validation_for_transition = validation
    controller._retarget_attached_workload_in_kit = repair

    result = asyncio.run(
        controller.request_attached_workload_transition_in_kit("Nominal")
    )

    assert result.success is True
    assert calls == ["validation", "retarget"]
    assert controller.airflow_transition_state()["active_airflow_selector"] == (
        "server/load_normal"
    )
    assert controller.airflow_transition_state()["pending_airflow_selector"] is None


def test_transition_log_block_has_structured_authoritative_fields():
    message = RuntimeController._format_airflow_transition_log_block(
        "COMMIT",
        (
            ("Active airflow:", "server/load_critical"),
            ("Pending airflow:", "None"),
            ("Runtime source:", "critical_1651.vti"),
            ("Runtime consumed:", True),
            ("RESULT:", "PASS"),
        ),
    )

    assert "DTRS AIRFLOW TRANSITION" in message
    assert "process=WORKLOAD | state=COMMIT" in message
    assert "active_airflow=server/load_critical" in message
    assert "runtime_source=critical_1651.vti" in message
    assert "result=PASS" in message
    assert re.search(
        r"Local time: \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} [+-]\d{2}:\d{2}",
        message,
    )


def test_completed_temporal_proof_is_not_repeated_in_periodic_performance_logs():
    controller = RuntimeController("configs/digital_twin_runtime_suite.toml")
    controller._flow_last_temporal_proof_selector = "server/load_normal"
    controller._flow_temporal_progress = TemporalProofProgress(
        state=TemporalProofState.PASSED,
        validated_sample_count=80,
        total_sample_count=80,
        current_asset_name="server_airflow_velocity_normal_1791.vti",
        loop_closure_state="PASS",
    )

    assert controller._last_temporal_proof_log_fields() == ()

    controller._flow_temporal_progress = TemporalProofProgress()
    assert controller._last_temporal_proof_log_fields() == ()


def test_running_temporal_proof_is_superseded_with_partial_progress_before_transition():
    controller = RuntimeController("configs/digital_twin_runtime_suite.toml")
    generation = controller._flow_temporal_proof_generation
    controller._flow_temporal_progress = TemporalProofProgress(
        state=TemporalProofState.RUNNING,
        validated_sample_count=17,
        total_sample_count=80,
        current_asset_name="server_airflow_velocity_normal_1171.vti",
    )

    assert controller._cancel_kit_cae_temporal_proof(
        reason="SUPERSEDED_BY_WORKLOAD_TRANSITION"
    )

    progress = controller.temporal_proof_progress()
    assert progress.state is TemporalProofState.CANCELLED
    assert progress.failure_reason is None
    assert progress.loop_closure_state is None
    assert progress.cancellation_reason == "WORKLOAD_TRANSITION"
    assert progress.validated_sample_count == 17
    assert progress.total_sample_count == 80
    assert progress.validated_sample_count != progress.total_sample_count
    assert not controller._update_temporal_proof_progress(
        generation_id=generation,
        state=TemporalProofState.FAILED,
        total_sample_count=80,
        validated_sample_count=80,
        current_asset_name="server_airflow_velocity_normal_1791.vti",
        started_at=0.0,
    )
    assert controller.temporal_proof_progress().state is TemporalProofState.CANCELLED


def test_superseded_proof_cannot_block_transition_commit_state():
    controller = RuntimeController("configs/digital_twin_runtime_suite.toml")
    controller.set_workload_source(lambda: "Critical")
    active = controller.resolve_workload_airflow_binding("Nominal")
    target = controller.resolve_workload_airflow_binding("Critical")
    controller._flow_session_workload_binding = active
    controller._flow_pending_workload_binding = target
    controller._flow_temporal_progress = TemporalProofProgress(
        state=TemporalProofState.CHECKING_LOOP_CLOSURE,
        validated_sample_count=41,
        total_sample_count=80,
    )

    controller._cancel_kit_cae_temporal_proof(
        reason="SUPERSEDED_BY_WORKLOAD_TRANSITION"
    )

    assert controller._commit_attached_workload_transition(target, True)
    assert controller.airflow_transition_state() == {
        "semantic_workload": "Critical",
        "active_airflow_selector": "server/load_critical",
        "pending_airflow_selector": None,
    }
    assert controller.temporal_proof_progress().state is TemporalProofState.CANCELLED


def test_runtime_contract_prevents_transition_commit():
    controller = RuntimeController("configs/digital_twin_runtime_suite.toml")
    active = controller.resolve_workload_airflow_binding("Nominal")
    target = controller.resolve_workload_airflow_binding("Critical")
    controller._flow_session_workload_binding = active
    controller._flow_pending_workload_binding = target

    assert not controller._commit_attached_workload_transition(
        target, True, runtime_contract_match=False
    )
    assert controller._flow_session_workload_binding == active
    assert controller._flow_pending_workload_binding == target
    assert controller._commit_attached_workload_transition(
        target, True, runtime_contract_match=True
    )


def test_runtime_proof_accepts_later_target_family_samples(tmp_path):
    critical = tuple(tmp_path / f"critical_{index}.vti" for index in range(3))

    proof = RuntimeController._evaluate_runtime_dataset_consumption_proof(
        critical,
        critical[0],
        (critical[1], critical[2]),
        operator_completion_delta=1,
        payload_digest_changed=True,
    )

    assert proof["target_family_observed"] is True
    assert proof["exact_target_sample_observed"] is False
    assert proof["target_family_boundaries"] == 2
    assert proof["foreign_family_source_observed"] is False
    assert proof["passed"] is True


def test_runtime_proof_initializes_payload_accumulator_before_observation(
    monkeypatch,
):
    async def scenario():
        controller = _attached_transition_controller()
        target = controller.resolve_workload_airflow_binding("Critical")
        controller._flow_pending_workload_binding = target
        transition_id = controller._flow_active_transition_id
        target_dataset = controller._airflow_state.resolve_target(target).dataset
        selected_source = target_dataset.velocity_vti_sequence_paths[1]

        async def next_update_async():
            return None

        app = types.SimpleNamespace(next_update_async=next_update_async)
        timeline = types.SimpleNamespace(
            is_playing=lambda: True,
            get_current_time=lambda: 0.0,
        )
        stage = types.SimpleNamespace(GetTimeCodesPerSecond=lambda: 1.0)
        payload_attr = types.SimpleNamespace(IsValid=lambda: True, Get=lambda: [1])
        monkeypatch.setattr(
            workload_transition.flow_temporal,
            "kit_cae_selected_velocity_asset",
            lambda *_args: selected_source,
        )
        controller._kit_cae_operator_completion_count = lambda _path: 1

        proof = await controller._await_runtime_dataset_consumption_proof(
            app=app,
            timeline=timeline,
            stage=stage,
            field_prim=object(),
            payload_attr=payload_attr,
            emitter_path="/DTRS_KitCAE/DataSetEmitter",
            expected_paths=target_dataset.velocity_vti_sequence_paths,
            initial_target_source=target_dataset.velocity_vti_sequence_paths[0],
            completions_before=0,
            payload_before_digest="before",
            cae_vtk=object(),
            Usd=object(),
            transition_id=transition_id,
            target_binding=target,
        )

        assert proof["payload_digest_changed"] is True
        assert proof["passed"] is True

    asyncio.run(scenario())


def test_unexpected_pre_mutation_exception_preserves_previous_state(monkeypatch):
    async def scenario():
        controller = _attached_transition_controller()
        _install_fake_carb(monkeypatch)
        _mock_transition_dataset_signature(monkeypatch, controller)

        async def unexpected_validation(_binding):
            raise ValueError("pre-mutation validation fault")

        controller.acquire_airflow_validation_for_transition = unexpected_validation

        result = await controller.request_attached_workload_transition_in_kit(
            "Critical"
        )

        assert result.success is False
        assert "pre-mutation validation fault" in result.message
        assert controller.airflow_transition_state() == {
            "semantic_workload": "Critical",
            "active_airflow_selector": "server/load_normal",
            "pending_airflow_selector": None,
        }

    asyncio.run(scenario())


def test_unexpected_post_mutation_exception_rolls_back_before_failure(monkeypatch):
    async def scenario():
        controller = _attached_transition_controller()
        _install_fake_carb(monkeypatch)
        target = controller.resolve_workload_airflow_binding("Critical")
        transition = controller._airflow_state.begin(
            controller._airflow_state.resolve_target(target)
        )
        assert transition is not None
        controller._flow_runtime_mutation_context = {
            "transition_id": transition.transition_id,
            "target_dataset": transition.target.dataset,
        }

        async def unexpected_request(*_args, **_kwargs):
            raise RuntimeError("post-mutation proof fault")

        async def verified_rollback(**_kwargs):
            return True, "previous dataset restored"

        controller._request_attached_workload_transition_in_kit = unexpected_request
        controller._rollback_attached_runtime_target_mutation = verified_rollback

        result = await controller.request_attached_workload_transition_in_kit(
            "Critical"
        )

        assert result.success is False
        assert "Rollback verified" in result.message
        assert controller.airflow_transition_state() == {
            "semantic_workload": "Critical",
            "active_airflow_selector": "server/load_normal",
            "pending_airflow_selector": None,
        }

    asyncio.run(scenario())


def test_runtime_proof_rejects_foreign_dataset_source(tmp_path):
    critical = tuple(tmp_path / f"critical_{index}.vti" for index in range(2))
    normal = tmp_path / "normal_0.vti"

    proof = RuntimeController._evaluate_runtime_dataset_consumption_proof(
        critical,
        critical[0],
        (critical[1], normal),
        operator_completion_delta=1,
        payload_digest_changed=True,
    )

    assert proof["foreign_family_source_observed"] is True
    assert proof["foreign_family_sources"] == ("normal_0.vti",)
    assert proof["passed"] is False


@pytest.mark.parametrize(
    ("completion_delta", "payload_changed"),
    ((0, True), (1, False)),
)
def test_runtime_proof_requires_operator_and_payload_evidence(
    tmp_path,
    completion_delta,
    payload_changed,
):
    critical = (tmp_path / "critical_0.vti",)

    proof = RuntimeController._evaluate_runtime_dataset_consumption_proof(
        critical,
        critical[0],
        critical,
        operator_completion_delta=completion_delta,
        payload_digest_changed=payload_changed,
    )

    assert proof["target_family_observed"] is True
    assert proof["passed"] is False


def test_runtime_proof_rejects_missing_target_dataset_observation(tmp_path):
    critical = (tmp_path / "critical_0.vti",)

    proof = RuntimeController._evaluate_runtime_dataset_consumption_proof(
        critical,
        critical[0],
        (),
        operator_completion_delta=1,
        payload_digest_changed=True,
    )

    assert proof["target_family_observed"] is False
    assert proof["last_observed_source"] == "unavailable"
    assert proof["passed"] is False


def test_verified_runtime_rollback_keeps_previous_committed_dataset(monkeypatch):
    async def scenario():
        controller = _attached_transition_controller()
        _install_fake_carb(monkeypatch)
        _mock_transition_dataset_signature(monkeypatch, controller)

        async def validate(_binding):
            return _FakeValidationLease()

        async def failed_retarget(*_args):
            return SimulationCacheResult(
                False,
                "Airflow transition is pending live runtime consumption. "
                "Rollback verified: previous committed dataset restored.",
            )

        controller.acquire_airflow_validation_for_transition = validate
        controller._retarget_attached_workload_in_kit = failed_retarget

        result = await controller.request_attached_workload_transition_in_kit(
            "Critical"
        )

        assert result.success is False
        assert controller.airflow_transition_state() == {
            "semantic_workload": "Critical",
            "active_airflow_selector": "server/load_normal",
            "pending_airflow_selector": None,
        }
        assert controller.airflow_failure_state()["action"] == (
            "kept_previous_safe_dataset"
        )

    asyncio.run(scenario())


def test_unreconciled_runtime_failure_clears_committed_consumer_truth(monkeypatch):
    async def scenario():
        controller = _attached_transition_controller()
        _install_fake_carb(monkeypatch)
        _mock_transition_dataset_signature(monkeypatch, controller)

        async def validate(_binding):
            return _FakeValidationLease()

        async def unreconciled_retarget(*_args):
            return SimulationCacheResult(
                False,
                "Airflow transition runtime reconciliation required: "
                "previous dataset did not pass runtime rollback proof.",
            )

        controller.acquire_airflow_validation_for_transition = validate
        controller._retarget_attached_workload_in_kit = unreconciled_retarget

        result = await controller.request_attached_workload_transition_in_kit(
            "Critical"
        )

        assert result.success is False
        assert "reconciliation required" in result.message
        assert controller.airflow_transition_state() == {
            "semantic_workload": "Critical",
            "active_airflow_selector": None,
            "pending_airflow_selector": None,
        }
        assert controller.airflow_failure_state()["action"] == (
            "runtime_reconciliation_required"
        )
        assert controller.airflow_failure_state()["active_airflow_selector"] == (
            "UNRECONCILED"
        )

    asyncio.run(scenario())


def test_target_family_proof_requires_full_ordered_loop_without_foreign_source(
    tmp_path,
):
    expected = tuple(tmp_path / f"critical_{index}.vti" for index in range(4))
    observed = (expected[2], expected[3], expected[0], expected[1])

    proof = RuntimeController._evaluate_target_family_proof(
        expected, 2, observed, runtime_contract_match=True
    )

    assert proof == {
        "samples_observed": "4/4",
        "foreign_family_samples": 0,
        "forward_transitions": 3,
        "loop_closure": "PASS",
        "runtime_contract_match": True,
        "last_source": "critical_1.vti",
        "passed": True,
    }
    failed = RuntimeController._evaluate_target_family_proof(
        expected,
        2,
        (expected[2], expected[3], tmp_path / "normal_0.vti", expected[1]),
        runtime_contract_match=True,
    )
    assert failed["foreign_family_samples"] == 1
    assert failed["loop_closure"] == "FAIL"
    assert failed["passed"] is False


def test_target_family_proof_reports_79_forward_steps_and_one_loop_closure(tmp_path):
    expected = tuple(tmp_path / f"critical_{index}.vti" for index in range(80))
    observed = expected[37:] + expected[:37]

    proof = RuntimeController._evaluate_target_family_proof(
        expected, 37, observed, runtime_contract_match=True
    )

    assert proof["samples_observed"] == "80/80"
    assert proof["foreign_family_samples"] == 0
    assert proof["forward_transitions"] == 79
    assert proof["loop_closure"] == "PASS"
    assert proof["passed"] is True


def test_target_runtime_contract_is_resolved_from_validated_vti_metadata():
    base_velocity_scale = (
        flow_validation.calculate_kit_cae_direct_attach_base_velocity_scale(
            (0.0, 10.0, 0.0, 20.0, 0.0, 20.0),
            10.0,
        )
    )

    contract = flow_validation.resolve_kit_cae_direct_attach_runtime_contract(
        {"kit_cae_direct_attach_base_velocity_scale": base_velocity_scale},
        velocity_scale_multiplier=1.25,
    )

    assert contract["base_velocity_scale"] == base_velocity_scale
    assert contract["effective_velocity_scale"] == base_velocity_scale * 1.25


def test_target_runtime_velocity_scale_uses_direct_attach_authoring_and_readback():
    emitter = _FakeVelocityScaleEmitter(initial=0.6315408945083618)

    applied = flow_smoke.apply_kit_cae_direct_attach_velocity_scale(
        emitter,
        base_velocity_scale=0.4954637613675828,
        velocity_scale_multiplier=1.0,
    )

    attribute = emitter.GetAttribute("velocityScale")
    assert applied == 0.4954637613675828
    assert attribute.Get() == 0.4954637613675828
    assert attribute.GetCustomDataByKey("omni:kit:locked") is True


def test_all_registered_transition_targets_resolve_without_prior_direct_attach():
    controller = RuntimeController("configs/digital_twin_runtime_suite.toml")
    controller.set_workload_source(lambda: "Nominal")
    assert not hasattr(controller, "_flow_direct_attach_base_velocity_scales")
    base_by_selector = {
        "server/load_idle": 0.4,
        "server/load_normal": 0.8,
        "server/load_surge": 1.2,
        "server/load_critical": 1.6,
    }
    metadata_by_selector = {
        selector: {"kit_cae_direct_attach_base_velocity_scale": base}
        for selector, base in base_by_selector.items()
    }
    controller._flow_session_workload_binding = (
        controller.resolve_workload_airflow_binding("Nominal")
    )
    direct_attach_normal = (
        flow_validation.resolve_kit_cae_direct_attach_runtime_contract(
            metadata_by_selector["server/load_normal"],
            controller.config.simulation_cache.smoke_tuning.velocity_scale_multiplier,
        )["effective_velocity_scale"]
    )

    for workload in ("Critical", "Idle", "Surge", "Nominal"):
        target = controller.resolve_workload_airflow_binding(workload)
        contract = flow_validation.resolve_kit_cae_direct_attach_runtime_contract(
            metadata_by_selector[target.dataset_identity],
            controller.config.simulation_cache.smoke_tuning.velocity_scale_multiplier,
        )
        assert (
            contract["base_velocity_scale"] == base_by_selector[target.dataset_identity]
        )
        controller._flow_pending_workload_binding = target
        assert controller._commit_attached_workload_transition(
            target,
            runtime_consumed=True,
            runtime_contract_match=True,
        )
        assert controller._flow_pending_workload_binding is None
        assert controller._flow_session_workload_binding == target

    returned_normal = flow_validation.resolve_kit_cae_direct_attach_runtime_contract(
        metadata_by_selector["server/load_normal"],
        controller.config.simulation_cache.smoke_tuning.velocity_scale_multiplier,
    )["effective_velocity_scale"]
    assert direct_attach_normal == returned_normal


@pytest.mark.parametrize(
    "checkpoint",
    ("validation", "sample_boundary", "after_retarget", "after_consumption"),
)
def test_superseded_transition_cannot_commit_after_async_barrier(
    monkeypatch, checkpoint
):
    async def scenario():
        current_workload = {"value": "Surge"}
        controller = _attached_transition_controller(workload="Surge")
        controller.set_workload_source(lambda: current_workload["value"])
        logs = _install_fake_carb(monkeypatch)
        _mock_transition_dataset_signature(monkeypatch, controller)
        entered = asyncio.Event()
        release = asyncio.Event()
        commits: list[str] = []

        async def validate(binding):
            if (
                binding.dataset_identity == "server/load_surge"
                and checkpoint == "validation"
            ):
                entered.set()
                await release.wait()
            return _FakeValidationLease()

        async def retarget(_active, target, *_args):
            if (
                target.dataset_identity == "server/load_surge"
                and checkpoint != "validation"
            ):
                entered.set()
                await release.wait()
            transition_id = _args[-1]
            if controller._commit_attached_workload_transition(
                target,
                True,
                transition_id=transition_id,
            ):
                commits.append(target.dataset_identity)
                return SimulationCacheResult(True, "transition committed")
            return controller._superseded_transition_result(transition_id, target)

        controller.acquire_airflow_validation_for_transition = validate
        controller._retarget_attached_workload_in_kit = retarget
        controller.detach_simulation_cache_in_kit = lambda: (_ for _ in ()).throw(
            AssertionError()
        )
        controller.reset_simulation_cache_in_kit = lambda: (_ for _ in ()).throw(
            AssertionError()
        )

        surge_task = asyncio.create_task(
            controller.request_attached_workload_transition_in_kit("Surge")
        )
        await entered.wait()
        current_workload["value"] = "Critical"
        critical_result = await controller.request_attached_workload_transition_in_kit(
            "Critical"
        )
        release.set()
        surge_result = await surge_task

        assert critical_result.success is True
        assert surge_result.success is True
        assert commits == ["server/load_critical"]
        assert controller.airflow_transition_state() == {
            "semantic_workload": "Critical",
            "active_airflow_selector": "server/load_critical",
            "pending_airflow_selector": None,
        }
        assert any("process=WORKLOAD | state=SUPERSEDED" in log for log in logs)
        assert any("old_commit_allowed=False" in log for log in logs)

    asyncio.run(scenario())


def test_rapid_surge_critical_idle_only_idle_commits(monkeypatch):
    async def scenario():
        current_workload = {"value": "Surge"}
        controller = _attached_transition_controller(workload="Surge")
        controller.set_workload_source(lambda: current_workload["value"])
        _install_fake_carb(monkeypatch)
        _mock_transition_dataset_signature(monkeypatch, controller)
        entered_surge = asyncio.Event()
        entered_critical = asyncio.Event()
        release_surge = asyncio.Event()
        release_critical = asyncio.Event()
        commits: list[str] = []

        async def validate(_binding):
            return _FakeValidationLease()

        async def retarget(_active, target, *_args):
            transition_id = _args[-1]
            if target.dataset_identity == "server/load_surge":
                entered_surge.set()
                await release_surge.wait()
            elif target.dataset_identity == "server/load_critical":
                entered_critical.set()
                await release_critical.wait()
            if controller._commit_attached_workload_transition(
                target, True, transition_id=transition_id
            ):
                commits.append(target.dataset_identity)
                return SimulationCacheResult(True, "transition committed")
            return controller._superseded_transition_result(transition_id, target)

        controller.acquire_airflow_validation_for_transition = validate
        controller._retarget_attached_workload_in_kit = retarget
        controller.detach_simulation_cache_in_kit = lambda: (_ for _ in ()).throw(
            AssertionError()
        )
        controller.reset_simulation_cache_in_kit = lambda: (_ for _ in ()).throw(
            AssertionError()
        )

        surge_task = asyncio.create_task(
            controller.request_attached_workload_transition_in_kit("Surge")
        )
        await entered_surge.wait()
        current_workload["value"] = "Critical"
        critical_task = asyncio.create_task(
            controller.request_attached_workload_transition_in_kit("Critical")
        )
        await entered_critical.wait()
        assert controller.airflow_transition_state() == {
            "semantic_workload": "Critical",
            "active_airflow_selector": "server/load_normal",
            "pending_airflow_selector": "server/load_critical",
        }
        current_workload["value"] = "Idle"
        idle_result = await controller.request_attached_workload_transition_in_kit(
            "Idle"
        )
        release_critical.set()
        release_surge.set()
        critical_result, surge_result = await asyncio.gather(critical_task, surge_task)

        assert idle_result.success is True
        assert critical_result.success is True
        assert surge_result.success is True
        assert commits == ["server/load_idle"]
        assert controller.airflow_transition_state() == {
            "semantic_workload": "Idle",
            "active_airflow_selector": "server/load_idle",
            "pending_airflow_selector": None,
        }

    asyncio.run(scenario())


def _attached_transition_controller(*, workload: str = "Critical") -> RuntimeController:
    controller = RuntimeController("configs/digital_twin_runtime_suite.toml")
    controller.set_workload_source(lambda: workload)
    controller._flow_lifecycle_state = "ATTACHED"
    controller._flow_session_workload_binding = (
        controller.resolve_workload_airflow_binding("Nominal")
    )
    return controller


def _install_fake_carb(monkeypatch) -> list[str]:
    logs: list[str] = []
    monkeypatch.setitem(
        sys.modules,
        "carb",
        types.SimpleNamespace(log_warn=logs.append, log_error=logs.append),
    )
    return logs


def _mock_transition_dataset_signature(monkeypatch, controller) -> None:
    monkeypatch.setattr(
        workload_transition,
        "build_dataset_validation_signature",
        lambda *_args: object(),
    )
    controller._flow_validation_cache = _FakeValidationCache()
    controller.validate_attached_airflow_transition_pair = lambda **_kwargs: (
        types.SimpleNamespace(
            family_compatible=True,
            member_selectors=("server/load_normal", "server/load_critical"),
            phase_mapping="normalized_discrete",
        )
    )
    monkeypatch.setattr(
        controller,
        "validate_registered_airflow_dataset_family",
        lambda: types.SimpleNamespace(
            family_compatible=True,
            member_selectors=(
                "server/load_idle",
                "server/load_normal",
                "server/load_surge",
                "server/load_critical",
            ),
            phase_mapping="normalized_discrete",
        ),
    )


class _FakeValidationCache:
    def __init__(self):
        self._lookup_count = 0

    def lookup(self, _signature):
        self._lookup_count += 1
        return types.SimpleNamespace(
            preflight=(
                None if self._lookup_count == 1 else _FakeValidationLease().receipt
            )
        )


class _FakeValidationLease:
    def __init__(self):
        self.receipt = types.SimpleNamespace(
            signature=types.SimpleNamespace(compact_digest="test-receipt")
        )

    def release(self):
        return None


class _FakeTimeline:
    def __init__(self, *, playing: bool) -> None:
        self.playing = playing

    def is_playing(self) -> bool:
        return self.playing


class _FakeStage:
    def __init__(self):
        self._edit_target = object()
        self._session_layer = object()

    def GetEditTarget(self):
        return self._edit_target

    def GetSessionLayer(self):
        return self._session_layer

    def SetEditTarget(self, edit_target):
        self._edit_target = edit_target


class _FakeVelocityScaleEmitter:
    def __init__(self, initial: float):
        self.attribute = _FakeVelocityScaleAttribute(initial)

    def GetAttribute(self, name: str):
        return self.attribute if name == "velocityScale" else None


class _FakeVelocityScaleAttribute:
    def __init__(self, value: float):
        self._value = value
        self._custom_data: dict[str, object] = {}

    def IsValid(self):
        return True

    def SetCustomDataByKey(self, key: str, value):
        self._custom_data[key] = value

    def GetCustomDataByKey(self, key: str):
        return self._custom_data.get(key)

    def Set(self, value):
        self._value = value

    def Get(self):
        return self._value


class _FakeFieldPrim:
    def __init__(self):
        self.file_names = _FakeFileNamesAttribute()


class _FakeCaeVtk:
    @staticmethod
    def FieldArray(field_prim):
        return _FakeFieldArray(field_prim.file_names)


class _FakeFieldArray:
    def __init__(self, file_names):
        self._file_names = file_names

    def GetFileNamesAttr(self):
        return self._file_names


class _FakeFileNamesAttribute:
    def __init__(self):
        self.values = {}

    def IsValid(self):
        return True

    def Set(self, values, time_code):
        self.values[time_code] = values
        return True

    def Get(self, time_code):
        return self.values.get(time_code)


class _FakeAssetPath:
    def __init__(self, path):
        self.path = str(path)
        self.resolvedPath = self.path


class _FakeSdf:
    AssetPath = _FakeAssetPath


class _FakeUsd:
    @staticmethod
    def TimeCode(value):
        return value
