# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""Format visually isolated DTRS development status records."""

from __future__ import annotations

from collections.abc import Callable, Mapping

_STATUS_SEPARATOR = "=" * 20


def format_dtrs_status_block(
    content: str,
    *,
    append_local_timestamp: Callable[[str], str],
) -> str:
    """Keep a stamped status record readable inside a single Kit log entry.

    Kit prepends its logger context once and the DTRS timestamp helper appends
    to the received text.  Stamping content before the closing separator keeps
    both separators on dedicated lines.
    """

    stamped_content = append_local_timestamp(content)
    return f"\n{_STATUS_SEPARATOR}\n{stamped_content}\n{_STATUS_SEPARATOR}"


def format_dtrs_diagnostic_content(
    *,
    owner: str,
    process: str,
    state: str,
    details: Mapping[str, object],
) -> str:
    """Put every technical diagnostic into owner, state, and detail lines."""

    lines = [f"DTRS {owner}", f"process={process} | state={state}"]
    lines.extend(f"{name}={value}" for name, value in details.items())
    return "\n".join(lines)


def format_dtrs_diagnostic_block(
    *,
    owner: str,
    process: str,
    state: str,
    details: Mapping[str, object],
    append_local_timestamp: Callable[[str], str],
) -> str:
    """Format one timestamped diagnostic block from semantic fields."""

    return format_dtrs_status_block(
        format_dtrs_diagnostic_content(
            owner=owner,
            process=process,
            state=state,
            details=details,
        ),
        append_local_timestamp=append_local_timestamp,
    )
