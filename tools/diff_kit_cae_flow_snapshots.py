"""Create a machine-readable parity diff from the two Kit-CAE Flow snapshots."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from digital_twin_runtime_suite.app.kit_cae_flow_parity import (  # noqa: E402
    diff_flow_snapshots,
)

DIAGNOSTICS = PROJECT_ROOT / "out" / "diagnostics"
REFERENCE_PATH = DIAGNOSTICS / "kit_cae_flow_snapshot_reference_npz.json"
DTRS_PATH = DIAGNOSTICS / "kit_cae_flow_snapshot_dtrs.json"
OUTPUT_PATH = DIAGNOSTICS / "kit_cae_flow_parity_diff.json"


def main() -> None:
    reference = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))
    dtrs = json.loads(DTRS_PATH.read_text(encoding="utf-8"))
    output_path = OUTPUT_PATH
    output_path.write_text(
        json.dumps(diff_flow_snapshots(reference, dtrs), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(output_path)


if __name__ == "__main__":
    main()
