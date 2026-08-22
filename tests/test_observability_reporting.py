"""Focused contracts for reusable DTRS live progress and durable events."""

from __future__ import annotations

from digital_twin_runtime_suite.app.observability import (
    DtrsEventSink,
    EventKind,
    KitStatusBarProgressSink,
    ProgressReporter,
    ProgressState,
    TerminalProgressRenderer,
    format_live_progress_preview,
)


def test_progress_replaces_visible_state_without_creating_durable_events():
    events = []
    progress = []
    reporter = ProgressReporter(
        event_sinks=(events.append,),
        progress_sinks=(progress.append,),
    )

    reporter.progress(_state(fraction=0.125, current=10))
    reporter.progress(_state(fraction=0.25, current=20))

    assert events == []
    assert [state.current for state in progress] == [10, 20]
    assert reporter.latest_progress is progress[-1]


def test_event_uses_semantic_info_warning_and_error_loggers():
    info = []
    warnings = []
    errors = []
    reporter = ProgressReporter(
        event_sinks=(
            DtrsEventSink(
                log_info=info.append,
                log_warning=warnings.append,
                log_error=errors.append,
                append_local_timestamp=lambda message: f"{message} | Local time: fixed",
            ),
        ),
    )

    reporter.event(EventKind.START, "CACHE_MATRIX", "Build started.")
    reporter.event(EventKind.WARNING, "CACHE_MATRIX", "Fallback retained.")
    reporter.event(EventKind.FAIL, "CACHE_MATRIX", "Build failed.")

    assert "DTRS CACHE_MATRIX | START" in info[0]
    assert "DTRS CACHE_MATRIX | WARNING" in warnings[0]
    assert "DTRS CACHE_MATRIX | FAIL" in errors[0]


def test_tty_renderer_replaces_and_clears_a_shorter_live_line():
    stream = _Stream(tty=True)
    renderer = TerminalProgressRenderer(stream, width=4)
    first = _state(fraction=0.5, current=50, context="very long cache context")
    second = _state(fraction=0.75, current=75, context="short")

    first_line = renderer._format(first)
    second_line = renderer._format(second)
    renderer.publish(first)
    renderer.publish(second)

    assert stream.value == (
        f"\r{first_line}\r{second_line}" f"{' ' * (len(first_line) - len(second_line))}"
    )


def test_non_tty_renderer_emits_no_live_progress_spam():
    stream = _Stream(tty=False)
    renderer = TerminalProgressRenderer(stream)

    renderer.publish(_state(fraction=0.5, current=50))
    renderer.finish()

    assert stream.value == ""


def test_finish_clears_the_tty_line_before_the_next_durable_event():
    stream = _Stream(tty=True)
    renderer = TerminalProgressRenderer(stream)
    reporter = ProgressReporter(
        event_sinks=(lambda _event: None,),
        progress_sinks=(renderer.publish,),
        finish_sinks=(renderer.finish,),
    )

    reporter.progress(_state(fraction=0.5, current=50))
    reporter.event(EventKind.COMPLETE, "CACHE_MATRIX", "Build complete.")

    assert stream.value.endswith("\r\n")
    assert renderer._previous_length == 0


def test_progress_sink_failure_never_aborts_the_observed_operation():
    reporter = ProgressReporter(progress_sinks=(_raise_presentation_error,))
    state = _state(fraction=0.5, current=50)

    reporter.progress(state)

    assert reporter.latest_progress is state


def test_kit_status_bar_sink_replaces_progress_without_creating_log_events():
    events = []
    sink = KitStatusBarProgressSink(
        lambda event_name, *, payload: events.append((event_name, payload))
    )

    sink(_state(fraction=0.25, current=25))
    sink(_state(fraction=0.75, current=75, context="short"))
    sink.finish()

    assert events == [
        ("omni.kit.window.status_bar@activity", {"text": ""}),
        ("omni.kit.window.status_bar@progress", {"progress": 0.25}),
        (
            "omni.kit.window.status_bar@activity",
            {
                "text": (
                    "DTRS Streamlines [+++++---------------] 25.0% | 25/100 "
                    "| cache 1/8 | Idle / Volume Coverage"
                )
            },
        ),
        ("omni.kit.window.status_bar@activity", {"text": ""}),
        ("omni.kit.window.status_bar@progress", {"progress": 0.75}),
        (
            "omni.kit.window.status_bar@activity",
            {"text": "DTRS Streamlines [+++++++++++++++-----] 75.0% | 75/100 | short"},
        ),
        ("omni.kit.window.status_bar@progress", {"progress": -1.0}),
        ("omni.kit.window.status_bar@activity", {"text": ""}),
    ]


def test_static_preview_uses_the_same_live_terminal_representation():
    preview = format_live_progress_preview()

    assert "Development-only static preview; no DTRS operation is active." in preview
    assert "25% example | DTRS Streamlines [" in preview
    assert "75% example | DTRS Streamlines [" in preview
    assert "+" in preview
    assert "-" in preview
    assert "20/80 | cache 2/8 | Idle / Global Flow Path" in preview
    assert "60/80 | cache 6/8 | Surge / Global Flow Path" in preview
    assert "Live updates replace this line" in preview


def _state(
    *,
    fraction: float,
    current: int,
    context: str = "cache 1/8 | Idle / Volume Coverage",
) -> ProgressState:
    return ProgressState(
        operation_id="Streamlines",
        phase="CACHE_MATRIX",
        fraction=fraction,
        current=current,
        total=100,
        metadata={"terminal_context": context},
    )


def _raise_presentation_error(_state: ProgressState) -> None:
    raise RuntimeError("presentation sink failed")


class _Stream:
    def __init__(self, *, tty: bool) -> None:
        self._tty = tty
        self.value = ""
        self.flush_calls = 0

    def isatty(self) -> bool:
        return self._tty

    def write(self, value: str) -> int:
        self.value += value
        return len(value)

    def flush(self) -> None:
        self.flush_calls += 1
