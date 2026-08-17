"""Plain formatting and sequencing for the Phase 3.3 manual airflow check."""

from __future__ import annotations

from dataclasses import dataclass

from digital_twin_runtime_suite.app.manual_acceptance import (
    format_manual_acceptance_event,
    format_manual_acceptance_test_complete,
)


@dataclass
class Phase33AcceptanceState:
    """Track only the four manual Phase 3.3 milestones for one UI session."""

    attach_complete: bool = False
    critical_complete: bool = False
    nominal_complete: bool = False
    failed: bool = False
    terminal_emitted: bool = False

    def begin_session(self) -> None:
        """Clear prior acceptance evidence when the operator starts a new Attach."""

        self.attach_complete = False
        self.critical_complete = False
        self.nominal_complete = False
        self.failed = False
        self.terminal_emitted = False

    def mark_attach_complete(self) -> None:
        """Record the first required milestone after successful Attach."""

        self.attach_complete = True

    def mark_transition_complete(self, workload_mode: str) -> None:
        """Record only the ordered Critical then Nominal manual checks."""

        if not self.attach_complete or self.failed:
            return
        if workload_mode == "Critical":
            self.critical_complete = True
        elif workload_mode == "Nominal" and self.critical_complete:
            self.nominal_complete = True

    def mark_failed(self) -> None:
        """Disqualify this manual session without changing runtime state."""

        self.failed = True

    def complete_after_detach(self) -> bool:
        """Return true exactly once when successful Detach closes all milestones."""

        if self.terminal_emitted or self.failed:
            return False
        if not (
            self.attach_complete and self.critical_complete and self.nominal_complete
        ):
            return False
        self.terminal_emitted = True
        return True


def format_airflow_acceptance_event(
    event: str,
    status: str,
    *,
    next_action: str | None = None,
) -> str:
    """Format one readable acceptance event with an isolated next action."""

    return format_manual_acceptance_event(
        area="AIRFLOW | SHARED_STATE",
        event=event,
        status=status,
        next_action=next_action,
    )


def next_phase33_airflow_action(workload_mode: str) -> str:
    """Return the next required manual action after one accepted transition."""

    if workload_mode == "Critical":
        return 'Select "Nominal" in the "Workload" control.'
    return 'Press "Detach".'


def format_phase33_airflow_test_complete() -> str:
    """Return the explicit terminal record for the accepted Phase 3.3 flow."""

    return format_manual_acceptance_test_complete(
        "Phase 3.3 shared airflow state acceptance passed."
    )
