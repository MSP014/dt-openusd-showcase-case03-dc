import importlib.util
from pathlib import Path

import pytest


def _load_jira_link():
    path = Path("tools/jira_link.py")
    spec = importlib.util.spec_from_file_location("jira_link", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_worklog_payload_uses_exact_start_end_duration_and_comment():
    jira_link = _load_jira_link()

    payload, duration_seconds, started = jira_link._build_worklog_payload(
        None,
        "Stage 5 - full server integration",
        "2026-07-19 09:00:00",
        "2026-07-19 11:12:06",
        "Asia/Yerevan",
    )

    assert duration_seconds == 7926
    assert payload["timeSpentSeconds"] == 7926
    assert payload["started"] == "2026-07-19T09:00:00.000+0400"
    assert payload["comment"]["content"][0]["content"][0]["text"] == (
        "Stage 5 - full server integration"
    )
    assert started.isoformat() == "2026-07-19T09:00:00+04:00"


def test_worklog_payload_remains_compatible_with_duration_only_calls():
    jira_link = _load_jira_link()

    payload, duration_seconds, started = jira_link._build_worklog_payload(
        "1h 30m",
        None,
        None,
        None,
        "Asia/Yerevan",
    )

    assert payload == {"timeSpentSeconds": 5400}
    assert duration_seconds == 5400
    assert started is None


def test_worklog_payload_rejects_conflicting_duration_and_end_timestamp():
    jira_link = _load_jira_link()

    with pytest.raises(ValueError, match="does not match"):
        jira_link._build_worklog_payload(
            "2h",
            None,
            "2026-07-19 09:00:00",
            "2026-07-19 11:12:06",
            "Asia/Yerevan",
        )
