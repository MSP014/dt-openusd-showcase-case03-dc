"""Plain data contracts for DTRS primary visualization presentation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class VisualizationMode(str, Enum):
    """One primary DTRS presentation consumer selected by the operator."""

    NORMAL = "Normal"
    SMOKE = "Smoke"
    STREAMLINES = "Streamlines"
    STREAMLINES_XRAY = "Streamlines + X-Ray"
    HEATMAP = "Heatmap"


@dataclass(frozen=True)
class VisualizationTransition:
    """One generation eligible to replace the proven primary presentation."""

    generation: int
    transition_id: str
    target: VisualizationMode
    superseded_transition_id: str | None = None


@dataclass(frozen=True)
class VisualizationTransitionContext:
    """One shared-airflow snapshot used throughout a consumer handoff."""

    workload: str
    dataset_identity: str
    logical_phase_seconds: float
    normalized_phase_seconds: float
    source_sample_index: int
    source_time_seconds: float
    source_vti: Path


@dataclass(frozen=True)
class VisualizationFailure:
    """A rejected request that leaves the previous committed mode authoritative."""

    requested_mode: VisualizationMode
    reason: str


@dataclass(frozen=True)
class VisualizationSnapshot:
    """Immutable primary-presentation state exposed to UI and diagnostics."""

    committed: VisualizationMode
    pending: VisualizationTransition | None
    failure: VisualizationFailure | None
