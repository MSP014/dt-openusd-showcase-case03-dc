"""Plain manifest-backed temporal source contracts for Streamlines.

The Kit-facing runtime owns VTI import, USD time-sample authoring, and CAE
execution. This module deliberately contains only deterministic source
selection rules, so the temporal behaviour can be tested without Kit.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from digital_twin_runtime_suite.app.flow.static_source import (
    StaticVelocitySourceDescriptor,
)


@dataclass(frozen=True)
class TemporalVelocitySourceDescriptor:
    """One logical ``vel`` source with manifest-derived USD time samples.

    ``static_descriptor`` records the accepted spatial import of sample zero.
    Every later source change is a time selection on its same imported field;
    it is never a new VTI import contract.
    """

    static_descriptor: StaticVelocitySourceDescriptor
    velocity_paths: tuple[Path, ...]
    sample_time_codes: tuple[float, ...]
    time_codes_per_second: float
    sample_interval_seconds: float

    @property
    def workload(self) -> str:
        """Return the semantic workload that selected this manifest."""

        return self.static_descriptor.workload

    @property
    def dataset_identity(self) -> str:
        """Return the manifest dataset identity without exposing Kit state."""

        return self.static_descriptor.dataset_identity

    @property
    def sample_count(self) -> int:
        """Return the manifest-derived number of real VTI samples."""

        return len(self.velocity_paths)

    @property
    def source_cadence_hz(self) -> float:
        """Return cadence computed from the manifest interval."""

        return 1.0 / self.sample_interval_seconds


@dataclass(frozen=True)
class TemporalSourceSample:
    """One exact manifest source selection for cache generation or playback."""

    ordinal: int
    total: int
    sample_index: int
    source_vti: Path
    source_time_seconds: float
    time_code: float
