"""Flow viewport-performance data contracts and pure aggregation helpers."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class FlowPerformanceSample:
    """One Stage 6 observation from Kit's built-in viewport statistics."""

    captured_at: float
    fps: float | None
    frame_time_ms: float | None
    gpu_memory_used_gib: float | None
    process_memory_used_gib: float | None
    temporal_source: str | None


def format_flow_performance_value(
    value: float | None,
    *,
    suffix: str = "",
) -> str:
    """Format optional Stage 6 performance values without inventing data."""

    return "unavailable" if value is None else f"{value:.1f}{suffix}"


def flow_performance_statistics(
    samples: list[FlowPerformanceSample],
) -> dict[str, float | None]:
    """Reduce viewport observations for a log interval or Attach lifetime."""

    fps_values = [sample.fps for sample in samples if sample.fps is not None]
    frame_times = [
        sample.frame_time_ms for sample in samples if sample.frame_time_ms is not None
    ]
    return {
        "fps_average": sum(fps_values) / len(fps_values) if fps_values else None,
        "fps_minimum": min(fps_values) if fps_values else None,
        "fps_maximum": max(fps_values) if fps_values else None,
        "frame_time_average": (
            sum(frame_times) / len(frame_times) if frame_times else None
        ),
    }


class FlowPerformanceMixin:
    """Own Flow viewport sampling and periodic performance reporting."""

    @staticmethod
    def _format_flow_performance_value(
        value: float | None,
        *,
        suffix: str = "",
    ) -> str:
        """Format optional Stage 6 performance values without inventing data."""

        return "unavailable" if value is None else f"{value:.1f}{suffix}"

    @staticmethod
    def _flow_performance_statistics(
        samples: list[FlowPerformanceSample],
    ) -> dict[str, float | None]:
        """Reduce viewport observations for a log interval or Attach lifetime."""

        fps_values = [sample.fps for sample in samples if sample.fps is not None]
        frame_times = [
            sample.frame_time_ms
            for sample in samples
            if sample.frame_time_ms is not None
        ]
        return {
            "fps_average": sum(fps_values) / len(fps_values) if fps_values else None,
            "fps_minimum": min(fps_values) if fps_values else None,
            "fps_maximum": max(fps_values) if fps_values else None,
            "frame_time_average": (
                sum(frame_times) / len(frame_times) if frame_times else None
            ),
        }

    def _capture_flow_performance_sample(self) -> FlowPerformanceSample:
        """Read the same viewport FPS and memory sources used by Kit's HUD."""

        captured_at = time.monotonic()
        fps = None
        frame_time_ms = None
        gpu_memory_used_gib = None
        process_memory_used_gib = None
        try:
            import omni.hydra.engine.stats as engine_stats
            import omni.kit.viewport.utility as viewport_utility
            from omni.gpu_foundation_factory import get_memory_info

            viewport = viewport_utility.get_active_viewport()
            frame_info = viewport.frame_info if viewport else {}
            if viewport:
                subframe_count = frame_info.get("subframe_count", 1) or 1
                effective_fps = float(viewport.fps) * float(subframe_count)
                if effective_fps > 0.0:
                    fps = effective_fps
                    frame_time_ms = 1000.0 / effective_fps

            device_mask = frame_info.get("device_mask")
            device_info = engine_stats.get_device_info()
            enabled_devices = [
                device
                for index, device in enumerate(device_info)
                if device_mask is None or device_mask & (1 << index)
            ]
            selected_device = (enabled_devices or device_info or [None])[0]
            if selected_device:
                gpu_memory_used_gib = float(selected_device["usage"]) / (1024**3)

            host_info = get_memory_info(rss=True)
            process_memory_used_gib = float(host_info["rss_memory"]) / (1024**3)
        except Exception:
            # Performance instrumentation must never make Flow Attach fail.
            fps = frame_time_ms = gpu_memory_used_gib = process_memory_used_gib = None

        return FlowPerformanceSample(
            captured_at=captured_at,
            fps=fps,
            frame_time_ms=frame_time_ms,
            gpu_memory_used_gib=gpu_memory_used_gib,
            process_memory_used_gib=process_memory_used_gib,
            temporal_source=self._kit_cae_current_temporal_source_name(),
        )

    def _kit_cae_current_temporal_source_name(self) -> str | None:
        """Read the composed source active at the current Kit timeline time."""

        if not self._flow_airflow_simulate_path:
            return None
        try:
            import omni.timeline
            import omni.usd
            from omni.cae.schema import vtk as cae_vtk
            from pxr import Usd

            stage = omni.usd.get_context().get_stage()
            if not stage:
                return None
            field_path = (
                "/DTRS_HoudiniVelocity/PointData/"
                f"{self.config.simulation_cache.velocity_field_name}"
            )
            field_prim = stage.GetPrimAtPath(field_path)
            if not field_prim or not field_prim.IsValid():
                return None
            timeline_seconds = float(
                omni.timeline.get_timeline_interface().get_current_time()
            )
            asset = self._kit_cae_selected_velocity_asset(
                field_prim,
                timeline_seconds * float(stage.GetTimeCodesPerSecond()),
                cae_vtk,
                Usd,
            )
            return asset.name if asset else None
        except Exception:
            # The temporal source is evidence only; an unavailable read is non-fatal.
            return None

    def _log_flow_performance_event(
        self,
        carb,
        *,
        event: str,
        sample: FlowPerformanceSample,
    ) -> None:
        """Record the baseline or settled Flow performance from Kit's HUD data."""

        fields = [
            ("Event:", event),
            ("FPS:", self._format_flow_performance_value(sample.fps)),
            (
                "Frame time:",
                self._format_flow_performance_value(
                    sample.frame_time_ms,
                    suffix=" ms",
                ),
            ),
        ]
        if event == "FLOW_ATTACHED":
            fields.extend(
                (
                    (
                        "GPU memory used:",
                        self._format_flow_performance_value(
                            sample.gpu_memory_used_gib,
                            suffix=" GiB",
                        ),
                    ),
                    (
                        "Process memory:",
                        self._format_flow_performance_value(
                            sample.process_memory_used_gib,
                            suffix=" GiB",
                        ),
                    ),
                    ("Temporal source:", sample.temporal_source or "unavailable"),
                    ("Camera bookmark:", self._flow_performance_camera_bookmark),
                    ("Flow attached:", True),
                )
            )
        carb.log_warn(
            self._format_flow_log_block("PERFORMANCE", (("", tuple(fields)),))
        )

    def _start_flow_performance_sampler(self) -> None:
        """Start one low-frequency Stage 6 sampler after Flow is live and settled."""

        self._stop_flow_performance_sampler()
        self._flow_performance_session_id += 1
        session_id = self._flow_performance_session_id
        self._flow_performance_attached_at = time.monotonic()
        initial_sample = self._capture_flow_performance_sample()
        self._flow_performance_samples = [initial_sample]

        import carb

        self._log_flow_performance_event(
            carb,
            event="FLOW_ATTACHED",
            sample=initial_sample,
        )
        self._flow_performance_task = asyncio.ensure_future(
            self._run_flow_performance_sampler(session_id)
        )

    def set_flow_performance_camera_bookmark(self, name: str) -> None:
        """Label future Flow performance intervals with the active fixed camera."""

        self._flow_performance_camera_bookmark = name

    def _stop_flow_performance_sampler(self) -> None:
        """Cancel a prior Stage 6 sampler before reload, detach, or reattach."""

        self._flow_performance_session_id += 1
        task = self._flow_performance_task
        self._flow_performance_task = None
        if task and not task.done():
            task.cancel()

    async def _run_flow_performance_sampler(self, session_id: int) -> None:
        """Collect HUD observations at low frequency and log thirty-second intervals."""

        import carb

        attached_at = self._flow_performance_attached_at
        if attached_at is None:
            return
        next_log_at = attached_at + self.FLOW_PERFORMANCE_LOG_INTERVAL_SECONDS
        interval_start = attached_at
        try:
            while (
                session_id == self._flow_performance_session_id
                and self._flow_lifecycle_state == "ATTACHED"
                and self._flow_airflow_simulate_path
            ):
                await asyncio.sleep(self.FLOW_PERFORMANCE_SAMPLE_INTERVAL_SECONDS)
                if session_id != self._flow_performance_session_id:
                    return
                sample = self._capture_flow_performance_sample()
                self._flow_performance_samples.append(sample)
                if sample.captured_at >= next_log_at:
                    interval_samples = [
                        item
                        for item in self._flow_performance_samples
                        if item.captured_at >= interval_start
                    ]
                    self._log_flow_performance_interval(carb, interval_samples)
                    interval_start = sample.captured_at
                    next_log_at = (
                        sample.captured_at + self.FLOW_PERFORMANCE_LOG_INTERVAL_SECONDS
                    )
        except asyncio.CancelledError:
            return

    def _log_flow_performance_interval(
        self,
        carb,
        samples: list[FlowPerformanceSample],
    ) -> None:
        """Emit rolling ten-second Stage 6 evidence while Flow remains attached."""

        if not samples or self._flow_performance_attached_at is None:
            return
        latest_sample = samples[-1]
        statistics = self._flow_performance_statistics(samples)
        elapsed = latest_sample.captured_at - self._flow_performance_attached_at
        carb.log_warn(
            self._format_flow_log_block(
                "PERFORMANCE",
                (
                    (
                        "",
                        (("Elapsed since Attach:", f"{elapsed:.1f} s"),),
                    ),
                    (
                        "FPS",
                        (
                            (
                                "Average:",
                                self._format_flow_performance_value(
                                    statistics["fps_average"]
                                ),
                            ),
                            (
                                "Minimum:",
                                self._format_flow_performance_value(
                                    statistics["fps_minimum"]
                                ),
                            ),
                            (
                                "Maximum:",
                                self._format_flow_performance_value(
                                    statistics["fps_maximum"]
                                ),
                            ),
                        ),
                    ),
                    (
                        "Frame time",
                        (
                            (
                                "Average:",
                                self._format_flow_performance_value(
                                    statistics["frame_time_average"],
                                    suffix=" ms",
                                ),
                            ),
                        ),
                    ),
                    (
                        "Memory",
                        (
                            (
                                "GPU memory used:",
                                self._format_flow_performance_value(
                                    latest_sample.gpu_memory_used_gib,
                                    suffix=" GiB",
                                ),
                            ),
                            (
                                "Process memory:",
                                self._format_flow_performance_value(
                                    latest_sample.process_memory_used_gib,
                                    suffix=" GiB",
                                ),
                            ),
                        ),
                    ),
                    (
                        "Flow",
                        (
                            (
                                "Temporal source:",
                                latest_sample.temporal_source or "unavailable",
                            ),
                            (
                                "Camera bookmark:",
                                self._flow_performance_camera_bookmark,
                            ),
                            ("Flow attached:", bool(self._flow_airflow_simulate_path)),
                        ),
                    ),
                ),
            )
        )

    def _log_flow_performance_summary(self, carb) -> None:
        """Write the final Attach-lifetime result before clearing sampler state."""

        if (
            not self._flow_performance_samples
            or self._flow_performance_attached_at is None
        ):
            return
        statistics = self._flow_performance_statistics(self._flow_performance_samples)
        duration = time.monotonic() - self._flow_performance_attached_at
        gpu_samples = [
            sample.gpu_memory_used_gib
            for sample in self._flow_performance_samples
            if sample.gpu_memory_used_gib is not None
        ]
        flow_resets = sum(
            1 for record in self._flow_temporal_records if record["flow_reset"]
        )
        summary_fields = [
            ("Flow resets:", flow_resets),
        ]
        if gpu_samples:
            summary_fields.append(("Peak GPU memory:", f"{max(gpu_samples):.1f} GiB"))
        carb.log_warn(
            self._format_flow_log_block(
                "PERFORMANCE SUMMARY",
                (
                    (
                        "",
                        (("Attached duration:", f"{duration:.1f} s"),),
                    ),
                    (
                        "FPS",
                        (
                            (
                                "Average:",
                                self._format_flow_performance_value(
                                    statistics["fps_average"]
                                ),
                            ),
                            (
                                "Minimum:",
                                self._format_flow_performance_value(
                                    statistics["fps_minimum"]
                                ),
                            ),
                            (
                                "Maximum:",
                                self._format_flow_performance_value(
                                    statistics["fps_maximum"]
                                ),
                            ),
                        ),
                    ),
                    ("Flow", tuple(summary_fields)),
                ),
            )
        )
