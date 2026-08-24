# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
from pathlib import Path

from digital_twin_runtime_suite.app.review import runtime as review_runtime
from digital_twin_runtime_suite.app.review.runtime import ReviewRuntimeMixin


class _Carb:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def log_warn(self, message: str) -> None:
        self.messages.append(message)


def test_usd_stage_open_diagnostic_uses_the_standard_dtrs_block(monkeypatch) -> None:
    monkeypatch.setattr(
        review_runtime,
        "with_dtrs_local_timestamp",
        lambda content: f"{content} | Local time: fixed",
    )
    carb = _Carb()

    ReviewRuntimeMixin._log_usd_stage_open_diagnostic(
        carb,
        state="COMPLETE",
        asset_path=Path("asset.usd"),
        details={"elapsed_ms": 123, "root_layer": "asset.usd"},
    )

    assert carb.messages[0].splitlines()[1:4] == [
        "====================",
        "DTRS USD DIAGNOSTICS",
        "process=STAGE OPEN | state=COMPLETE",
    ]
    assert "asset_path=asset.usd" in carb.messages[0]
    assert "elapsed_ms=123" in carb.messages[0]
    assert carb.messages[0].endswith("Local time: fixed\n====================")
