"""Time-based Heatmap presentation smoothing coverage."""

from __future__ import annotations

import pytest

from digital_twin_runtime_suite.app.heatmaps.runtime import HeatmapRuntimeMixin
from digital_twin_runtime_suite.app.heatmaps.smoothing import (
    HEATMAP_PRESENTATION_CADENCE_HZ,
    HEATMAP_PRESENTATION_PERIOD_SECONDS,
    HeatmapPresentationSmoother,
)


def test_5hz_and_2hz_share_two_second_transition_and_same_target() -> None:
    assert HEATMAP_PRESENTATION_CADENCE_HZ == 2
    assert HEATMAP_PRESENTATION_PERIOD_SECONDS == 0.5

    smoother_5 = HeatmapPresentationSmoother()
    smoother_2 = HeatmapPresentationSmoother()
    smoother_5.reset({"group": 50.0}, now=0.0)
    smoother_2.reset({"group": 50.0}, now=0.0)
    smoother_5.set_targets({"group": 60.0}, now=0.0)
    smoother_2.set_targets({"group": 60.0}, now=0.0)

    five_hz_values = [smoother_5.tick(now=index / 5)["group"] for index in range(1, 11)]
    two_hz_values = [smoother_2.tick(now=index / 2)["group"] for index in range(1, 5)]

    assert five_hz_values == [
        51.0,
        52.0,
        53.0,
        54.0,
        55.0,
        56.0,
        57.0,
        58.0,
        59.0,
        60.0,
    ]
    assert two_hz_values == [52.5, 55.0, 57.5, 60.0]
    assert smoother_5.transition_duration_seconds == 2.0
    assert smoother_2.transition_duration_seconds == 2.0


def test_new_snapshot_restarts_from_current_displayed_value_without_queueing() -> None:
    smoother = HeatmapPresentationSmoother(transition_duration_seconds=2.0)
    smoother.reset({"group": 50.0}, now=0.0)
    assert smoother.set_targets({"group": 60.0}, now=0.0) == 1
    assert smoother.tick(now=0.5)["group"] == 52.5

    assert smoother.set_targets({"group": 70.0}, now=0.55) == 1
    assert smoother.tick(now=0.65)["group"] == 53.375
    assert smoother.tick(now=2.55)["group"] == 70.0
    evidence = smoother.retarget_evidence
    assert len(evidence) == 1
    assert evidence[0].displayed_before_celsius == 52.5
    assert evidence[0].first_displayed_after_celsius == 53.375
    assert evidence[0].continuous


def test_settled_or_unchanged_targets_emit_no_repeated_parameter_values() -> None:
    smoother = HeatmapPresentationSmoother()
    smoother.reset({"group": 50.0}, now=0.0)

    assert smoother.set_targets({"group": 50.0}, now=1.0) == 0
    assert not smoother.tick(now=1.0)
    assert not smoother.tick(now=2.0)


def test_runtime_keeps_the_fixed_two_hz_scheduler_contract() -> None:
    runtime = _SchedulerRuntime()

    runtime.set_heatmap_presentation_cadence_hz(2)

    assert runtime.cadence_hz == 2
    assert not runtime.tasks[0].cancelled
    assert runtime.scheduler_starts == 0
    with pytest.raises(ValueError, match="fixed at 2 Hz"):
        runtime.set_heatmap_presentation_cadence_hz(5)


class _Task:
    def __init__(self) -> None:
        self.cancelled = False

    def done(self) -> bool:
        return False

    def cancel(self) -> None:
        self.cancelled = True


class _SchedulerRuntime:
    set_heatmap_presentation_cadence_hz = (
        HeatmapRuntimeMixin.set_heatmap_presentation_cadence_hz
    )

    def __init__(self) -> None:
        self._heatmap_presentation_cadence_hz = 5
        self._heatmap_presentation_task = _Task()
        self._heatmap_presentation_scheduler_id = 0
        self.tasks = [self._heatmap_presentation_task]
        self.scheduler_starts = 0

    @property
    def cadence_hz(self) -> int:
        return self._heatmap_presentation_cadence_hz

    def _ensure_heatmap_presentation_scheduler(self) -> None:
        self.scheduler_starts += 1
        task = _Task()
        self._heatmap_presentation_task = task
        self.tasks.append(task)
