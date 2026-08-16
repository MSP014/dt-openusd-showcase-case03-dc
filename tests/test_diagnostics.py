"""Focused portable timestamp contracts for DTRS diagnostics."""

from __future__ import annotations

import re

from digital_twin_runtime_suite.app import diagnostics


def test_yerevan_timestamp_uses_fixed_offset_when_kit_lacks_tzdata(
    monkeypatch,
):
    def missing_tzdata(_name):
        raise RuntimeError("No time zone found with key Asia/Yerevan")

    monkeypatch.setattr(diagnostics, "ZoneInfo", missing_tzdata)

    timestamp = diagnostics.dtrs_yerevan_timestamp()

    assert re.fullmatch(
        r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} \+04:00", timestamp
    )


def test_yerevan_log_wrapper_never_raises_when_timestamp_formatter_fails(
    monkeypatch,
):
    def broken_timestamp():
        raise RuntimeError("unexpected formatter failure")

    monkeypatch.setattr(diagnostics, "dtrs_yerevan_timestamp", broken_timestamp)

    event = diagnostics.with_dtrs_yerevan_timestamp(
        "DTRS STREAMLINES | STATIC_SOURCE | BEGIN"
    )

    assert re.match(r"^\[\d{4}-\d{2}-\d{2} .* \+04:00\] DTRS STREAMLINES", event)
