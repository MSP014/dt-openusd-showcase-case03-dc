"""Runtime orchestration for transactional DTRS primary visualization modes."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Callable

from digital_twin_runtime_suite.app.airflow_validation.cache import (
    build_dataset_validation_signature,
)
from digital_twin_runtime_suite.app.visualization_mode.model import (
    VisualizationMode,
    VisualizationTransitionContext,
)
from digital_twin_runtime_suite.app.visualization_mode.readiness import (
    VisualizationReadiness,
    VisualizationReadinessSnapshot,
)
from digital_twin_runtime_suite.app.visualization_mode.state import (
    VisualizationModeState,
)

_HEATMAP_XRAY_OVERRIDE_OWNER = "heatmap_preview"
_STREAMLINES_XRAY_OVERRIDE_OWNER = "streamlines_xray"
_STREAMLINES_PRIMARY_MODES = frozenset(
    (
        VisualizationMode.STREAMLINES,
        VisualizationMode.STREAMLINES_XRAY,
    )
)


@dataclass(frozen=True)
class VisualizationModeResult:
    """Result of one primary-mode request without exposing Kit implementation."""

    success: bool
    message: str
    committed_mode: VisualizationMode


@dataclass(frozen=True)
class PrimaryPresentationSnapshot:
    """Backend state for primary-consumer cleanup and acceptance proof."""

    flow_source_prepared: bool
    smoke_presentation_visible: bool
    streamlines_root_prepared: bool
    streamlines_presentation_visible: bool
    streamlines_scheduler_tasks: int

    @property
    def primary_presentation_active(self) -> bool:
        """Report viewport-active consumers, excluding hidden prepared state."""

        return self.smoke_presentation_visible or self.streamlines_presentation_visible

    def normal_failure_reason(self) -> str | None:
        """Describe the exact backend condition that prevents Normal commit."""

        fields = []
        if self.flow_source_prepared:
            fields.append("Flow source remains prepared")
        if self.smoke_presentation_visible:
            fields.append("native Flow Smoke renderer remains visible")
        if self.streamlines_presentation_visible:
            fields.append("Streamlines root remains visible")
        if self.streamlines_scheduler_tasks:
            fields.append(
                "Streamlines scheduler tasks=" f"{self.streamlines_scheduler_tasks}"
            )
        return "; ".join(fields) if fields else None


class VisualizationModeRuntimeMixin:
    """Compose primary presentation over independent airflow and X-Ray owners.

    This mixin owns only mode transactions. Flow retains airflow lifecycle and
    Streamlines retains cache classification; X-Ray retains material bindings.
    """

    def reset_visualization_mode_state(self) -> None:
        """Clear transient mode ownership at reload or shutdown boundaries."""

        self._visualization_mode_state = VisualizationModeState()
        self._visualization_flow_attach_calls = 0

    def visualization_snapshot(self):
        """Expose committed and pending primary presentation without UI ownership."""

        return self._visualization_mode_state.snapshot

    def primary_visualization_presentation_snapshot_in_kit(
        self,
    ) -> PrimaryPresentationSnapshot:
        """Read backend presentation state without trusting intent flags."""

        return PrimaryPresentationSnapshot(
            flow_source_prepared=self.flow_source_is_prepared_in_kit(),
            smoke_presentation_visible=self.smoke_presentation_is_visible_in_kit(),
            streamlines_root_prepared=(
                self.streamlines_cached_presentation_is_prepared_in_kit()
            ),
            streamlines_presentation_visible=(
                self.streamlines_cached_presentation_is_visible_in_kit()
            ),
            streamlines_scheduler_tasks=(
                self._active_streamlines_playback_task_count()
            ),
        )

    def visualization_readiness(self) -> VisualizationReadinessSnapshot:
        """Project current-workload readiness without building or validating data."""

        binding, dataset = self.resolve_current_airflow_dataset()
        smoke = self._smoke_readiness(dataset)
        streamlines = self.streamlines_cache_readiness_snapshot()
        return VisualizationReadinessSnapshot(
            workload=binding.workload_mode,
            entries=(
                VisualizationReadiness(
                    VisualizationMode.NORMAL,
                    "READY",
                    "No primary visualization consumer is active.",
                    True,
                ),
                smoke,
                VisualizationReadiness(
                    VisualizationMode.STREAMLINES,
                    streamlines.classification,
                    streamlines.message,
                    streamlines.classification in {"VALID", "CHECKING"},
                ),
                VisualizationReadiness(
                    VisualizationMode.STREAMLINES_XRAY,
                    streamlines.classification,
                    f"{streamlines.message} X-Ray overlay uses current settings.",
                    streamlines.classification in {"VALID", "CHECKING"},
                ),
                VisualizationReadiness(
                    VisualizationMode.HEATMAP,
                    "PREVIEW_READY",
                    "X-Ray preview ready — thermal presentation pending.",
                    True,
                ),
            ),
        )

    def _smoke_readiness(self, dataset) -> VisualizationReadiness:
        """Read only the current dataset's existing background validation receipt."""

        try:
            signature = build_dataset_validation_signature(
                dataset,
                self.config.simulation_cache.velocity_field_name,
            )
            receipt = self._flow_validation_cache.lookup(signature).preflight
        except Exception as error:
            return VisualizationReadiness(
                VisualizationMode.SMOKE,
                "UNAVAILABLE",
                f"Current workload validation is unavailable: {error}",
                False,
            )
        if receipt is None:
            return VisualizationReadiness(
                VisualizationMode.SMOKE,
                "VALIDATING",
                "Current workload Flow validation is not complete.",
                True,
            )
        return VisualizationReadiness(
            VisualizationMode.SMOKE,
            "READY",
            "Current workload Flow validation receipt is ready.",
            True,
        )

    async def request_visualization_mode_in_kit(
        self,
        mode: VisualizationMode | str,
        *,
        status_callback: Callable[[str], None] | None = None,
    ) -> VisualizationModeResult:
        """Request one primary presentation without changing airflow semantics."""

        target = VisualizationMode(mode)
        if target in _STREAMLINES_PRIMARY_MODES:
            readiness = self.visualization_readiness().for_mode(target)
            if readiness.state not in {"VALID", "CHECKING"}:
                return self._result(
                    False,
                    "Streamlines cache is " f"{readiness.state}: {readiness.message}",
                )
        transition = self._visualization_mode_state.begin(target)
        if transition is None:
            return self._result(True, f"Visualization mode remains {target.value}.")
        lock = getattr(self, "_visualization_mode_lock", None)
        if lock is None:
            lock = asyncio.Lock()
            self._visualization_mode_lock = lock
        async with lock:
            pending = self._visualization_mode_state.snapshot.pending
            if pending is None or pending.transition_id != transition.transition_id:
                return self._result(False, "Visualization request was superseded.")
            try:
                if target is VisualizationMode.NORMAL:
                    result = await self._activate_normal_mode()
                elif target is VisualizationMode.SMOKE:
                    result = await self._activate_requested_smoke_mode(
                        transition,
                        status_callback,
                    )
                elif target is VisualizationMode.STREAMLINES:
                    result = await self._activate_streamlines_mode(
                        transition,
                        status_callback,
                    )
                elif target is VisualizationMode.STREAMLINES_XRAY:
                    result = await self._activate_streamlines_xray_mode(
                        transition,
                        status_callback,
                    )
                else:
                    result = await self._activate_heatmap_preview_mode()
            except Exception as error:
                result = VisualizationModeResult(
                    False,
                    f"Visualization transition failed: {error}",
                    self._visualization_mode_state.committed,
                )
        if result.success and self._visualization_mode_state.commit(
            transition.transition_id
        ):
            if target in _STREAMLINES_PRIMARY_MODES:
                metadata = getattr(self, "_streamlines_loaded_cache_metadata", None)
                if metadata is not None:
                    from digital_twin_runtime_suite.app.streamlines.profile import (
                        StreamlinesProfileId,
                    )

                    self._streamlines_profile_preference.mark_loaded(
                        StreamlinesProfileId(metadata.profile_id)
                    )
            return self._result(True, result.message)
        if not result.success:
            self._visualization_mode_state.fail(
                transition.transition_id,
                result.message,
            )
        return self._result(False, result.message)

    def cancel_visualization_transition(self) -> bool:
        """Cancel only pending mode ownership during shutdown or UI supersession."""

        cancel_presentation = getattr(
            self,
            "cancel_streamlines_cached_presentation_in_kit",
            None,
        )
        if cancel_presentation:
            cancel_presentation()
        else:
            cancel_playback = getattr(
                self,
                "cancel_streamlines_cached_playback",
                None,
            )
            if cancel_playback:
                cancel_playback()
        return self._visualization_mode_state.cancel()

    async def _activate_normal_mode(self) -> VisualizationModeResult:
        """Remove the primary Flow consumer while preserving independent X-Ray."""

        previous_mode = self._visualization_mode_state.committed
        released_streamlines_xray = False
        if previous_mode is VisualizationMode.STREAMLINES_XRAY:
            release = self.release_streamlines_xray_override_in_kit()
            if not release.success:
                return self._result(False, release.message)
            released_streamlines_xray = True
        elif previous_mode is VisualizationMode.HEATMAP:
            release = self.release_heatmap_xray_override_in_kit()
            if not release.success:
                return self._result(False, release.message)
        if (
            previous_mode in _STREAMLINES_PRIMARY_MODES
            or getattr(self, "_streamlines_cache_playback_contract", None) is not None
            or self.streamlines_cached_presentation_is_prepared_in_kit()
        ):
            try:
                await self.cleanup_streamlines_cached_presentation_in_kit()
                self.release_streamlines_presentation_material_in_kit()
            except Exception as error:
                if released_streamlines_xray:
                    self.restore_streamlines_xray_override_in_kit()
                return self._result(
                    False,
                    f"Normal cleanup could not release Streamlines: {error}",
                )
        before_detach = self.primary_visualization_presentation_snapshot_in_kit()
        streamlines_failure = before_detach.normal_failure_reason()
        if (
            before_detach.streamlines_presentation_visible
            or before_detach.streamlines_scheduler_tasks
        ):
            return self._result(
                False,
                "Normal cleanup left Streamlines active: "
                f"{streamlines_failure or 'inspect presentation snapshot'}.",
            )
        if self._flow_lifecycle_state != "DETACHED":
            result = await self.detach_simulation_cache_in_kit()
            if not result.success:
                return self._result(False, result.message)
        final_snapshot = self.primary_visualization_presentation_snapshot_in_kit()
        failure = final_snapshot.normal_failure_reason()
        if failure is not None:
            return self._result(
                False,
                "Normal cleanup left an active primary consumer: " f"{failure}.",
            )
        return self._result(True, "Normal visualization is active.")

    async def _activate_requested_smoke_mode(
        self,
        transition,
        status_callback: Callable[[str], None] | None,
    ) -> VisualizationModeResult:
        """Choose direct Smoke attach or the transactional Streamlines return."""

        if self._visualization_mode_state.committed in _STREAMLINES_PRIMARY_MODES:
            context = self._capture_visualization_transition_context()
            return await self._activate_smoke_from_streamlines_mode(
                transition,
                context,
                status_callback,
            )
        return await self._activate_smoke_mode()

    async def _activate_smoke_mode(self) -> VisualizationModeResult:
        """Attach Flow first, retaining Heatmap override until Smoke is proven."""

        if self._flow_lifecycle_state == "DETACHED":
            attached = await self._attach_flow_for_visualization_mode()
            if not attached.success:
                return self._result(False, attached.message)
        elif self._flow_lifecycle_state != "ATTACHED":
            return self._result(False, "Flow lifecycle is busy; Smoke is not ready.")
        release = self.release_heatmap_xray_override_in_kit()
        if release.success:
            visible = self.set_smoke_presentation_visible_in_kit(True)
            if not visible.success:
                return self._result(False, visible.message)
            return self._result(True, "Smoke visualization is active.")
        detached = await self.detach_simulation_cache_in_kit()
        restore = self.restore_heatmap_xray_override_in_kit()
        message = f"Smoke rollback after X-Ray release failure: {release.message}"
        if not detached.success or not restore.success:
            message += " Primary presentation recovery needs inspection."
        return self._result(False, message)

    async def _activate_streamlines_mode(
        self,
        transition,
        status_callback: Callable[[str], None] | None,
        *,
        with_xray_overlay: bool = False,
    ) -> VisualizationModeResult:
        """Prepare and prove persisted Streamlines from any committed source."""

        previous_mode = self._visualization_mode_state.committed
        if previous_mode is VisualizationMode.STREAMLINES_XRAY:
            return self._deactivate_streamlines_xray_mode()
        binding, airflow_dataset, context = (
            self._capture_visualization_transition_target()
        )
        attach_calls_before = self.visualization_flow_attach_call_count()
        try:
            if self._cancel_running_flow_temporal_proof_for_streamlines():
                self._report_visualization_progress(
                    status_callback,
                    "Streamlines: cancelled the running Flow temporal proof; "
                    "retained Flow source remains prepared.",
                )
            self._report_visualization_progress(
                status_callback,
                "Streamlines: resolving the preserved cached source sample.",
            )
            resolution = await self.prepare_streamlines_cached_target_in_kit(
                binding,
                airflow_dataset,
                context.logical_phase_seconds,
                expected_sample_index=context.source_sample_index,
                expected_source_vti=context.source_vti,
                status_callback=status_callback,
                cancellation_requested=(
                    lambda: not self._visualization_transition_is_current(transition)
                ),
            )
            if not self._visualization_transition_is_current(transition):
                await self.cleanup_streamlines_cached_presentation_in_kit()
                return self._result(False, "Visualization request was superseded.")
            self._verify_streamlines_transition_context(context, resolution)
            self._report_visualization_progress(
                status_callback,
                "Streamlines: starting the accepted 200 ms scheduler.",
            )
            await self.start_streamlines_cached_playback_in_kit(
                status_callback=status_callback,
            )
            if not self._visualization_transition_is_current(transition):
                await self.cleanup_streamlines_cached_presentation_in_kit()
                return self._result(False, "Visualization request was superseded.")
            if self._active_streamlines_playback_task_count() != 1:
                raise RuntimeError("Streamlines requires exactly one scheduler task.")
            self._report_visualization_progress(
                status_callback,
                "Snapshot presentation prepared; initial real state selected; "
                "cached playback scheduler started.",
            )
            advance_proof = (
                await (
                    self.await_streamlines_cached_playback_advancement_in_kit(
                        resolution.sample
                    )
                )
            )
            if not advance_proof.sample_advanced:
                raise RuntimeError(
                    "Streamlines scheduler did not select a later real cached sample."
                )
            if not self.set_streamlines_cached_presentation_visible_in_kit(True):
                raise RuntimeError(
                    "Prepared Streamlines presentation could not be shown."
                )
            if not self.streamlines_cached_presentation_is_visible_in_kit():
                raise RuntimeError("Prepared Streamlines visibility proof failed.")
            self._report_visualization_progress(
                status_callback,
                "Production snapshot presentation is visible; "
                "cached-playback scheduler is active.",
            )
            await self._quiesce_previous_mode_for_streamlines(previous_mode)
            if with_xray_overlay:
                overlay = self.apply_streamlines_xray_override_in_kit()
                if not overlay.success:
                    raise RuntimeError(overlay.message)
            if not self._visualization_transition_is_current(transition):
                raise RuntimeError("Visualization request was superseded.")
            attach_calls = (
                self.visualization_flow_attach_call_count() - attach_calls_before
            )
            if attach_calls:
                raise RuntimeError("Streamlines activation unexpectedly attached Flow.")
            target = self._airflow_state.resolve_target(binding)
            if not self._airflow_state.commit_target(target):
                raise RuntimeError(
                    "Streamlines presentation lost shared-airflow commit authority."
                )
        except Exception as error:
            message = f"Streamlines transition rejected: {error}"
            try:
                await self.cleanup_streamlines_cached_presentation_in_kit()
            except Exception as cleanup_error:
                message += f" Candidate cleanup failed: {cleanup_error}"
            rollback = await self._restore_previous_after_streamlines_failure(
                previous_mode
            )
            if rollback is not None:
                message += f" Rollback failed: {rollback}"
            return self._result(False, message)
        presentation_name = (
            "Streamlines + X-Ray" if with_xray_overlay else "Streamlines"
        )
        return self._result(
            True,
            f"{presentation_name} visualization is active; cache_build=0; KitCAE=0; "
            "RuntimePreview=0; VTI_import=0; rebuild=0; flow_attach_calls=0; "
            f"initial_sample={advance_proof.initial_sample_identity}; "
            f"advanced_sample={advance_proof.advanced_sample_identity}; "
            f"scheduler_tasks={advance_proof.scheduler_tasks}.",
        )

    async def _activate_streamlines_xray_mode(
        self,
        transition,
        status_callback: Callable[[str], None] | None,
    ) -> VisualizationModeResult:
        """Overlay X-Ray on an existing Streamlines view or prepare both safely."""

        if self._visualization_mode_state.committed is VisualizationMode.STREAMLINES:
            if (
                self._active_streamlines_playback_task_count() != 1
                or not self.streamlines_cached_presentation_is_visible_in_kit()
            ):
                return self._result(
                    False,
                    "Streamlines + X-Ray requires one visible cached scheduler.",
                )
            overlay = self.apply_streamlines_xray_override_in_kit()
            if not overlay.success:
                return self._result(False, overlay.message)
            if self.xray_target_snapshot().override_owner != (
                _STREAMLINES_XRAY_OVERRIDE_OWNER
            ):
                self.release_streamlines_xray_override_in_kit()
                return self._result(
                    False,
                    "Streamlines + X-Ray overlay ownership proof failed.",
                )
            return self._result(
                True,
                "Streamlines + X-Ray is active; existing cached playback "
                "continues with scheduler_tasks=1.",
            )
        return await self._activate_streamlines_mode(
            transition,
            status_callback,
            with_xray_overlay=True,
        )

    def _deactivate_streamlines_xray_mode(self) -> VisualizationModeResult:
        """Return to the existing Streamlines playback without rebuilding it."""

        if (
            self._active_streamlines_playback_task_count() != 1
            or not self.streamlines_cached_presentation_is_visible_in_kit()
        ):
            return self._result(
                False,
                "Streamlines playback is unavailable while removing X-Ray.",
            )
        release = self.release_streamlines_xray_override_in_kit()
        if not release.success:
            return self._result(False, release.message)
        return self._result(
            True,
            "Streamlines visualization is active; cached playback continues "
            "with scheduler_tasks=1.",
        )

    async def _quiesce_previous_mode_for_streamlines(self, previous_mode) -> None:
        """Remove only the previous primary presentation after target proof."""

        if previous_mode is VisualizationMode.SMOKE:
            hidden_smoke = self.set_smoke_presentation_visible_in_kit(False)
            if not hidden_smoke.success:
                raise RuntimeError(hidden_smoke.message)
            if not await self.await_smoke_presentation_visibility_in_kit(False):
                raise RuntimeError(
                    "Native Flow Smoke renderer remained visible after handoff."
                )
            return
        if previous_mode is VisualizationMode.HEATMAP:
            released = self.release_heatmap_xray_override_in_kit()
            if not released.success:
                raise RuntimeError(released.message)

    async def _restore_previous_after_streamlines_failure(
        self,
        previous_mode,
    ) -> str | None:
        """Prove rollback to the prior committed presentation after target failure."""

        if previous_mode is VisualizationMode.SMOKE:
            restored = await self.resume_smoke_presentation_in_kit()
            if not restored.success or not self.smoke_presentation_is_visible_in_kit():
                return restored.message
            return None
        if previous_mode is VisualizationMode.HEATMAP:
            restored = self.restore_heatmap_xray_override_in_kit()
            if not restored.success:
                return restored.message
            override_owner = self.xray_target_snapshot().override_owner
            if override_owner != _HEATMAP_XRAY_OVERRIDE_OWNER:
                return "Heatmap X-Ray override was not restored."
            return None
        snapshot = self.primary_visualization_presentation_snapshot_in_kit()
        if snapshot.primary_presentation_active:
            return "Normal rollback retained a visible primary presentation."
        return None

    async def _activate_smoke_from_streamlines_mode(
        self,
        transition,
        context: VisualizationTransitionContext,
        status_callback: Callable[[str], None] | None,
    ) -> VisualizationModeResult:
        """Release Streamlines time ownership, then prove sustained retained Flow."""

        previous_mode = self._visualization_mode_state.committed
        reused = self._retained_flow_source_matches(context)
        reconstructed = False
        reconciled = False
        self._report_visualization_progress(
            status_callback,
            "Smoke: checking the retained Flow temporal source.",
        )
        if not reused:
            target_binding = self._airflow_state.resolve_binding(context.workload)
            target = self._airflow_state.resolve_target(target_binding)
            if self._flow_lifecycle_state == "ATTACHED":
                repaired = await self.request_attached_workload_transition_in_kit(
                    context.workload,
                    status_callback=status_callback,
                )
                if not repaired.success:
                    return await self._restore_streamlines_after_smoke_resume_failure(
                        "Stale retained Flow source reconciliation failed: "
                        + repaired.message
                    )
                reconciled = True
            elif self._flow_lifecycle_state != "DETACHED":
                return await self._restore_streamlines_after_smoke_resume_failure(
                    "Retained Flow lifecycle is busy and cannot be reconciled."
                )
            else:
                reconstructed = True
                self._report_visualization_progress(
                    status_callback,
                    "Smoke: reconstructing Flow because no source remains.",
                )
                attached = await self._attach_flow_for_visualization_mode()
                if not attached.success:
                    self._airflow_state.commit_target(target)
                    return await self._restore_streamlines_after_smoke_resume_failure(
                        "Smoke reconstruction failed: " + attached.message
                    )
                hidden = self.set_smoke_presentation_visible_in_kit(False)
                if not hidden.success or self.smoke_presentation_is_visible_in_kit():
                    await self.detach_simulation_cache_in_kit()
                    return self._result(
                        False,
                        "Reconstructed Flow Smoke presentation could not be "
                        "quiesced.",
                    )
        if not self._visualization_transition_is_current(transition):
            return self._result(False, "Visualization request was superseded.")
        if not self._retained_flow_source_matches(context):
            return self._result(
                False,
                "Smoke source does not match the preserved context.",
            )
        if not self._visualization_transition_is_current(transition):
            return self._result(False, "Visualization request was superseded.")
        self._report_visualization_progress(
            status_callback,
            "Smoke: stopping Streamlines scheduling.",
        )
        await self.stop_streamlines_cached_playback_in_kit()
        if self._active_streamlines_playback_task_count() != 0:
            return await self._restore_streamlines_after_smoke_resume_failure(
                "Streamlines scheduler did not stop cleanly."
            )
        if not self._visualization_transition_is_current(transition):
            return await self._restore_streamlines_after_smoke_resume_failure(
                "Visualization request was superseded."
            )
        self._report_visualization_progress(
            status_callback,
            "Smoke: proving sustained Flow playback after Streamlines cleanup.",
        )
        resumed = await self.resume_smoke_presentation_in_kit(show_presentation=False)
        if not resumed.success:
            return await self._restore_streamlines_after_smoke_resume_failure(
                resumed.message
            )
        smoke_proof = self.smoke_resume_advance_proof_in_kit()
        if smoke_proof is None or not smoke_proof.sustained_flow_playback:
            return await self._restore_streamlines_after_smoke_resume_failure(
                "Retained Flow source did not prove sustained temporal playback."
            )
        if not self._visualization_transition_is_current(transition):
            return await self._restore_streamlines_after_smoke_resume_failure(
                "Visualization request was superseded."
            )
        if (
            self._active_streamlines_playback_task_count() != 0
            or not smoke_proof.timeline_playing
        ):
            return await self._restore_streamlines_after_smoke_resume_failure(
                "Flow liveness was not proven after complete Streamlines cleanup."
            )
        visible_smoke = self.set_smoke_presentation_visible_in_kit(True)
        if not visible_smoke.success:
            return await self._restore_streamlines_after_smoke_resume_failure(
                "Flow Smoke presentation could not be restored."
            )
        smoke_visible = await self.await_smoke_presentation_visibility_in_kit(True)
        if not smoke_visible:
            return await self._restore_streamlines_after_smoke_resume_failure(
                "Flow Smoke presentation could not be restored."
            )
        hidden_streamlines = self.set_streamlines_cached_presentation_visible_in_kit(
            False
        )
        if (
            hidden_streamlines is False
            or self.streamlines_cached_presentation_is_visible_in_kit()
        ):
            return await self._restore_streamlines_after_smoke_resume_failure(
                "Streamlines presentation could not be hidden."
            )
        if not self._visualization_transition_is_current(transition):
            return await self._restore_streamlines_after_smoke_resume_failure(
                "Visualization request was superseded."
            )
        if not self.flow_timeline_is_playing_in_kit():
            return await self._restore_streamlines_after_smoke_resume_failure(
                "Flow timeline stopped after the sustained Smoke resume proof."
            )
        if previous_mode is VisualizationMode.STREAMLINES_XRAY:
            release = self.release_streamlines_xray_override_in_kit()
            if not release.success:
                return await self._restore_streamlines_after_smoke_resume_failure(
                    "Streamlines + X-Ray release failed: " + release.message
                )
        return self._result(
            True,
            "Smoke visualization is active; "
            f"reused={reused}; reconstructed={reconstructed}; "
            f"reconciled={reconciled}; "
            "streamlines_scheduler_tasks=0; "
            f"timeline_playing={smoke_proof.timeline_playing}; "
            f"flow_source_0={smoke_proof.source_0}; "
            f"flow_source_1={smoke_proof.source_1}; "
            f"flow_source_2={smoke_proof.source_2}; "
            f"sustained_flow_playback={smoke_proof.sustained_flow_playback}.",
        )

    async def _restore_streamlines_after_smoke_resume_failure(
        self,
        reason: str,
    ) -> VisualizationModeResult:
        """Restore the last valid Streamlines view after a failed Smoke proof."""

        self.set_smoke_presentation_visible_in_kit(False)
        self.set_streamlines_cached_presentation_visible_in_kit(True)
        try:
            if self._active_streamlines_playback_task_count() != 1:
                await self.start_streamlines_cached_playback_in_kit()
        except Exception as error:
            return self._result(
                False,
                f"{reason} Streamlines rollback failed: {error}",
            )
        if self._active_streamlines_playback_task_count() != 1:
            return self._result(
                False,
                f"{reason} Streamlines rollback did not restore one scheduler.",
            )
        return self._result(False, reason)

    @staticmethod
    def _report_visualization_progress(
        status_callback: Callable[[str], None] | None,
        message: str,
    ) -> None:
        """Forward bounded transaction milestones without owning UI logging."""

        if status_callback:
            status_callback(message)

    def _capture_visualization_transition_context(
        self,
    ) -> VisualizationTransitionContext:
        """Capture shared workload and phase exactly once for one handoff."""

        _binding, _dataset, context = self._capture_visualization_transition_target()
        return context

    def _capture_visualization_transition_target(self):
        """Capture exact target binding, dataset and canonical phase once."""

        binding, dataset = self.resolve_current_airflow_dataset()
        resolution = self._airflow_state.resolve_phase(dataset)
        context = VisualizationTransitionContext(
            workload=binding.workload_mode,
            dataset_identity=binding.dataset_identity,
            logical_phase_seconds=resolution.phase_seconds,
            normalized_phase_seconds=resolution.normalized_phase_seconds,
            source_sample_index=resolution.sample.sample_index,
            source_time_seconds=resolution.sample.source_time_seconds,
            source_vti=resolution.sample.source_vti,
        )
        return binding, dataset, context

    def _cancel_running_flow_temporal_proof_for_streamlines(self) -> bool:
        """Cancel only a competing Flow observer before cache composition.

        The retained Flow source remains attached.  Cancellation invalidates the
        observer generation because cache composition can legitimately delay Kit
        updates beyond the strict every-source proof cadence.
        """

        progress = self.temporal_proof_progress()
        if getattr(progress.state, "value", progress.state) not in {
            "RUNNING",
            "CHECKING_LOOP_CLOSURE",
        }:
            return False
        return self._cancel_kit_cae_temporal_proof(
            reason="VISUALIZATION_MODE_TRANSITION"
        )

    def _verify_streamlines_transition_context(self, context, resolution) -> None:
        """Reject a prepared cache that drifted from the captured source identity."""

        contract = self._streamlines_cache_playback_contract
        if (
            contract.workload != context.workload
            or contract.dataset_identity != context.dataset_identity
            or resolution.sample.sample_index != context.source_sample_index
            or resolution.sample.source_vti.resolve() != context.source_vti.resolve()
        ):
            raise RuntimeError("Prepared Streamlines cache identity proof failed.")

    def _retained_flow_source_matches(self, context) -> bool:
        """Verify the actual live Flow source, never shared logical intent alone."""

        if self._flow_lifecycle_state != "ATTACHED":
            return False
        try:
            binding = self._airflow_state.resolve_binding(context.workload)
            target = self._airflow_state.resolve_target(binding)
        except Exception:
            return False
        if binding.dataset_identity != context.dataset_identity:
            return False
        matches, _source = self._live_flow_consumer_matches_dataset(target.dataset)
        return matches

    def _visualization_transition_is_current(self, transition) -> bool:
        """Guard irreversible handoff steps against a newer mode generation."""

        pending = self._visualization_mode_state.snapshot.pending
        return bool(pending and pending.transition_id == transition.transition_id)

    async def _activate_heatmap_preview_mode(self) -> VisualizationModeResult:
        """Prove Heatmap preview, then release any previous primary consumer."""

        previous_mode = self._visualization_mode_state.committed
        released_streamlines_xray = False
        if previous_mode is VisualizationMode.STREAMLINES_XRAY:
            release = self.release_streamlines_xray_override_in_kit()
            if not release.success:
                return self._result(False, release.message)
            released_streamlines_xray = True
        applied = self.apply_heatmap_xray_override_in_kit()
        if not applied.success:
            if released_streamlines_xray:
                self.restore_streamlines_xray_override_in_kit()
            return self._result(False, applied.message)
        if self._flow_lifecycle_state != "DETACHED":
            detached = await self.detach_simulation_cache_in_kit()
            if not detached.success:
                self.release_heatmap_xray_override_in_kit()
                if released_streamlines_xray:
                    self.restore_streamlines_xray_override_in_kit()
                return self._result(False, detached.message)
        if previous_mode in _STREAMLINES_PRIMARY_MODES:
            try:
                await self.stop_streamlines_cached_playback_in_kit()
                if self._active_streamlines_playback_task_count() != 0:
                    raise RuntimeError("Streamlines scheduler did not stop cleanly.")
                await self.cleanup_streamlines_cached_presentation_in_kit()
                presentation = self.primary_visualization_presentation_snapshot_in_kit()
                if (
                    presentation.streamlines_presentation_visible
                    or presentation.streamlines_scheduler_tasks
                ):
                    raise RuntimeError(
                        "Streamlines presentation remained active after cleanup."
                    )
            except Exception as error:
                self.release_heatmap_xray_override_in_kit()
                rollback = await self._restore_streamlines_after_target_failure(
                    str(error)
                )
                if released_streamlines_xray:
                    restored = self.restore_streamlines_xray_override_in_kit()
                    if not restored.success:
                        rollback += f" X-Ray rollback failed: {restored.message}"
                return self._result(False, rollback)
        return self._result(
            True,
            "Heatmap X-Ray preview is active; thermal presentation is pending.",
        )

    async def _restore_streamlines_after_target_failure(self, reason: str) -> str:
        """Restore one visible scheduled Streamlines presentation after handoff."""

        self.set_streamlines_cached_presentation_visible_in_kit(True)
        try:
            if self._active_streamlines_playback_task_count() != 1:
                await self.start_streamlines_cached_playback_in_kit()
        except Exception as error:
            return f"{reason} Streamlines rollback failed: {error}"
        if (
            self._active_streamlines_playback_task_count() != 1
            or not self.streamlines_cached_presentation_is_visible_in_kit()
        ):
            return f"{reason} Streamlines rollback could not be proven."
        return reason

    async def _attach_flow_for_visualization_mode(self):
        """Count only Flow attach attempts owned by primary-mode activation."""

        self._visualization_flow_attach_calls += 1
        return await self.attach_simulation_cache_in_kit()

    def visualization_flow_attach_call_count(self) -> int:
        """Expose cumulative mode-owned Flow attach attempts for acceptance."""

        return getattr(self, "_visualization_flow_attach_calls", 0)

    def _result(self, success: bool, message: str) -> VisualizationModeResult:
        """Build a result against the current committed state after any rollback."""

        return VisualizationModeResult(
            success,
            message,
            self._visualization_mode_state.committed,
        )
