"""Transactional cached switching between frozen Streamlines profiles."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Callable

from digital_twin_runtime_suite.app.streamlines.profile import StreamlinesProfileId
from digital_twin_runtime_suite.app.visualization_mode.model import VisualizationMode

StatusCallback = Callable[[str], None]


@dataclass(frozen=True)
class StreamlinesProfileTransitionResult:
    success: bool
    message: str
    requested_profile: StreamlinesProfileId
    committed_profile: StreamlinesProfileId | None
    rolled_back: bool = False


@dataclass(frozen=True)
class StreamlinesProfileTransitionEvidence:
    """Published proof that a cached profile swap preserved workload and phase."""

    previous_profile: StreamlinesProfileId
    committed_profile: StreamlinesProfileId
    workload: str
    dataset_identity: str
    requested_normalized_phase_seconds: float
    selected_normalized_phase_seconds: float
    normalized_phase_preserved: bool
    sample_advanced: bool
    scheduler_tasks: int
    reference_swap_passed: bool
    session_sublayers_unchanged: bool
    root_sublayers_unchanged: bool
    server_scene_composition_mutations: int


class StreamlinesProfileTransitionMixin:
    """Switch only persisted profile cache references under the shared lock."""

    async def request_streamlines_profile_transition_in_kit(
        self,
        profile_id: StreamlinesProfileId,
        status_callback: StatusCallback | None = None,
    ) -> StreamlinesProfileTransitionResult:
        profile_id = StreamlinesProfileId(profile_id)
        if self.visualization_snapshot().committed is not VisualizationMode.STREAMLINES:
            self._streamlines_profile_preference.set_preference(profile_id)
            return self._streamlines_profile_transition_result(
                True,
                profile_id,
                "Streamlines profile preference updated; presentation is inactive.",
            )
        transition = self._streamlines_profile_preference.begin(profile_id)
        if transition is None:
            return self._streamlines_profile_transition_result(
                True,
                profile_id,
                "Streamlines already presents the requested profile.",
            )
        lock = getattr(self, "_visualization_mode_lock", None)
        if lock is None:
            lock = asyncio.Lock()
            self._visualization_mode_lock = lock
        async with lock:
            return await self._run_streamlines_profile_transition_in_kit(
                transition,
                status_callback=status_callback,
            )

    def streamlines_profile_transition_evidence(
        self,
    ) -> StreamlinesProfileTransitionEvidence | None:
        """Return the latest successfully committed cached profile proof."""

        return getattr(self, "_streamlines_last_profile_transition_evidence", None)

    async def _run_streamlines_profile_transition_in_kit(
        self,
        transition,
        *,
        status_callback: StatusCallback | None,
    ) -> StreamlinesProfileTransitionResult:
        committed_airflow = self._airflow_state.committed
        if committed_airflow is None:
            self._streamlines_profile_preference.fail(transition)
            return self._streamlines_profile_transition_result(
                False,
                transition.target_profile,
                "Active Streamlines has no committed workload.",
            )
        binding = committed_airflow.binding
        dataset = committed_airflow.dataset
        previous = transition.previous_profile
        if previous is None:
            loaded = getattr(self, "_streamlines_loaded_cache_metadata", None)
            previous = StreamlinesProfileId(loaded.profile_id) if loaded else None
        candidate_preparation_started = False
        try:
            if status_callback:
                status_callback("Streamlines profile: validating target cache.")
            receipt = await self.ensure_streamlines_cache_validation_in_background(
                binding,
                dataset,
                profile_id=transition.target_profile,
            )
            if receipt.inspection.classification != "VALID":
                raise RuntimeError(
                    f"Target profile cache is {receipt.inspection.classification}."
                )
            if not self._streamlines_profile_preference.is_current(transition):
                raise RuntimeError("Streamlines profile request was superseded.")
            phase = self._airflow_state.resolve_phase(dataset)
            candidate_preparation_started = True
            resolution = await self.prepare_streamlines_cached_target_in_kit(
                binding,
                dataset,
                phase.phase_seconds,
                expected_sample_index=phase.sample.sample_index,
                expected_source_vti=phase.sample.source_vti,
                validated_receipt=receipt,
                status_callback=status_callback,
                cancellation_requested=lambda: not (
                    self._streamlines_profile_preference.is_current(transition)
                ),
            )
            await self.start_streamlines_cached_playback_in_kit()
            proof = await self.await_streamlines_cached_playback_advancement_in_kit(
                resolution.sample,
                cancellation_requested=lambda: not (
                    self._streamlines_profile_preference.is_current(transition)
                ),
            )
            if (
                not proof.sample_advanced
                or self._active_streamlines_playback_task_count() != 1
                or not self.set_streamlines_cached_presentation_visible_in_kit(True)
            ):
                raise RuntimeError(
                    "Target profile cache failed playback liveness proof."
                )
            composition = self.streamlines_presentation_reference_snapshot()
            if composition is None or not composition.reference_swap_passed:
                raise RuntimeError("Target profile cache reference swap was not local.")
            self.apply_streamlines_presentation_in_kit()
            if not self._streamlines_profile_preference.commit(transition):
                raise RuntimeError("Streamlines profile commit was superseded.")
        except Exception as error:
            if not candidate_preparation_started:
                self._streamlines_profile_preference.fail(transition)
                return self._streamlines_profile_transition_result(
                    False,
                    transition.target_profile,
                    f"Streamlines profile transition failed: {error}",
                )
            rolled_back = await self._rollback_streamlines_profile_in_kit(
                transition,
                previous,
                binding,
                dataset,
            )
            return self._streamlines_profile_transition_result(
                False,
                transition.target_profile,
                f"Streamlines profile transition failed: {error}",
                rolled_back=rolled_back,
            )
        self._streamlines_last_profile_transition_evidence = (
            StreamlinesProfileTransitionEvidence(
                previous_profile=previous,
                committed_profile=transition.target_profile,
                workload=binding.workload_mode,
                dataset_identity=binding.dataset_identity,
                requested_normalized_phase_seconds=(phase.normalized_phase_seconds),
                selected_normalized_phase_seconds=(resolution.normalized_phase_seconds),
                normalized_phase_preserved=(
                    resolution.sample.sample_index == phase.sample.sample_index
                ),
                sample_advanced=proof.sample_advanced,
                scheduler_tasks=proof.scheduler_tasks,
                reference_swap_passed=composition.reference_swap_passed,
                session_sublayers_unchanged=(composition.session_sublayers_unchanged),
                root_sublayers_unchanged=composition.root_sublayers_unchanged,
                server_scene_composition_mutations=(
                    composition.server_scene_composition_mutations
                ),
            )
        )
        return self._streamlines_profile_transition_result(
            True,
            transition.target_profile,
            f"Streamlines profile committed: {transition.target_profile.value}; "
            "scheduler_tasks=1; cache_build=0; KitCAE=0; VTI_import=0.",
        )

    async def _rollback_streamlines_profile_in_kit(
        self,
        transition,
        previous,
        binding,
        dataset,
    ) -> bool:
        self._streamlines_profile_preference.fail(transition)
        if previous is None:
            return False
        try:
            receipt = await self.ensure_streamlines_cache_validation_in_background(
                binding,
                dataset,
                profile_id=previous,
            )
            phase = self._airflow_state.resolve_phase(dataset)
            resolution = await self.prepare_streamlines_cached_target_in_kit(
                binding,
                dataset,
                phase.phase_seconds,
                validated_receipt=receipt,
            )
            await self.start_streamlines_cached_playback_in_kit()
            proof = await self.await_streamlines_cached_playback_advancement_in_kit(
                resolution.sample
            )
            if not proof.sample_advanced:
                return False
            self.set_streamlines_cached_presentation_visible_in_kit(True)
            self.apply_streamlines_presentation_in_kit()
            self._streamlines_profile_preference.mark_loaded(previous)
            return True
        except Exception:
            return False

    def _streamlines_profile_transition_result(
        self,
        success: bool,
        requested: StreamlinesProfileId,
        message: str,
        *,
        rolled_back: bool = False,
    ) -> StreamlinesProfileTransitionResult:
        return StreamlinesProfileTransitionResult(
            success=success,
            message=message,
            requested_profile=requested,
            committed_profile=(
                self._streamlines_profile_preference.snapshot.committed_profile
            ),
            rolled_back=rolled_back,
        )
