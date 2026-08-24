# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""Stage 08 single-flight validation priority, retry, and shutdown contracts."""

import asyncio
import threading
import time
from pathlib import Path

import pytest

from digital_twin_runtime_suite.app.airflow_dataset import (
    AirflowDataset,
    AirflowDatasetManifest,
    AirflowDatasetSelector,
)
from digital_twin_runtime_suite.app.airflow_validation import (
    preflight as airflow_preflight,
)
from digital_twin_runtime_suite.app.airflow_validation.cache import (
    SessionValidationCache,
    build_dataset_validation_signature,
)
from digital_twin_runtime_suite.app.validation_receipts import (
    ValidationReceiptStore,
)
from digital_twin_runtime_suite.app.workload_binding.background_validation import (
    BackgroundAirflowValidationCoordinator,
    BackgroundValidationError,
)
from digital_twin_runtime_suite.app.workload_binding.runtime import (
    WorkloadAirflowBinding,
)


def test_background_validation_is_sequential_and_current_workload_first(tmp_path):
    datasets = _datasets(tmp_path)
    calls = []
    logs = []

    def validator(paths, _field_name, _cancel_requested):
        calls.append(paths[0].parent.name)
        return _metadata(), True

    result = asyncio.run(
        _coordinator(datasets, "Nominal", preflight_validator=validator).run(
            logs.append
        )
    )

    assert calls == ["load_normal", "load_idle", "load_surge", "load_critical"]
    assert result.validated == 4
    assert result.failed == 0
    assert logs[0] == "\n".join(
        (
            "DTRS AIRFLOW BACKGROUND VALIDATION",
            "process=DATASET PREFLIGHT | state=START",
            "current_workload=Nominal",
            "order=server/load_normal, server/load_idle, server/load_surge, "
            "server/load_critical",
            "mode=sequential",
        )
    )
    assert sum("receipt_source=FRESH" in line for line in logs) == 4
    assert sum("validation_executed=True" in line for line in logs) == 4


def test_default_preflight_publishes_per_vti_file_progress(tmp_path, monkeypatch):
    dataset = _datasets(tmp_path)[1]
    progress = []

    def validate(paths, _field_name, progress_callback=None, cancel_requested=None):
        assert cancel_requested is not None
        for completed, path in enumerate(paths, start=1):
            progress_callback(completed, len(paths), path.name)
        return _metadata(), True

    monkeypatch.setattr(
        airflow_preflight,
        "validate_kit_cae_temporal_vti_contract",
        validate,
    )

    result = asyncio.run(
        _coordinator(
            (dataset,),
            "Nominal",
            preflight_validator=None,
        ).run(
            lambda _message: None,
            progress_callback=lambda selector, current, total, name: progress.append(
                (selector, current, total, name)
            ),
        )
    )

    assert result.validated == 1
    assert progress == [
        (
            "server/load_normal",
            0,
            1,
            "server_airflow_velocity_load_normal_1001.vti",
        ),
        (
            "server/load_normal",
            1,
            1,
            "server_airflow_velocity_load_normal_1001.vti",
        ),
    ]


def test_expensive_vti_preflight_runs_off_the_calling_thread(tmp_path):
    dataset = _datasets(tmp_path)[1]
    calling_thread = threading.get_ident()
    worker_threads = []

    def validator(*_args):
        worker_threads.append(threading.get_ident())
        return _metadata(), True

    asyncio.run(
        _coordinator(
            (dataset,),
            "Nominal",
            preflight_validator=validator,
        ).run(lambda _message: None)
    )

    assert worker_threads
    assert all(thread_id != calling_thread for thread_id in worker_threads)


def test_background_validation_reuses_existing_preflight_receipt(tmp_path):
    dataset = _datasets(tmp_path)[1]
    cache = SessionValidationCache()
    signature = build_dataset_validation_signature(dataset, "vel")
    cache.store_preflight(signature, _metadata(), True)
    logs = []

    def unexpected_validator(*_args):
        raise AssertionError("A matching receipt must skip expensive VTI preflight.")

    result = asyncio.run(
        _coordinator(
            (dataset,),
            "Nominal",
            validation_cache=cache,
            preflight_validator=unexpected_validator,
        ).run(logs.append)
    )

    assert result.validated == 0
    assert any(
        "process=DATASET PREFLIGHT | state=REUSED" in line
        and "selector=server/load_normal" in line
        for line in logs
    )
    assert any("receipt_source=FRESH" in line for line in logs)
    assert any("current_cache_location=SESSION" in line for line in logs)
    assert any("validation_executed=False" in line for line in logs)
    assert not any(
        "state=BEGIN" in line and "selector=server/load_normal" in line for line in logs
    )


def test_next_process_reuses_persisted_vti_without_worker_call(tmp_path):
    dataset = _datasets(tmp_path)[1]
    store_path = tmp_path / "receipts.local.json"
    first_calls = []
    first_cache = SessionValidationCache(
        persisted_store=ValidationReceiptStore(store_path),
        reuse_persisted=True,
    )

    def first_validator(*_args):
        first_calls.append("validated")
        return _metadata(), True

    asyncio.run(
        _coordinator(
            (dataset,),
            "Nominal",
            validation_cache=first_cache,
            preflight_validator=first_validator,
        ).run(lambda _message: None)
    )

    restarted_store = ValidationReceiptStore(store_path)
    restarted_cache = SessionValidationCache(
        persisted_store=restarted_store,
        reuse_persisted=True,
    )
    logs = []

    def unexpected_validator(*_args):
        raise AssertionError("Persisted VTI evidence must bypass the worker.")

    result = asyncio.run(
        _coordinator(
            (dataset,),
            "Nominal",
            validation_cache=restarted_cache,
            preflight_validator=unexpected_validator,
        ).run(logs.append)
    )

    assert first_calls == ["validated"]
    assert result.failed == 0
    assert any("receipt_source=PERSISTED" in line for line in logs)
    assert restarted_store.metrics_snapshot().vti.expensive_validation_calls == 0


def test_changed_vti_fingerprint_revalidates_only_changed_workload(tmp_path):
    datasets = _datasets(tmp_path)
    store_path = tmp_path / "receipts.local.json"
    first_cache = SessionValidationCache(
        persisted_store=ValidationReceiptStore(store_path),
        reuse_persisted=True,
    )
    asyncio.run(
        _coordinator(
            datasets,
            "Nominal",
            validation_cache=first_cache,
            preflight_validator=lambda *_args: (_metadata(), True),
        ).run(lambda _message: None)
    )
    changed_path = datasets[1].velocity_vti_sequence_paths[0]
    changed_path.write_bytes(changed_path.read_bytes() + b"changed")
    calls = []

    def validator(paths, *_args):
        calls.append(paths[0].parent.name)
        return _metadata(), True

    restarted_cache = SessionValidationCache(
        persisted_store=ValidationReceiptStore(store_path),
        reuse_persisted=True,
    )
    asyncio.run(
        _coordinator(
            datasets,
            "Nominal",
            validation_cache=restarted_cache,
            preflight_validator=validator,
        ).run(lambda _message: None)
    )

    assert calls == ["load_normal"]


def test_failed_dataset_retries_after_other_first_pass_and_becomes_terminal(tmp_path):
    datasets = _datasets(tmp_path)
    calls = []
    logs = []

    def validator(paths, _field_name, _cancel_requested):
        dataset_name = paths[0].parent.name
        calls.append(dataset_name)
        if dataset_name == "load_surge":
            raise RuntimeError("synthetic corrupt VTI")
        return _metadata(), True

    result = asyncio.run(
        _coordinator(datasets, "Nominal", preflight_validator=validator).run(
            logs.append
        )
    )

    assert calls == [
        "load_normal",
        "load_idle",
        "load_surge",
        "load_critical",
        "load_surge",
        "load_surge",
    ]
    assert result.validated == 3
    assert result.failed == 1
    assert any("queued_for_retry=True" in line for line in logs)
    assert any("TERMINAL FAILURE" in line and "attempts=3/3" in line for line in logs)


def test_background_validation_stops_cooperatively_after_shutdown_cancellation(
    tmp_path,
):
    dataset = _datasets(tmp_path)[1]
    entered = threading.Event()

    def validator(_paths, _field_name, cancel_requested):
        entered.set()
        while not cancel_requested():
            time.sleep(0.001)
        raise airflow_preflight.TemporalVtiValidationCancelled(
            "VTI preflight cancelled"
        )

    async def run_and_cancel():
        coordinator = _coordinator((dataset,), "Nominal", preflight_validator=validator)
        task = asyncio.create_task(coordinator.run(lambda _message: None))
        await asyncio.to_thread(entered.wait)
        coordinator.cancel()
        return await task

    result = asyncio.run(run_and_cancel())

    assert result.cancelled is True
    assert result.validated == 0
    assert result.failed == 0


def test_manual_attach_promotes_the_current_background_job_without_restart(tmp_path):
    dataset = _datasets(tmp_path)[1]
    entered, release = threading.Event(), threading.Event()
    calls, logs = [], []

    def validator(paths, _field_name, _cancel_requested):
        calls.append(paths[0].parent.name)
        entered.set()
        release.wait()
        return _metadata(), True

    async def exercise():
        coordinator = _coordinator((dataset,), "Nominal", preflight_validator=validator)
        task = asyncio.create_task(coordinator.run(logs.append))
        await asyncio.to_thread(entered.wait)
        attach = asyncio.create_task(
            coordinator.acquire_for_attach(_binding("Nominal"))
        )
        await asyncio.sleep(0)
        release.set()
        lease = await attach
        lease.release()
        await task

    asyncio.run(exercise())

    assert calls == ["load_normal"]
    assert any("PROMOTED | selector=server/load_normal" in log for log in logs)


def test_manual_attach_preempts_background_and_resumes_it_after_lease(tmp_path):
    datasets = _datasets(tmp_path)
    idle_entered, idle_release = threading.Event(), threading.Event()
    calls, logs = [], []

    def validator(paths, _field_name, cancel_requested):
        name = paths[0].parent.name
        calls.append(name)
        if name == "load_idle" and len(calls) == 1:
            idle_entered.set()
            while not idle_release.is_set():
                if cancel_requested():
                    raise airflow_preflight.TemporalVtiValidationCancelled("preempted")
                time.sleep(0.001)
        return _metadata(), True

    async def exercise():
        coordinator = _coordinator(datasets, "Idle", preflight_validator=validator)
        task = asyncio.create_task(coordinator.run(logs.append))
        await asyncio.to_thread(idle_entered.wait)
        lease = await coordinator.acquire_for_attach(_binding("Critical"))
        assert calls == ["load_idle", "load_critical"]
        lease.release()
        await task

    asyncio.run(exercise())

    assert calls == [
        "load_idle",
        "load_critical",
        "load_idle",
        "load_normal",
        "load_surge",
    ]
    assert any(
        "PREEMPT | active=server/load_idle | requested=server/load_critical" in log
        for log in logs
    )
    assert any(
        "state=REQUEUED" in log
        and "selector=server/load_idle" in log
        and "attempt_preserved=True" in log
        for log in logs
    )
    assert any("PRIORITY PASS | selector=server/load_critical" in log for log in logs)
    assert any("state=RESUME" in log and "next=server/load_idle" in log for log in logs)
    assert any(
        "background_validated=3\npriority_validated=1\ntotal_validated=4" in log
        for log in logs
    )


def test_manual_attach_hit_preempts_background_without_running_target_preflight(
    tmp_path,
):
    datasets = _datasets(tmp_path)
    idle_entered = threading.Event()
    calls, logs, cache = [], [], SessionValidationCache()
    critical = datasets[3]
    cache.store_preflight(
        build_dataset_validation_signature(critical, "vel"), _metadata(), True
    )

    def validator(paths, _field_name, cancel_requested):
        name = paths[0].parent.name
        calls.append(name)
        if name == "load_idle" and len(calls) == 1:
            idle_entered.set()
            while not cancel_requested():
                time.sleep(0.001)
            raise airflow_preflight.TemporalVtiValidationCancelled("preempted")
        return _metadata(), True

    async def exercise():
        coordinator = _coordinator(
            datasets, "Idle", validation_cache=cache, preflight_validator=validator
        )
        task = asyncio.create_task(coordinator.run(logs.append))
        await asyncio.to_thread(idle_entered.wait)
        lease = await coordinator.acquire_for_attach(_binding("Critical"))
        lease.release()
        await task

    asyncio.run(exercise())

    assert calls.count("load_critical") == 0
    assert any(
        "state=REUSED" in log and "selector=server/load_critical" in log for log in logs
    )
    assert not any(
        "PRIORITY PASS | selector=server/load_critical" in log for log in logs
    )


def test_preempted_late_result_cannot_store_a_stale_receipt(tmp_path):
    datasets = _datasets(tmp_path)
    idle_entered, idle_release = threading.Event(), threading.Event()
    cache = SessionValidationCache()
    logs = []

    def validator(paths, _field_name, _cancel_requested):
        name = paths[0].parent.name
        if name == "load_idle" and not idle_entered.is_set():
            idle_entered.set()
            idle_release.wait()
        return _metadata(), True

    async def exercise():
        coordinator = _coordinator(
            datasets, "Idle", validation_cache=cache, preflight_validator=validator
        )
        task = asyncio.create_task(coordinator.run(logs.append))
        await asyncio.to_thread(idle_entered.wait)
        attach = asyncio.create_task(
            coordinator.acquire_for_attach(_binding("Critical"))
        )
        await asyncio.sleep(0)
        idle_release.set()
        lease = await attach
        idle_signature = build_dataset_validation_signature(datasets[0], "vel")
        assert cache.lookup(idle_signature).preflight is None
        lease.release()
        await task

    asyncio.run(exercise())

    idle_signature = build_dataset_validation_signature(datasets[0], "vel")
    assert cache.lookup(idle_signature).preflight is not None


def test_manual_attach_retries_failed_target_three_times(tmp_path):
    dataset = _datasets(tmp_path)[3]
    calls, logs = [], []

    def validator(paths, _field_name, _cancel_requested):
        calls.append(paths[0].parent.name)
        raise RuntimeError("synthetic corrupt VTI")

    async def exercise():
        coordinator = _coordinator(
            (dataset,), "Critical", preflight_validator=validator
        )
        coordinator._log = logs.append
        with pytest.raises(BackgroundValidationError, match="after 3/3 attempts"):
            await coordinator.acquire_for_attach(_binding("Critical"))

    asyncio.run(exercise())

    assert calls == ["load_critical", "load_critical", "load_critical"]
    assert sum("PRIORITY FAILED" in log for log in logs) == 2


def _coordinator(
    datasets,
    workload_mode,
    *,
    validation_cache=None,
    preflight_validator,
):
    state_by_workload = {
        "Idle": "load_idle",
        "Nominal": "load_normal",
        "Surge": "load_surge",
        "Critical": "load_critical",
    }
    state = state_by_workload[workload_mode]
    return BackgroundAirflowValidationCoordinator(
        datasets,
        WorkloadAirflowBinding(
            workload_mode,
            AirflowDatasetSelector("airflows", "server", state),
        ),
        "vel",
        validation_cache or SessionValidationCache(),
        preflight_validator=preflight_validator,
    )


def _binding(workload_mode: str) -> WorkloadAirflowBinding:
    state_by_workload = {
        "Idle": "load_idle",
        "Nominal": "load_normal",
        "Surge": "load_surge",
        "Critical": "load_critical",
    }
    return WorkloadAirflowBinding(
        workload_mode,
        AirflowDatasetSelector("airflows", "server", state_by_workload[workload_mode]),
    )


def _datasets(tmp_path: Path) -> tuple[AirflowDataset, ...]:
    states = ("load_idle", "load_normal", "load_surge", "load_critical")
    return tuple(_dataset(tmp_path, state) for state in states)


def _dataset(root: Path, state: str) -> AirflowDataset:
    directory = root / state
    directory.mkdir()
    manifest_path = directory / "manifest.toml"
    manifest_path.write_text(f'scope = "server"\nstate = "{state}"\n', encoding="utf-8")
    velocity_path = directory / f"server_airflow_velocity_{state}_1001.vti"
    velocity_path.write_bytes(b"vti")
    return AirflowDataset(
        root=root,
        directory=directory,
        manifest_path=manifest_path,
        manifest=AirflowDatasetManifest(
            scope="server",
            state=state,
            source_fps=50.0,
            sample_step_frames=10,
            sample_rate_hz=5.0,
            sample_count=1,
            grid=(2, 2, 2),
        ),
        velocity_vti_sequence_paths=(velocity_path,),
        source_frames=(1001,),
    )


def _metadata() -> dict[str, object]:
    return {
        "components": 3,
        "data_type": "float",
        "dimensions": (2, 2, 2),
        "point_count": 8,
        "origin": (0.0, 0.0, 0.0),
        "vti_header_origin": (0.0, 0.0, 0.0),
        "vtk_reader_origin": (0.0, 0.0, 0.0),
        "spacing": (1.0, 1.0, 1.0),
        "bounds": (0.0, 1.0, 0.0, 1.0, 0.0, 1.0),
        "velocity_magnitude_max": 1.0,
        "kit_cae_direct_attach_base_velocity_scale": 1.0,
        "velocity_field_name": "vel",
        "velocity_field_association": "point_data",
    }
