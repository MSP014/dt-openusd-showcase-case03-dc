"""Seven-segment QLED display helpers for runtime telemetry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SEGMENTS = ("a", "b", "c", "d", "e", "f", "g")
DIGIT_SEGMENTS = {
    0: frozenset(("a", "b", "c", "d", "e", "f")),
    1: frozenset(("b", "c")),
    2: frozenset(("a", "b", "d", "e", "g")),
    3: frozenset(("a", "b", "c", "d", "g")),
    4: frozenset(("b", "c", "f", "g")),
    5: frozenset(("a", "c", "d", "f", "g")),
    6: frozenset(("a", "c", "d", "e", "f", "g")),
    7: frozenset(("a", "b", "c")),
    8: frozenset(("a", "b", "c", "d", "e", "f", "g")),
    9: frozenset(("a", "b", "c", "d", "f", "g")),
}
DisplayMode = Literal["normal", "warning"]


@dataclass(frozen=True)
class QledDisplayState:
    """Resolved two-digit seven-segment display state."""

    value: int
    tens: int
    units: int
    mode: DisplayMode
    active_segments: dict[str, frozenset[str]]


def qled_state_from_temperature(
    temperature_c: float,
    *,
    warning_threshold_c: float = 100.0,
    minimum_value: int = 0,
    maximum_value: int = 99,
) -> QledDisplayState:
    """Convert a CPU temperature into a two-digit QLED segment state."""

    rounded = int(round(float(temperature_c)))
    warning = float(temperature_c) >= warning_threshold_c
    value = max(minimum_value, min(maximum_value, rounded))
    if warning:
        value = maximum_value

    tens = value // 10
    units = value % 10
    return QledDisplayState(
        value=value,
        tens=tens,
        units=units,
        mode="warning" if warning else "normal",
        active_segments={
            "tens": DIGIT_SEGMENTS[tens],
            "units": DIGIT_SEGMENTS[units],
        },
    )
