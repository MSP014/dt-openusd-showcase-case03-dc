"""Shared viewport-performance measurements for DTRS X-Ray features.

Owns only generic sampling and aggregation of Kit viewport statistics. This
module has no material, Session Layer, camera, or geometry ownership.
"""

from __future__ import annotations

from digital_twin_runtime_suite.app.flow.performance import (
    ViewportPerformanceSample,
)
from digital_twin_runtime_suite.app.flow.performance import (
    capture_viewport_performance_sample as _capture_viewport_performance_sample,
)


def capture_viewport_performance_sample() -> ViewportPerformanceSample:
    """Capture one non-fatal HUD sample through the established Kit reader."""

    return _capture_viewport_performance_sample()


def viewport_performance_state(
    samples: list[ViewportPerformanceSample],
) -> dict[str, str]:
    """Return formatted generic FPS, frame-time, and memory summary values."""

    latest = samples[-1] if samples else None
    fps_values = [sample.fps for sample in samples if sample.fps is not None]
    frame_times = [
        sample.frame_time_ms for sample in samples if sample.frame_time_ms is not None
    ]

    def average(values):
        return sum(values) / len(values) if values else None

    def formatted(value):
        return f"{value:.2f}" if value is not None else "<unavailable>"

    return {
        "fps_current": formatted(latest.fps if latest else None),
        "frame_time_ms_current": formatted(latest.frame_time_ms if latest else None),
        "average_fps": formatted(average(fps_values)),
        "minimum_fps": formatted(min(fps_values) if fps_values else None),
        "maximum_fps": formatted(max(fps_values) if fps_values else None),
        "average_frame_time_ms": formatted(average(frame_times)),
        "gpu_used_gib": formatted(latest.gpu_memory_used_gib if latest else None),
        "process_used_gib": formatted(
            latest.process_memory_used_gib if latest else None
        ),
    }
