"""Focused raw-speed persistence contracts for cached Streamlines geometry."""

from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from digital_twin_runtime_suite.app.streamlines.cache_runtime import (
    _author_persisted_speed_sample,
    _validate_persisted_speed_primvar,
)
from digital_twin_runtime_suite.app.streamlines.profile import (
    PRODUCTION_STREAMLINES_PROFILE,
)
from digital_twin_runtime_suite.app.streamlines.speed import (
    SPEED_PRIMVAR_ATTRIBUTE,
    speed_magnitudes_from_velocity_vectors,
    validate_persisted_speed_magnitudes,
)


def test_raw_speed_matches_each_generated_source_velocity_vector() -> None:
    speeds = speed_magnitudes_from_velocity_vectors(
        ((3.0, 4.0, 0.0), (0.0, 0.0, 0.0), (-2.0, 0.0, 0.0)),
        expected_point_count=3,
    )

    assert speeds == (5.0, 0.0, 2.0)
    assert (
        SPEED_PRIMVAR_ATTRIBUTE in PRODUCTION_STREAMLINES_PROFILE.persisted_attributes
    )


@pytest.mark.parametrize(
    ("vectors", "expected_count", "message"),
    (
        (((1.0, 0.0, 0.0),), 2, "count"),
        (((1.0, 0.0),), 1, "invalid"),
        (((math.nan, 0.0, 0.0),), 1, "invalid"),
        (((math.inf, 0.0, 0.0),), 1, "invalid"),
    ),
)
def test_raw_speed_rejects_invalid_source_velocity_probe(
    vectors,
    expected_count: int,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        speed_magnitudes_from_velocity_vectors(
            vectors,
            expected_point_count=expected_count,
        )


@pytest.mark.parametrize(
    "values",
    (
        (1.0,),
        (1.0, math.nan),
        (1.0, -0.1),
    ),
)
def test_persisted_raw_speed_rejects_missing_or_invalid_vertex_values(values) -> None:
    with pytest.raises(ValueError):
        validate_persisted_speed_magnitudes(values, expected_point_count=2)


def test_cache_authors_vertex_speed_and_revalidates_each_time_sample() -> None:
    primvar = _Primvar()
    speed_values = _author_persisted_speed_sample(
        primvar,
        (5.0, 0.0, 2.0),
        expected_point_count=3,
        time_code=12.0,
    )
    attribute = _Attribute({0.0: (1.0, 2.0), 12.0: speed_values})

    _validate_persisted_speed_primvar(
        attribute,
        expected_time_codes=(0.0, 12.0),
        expected_point_counts=(2, 3),
        Usd=SimpleNamespace(TimeCode=float),
    )

    assert primvar.interpolation == "vertex"
    assert primvar.authored == [(12.0, [5.0, 0.0, 2.0])]


def test_cache_rejects_speed_time_or_vertex_count_mismatch() -> None:
    attribute = _Attribute({0.0: (1.0, 2.0)})

    with pytest.raises(RuntimeError, match="time samples"):
        _validate_persisted_speed_primvar(
            attribute,
            expected_time_codes=(0.0, 12.0),
            expected_point_counts=(2, 2),
            Usd=SimpleNamespace(TimeCode=float),
        )

    with pytest.raises(RuntimeError, match="point count"):
        _validate_persisted_speed_primvar(
            attribute,
            expected_time_codes=(0.0,),
            expected_point_counts=(3,),
            Usd=SimpleNamespace(TimeCode=float),
        )


class _Primvar:
    interpolation = "vertex"

    def __init__(self) -> None:
        self.authored: list[tuple[float, list[float]]] = []

    def Set(self, values, time_code) -> None:
        self.authored.append((time_code, values))


class _Attribute:
    def __init__(self, values_by_time: dict[float, tuple[float, ...]]) -> None:
        self._values_by_time = values_by_time

    def IsValid(self) -> bool:
        return True

    def GetTimeSamples(self) -> tuple[float, ...]:
        return tuple(self._values_by_time)

    def Get(self, time_code: float) -> tuple[float, ...] | None:
        return self._values_by_time.get(time_code)
