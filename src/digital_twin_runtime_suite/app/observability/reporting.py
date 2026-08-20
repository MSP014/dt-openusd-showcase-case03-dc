"""Route generic durable events and replaceable progress to independent sinks."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping

from digital_twin_runtime_suite.app.status_log import format_dtrs_status_block

from .progress import DurableEvent, EventKind, EventSeverity, ProgressState

ProgressSink = Callable[[ProgressState], None]
EventSink = Callable[[DurableEvent], None]


class CallbackProgressSink:
    """Adapt any existing status/UI callback without importing its UI toolkit."""

    def __init__(self, callback: ProgressSink) -> None:
        self._callback = callback

    def __call__(self, state: ProgressState) -> None:
        self._callback(state)


class ProgressReporter:
    """Publish replaceable state separately from immutable operation history."""

    def __init__(
        self,
        *,
        event_sinks: Iterable[EventSink] = (),
        progress_sinks: Iterable[ProgressSink] = (),
        finish_sinks: Iterable[Callable[[], None]] = (),
    ) -> None:
        self._event_sinks = tuple(event_sinks)
        self._progress_sinks = list(progress_sinks)
        self._finish_sinks = tuple(finish_sinks)
        self._latest_progress: ProgressState | None = None

    @property
    def latest_progress(self) -> ProgressState | None:
        """Expose the most recently published state without replaying history."""

        return self._latest_progress

    def add_progress_sink(self, sink: ProgressSink) -> None:
        """Attach an adapter after its workflow owner has been constructed."""

        self._progress_sinks.append(sink)

    def event(
        self,
        kind: EventKind,
        operation_id: str,
        message: str = "",
        *,
        metadata: Mapping[str, object] | None = None,
    ) -> DurableEvent:
        """Finish the live line and publish one durable semantic boundary."""

        self.finish()
        event = DurableEvent(
            operation_id=operation_id,
            kind=kind,
            message=message,
            metadata=metadata or {},
        )
        for sink in self._event_sinks:
            self._publish_safely(sink, event)
        return event

    def progress(self, state: ProgressState) -> None:
        """Replace visible state; presentation failures never abort producer work."""

        self._latest_progress = state
        for sink in self._progress_sinks:
            self._publish_safely(sink, state)

    def finish(self) -> None:
        """Release ephemeral renderers without adding a historical log record."""

        for sink in self._finish_sinks:
            self._publish_safely(sink)

    @staticmethod
    def _publish_safely(callback, *arguments) -> None:
        """Keep diagnostics isolated from the long-running operation they observe."""

        try:
            callback(*arguments)
        except Exception:
            return


class DtrsEventSink:
    """Format generic durable events through the established DTRS log contract."""

    def __init__(
        self,
        *,
        log_info: Callable[[str], None],
        log_warning: Callable[[str], None],
        log_error: Callable[[str], None],
        append_local_timestamp: Callable[[str], str],
    ) -> None:
        self._loggers = {
            EventSeverity.INFO: log_info,
            EventSeverity.WARNING: log_warning,
            EventSeverity.ERROR: log_error,
        }
        self._append_local_timestamp = append_local_timestamp

    def __call__(self, event: DurableEvent) -> None:
        """Write one timestamped historical event at its semantic severity."""

        logger = self._loggers[event.severity]
        logger(
            format_dtrs_status_block(
                self._content(event),
                append_local_timestamp=self._append_local_timestamp,
            )
        )

    @staticmethod
    def _content(event: DurableEvent) -> str:
        """Keep acceptance wording while formatting arbitrary event metadata."""

        if event.kind is EventKind.TEST_COMPLETE:
            return "\n".join((event.kind.value, event.message))
        lines = [f"DTRS {event.operation_id} | {event.kind.value}"]
        if event.message:
            lines.append(f"status={event.message}")
        for name, value in event.metadata.items():
            if name == "next_action":
                lines.append(f"NEXT_ACTION | {value}")
            else:
                lines.append(f"{name}={value}")
        return "\n".join(lines)
