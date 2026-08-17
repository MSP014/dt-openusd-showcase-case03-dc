"""Kit-neutral transactional state for primary DTRS visualization modes."""

from __future__ import annotations

from digital_twin_runtime_suite.app.visualization_mode.model import (
    VisualizationFailure,
    VisualizationMode,
    VisualizationSnapshot,
    VisualizationTransition,
)


class VisualizationModeState:
    """Keep the last proven mode authoritative until a replacement is ready."""

    def __init__(self) -> None:
        self._committed = VisualizationMode.NORMAL
        self._pending: VisualizationTransition | None = None
        self._failure: VisualizationFailure | None = None
        self._generation = 0

    @property
    def snapshot(self) -> VisualizationSnapshot:
        """Return the complete plain-data state without exposing mutation."""

        return VisualizationSnapshot(self._committed, self._pending, self._failure)

    @property
    def committed(self) -> VisualizationMode:
        """Return the last mode that proved its presentation postconditions."""

        return self._committed

    def begin(self, target: VisualizationMode) -> VisualizationTransition | None:
        """Make a replacement pending, superseding any older pending request."""

        if self._pending and self._pending.target == target:
            return None
        if self._committed == target:
            self._pending = None
            self._failure = None
            return None
        superseded = self._pending.transition_id if self._pending else None
        self._generation += 1
        transition = VisualizationTransition(
            self._generation,
            f"V{self._generation:04d}",
            target,
            superseded,
        )
        self._pending = transition
        self._failure = None
        return transition

    def commit(self, transition_id: str) -> bool:
        """Commit only the current generation after its backend proves ready."""

        if self._pending is None or self._pending.transition_id != transition_id:
            return False
        self._committed = self._pending.target
        self._pending = None
        self._failure = None
        return True

    def fail(self, transition_id: str, reason: str) -> bool:
        """Reject only the active request while retaining the proven mode."""

        if self._pending is None or self._pending.transition_id != transition_id:
            return False
        self._failure = VisualizationFailure(self._pending.target, reason)
        self._pending = None
        return True

    def cancel(self, transition_id: str | None = None) -> bool:
        """Clear a pending request without changing the committed presentation."""

        if self._pending is None:
            return False
        if transition_id is not None and self._pending.transition_id != transition_id:
            return False
        self._pending = None
        return True

    def reset(self) -> None:
        """Return to Normal at a lifecycle boundary with no stale generation."""

        self._committed = VisualizationMode.NORMAL
        self._pending = None
        self._failure = None
        self._generation = 0
