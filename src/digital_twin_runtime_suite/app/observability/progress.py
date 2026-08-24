# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""Pure contracts for mutable operation state and durable observability events."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Mapping


class EventKind(str, Enum):
    """Name a durable operation boundary rather than a changing percentage."""

    READY = "READY"
    START = "START"
    ITEM_START = "ITEM_START"
    ITEM_COMPLETE = "ITEM_COMPLETE"
    PROGRESS = "PROGRESS"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"
    WARNING = "WARNING"
    FAIL = "FAIL"
    TEST_COMPLETE = "TEST COMPLETE"


class EventSeverity(str, Enum):
    """Keep routine milestones distinct from unusual and failed conditions."""

    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


@dataclass(frozen=True)
class ProgressState:
    """One replaceable current-state snapshot for a long-running operation."""

    operation_id: str
    phase: str
    message: str = ""
    fraction: float | None = None
    current: int | None = None
    total: int | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Reject impossible generic accounting while preserving domain metadata."""

        if self.fraction is not None and not 0.0 <= self.fraction <= 1.0:
            raise ValueError("Progress fraction must be between zero and one.")
        if self.current is not None and self.current < 0:
            raise ValueError("Progress current value cannot be negative.")
        if self.total is not None and self.total < 0:
            raise ValueError("Progress total value cannot be negative.")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True)
class DurableEvent:
    """One historical operation boundary with semantic severity."""

    operation_id: str
    kind: EventKind
    message: str = ""
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Freeze details so a logged event cannot mutate after publication."""

        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    @property
    def severity(self) -> EventSeverity:
        """Map only unusual or failed events above normal informational severity."""

        if self.kind is EventKind.FAIL:
            return EventSeverity.ERROR
        if self.kind is EventKind.WARNING:
            return EventSeverity.WARNING
        return EventSeverity.INFO
