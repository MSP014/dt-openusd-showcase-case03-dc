# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""Plain ordered-workflow contracts shared by temporary DTRS acceptance UI."""

from digital_twin_runtime_suite.app.manual_acceptance import (
    GuidedAcceptanceSession,
)


def test_guided_session_completes_once_in_its_required_order() -> None:
    session = GuidedAcceptanceSession(("first", "second"))

    session.begin()

    assert session.record("first") is True
    assert session.record("second") is True
    assert session.complete() is True
    assert session.complete() is False


def test_guided_session_rejects_skipped_or_duplicate_milestones() -> None:
    session = GuidedAcceptanceSession(("first", "second"))

    session.begin()

    assert session.record("second") is False
    assert session.record("first") is True
    assert session.record("first") is False
    assert session.complete() is False


def test_guided_session_failure_never_completes() -> None:
    session = GuidedAcceptanceSession(("only",))

    session.begin()
    session.mark_failed()

    assert session.record("only") is False
    assert session.complete() is False


def test_guided_session_new_run_resets_previous_terminal_state() -> None:
    session = GuidedAcceptanceSession(("only",))
    session.begin()
    assert session.record("only") is True
    assert session.complete() is True

    session.begin()

    assert session.terminal_emitted is False
    assert session.record("only") is True
    assert session.complete() is True
