"""Own disposable Streamlines profile previews and guided review state."""

from __future__ import annotations

import asyncio
import time
from contextlib import suppress
from dataclasses import dataclass, replace
from statistics import mean
from typing import Callable

from digital_twin_runtime_suite.app.diagnostics import with_dtrs_yerevan_timestamp
from digital_twin_runtime_suite.app.flow.performance import (
    ViewportPerformanceSample,
    capture_viewport_performance_sample,
)
from digital_twin_runtime_suite.app.manual_acceptance import (
    GuidedAcceptanceSession,
    format_manual_acceptance_event,
    format_manual_acceptance_test_complete,
)
from digital_twin_runtime_suite.app.streamlines.profile import (
    DEFAULT_STREAMLINES_PROFILE,
    STREAMLINES_PROFILE_LABELS,
    StreamlinesProfileId,
)
from digital_twin_runtime_suite.app.streamlines.profile_state import (
    StreamlinesProfileState,
)
from digital_twin_runtime_suite.app.streamlines.tuning import (
    DEFAULT_GLOBAL_FLOW_PATH_TUNING,
    FINAL_GLOBAL_FLOW_PATH_CANDIDATE,
    FINAL_VOLUME_COVERAGE_CANDIDATE,
    PREVIEW_WORKLOAD_OPTIONS,
    AcceptedStreamlinesCandidate,
    StreamlinesPreviewSelectionMismatchError,
    StreamlinesProfileTuning,
    StreamlinesTuningState,
    format_streamlines_tuning_complete,
)

StatusCallback = Callable[[str], None]
_VALIDATION_MILESTONES = tuple(
    f"{StreamlinesProfileId.VOLUME_COVERAGE.value}:{workload}"
    for workload in PREVIEW_WORKLOAD_OPTIONS
)
_PERFORMANCE_SETTLE_SECONDS = 10.0
_PERFORMANCE_SAMPLE_WINDOW_SECONDS = 2.0
_PERFORMANCE_SAMPLE_COUNT = 8


@dataclass(frozen=True)
class _StabilizedPerformanceReceipt:
    samples: int
    fps_current: float | None
    fps_average: float | None
    fps_minimum: float | None
    frame_time_ms_current: float | None
    frame_time_ms_average: float | None
    gpu_used_gib: float | None
    process_used_gib: float | None


class StreamlinesProfilePreviewRuntimeMixin:
    """Coordinate preview-only work without mutating production cache state."""

    def reset_streamlines_profile_preview_state(self) -> None:
        """Reset preference, independent tuning selections and guided sessions."""

        current_state = getattr(self, "_streamlines_profile_preference", None)
        preferred_profile = (
            current_state.snapshot.preferred_profile
            if current_state is not None
            else DEFAULT_STREAMLINES_PROFILE
        )
        self.cancel_streamlines_profile_preview_measurement()
        self._streamlines_profile_preference = StreamlinesProfileState(
            preferred_profile
        )
        self._streamlines_tuning_state = StreamlinesTuningState()
        self._streamlines_phase44a_tuning_session = None
        self._streamlines_phase44a_validation_session = None
        self._streamlines_phase44a_accepted_candidates = {}
        self._streamlines_phase44a_last_preview = None
        self._streamlines_preview_work_task = None
        self._streamlines_preview_performance_task = None

    def cancel_streamlines_profile_preview_measurement(self) -> None:
        """Invalidate preview work so stale geometry cannot publish a receipt."""

        self._streamlines_preview_generation = (
            getattr(self, "_streamlines_preview_generation", 0) + 1
        )
        for name in (
            "_streamlines_preview_work_task",
            "_streamlines_preview_performance_task",
        ):
            task = getattr(self, name, None)
            if task is not None and not task.done():
                task.cancel()
            setattr(self, name, None)

    def streamlines_profile_preference_snapshot(self):
        """Return the production-facing preference without presentation work."""

        return self._streamlines_profile_preference.snapshot

    def set_streamlines_profile_preference(
        self,
        profile_id: StreamlinesProfileId,
    ):
        """Change preference only; cached production switching is future work."""

        return self._streamlines_profile_preference.set_preference(profile_id)

    def streamlines_tuning_selection(
        self,
        profile_id: StreamlinesProfileId,
    ) -> StreamlinesProfileTuning:
        return self._streamlines_tuning_state.selection_for(profile_id)

    async def preview_streamlines_production_profile_in_kit(
        self,
        status_callback: StatusCallback | None = None,
        *,
        workload: str,
        tuning: StreamlinesProfileTuning = DEFAULT_GLOBAL_FLOW_PATH_TUNING,
        profile_id: StreamlinesProfileId = DEFAULT_STREAMLINES_PROFILE,
    ):
        """Compatibility entry point for the existing controller/UI seam."""

        return await self.run_streamlines_profile_preview(
            profile_id=profile_id,
            workload=workload,
            tuning_selection=tuning,
            status_callback=status_callback,
        )

    async def run_streamlines_profile_preview(
        self,
        *,
        profile_id: StreamlinesProfileId,
        workload: str,
        tuning_selection: StreamlinesProfileTuning,
        status_callback: StatusCallback | None = None,
    ):
        """Run one explicit profile/workload preview with zero cache writes."""

        profile_id = StreamlinesProfileId(profile_id)
        if tuning_selection.profile_id is not profile_id:
            raise ValueError("Streamlines profile and tuning selection disagree.")
        try:
            effective_selection, accepted_candidate = (
                self._validate_phase44a_requested_preview(
                    profile_id,
                    workload,
                    tuning_selection,
                )
            )
        except StreamlinesPreviewSelectionMismatchError as error:
            self._report_phase44a_validation_mismatch(error)
            raise
        except Exception as error:
            self._fail_phase44a_active(str(error))
            raise
        if self._flow_lifecycle_state != "DETACHED":
            raise RuntimeError("Profile preview requires Flow DETACHED.")
        targets = {
            target.binding.workload_mode: target
            for target in self.resolve_configured_airflow_targets()
        }
        target = targets.get(workload)
        if target is None:
            raise RuntimeError(f"Unknown Streamlines preview workload: {workload}.")
        self.cancel_streamlines_profile_preview_measurement()
        generation = self._streamlines_preview_generation
        preview_started_at = time.monotonic()
        self._streamlines_phase44a_last_preview = None
        if accepted_candidate is None:
            self._streamlines_tuning_state.set_selection(effective_selection)
        label = STREAMLINES_PROFILE_LABELS[profile_id]
        self._report_phase44a_active("START", f"Preparing {label} for {workload}.")
        self._report_phase44a_active(
            "PROGRESS",
            "Deriving deterministic profile seed Mesh.",
        )
        if status_callback:
            status_callback(f"Preparing {label} / {workload} preview.")
        try:
            result = await self._await_profile_preview_with_waiting(
                self._preview_streamlines_profile_target_in_kit(
                    binding=target.binding,
                    airflow_dataset=target.dataset,
                    profile_id=profile_id,
                    tuning=effective_selection,
                ),
                generation=generation,
            )
            self._require_current_streamlines_preview(generation)
            if result.curve_count <= 0 or result.point_count <= 0:
                raise RuntimeError("Profile preview produced placeholder geometry.")
            if (
                accepted_candidate is not None
                and result.curve_count != result.expected_curve_count
            ):
                raise RuntimeError(
                    "Accepted Streamlines candidate curve count changed: "
                    f"expected={result.expected_curve_count}; "
                    f"actual={result.curve_count}."
                )
            self._report_phase44a_active("PROGRESS", "Preview is visible.")
            performance = await self._measure_stabilized_preview_performance(generation)
            self._require_current_streamlines_preview(generation)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._fail_phase44a_active(str(error))
            raise
        if result.tuning_evidence is not None:
            evidence = replace(
                result.tuning_evidence,
                viewport_fps=performance.fps_current,
                viewport_fps_average=performance.fps_average,
                viewport_fps_minimum=performance.fps_minimum,
                frame_time_ms_current=performance.frame_time_ms_current,
                frame_time_ms_average=performance.frame_time_ms_average,
                gpu_used_gib=performance.gpu_used_gib,
                process_used_gib=performance.process_used_gib,
                performance_settle_seconds=_PERFORMANCE_SETTLE_SECONDS,
                performance_sample_window_seconds=(_PERFORMANCE_SAMPLE_WINDOW_SECONDS),
                performance_samples=performance.samples,
                preview_total_ms=(time.monotonic() - preview_started_at) * 1000.0,
                candidate_source=(
                    "ACCEPTED_SESSION"
                    if accepted_candidate is not None
                    else "LIVE_TUNING"
                ),
                accepted_candidate_signature=(
                    accepted_candidate.signature
                    if accepted_candidate is not None
                    else None
                ),
                live_tuning_ignored=accepted_candidate is not None,
            )
            result = replace(result, tuning_evidence=evidence)
        self._streamlines_phase44a_last_preview = (
            profile_id,
            workload,
            effective_selection,
            result,
        )
        if result.tuning_evidence is not None:
            carb = self._streamlines_carb_logger()
            if carb:
                carb.log_warn(
                    with_dtrs_yerevan_timestamp(
                        format_streamlines_tuning_complete(result.tuning_evidence)
                    )
                )
        self._complete_phase44a_preview(
            profile_id,
            workload,
            effective_selection,
            result,
            accepted_candidate=accepted_candidate,
            performance=performance,
        )
        if status_callback:
            status_callback(
                f"{label} / {workload} ready: curves={result.curve_count}; "
                f"points={result.point_count}."
            )
        return (result,)

    async def _await_profile_preview_with_waiting(self, awaitable, *, generation):
        """Emit bounded five-second waits only while real preview work is active."""

        task = asyncio.ensure_future(awaitable)
        self._streamlines_preview_work_task = task
        try:
            while True:
                done, _pending = await asyncio.wait({task}, timeout=5.0)
                if done:
                    self._require_current_streamlines_preview(generation)
                    return task.result()
                self._report_phase44a_active(
                    "WAITING",
                    "Standard Kit-CAE Streamlines preview is still executing.",
                )
        except asyncio.CancelledError:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            raise
        finally:
            if self._streamlines_preview_work_task is task:
                self._streamlines_preview_work_task = None

    async def _measure_stabilized_preview_performance(
        self,
        generation: int,
    ) -> _StabilizedPerformanceReceipt:
        """Measure several quiet viewport samples after the preview is visible."""

        await self._await_one_preview_viewport_update()
        self._require_current_streamlines_preview(generation)
        self._report_phase44a_active(
            "WAITING",
            "Allowing viewport to stabilize for performance measurement.",
        )
        task = asyncio.ensure_future(
            self._collect_stabilized_preview_samples(generation)
        )
        self._streamlines_preview_performance_task = task
        try:
            samples = await task
        finally:
            if self._streamlines_preview_performance_task is task:
                self._streamlines_preview_performance_task = None
        return self._aggregate_stabilized_preview_samples(samples)

    async def _collect_stabilized_preview_samples(
        self,
        generation: int,
    ) -> tuple[ViewportPerformanceSample, ...]:
        await self._wait_preview_measurement_interval(_PERFORMANCE_SETTLE_SECONDS)
        self._require_current_streamlines_preview(generation)
        interval = _PERFORMANCE_SAMPLE_WINDOW_SECONDS / (_PERFORMANCE_SAMPLE_COUNT - 1)
        samples = []
        for index in range(_PERFORMANCE_SAMPLE_COUNT):
            self._require_current_streamlines_preview(generation)
            samples.append(capture_viewport_performance_sample())
            if index + 1 < _PERFORMANCE_SAMPLE_COUNT:
                await self._wait_preview_measurement_interval(interval)
        return tuple(samples)

    @staticmethod
    async def _wait_preview_measurement_interval(seconds: float) -> None:
        await asyncio.sleep(seconds)

    @staticmethod
    async def _await_one_preview_viewport_update() -> None:
        try:
            import omni.kit.app
        except ImportError:
            await asyncio.sleep(0)
            return
        await omni.kit.app.get_app().next_update_async()

    @staticmethod
    def _aggregate_stabilized_preview_samples(
        samples: tuple[ViewportPerformanceSample, ...],
    ) -> _StabilizedPerformanceReceipt:
        if len(samples) < 2:
            raise RuntimeError("Stabilized preview performance needs several samples.")
        fps_values = tuple(sample.fps for sample in samples if sample.fps is not None)
        frame_times = tuple(
            sample.frame_time_ms
            for sample in samples
            if sample.frame_time_ms is not None
        )
        final = samples[-1]
        return _StabilizedPerformanceReceipt(
            samples=len(samples),
            fps_current=final.fps,
            fps_average=(float(mean(fps_values)) if fps_values else None),
            fps_minimum=(min(fps_values) if fps_values else None),
            frame_time_ms_current=final.frame_time_ms,
            frame_time_ms_average=(float(mean(frame_times)) if frame_times else None),
            gpu_used_gib=final.gpu_memory_used_gib,
            process_used_gib=final.process_memory_used_gib,
        )

    def _require_current_streamlines_preview(self, generation: int) -> None:
        if generation != self._streamlines_preview_generation:
            raise asyncio.CancelledError

    def accept_current_streamlines_profile_candidate(self) -> bool:
        """Reject obsolete Test A acceptance after both profiles were selected."""

        return False

    def announce_streamlines_phase44a_acceptance_when_ready(
        self,
        *,
        no_pending_visualization: bool,
        no_pending_airflow: bool,
    ) -> None:
        """Start the final Volume-only delta validation once review is clean."""

        if (
            self._streamlines_phase44a_validation_session is not None
            or not no_pending_visualization
            or not no_pending_airflow
            or not self.streamlines_phase44a_preview_ready()
        ):
            return
        self._streamlines_phase44a_accepted_candidates = {
            StreamlinesProfileId.GLOBAL_FLOW_PATH: (
                AcceptedStreamlinesCandidate.capture(FINAL_GLOBAL_FLOW_PATH_CANDIDATE)
            ),
            StreamlinesProfileId.VOLUME_COVERAGE: (
                AcceptedStreamlinesCandidate.capture(FINAL_VOLUME_COVERAGE_CANDIDATE)
            ),
        }
        self._begin_phase44a_validation()

    def _validate_phase44a_requested_preview(
        self,
        profile_id: StreamlinesProfileId,
        workload: str,
        selection: StreamlinesProfileTuning,
    ) -> tuple[
        StreamlinesProfileTuning,
        AcceptedStreamlinesCandidate | None,
    ]:
        validation = self._streamlines_phase44a_validation_session
        if validation is None or validation.expected_milestone is None:
            return selection, None
        expected_profile_value, expected_workload = validation.expected_milestone.split(
            ":", 1
        )
        expected_profile = StreamlinesProfileId(expected_profile_value)
        if profile_id is not expected_profile or workload != expected_workload:
            raise StreamlinesPreviewSelectionMismatchError(
                expected_profile=expected_profile,
                selected_profile=profile_id,
                expected_workload=expected_workload,
                selected_workload=workload,
            )
        accepted = self._streamlines_phase44a_accepted_candidates[profile_id]
        return accepted.selection, accepted

    def _report_phase44a_validation_mismatch(
        self,
        error: StreamlinesPreviewSelectionMismatchError,
    ) -> None:
        """Reject a wrong Test B action while preserving its current milestone."""

        validation = self._streamlines_phase44a_validation_session
        if validation is None or validation.expected_milestone is None:
            return
        self._report_phase44a(
            "STREAMLINES | PHASE_4_4A_VALIDATION",
            validation,
            "FAIL",
            str(error),
            next_action=self._phase44a_validation_next_action(validation),
        )

    def _complete_phase44a_preview(
        self,
        profile_id,
        workload,
        selection,
        result,
        *,
        accepted_candidate: AcceptedStreamlinesCandidate | None,
        performance: _StabilizedPerformanceReceipt,
    ) -> None:
        validation = self._streamlines_phase44a_validation_session
        contract = selection.geometry_contract
        evidence = (
            f"profile={profile_id.value}; workload={workload}; "
            f"dataset={result.dataset_identity}; sample_index={result.sample_index}; "
            f"seed_count={contract.seed_count}; "
            f"section_count={contract.section_count}; "
            f"max_steps={contract.max_steps}; "
            "effective_steps="
            f"{contract.min_step_cell_multiplier:.9g}/"
            f"{contract.initial_step_cell_multiplier:.9g}/"
            f"{contract.max_step_cell_multiplier:.9g}; "
            f"expected_curves={result.expected_curve_count}; "
            f"actual_curves={result.curve_count}; points={result.point_count}; "
            "cache_build=0; cache_rebuild=0; "
            f"performance_settle_seconds={_PERFORMANCE_SETTLE_SECONDS:g}; "
            "performance_sample_window_seconds="
            f"{_PERFORMANCE_SAMPLE_WINDOW_SECONDS:g}; "
            f"performance_samples={performance.samples}; "
            f"viewport_fps_current={performance.fps_current}; "
            f"viewport_fps_average={performance.fps_average}; "
            f"viewport_fps_minimum={performance.fps_minimum}; "
            f"frame_time_ms_current={performance.frame_time_ms_current}; "
            f"frame_time_ms_average={performance.frame_time_ms_average}; "
            f"gpu_used_gib={performance.gpu_used_gib}; "
            f"process_used_gib={performance.process_used_gib}"
        )
        if accepted_candidate is not None:
            evidence += (
                "; candidate_source=ACCEPTED_SESSION; "
                "accepted_candidate_signature="
                f"{accepted_candidate.signature}; live_tuning_ignored=True"
            )
        if validation is None:
            tuning = self._streamlines_phase44a_tuning_session
            self._report_phase44a(
                "STREAMLINES | PHASE_4_4A_TUNING",
                tuning,
                "COMPLETE",
                evidence,
                next_action=(
                    "Inspect the result, then press "
                    '"Accept Current Candidate" if usable.'
                ),
            )
            return
        milestone = f"{profile_id.value}:{workload}"
        if not validation.record(milestone):
            return
        if validation.expected_milestone is None:
            self._report_phase44a(
                "STREAMLINES | PHASE_4_4A_VALIDATION",
                validation,
                "COMPLETE",
                evidence,
            )
            if validation.complete():
                self._emit_test_complete(
                    "Phase 4.4A Streamlines profiles passed final geometry "
                    "validation.\nGlobal Flow Path and Volume Coverage "
                    "production candidates are accepted."
                )
            return
        self._report_phase44a(
            "STREAMLINES | PHASE_4_4A_VALIDATION",
            validation,
            "COMPLETE",
            evidence,
            next_action=self._phase44a_validation_next_action(validation),
        )

    @staticmethod
    def _phase44a_validation_next_action(validation) -> str:
        profile_value, workload = validation.expected_milestone.split(":", 1)
        label = STREAMLINES_PROFILE_LABELS[StreamlinesProfileId(profile_value)]
        prefix = (
            "Inspect result; select" if validation.completed_milestones else "Select"
        )
        return (
            f'{prefix} "{label}" in "Profile", '
            f'select "{workload}" in "Workload" and run '
            '"Run Profile Preview".'
        )

    def _begin_phase44a_validation(self) -> None:
        session = GuidedAcceptanceSession(_VALIDATION_MILESTONES)
        session.begin()
        self._streamlines_phase44a_validation_session = session
        self._report_phase44a(
            "STREAMLINES | PHASE_4_4A_VALIDATION",
            session,
            "READY",
            "Final Volume Coverage Max Steps=20 candidate is locked for "
            "four-workload delta validation.",
            next_action=self._phase44a_validation_next_action(session),
        )

    def _report_phase44a_active(self, event: str, status: str) -> None:
        validation = self._streamlines_phase44a_validation_session
        if validation is not None:
            self._report_phase44a(
                "STREAMLINES | PHASE_4_4A_VALIDATION",
                validation,
                event,
                status,
            )
            return
        self._report_phase44a(
            "STREAMLINES | PHASE_4_4A_TUNING",
            self._streamlines_phase44a_tuning_session,
            event,
            status,
        )

    def _fail_phase44a_active(self, reason: str) -> None:
        session = (
            self._streamlines_phase44a_validation_session
            or self._streamlines_phase44a_tuning_session
        )
        if session is None or session.failed or session.terminal_emitted:
            return
        session.mark_failed()
        area = (
            "STREAMLINES | PHASE_4_4A_VALIDATION"
            if self._streamlines_phase44a_validation_session is not None
            else "STREAMLINES | PHASE_4_4A_TUNING"
        )
        self._report_phase44a(area, session, "FAIL", reason)

    def _report_phase44a(
        self,
        area: str,
        session,
        event: str,
        status: str,
        *,
        next_action: str | None = None,
    ) -> None:
        if session is None or session.terminal_emitted:
            return
        carb = self._streamlines_carb_logger()
        if carb:
            carb.log_warn(
                with_dtrs_yerevan_timestamp(
                    format_manual_acceptance_event(
                        area=area,
                        event=event,
                        status=status,
                        next_action=next_action,
                    )
                )
            )

    def _emit_test_complete(self, result: str) -> None:
        carb = self._streamlines_carb_logger()
        if carb:
            carb.log_warn(
                with_dtrs_yerevan_timestamp(
                    format_manual_acceptance_test_complete(result)
                )
            )
