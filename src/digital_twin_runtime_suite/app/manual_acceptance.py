"""Reusable plain formatting for guided DTRS manual acceptance workflows."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class GuidedAcceptanceSession:
    """Track ordered manual milestones without owning any runtime behaviour."""

    required_milestones: tuple[str, ...]
    completed_milestones: tuple[str, ...] = ()
    started: bool = False
    failed: bool = False
    terminal_emitted: bool = False

    @property
    def expected_milestone(self) -> str | None:
        """Return the one next milestone that may advance this session."""

        if self.failed or len(self.completed_milestones) >= len(
            self.required_milestones
        ):
            return None
        return self.required_milestones[len(self.completed_milestones)]

    def begin(self) -> None:
        """Reset the session before its first required manual action."""

        self.completed_milestones = ()
        self.started = True
        self.failed = False
        self.terminal_emitted = False

    def can_record(self, milestone: str) -> bool:
        """Return whether this exact milestone is currently expected."""

        return self.started and self.expected_milestone == milestone

    def record(self, milestone: str) -> bool:
        """Record one ordered success and reject duplicate or skipped steps."""

        if not self.can_record(milestone):
            return False
        self.completed_milestones = (*self.completed_milestones, milestone)
        return True

    def mark_failed(self) -> None:
        """Disqualify an active session without changing the runtime result."""

        if self.started and not self.terminal_emitted:
            self.failed = True

    def complete(self) -> bool:
        """Return true exactly once when every required milestone succeeded."""

        if (
            not self.started
            or self.failed
            or self.terminal_emitted
            or self.expected_milestone is not None
        ):
            return False
        self.terminal_emitted = True
        return True


def format_manual_acceptance_event(
    *,
    area: str,
    event: str,
    status: str,
    next_action: str | None = None,
) -> str:
    """Format guided-acceptance content for the shared status-block owner."""

    message = f"DTRS {area} | {event}\nstatus={status}"
    if next_action:
        message += f"\nNEXT_ACTION | {next_action}"
    return message


def format_manual_acceptance_test_complete(result: str) -> str:
    """Format terminal content for the shared status-block owner."""

    return "\n".join(
        (
            "TEST COMPLETE",
            result,
            "No further manual action required.",
        )
    )
