# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""Shared, portable timestamp formatting for DTRS-owned diagnostics."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - available in the supported CPython builds.
    ZoneInfo = None


# Armenia has used UTC+04:00 without daylight saving time since 2012.  Kit's
# bundled Python may omit the IANA tzdata database, so DTRS can still produce
# project-local acceptance logs without making a logging detail a dependency.
_YEREVAN_FIXED_OFFSET = timezone(timedelta(hours=4), name="Asia/Yerevan")


def _format_timestamp(timestamp: datetime) -> str:
    """Keep DTRS timestamp precision and offset spelling consistent."""

    offset = timestamp.strftime("%z")
    return (
        timestamp.strftime("%Y-%m-%d %H:%M:%S.")
        + f"{timestamp.microsecond // 1000:03d} {offset[:3]}:{offset[3:]}"
    )


def dtrs_local_timestamp() -> str:
    """Return the host-local timestamp without assuming a specific timezone."""

    local_now = datetime.now().astimezone()
    offset = local_now.strftime("%z")
    return (
        local_now.strftime("%Y-%m-%d %H:%M:%S.")
        + f"{local_now.microsecond // 1000:03d} {offset[:3]}:{offset[3:]}"
    )


def with_dtrs_local_timestamp(message: str) -> str:
    """Add one readable local timestamp to a DTRS-owned diagnostic.

    Kit still supplies its own UTC prefix.  Keeping the local timestamp inside
    the DTRS message makes Flow, validation and workload events comparable with
    local VTK diagnostics without modifying Omniverse's global logger.
    """

    lines = message.splitlines()
    timestamp = dtrs_local_timestamp()
    if lines and lines[0].startswith("=== DTRS "):
        return "\n".join((lines[0], f"  Local time: {timestamp}", *lines[1:]))
    return f"{message} | Local time: {timestamp}"


def dtrs_yerevan_timestamp() -> str:
    """Return a project-local timestamp without requiring IANA tzdata.

    Prefer the standard-library IANA zone when Kit provides its database.  A
    fixed UTC+04:00 fallback preserves the project's required Yerevan format
    when the bundled interpreter does not ship ``tzdata``.
    """

    try:
        yerevan_timezone = (
            ZoneInfo("Asia/Yerevan") if ZoneInfo else _YEREVAN_FIXED_OFFSET
        )
        yerevan_now = datetime.now(yerevan_timezone)
    except Exception:
        # Diagnostics must never prevent the runtime action they are describing.
        yerevan_now = datetime.now(_YEREVAN_FIXED_OFFSET)
    return _format_timestamp(yerevan_now)


def with_dtrs_yerevan_timestamp(message: str) -> str:
    """Prefix one DTRS acceptance event without letting logging abort runtime work."""

    try:
        timestamp = dtrs_yerevan_timestamp()
    except Exception:
        timestamp = _format_timestamp(datetime.now(_YEREVAN_FIXED_OFFSET))
    return f"[{timestamp}] {message}"
