"""Shared, portable timestamp formatting for DTRS-owned diagnostics."""

from __future__ import annotations

from datetime import datetime


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
