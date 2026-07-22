import pytest

from blackwell_monitoring_suite.app.qled import (
    DIGIT_SEGMENTS,
    qled_state_from_temperature,
)


def test_digit_segment_masks_cover_expected_seven_segment_shapes():
    assert DIGIT_SEGMENTS[0] == frozenset(("a", "b", "c", "d", "e", "f"))
    assert DIGIT_SEGMENTS[1] == frozenset(("b", "c"))
    assert DIGIT_SEGMENTS[8] == frozenset(("a", "b", "c", "d", "e", "f", "g"))


def test_qled_state_from_temperature_builds_tens_and_units_masks():
    state = qled_state_from_temperature(57.2)

    assert state.value == 57
    assert state.tens == 5
    assert state.units == 7
    assert state.mode == "normal"
    assert state.active_segments["tens"] == DIGIT_SEGMENTS[5]
    assert state.active_segments["units"] == DIGIT_SEGMENTS[7]


def test_qled_state_from_temperature_rounds_to_nearest_degree():
    assert qled_state_from_temperature(57.4).value == 57
    assert qled_state_from_temperature(57.6).value == 58


def test_qled_state_from_temperature_clamps_low_values():
    state = qled_state_from_temperature(-12.0)

    assert state.value == 0
    assert state.tens == 0
    assert state.units == 0


def test_qled_state_from_temperature_clamps_high_values_to_99():
    state = qled_state_from_temperature(123.0)

    assert state.value == 99
    assert state.tens == 9
    assert state.units == 9


def test_qled_state_from_temperature_switches_to_warning_at_threshold():
    assert qled_state_from_temperature(99.9).mode == "normal"
    warning = qled_state_from_temperature(100.0)

    assert warning.mode == "warning"
    assert warning.value == 99


def test_qled_state_from_temperature_honours_custom_threshold_and_range():
    state = qled_state_from_temperature(
        88.0,
        warning_threshold_c=90.0,
        minimum_value=10,
        maximum_value=80,
    )

    assert state.value == 80
    assert state.mode == "normal"


@pytest.mark.parametrize("value", range(10))
def test_all_qled_digit_masks_only_use_known_segments(value):
    assert DIGIT_SEGMENTS[value] <= frozenset(("a", "b", "c", "d", "e", "f", "g"))
