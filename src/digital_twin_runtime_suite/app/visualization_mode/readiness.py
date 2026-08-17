"""Read-only primary-visualization readiness projections for DTRS."""

from __future__ import annotations

from dataclasses import dataclass

from digital_twin_runtime_suite.app.visualization_mode.model import VisualizationMode


@dataclass(frozen=True)
class VisualizationReadiness:
    """One mode's current readiness without triggering runtime work."""

    mode: VisualizationMode
    state: str
    message: str
    activation_available: bool


@dataclass(frozen=True)
class VisualizationReadinessSnapshot:
    """Current-workload readiness for every primary visualization mode."""

    workload: str
    entries: tuple[VisualizationReadiness, ...]

    def for_mode(self, mode: VisualizationMode) -> VisualizationReadiness:
        """Return the requested mode's projection from this one read-only pass."""

        return next(entry for entry in self.entries if entry.mode == mode)
