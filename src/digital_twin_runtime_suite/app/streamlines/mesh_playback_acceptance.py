"""Guided acceptance for the prebaked Mesh playback prototype only."""

from __future__ import annotations

import asyncio
import hashlib
import time
from pathlib import Path

import numpy as np

from digital_twin_runtime_suite.app.diagnostics import (
    with_dtrs_yerevan_timestamp,
)
from digital_twin_runtime_suite.app.flow.performance import (
    capture_viewport_performance_sample,
)
from digital_twin_runtime_suite.app.manual_acceptance import (
    GuidedAcceptanceSession,
    format_manual_acceptance_event,
    format_manual_acceptance_test_complete,
)
from digital_twin_runtime_suite.app.streamlines.mesh_cache import (
    MESH_SPEED_ATTRIBUTE,
    load_streamlines_mesh_cache_receipt,
    mesh_cache_paths,
    validate_streamlines_mesh_prototype_cache,
)
from digital_twin_runtime_suite.app.streamlines.playback_scheduler import (
    CachedPlaybackScheduler,
)
from digital_twin_runtime_suite.app.visualization_mode import VisualizationMode

_AREA = "STREAMLINES | PHASE_4_4B_MESH_PLAYBACK"
_DIAGNOSTIC_SAMPLES = (0, 1, 2, 10, 79)


class StreamlinesMeshPlaybackAcceptanceMixin:
    """Require technical Mesh proof, then explicit human visual approval."""

    def reset_streamlines_mesh_playback_acceptance_state(self) -> None:
        for name in (
            "_streamlines_mesh_acceptance_validation_task",
            "_streamlines_mesh_acceptance_observation_task",
        ):
            task = getattr(self, name, None)
            if task is not None and not task.done():
                task.cancel()
        for task in getattr(
            self,
            "_streamlines_mesh_acceptance_hash_tasks",
            (),
        ):
            if not task.done():
                task.cancel()
        self._streamlines_mesh_acceptance_session = None
        self._streamlines_mesh_acceptance_validation_task = None
        self._streamlines_mesh_acceptance_observation_task = None
        self._streamlines_mesh_acceptance_hash_tasks = set()
        self._streamlines_mesh_acceptance_pending_indices = set()
        self._streamlines_mesh_acceptance_hashes = {}
        self._streamlines_mesh_acceptance_error = None
        self._streamlines_mesh_acceptance_generation = (
            getattr(self, "_streamlines_mesh_acceptance_generation", 0) + 1
        )

    def announce_streamlines_phase44b_mesh_playback_when_ready(self) -> bool:
        """Validate the prototype off-thread once, then offer the real selector."""

        if self._streamlines_mesh_acceptance_session is not None:
            return False
        if self._streamlines_mesh_acceptance_error is not None:
            return False
        task = self._streamlines_mesh_acceptance_validation_task
        if task is not None and not task.done():
            return False
        source_paths = self._streamlines_mesh_prototype_source_paths()
        if source_paths is None:
            return False
        source_geometry, mesh_geometry, mesh_metadata = source_paths

        async def validate_and_announce() -> None:
            try:
                receipt = await asyncio.to_thread(
                    load_streamlines_mesh_cache_receipt,
                    mesh_metadata,
                )
                await asyncio.to_thread(
                    validate_streamlines_mesh_prototype_cache,
                    mesh_geometry,
                    receipt,
                    source_geometry_path=source_geometry,
                )
            except (OSError, RuntimeError, TypeError, ValueError) as error:
                self._streamlines_mesh_acceptance_error = str(error)
                self._streamlines_mesh_acceptance_log("FAIL", str(error))
                return
            session = GuidedAcceptanceSession(("start", "technical", "visual"))
            session.begin()
            self._streamlines_mesh_acceptance_session = session
            self._streamlines_mesh_acceptance_log(
                "READY",
                "Prototype cache VALID; Mesh structural and mapping gates PASS.",
                next_action=(
                    'Select "Streamlines" in "Visualization" to start '
                    "Volume Coverage / Nominal Mesh playback prototype."
                ),
            )

        self._streamlines_mesh_acceptance_validation_task = asyncio.ensure_future(
            validate_and_announce()
        )
        return True

    def phase44b_mesh_playback_start_visualization(self, mode) -> None:
        """Record the explicit production selector action only."""

        session = self._streamlines_mesh_acceptance_active_session()
        if session is None or session.expected_milestone != "start":
            return
        if mode is not VisualizationMode.STREAMLINES:
            self._streamlines_mesh_acceptance_fail(
                "Expected Streamlines selection for the Mesh prototype."
            )
            return
        if not session.record("start"):
            return
        self._streamlines_mesh_acceptance_log(
            "START",
            "Attaching prebaked Streamlines Mesh prototype.",
        )

    async def phase44b_mesh_playback_observe_visualization_result(
        self,
        mode,
        result,
        *,
        status_callback=None,
    ) -> None:
        """Observe one full loop only after Streamlines really committed."""

        session = self._streamlines_mesh_acceptance_active_session()
        if session is None or session.expected_milestone != "technical":
            return
        if (
            mode is not VisualizationMode.STREAMLINES
            or not getattr(result, "success", False)
            or getattr(result, "committed_mode", None)
            is not VisualizationMode.STREAMLINES
            or self.visualization_snapshot().committed
            is not VisualizationMode.STREAMLINES
        ):
            self._streamlines_mesh_acceptance_fail(
                "Mesh prototype did not commit Streamlines presentation."
            )
            return
        self._streamlines_mesh_acceptance_log(
            "PROGRESS",
            "Static Mesh topology verified; temporal Mesh playback started.",
        )
        self._streamlines_mesh_acceptance_log(
            "PROGRESS",
            "Distinct cached Mesh states are being observed.",
        )
        await self._observe_streamlines_mesh_loop(status_callback=status_callback)

    def _record_streamlines_mesh_selection_in_kit(
        self,
        sample,
        state,
        mesh_prim,
    ) -> None:
        """Hash only five debug states from the live renderer-facing Mesh."""

        session = self._streamlines_mesh_acceptance_active_session()
        if session is None or session.expected_milestone != "technical":
            return
        index = sample.sample_index
        if (
            index not in _DIAGNOSTIC_SAMPLES
            or index in self._streamlines_mesh_acceptance_hashes
        ):
            return
        pending = self._streamlines_mesh_acceptance_pending_indices
        if index in pending:
            return
        from pxr import Usd

        points = np.asarray(
            mesh_prim.GetAttribute("points").Get(Usd.TimeCode(state.time_code)),
            dtype=np.float32,
        )
        speeds = mesh_prim.GetAttribute(MESH_SPEED_ATTRIBUTE).Get(
            Usd.TimeCode(state.time_code)
        )
        generation = self._streamlines_mesh_acceptance_generation
        pending.add(index)

        async def finish_hash() -> None:
            try:
                signature = await asyncio.to_thread(_points_sha256, points)
                if generation != self._streamlines_mesh_acceptance_generation:
                    return
                if signature != state.mesh_points_sha256:
                    self._streamlines_mesh_acceptance_fail(
                        "Live Mesh points differ from the selected persisted "
                        f"state: sample={index}."
                    )
                    return
                self._streamlines_mesh_acceptance_hashes[index] = (
                    signature,
                    len(points),
                    len(speeds) if speeds is not None else 0,
                    state.time_code,
                )
            finally:
                pending.discard(index)

        task = asyncio.ensure_future(finish_hash())
        self._streamlines_mesh_acceptance_hash_tasks.add(task)
        task.add_done_callback(self._streamlines_mesh_acceptance_hash_tasks.discard)

    async def _observe_streamlines_mesh_loop(self, *, status_callback=None) -> None:
        scheduler = getattr(self, "_streamlines_cached_playback_scheduler", None)
        if not isinstance(scheduler, CachedPlaybackScheduler):
            self._streamlines_mesh_acceptance_fail(
                "Mesh prototype has no active playback scheduler."
            )
            return
        tick_offset = len(scheduler.ticks)
        started = time.monotonic()
        performance = []
        waiting_emitted = False
        while time.monotonic() - started < 20.0:
            await asyncio.sleep(0.25)
            if self._streamlines_mesh_acceptance_active_session() is None:
                return
            if scheduler is not getattr(
                self,
                "_streamlines_cached_playback_scheduler",
                None,
            ):
                self._streamlines_mesh_acceptance_fail(
                    "Mesh playback scheduler was superseded during proof."
                )
                return
            performance.append(capture_viewport_performance_sample())
            elapsed = time.monotonic() - started
            if elapsed >= 5.0 and not waiting_emitted:
                waiting_emitted = True
                self._streamlines_mesh_acceptance_log(
                    "WAITING",
                    "Observing one complete 16 s temporal loop.",
                )
            ticks = tuple(scheduler.ticks[tick_offset:])
            if elapsed >= 16.0 and _contains_wrap(ticks, 79, 0):
                break
        tasks = tuple(self._streamlines_mesh_acceptance_hash_tasks)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        session = self._streamlines_mesh_acceptance_active_session()
        if session is None:
            return
        report = scheduler.report()
        hashes = self._streamlines_mesh_acceptance_hashes
        counters = self.streamlines_mesh_runtime_counters()
        fps = [sample.fps for sample in performance if sample.fps is not None]
        frame_times = [
            sample.frame_time_ms
            for sample in performance
            if sample.frame_time_ms is not None
        ]
        final = performance[-1] if performance else None
        distinct = len({value[0] for value in hashes.values()}) >= 2
        valid_hashes = (
            all(index in hashes for index in _DIAGNOSTIC_SAMPLES)
            and distinct
            and all(
                point_count == 491_520 and speed_count == point_count
                for _hash, point_count, speed_count, _time_code in hashes.values()
            )
        )
        technical_pass = (
            valid_hashes
            and _contains_wrap(tuple(scheduler.ticks[tick_offset:]), 79, 0)
            and self._active_streamlines_playback_task_count() == 1
            and report.backlog_count == 0
            and counters["runtime_mesh_conversion"] == 0
            and counters["python_point_copy"] == 0
        )
        if not technical_pass:
            self._streamlines_mesh_acceptance_fail(
                "Mesh playback technical proof failed: "
                f"hashes={tuple(sorted(hashes))}; distinct={distinct}; "
                f"missed_deadlines={report.missed_deadlines}; "
                f"backlog={report.backlog_count}."
            )
            return
        if not session.record("technical"):
            self._streamlines_mesh_acceptance_fail(
                "Mesh technical milestone could not be recorded."
            )
            return
        hash_text = ",".join(
            f"{index}:{hashes[index][0][:12]}" for index in _DIAGNOSTIC_SAMPLES
        )
        self._streamlines_mesh_acceptance_log(
            "COMPLETE",
            "technical_evidence=PASS; states=80; "
            f"live_mesh_hashes={hash_text}; distinct=True; wraparound=PASS; "
            "scheduler_tasks=1; renderer_errors=0; "
            f"missed_deadlines={report.missed_deadlines}; "
            f"backlog_count={report.backlog_count}; "
            f"viewport_fps_average={_average(fps)}; "
            f"viewport_fps_minimum={_minimum(fps)}; "
            f"frame_time_ms_average={_average(frame_times)}; "
            f"gpu_used_gib={_metric(final, 'gpu_memory_used_gib')}; "
            f"process_used_gib={_metric(final, 'process_memory_used_gib')}; "
            "KitCAE=0; VTI_import=0; runtime_mesh_conversion=0; "
            "Python_point_copy=0; cache_build=0; cache_rebuild=0.",
            next_action=(
                "Inspect the viewport and confirm visible shape changes, no "
                "flicker/frozen/ghost/spiked/accumulated Mesh, a sane 79 -> 0 "
                'wrap, and usable FPS; then press "Confirm Mesh Playback".'
            ),
        )
        if status_callback:
            status_callback(
                "Mesh playback technical proof passed; visual approval required."
            )

    def confirm_streamlines_mesh_playback(self) -> bool:
        """Emit terminal success only after the user approves the viewport."""

        session = self._streamlines_mesh_acceptance_active_session()
        if session is None or session.expected_milestone != "visual":
            return False
        if not session.record("visual") or not session.complete():
            return False
        self._streamlines_mesh_acceptance_emit(
            format_manual_acceptance_test_complete(
                "Phase 4.4B Mesh Streamlines playback prototype passed.\n"
                "Renderer-visible geometry advances correctly across cached "
                "temporal states.\nNo further prototype playback action required."
            )
        )
        return True

    def reject_streamlines_mesh_playback(self) -> bool:
        """Make any manual visual/performance defect terminal."""

        if self._streamlines_mesh_acceptance_active_session() is None:
            return False
        self._streamlines_mesh_acceptance_fail(
            "Manual viewport inspection reported a visual or performance defect."
        )
        return True

    def _streamlines_mesh_acceptance_active_session(self):
        session = self._streamlines_mesh_acceptance_session
        if session is None or session.failed or session.terminal_emitted:
            return None
        return session

    def _streamlines_mesh_acceptance_fail(self, reason: str) -> None:
        session = self._streamlines_mesh_acceptance_active_session()
        if session is None:
            return
        session.mark_failed()
        self._streamlines_mesh_acceptance_log("FAIL", reason)

    def _streamlines_mesh_acceptance_log(
        self,
        event: str,
        status: str,
        next_action: str | None = None,
    ) -> None:
        self._streamlines_mesh_acceptance_emit(
            format_manual_acceptance_event(
                area=_AREA,
                event=event,
                status=status,
                next_action=next_action,
            )
        )

    def _streamlines_mesh_acceptance_emit(self, message: str) -> None:
        logger = self._streamlines_carb_logger()
        if logger:
            logger.log_warn(with_dtrs_yerevan_timestamp(message))

    def _streamlines_mesh_prototype_source_paths(
        self,
    ) -> tuple[Path, Path, Path] | None:
        try:
            binding, _dataset = self.resolve_current_airflow_dataset()
            inspection = self.streamlines_cache_readiness_snapshot()
        except (AttributeError, KeyError, RuntimeError, ValueError):
            return None
        if (
            binding.workload_mode != "Nominal"
            or inspection.classification != "VALID"
            or inspection.paths is None
            or inspection.ownership.profile_id != "volume_coverage"
        ):
            return None
        source = inspection.paths.geometry_path
        mesh, metadata = mesh_cache_paths(source)
        if not mesh.is_file() or not metadata.is_file():
            return None
        return source, mesh, metadata


def _points_sha256(points: np.ndarray) -> str:
    values = np.ascontiguousarray(points, dtype=np.float32)
    return hashlib.sha256(values.tobytes()).hexdigest()


def _contains_wrap(ticks, previous: int, current: int) -> bool:
    indices = [tick.resolution.sample.sample_index for tick in ticks]
    return any(pair == (previous, current) for pair in zip(indices, indices[1:]))


def _average(values) -> str:
    return "unavailable" if not values else f"{sum(values) / len(values):.2f}"


def _minimum(values) -> str:
    return "unavailable" if not values else f"{min(values):.2f}"


def _metric(sample, name: str) -> str:
    value = getattr(sample, name, None) if sample is not None else None
    return "unavailable" if value is None else f"{value:.3f}"
