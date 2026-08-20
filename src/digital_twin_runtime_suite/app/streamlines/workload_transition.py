"""Transactional workload switching for an active Streamlines presentation."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Callable

from digital_twin_runtime_suite.app.streamlines.playback import (
    CachedPlaybackContract,
)
from digital_twin_runtime_suite.app.visualization_mode.model import (
    VisualizationMode,
)

StatusCallback = Callable[[str], None]


@dataclass(frozen=True)
class StreamlinesWorkloadTransitionEvidence:
    """Verified target facts published only after a successful shared commit."""

    transition_id: str
    requested_workload: str
    previous_workload: str
    target_dataset: str
    target_cache: str
    selected_sample_identity: str
    initial_sample_identity: str
    advanced_sample_identity: str | None
    committed_workload: str
    scheduler_tasks: int
    streamlines_visible: bool
    sample_advanced: bool
    flow_attach_calls: int
    requested_normalized_phase_seconds: float
    selected_normalized_phase_seconds: float
    normalized_phase_preserved: bool


@dataclass(frozen=True)
class StreamlinesWorkloadTransitionResult:
    """Terminal result for one product workload request in Streamlines mode."""

    success: bool
    message: str
    requested_workload: str
    committed_workload: str | None
    transition_id: str | None = None
    rolled_back: bool = False
    unreconciled: bool = False


class StreamlinesWorkloadTransitionMixin:
    """Own target proof, shared commit, rollback, and supersession."""

    def reset_streamlines_workload_transition_state(self) -> None:
        """Clear session-only evidence at controller lifecycle boundaries."""

        self._streamlines_last_workload_transition_evidence = None

    def streamlines_workload_transition_evidence(
        self,
    ) -> StreamlinesWorkloadTransitionEvidence | None:
        """Return the latest successfully committed workload proof."""

        return self._streamlines_last_workload_transition_evidence

    async def request_streamlines_workload_transition_in_kit(
        self,
        workload_mode: str,
        status_callback: StatusCallback | None = None,
    ) -> StreamlinesWorkloadTransitionResult:
        """Switch one active persisted cache before committing shared airflow."""

        if not self._streamlines_workload_mode_owned():
            return self._streamlines_workload_result(
                False,
                workload_mode,
                "Streamlines does not own the primary presentation.",
            )
        try:
            target_binding = self._airflow_state.resolve_binding(workload_mode)
            target = self._airflow_state.resolve_target(target_binding)
        except Exception as error:
            return self._streamlines_workload_result(
                False,
                workload_mode,
                f"Streamlines workload target could not be resolved: {error}",
            )
        if self._loaded_streamlines_target_is_healthy(target_binding):
            return self._streamlines_workload_result(
                True,
                workload_mode,
                "Streamlines already presents the requested workload.",
            )
        transition = self._airflow_state.begin(target)
        if transition is None:
            return self._streamlines_workload_result(
                False,
                workload_mode,
                "Committed workload matches, but its Streamlines presentation "
                "is not healthy.",
            )
        lock = getattr(self, "_visualization_mode_lock", None)
        if lock is None:
            lock = asyncio.Lock()
            self._visualization_mode_lock = lock
        async with lock:
            return await self._run_streamlines_workload_transition_in_kit(
                transition,
                status_callback=status_callback,
            )

    async def _run_streamlines_workload_transition_in_kit(
        self,
        transition,
        *,
        status_callback: StatusCallback | None,
    ) -> StreamlinesWorkloadTransitionResult:
        """Mutate the sole cache presentation only while both owners agree."""

        target = transition.target
        target_binding = target.binding
        requested = target.workload_mode
        previous = self._airflow_state.committed
        if previous is None:
            return self._finish_streamlines_workload_failure(
                transition,
                "Active Streamlines has no committed airflow workload.",
                failure_stage="precondition",
                rolled_back=False,
            )
        if not self._streamlines_workload_transition_current(transition):
            if self._airflow_state.is_current(
                transition.transition_id,
                transition.target.binding,
            ):
                return self._finish_streamlines_workload_failure(
                    transition,
                    "Visualization mode superseded Streamlines before mutation.",
                    failure_stage="visualization_supersession",
                    rolled_back=False,
                )
            return self._streamlines_workload_result(
                False,
                requested,
                "Streamlines workload request was superseded before mutation.",
                transition_id=transition.transition_id,
            )
        self._report_streamlines_workload_progress(
            status_callback,
            f"Streamlines workload: validating {requested} cache receipt.",
        )
        try:
            receipt = await self.ensure_streamlines_cache_validation_in_background(
                target_binding,
                target.dataset,
            )
        except Exception as error:
            return self._finish_streamlines_workload_failure(
                transition,
                f"Target cache validation failed: {error}",
                failure_stage="cache_validation",
                rolled_back=False,
            )
        if not self._streamlines_workload_transition_current(transition):
            if self._airflow_state.is_current(
                transition.transition_id,
                transition.target.binding,
            ):
                return self._finish_streamlines_workload_failure(
                    transition,
                    "Visualization mode superseded Streamlines during validation.",
                    failure_stage="visualization_supersession",
                    rolled_back=False,
                )
            return self._streamlines_workload_result(
                False,
                requested,
                "Streamlines workload request was superseded during validation.",
                transition_id=transition.transition_id,
            )
        classification = receipt.inspection.classification
        if classification != "VALID":
            return self._finish_streamlines_workload_failure(
                transition,
                "Target Streamlines cache is "
                f"{classification}: {receipt.inspection.message}",
                failure_stage="cache_readiness",
                rolled_back=False,
            )
        try:
            active_resolution, target_resolution = (
                self._airflow_state.resolve_transition_phase_pair(
                    previous.dataset,
                    target.dataset,
                )
            )
        except Exception as error:
            return self._finish_streamlines_workload_failure(
                transition,
                f"Shared phase resolution failed: {error}",
                failure_stage="temporal_resolution",
                rolled_back=False,
            )
        self._report_streamlines_workload_progress(
            status_callback,
            "Streamlines workload: shared phase "
            f"{target_resolution.phase_seconds:.3f} s; previous sample="
            f"{active_resolution.sample.sample_index}; target sample="
            f"{target_resolution.sample.sample_index}.",
        )
        flow_attach_calls_before = self.visualization_flow_attach_call_count()
        mutated = False
        try:
            self._report_streamlines_workload_progress(
                status_callback,
                "Streamlines workload: preparing target persisted cache.",
            )
            mutated = True
            resolution = await self.prepare_streamlines_cached_target_in_kit(
                target_binding,
                target.dataset,
                target_resolution.phase_seconds,
                expected_sample_index=target_resolution.sample.sample_index,
                expected_source_vti=target_resolution.sample.source_vti,
                validated_receipt=receipt,
                status_callback=status_callback,
                cancellation_requested=lambda: not (
                    self._streamlines_workload_transition_current(transition)
                ),
            )
            self._require_streamlines_workload_target(transition)
            contract = self._streamlines_cache_playback_contract
            if not isinstance(contract, CachedPlaybackContract):
                raise RuntimeError("Target cache did not publish a playback contract.")
            self._report_streamlines_workload_progress(
                status_callback,
                "Streamlines workload: proving target cached playback.",
            )
            await self.start_streamlines_cached_contract_playback_in_kit(
                contract,
                authorization=lambda: self._streamlines_workload_target_authorized(
                    transition.transition_id,
                    target_binding,
                ),
                status_callback=status_callback,
            )
            proof = await self.await_streamlines_cached_playback_advancement_in_kit(
                resolution.sample,
                cancellation_requested=lambda: not (
                    self._streamlines_workload_transition_current(transition)
                ),
            )
            self._require_streamlines_workload_target(transition)
            if not proof.sample_advanced:
                raise RuntimeError(
                    "Target Streamlines cache did not advance to a later real sample."
                )
            if not self.set_streamlines_cached_presentation_visible_in_kit(True):
                raise RuntimeError(
                    "Target Streamlines presentation could not be shown."
                )
            self._verify_streamlines_workload_presentation(target_binding, proof)
            flow_attach_calls = (
                self.visualization_flow_attach_call_count() - flow_attach_calls_before
            )
            if flow_attach_calls:
                raise RuntimeError(
                    "Streamlines workload switch unexpectedly attached Flow."
                )
            if not self._airflow_state.commit(transition.transition_id):
                raise RuntimeError(
                    "Streamlines workload commit authority was superseded."
                )
        except Exception as error:
            if not mutated:
                return self._finish_streamlines_workload_failure(
                    transition,
                    str(error),
                    failure_stage="target_preparation",
                    rolled_back=False,
                )
            return await self._rollback_streamlines_workload_failure(
                transition,
                previous,
                str(error),
            )
        selected_identity = self._streamlines_cached_sample_identity(resolution.sample)
        evidence = StreamlinesWorkloadTransitionEvidence(
            transition_id=transition.transition_id,
            requested_workload=requested,
            previous_workload=previous.workload_mode,
            target_dataset=target_binding.dataset_identity,
            target_cache=classification,
            selected_sample_identity=selected_identity,
            initial_sample_identity=proof.initial_sample_identity,
            advanced_sample_identity=proof.advanced_sample_identity,
            committed_workload=requested,
            scheduler_tasks=proof.scheduler_tasks,
            streamlines_visible=True,
            sample_advanced=proof.sample_advanced,
            flow_attach_calls=0,
            requested_normalized_phase_seconds=(
                target_resolution.normalized_phase_seconds
            ),
            selected_normalized_phase_seconds=getattr(
                resolution,
                "normalized_phase_seconds",
                target_resolution.normalized_phase_seconds,
            ),
            normalized_phase_preserved=(
                resolution.sample.sample_index == target_resolution.sample.sample_index
            ),
        )
        self._streamlines_last_workload_transition_evidence = evidence
        message = (
            f"Streamlines workload committed: {previous.workload_mode} -> "
            f"{requested}; dataset={target_binding.dataset_identity}; "
            f"selected_sample={selected_identity}; scheduler_tasks=1; "
            "cache_build=0; recompute=0; KitCAE=0; VTI_import=0; "
            "Flow_attach_due_to_transition=0."
        )
        self._log_streamlines_workload_transition("COMPLETE", message)
        return self._streamlines_workload_result(
            True,
            requested,
            message,
            transition_id=transition.transition_id,
        )

    async def _rollback_streamlines_workload_failure(
        self,
        transition,
        previous,
        reason: str,
    ) -> StreamlinesWorkloadTransitionResult:
        """Reload and prove the last committed cache at the current phase."""

        try:
            await self.cleanup_streamlines_cached_presentation_in_kit()
            rollback_resolution = self._airflow_state.resolve_phase(previous.dataset)
            receipt = await self.ensure_streamlines_cache_validation_in_background(
                previous.binding,
                previous.dataset,
            )
            if receipt.inspection.classification != "VALID":
                raise RuntimeError(
                    "Previous cache is " f"{receipt.inspection.classification}."
                )
            restored = await self.prepare_streamlines_cached_target_in_kit(
                previous.binding,
                previous.dataset,
                rollback_resolution.phase_seconds,
                expected_sample_index=rollback_resolution.sample.sample_index,
                expected_source_vti=rollback_resolution.sample.source_vti,
                validated_receipt=receipt,
            )
            await self.start_streamlines_cached_playback_in_kit()
            proof = await self.await_streamlines_cached_playback_advancement_in_kit(
                restored.sample
            )
            if not proof.sample_advanced:
                raise RuntimeError("Previous cache did not resume real playback.")
            if not self.set_streamlines_cached_presentation_visible_in_kit(True):
                raise RuntimeError("Previous Streamlines presentation stayed hidden.")
            self._verify_streamlines_workload_presentation(previous.binding, proof)
        except Exception as rollback_error:
            if self._airflow_state.is_current(
                transition.transition_id,
                transition.target.binding,
            ):
                self._airflow_state.fail_unreconciled_runtime(
                    transition.transition_id,
                    semantic_workload=transition.target.workload_mode,
                    requested_binding=transition.target.binding,
                    reason=f"{reason}; rollback failed: {rollback_error}",
                )
            message = (
                f"Streamlines workload target failed: {reason}; "
                f"rollback unreconciled: {rollback_error}."
            )
            self._log_streamlines_workload_transition("FAIL", message)
            return self._streamlines_workload_result(
                False,
                transition.target.workload_mode,
                message,
                transition_id=transition.transition_id,
                unreconciled=True,
            )
        return self._finish_streamlines_workload_failure(
            transition,
            f"{reason}; previous Streamlines cache restored and advancing",
            failure_stage="target_presentation",
            rolled_back=True,
        )

    def _verify_streamlines_workload_presentation(self, binding, proof) -> None:
        """Require exact loaded identity and one visible advancing scheduler."""

        contract = self._streamlines_cache_playback_contract
        if (
            not isinstance(contract, CachedPlaybackContract)
            or contract.workload != binding.workload_mode
            or contract.dataset_identity != binding.dataset_identity
            or not self.streamlines_cached_presentation_is_visible_in_kit()
            or self._active_streamlines_playback_task_count() != 1
            or not proof.sample_advanced
        ):
            raise RuntimeError(
                "Streamlines workload presentation identity/liveness proof failed."
            )

    def _require_streamlines_workload_target(self, transition) -> None:
        """Reject stale workload or visualization ownership before mutation."""

        if not self._streamlines_workload_transition_current(transition):
            raise RuntimeError("Streamlines workload request was superseded.")

    def _streamlines_workload_transition_current(self, transition) -> bool:
        """Require the exact airflow generation and unchallenged Streamlines mode."""

        return (
            self._streamlines_workload_mode_owned()
            and self._airflow_state.is_current(
                transition.transition_id,
                transition.target.binding,
            )
        )

    def _streamlines_workload_target_authorized(
        self,
        transition_id: str,
        binding,
    ) -> bool:
        """Authorize target ticks while pending and after their proven commit."""

        if not self._streamlines_workload_mode_owned():
            return False
        if self._airflow_state.is_current(transition_id, binding):
            return True
        committed = self._airflow_state.committed
        return bool(committed and committed.binding == binding)

    def _streamlines_workload_mode_owned(self) -> bool:
        """Return whether Streamlines exclusively owns primary presentation state."""

        snapshot = self.visualization_snapshot()
        return bool(
            snapshot.committed
            in {
                VisualizationMode.STREAMLINES,
                VisualizationMode.STREAMLINES_XRAY,
            }
            and snapshot.pending is None
        )

    def _loaded_streamlines_target_is_healthy(self, binding) -> bool:
        """Recognise a true same-workload no-op without restarting playback."""

        committed = self._airflow_state.committed
        contract = getattr(self, "_streamlines_cache_playback_contract", None)
        return bool(
            committed
            and committed.binding == binding
            and isinstance(contract, CachedPlaybackContract)
            and contract.workload == binding.workload_mode
            and contract.dataset_identity == binding.dataset_identity
            and self.streamlines_cached_presentation_is_visible_in_kit()
            and self._active_streamlines_playback_task_count() == 1
            and self.streamlines_cached_playback_advanced_in_kit()
        )

    def _finish_streamlines_workload_failure(
        self,
        transition,
        reason: str,
        *,
        failure_stage: str,
        rolled_back: bool,
    ) -> StreamlinesWorkloadTransitionResult:
        """Clear only this generation and preserve superseding requests."""

        if self._airflow_state.is_current(
            transition.transition_id,
            transition.target.binding,
        ):
            self._airflow_state.fail(
                transition.transition_id,
                semantic_workload=transition.target.workload_mode,
                requested_binding=transition.target.binding,
                reason=reason,
                failure_stage=failure_stage,
                attached=True,
            )
        message = f"Streamlines workload transition failed: {reason}."
        self._log_streamlines_workload_transition("FAIL", message)
        return self._streamlines_workload_result(
            False,
            transition.target.workload_mode,
            message,
            transition_id=transition.transition_id,
            rolled_back=rolled_back,
        )

    def _streamlines_workload_result(
        self,
        success: bool,
        requested_workload: str,
        message: str,
        *,
        transition_id: str | None = None,
        rolled_back: bool = False,
        unreconciled: bool = False,
    ) -> StreamlinesWorkloadTransitionResult:
        """Build a result from current shared committed truth."""

        committed = self._airflow_state.committed
        return StreamlinesWorkloadTransitionResult(
            success=success,
            message=message,
            requested_workload=requested_workload,
            committed_workload=(committed.workload_mode if committed else None),
            transition_id=transition_id,
            rolled_back=rolled_back,
            unreconciled=unreconciled,
        )

    @staticmethod
    def _report_streamlines_workload_progress(
        status_callback: StatusCallback | None,
        message: str,
    ) -> None:
        """Publish bounded milestones without owning UI state."""

        if status_callback:
            status_callback(message)

    @staticmethod
    def _log_streamlines_workload_transition(event: str, message: str) -> None:
        """Emit concise production diagnostics when Kit logging is available."""

        try:
            import carb
        except ImportError:
            return
        logger = carb.log_error if event == "FAIL" else carb.log_warn
        logger(f"DTRS STREAMLINES | WORKLOAD_TRANSITION | {event} | {message}")
