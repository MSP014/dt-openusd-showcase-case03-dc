"""Stage 09 real Kit-CAE acceptance for Streamlines source and runtime output."""

from __future__ import annotations

from pathlib import Path

import omni.kit.test
import omni.usd
from omni.cae.testing import new_stage

from digital_twin_runtime_suite.app.streamlines.reproducer import (
    REPRODUCER_ROOT,
    run_streamlines_integration_acceptance_in_kit,
)


class TestStage09StreamlinesIntegration(omni.kit.test.AsyncTestCase):
    """Prove the NVIDIA baseline and Houdini VTI through real Kit runtime data."""

    async def test_nvidia_baseline_and_houdini_vti_produce_runtime_streamlines(
        self,
    ):
        """Reject USD placeholders; require non-placeholder UsdRT BasisCurves."""

        async with new_stage():
            result = await run_streamlines_integration_acceptance_in_kit(
                _case03_asset_root(),
            )
            stage = omni.usd.get_context().get_stage()
            self.assertFalse(stage.GetPrimAtPath(REPRODUCER_ROOT).IsValid())

        self.assertTrue(result.case_a.passed, result.case_a.reason)
        self.assertTrue(result.case_b.passed, result.case_b.reason)
        self.assertTrue(result.cleanup_passed, result.cleanup_reason)
        self.assertTrue(result.success, result.message)


def _case03_asset_root() -> Path:
    """Locate repository-owned assets without depending on the test runner CWD."""

    for parent in Path(__file__).resolve().parents:
        candidate = parent / "assets" / "_external"
        if candidate.is_dir():
            return candidate
    raise RuntimeError("Stage 09 integration test could not locate assets/_external.")
