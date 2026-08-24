# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""Focused shared airflow state transition ownership contracts."""

from __future__ import annotations

from pathlib import Path

import pytest

from digital_twin_runtime_suite.app.airflow_dataset import (
    AirflowDataset,
    AirflowDatasetManifest,
    AirflowDatasetSelector,
)
from digital_twin_runtime_suite.app.airflow_state.runtime import AirflowStateRuntime
from digital_twin_runtime_suite.app.workload_binding.runtime import (
    WorkloadBindingRuntime,
)


def test_resolves_semantic_workload_through_the_shared_registry() -> None:
    state = _state()

    target = state.resolve_current()

    assert target.binding.dataset_identity == "server/load_normal"
    assert target.dataset.manifest.state == "load_normal"


def test_pending_transition_commits_only_after_consumer_success() -> None:
    state = _state()

    transition = state.begin_for_workload("Nominal")

    assert transition is not None
    assert state.commit(transition.transition_id) is True
    assert state.committed == transition.target
    assert state.pending is None


def test_failed_target_preserves_previous_committed_dataset() -> None:
    state = _state()
    committed = state.begin_for_workload("Nominal")
    assert committed is not None
    assert state.commit(committed.transition_id)
    pending = state.begin_for_workload("Critical")
    assert pending is not None

    failure = state.fail(
        pending.transition_id,
        semantic_workload="Critical",
        requested_binding=pending.target.binding,
        reason="VTI proof failed",
        failure_stage="validation",
        attached=True,
    )

    assert failure is not None
    assert state.committed == committed.target
    assert state.pending is None
    assert failure.action == "kept_previous_safe_dataset"


def test_newer_request_supersedes_older_generation_and_stale_commit_is_rejected() -> (
    None
):
    state = _state()
    seed = state.begin_for_workload("Nominal")
    assert seed is not None and state.commit(seed.transition_id)
    surge = state.begin_for_workload("Surge")
    critical = state.begin_for_workload("Critical")

    assert surge is not None and critical is not None
    assert critical.superseded_transition_id == surge.transition_id
    assert state.commit(surge.transition_id) is False
    assert state.commit(critical.transition_id) is True
    assert state.committed == critical.target


def test_same_committed_or_pending_request_is_no_op() -> None:
    state = _state()
    first = state.begin_for_workload("Nominal")
    assert first is not None
    assert state.begin_for_workload("Nominal") is None
    assert state.commit(first.transition_id)
    assert state.begin_for_workload("Nominal") is None
    assert state.generation == 1


def test_phase_snapshot_uses_shared_clock_and_exact_manifest_sample() -> None:
    state = _state(monotonic=lambda: 10.0)
    target = state.begin_for_workload("Nominal")
    assert target is not None and state.commit(target.transition_id)

    resolution = state.resolve_phase(now=10.81)

    assert resolution.sample.sample_index == 2
    assert resolution.normalized_phase_seconds == pytest.approx(0.81)


def test_flow_and_streamlines_consume_one_dataset_and_phase_truth() -> None:
    state = _state(monotonic=lambda: 4.0)
    transition = state.begin_for_workload("Nominal")
    assert transition is not None and state.commit(transition.transition_id)

    flow_resolution = state.resolve_phase(now=4.41)
    streamlines_resolution = state.resolve_phase(
        state.committed.dataset,
        now=4.41,
    )

    assert state.committed.binding.dataset_identity == "server/load_normal"
    assert flow_resolution.sample == streamlines_resolution.sample
    assert flow_resolution.normalized_phase_seconds == pytest.approx(0.41)


def test_transition_phase_pair_uses_one_absolute_clock_with_nonzero_origin() -> None:
    state = _state(monotonic=lambda: 53.81)
    nominal = state.begin_for_workload("Nominal")
    assert nominal is not None and state.commit(nominal.transition_id)
    critical = state.resolve_target(state.resolve_binding("Critical")).dataset

    active, target = state.resolve_transition_phase_pair(
        state.committed.dataset,
        critical,
        now=54.62,
    )

    assert state.phase_seconds(now=54.62) == pytest.approx(0.81)
    assert active.normalized_phase_seconds == pytest.approx(0.81)
    assert target.normalized_phase_seconds == pytest.approx(0.81)
    assert active.sample.sample_index == target.sample.sample_index == 2


def _state(*, monotonic=lambda: 0.0) -> AirflowStateRuntime:
    workloads = {
        "Idle": "load_idle",
        "Nominal": "load_normal",
        "Surge": "load_surge",
        "Critical": "load_critical",
    }

    class _Cache:
        def airflow_dataset_selector_for_workload(self, workload: str):
            return AirflowDatasetSelector("datasets", "server", workloads[workload])

    registry = tuple(_dataset(state) for state in workloads.values())
    return AirflowStateRuntime(
        WorkloadBindingRuntime(_Cache(), lambda: "Nominal"),
        registry,
        monotonic=monotonic,
    )


def _dataset(state: str) -> AirflowDataset:
    paths = tuple(Path(f"{state}_{index}.vti") for index in range(4))
    manifest = AirflowDatasetManifest(
        scope="server",
        state=state,
        source_fps=5.0,
        sample_step_frames=2,
        sample_rate_hz=2.5,
        sample_count=len(paths),
        grid=(2, 2, 2),
    )
    return AirflowDataset(
        root=Path("datasets"),
        directory=Path(state),
        manifest_path=Path(state) / "manifest.toml",
        manifest=manifest,
        velocity_vti_sequence_paths=paths,
        source_frames=(0, 2, 4, 6),
    )
