"""Regression guard for the final cleaned Streamlines runtime boundary."""

from __future__ import annotations

import re
from pathlib import Path


def test_clean_runtime_tests_and_extension_exclude_retired_renderer_modules() -> None:
    root = Path(__file__).parents[2]
    active_sources = (
        root / "src" / "digital_twin_runtime_suite" / "app",
        root / "src" / "digital_twin_runtime_suite" / "ext",
        root / "tests",
    )
    retired = tuple(
        "_".join(parts)
        for parts in (
            ("cached", "state", "runtime"),
            ("mesh", "conversion"),
            ("mesh", "cache"),
            ("mesh", "playback", "runtime"),
            ("mesh", "playback", "acceptance"),
            ("xform", "probe"),
            ("real", "curve", "ab", "probe"),
            ("full", "state", "ab", "probe"),
            ("cache", "playback", "sanity"),
            ("renderer", "diagnostic"),
        )
    )

    source = "\n".join(
        path.read_text(encoding="utf-8")
        for directory in active_sources
        for path in directory.rglob("*.py")
    )

    assert all(
        re.search(rf"(?<![A-Za-z0-9_]){name}(?![A-Za-z0-9_])", source) is None
        for name in retired
    )


def test_clean_streamlines_sources_have_no_timeline_or_probe_ui() -> None:
    root = Path(__file__).parents[2]
    streamlines = root / "src" / "digital_twin_runtime_suite" / "app" / "streamlines"
    extension = (
        root
        / "src"
        / "digital_twin_runtime_suite"
        / "ext"
        / "msp.dtrs"
        / "msp"
        / "dtrs"
        / "extension.py"
    )
    streamlines_source = "\n".join(
        path.read_text(encoding="utf-8") for path in streamlines.rglob("*.py")
    )
    extension_source = extension.read_text(encoding="utf-8")
    retired_buttons = tuple(
        " ".join(parts)
        for parts in (
            ("Run", "Streamlines", "Xform", "Probe"),
            ("Run", "Real", "Curve", "A/B", "Probe"),
            ("Run", "Full", "80-State", "Streamlines", "Probe"),
        )
    )

    assert "omni.timeline" not in streamlines_source
    assert all(button not in extension_source for button in retired_buttons)
