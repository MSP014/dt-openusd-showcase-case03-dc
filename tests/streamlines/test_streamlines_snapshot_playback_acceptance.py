"""Focused final-gate evidence contracts for cleaned Streamlines playback."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from digital_twin_runtime_suite.app.streamlines import (
    snapshot_playback_acceptance,
)
from digital_twin_runtime_suite.app.streamlines.playback import (
    CachedPlaybackContract,
)
from digital_twin_runtime_suite.app.streamlines.snapshot_playback_acceptance import (
    SnapshotPlaybackAcceptanceExpectation,
    StreamlinesSnapshotPlaybackAcceptanceMixin,
    collect_snapshot_playback_loop_evidence,
    first_unordered_snapshot_transition,
)
from digital_twin_runtime_suite.app.streamlines.temporal import (
    TemporalSourceSample,
)
from digital_twin_runtime_suite.app.visualization_mode import VisualizationMode


def test_production_acceptance_announces_only_from_clean_valid_normal() -> None:
    runtime = _AcceptanceRuntime(readiness="VALID")

    assert runtime.announce_streamlines_snapshot_playback_acceptance_ready() is True
    assert "PHASE_4_4B_CLEAN_SNAPSHOT_FINAL | READY" in runtime.messages[0]
    assert 'NEXT_ACTION | Select "Streamlines" in "Visualization".' in (
        runtime.messages[0]
    )

    invalid = _AcceptanceRuntime(readiness="MISSING")

    assert invalid.announce_streamlines_snapshot_playback_acceptance_ready() is False
    assert invalid.messages == []


def test_production_acceptance_rejects_a_loaded_retired_module(monkeypatch) -> None:
    runtime = _AcceptanceRuntime(readiness="VALID")
    monkeypatch.setattr(
        snapshot_playback_acceptance,
        "loaded_retired_streamlines_modules",
        lambda: ("_".join(("mesh", "cache")),),
    )

    assert runtime.announce_streamlines_snapshot_playback_acceptance_ready() is False
    assert runtime.messages == []


def test_production_acceptance_requires_one_complete_real_cached_loop() -> None:
    contract = _contract()
    evidence = collect_snapshot_playback_loop_evidence(
        contract=contract,
        ticks=_ticks((0, 1, 2, 0)),
        visible_counts=(1, 1, 1, 1),
        scheduler_tasks=1,
        scheduler_report=SimpleNamespace(missed_deadlines=0, backlog_count=0),
        state_failure=None,
        state_failure_count=0,
    )

    assert evidence.observed_indices == (0, 1, 2, 0)
    assert evidence.distinct_sample_count == 3
    assert evidence.wrap_observed is True
    assert evidence.full_loop_passed(_expectation()) is True


def test_production_acceptance_rejects_skipped_or_non_visible_state() -> None:
    evidence = collect_snapshot_playback_loop_evidence(
        contract=_contract(),
        ticks=_ticks((0, 2, 0)),
        visible_counts=(1, 2, 1),
        scheduler_tasks=1,
        scheduler_report=SimpleNamespace(missed_deadlines=0, backlog_count=0),
        state_failure=None,
        state_failure_count=0,
    )

    assert evidence.ordered is False
    assert first_unordered_snapshot_transition(evidence) == (0, 2)
    assert evidence.visible_states_max == 2
    assert evidence.full_loop_passed(_expectation()) is False


def test_production_acceptance_accepts_no_op_ticks_within_real_order() -> None:
    evidence = collect_snapshot_playback_loop_evidence(
        contract=_contract(),
        ticks=_ticks((0, 0, 1, 2, 2, 0)),
        visible_counts=(1, 1, 1, 1, 1, 1),
        scheduler_tasks=1,
        scheduler_report=SimpleNamespace(missed_deadlines=0, backlog_count=0),
        state_failure=None,
        state_failure_count=0,
    )

    assert evidence.ordered is True
    assert evidence.wrap_observed is True
    assert evidence.full_loop_passed(_expectation()) is True


def test_reentry_requires_consecutive_real_states_without_legacy_work() -> None:
    evidence = collect_snapshot_playback_loop_evidence(
        contract=_contract(),
        ticks=_ticks((1, 2)),
        visible_counts=(1, 1),
        scheduler_tasks=1,
        scheduler_report=SimpleNamespace(missed_deadlines=0, backlog_count=0),
        state_failure=None,
        state_failure_count=0,
    )

    assert evidence.reentry_passed(_expectation()) is True


def test_activation_timing_uses_first_visible_and_commit_milestones(
    monkeypatch,
) -> None:
    runtime = _AcceptanceRuntime(readiness="VALID")
    monkeypatch.setattr(snapshot_playback_acceptance.time, "monotonic", lambda: 10.0)

    assert runtime.start_streamlines_snapshot_playback_acceptance(
        VisualizationMode.STREAMLINES
    )
    assert (
        runtime._streamlines_snapshot_playback_acceptance_activation_started_at == 10.0
    )
    runtime.streamlines_visible = True
    runtime.visible_snapshot_count = 1
    runtime.scheduler_tasks = 1
    monkeypatch.setattr(snapshot_playback_acceptance.time, "monotonic", lambda: 11.5)
    runtime.report_streamlines_snapshot_playback_acceptance_progress(
        "Production snapshot presentation is visible; "
        "cached-playback scheduler is active."
    )
    assert runtime._streamlines_snapshot_playback_acceptance_first_visible_at == 11.5
    runtime._streamlines_snapshot_playback_acceptance_activation_committed_at = 12.0

    assert runtime._snapshot_playback_time_to_first_visible_ms() == 1500.0
    assert runtime._snapshot_playback_activation_total_ms() == 2000.0

    # A later 16-second loop observation must not overwrite activation facts.
    runtime._streamlines_snapshot_playback_acceptance_loop_samples = ()
    assert runtime._snapshot_playback_time_to_first_visible_ms() == 1500.0
    assert runtime._snapshot_playback_activation_total_ms() == 2000.0


def test_reentry_records_its_own_first_visible_milestone(monkeypatch) -> None:
    runtime = _AcceptanceRuntime(readiness="VALID")
    session = runtime._streamlines_snapshot_playback_acceptance_session
    runtime.streamlines_visible = True
    runtime.visible_snapshot_count = 1
    runtime.scheduler_tasks = 1
    message = (
        "Production snapshot presentation is visible; "
        "cached-playback scheduler is active."
    )

    session.begin()
    assert session.record("first_start") is True
    monkeypatch.setattr(snapshot_playback_acceptance.time, "monotonic", lambda: 10.0)
    runtime.report_streamlines_snapshot_playback_acceptance_progress(message)
    assert session.record("first_technical") is True
    assert session.record("first_visual") is True
    assert session.record("first_cleanup") is True
    assert session.record("reentry_start") is True

    monkeypatch.setattr(snapshot_playback_acceptance.time, "monotonic", lambda: 20.0)
    runtime.report_streamlines_snapshot_playback_acceptance_progress(message)

    assert runtime._streamlines_snapshot_playback_acceptance_first_visible_at == 10.0
    assert (
        runtime._streamlines_snapshot_playback_acceptance_reentry_first_visible_at
        == 20.0
    )


def test_manual_failure_and_incomplete_cleanup_cannot_complete_final_gate() -> None:
    runtime = _AcceptanceRuntime(readiness="VALID")

    assert runtime.start_streamlines_snapshot_playback_acceptance(
        VisualizationMode.STREAMLINES
    )
    session = runtime._streamlines_snapshot_playback_acceptance_session
    assert session.record("first_technical") is True
    assert runtime.reject_streamlines_snapshot_playback_acceptance("flicker") is True
    assert session.failed is True
    assert session.complete() is False


def test_final_gate_requires_cleanup_and_reentry_visual_pass_before_terminal() -> None:
    runtime = _AcceptanceRuntime(readiness="VALID")

    assert runtime.start_streamlines_snapshot_playback_acceptance(
        VisualizationMode.STREAMLINES
    )
    session = runtime._streamlines_snapshot_playback_acceptance_session
    assert session.record("first_technical") is True
    assert runtime.confirm_streamlines_snapshot_playback_acceptance() is True
    assert session.expected_milestone == "first_cleanup"
    assert (
        runtime.start_streamlines_snapshot_playback_acceptance(
            VisualizationMode.STREAMLINES
        )
        is False
    )
    assert session.record("first_cleanup") is True
    assert (
        runtime.start_streamlines_snapshot_playback_acceptance(
            VisualizationMode.STREAMLINES
        )
        is True
    )
    assert session.record("reentry_technical") is True
    assert runtime.confirm_streamlines_snapshot_playback_acceptance() is True
    assert session.expected_milestone == "final_cleanup"
    assert session.complete() is False
    assert session.record("final_cleanup") is True
    assert session.complete() is True
    assert session.complete() is False


def _contract() -> CachedPlaybackContract:
    return CachedPlaybackContract(
        workload="Nominal",
        dataset_identity="server/load_normal",
        sample_interval_seconds=0.2,
        samples=tuple(_sample(index) for index in range(3)),
        profile_id="volume_coverage",
        cache_identity="tiny-cache",
    )


def _sample(index: int) -> TemporalSourceSample:
    return TemporalSourceSample(
        ordinal=index + 1,
        total=3,
        sample_index=index,
        source_vti=Path(f"sample_{index}.vti"),
        source_time_seconds=index * 0.2,
        time_code=index * 12.0,
    )


def _ticks(indices: tuple[int, ...]):
    return tuple(
        SimpleNamespace(
            resolution=SimpleNamespace(
                sample=SimpleNamespace(sample_index=sample_index)
            )
        )
        for sample_index in indices
    )


def _expectation() -> SnapshotPlaybackAcceptanceExpectation:
    return SnapshotPlaybackAcceptanceExpectation(
        sample_count=3,
        sample_interval_seconds=0.2,
        reentry_minimum_ticks=2,
    )


class _AcceptanceRuntime(StreamlinesSnapshotPlaybackAcceptanceMixin):
    def __init__(self, *, readiness: str) -> None:
        self._readiness = readiness
        self.messages = []
        self.committed = VisualizationMode.NORMAL
        self.pending = None
        self.scheduler_tasks = 0
        self.streamlines_prepared = False
        self.streamlines_visible = False
        self.visible_snapshot_count = 0
        self.reset_streamlines_snapshot_playback_acceptance_state()

    def visualization_readiness(self):
        return SimpleNamespace(
            for_mode=lambda _mode: SimpleNamespace(state=self._readiness)
        )

    def visualization_snapshot(self):
        return SimpleNamespace(committed=self.committed, pending=self.pending)

    def _active_streamlines_playback_task_count(self) -> int:
        return self.scheduler_tasks

    def streamlines_cached_presentation_is_prepared_in_kit(self) -> bool:
        return self.streamlines_prepared

    def streamlines_cached_presentation_is_visible_in_kit(self) -> bool:
        return self.streamlines_visible

    def streamlines_snapshot_visible_count_in_kit(self) -> int:
        return self.visible_snapshot_count

    @staticmethod
    def _snapshot_playback_acceptance_has_no_duplicate_root() -> bool:
        return True

    def _streamlines_carb_logger(self):
        return SimpleNamespace(
            log_error=self.messages.append,
            log_warn=self.messages.append,
        )
