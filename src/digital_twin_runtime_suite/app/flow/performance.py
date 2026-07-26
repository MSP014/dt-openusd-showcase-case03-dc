"""Flow viewport-performance data contracts and pure aggregation helpers."""

from __future__ import annotations

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
