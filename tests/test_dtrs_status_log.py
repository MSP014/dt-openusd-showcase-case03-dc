"""Focused formatting contracts for visually isolated DTRS status records."""

from digital_twin_runtime_suite.app.status_log import (
    format_dtrs_diagnostic_block,
    format_dtrs_status_block,
)


def test_status_block_stamps_the_last_content_line_before_its_separator():
    block = format_dtrs_status_block(
        "DTRS STREAMLINES | MANUAL_VALIDATION_EXAMPLE | READY\n"
        "status=valid=8/8; normal_preconditions=PASS.\n"
        'NEXT_ACTION | Select "Streamlines" in "Visualization".',
        append_local_timestamp=lambda content: f"{content} | Local time: fixed",
    )

    assert block.splitlines() == [
        "",
        "====================",
        "DTRS STREAMLINES | MANUAL_VALIDATION_EXAMPLE | READY",
        "status=valid=8/8; normal_preconditions=PASS.",
        'NEXT_ACTION | Select "Streamlines" in "Visualization".' " | Local time: fixed",
        "====================",
    ]


def test_diagnostic_block_separates_its_owner_state_and_details():
    block = format_dtrs_diagnostic_block(
        owner="VALIDATION RECEIPTS",
        process="CACHE VALIDATION",
        state="PROGRESS",
        details={
            "workload": "Idle",
            "profile": "volume_coverage",
            "status": "CHECKING",
        },
        append_local_timestamp=lambda content: f"{content} | Local time: fixed",
    )

    assert block.splitlines() == [
        "",
        "====================",
        "DTRS VALIDATION RECEIPTS",
        "process=CACHE VALIDATION | state=PROGRESS",
        "workload=Idle",
        "profile=volume_coverage",
        "status=CHECKING | Local time: fixed",
        "====================",
    ]
