"""Focused contracts for consumer-neutral airflow temporal truth."""

from __future__ import annotations

from pathlib import Path

import pytest

from digital_twin_runtime_suite.app.airflow_state.temporal import (
    TemporalSourceSample,
    normalize_airflow_phase,
    resolve_manifest_sample,
)


def test_resolves_latest_real_sample_at_phase_boundary() -> None:
    resolution = resolve_manifest_sample(
        _samples(),
        sample_interval_seconds=0.4,
        phase_seconds=0.8,
    )

    assert resolution.sample.sample_index == 2
    assert resolution.normalized_phase_seconds == pytest.approx(0.8)
    assert resolution.decision == "SELECT"


@pytest.mark.parametrize(
    ("phase_seconds", "expected_index"),
    ((0.0, 0), (0.399, 0), (0.401, 1), (1.6, 0), (-0.1, 3)),
)
def test_resolves_boundaries_and_loop_wrap(
    phase_seconds: float, expected_index: int
) -> None:
    resolution = resolve_manifest_sample(
        _samples(), sample_interval_seconds=0.4, phase_seconds=phase_seconds
    )

    assert resolution.sample.sample_index == expected_index


def test_same_resolved_sample_is_no_op() -> None:
    resolution = resolve_manifest_sample(
        _samples(),
        sample_interval_seconds=0.4,
        phase_seconds=0.79,
        active_sample_index=1,
    )

    assert resolution.is_no_op is True


@pytest.mark.parametrize("phase_seconds", (float("nan"), float("inf")))
def test_rejects_non_finite_phase(phase_seconds: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        normalize_airflow_phase(phase_seconds, loop_duration_seconds=1.6)


def test_rejects_invalid_manifest_shape() -> None:
    invalid = (_sample(0, 0.1),)

    with pytest.raises(ValueError, match="phase zero"):
        resolve_manifest_sample(invalid, sample_interval_seconds=0.4, phase_seconds=0.0)


def _samples() -> tuple[TemporalSourceSample, ...]:
    return tuple(_sample(index, index * 0.4) for index in range(4))


def _sample(index: int, source_time_seconds: float) -> TemporalSourceSample:
    return TemporalSourceSample(
        ordinal=index + 1,
        total=4,
        sample_index=index,
        source_vti=Path(f"sample_{index}.vti"),
        source_time_seconds=source_time_seconds,
        time_code=source_time_seconds,
    )
