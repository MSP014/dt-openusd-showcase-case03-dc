"""Optional TTY-only rendering for replaceable DTRS operation progress."""

from __future__ import annotations

import sys
from typing import TextIO

from .progress import ProgressState


def format_terminal_progress_line(state: ProgressState, *, width: int = 20) -> str:
    """Return the TTY representation shared by live output and static previews."""

    fraction = state.fraction
    if fraction is None:
        bar = "?" * width
        percentage = "?"
    else:
        filled = round(width * fraction)
        # Carbonite console output is not reliably UTF-8 on this Kit build.
        bar = "+" * filled + "-" * (width - filled)
        percentage = f"{fraction * 100.0:.1f}%"
    current = (
        f" | {state.current}/{state.total}"
        if state.current is not None and state.total is not None
        else ""
    )
    context = str(state.metadata.get("terminal_context", "")).strip()
    context_text = f" | {context}" if context else ""
    return f"DTRS {state.operation_id} [{bar}] {percentage}{current}{context_text}"


def format_live_progress_preview() -> str:
    """Show static post-startup examples without creating a fake operation."""

    examples = (
        (0.25, 20, "cache 2/8 | Idle / Global Flow Path"),
        (0.75, 60, "cache 6/8 | Surge / Global Flow Path"),
    )
    lines = ["Development-only static preview; no DTRS operation is active."]
    for fraction, current, context in examples:
        line = format_terminal_progress_line(
            ProgressState(
                operation_id="Streamlines",
                phase="CACHE_MATRIX",
                fraction=fraction,
                current=current,
                total=80,
                metadata={"terminal_context": context},
            )
        )
        lines.append(f"{fraction * 100.0:.0f}% example | {line}")
    lines.append("Live updates replace this line; they do not add Carbonite history.")
    return "\n".join(lines)


class TerminalProgressRenderer:
    """Render one progress state in place without becoming a correctness owner."""

    def __init__(self, stream: TextIO | None = None, *, width: int = 20) -> None:
        self._stream = stream or sys.stderr
        self._width = width
        self._previous_length = 0

    def publish(self, state: ProgressState) -> None:
        """Replace the previous TTY line and ignore non-interactive streams."""

        if not self._interactive:
            return
        line = self._format(state)
        clear = " " * max(self._previous_length - len(line), 0)
        self._stream.write(f"\r{line}{clear}")
        self._stream.flush()
        self._previous_length = len(line)

    def finish(self) -> None:
        """Clear a live line before the next durable console event is printed."""

        if not self._interactive or not self._previous_length:
            return
        self._stream.write(f"\r{' ' * self._previous_length}\r\n")
        self._stream.flush()
        self._previous_length = 0

    @property
    def _interactive(self) -> bool:
        """Avoid control characters in redirected Kit or test output."""

        isatty = getattr(self._stream, "isatty", None)
        return bool(isatty and isatty())

    def _format(self, state: ProgressState) -> str:
        """Render generic fields while allowing producers to add concise context."""

        return format_terminal_progress_line(state, width=self._width)
