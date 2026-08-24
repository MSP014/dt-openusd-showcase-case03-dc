# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""Immutable progress snapshots for DTRS temporal VTI validation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TemporalProofState(str, Enum):
    """Lifecycle states exposed by the DTRS temporal validation UX."""

    IDLE = "IDLE"
    RUNNING = "RUNNING"
    CHECKING_LOOP_CLOSURE = "CHECKING_LOOP_CLOSURE"
    PASSED = "PASSED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class TemporalProofResultSource(str, Enum):
    """Identify whether the displayed PASS ran now or was safely reused."""

    LIVE = "LIVE"
    SESSION_CACHE = "SESSION_CACHE"


@dataclass(frozen=True)
class TemporalProofProgress:
    """Plain-data temporal validation progress safe to read from the UI."""

    state: TemporalProofState = TemporalProofState.IDLE
    result_source: TemporalProofResultSource = TemporalProofResultSource.LIVE
    validated_sample_count: int = 0
    total_sample_count: int = 0
    current_sample_index: int | None = None
    current_asset_name: str | None = None
    elapsed_seconds: float = 0.0
    loop_closure_state: str | None = None
    failure_reason: str | None = None
    cancellation_reason: str | None = None
    generation_id: int = 0
    last_progress_at: float | None = None

    @property
    def percentage(self) -> int | None:
        """Return real completed-sample progress without inventing loop work."""

        if self.total_sample_count <= 0:
            return None
        return round(100 * self.validated_sample_count / self.total_sample_count)
