# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""Kit status-bar adapter for the shared replaceable-progress contract."""

from __future__ import annotations

from collections.abc import Callable

from .progress import ProgressState
from .terminal import format_terminal_progress_line

_PROGRESS_EVENT = "omni.kit.window.status_bar@progress"
_ACTIVITY_EVENT = "omni.kit.window.status_bar@activity"


class KitStatusBarProgressSink:
    """Present the latest progress state in Kit's single replaceable status bar.

    This is a presentation adapter, not an observability correctness owner.
    The status bar has one slot; feature panels may retain separate rows for
    simultaneous operations.
    """

    def __init__(self, queue_event: Callable[..., object]) -> None:
        self._queue_event = queue_event

    @classmethod
    def from_kit(cls) -> "KitStatusBarProgressSink":
        """Construct the adapter without importing Kit in producer modules."""

        from omni.kit.app import queue_event

        return cls(queue_event)

    def __call__(self, state: ProgressState) -> None:
        """Replace the current Kit status-bar message and progress value."""

        progress = state.fraction if state.fraction is not None else -1.0
        # Kit-CAE can publish another status update in the same frame.  Some
        # Kit status-bar builds concatenate consecutive activity events unless
        # the old activity is explicitly cleared first.
        self._queue_event(_ACTIVITY_EVENT, payload={"text": ""})
        self._queue_event(_PROGRESS_EVENT, payload={"progress": progress})
        self._queue_event(
            _ACTIVITY_EVENT,
            payload={"text": format_terminal_progress_line(state)},
        )

    def finish(self) -> None:
        """Return the Kit status bar to its normal application state."""

        self._queue_event(_PROGRESS_EVENT, payload={"progress": -1.0})
        self._queue_event(_ACTIVITY_EVENT, payload={"text": ""})
