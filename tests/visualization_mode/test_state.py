"""Focused primary-visualization transaction ownership contracts."""

from __future__ import annotations

from digital_twin_runtime_suite.app.visualization_mode.model import VisualizationMode
from digital_twin_runtime_suite.app.visualization_mode.state import (
    VisualizationModeState,
)


def test_normal_to_pending_smoke_commits_only_after_readiness_proof() -> None:
    state = VisualizationModeState()

    transition = state.begin(VisualizationMode.SMOKE)

    assert transition is not None
    assert state.snapshot.committed is VisualizationMode.NORMAL
    assert state.commit(transition.transition_id) is True
    assert state.snapshot.committed is VisualizationMode.SMOKE
    assert state.snapshot.pending is None


def test_failure_preserves_committed_mode() -> None:
    state = VisualizationModeState()
    transition = state.begin(VisualizationMode.SMOKE)

    assert transition is not None
    assert state.fail(transition.transition_id, "Current workload validation failed")
    assert state.snapshot.committed is VisualizationMode.NORMAL
    assert state.snapshot.pending is None
    assert state.snapshot.failure is not None


def test_newer_request_supersedes_and_stale_transition_cannot_commit() -> None:
    state = VisualizationModeState()
    smoke = state.begin(VisualizationMode.SMOKE)
    streamlines = state.begin(VisualizationMode.STREAMLINES)

    assert smoke is not None and streamlines is not None
    assert streamlines.superseded_transition_id == smoke.transition_id
    assert state.commit(smoke.transition_id) is False
    assert state.commit(streamlines.transition_id) is True
    assert state.snapshot.committed is VisualizationMode.STREAMLINES


def test_same_request_is_no_op_and_committed_request_cancels_pending_state() -> None:
    state = VisualizationModeState()
    smoke = state.begin(VisualizationMode.SMOKE)

    assert smoke is not None
    assert state.begin(VisualizationMode.SMOKE) is None
    assert state.begin(VisualizationMode.NORMAL) is None
    assert state.snapshot.pending is None


def test_cancel_and_reset_clear_pending_state() -> None:
    state = VisualizationModeState()
    transition = state.begin(VisualizationMode.SMOKE)

    assert transition is not None
    assert state.cancel(transition.transition_id) is True
    assert state.snapshot.pending is None
    state.begin(VisualizationMode.STREAMLINES_XRAY)
    state.reset()

    assert state.snapshot.committed is VisualizationMode.NORMAL
    assert state.snapshot.pending is None
