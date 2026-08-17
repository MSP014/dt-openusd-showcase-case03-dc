"""Focused manual-acceptance presentation contracts for Phase 3.3."""

from __future__ import annotations

from digital_twin_runtime_suite.app.airflow_acceptance import (
    Phase33AcceptanceState,
    format_airflow_acceptance_event,
    format_phase33_airflow_test_complete,
    next_phase33_airflow_action,
)


def test_next_action_is_visually_isolated_from_status_noise() -> None:
    message = format_airflow_acceptance_event(
        "COMPLETE",
        "Airflow transitioned to server/load_critical.",
        next_action='Select "Nominal" in the "Workload" control.',
    )

    assert "status=Airflow transitioned" in message
    assert (
        "\n\n===============================================================\n"
        in message
    )
    assert 'NEXT_ACTION | Select "Nominal" in the "Workload" control.' in message
    assert message.endswith(
        "==============================================================="
    )


def test_phase33_acceptance_next_actions_cover_the_reverse_transition() -> None:
    assert next_phase33_airflow_action("Critical") == (
        'Select "Nominal" in the "Workload" control.'
    )
    assert next_phase33_airflow_action("Nominal") == 'Press "Detach".'


def test_phase33_terminal_record_is_explicit() -> None:
    message = format_phase33_airflow_test_complete()

    assert (
        "TEST COMPLETE | Phase 3.3 shared airflow state acceptance passed." in message
    )
    assert "No further manual action required." in message


def test_full_phase33_sequence_emits_terminal_once_after_detach() -> None:
    state = Phase33AcceptanceState()
    state.begin_session()
    state.mark_attach_complete()
    state.mark_transition_complete("Critical")
    state.mark_transition_complete("Nominal")

    assert state.complete_after_detach() is True
    assert state.complete_after_detach() is False


def test_incomplete_or_failed_sequence_never_emits_terminal_pass() -> None:
    incomplete = Phase33AcceptanceState()
    incomplete.begin_session()
    incomplete.mark_attach_complete()
    assert incomplete.complete_after_detach() is False

    failed = Phase33AcceptanceState()
    failed.begin_session()
    failed.mark_attach_complete()
    failed.mark_transition_complete("Critical")
    failed.mark_transition_complete("Nominal")
    failed.mark_failed()
    assert failed.complete_after_detach() is False


def test_background_state_does_not_gate_manual_terminal_completion() -> None:
    state = Phase33AcceptanceState()
    state.begin_session()
    state.mark_attach_complete()
    state.mark_transition_complete("Critical")
    state.mark_transition_complete("Nominal")
    state.background_validation_state = "RUNNING"

    assert state.complete_after_detach() is True


def test_new_acceptance_session_resets_prior_terminal_state() -> None:
    state = Phase33AcceptanceState(
        attach_complete=True,
        critical_complete=True,
        nominal_complete=True,
        terminal_emitted=True,
    )

    state.begin_session()

    assert state.terminal_emitted is False
    assert state.complete_after_detach() is False
