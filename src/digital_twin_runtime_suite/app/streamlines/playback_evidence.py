"""Read-only evidence for the one active production Streamlines presentation."""

from __future__ import annotations

from dataclasses import dataclass

from digital_twin_runtime_suite.app.streamlines.playback import (
    CachedPlaybackContract,
)


@dataclass(frozen=True)
class StreamlinesPlaybackEvidence:
    """Expose active snapshot and scheduler facts without renderer mutation."""

    workload: str | None
    dataset_identity: str | None
    profile_id: str | None
    cache_identity: str | None
    sample_count: int
    loop_duration_seconds: float
    snapshot_count: int
    snapshot_root_present: bool
    snapshot_root_count: int
    visible_snapshots: int
    active_sample_index: int | None
    visible_snapshot_sample_index: int | None
    visible_snapshot_matches_persisted_geometry: bool
    scheduler_tasks: int
    missed_deadlines: int | None
    backlog: int | None
    loop_wrap_count: int
    observed_sample_indices: tuple[int, ...]
    streamlines_visible: bool
    cache_build_active: bool
    kit_cae_calls_during_playback: int
    vti_imports_during_playback: int
    workload_transition_pending: bool
    profile_transition_pending: bool


class StreamlinesPlaybackEvidenceMixin:
    """Publish public playback state for workflows without changing playback."""

    def streamlines_playback_evidence(self) -> StreamlinesPlaybackEvidence:
        """Return facts for the sole active cache; no cache work is initiated."""

        contract = getattr(self, "_streamlines_cache_playback_contract", None)
        if not isinstance(contract, CachedPlaybackContract):
            contract = None
        snapshots = getattr(self, "_streamlines_snapshot_set_ownership", None)
        scheduler = getattr(self, "_streamlines_cached_playback_scheduler", None)
        report = scheduler.report() if scheduler is not None else None
        visible_snapshot = self.streamlines_snapshot_active_state_ownership()
        proofs = self.streamlines_state_replacement_proofs()
        airflow_state = getattr(self, "_airflow_state", None)
        profile_snapshot = self.streamlines_profile_preference_snapshot()
        return StreamlinesPlaybackEvidence(
            workload=contract.workload if contract else None,
            dataset_identity=contract.dataset_identity if contract else None,
            profile_id=contract.profile_id if contract else None,
            cache_identity=contract.cache_identity if contract else None,
            sample_count=contract.sample_count if contract else 0,
            loop_duration_seconds=(contract.loop_duration_seconds if contract else 0.0),
            snapshot_count=len(snapshots.states) if snapshots is not None else 0,
            snapshot_root_present=snapshots is not None,
            snapshot_root_count=self.streamlines_snapshot_root_count_in_kit(),
            visible_snapshots=self.streamlines_snapshot_visible_count_in_kit(),
            active_sample_index=getattr(
                self,
                "_streamlines_cache_active_sample_index",
                None,
            ),
            visible_snapshot_sample_index=(
                visible_snapshot.sample_index if visible_snapshot is not None else None
            ),
            visible_snapshot_matches_persisted_geometry=(
                visible_snapshot.matches_persisted_geometry
                if visible_snapshot is not None
                else False
            ),
            scheduler_tasks=self._active_streamlines_playback_task_count(),
            missed_deadlines=report.missed_deadlines if report else None,
            backlog=report.backlog_count if report else None,
            loop_wrap_count=report.loop_wrap_count if report else 0,
            observed_sample_indices=tuple(
                proof.requested_sample_index for proof in proofs
            ),
            streamlines_visible=(
                self.streamlines_cached_presentation_is_visible_in_kit()
            ),
            cache_build_active=(
                getattr(self, "_streamlines_cache_build_active_sample_index", None)
                is not None
            ),
            kit_cae_calls_during_playback=0,
            vti_imports_during_playback=0,
            workload_transition_pending=bool(
                airflow_state is not None and airflow_state.pending is not None
            ),
            profile_transition_pending=profile_snapshot.pending_profile is not None,
        )
