"""Guided proof for final profile-aware cached Streamlines playback."""

from __future__ import annotations

import asyncio
import math
import time
from dataclasses import dataclass
from statistics import median

from digital_twin_runtime_suite.app.diagnostics import with_dtrs_yerevan_timestamp
from digital_twin_runtime_suite.app.flow.performance import (
    capture_viewport_performance_sample,
)
from digital_twin_runtime_suite.app.manual_acceptance import (
    GuidedAcceptanceSession,
    format_manual_acceptance_event,
    format_manual_acceptance_test_complete,
)
from digital_twin_runtime_suite.app.streamlines.cache import (
    CACHE_PLAYBACK_CURVES_PATH,
)
from digital_twin_runtime_suite.app.streamlines.cadence_probe import (
    resolved_cache_state_wrap_transition,
)
from digital_twin_runtime_suite.app.streamlines.constant_topology import (
    StreamlinesPointArraySignature,
    probe_persisted_streamlines_point_signatures,
    streamlines_point_array_signature,
)
from digital_twin_runtime_suite.app.streamlines.lifecycle import (
    streamlines_duplicate_runtime_prim_count,
)
from digital_twin_runtime_suite.app.streamlines.profile import (
    StreamlinesProfileId,
    final_geometry_contract,
    geometry_contract_signature,
)
from digital_twin_runtime_suite.app.streamlines.speed import (
    SPEED_PRIMVAR_ATTRIBUTE,
)
from digital_twin_runtime_suite.app.visualization_mode.model import VisualizationMode

_AREA = "STREAMLINES | PHASE_4_4B_CACHE_PLAYBACK"
_CONSTANT_TOPOLOGY_AREA = "STREAMLINES | PHASE_4_4B_CONSTANT_TOPOLOGY"
_EXPLICIT_PRESENTATION_AREA = "STREAMLINES | PHASE_4_4B_EXPLICIT_PRESENTATION"
_POINT_PROBE_SAMPLE_INDICES = (0, 1, 2, 10, 79)
_MILESTONES = (
    "volume_nominal_loop",
    "global_nominal",
    "global_surge",
    "volume_surge",
    "normal",
)


@dataclass(frozen=True)
class StreamlinesCacheLoopSanityEvidence:
    """Observed production playback evidence without assuming fixed topology."""

    profile_id: StreamlinesProfileId
    workload: str
    sample_count: int
    sample_interval_seconds: float
    scheduler_tasks: int
    tick_count: int
    distinct_sample_count: int
    wrap_transition: tuple[int, int] | None
    replacements_passed: bool
    composed_samples_passed: bool
    renderer_integrity_passed: bool
    duplicate_presentation_prims: int

    @property
    def passed(self) -> bool:
        return (
            self.profile_id is StreamlinesProfileId.VOLUME_COVERAGE
            and self.workload == "Nominal"
            and self.sample_count == 80
            and math.isclose(self.sample_interval_seconds, 0.2)
            and self.scheduler_tasks == 1
            and self.tick_count >= 2
            and self.distinct_sample_count > 1
            and self.wrap_transition == (79, 0)
            and self.replacements_passed
            and self.composed_samples_passed
            and self.renderer_integrity_passed
            and self.duplicate_presentation_prims == 0
        )


@dataclass(frozen=True)
class StreamlinesComposedSampleProbe:
    """Count exact authored arrays without retaining large geometry payloads."""

    sample_index: int
    requested_time_code: float
    timeline_current_time_seconds: float
    resolved_usd_time_code: float
    point_count: int
    required_point_count: int
    curve_count: int
    speed_count: int

    @property
    def passed(self) -> bool:
        return (
            self.point_count == self.required_point_count
            and self.speed_count == self.point_count
        )


@dataclass(frozen=True)
class StreamlinesTemporalPointMatch:
    """Persisted/composed point evidence captured after one real selection."""

    sample_index: int
    requested_time_code: float
    selected_timeline_time_seconds: float
    composed_usd_time_code: float
    persisted: StreamlinesPointArraySignature
    composed: StreamlinesPointArraySignature

    @property
    def signatures_match(self) -> bool:
        return (
            self.persisted.point_count == self.composed.point_count
            and self.persisted.sha256 == self.composed.sha256
        )


@dataclass(frozen=True)
class StreamlinesTemporalPointEvidence:
    """Require real point variation, not merely advancing sample identities."""

    required_sample_indices: tuple[int, ...]
    matches: tuple[StreamlinesTemporalPointMatch, ...]
    expected_point_count: int

    @property
    def passed(self) -> bool:
        observed = tuple(match.sample_index for match in self.matches)
        persisted_signatures = {match.persisted.sha256 for match in self.matches}
        composed_signatures = {match.composed.sha256 for match in self.matches}
        return (
            observed == self.required_sample_indices
            and len(persisted_signatures) >= 2
            and len(composed_signatures) >= 2
            and all(
                match.signatures_match
                and match.persisted.point_count == self.expected_point_count
                and match.composed.point_count == self.expected_point_count
                for match in self.matches
            )
        )


def evaluate_streamlines_temporal_point_matches(
    matches,
    *,
    required_sample_indices: tuple[int, ...] = _POINT_PROBE_SAMPLE_INDICES,
    expected_point_count: int = 122_880,
) -> StreamlinesTemporalPointEvidence:
    """Order exact per-sample matches and reject static composed geometry."""

    by_index = {match.sample_index: match for match in matches}
    ordered = tuple(
        by_index[index] for index in required_sample_indices if index in by_index
    )
    return StreamlinesTemporalPointEvidence(
        required_sample_indices=required_sample_indices,
        matches=ordered,
        expected_point_count=expected_point_count,
    )


def streamlines_sample_array_probe(
    *,
    sample_index: int,
    requested_time_code: float,
    timeline_current_time_seconds: float,
    resolved_usd_time_code: float,
    points,
    curve_vertex_counts,
    speed_values,
) -> StreamlinesComposedSampleProbe:
    """Reduce exact USD arrays without normalising, padding, or mutating them."""

    return StreamlinesComposedSampleProbe(
        sample_index=sample_index,
        requested_time_code=requested_time_code,
        timeline_current_time_seconds=timeline_current_time_seconds,
        resolved_usd_time_code=resolved_usd_time_code,
        point_count=len(points),
        required_point_count=sum(curve_vertex_counts),
        curve_count=len(curve_vertex_counts),
        speed_count=len(speed_values),
    )


def probe_streamlines_sample_attributes(
    *,
    sample_index: int,
    requested_time_code: float,
    timeline_current_time_seconds: float,
    resolved_usd_time_code: float,
    usd_time_code,
    points_attr,
    curve_vertex_counts_attr,
    speed_attr,
) -> StreamlinesComposedSampleProbe:
    """Read all three arrays at one identical explicit USD time code."""

    return streamlines_sample_array_probe(
        sample_index=sample_index,
        requested_time_code=requested_time_code,
        timeline_current_time_seconds=timeline_current_time_seconds,
        resolved_usd_time_code=resolved_usd_time_code,
        points=points_attr.Get(usd_time_code),
        curve_vertex_counts=curve_vertex_counts_attr.Get(usd_time_code),
        speed_values=speed_attr.Get(usd_time_code),
    )


def evaluate_streamlines_cache_loop(
    *,
    profile_id: StreamlinesProfileId,
    workload: str,
    sample_count: int,
    sample_interval_seconds: float,
    scheduler_tasks: int,
    ticks: tuple,
    replacement_proofs: tuple,
    composed_sample_probes: tuple[StreamlinesComposedSampleProbe, ...],
    renderer_integrity_passed: bool,
    duplicate_presentation_prims: int,
) -> StreamlinesCacheLoopSanityEvidence:
    """Reduce actual scheduler ticks; variable curve topology is intentionally valid."""

    indices = tuple(tick.resolution.sample.sample_index for tick in ticks)
    evidence = StreamlinesCacheLoopSanityEvidence(
        profile_id=StreamlinesProfileId(profile_id),
        workload=workload,
        sample_count=sample_count,
        sample_interval_seconds=sample_interval_seconds,
        scheduler_tasks=scheduler_tasks,
        tick_count=len(ticks),
        distinct_sample_count=len(set(indices)),
        wrap_transition=resolved_cache_state_wrap_transition(ticks),
        replacements_passed=(
            bool(replacement_proofs)
            and len(replacement_proofs) >= len(ticks)
            and all(proof.passed for proof in replacement_proofs[-len(ticks) :])
        ),
        composed_samples_passed=(
            bool(composed_sample_probes)
            and all(probe.passed for probe in composed_sample_probes)
        ),
        renderer_integrity_passed=renderer_integrity_passed,
        duplicate_presentation_prims=duplicate_presentation_prims,
    )
    return evidence


class StreamlinesCachePlaybackSanityMixin:
    """Observe production selectors and playback; never create presentation work."""

    def reset_streamlines_cache_playback_sanity_state(self) -> None:
        for task in getattr(self, "_streamlines_temporal_point_probe_tasks", ()):
            if not task.done():
                task.cancel()
        for task in getattr(self, "_streamlines_explicit_hash_tasks", ()):
            if not task.done():
                task.cancel()
        self._streamlines_cache_playback_sanity_session = None
        self._streamlines_cache_playback_sanity_ready_emitted = False
        self._streamlines_cache_playback_sanity_evidence = None
        self._streamlines_constant_topology_session = None
        self._streamlines_constant_topology_ready_emitted = False
        self._streamlines_temporal_point_probe_generation = (
            getattr(self, "_streamlines_temporal_point_probe_generation", 0) + 1
        )
        self._streamlines_temporal_point_probe_tasks = set()
        self._streamlines_temporal_point_probe_pending_indices = set()
        self._streamlines_temporal_point_persisted = {}
        self._streamlines_temporal_point_matches = {}
        self._streamlines_explicit_presentation_session = None
        self._streamlines_explicit_presentation_ready_emitted = False
        self._streamlines_explicit_hash_tasks = set()
        self._streamlines_explicit_hash_pending = set()
        self._streamlines_explicit_hash_matches = {}

    def announce_streamlines_phase44b_explicit_presentation_when_ready(self) -> bool:
        """Offer the explicit-property Volume/Nominal prototype only."""

        if getattr(self, "_streamlines_explicit_presentation_ready_emitted", False):
            return False
        target = next(
            (
                item
                for item in self.final_streamlines_cache_readiness_snapshot()
                if item.workload == "Nominal"
                and item.profile_id is StreamlinesProfileId.VOLUME_COVERAGE
            ),
            None,
        )
        metadata = getattr(getattr(target, "inspection", None), "metadata", None)
        if (
            target is None
            or target.inspection.classification != "VALID"
            or metadata is None
            or metadata.schema_version != 5
            or not metadata.topology_consistent
            or any(
                state.curve_count != 6144 or state.point_count != 122880
                for state in metadata.states
            )
            or self.visualization_snapshot().pending is not None
            or self._airflow_state.snapshot.pending is not None
        ):
            return False
        session = GuidedAcceptanceSession(("technical", "visual"))
        session.begin()
        self._streamlines_explicit_presentation_session = session
        self._streamlines_explicit_presentation_ready_emitted = True
        self._streamlines_explicit_presentation_log(
            "READY",
            "Volume Coverage / Nominal schema-5 cache is ready for explicit playback.",
            next_action=(
                "Start explicit cached Streamlines playback for Volume Coverage / "
                "Nominal."
            ),
        )
        return True

    def announce_streamlines_phase44b_constant_topology_when_ready(self) -> bool:
        """The failed timeline-driven prototype is retired permanently."""

        return False

    def _retired_announce_streamlines_phase44b_constant_topology_when_ready(
        self,
    ) -> bool:
        """Retained implementation evidence; no production caller reaches it."""

        if getattr(self, "_streamlines_constant_topology_ready_emitted", False):
            return False
        target = next(
            (
                item
                for item in self.final_streamlines_cache_readiness_snapshot()
                if item.workload == "Nominal"
                and item.profile_id is StreamlinesProfileId.VOLUME_COVERAGE
            ),
            None,
        )
        metadata = getattr(
            getattr(target, "inspection", None),
            "metadata",
            None,
        )
        profile = self.streamlines_profile_preference_snapshot()
        if (
            target is None
            or target.inspection.classification != "VALID"
            or metadata is None
            or metadata.schema_version != 5
            or not metadata.topology_consistent
            or any(
                state.curve_count != 6144 or state.point_count != 122880
                for state in metadata.states
            )
            or getattr(self, "_streamlines_cache_build_active_sample_index", None)
            is not None
            or profile.pending_profile is not None
            or self._airflow_state.snapshot.pending is not None
            or self.visualization_snapshot().pending is not None
        ):
            return False
        session = GuidedAcceptanceSession(("loop",))
        session.begin()
        self._streamlines_constant_topology_session = session
        self._streamlines_constant_topology_ready_emitted = True
        self._streamlines_constant_topology_log(
            "READY",
            "Volume Coverage / Nominal schema-5 cache is VALID and fixed-topology.",
            next_action=(
                "Load Volume Coverage / Nominal constant-topology cache and run "
                "playback prototype."
            ),
        )
        return True

    def announce_streamlines_phase44b_cache_playback_when_ready(self) -> bool:
        if getattr(self, "_streamlines_cache_playback_sanity_ready_emitted", False):
            return False
        if not self._streamlines_cache_playback_preconditions_pass():
            return False
        session = GuidedAcceptanceSession(_MILESTONES)
        session.begin()
        self._streamlines_cache_playback_sanity_session = session
        self._streamlines_cache_playback_sanity_ready_emitted = True
        self._streamlines_cache_playback_sanity_log(
            "READY",
            "All 8 final caches are VALID and no transition/build is pending.",
            next_action=(
                'Select "Volume Coverage" in "Profile", select "Nominal" in '
                '"Workload", then select "Streamlines" in "Visualization".'
            ),
        )
        return True

    def _streamlines_cache_playback_preconditions_pass(self) -> bool:
        snapshots = self.final_streamlines_cache_readiness_snapshot()
        if len(snapshots) != 8:
            return False
        for snapshot in snapshots:
            inspection = snapshot.inspection
            metadata = getattr(inspection, "metadata", None)
            settings = getattr(metadata, "settings", None)
            expected = geometry_contract_signature(
                final_geometry_contract(snapshot.profile_id)
            )
            if (
                inspection.classification != "VALID"
                or metadata is None
                or metadata.profile_id != snapshot.profile_id.value
                or settings is None
                or settings.profile_signature != expected
                or "primvars:dtrs:speed" not in settings.persisted_attributes
            ):
                return False
        profile = self.streamlines_profile_preference_snapshot()
        return not any(
            (
                getattr(self, "_streamlines_cache_build_active_sample_index", None)
                is not None,
                profile.pending_profile is not None,
                self._airflow_state.snapshot.pending is not None,
                self.visualization_snapshot().pending is not None,
            )
        )

    def phase44b_cache_playback_start_visualization(self, mode) -> None:
        explicit_session = self._streamlines_explicit_presentation_active_session()
        if explicit_session is not None:
            mode = VisualizationMode(mode)
            if mode is VisualizationMode.STREAMLINES:
                self._streamlines_explicit_presentation_log(
                    "START",
                    "Starting explicit Volume Coverage / Nominal cached playback.",
                )
            else:
                self._streamlines_explicit_presentation_fail(
                    "Prototype requires Visualization=Streamlines."
                )
            return
        constant_session = self._streamlines_constant_topology_active_session()
        if constant_session is not None:
            mode = VisualizationMode(mode)
            if mode is VisualizationMode.STREAMLINES:
                self._streamlines_constant_topology_log(
                    "START",
                    "Starting Volume Coverage / Nominal production cache loop.",
                )
            else:
                self._streamlines_constant_topology_fail(
                    "Prototype requires Visualization=Streamlines."
                )
            return
        session = self._streamlines_cache_playback_sanity_active_session()
        if session is None:
            return
        mode = VisualizationMode(mode)
        expected = session.expected_milestone
        if (
            expected == "volume_nominal_loop" and mode is VisualizationMode.STREAMLINES
        ) or (expected == "normal" and mode is VisualizationMode.NORMAL):
            self._streamlines_cache_playback_sanity_log(
                "START", f"Requested production visualization={mode.value}."
            )
            return
        self._streamlines_cache_playback_sanity_fail(
            "Unexpected visualization request: "
            f"expected={expected}; selected={mode.value}."
        )

    def phase44b_cache_playback_start_profile(self, profile_id) -> None:
        session = self._streamlines_cache_playback_sanity_active_session()
        if session is None:
            return
        profile_id = StreamlinesProfileId(profile_id)
        expected = session.expected_milestone
        expected_profile = {
            "global_nominal": StreamlinesProfileId.GLOBAL_FLOW_PATH,
            "volume_surge": StreamlinesProfileId.VOLUME_COVERAGE,
        }.get(expected)
        if expected_profile is profile_id:
            self._streamlines_cache_playback_sanity_log(
                "START", f"Requested cached profile={profile_id.value}."
            )
            return
        self._streamlines_cache_playback_sanity_fail(
            "Unexpected profile request: "
            f"expected={expected_profile}; selected={profile_id.value}."
        )

    def phase44b_cache_playback_start_workload(self, workload: str) -> None:
        session = self._streamlines_cache_playback_sanity_active_session()
        if session is None:
            return
        if (
            session.expected_milestone == "volume_nominal_loop"
            and workload == "Nominal"
        ):
            self._streamlines_cache_playback_sanity_log(
                "PROGRESS", "Initial workload preference selected: Nominal."
            )
            return
        if session.expected_milestone == "global_surge" and workload == "Surge":
            self._streamlines_cache_playback_sanity_log(
                "START", "Requested cached workload=Surge."
            )
            return
        self._streamlines_cache_playback_sanity_fail(
            "Unexpected workload request: expected=Surge; " f"selected={workload}."
        )

    async def phase44b_cache_playback_observe_visualization_result(
        self, mode, result, *, status_callback=None
    ) -> None:
        if self._streamlines_explicit_presentation_active_session() is not None:
            if not result.success:
                self._streamlines_explicit_presentation_fail(result.message)
                return
            if VisualizationMode(mode) is not VisualizationMode.STREAMLINES:
                self._streamlines_explicit_presentation_fail(
                    "Prototype did not activate Streamlines."
                )
                return
            await self._observe_explicit_presentation_loop(status_callback)
            return
        if self._streamlines_constant_topology_active_session() is not None:
            if not result.success:
                self._streamlines_constant_topology_fail(result.message)
                return
            if VisualizationMode(mode) is not VisualizationMode.STREAMLINES:
                self._streamlines_constant_topology_fail(
                    "Prototype did not activate Streamlines."
                )
                return
            await self._observe_constant_topology_prototype_loop(status_callback)
            return
        session = self._streamlines_cache_playback_sanity_active_session()
        if session is None:
            return
        mode = VisualizationMode(mode)
        if not result.success:
            self._streamlines_cache_playback_sanity_fail(result.message)
            return
        if mode is VisualizationMode.STREAMLINES:
            await self._observe_streamlines_full_loop(status_callback)
        elif mode is VisualizationMode.NORMAL:
            self._complete_streamlines_normal_exit()

    def phase44b_cache_playback_observe_profile_result(
        self, profile_id, result
    ) -> None:
        session = self._streamlines_cache_playback_sanity_active_session()
        if session is None:
            return
        profile_id = StreamlinesProfileId(profile_id)
        if not result.success:
            self._streamlines_cache_playback_sanity_fail(result.message)
            return
        evidence = self.streamlines_profile_transition_evidence()
        airflow = self._airflow_state.committed
        loaded = getattr(self, "_streamlines_loaded_cache_metadata", None)
        if not (
            evidence
            and evidence.committed_profile is profile_id
            and evidence.normalized_phase_preserved
            and evidence.sample_advanced
            and evidence.scheduler_tasks == 1
            and evidence.reference_swap_passed
            and evidence.server_scene_composition_mutations == 0
            and airflow
            and airflow.workload_mode == evidence.workload
            and loaded
            and loaded.profile_id == profile_id.value
            and loaded.workload == evidence.workload
            and loaded.dataset_identity == evidence.dataset_identity
            and self._active_streamlines_playback_task_count() == 1
            and self._streamlines_duplicate_prim_count() == 0
        ):
            self._streamlines_cache_playback_sanity_fail(
                f"Cached profile target proof failed: profile={profile_id.value}."
            )
            return
        self._streamlines_cache_playback_sanity_record(
            session.expected_milestone,
            "profile="
            f"{profile_id.value}; workload={evidence.workload}; "
            "sample_advanced=True; scheduler_tasks=1; "
            "shared_normalized_phase_preserved=True; local_reference_swap=PASS; "
            "server_scene_composition_mutations=0; duplicate_presentation_prims=0; "
            "cache_build=0; cache_rebuild=0; KitCAE_execution=0; "
            "VTI_presentation_import=0; runtime_recompute=0.",
        )

    def phase44b_cache_playback_observe_workload_result(self, workload, result) -> None:
        session = self._streamlines_cache_playback_sanity_active_session()
        if session is None:
            return
        if not result.success:
            self._streamlines_cache_playback_sanity_fail(result.message)
            return
        evidence = self.streamlines_workload_transition_evidence()
        profile = self.streamlines_profile_preference_snapshot()
        loaded = getattr(self, "_streamlines_loaded_cache_metadata", None)
        if not (
            evidence
            and evidence.committed_workload == workload
            and evidence.target_cache == "VALID"
            and evidence.normalized_phase_preserved
            and evidence.sample_advanced
            and evidence.scheduler_tasks == 1
            and evidence.streamlines_reference_swap
            and evidence.server_scene_composition_mutations == 0
            and profile.committed_profile is StreamlinesProfileId.GLOBAL_FLOW_PATH
            and loaded
            and loaded.workload == workload
            and loaded.profile_id == StreamlinesProfileId.GLOBAL_FLOW_PATH.value
            and loaded.dataset_identity == evidence.target_dataset
            and self._active_streamlines_playback_task_count() == 1
            and self._streamlines_duplicate_prim_count() == 0
        ):
            self._streamlines_cache_playback_sanity_fail(
                f"Cached workload target proof failed: workload={workload}."
            )
            return
        self._streamlines_cache_playback_sanity_record(
            "global_surge",
            "profile=global_flow_path; workload=Surge; sample_advanced=True; "
            "scheduler_tasks=1; shared_normalized_phase_preserved=True; "
            "local_reference_swap=PASS; server_scene_composition_mutations=0; "
            "duplicate_presentation_prims=0; cache_build=0; cache_rebuild=0; "
            "KitCAE_execution=0; VTI_presentation_import=0; runtime_recompute=0.",
        )

    async def _observe_streamlines_full_loop(self, status_callback) -> None:
        session = self._streamlines_cache_playback_sanity_active_session()
        scheduler = getattr(self, "_streamlines_cached_playback_scheduler", None)
        metadata = getattr(self, "_streamlines_loaded_cache_metadata", None)
        airflow = self._airflow_state.committed
        profile = self.streamlines_profile_preference_snapshot()
        if not (
            session
            and session.expected_milestone == "volume_nominal_loop"
            and metadata
            and airflow
            and metadata.profile_id == StreamlinesProfileId.VOLUME_COVERAGE.value
            and metadata.workload == "Nominal"
            and airflow.workload_mode == "Nominal"
            and profile.committed_profile is StreamlinesProfileId.VOLUME_COVERAGE
            and scheduler is not None
            and self._active_streamlines_playback_task_count() == 1
        ):
            self._streamlines_cache_playback_sanity_fail(
                "Volume Coverage / Nominal production cache was not attached "
                "exactly once."
            )
            return
        tick_offset = len(scheduler.ticks)
        proof_offset = len(self.streamlines_state_replacement_proofs())
        self._streamlines_cache_playback_sanity_log(
            "PROGRESS", "Final Volume Coverage / Nominal cache attached."
        )
        started = time.monotonic()
        duration = metadata.sample_count * metadata.sample_interval_seconds + 0.4
        next_wait = 5.0
        while time.monotonic() - started < duration:
            await asyncio.sleep(0.1)
            if scheduler is not getattr(
                self, "_streamlines_cached_playback_scheduler", None
            ):
                self._streamlines_cache_playback_sanity_fail(
                    "Production scheduler was replaced during full-loop observation."
                )
                return
            elapsed = time.monotonic() - started
            if elapsed >= next_wait:
                self._streamlines_cache_playback_sanity_log(
                    "WAITING",
                    f"Observing one complete 16 s loop; elapsed={int(elapsed)} s.",
                )
                next_wait += 5.0
        ticks = tuple(scheduler.ticks[tick_offset:])
        proofs = self.streamlines_state_replacement_proofs()[proof_offset:]
        probes = self._probe_observed_streamlines_samples_in_kit(metadata, ticks)
        mismatch = next((probe for probe in probes if not probe.passed), None)
        if mismatch is not None:
            self._streamlines_cache_playback_sanity_fail(
                "Composed cache sample arrays are inconsistent: "
                f"sample_index={mismatch.sample_index}; "
                f"point_count={mismatch.point_count}; "
                f"required_point_count={mismatch.required_point_count}; "
                f"speed_count={mismatch.speed_count}."
            )
            return
        point_counts = {probe.point_count for probe in probes}
        renderer_integrity_passed = len(point_counts) == 1
        evidence = evaluate_streamlines_cache_loop(
            profile_id=StreamlinesProfileId.VOLUME_COVERAGE,
            workload="Nominal",
            sample_count=metadata.sample_count,
            sample_interval_seconds=metadata.sample_interval_seconds,
            scheduler_tasks=self._active_streamlines_playback_task_count(),
            ticks=ticks,
            replacement_proofs=proofs,
            composed_sample_probes=probes,
            renderer_integrity_passed=renderer_integrity_passed,
            duplicate_presentation_prims=self._streamlines_duplicate_prim_count(),
        )
        self._streamlines_cache_playback_sanity_evidence = evidence
        if not renderer_integrity_passed:
            changed = next(
                probe for probe in probes if probe.point_count != probes[0].point_count
            )
            self._streamlines_cache_playback_sanity_fail(
                "RTX/Hydra variable-topology presentation integrity is not proven: "
                "composed USD arrays are valid but the renderer retained an older "
                "points buffer during the real run; "
                f"sample_index={changed.sample_index}; "
                f"point_count={changed.point_count}; "
                f"required_point_count={changed.required_point_count}; "
                f"speed_count={changed.speed_count}; "
                f"previous_point_count={probes[0].point_count}."
            )
            return
        if not evidence.passed:
            self._streamlines_cache_playback_sanity_fail(
                "Full-loop proof failed: "
                f"ticks={evidence.tick_count}; "
                f"distinct={evidence.distinct_sample_count}; "
                f"wrap={evidence.wrap_transition}; "
                f"replacements={evidence.replacements_passed}."
            )
            return
        self._streamlines_cache_playback_sanity_log(
            "PROGRESS",
            "Cached temporal samples are advancing and replacing prior state.",
        )
        self._streamlines_cache_playback_sanity_record(
            "volume_nominal_loop",
            "profile=volume_coverage; workload=Nominal; cache_valid=True; "
            "sample_count=80; sample_interval_seconds=0.2; scheduler_tasks=1; "
            f"ticks={evidence.tick_count}; "
            f"distinct_samples={evidence.distinct_sample_count}; "
            "sample_advanced=True; multiple_distinct_samples_observed=True; "
            "wraparound_79_to_0=True; temporal_state_replacement=True; "
            "duplicate_presentation_prims=0; cache_build=0; cache_rebuild=0; "
            "KitCAE_execution=0; VTI_presentation_import=0; runtime_recompute=0.",
        )
        if status_callback:
            status_callback(
                "Cached playback sanity loop passed; inspect viewport integrity."
            )

    async def _observe_constant_topology_prototype_loop(self, status_callback) -> None:
        """Observe one real fixed-topology loop without starting another scheduler."""

        scheduler = getattr(self, "_streamlines_cached_playback_scheduler", None)
        metadata = getattr(self, "_streamlines_loaded_cache_metadata", None)
        airflow = self._airflow_state.committed
        profile = self.streamlines_profile_preference_snapshot()
        if not (
            metadata
            and airflow
            and metadata.profile_id == StreamlinesProfileId.VOLUME_COVERAGE.value
            and metadata.workload == "Nominal"
            and metadata.topology_consistent
            and airflow.workload_mode == "Nominal"
            and profile.committed_profile is StreamlinesProfileId.VOLUME_COVERAGE
            and scheduler is not None
            and self._active_streamlines_playback_task_count() == 1
        ):
            self._streamlines_constant_topology_fail(
                "Volume Coverage / Nominal fixed-topology cache is not active."
            )
            return
        try:
            await self._prepare_streamlines_temporal_point_probe(metadata)
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            self._streamlines_constant_topology_fail(
                f"Persisted temporal-point proof failed: {error}"
            )
            return
        tick_offset = len(scheduler.ticks)
        proof_offset = len(self.streamlines_state_replacement_proofs())
        self._streamlines_constant_topology_log(
            "PROGRESS",
            "Constant-topology cache attached; observing exact temporal states.",
        )
        started = time.monotonic()
        duration = metadata.sample_count * metadata.sample_interval_seconds + 0.4
        next_wait = 5.0
        while time.monotonic() - started < duration:
            await asyncio.sleep(0.1)
            if self._streamlines_constant_topology_active_session() is None:
                return
            if scheduler is not getattr(
                self,
                "_streamlines_cached_playback_scheduler",
                None,
            ):
                self._streamlines_constant_topology_fail(
                    "Prototype scheduler was replaced during loop observation."
                )
                return
            elapsed = time.monotonic() - started
            if elapsed >= next_wait:
                self._streamlines_constant_topology_log(
                    "WAITING",
                    f"Observing complete 16 s loop; elapsed={int(elapsed)} s.",
                )
                next_wait += 5.0
        probe_tasks = tuple(
            getattr(self, "_streamlines_temporal_point_probe_tasks", ())
        )
        if probe_tasks:
            await asyncio.gather(*probe_tasks, return_exceptions=True)
        if self._streamlines_constant_topology_active_session() is None:
            return
        ticks = tuple(scheduler.ticks[tick_offset:])
        proofs = self.streamlines_state_replacement_proofs()[proof_offset:]
        composed = self._probe_observed_streamlines_samples_in_kit(
            metadata,
            ticks,
            sample_indices=_POINT_PROBE_SAMPLE_INDICES,
        )
        point_evidence = evaluate_streamlines_temporal_point_matches(
            getattr(self, "_streamlines_temporal_point_matches", {}).values()
        )
        renderer_integrity = (
            bool(composed)
            and all(
                probe.passed
                and probe.point_count == 122880
                and probe.required_point_count == 122880
                and probe.speed_count == 122880
                for probe in composed
            )
            and point_evidence.passed
        )
        evidence = evaluate_streamlines_cache_loop(
            profile_id=StreamlinesProfileId.VOLUME_COVERAGE,
            workload="Nominal",
            sample_count=metadata.sample_count,
            sample_interval_seconds=metadata.sample_interval_seconds,
            scheduler_tasks=self._active_streamlines_playback_task_count(),
            ticks=ticks,
            replacement_proofs=proofs,
            composed_sample_probes=composed,
            renderer_integrity_passed=renderer_integrity,
            duplicate_presentation_prims=self._streamlines_duplicate_prim_count(),
        )
        if not evidence.passed:
            mismatch = next(
                (probe for probe in composed if not probe.passed),
                None,
            )
            detail = (
                "unavailable"
                if mismatch is None
                else (
                    f"sample_index={mismatch.sample_index}; "
                    f"point_count={mismatch.point_count}; "
                    f"required_point_count={mismatch.required_point_count}; "
                    f"speed_count={mismatch.speed_count}"
                )
            )
            self._streamlines_constant_topology_fail(
                "Renderer/topology loop proof failed: "
                f"wrap={evidence.wrap_transition}; counts={detail}; "
                "temporal_points="
                f"{self._format_temporal_point_evidence(point_evidence)}."
            )
            return
        session = self._streamlines_constant_topology_active_session()
        if session is None or not session.record("loop"):
            self._streamlines_constant_topology_fail(
                "Prototype loop milestone could not be recorded."
            )
            return
        self._streamlines_constant_topology_log(
            "COMPLETE",
            "sample_advanced=True; wraparound_79_to_0=True; scheduler_tasks=1; "
            "points=122880; required_points=122880; speed=122880; "
            "topology_consistent=True; temporal_point_signatures_distinct=True; "
            "persisted_composed_signatures_match=True; cache_build=0; "
            "cache_rebuild=0; "
            "KitCAE=0; VTI_presentation_import=0; runtime_recompute=0.",
        )
        if session.complete():
            self._streamlines_cache_playback_sanity_emit(
                format_manual_acceptance_test_complete(
                    "Constant-topology Volume Coverage / Nominal playback passed.\n"
                    "RTX/Hydra variable-topology defect is resolved for the prototype."
                )
            )
        if status_callback:
            status_callback("Constant-topology playback prototype passed.")

    async def _observe_explicit_presentation_loop(self, status_callback) -> None:
        """Prove one full explicit-property loop, then await visual approval."""

        scheduler = getattr(self, "_streamlines_cached_playback_scheduler", None)
        metadata = getattr(self, "_streamlines_loaded_cache_metadata", None)
        airflow = self._airflow_state.committed
        profile = self.streamlines_profile_preference_snapshot()
        if not (
            metadata
            and airflow
            and metadata.profile_id == StreamlinesProfileId.VOLUME_COVERAGE.value
            and metadata.workload == "Nominal"
            and metadata.topology_consistent
            and airflow.workload_mode == "Nominal"
            and profile.committed_profile is StreamlinesProfileId.VOLUME_COVERAGE
            and scheduler is not None
            and self._active_streamlines_playback_task_count() == 1
            and not self.streamlines_controls_timeline_in_kit()
        ):
            self._streamlines_explicit_presentation_fail(
                "Volume Coverage / Nominal explicit presentation is not active once."
            )
            return

        self._streamlines_explicit_hash_matches = {}
        self._streamlines_explicit_hash_pending = set()
        tick_offset = len(scheduler.ticks)
        receipt_offset = len(self.streamlines_cached_state_apply_receipts())
        performance_samples = []
        self._streamlines_explicit_presentation_log(
            "PROGRESS",
            "Stable presentation Geometry created and cache Source attached.",
        )
        self._streamlines_explicit_presentation_log(
            "PROGRESS",
            "Explicit cached states are changing.",
        )
        started = time.monotonic()
        duration = metadata.sample_count * metadata.sample_interval_seconds + 0.4
        next_wait = 5.0
        next_performance_sample = 0.0
        while time.monotonic() - started < duration:
            await asyncio.sleep(0.1)
            if self._streamlines_explicit_presentation_active_session() is None:
                return
            if scheduler is not getattr(
                self, "_streamlines_cached_playback_scheduler", None
            ):
                self._streamlines_explicit_presentation_fail(
                    "Explicit presentation scheduler was replaced during observation."
                )
                return
            elapsed = time.monotonic() - started
            if elapsed >= next_performance_sample:
                performance_samples.append(capture_viewport_performance_sample())
                next_performance_sample += 0.5
            if elapsed >= next_wait:
                self._streamlines_explicit_presentation_log(
                    "WAITING",
                    f"Observe one complete 16 s loop; elapsed={int(elapsed)} s.",
                )
                next_wait += 5.0

        tasks = tuple(getattr(self, "_streamlines_explicit_hash_tasks", ()))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if self._streamlines_explicit_presentation_active_session() is None:
            return
        ticks = tuple(scheduler.ticks[tick_offset:])
        receipts = self.streamlines_cached_state_apply_receipts()[receipt_offset:]
        hashes = getattr(self, "_streamlines_explicit_hash_matches", {})
        observed_indices = tuple(sorted(hashes))
        distinct_source = {item[0].sha256 for item in hashes.values()}
        distinct_visible = {item[1].sha256 for item in hashes.values()}
        hashes_pass = (
            all(index in hashes for index in _POINT_PROBE_SAMPLE_INDICES)
            and len(distinct_source) >= 2
            and len(distinct_visible) >= 2
            and all(
                source.sha256 == visible.sha256
                and source.point_count == 122880
                and visible.point_count == 122880
                and speed_count == 122880
                for source, visible, speed_count, _source_time in hashes.values()
            )
        )
        report = scheduler.report()
        wrap = resolved_cache_state_wrap_transition(ticks)
        apply_values = sorted(receipt.apply_ms for receipt in receipts)
        if not (
            hashes_pass
            and wrap == (79, 0)
            and report.missed_deadlines == 0
            and report.backlog_count == 0
            and self._active_streamlines_playback_task_count() == 1
            and apply_values
        ):
            self._streamlines_explicit_presentation_fail(
                "Explicit presentation technical proof failed: "
                f"hash_samples={observed_indices}; distinct_visible="
                f"{len(distinct_visible)}; wrap={wrap}; "
                f"missed_deadlines={report.missed_deadlines}; "
                f"backlog_count={report.backlog_count}."
            )
            return

        fps_values = [sample.fps for sample in performance_samples if sample.fps]
        final_performance = performance_samples[-1] if performance_samples else None
        p95_index = min(len(apply_values) - 1, math.ceil(len(apply_values) * 0.95) - 1)
        hash_detail = "\n".join(
            f"sample_index={index}; source_time={hashes[index][3]:.3f}; "
            f"source_points_hash={hashes[index][0].sha256}; "
            f"visible_presentation_points_hash={hashes[index][1].sha256}; "
            f"hashes_match=True; visible_points={hashes[index][1].point_count}; "
            f"visible_speed={hashes[index][2]}"
            for index in _POINT_PROBE_SAMPLE_INDICES
        )
        session = self._streamlines_explicit_presentation_active_session()
        if session is None or not session.record("technical"):
            self._streamlines_explicit_presentation_fail(
                "Explicit presentation technical milestone could not be recorded."
            )
            return
        self._streamlines_explicit_presentation_log(
            "COMPLETE",
            "technical_evidence=PASS; sample_advanced=True; wraparound_79_to_0=True; "
            "scheduler_tasks=1; timeline_control=False; "
            f"representative_samples:\n{hash_detail}\n"
            f"state_apply_ms_median={median(apply_values):.3f}; "
            f"state_apply_ms_p95={apply_values[p95_index]:.3f}; "
            f"state_apply_ms_max={max(apply_values):.3f}; "
            f"missed_deadlines={report.missed_deadlines}; "
            f"backlog_count={report.backlog_count}; "
            f"viewport_fps_average={self._optional_average(fps_values)}; "
            f"viewport_fps_minimum={self._optional_minimum(fps_values)}; "
            "gpu_used_gib="
            f"{self._optional_metric(final_performance, 'gpu_memory_used_gib')}; "
            "process_used_gib="
            f"{self._optional_metric(final_performance, 'process_memory_used_gib')}",
            next_action=(
                "Inspect the viewport and confirm visible temporal change, no 5 Hz "
                "flicker, no ghost/stale curves, no origin spikes, no accumulation, "
                'and a sane 79 -> 0 wrap; then press "Confirm Visible Playback".'
            ),
        )
        if status_callback:
            status_callback(
                "Explicit playback technical proof passed; "
                "visual confirmation required."
            )

    def _record_streamlines_explicit_state_application_in_kit(
        self, sample, state, visible_prim, receipt
    ) -> None:
        """Hash representative source/visible arrays only during the prototype gate."""

        if self._streamlines_explicit_presentation_active_session() is None:
            return
        sample_index = sample.sample_index
        matches = self._streamlines_explicit_hash_matches
        pending = self._streamlines_explicit_hash_pending
        if (
            sample_index not in _POINT_PROBE_SAMPLE_INDICES
            or sample_index in matches
            or sample_index in pending
        ):
            return
        source_points = tuple(state.points)
        visible_points = tuple(visible_prim.GetAttribute("points").Get() or ())
        visible_speed = tuple(
            visible_prim.GetAttribute(SPEED_PRIMVAR_ATTRIBUTE).Get() or ()
        )
        pending.add(sample_index)

        async def complete_hashes() -> None:
            try:
                source_hash, visible_hash = await asyncio.gather(
                    asyncio.to_thread(streamlines_point_array_signature, source_points),
                    asyncio.to_thread(
                        streamlines_point_array_signature, visible_points
                    ),
                )
                if self._streamlines_explicit_presentation_active_session() is None:
                    return
                matches[sample_index] = (
                    source_hash,
                    visible_hash,
                    len(visible_speed),
                    receipt.source_time_seconds,
                )
                if source_hash.sha256 != visible_hash.sha256:
                    self._streamlines_explicit_presentation_fail(
                        "Visible points differ from selected Source: "
                        f"sample_index={sample_index}; source={source_hash.sha256}; "
                        f"visible={visible_hash.sha256}."
                    )
            finally:
                pending.discard(sample_index)

        task = asyncio.ensure_future(complete_hashes())
        self._streamlines_explicit_hash_tasks.add(task)
        task.add_done_callback(self._streamlines_explicit_hash_tasks.discard)

    def confirm_streamlines_explicit_presentation_playback(self) -> bool:
        """Accept the manual viewport proof only after technical COMPLETE."""

        session = self._streamlines_explicit_presentation_active_session()
        if session is None or session.expected_milestone != "visual":
            return False
        if not session.record("visual") or not session.complete():
            self._streamlines_explicit_presentation_fail(
                "Visual playback confirmation could not be recorded."
            )
            return False
        self._streamlines_cache_playback_sanity_emit(
            format_manual_acceptance_test_complete(
                "Phase 4.4B explicit Streamlines presentation playback passed.\n"
                "Visible geometry advances at 200 ms without timeline-driven flicker.\n"
                "No further prototype playback action required."
            )
        )
        return True

    def reject_streamlines_explicit_presentation_playback(self) -> bool:
        """Record manual static/flickering evidence as terminal prototype failure."""

        if self._streamlines_explicit_presentation_active_session() is None:
            return False
        self._streamlines_explicit_presentation_fail(
            "Manual viewport inspection reported static geometry or flicker."
        )
        return True

    def _streamlines_explicit_presentation_active_session(self):
        session = getattr(self, "_streamlines_explicit_presentation_session", None)
        if session is None or session.failed or session.terminal_emitted:
            return None
        return session

    def _streamlines_explicit_presentation_fail(self, reason: str) -> None:
        session = self._streamlines_explicit_presentation_active_session()
        if session is None:
            return
        session.mark_failed()
        self._streamlines_explicit_presentation_log("FAIL", reason)

    def _streamlines_explicit_presentation_log(
        self, event: str, status: str, next_action: str | None = None
    ) -> None:
        self._streamlines_cache_playback_sanity_emit(
            format_manual_acceptance_event(
                area=_EXPLICIT_PRESENTATION_AREA,
                event=event,
                status=status,
                next_action=next_action,
            )
        )

    @staticmethod
    def _optional_average(values) -> str:
        return "unavailable" if not values else f"{sum(values) / len(values):.2f}"

    @staticmethod
    def _optional_minimum(values) -> str:
        return "unavailable" if not values else f"{min(values):.2f}"

    @staticmethod
    def _optional_metric(sample, attribute: str) -> str:
        value = getattr(sample, attribute, None) if sample is not None else None
        return "unavailable" if value is None else f"{value:.3f}"

    async def _prepare_streamlines_temporal_point_probe(self, metadata) -> None:
        """Load five persisted hashes off-thread before observing selections."""

        paths = getattr(self, "_streamlines_loaded_cache_paths", None)
        if paths is None:
            raise RuntimeError("Loaded Streamlines cache paths are unavailable.")
        probes = await asyncio.to_thread(
            probe_persisted_streamlines_point_signatures,
            paths.geometry_path,
            metadata,
            sample_indices=_POINT_PROBE_SAMPLE_INDICES,
        )
        if any(probe.points.point_count != 122_880 for probe in probes):
            raise ValueError("Persisted point count differs from fixed topology.")
        if len({probe.points.sha256 for probe in probes}) < 2:
            raise ValueError("Persisted temporal point geometry is static.")
        for task in getattr(self, "_streamlines_temporal_point_probe_tasks", ()):
            if not task.done():
                task.cancel()
        self._streamlines_temporal_point_probe_generation += 1
        self._streamlines_temporal_point_probe_tasks = set()
        self._streamlines_temporal_point_probe_pending_indices = set()
        self._streamlines_temporal_point_persisted = {
            probe.sample_index: probe for probe in probes
        }
        self._streamlines_temporal_point_matches = {}

    def _record_streamlines_temporal_point_selection_in_kit(
        self,
        resolution,
    ) -> None:
        """Capture composed points after Kit applied one selected timeline state."""

        if self._streamlines_constant_topology_active_session() is None:
            return
        sample_index = resolution.sample.sample_index
        persisted = getattr(
            self,
            "_streamlines_temporal_point_persisted",
            {},
        ).get(sample_index)
        pending = self._streamlines_temporal_point_probe_pending_indices
        if (
            persisted is None
            or sample_index in pending
            or sample_index in self._streamlines_temporal_point_matches
        ):
            return

        import omni.usd
        from pxr import Usd

        stage = omni.usd.get_context().get_stage()
        prim = stage.GetPrimAtPath(CACHE_PLAYBACK_CURVES_PATH) if stage else None
        if not prim or not prim.IsValid():
            self._streamlines_constant_topology_fail(
                "Composed Streamlines geometry disappeared during point proof."
            )
            return
        timeline = omni.timeline.get_timeline_interface()
        timeline_seconds = float(timeline.get_current_time())
        stage_time_code = timeline_seconds * float(stage.GetTimeCodesPerSecond())
        points = tuple(
            prim.GetAttribute("points").Get(Usd.TimeCode(stage_time_code)) or ()
        )
        generation = self._streamlines_temporal_point_probe_generation
        pending.add(sample_index)

        async def finish_probe() -> None:
            try:
                signature = await asyncio.to_thread(
                    streamlines_point_array_signature,
                    points,
                )
                if generation != self._streamlines_temporal_point_probe_generation:
                    return
                match = StreamlinesTemporalPointMatch(
                    sample_index=sample_index,
                    requested_time_code=persisted.time_code,
                    selected_timeline_time_seconds=timeline_seconds,
                    composed_usd_time_code=stage_time_code,
                    persisted=persisted.points,
                    composed=signature,
                )
                self._streamlines_temporal_point_matches[sample_index] = match
                if not match.signatures_match:
                    self._streamlines_constant_topology_fail(
                        "Composed points differ from persisted points: "
                        f"sample_index={sample_index}; "
                        f"persisted={persisted.points.sha256}; "
                        f"composed={signature.sha256}."
                    )
            except (RuntimeError, TypeError, ValueError) as error:
                self._streamlines_constant_topology_fail(
                    f"Composed temporal-point signature failed: {error}"
                )
            finally:
                pending.discard(sample_index)

        task = asyncio.ensure_future(finish_probe())
        self._streamlines_temporal_point_probe_tasks.add(task)
        task.add_done_callback(self._streamlines_temporal_point_probe_tasks.discard)

    @staticmethod
    def _format_temporal_point_evidence(
        evidence: StreamlinesTemporalPointEvidence,
    ) -> str:
        return (
            ",".join(
                f"{match.sample_index}:"
                f"{match.persisted.sha256[:12]}/"
                f"{match.composed.sha256[:12]}/"
                f"match={match.signatures_match}"
                for match in evidence.matches
            )
            or "unavailable"
        )

    def _probe_observed_streamlines_samples_in_kit(
        self,
        metadata,
        ticks,
        *,
        sample_indices=None,
    ):
        """Read every distinct observed state at its exact composed time code."""

        import omni.timeline
        import omni.usd
        from pxr import Usd

        stage = omni.usd.get_context().get_stage()
        prim = stage.GetPrimAtPath(CACHE_PLAYBACK_CURVES_PATH) if stage else None
        if not prim or not prim.IsValid():
            raise RuntimeError("Composed Streamlines BasisCurves is unavailable.")
        points_attr = prim.GetAttribute("points")
        counts_attr = prim.GetAttribute("curveVertexCounts")
        speed_attr = prim.GetAttribute(SPEED_PRIMVAR_ATTRIBUTE)
        stage_time_codes_per_second = float(stage.GetTimeCodesPerSecond())
        states = {state.sample_index: state for state in metadata.states}
        probes = []
        observed = set()
        requested_indices = None if sample_indices is None else set(sample_indices)
        for tick in ticks:
            sample_index = tick.resolution.sample.sample_index
            if (
                sample_index in observed
                or requested_indices is not None
                and sample_index not in requested_indices
            ):
                continue
            observed.add(sample_index)
            state = states[sample_index]
            timeline_time = state.source_time_seconds
            resolved_time_code = timeline_time * stage_time_codes_per_second
            time_code = Usd.TimeCode(resolved_time_code)
            probes.append(
                probe_streamlines_sample_attributes(
                    sample_index=sample_index,
                    requested_time_code=state.time_code,
                    timeline_current_time_seconds=timeline_time,
                    resolved_usd_time_code=resolved_time_code,
                    usd_time_code=time_code,
                    points_attr=points_attr,
                    curve_vertex_counts_attr=counts_attr,
                    speed_attr=speed_attr,
                )
            )
        return tuple(probes)

    def _complete_streamlines_normal_exit(self) -> None:
        session = self._streamlines_cache_playback_sanity_active_session()
        profile = self.streamlines_profile_preference_snapshot()
        clean = (
            session is not None
            and session.expected_milestone == "normal"
            and self.visualization_snapshot().committed is VisualizationMode.NORMAL
            and self.visualization_snapshot().pending is None
            and self._airflow_state.snapshot.pending is None
            and profile.pending_profile is None
            and self._active_streamlines_playback_task_count() == 0
            and not self.streamlines_controls_timeline_in_kit()
            and not self.streamlines_cached_presentation_is_prepared_in_kit()
            and self._streamlines_cache_playback_preconditions_pass()
        )
        if not clean:
            self._streamlines_cache_playback_sanity_fail(
                "Normal exit retained Streamlines presentation, scheduler, "
                "timeline, or pending state."
            )
            return
        self._streamlines_cache_playback_sanity_record(
            "normal",
            "Streamlines visible=False; scheduler_tasks=0; pending_profile=None; "
            "pending_workload=None; pending_visualization=None; "
            "presentation_residue=0.",
        )
        if session and session.complete():
            self._streamlines_cache_playback_sanity_emit(
                format_manual_acceptance_test_complete(
                    "Phase 4.4B final Streamlines caches passed cached playback "
                    "sanity.\n8/8 caches remain VALID and production playback "
                    "requires no recompute."
                )
            )

    def _streamlines_cache_playback_sanity_record(self, milestone, status) -> None:
        session = self._streamlines_cache_playback_sanity_active_session()
        if session is None or not session.record(milestone):
            self._streamlines_cache_playback_sanity_fail(
                f"Guided milestone could not be recorded: {milestone}."
            )
            return
        actions = {
            "global_nominal": (
                "Inspect playback integrity, then select "
                '"Global Flow Path" in "Profile" '
                'while keeping Workload="Nominal".'
            ),
            "global_surge": 'Select "Surge" in "Workload".',
            "volume_surge": (
                'Select "Volume Coverage" in "Profile" while keeping Workload="Surge".'
            ),
            "normal": 'Select "Normal" in "Visualization".',
        }
        self._streamlines_cache_playback_sanity_log(
            "COMPLETE", status, next_action=actions.get(session.expected_milestone)
        )

    def _streamlines_cache_playback_sanity_active_session(self):
        session = getattr(self, "_streamlines_cache_playback_sanity_session", None)
        if session is None or session.failed or session.terminal_emitted:
            return None
        return session

    def _streamlines_constant_topology_active_session(self):
        session = getattr(self, "_streamlines_constant_topology_session", None)
        if session is None or session.failed or session.terminal_emitted:
            return None
        return session

    def _streamlines_constant_topology_fail(self, reason: str) -> None:
        session = self._streamlines_constant_topology_active_session()
        if session is None:
            return
        session.mark_failed()
        self._streamlines_constant_topology_log("FAIL", reason)

    def _streamlines_constant_topology_log(
        self,
        event: str,
        status: str,
        next_action: str | None = None,
    ) -> None:
        self._streamlines_cache_playback_sanity_emit(
            format_manual_acceptance_event(
                area=_CONSTANT_TOPOLOGY_AREA,
                event=event,
                status=status,
                next_action=next_action,
            )
        )

    def _streamlines_cache_playback_sanity_fail(self, reason: str) -> None:
        session = self._streamlines_cache_playback_sanity_active_session()
        if session is None:
            return
        session.mark_failed()
        self._streamlines_cache_playback_sanity_log("FAIL", reason)

    def _streamlines_duplicate_prim_count(self) -> int:
        try:
            import omni.usd
        except ImportError:
            return 0
        stage = omni.usd.get_context().get_stage()
        return streamlines_duplicate_runtime_prim_count(stage) if stage else 0

    def _streamlines_cache_playback_sanity_log(self, event, status, next_action=None):
        self._streamlines_cache_playback_sanity_emit(
            format_manual_acceptance_event(
                area=_AREA, event=event, status=status, next_action=next_action
            )
        )

    def _streamlines_cache_playback_sanity_emit(self, message: str) -> None:
        carb = self._streamlines_carb_logger()
        if carb:
            carb.log_warn(with_dtrs_yerevan_timestamp(message))
