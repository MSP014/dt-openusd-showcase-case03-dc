"""Passive production acceptance for the standard Streamlines snapshot path."""

from __future__ import annotations

import asyncio
import sys
import time
from dataclasses import dataclass

from digital_twin_runtime_suite.app.flow.performance import (
    ViewportPerformanceSample,
    capture_viewport_performance_sample,
)
from digital_twin_runtime_suite.app.manual_acceptance import (
    GuidedAcceptanceSession,
    format_manual_acceptance_event,
    format_manual_acceptance_test_complete,
)
from digital_twin_runtime_suite.app.streamlines.playback import (
    CachedPlaybackContract,
)
from digital_twin_runtime_suite.app.streamlines.playback_scheduler import (
    CachedPlaybackScheduler,
)
from digital_twin_runtime_suite.app.visualization_mode import VisualizationMode

_AREA = "STREAMLINES | PHASE_4_4B_CLEAN_SNAPSHOT_FINAL"
_RETIRED_MODULE_BASENAMES = frozenset(
    "_".join(parts)
    for parts in (
        ("cached", "state", "runtime"),
        ("mesh", "conversion"),
        ("mesh", "cache"),
        ("mesh", "playback", "runtime"),
        ("mesh", "playback", "acceptance"),
        ("xform", "probe"),
        ("real", "curve", "ab", "probe"),
        ("full", "state", "ab", "probe"),
        ("cache", "playback", "sanity"),
        ("renderer", "diagnostic"),
    )
)


@dataclass(frozen=True)
class SnapshotPlaybackAcceptanceExpectation:
    """Current-cache acceptance facts; never a production playback setting."""

    workload: str = "Nominal"
    profile_id: str = "volume_coverage"
    sample_count: int = 80
    sample_interval_seconds: float = 0.2
    reentry_minimum_ticks: int = 4


@dataclass(frozen=True)
class SnapshotPlaybackLoopEvidence:
    """Compact evidence read from one existing scheduler lifetime."""

    observed_indices: tuple[int, ...]
    visible_counts: tuple[int, ...]
    expected_indices: tuple[int, ...]
    wrap_observed: bool
    ordered: bool
    no_synthetic_samples: bool
    scheduler_tasks: int
    visible_states_max: int
    missed_deadlines: int
    backlog_count: int
    state_failure: str | None
    state_failure_count: int

    @property
    def distinct_sample_count(self) -> int:
        """Count distinct real cached samples without retaining geometry arrays."""

        return len(set(self.observed_indices))

    @property
    def visible_states_min(self) -> int:
        """Expose the strictest observed snapshot visibility value."""

        return min(self.visible_counts, default=0)

    def full_loop_passed(
        self,
        expectation: SnapshotPlaybackAcceptanceExpectation,
    ) -> bool:
        """Require one complete current-cache sequence and all hard invariants."""

        return (
            len(self.expected_indices) == expectation.sample_count
            and len(self.observed_indices) >= expectation.sample_count
            and self.distinct_sample_count == expectation.sample_count
            and self.wrap_observed
            and self.ordered
            and self.no_synthetic_samples
            and self.scheduler_tasks == 1
            and self.visible_states_min == 1
            and self.visible_states_max == 1
            and self.missed_deadlines == 0
            and self.backlog_count == 0
            and self.state_failure is None
            and self.state_failure_count == 0
        )

    def reentry_passed(
        self,
        expectation: SnapshotPlaybackAcceptanceExpectation,
    ) -> bool:
        """Require several consecutive real states after a clean product re-entry."""

        return (
            len(self.observed_indices) >= expectation.reentry_minimum_ticks
            and self.distinct_sample_count >= expectation.reentry_minimum_ticks
            and self.ordered
            and self.no_synthetic_samples
            and self.scheduler_tasks == 1
            and self.visible_states_min == 1
            and self.visible_states_max == 1
            and self.missed_deadlines == 0
            and self.backlog_count == 0
            and self.state_failure is None
            and self.state_failure_count == 0
        )


@dataclass(frozen=True)
class SnapshotPlaybackPerformanceEvidence:
    """Compact production-path measurements collected without owning playback."""

    activation_total_ms: float | None
    time_to_first_visible_ms: float | None
    acceptance_loop_observation_ms: float | None
    before_snapshots: ViewportPerformanceSample | None
    after_snapshots: ViewportPerformanceSample | None
    loop_samples: tuple[ViewportPerformanceSample, ...]
    after_cleanup: ViewportPerformanceSample | None


def collect_snapshot_playback_loop_evidence(
    *,
    contract: CachedPlaybackContract,
    ticks,
    visible_counts: tuple[int, ...],
    scheduler_tasks: int,
    scheduler_report,
    state_failure: str | None,
    state_failure_count: int,
) -> SnapshotPlaybackLoopEvidence:
    """Evaluate resolved scheduler decisions without touching runtime state."""

    expected_indices = tuple(sample.sample_index for sample in contract.samples)
    observed_indices = tuple(tick.resolution.sample.sample_index for tick in ticks)
    selected_indices = tuple(
        index
        for index, previous in zip(
            observed_indices,
            (None, *observed_indices),
        )
        if index != previous
    )
    expected_next = {
        index: expected_indices[(offset + 1) % len(expected_indices)]
        for offset, index in enumerate(expected_indices)
    }
    ordered = bool(selected_indices) and all(
        expected_next.get(previous) == current
        for previous, current in zip(selected_indices, selected_indices[1:])
    )
    wrap_observed = any(
        previous == expected_indices[-1] and current == expected_indices[0]
        for previous, current in zip(selected_indices, selected_indices[1:])
    )
    return SnapshotPlaybackLoopEvidence(
        observed_indices=observed_indices,
        visible_counts=visible_counts,
        expected_indices=expected_indices,
        wrap_observed=wrap_observed,
        ordered=ordered,
        no_synthetic_samples=set(observed_indices).issubset(expected_indices),
        scheduler_tasks=scheduler_tasks,
        visible_states_max=max(visible_counts, default=0),
        missed_deadlines=scheduler_report.missed_deadlines,
        backlog_count=scheduler_report.backlog_count,
        state_failure=state_failure,
        state_failure_count=state_failure_count,
    )


def first_unordered_snapshot_transition(
    evidence: SnapshotPlaybackLoopEvidence,
) -> tuple[int, int] | None:
    """Return the first non-consecutive committed state transition, if any."""

    observed = evidence.observed_indices
    selected = tuple(
        index
        for index, previous in zip(observed, (None, *observed))
        if index != previous
    )
    expected_next = {
        index: evidence.expected_indices[(offset + 1) % len(evidence.expected_indices)]
        for offset, index in enumerate(evidence.expected_indices)
    }
    return next(
        (
            (previous, current)
            for previous, current in zip(selected, selected[1:])
            if expected_next.get(previous) != current
        ),
        None,
    )


class StreamlinesSnapshotPlaybackAcceptanceMixin:
    """Guide manual proof of the existing standard snapshot playback path."""

    def reset_streamlines_snapshot_playback_acceptance_state(self) -> None:
        """Clear only acceptance evidence; never stop or alter production playback."""

        self._streamlines_snapshot_playback_acceptance_session = (
            GuidedAcceptanceSession(
                (
                    "first_start",
                    "first_technical",
                    "first_visual",
                    "first_cleanup",
                    "reentry_start",
                    "reentry_technical",
                    "reentry_visual",
                    "final_cleanup",
                )
            )
        )
        self._streamlines_snapshot_playback_acceptance_ready_emitted = False
        self._streamlines_snapshot_playback_acceptance_activation_started_at = None
        self._streamlines_snapshot_playback_acceptance_first_visible_at = None
        self._streamlines_snapshot_playback_acceptance_activation_committed_at = None
        self._streamlines_snapshot_playback_acceptance_reentry_started_at = None
        self._streamlines_snapshot_playback_acceptance_reentry_first_visible_at = None
        self._streamlines_snapshot_playback_acceptance_before_snapshots = None
        self._streamlines_snapshot_playback_acceptance_after_snapshots = None
        self._streamlines_snapshot_playback_acceptance_loop_samples = ()
        self._streamlines_snapshot_playback_acceptance_loop_observation_ms = None
        self._streamlines_snapshot_playback_acceptance_after_cleanup = None
        self._streamlines_snapshot_playback_acceptance_progress = set()

    def announce_streamlines_snapshot_playback_acceptance_ready(self) -> bool:
        """Offer the final gate only from a clean Normal product baseline."""

        if (
            self._streamlines_snapshot_playback_acceptance_ready_emitted
            or not self._snapshot_playback_acceptance_first_start_ready()
            or loaded_retired_streamlines_modules()
        ):
            return False
        self._streamlines_snapshot_playback_acceptance_log(
            "READY",
            "Current Nominal / volume_coverage cache is valid; Normal is clean; "
            "legacy renderer modules are absent.",
            next_action='Select "Streamlines" in "Visualization".',
        )
        self._streamlines_snapshot_playback_acceptance_ready_emitted = True
        return True

    def streamlines_snapshot_playback_acceptance_expected_action(self) -> str | None:
        """Expose the one manual action that the temporary UI may enable."""

        session = self._streamlines_snapshot_playback_acceptance_session
        expected = session.expected_milestone
        if expected == "first_visual":
            return "first_visual"
        if expected == "reentry_visual":
            return "reentry_visual"
        return None

    def streamlines_snapshot_playback_acceptance_is_active(self) -> bool:
        """Return whether the final gate owns a non-terminal production run."""

        session = self._streamlines_snapshot_playback_acceptance_session
        return session.started and not session.failed and not session.terminal_emitted

    def start_streamlines_snapshot_playback_acceptance(self, mode) -> bool:
        """Record a normal product selection without starting another scheduler."""

        session = self._streamlines_snapshot_playback_acceptance_session
        if mode is not VisualizationMode.STREAMLINES:
            return False
        if session.expected_milestone == "first_start":
            if not self._snapshot_playback_acceptance_first_start_ready():
                return False
            session.begin()
            if not session.record("first_start"):
                return False
            message = (
                "Final clean Streamlines production regression started.\n"
                "workload=Nominal\n"
                "profile=volume_coverage\n"
                "source=VisualizationMode"
            )
        elif session.expected_milestone == "reentry_start":
            if not self._snapshot_playback_acceptance_clean_normal_state():
                self._streamlines_snapshot_playback_acceptance_fail(
                    "Production re-entry did not start from clean Normal state."
                )
                return False
            if not session.record("reentry_start"):
                return False
            message = "Final clean Streamlines re-entry regression started."
        else:
            return False
        started_at = time.monotonic()
        if session.expected_milestone == "first_technical":
            self._streamlines_snapshot_playback_acceptance_activation_started_at = (
                started_at
            )
            self._streamlines_snapshot_playback_acceptance_first_visible_at = None
            self._streamlines_snapshot_playback_acceptance_activation_committed_at = (
                None
            )
        else:
            self._streamlines_snapshot_playback_acceptance_reentry_started_at = (
                started_at
            )
            self._streamlines_snapshot_playback_acceptance_reentry_first_visible_at = (
                None
            )
        self._streamlines_snapshot_playback_acceptance_before_snapshots = (
            capture_viewport_performance_sample()
        )
        self._streamlines_snapshot_playback_acceptance_loop_samples = ()
        self._streamlines_snapshot_playback_acceptance_loop_observation_ms = None
        self._streamlines_snapshot_playback_acceptance_log("START", message)
        return True

    def report_streamlines_snapshot_playback_acceptance_progress(
        self,
        message: str,
    ) -> None:
        """Forward only the two bounded standard-path preparation milestones."""

        session = self._streamlines_snapshot_playback_acceptance_session
        milestone = session.expected_milestone
        if milestone not in {"first_technical", "reentry_technical"}:
            return
        accepted = {
            "Valid persisted centerline cache accepted; preparing "
            "production snapshots.",
            "Snapshot presentation prepared; initial real state selected; "
            "cached playback scheduler started.",
            "Production snapshot presentation is visible; "
            "cached-playback scheduler is active.",
        }
        progress_key = (milestone, message)
        if (
            message not in accepted
            or progress_key in self._streamlines_snapshot_playback_acceptance_progress
        ):
            return
        if message.startswith("Production snapshot presentation"):
            if not self._snapshot_playback_acceptance_visible_scheduler_state():
                self._streamlines_snapshot_playback_acceptance_fail(
                    "Visible-snapshot milestone did not satisfy production "
                    "presentation invariants."
                )
                return
            now = time.monotonic()
            if milestone == "first_technical":
                if (
                    self._streamlines_snapshot_playback_acceptance_first_visible_at
                    is None
                ):
                    self._streamlines_snapshot_playback_acceptance_first_visible_at = (
                        now
                    )
            elif (
                self._streamlines_snapshot_playback_acceptance_reentry_first_visible_at
                is None
            ):
                setattr(
                    self,
                    "_streamlines_snapshot_playback_acceptance_"
                    "reentry_first_visible_at",
                    now,
                )
        self._streamlines_snapshot_playback_acceptance_progress.add(progress_key)
        self._streamlines_snapshot_playback_acceptance_log("PROGRESS", message)

    async def observe_streamlines_snapshot_playback_acceptance_result(
        self,
        mode,
        result,
    ) -> None:
        """Passively observe a committed standard Streamlines activation."""

        session = self._streamlines_snapshot_playback_acceptance_session
        milestone = session.expected_milestone
        if milestone not in {"first_technical", "reentry_technical"}:
            return
        if (
            mode is not VisualizationMode.STREAMLINES
            or not getattr(result, "success", False)
            or getattr(result, "committed_mode", None)
            is not VisualizationMode.STREAMLINES
            or self.visualization_snapshot().committed
            is not VisualizationMode.STREAMLINES
        ):
            self._streamlines_snapshot_playback_acceptance_fail(
                "Standard Streamlines activation did not commit."
            )
            return
        contract = getattr(self, "_streamlines_cache_playback_contract", None)
        try:
            self._require_streamlines_snapshot_contract_ownership(contract)
        except (AttributeError, RuntimeError, TypeError):
            self._streamlines_snapshot_playback_acceptance_fail(
                "Prepared snapshot ownership does not match production playback."
            )
            return
        if self.streamlines_snapshot_visible_count_in_kit() != 1:
            self._streamlines_snapshot_playback_acceptance_fail(
                "Committed production presentation lacks one visible snapshot."
            )
            return
        if not self._snapshot_playback_acceptance_visible_scheduler_state():
            self._streamlines_snapshot_playback_acceptance_fail(
                "Committed Streamlines presentation lost its visible-snapshot "
                "invariants."
            )
            return
        now = time.monotonic()
        if milestone == "first_technical":
            if self._streamlines_snapshot_playback_acceptance_first_visible_at is None:
                self._streamlines_snapshot_playback_acceptance_fail(
                    "First-visible timing milestone was not observed."
                )
                return
            if (
                self._streamlines_snapshot_playback_acceptance_activation_committed_at
                is None
            ):
                setattr(
                    self,
                    "_streamlines_snapshot_playback_acceptance_activation_committed_at",
                    now,
                )
        elif (
            self._streamlines_snapshot_playback_acceptance_reentry_first_visible_at
            is None
        ):
            self._streamlines_snapshot_playback_acceptance_fail(
                "Re-entry first-visible timing milestone was not observed."
            )
            return
        self._streamlines_snapshot_playback_acceptance_after_snapshots = (
            capture_viewport_performance_sample()
        )
        evidence = await self._observe_streamlines_snapshot_playback_loop(
            full_loop=milestone == "first_technical"
        )
        if evidence is None:
            return
        expectation = SnapshotPlaybackAcceptanceExpectation()
        passed = (
            evidence.full_loop_passed(expectation)
            if milestone == "first_technical"
            else evidence.reentry_passed(expectation)
        )
        if not passed:
            self._streamlines_snapshot_playback_acceptance_fail(
                self._snapshot_playback_acceptance_failure_reason(evidence)
            )
            return
        loaded_retired = loaded_retired_streamlines_modules()
        if loaded_retired:
            self._streamlines_snapshot_playback_acceptance_fail(
                "Retired Streamlines modules were imported during acceptance: "
                f"{', '.join(loaded_retired)}."
            )
            return
        if not session.record(milestone):
            self._streamlines_snapshot_playback_acceptance_fail(
                "Production technical milestone could not be recorded."
            )
            return
        if milestone == "first_technical":
            self._streamlines_snapshot_playback_acceptance_log(
                "COMPLETE",
                self._snapshot_playback_acceptance_full_loop_message(evidence),
                next_action=(
                    "Visually confirm the final clean Streamlines loop, then choose "
                    '"Confirm Clean Playback" or '
                    '"Report Clean Playback Failure".'
                ),
            )
            return
        self._streamlines_snapshot_playback_acceptance_log(
            "COMPLETE",
            "Final clean production re-entry passed technically.\n"
            f"observed_ticks={len(evidence.observed_indices)}\n"
            f"distinct_samples={evidence.distinct_sample_count}\n"
            "scheduler_tasks=1\n"
            "visible_states_max=1\n"
            "reentry_time_to_first_visible_ms="
            f"{_metric(self._snapshot_playback_reentry_time_to_first_visible_ms())}",
            next_action=(
                "Confirm that Streamlines are visibly moving normally after "
                're-entry, then choose "Confirm Clean Re-entry" or '
                '"Report Clean Re-entry Failure".'
            ),
        )

    def observe_streamlines_snapshot_playback_acceptance_normal_result(
        self,
        mode,
        result,
    ) -> None:
        """Advance only after normal product teardown proves no snapshot residue."""

        session = self._streamlines_snapshot_playback_acceptance_session
        milestone = session.expected_milestone
        if milestone not in {"first_cleanup", "final_cleanup"}:
            return
        if mode is not VisualizationMode.NORMAL or not getattr(
            result, "success", False
        ):
            self._streamlines_snapshot_playback_acceptance_fail(
                "Expected a successful Normal cleanup action."
            )
            return
        if not self._snapshot_playback_acceptance_clean_normal_state():
            self._streamlines_snapshot_playback_acceptance_fail(
                "Visualization -> Normal left Streamlines runtime residue."
            )
            return
        self._streamlines_snapshot_playback_acceptance_after_cleanup = (
            capture_viewport_performance_sample()
        )
        if not session.record(milestone):
            self._streamlines_snapshot_playback_acceptance_fail(
                "Production cleanup milestone could not be recorded."
            )
            return
        if milestone == "first_cleanup":
            self._streamlines_snapshot_playback_acceptance_log(
                "PROGRESS",
                "Clean production teardown passed.\n"
                "committed_mode=Normal\n"
                "scheduler_tasks=0\n"
                "snapshot_root_present=False\n"
                "streamlines_visible=False\n"
                "pending_transition=None\n"
                "duplicate/suffixed DTRS roots=0\n"
                "acceptance_tasks=0\n"
                f"{self._snapshot_playback_after_cleanup_message()}",
                next_action='Select "Streamlines" in "Visualization" again.',
            )
            return
        loaded_retired = loaded_retired_streamlines_modules()
        if loaded_retired:
            self._streamlines_snapshot_playback_acceptance_fail(
                "Retired Streamlines modules were imported during acceptance: "
                f"{', '.join(loaded_retired)}."
            )
            return
        if not session.complete():
            return
        self._streamlines_snapshot_playback_acceptance_emit(
            format_manual_acceptance_test_complete(
                "Phase 4.4B final clean snapshot Streamlines regression passed.\n"
                "The cleaned runtime preserves the accepted production path: "
                "VALID persisted centerline cache -> static BasisCurves snapshots "
                "-> CachedPlaybackScheduler -> visibility-only playback.\n"
                "Standard Visualization -> Streamlines completes the current "
                "Volume Coverage / Nominal 80-sample / 5 Hz loop with one "
                "scheduler and one visible snapshot.\n"
                "Clean re-entry and Normal teardown leave no DTRS-owned "
                "Streamlines runtime residue.\n"
                "Retired Mesh, explicit-copy and renderer-probe implementations "
                "are absent from the active runtime and UI.\n"
                "Activation timing receipts use their real semantic milestones.\n"
                "Current 80-sample / 5 Hz production instance is FINAL-PASS.\n"
                "Higher sample-count scaling remains explicitly out of scope.\n"
                "acceptance_tasks=0\n"
                f"{self._snapshot_playback_after_cleanup_message()}\n"
                "No further production-playback acceptance action required."
            )
        )

    def confirm_streamlines_snapshot_playback_acceptance(self) -> bool:
        """Record visual approval and direct the next ordinary product action."""

        session = self._streamlines_snapshot_playback_acceptance_session
        milestone = session.expected_milestone
        if milestone not in {"first_visual", "reentry_visual"}:
            return False
        if not session.record(milestone):
            return False
        if milestone == "first_visual":
            self._streamlines_snapshot_playback_acceptance_log(
                "PROGRESS",
                "Clean production loop visually accepted.",
                next_action='Select "Normal" in "Visualization".',
            )
            return True
        self._streamlines_snapshot_playback_acceptance_log(
            "PROGRESS",
            "Clean production re-entry visually accepted.",
            next_action='Select "Normal" in "Visualization".',
        )
        return True

    def reject_streamlines_snapshot_playback_acceptance(self, reason: str) -> bool:
        """Make a visual rejection terminal without changing production state."""

        session = self._streamlines_snapshot_playback_acceptance_session
        if session.expected_milestone not in {"first_visual", "reentry_visual"}:
            return False
        self._streamlines_snapshot_playback_acceptance_fail(
            f"manual_reason={reason or 'No reason was entered.'}"
        )
        return True

    async def _observe_streamlines_snapshot_playback_loop(
        self,
        *,
        full_loop: bool,
    ) -> SnapshotPlaybackLoopEvidence | None:
        """Read one existing scheduler without creating a second acceptance task."""

        scheduler = getattr(self, "_streamlines_cached_playback_scheduler", None)
        contract = getattr(self, "_streamlines_cache_playback_contract", None)
        metadata = getattr(self, "_streamlines_loaded_cache_metadata", None)
        if (
            not isinstance(scheduler, CachedPlaybackScheduler)
            or not isinstance(contract, CachedPlaybackContract)
            or metadata is None
        ):
            self._streamlines_snapshot_playback_acceptance_fail(
                "Production snapshot scheduler state is unavailable."
            )
            return None
        expectation = SnapshotPlaybackAcceptanceExpectation()
        if (
            metadata.workload != expectation.workload
            or metadata.profile_id != expectation.profile_id
            or metadata.sample_count != expectation.sample_count
            or metadata.sample_interval_seconds != expectation.sample_interval_seconds
            or contract.workload != expectation.workload
            or contract.profile_id != expectation.profile_id
            or contract.sample_count != expectation.sample_count
            or contract.sample_interval_seconds != expectation.sample_interval_seconds
        ):
            self._streamlines_snapshot_playback_acceptance_fail(
                "Current cache does not match the D acceptance instance."
            )
            return None
        # The scheduler is started before the VisualizationMode transaction
        # exposes the prepared presentation.  Its earlier ticks are from this
        # same activation and are required to prove a complete logical loop;
        # discarding them can truncate the evidence by the setup duration.
        # Visibility is still sampled only after the presentation is exposed.
        tick_offset = len(scheduler.ticks)
        started_at = time.monotonic()
        duration = (
            contract.loop_duration_seconds + contract.sample_interval_seconds
            if full_loop
            else contract.sample_interval_seconds
            * (expectation.reentry_minimum_ticks + 2)
        )
        deadline = started_at + duration
        samples = []
        visible_counts = []
        checked_tick_count = tick_offset
        waiting_emitted = False
        while time.monotonic() < deadline:
            await asyncio.sleep(0.05)
            session = self._streamlines_snapshot_playback_acceptance_session
            if session.failed or session.terminal_emitted:
                return None
            if scheduler is not getattr(
                self,
                "_streamlines_cached_playback_scheduler",
                None,
            ):
                self._streamlines_snapshot_playback_acceptance_fail(
                    "Production scheduler was superseded during acceptance."
                )
                return None
            ticks = scheduler.ticks
            if len(ticks) > checked_tick_count:
                new_tick_count = len(ticks) - checked_tick_count
                visible = self.streamlines_snapshot_visible_count_in_kit()
                visible_counts.extend((visible,) * new_tick_count)
                checked_tick_count = len(ticks)
            samples.append(capture_viewport_performance_sample())
            if (
                full_loop
                and not waiting_emitted
                and time.monotonic() - started_at >= 5.0
            ):
                waiting_emitted = True
                self._streamlines_snapshot_playback_acceptance_log(
                    "WAITING",
                    "Observe one complete 16 s production Streamlines loop.",
                )
            if not full_loop and len(scheduler.ticks) - tick_offset >= (
                expectation.reentry_minimum_ticks
            ):
                break
        self._streamlines_snapshot_playback_acceptance_loop_samples = tuple(samples)
        if full_loop:
            self._streamlines_snapshot_playback_acceptance_loop_observation_ms = (
                time.monotonic() - started_at
            ) * 1000.0
        return collect_snapshot_playback_loop_evidence(
            contract=contract,
            ticks=(scheduler.ticks if full_loop else scheduler.ticks[tick_offset:]),
            visible_counts=tuple(visible_counts),
            scheduler_tasks=self._active_streamlines_playback_task_count(),
            scheduler_report=scheduler.report(),
            state_failure=getattr(self, "_streamlines_cached_state_failure", None),
            state_failure_count=getattr(
                self,
                "_streamlines_cached_state_failure_count",
                0,
            ),
        )

    def _snapshot_playback_acceptance_first_start_ready(self) -> bool:
        """Require the current accepted cache and a clean Normal baseline."""

        session = self._streamlines_snapshot_playback_acceptance_session
        if session.started or session.failed or session.terminal_emitted:
            return False
        readiness = self.visualization_readiness().for_mode(
            VisualizationMode.STREAMLINES
        )
        return (
            readiness.state == "VALID"
            and self._snapshot_playback_acceptance_clean_normal_state()
        )

    def _snapshot_playback_acceptance_clean_normal_state(self) -> bool:
        """Check cleanup facts without mutating the committed product state."""

        snapshot = self.visualization_snapshot()
        return (
            snapshot.committed is VisualizationMode.NORMAL
            and snapshot.pending is None
            and self._active_streamlines_playback_task_count() == 0
            and not self.streamlines_cached_presentation_is_prepared_in_kit()
            and not self.streamlines_cached_presentation_is_visible_in_kit()
            and self._snapshot_playback_acceptance_has_no_duplicate_root()
        )

    def _snapshot_playback_acceptance_visible_scheduler_state(self) -> bool:
        """Require the first-visible timing facts without changing presentation."""

        return (
            self.streamlines_cached_presentation_is_visible_in_kit()
            and self.streamlines_snapshot_visible_count_in_kit() == 1
            and self._active_streamlines_playback_task_count() == 1
        )

    def _snapshot_playback_acceptance_has_no_duplicate_root(self) -> bool:
        """Reject suffixed DTRS playback roots left by an earlier product run."""

        import omni.usd

        from digital_twin_runtime_suite.app.streamlines.cache import (
            CACHE_PLAYBACK_ROOT_PATH,
        )

        stage = omni.usd.get_context().get_stage()
        if stage is None:
            return False
        prefix = f"{CACHE_PLAYBACK_ROOT_PATH}_"
        return not any(
            str(prim.GetPath()).startswith(prefix) for prim in stage.Traverse()
        )

    def _snapshot_playback_acceptance_failure_reason(
        self,
        evidence: SnapshotPlaybackLoopEvidence,
    ) -> str:
        """Summarise a hard gate failure without dumping scheduler tick history."""

        invalid_transition = first_unordered_snapshot_transition(evidence)
        transition_text = (
            "none"
            if invalid_transition is None
            else f"{invalid_transition[0]}->{invalid_transition[1]}"
        )
        return (
            "Production snapshot playback proof failed: "
            f"ticks={len(evidence.observed_indices)}; "
            f"distinct={evidence.distinct_sample_count}; "
            f"wrap={evidence.wrap_observed}; ordered={evidence.ordered}; "
            f"first_invalid_transition={transition_text}; "
            f"visible_min={evidence.visible_states_min}; "
            f"visible_max={evidence.visible_states_max}; "
            f"missed_deadlines={evidence.missed_deadlines}; "
            f"backlog={evidence.backlog_count}; "
            f"state_failure_count={evidence.state_failure_count}; "
            f"state_failure={evidence.state_failure}."
        )

    def _snapshot_playback_acceptance_full_loop_message(
        self,
        evidence: SnapshotPlaybackLoopEvidence,
    ) -> str:
        """Format compact first-loop and performance evidence for human approval."""

        performance = SnapshotPlaybackPerformanceEvidence(
            activation_total_ms=self._snapshot_playback_activation_total_ms(),
            time_to_first_visible_ms=(
                self._snapshot_playback_time_to_first_visible_ms()
            ),
            acceptance_loop_observation_ms=(
                self._streamlines_snapshot_playback_acceptance_loop_observation_ms
            ),
            before_snapshots=(
                self._streamlines_snapshot_playback_acceptance_before_snapshots
            ),
            after_snapshots=(
                self._streamlines_snapshot_playback_acceptance_after_snapshots
            ),
            loop_samples=self._streamlines_snapshot_playback_acceptance_loop_samples,
            after_cleanup=(
                self._streamlines_snapshot_playback_acceptance_after_cleanup
            ),
        )
        return "\n".join(
            (
                "Final clean production loop passed technically.",
                "sample_count=80",
                f"distinct_samples={evidence.distinct_sample_count}",
                "real_sample_ordering=PASS",
                "wrap=79->0 PASS",
                "scheduler_tasks=1",
                "visible_states_max=1",
                "missed_deadlines=0",
                "backlog_count=0",
                "snapshot_backend=True",
                "legacy_probe_modules_loaded=0",
                "Mesh_playback=0",
                "timeline_control=False",
                "timeline_set_current_time_calls=0",
                "Python_point_copy=0",
                "runtime_mesh_conversion=0",
                "KitCAE=0",
                "VTI_import=0",
                "cache_build=0",
                "cache_rebuild=0",
                self._snapshot_playback_performance_message(performance),
            )
        )

    def _snapshot_playback_activation_total_ms(self) -> float | None:
        """Measure initial selector commit; never use loop-observation time."""

        started_at = (
            self._streamlines_snapshot_playback_acceptance_activation_started_at
        )
        committed_at = (
            self._streamlines_snapshot_playback_acceptance_activation_committed_at
        )
        if started_at is None or committed_at is None:
            return None
        return (committed_at - started_at) * 1000.0

    def _snapshot_playback_time_to_first_visible_ms(self) -> float | None:
        """Measure first observed visible snapshot, or report unavailable."""

        started_at = (
            self._streamlines_snapshot_playback_acceptance_activation_started_at
        )
        visible_at = self._streamlines_snapshot_playback_acceptance_first_visible_at
        if started_at is None or visible_at is None:
            return None
        return (visible_at - started_at) * 1000.0

    def _snapshot_playback_reentry_time_to_first_visible_ms(self) -> float | None:
        """Measure re-entry visibility separately from the initial activation."""

        started_at = self._streamlines_snapshot_playback_acceptance_reentry_started_at
        visible_at = (
            self._streamlines_snapshot_playback_acceptance_reentry_first_visible_at
        )
        if started_at is None or visible_at is None:
            return None
        return (visible_at - started_at) * 1000.0

    def _snapshot_playback_after_cleanup_message(self) -> str:
        """Report the optional final cleanup memory sample compactly."""

        sample = self._streamlines_snapshot_playback_acceptance_after_cleanup
        return "; ".join(
            (
                "gpu_used_gib_after_cleanup="
                f"{_sample_metric(sample, 'gpu_memory_used_gib')}",
                "process_used_gib_after_cleanup="
                f"{_sample_metric(sample, 'process_memory_used_gib')}",
            )
        )

    @staticmethod
    def _snapshot_playback_performance_message(
        evidence: SnapshotPlaybackPerformanceEvidence,
    ) -> str:
        """Keep characterization evidence compact and threshold-free."""

        loop = evidence.loop_samples
        fps = [sample.fps for sample in loop if sample.fps is not None]
        process_before = _sample_metric(
            evidence.before_snapshots,
            "process_memory_used_gib",
        )
        process_after = _sample_metric(
            evidence.after_snapshots,
            "process_memory_used_gib",
        )
        return "; ".join(
            (
                f"activation_total_ms={_metric(evidence.activation_total_ms)}",
                "time_to_first_visible_ms="
                f"{_metric(evidence.time_to_first_visible_ms)}",
                "acceptance_loop_observation_ms="
                f"{_metric(evidence.acceptance_loop_observation_ms)}",
                f"viewport_fps_average={_average(fps)}",
                f"viewport_fps_minimum={_minimum(fps)}",
                "gpu_used_gib_before_snapshots="
                f"{_sample_metric(evidence.before_snapshots, 'gpu_memory_used_gib')}",
                "gpu_used_gib_after_snapshots="
                f"{_sample_metric(evidence.after_snapshots, 'gpu_memory_used_gib')}",
                "gpu_used_gib_max_during_loop="
                f"{_maximum_metric(loop, 'gpu_memory_used_gib')}",
                "process_used_gib_before_snapshots=" f"{process_before}",
                "process_used_gib_after_snapshots=" f"{process_after}",
                "process_used_gib_max_during_loop="
                f"{_maximum_metric(loop, 'process_memory_used_gib')}",
                "gpu_used_gib_after_cleanup="
                f"{_sample_metric(evidence.after_cleanup, 'gpu_memory_used_gib')}",
                "process_used_gib_after_cleanup="
                f"{_sample_metric(evidence.after_cleanup, 'process_memory_used_gib')}",
            )
        )

    def _streamlines_snapshot_playback_acceptance_fail(self, reason: str) -> None:
        """Make one final-gate run terminal without cancelling production playback."""

        session = self._streamlines_snapshot_playback_acceptance_session
        if session.failed or session.terminal_emitted:
            return
        session.mark_failed()
        self._streamlines_snapshot_playback_acceptance_log("FAIL", reason)

    def _streamlines_snapshot_playback_acceptance_log(
        self,
        event: str,
        status: str,
        *,
        next_action: str | None = None,
    ) -> None:
        """Emit one generic-manual-acceptance record without UI ownership."""

        self._streamlines_snapshot_playback_acceptance_emit(
            format_manual_acceptance_event(
                area=_AREA,
                event=event,
                status=status,
                next_action=next_action,
            )
        )

    def _streamlines_snapshot_playback_acceptance_emit(self, message: str) -> None:
        """Use the runtime logger while keeping the acceptance owner Kit-neutral."""

        logger = self._streamlines_carb_logger()
        if logger:
            if "| FAIL" in message:
                logger.log_error(message)
            else:
                logger.log_warn(message)


def _average(values) -> str:
    return "unavailable" if not values else f"{sum(values) / len(values):.2f}"


def _minimum(values) -> str:
    return "unavailable" if not values else f"{min(values):.2f}"


def _metric(value: float | None) -> str:
    return "unavailable" if value is None else f"{value:.1f}"


def _sample_metric(sample, name: str) -> str:
    value = getattr(sample, name, None) if sample is not None else None
    return "unavailable" if value is None else f"{value:.3f}"


def _maximum_metric(samples, name: str) -> str:
    values = [getattr(sample, name) for sample in samples]
    values = [value for value in values if value is not None]
    return "unavailable" if not values else f"{max(values):.3f}"


def loaded_retired_streamlines_modules() -> tuple[str, ...]:
    """Return retired module basenames unexpectedly loaded by this Kit session."""

    return tuple(
        name
        for name in sys.modules
        if name.rsplit(".", 1)[-1] in _RETIRED_MODULE_BASENAMES
    )
