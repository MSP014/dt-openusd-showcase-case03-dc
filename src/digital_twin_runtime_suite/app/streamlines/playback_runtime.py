"""Kit-facing cached Streamlines switching and bounded cadence characterization."""

from __future__ import annotations

import asyncio
import math
import time
from dataclasses import dataclass
from typing import Callable

from digital_twin_runtime_suite.app.diagnostics import with_dtrs_yerevan_timestamp
from digital_twin_runtime_suite.app.flow.performance import (
    ViewportPerformanceSample,
    capture_viewport_performance_sample,
)
from digital_twin_runtime_suite.app.streamlines.cadence_probe import (
    CADENCE_CANDIDATE_PERIOD_SECONDS,
    FAST_CADENCE_CANDIDATE_PERIOD_SECONDS,
    FAST_CADENCE_FALLBACK_PERIOD_SECONDS,
    WRAP_RECHECK_CANDIDATE_PERIOD_SECONDS,
    WRAP_RECHECK_FALLBACK_PERIOD_SECONDS,
    WRAP_RECHECK_OBSERVATION_SECONDS,
    CadenceCandidateResult,
    cadence_candidate_result,
    resolved_cache_state_wrap_transition,
    select_cadence_candidate_or_fallback,
    select_shortest_acceptable_candidate,
)
from digital_twin_runtime_suite.app.streamlines.playback import (
    CachedPlaybackContract,
    resolve_cached_playback_state,
)
from digital_twin_runtime_suite.app.streamlines.playback_scheduler import (
    CachedPlaybackScheduler,
    CachedPlaybackSchedulerReport,
)
from digital_twin_runtime_suite.app.streamlines.temporal import (
    TemporalSampleResolution,
)

StatusCallback = Callable[[str], None]
PRODUCTION_CACHE_SANITY_PERIOD_SECONDS = 0.2
PRODUCTION_CACHE_SANITY_DURATION_SECONDS = 4.0


@dataclass(frozen=True)
class StreamlinesCadenceCharacterizationResult:
    """Completed bounded characterization and its persisted production selection."""

    candidates: tuple[CadenceCandidateResult, ...]
    selected: CadenceCandidateResult | None
    presentation_period_seconds: float | None
    fallback_retained: bool = False


@dataclass(frozen=True)
class StreamlinesProductionCacheSanityResult:
    """Short post-build proof that persisted geometry still plays at 200 ms."""

    scheduler: CachedPlaybackSchedulerReport
    duration_seconds: float
    maximum_active_playback_task_count: int
    active_playback_task_count_after_stop: int

    @property
    def passed(self) -> bool:
        """Require direct cached playback to switch, stay current, and stop cleanly."""

        return (
            math.isclose(
                self.scheduler.period_seconds,
                PRODUCTION_CACHE_SANITY_PERIOD_SECONDS,
            )
            and self.scheduler.tick_count >= 20
            and self.scheduler.missed_deadlines == 0
            and self.scheduler.backlog_count == 0
            and self.maximum_active_playback_task_count == 1
            and self.active_playback_task_count_after_stop == 0
        )


@dataclass(frozen=True)
class StreamlinesPlaybackAdvanceProof:
    """Evidence that a later scheduler tick selected a different real sample."""

    initial_sample_identity: str
    advanced_sample_identity: str | None
    scheduler_tasks: int
    scheduler_tick_count: int

    @property
    def sample_advanced(self) -> bool:
        """Return whether the accepted scheduler observed a later real sample."""

        return bool(
            self.advanced_sample_identity
            and self.advanced_sample_identity != self.initial_sample_identity
            and self.scheduler_tasks == 1
            and self.scheduler_tick_count >= 2
        )


@dataclass(frozen=True)
class StreamlinesTimelineOwnership:
    """Timeline state captured when cached playback takes temporal control."""

    was_playing: bool
    current_time_seconds: float


class StreamlinesPlaybackRuntimeMixin:
    """Own persisted-geometry switching; never import VTI or execute Kit-CAE."""

    async def select_streamlines_cache_state_in_kit(
        self,
        phase_seconds: float,
    ) -> TemporalSampleResolution:
        """Switch to the exact real cached state resolved from the current phase."""

        contract = self._streamlines_cache_playback_contract
        if not isinstance(contract, CachedPlaybackContract):
            raise RuntimeError(
                "Load a valid Streamlines cache before selecting a playback state."
            )
        shared_target = (
            self._airflow_state.committed or self._airflow_state.resolve_current()
        )
        if (
            contract.workload != shared_target.workload_mode
            or contract.dataset_identity != shared_target.binding.dataset_identity
        ):
            raise RuntimeError(
                "Validated Streamlines cache does not match shared airflow state."
            )
        resolution = resolve_cached_playback_state(
            contract,
            phase_seconds,
            active_sample_index=self._streamlines_cache_active_sample_index,
        )
        if resolution.is_no_op:
            return resolution

        import omni.kit.app
        import omni.timeline
        import omni.usd

        from digital_twin_runtime_suite.app.streamlines.cache import (
            CACHE_PLAYBACK_CURVES_PATH,
        )

        stage = omni.usd.get_context().get_stage()
        curves_prim = stage.GetPrimAtPath(CACHE_PLAYBACK_CURVES_PATH) if stage else None
        if not curves_prim or not curves_prim.IsValid():
            raise RuntimeError("Validated Streamlines cache geometry is not attached.")
        timeline = omni.timeline.get_timeline_interface()
        self._acquire_streamlines_timeline_control_in_kit(timeline)
        timeline.pause()
        timeline.set_current_time(resolution.sample.source_time_seconds)
        app = omni.kit.app.get_app()
        await app.next_update_async()
        await app.next_update_async()
        self._streamlines_cache_active_sample_index = resolution.sample.sample_index
        return resolution

    async def start_streamlines_cached_playback_in_kit(
        self,
        *,
        period_seconds: float | None = None,
        status_callback: StatusCallback | None = None,
    ) -> None:
        """Start one direct current-phase scheduler for the validated cache."""

        if not isinstance(
            self._streamlines_cache_playback_contract,
            CachedPlaybackContract,
        ):
            raise RuntimeError("Load a valid Streamlines cache before playback.")
        configured_period = (
            self.config.simulation_cache.streamlines_presentation_period_seconds
        )
        active_period = (
            period_seconds if period_seconds is not None else configured_period
        )
        if active_period is None:
            raise RuntimeError(
                "No accepted Streamlines presentation period is configured."
            )
        await self.stop_streamlines_cached_playback_in_kit()
        self._streamlines_cached_playback_advanced = False
        self._streamlines_cached_playback_last_sample = None
        started_at = time.monotonic()
        scheduler = CachedPlaybackScheduler(
            period_seconds=active_period,
            phase_source=self._airflow_state.phase_seconds,
            state_selector=self.select_streamlines_cache_state_in_kit,
            tick_observer=self._record_streamlines_cached_playback_tick,
        )
        self._streamlines_cached_playback_scheduler = scheduler
        self._streamlines_cached_playback_started_at = started_at
        await scheduler.start()
        self._report_streamlines_cached_playback(
            event="START",
            message=(
                "Cached playback started: " f"period_ms={active_period * 1000.0:.0f}."
            ),
            status_callback=status_callback,
        )

    async def await_streamlines_cached_playback_advancement_in_kit(
        self,
        initial_sample,
    ) -> StreamlinesPlaybackAdvanceProof:
        """Require a later 200 ms tick to select a different real cache sample."""

        import omni.kit.app

        app = omni.kit.app.get_app()
        initial_identity = self._streamlines_cached_sample_identity(initial_sample)
        advanced_identity = None
        for _ in range(480):
            await app.next_update_async()
            scheduler = getattr(self, "_streamlines_cached_playback_scheduler", None)
            tick_count = len(scheduler.ticks) if scheduler is not None else 0
            sample = getattr(self, "_streamlines_cached_playback_last_sample", None)
            advanced_identity = (
                self._streamlines_cached_sample_identity(sample)
                if sample is not None
                else None
            )
            proof = StreamlinesPlaybackAdvanceProof(
                initial_sample_identity=initial_identity,
                advanced_sample_identity=advanced_identity,
                scheduler_tasks=self._active_streamlines_playback_task_count(),
                scheduler_tick_count=tick_count,
            )
            if proof.sample_advanced:
                self._streamlines_cached_playback_advanced = True
                self._streamlines_cached_playback_advance_proof = proof
                return proof
        self._streamlines_cached_playback_advanced = False
        proof = StreamlinesPlaybackAdvanceProof(
            initial_sample_identity=initial_identity,
            advanced_sample_identity=advanced_identity,
            scheduler_tasks=self._active_streamlines_playback_task_count(),
            scheduler_tick_count=(
                len(self._streamlines_cached_playback_scheduler.ticks)
                if getattr(self, "_streamlines_cached_playback_scheduler", None)
                else 0
            ),
        )
        self._streamlines_cached_playback_advance_proof = proof
        return proof

    def streamlines_cached_playback_advanced_in_kit(self) -> bool:
        """Expose the visible transition's scheduler-driven advancement proof."""

        return bool(getattr(self, "_streamlines_cached_playback_advanced", False))

    def streamlines_cached_playback_advance_proof_in_kit(self):
        """Expose the latest exact cached-sample liveness receipt."""

        return getattr(self, "_streamlines_cached_playback_advance_proof", None)

    def _record_streamlines_cached_playback_tick(self, tick) -> None:
        """Keep the scheduler's resolved sample without altering its cadence."""

        self._streamlines_cached_playback_last_sample = tick.resolution.sample

    @staticmethod
    def _streamlines_cached_sample_identity(sample) -> str:
        """Format only canonical real-sample identity for transition evidence."""

        source = getattr(sample, "source_vti", None)
        source_name = source.name if source is not None else "unavailable"
        return f"index={sample.sample_index}; source={source_name}"

    async def stop_streamlines_cached_playback_in_kit(
        self,
    ) -> CachedPlaybackSchedulerReport | None:
        """Stop the owned production scheduler without detaching its cache layer."""

        scheduler = getattr(self, "_streamlines_cached_playback_scheduler", None)
        self._streamlines_cached_playback_scheduler = None
        self._streamlines_cached_playback_started_at = None
        if not isinstance(scheduler, CachedPlaybackScheduler):
            return None
        return await scheduler.stop()

    def _acquire_streamlines_timeline_control_in_kit(self, timeline) -> None:
        """Capture timeline state once before Streamlines begins selecting samples."""

        if getattr(self, "_streamlines_timeline_ownership", None) is not None:
            return
        self._streamlines_timeline_ownership = StreamlinesTimelineOwnership(
            was_playing=bool(timeline.is_playing()),
            current_time_seconds=float(timeline.get_current_time()),
        )

    def streamlines_controls_timeline_in_kit(self) -> bool:
        """Report whether cached Streamlines still owns global timeline updates."""

        return getattr(self, "_streamlines_timeline_ownership", None) is not None

    async def release_streamlines_timeline_control_in_kit(
        self,
    ) -> StreamlinesTimelineOwnership | None:
        """Stop all selectors before releasing global timeline ownership."""

        ownership = getattr(self, "_streamlines_timeline_ownership", None)
        await self.stop_streamlines_cached_playback_in_kit()
        self._streamlines_timeline_ownership = None
        return ownership

    def cancel_streamlines_cached_playback(self) -> None:
        """Request immediate task cancellation during synchronous stage teardown."""

        scheduler = getattr(self, "_streamlines_cached_playback_scheduler", None)
        if isinstance(scheduler, CachedPlaybackScheduler):
            scheduler.cancel()
        self._streamlines_cached_playback_scheduler = None
        self._streamlines_cached_playback_started_at = None
        self._streamlines_timeline_ownership = None

    async def run_streamlines_production_cache_sanity_in_kit(
        self,
        status_callback: StatusCallback | None = None,
    ) -> StreamlinesProductionCacheSanityResult:
        """Exercise an already valid cache at the accepted 200 ms period only.

        This is a short post-profile guard, not another cadence search. It may
        attach a validated persisted cache but never rebuilds geometry, imports
        a VTI for playback, or runs the Streamlines operator.
        """

        if self._flow_lifecycle_state != "DETACHED":
            raise RuntimeError("Production cache sanity requires Flow DETACHED.")
        if not isinstance(
            self._streamlines_cache_playback_contract,
            CachedPlaybackContract,
        ):
            await self.load_streamlines_cache_in_kit(
                status_callback=status_callback,
                start_playback=False,
            )
        await self.stop_streamlines_cached_playback_in_kit()
        self._report_streamlines_cached_playback(
            event="PROGRESS",
            message=(
                "Production-cache sanity: applying one unmeasured persisted "
                "cache state before the 200 ms window."
            ),
            status_callback=status_callback,
        )
        await self.select_streamlines_cache_state_in_kit(
            self._airflow_state.phase_seconds()
        )
        await self.start_streamlines_cached_playback_in_kit(
            period_seconds=PRODUCTION_CACHE_SANITY_PERIOD_SECONDS,
            status_callback=status_callback,
        )
        active_task_count = self._active_streamlines_playback_task_count()
        if active_task_count != 1:
            await self.stop_streamlines_cached_playback_in_kit()
            raise RuntimeError(
                "Production cache sanity requires exactly one active playback task; "
                f"observed={active_task_count}."
            )
        try:
            await asyncio.sleep(PRODUCTION_CACHE_SANITY_DURATION_SECONDS)
        finally:
            scheduler = await self.stop_streamlines_cached_playback_in_kit()
        active_task_count_after_stop = self._active_streamlines_playback_task_count()
        if scheduler is None:
            raise RuntimeError("Production cache sanity lost its playback scheduler.")
        result = StreamlinesProductionCacheSanityResult(
            scheduler=scheduler,
            duration_seconds=PRODUCTION_CACHE_SANITY_DURATION_SECONDS,
            maximum_active_playback_task_count=active_task_count,
            active_playback_task_count_after_stop=active_task_count_after_stop,
        )
        if not result.passed:
            raise RuntimeError(
                "Production cache sanity failed: "
                f"ticks={scheduler.tick_count}; "
                f"median_switch_ms="
                f"{scheduler.median_switch_latency_seconds * 1000.0:.1f}; "
                f"max_switch_ms="
                f"{scheduler.maximum_switch_latency_seconds * 1000.0:.1f}; "
                f"missed_deadlines={scheduler.missed_deadlines}; "
                f"max_deadline_lateness_ms="
                f"{scheduler.maximum_drift_seconds * 1000.0:.1f}; "
                f"backlog={scheduler.backlog_count}; "
                f"max_active_playback_tasks={active_task_count}; "
                f"active_playback_tasks_after_stop="
                f"{active_task_count_after_stop}."
            )
        return result

    def _active_streamlines_playback_task_count(self) -> int:
        """Return the active-task count of the sole scheduler owned by this mixin."""

        scheduler = getattr(self, "_streamlines_cached_playback_scheduler", None)
        if not isinstance(scheduler, CachedPlaybackScheduler):
            return 0
        return scheduler.active_task_count

    def announce_streamlines_cadence_characterization_ready(self) -> str:
        """Publish a manual cadence action only after a validated cache is loaded."""

        if not isinstance(
            self._streamlines_cache_playback_contract,
            CachedPlaybackContract,
        ):
            return "Load Streamlines Cache before cadence characterization."
        action = "Run Cadence Characterization"
        message = (
            "DTRS STREAMLINES | CADENCE_CHARACTERIZATION | READY\n"
            f'NEXT_ACTION | Press "{action}"'
        )
        carb = self._streamlines_carb_logger()
        if carb:
            carb.log_warn(with_dtrs_yerevan_timestamp(message))
        return f'Ready — Press "{action}".'

    def is_streamlines_cadence_characterization_ready(self) -> bool:
        """Return whether one loaded cache can enter the bounded manual workflow."""

        return self._flow_lifecycle_state == "DETACHED" and isinstance(
            self._streamlines_cache_playback_contract,
            CachedPlaybackContract,
        )

    def announce_streamlines_fast_cadence_check_ready(self) -> str:
        """Publish the continuation action only after the 500 ms baseline exists."""

        if not self.is_streamlines_fast_cadence_check_ready():
            return "Run Cadence Characterization before the fast cadence check."
        action = "Run Fast Cadence Check"
        message = (
            "DTRS STREAMLINES | CADENCE_CHARACTERIZATION | READY\n"
            f'NEXT_ACTION | Press "{action}"'
        )
        carb = self._streamlines_carb_logger()
        if carb:
            carb.log_warn(with_dtrs_yerevan_timestamp(message))
        return f'Ready — Press "{action}".'

    def is_streamlines_fast_cadence_check_ready(self) -> bool:
        """Require a loaded cache and the already accepted 500 ms baseline."""

        configured_period = (
            self.config.simulation_cache.streamlines_presentation_period_seconds
        )
        return self.is_streamlines_cadence_characterization_ready() and (
            configured_period is not None
            and math.isclose(
                configured_period,
                FAST_CADENCE_FALLBACK_PERIOD_SECONDS,
                rel_tol=0.0,
                abs_tol=1e-9,
            )
        )

    async def run_streamlines_cadence_characterization_in_kit(
        self,
        status_callback: StatusCallback | None = None,
    ) -> StreamlinesCadenceCharacterizationResult:
        """Measure only the four bounded cached-playback candidates."""

        return await self._run_streamlines_cadence_check_in_kit(
            candidate_periods=CADENCE_CANDIDATE_PERIOD_SECONDS,
            action="Run Cadence Characterization",
            fallback_period_seconds=None,
            minimum_observation_seconds=None,
            status_callback=status_callback,
            workflow_name="Cadence characterization",
        )

    async def run_streamlines_fast_cadence_check_in_kit(
        self,
        status_callback: StatusCallback | None = None,
    ) -> StreamlinesCadenceCharacterizationResult:
        """Measure only 250 and 200 ms against the accepted 500 ms baseline."""

        if not self.is_streamlines_fast_cadence_check_ready():
            raise RuntimeError(
                "Run Cadence Characterization before the fast cadence check."
            )
        return await self._run_streamlines_cadence_check_in_kit(
            candidate_periods=FAST_CADENCE_CANDIDATE_PERIOD_SECONDS,
            action="Run Fast Cadence Check",
            fallback_period_seconds=FAST_CADENCE_FALLBACK_PERIOD_SECONDS,
            minimum_observation_seconds=None,
            status_callback=status_callback,
            workflow_name="Fast cadence check",
        )

    def announce_streamlines_200ms_wrap_recheck_ready(self) -> str:
        """Publish the one-candidate recheck only after the 250 ms fallback exists."""

        if not self.is_streamlines_200ms_wrap_recheck_ready():
            return "A confirmed 250 ms Streamlines period is required for recheck."
        action = "Recheck 200 ms Wrap"
        message = (
            "DTRS STREAMLINES | CADENCE_CHARACTERIZATION | READY\n"
            f'NEXT_ACTION | Press "{action}"'
        )
        carb = self._streamlines_carb_logger()
        if carb:
            carb.log_warn(with_dtrs_yerevan_timestamp(message))
        return f'Ready — Press "{action}".'

    def is_streamlines_200ms_wrap_recheck_ready(self) -> bool:
        """Require the validated cache and the accepted 250 ms recovery baseline."""

        configured_period = (
            self.config.simulation_cache.streamlines_presentation_period_seconds
        )
        return self.is_streamlines_cadence_characterization_ready() and (
            configured_period is not None
            and math.isclose(
                configured_period,
                WRAP_RECHECK_FALLBACK_PERIOD_SECONDS,
                rel_tol=0.0,
                abs_tol=1e-9,
            )
        )

    async def run_streamlines_200ms_wrap_recheck_in_kit(
        self,
        status_callback: StatusCallback | None = None,
    ) -> StreamlinesCadenceCharacterizationResult:
        """Recheck only 200 ms with enough time to observe a real state wrap."""

        if not self.is_streamlines_200ms_wrap_recheck_ready():
            raise RuntimeError(
                "A confirmed 250 ms Streamlines period is required for recheck."
            )
        return await self._run_streamlines_cadence_check_in_kit(
            candidate_periods=WRAP_RECHECK_CANDIDATE_PERIOD_SECONDS,
            action="Recheck 200 ms Wrap",
            fallback_period_seconds=WRAP_RECHECK_FALLBACK_PERIOD_SECONDS,
            minimum_observation_seconds=WRAP_RECHECK_OBSERVATION_SECONDS,
            status_callback=status_callback,
            workflow_name="200 ms wrap recheck",
        )

    async def _run_streamlines_cadence_check_in_kit(
        self,
        *,
        candidate_periods: tuple[float, ...],
        action: str,
        fallback_period_seconds: float | None,
        minimum_observation_seconds: float | None,
        status_callback: StatusCallback | None,
        workflow_name: str,
    ) -> StreamlinesCadenceCharacterizationResult:
        """Run one fixed candidate set and restore its explicit production fallback."""

        contract = self._streamlines_cache_playback_contract
        if not isinstance(contract, CachedPlaybackContract):
            raise RuntimeError(
                "Load a valid Streamlines cache before cadence characterization."
            )
        await self.stop_streamlines_cached_playback_in_kit()
        started_at = time.monotonic()
        self._report_streamlines_cadence(
            event="START",
            message=(
                f"{workflow_name} started: "
                f"{len(candidate_periods)} bounded candidates."
            ),
            status_callback=status_callback,
        )
        results = []
        try:
            for ordinal, period_seconds in enumerate(candidate_periods, start=1):
                result = await self._run_streamlines_cadence_candidate_in_kit(
                    contract=contract,
                    ordinal=ordinal,
                    candidate_count=len(candidate_periods),
                    minimum_observation_seconds=minimum_observation_seconds,
                    period_seconds=period_seconds,
                    started_at=started_at,
                    status_callback=status_callback,
                )
                results.append(result)
        except Exception as error:
            if fallback_period_seconds is not None:
                await self.start_streamlines_cached_playback_in_kit(
                    period_seconds=fallback_period_seconds,
                    status_callback=status_callback,
                )
            self._report_streamlines_cadence(
                event="FAIL",
                message=f"Cadence characterization failed: {error}",
                status_callback=status_callback,
            )
            raise

        result_tuple = tuple(results)
        selection = (
            select_cadence_candidate_or_fallback(
                result_tuple,
                fallback_period_seconds=fallback_period_seconds,
            )
            if fallback_period_seconds is not None
            else None
        )
        selected = (
            selection.selected
            if selection is not None
            else select_shortest_acceptable_candidate(result_tuple)
        )
        if selected is None:
            if selection is not None:
                await self.start_streamlines_cached_playback_in_kit(
                    period_seconds=selection.presentation_period_seconds,
                    status_callback=status_callback,
                )
                self._report_streamlines_cadence(
                    event="COMPLETE",
                    message=(
                        f"{workflow_name} complete: retained accepted "
                        f"baseline_period_ms="
                        f"{selection.presentation_period_seconds * 1000.0:.0f}."
                    ),
                    status_callback=status_callback,
                )
                self._report_streamlines_cadence(
                    event="TEST COMPLETE",
                    message=(
                        f"{workflow_name} candidate rejected; accepted baseline "
                        "resumed. "
                        "No further manual action required."
                    ),
                    status_callback=status_callback,
                )
                return StreamlinesCadenceCharacterizationResult(
                    candidates=result_tuple,
                    selected=None,
                    presentation_period_seconds=(selection.presentation_period_seconds),
                    fallback_retained=True,
                )
            self._report_streamlines_cadence(
                event="FAIL",
                message="No cadence candidate met the complete acceptance gate.",
                status_callback=status_callback,
            )
            self._report_streamlines_cadence(
                event="NEXT_ACTION",
                message=f'Press "{action}" after review.',
                status_callback=status_callback,
            )
            return StreamlinesCadenceCharacterizationResult(
                candidates=result_tuple,
                selected=None,
                presentation_period_seconds=None,
            )

        self.save_streamlines_presentation_period(selected.period_seconds)
        await self.start_streamlines_cached_playback_in_kit(
            period_seconds=selected.period_seconds,
            status_callback=status_callback,
        )
        self._report_streamlines_cadence(
            event="COMPLETE",
            message=(
                f"{workflow_name} complete: "
                f"selected_period_ms={selected.period_seconds * 1000.0:.0f}."
            ),
            status_callback=status_callback,
        )
        self._report_streamlines_cadence(
            event="TEST COMPLETE",
            message=(
                "Cached playback cadence accepted. "
                "No further manual action required."
            ),
            status_callback=status_callback,
        )
        return StreamlinesCadenceCharacterizationResult(
            candidates=result_tuple,
            selected=selected,
            presentation_period_seconds=selected.period_seconds,
        )

    async def _run_streamlines_cadence_candidate_in_kit(
        self,
        *,
        contract: CachedPlaybackContract,
        ordinal: int,
        candidate_count: int,
        minimum_observation_seconds: float | None,
        period_seconds: float,
        started_at: float,
        status_callback: StatusCallback | None,
    ) -> CadenceCandidateResult:
        """Exercise one complete loop with direct current-phase scheduling."""

        self._report_streamlines_cadence(
            event="PROGRESS",
            message=(
                "Cadence candidate "
                f"{ordinal}/{candidate_count}: "
                f"period_ms={period_seconds * 1000.0:.0f}."
            ),
            status_callback=status_callback,
        )
        no_op_phase = 0.0
        await self.select_streamlines_cache_state_in_kit(no_op_phase)
        no_op_resolution = await self.select_streamlines_cache_state_in_kit(no_op_phase)
        performance_samples: list[ViewportPerformanceSample] = [
            capture_viewport_performance_sample()
        ]
        candidate_started_at = time.monotonic()
        scheduler = CachedPlaybackScheduler(
            period_seconds=period_seconds,
            phase_source=lambda: time.monotonic() - candidate_started_at,
            state_selector=self.select_streamlines_cache_state_in_kit,
            tick_observer=lambda _tick: performance_samples.append(
                capture_viewport_performance_sample()
            ),
        )
        await scheduler.start()
        try:
            duration_seconds = max(
                contract.loop_duration_seconds + period_seconds,
                minimum_observation_seconds or 0.0,
            )
            await self._await_streamlines_cadence_duration(
                scheduler=scheduler,
                duration_seconds=duration_seconds,
                ordinal=ordinal,
                candidate_count=candidate_count,
                period_seconds=period_seconds,
                started_at=started_at,
                status_callback=status_callback,
            )
        finally:
            scheduler_report = await scheduler.stop()
        performance_samples.append(capture_viewport_performance_sample())
        phase_mapping_pass = bool(scheduler.ticks) and all(
            0 <= tick.resolution.sample.sample_index < contract.sample_count
            for tick in scheduler.ticks
        )
        state_wrap_transition = resolved_cache_state_wrap_transition(scheduler.ticks)
        result = cadence_candidate_result(
            period_seconds=period_seconds,
            scheduler=scheduler_report,
            phase_mapping_pass=phase_mapping_pass,
            no_op_pass=no_op_resolution.is_no_op,
            resolved_state_wrap_transition=state_wrap_transition,
            clean_stop_pass=not scheduler.active,
            performance_samples=tuple(performance_samples),
        )
        self._report_streamlines_cadence(
            event="PROGRESS",
            message=self._format_streamlines_cadence_candidate(result),
            status_callback=status_callback,
        )
        return result

    async def _await_streamlines_cadence_duration(
        self,
        *,
        scheduler: CachedPlaybackScheduler,
        duration_seconds: float,
        ordinal: int,
        candidate_count: int,
        period_seconds: float,
        started_at: float,
        status_callback: StatusCallback | None,
    ) -> None:
        """Wait for a full loop while emitting bounded diagnostic heartbeats."""

        candidate_started_at = time.monotonic()
        deadline = candidate_started_at + duration_seconds
        next_heartbeat = candidate_started_at + 5.0
        while time.monotonic() < deadline:
            await asyncio.sleep(min(1.0, deadline - time.monotonic()))
            now = time.monotonic()
            if now < next_heartbeat:
                continue
            report = scheduler.report()
            self._report_streamlines_cadence(
                event="WAITING",
                message=(
                    "Cadence candidate "
                    f"{ordinal}/{candidate_count} "
                    f"period_ms={period_seconds * 1000.0:.0f}; "
                    f"ticks={report.tick_count}; "
                    f"elapsed_s={now - started_at:.1f}."
                ),
                status_callback=status_callback,
            )
            next_heartbeat += 5.0

    def _report_streamlines_cached_playback(
        self,
        *,
        event: str,
        message: str,
        status_callback: StatusCallback | None,
    ) -> None:
        """Publish production scheduler lifecycle without per-tick log noise."""

        self._report_streamlines_event(
            area="CACHED_PLAYBACK",
            event=event,
            message=message,
            status_callback=status_callback,
        )

    def _report_streamlines_cadence(
        self,
        *,
        event: str,
        message: str,
        status_callback: StatusCallback | None,
    ) -> None:
        """Publish every manual characterization state to OmniUI and Kit logs."""

        self._report_streamlines_event(
            area="CADENCE_CHARACTERIZATION",
            event=event,
            message=message,
            status_callback=status_callback,
        )

    def _report_streamlines_event(
        self,
        *,
        area: str,
        event: str,
        message: str,
        status_callback: StatusCallback | None,
    ) -> None:
        """Keep Streamlines workflow states authoritative and structured."""

        if status_callback:
            status_callback(message)
        carb = self._streamlines_carb_logger()
        if not carb:
            return
        log = carb.log_error if event == "FAIL" else carb.log_warn
        log(
            with_dtrs_yerevan_timestamp(
                f"DTRS STREAMLINES | {area} | {event}\nstatus={message}"
            )
        )

    @staticmethod
    def _format_streamlines_cadence_candidate(
        result: CadenceCandidateResult,
    ) -> str:
        """Summarise one candidate without exposing a tick-by-tick log stream."""

        scheduler = result.scheduler
        fps_minimum = (
            "unavailable" if result.fps_minimum is None else f"{result.fps_minimum:.1f}"
        )
        gpu_growth = (
            "unavailable"
            if result.gpu_memory_growth_gib is None
            else f"{result.gpu_memory_growth_gib:.3f}"
        )
        process_growth = (
            "unavailable"
            if result.process_memory_growth_gib is None
            else f"{result.process_memory_growth_gib:.3f}"
        )
        state_wrap_transition = (
            "not_observed"
            if result.state_wrap_transition is None
            else (
                f"{result.state_wrap_transition[0]}"
                f"->{result.state_wrap_transition[1]}"
            )
        )
        return (
            f"Cadence period_ms={result.period_seconds * 1000.0:.0f}; "
            f"ticks={scheduler.tick_count}; switches={scheduler.switch_count}; "
            f"no_ops={scheduler.no_op_count}; "
            f"median_switch_ms={scheduler.median_switch_latency_seconds * 1000.0:.1f}; "
            f"max_switch_ms={scheduler.maximum_switch_latency_seconds * 1000.0:.1f}; "
            f"missed_deadlines={scheduler.missed_deadlines}; "
            f"max_drift_ms={scheduler.maximum_drift_seconds * 1000.0:.1f}; "
            f"backlog={scheduler.backlog_count}; "
            f"phase_mapping_pass={result.phase_mapping_pass}; "
            f"no_op_pass={result.no_op_pass}; "
            f"loop_wrap_pass={result.loop_wrap_pass}; "
            f"state_wrap_transition={state_wrap_transition}; "
            f"clean_stop_pass={result.clean_stop_pass}; "
            f"fps_minimum={fps_minimum}; "
            f"gpu_memory_growth_gib={gpu_growth}; "
            f"process_memory_growth_gib={process_growth}; "
            f"kit_cae_executions={result.kit_cae_executions}; "
            f"runtime_preview_rebuilds={result.runtime_preview_rebuilds}; "
            f"playback_vti_imports={result.playback_vti_imports}; "
            f"acceptable={result.acceptable}."
        )
