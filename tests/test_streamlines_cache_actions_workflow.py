"""Focused UI-boundary tests for the production Streamlines cache-set action."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace


def _workflow_mixin():
    sys.modules.setdefault("carb", SimpleNamespace(log_error=lambda _message: None))
    path = (
        Path(__file__).parents[1]
        / "src/digital_twin_runtime_suite/ext/msp.dtrs/msp/dtrs/workflows"
        / "streamlines_cache_actions.py"
    )
    spec = importlib.util.spec_from_file_location("cache_actions_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.StreamlinesCacheWorkflowMixin


class _Controller:
    def __init__(self) -> None:
        self.status_callback = None

    async def build_validate_production_cache_set_in_kit(self, *, status_callback):
        self.status_callback = status_callback
        status_callback("cache=1/8; workload=Idle; profile=volume_coverage")
        return SimpleNamespace(
            success=True,
            message="All configured production Streamlines caches are VALID.",
        )

    def streamlines_production_speed_readiness_snapshot(self):
        return ("ready",) * 8

    async def collect_streamlines_speed_scale_proposal(
        self,
        *,
        status_callback,
        ready_entries,
    ):
        assert ready_entries == ("ready",) * 8
        status_callback("Volume speed evidence: Idle/volume_coverage.")
        return SimpleNamespace(
            scale=SimpleNamespace(
                minimum=0.25,
                maximum=3.5,
                units="source velocity units",
            )
        )


def test_cache_set_action_recalculates_and_saves_the_shared_speed_scale():
    mixin = _workflow_mixin()

    class Owner(mixin):
        def __init__(self) -> None:
            self._airflow_task = None
            self._controller = _Controller()
            self.enabled = []
            self.statuses = []
            self.material_statuses = []

        def _set_streamlines_cache_buttons_enabled(self, enabled: bool) -> None:
            self.enabled.append(enabled)

        def _set_streamlines_status(self, message: str) -> None:
            self.statuses.append(message)

        def _set_streamlines_material_status(self, message: str) -> None:
            self.material_statuses.append(message)

    owner = Owner()
    asyncio.run(owner._build_validate_production_cache_set())

    assert owner._controller.status_callback is not None
    assert owner.statuses == [
        "cache=1/8; workload=Idle; profile=volume_coverage",
        "Volume speed evidence: Idle/volume_coverage.",
        "All configured production Streamlines caches are VALID. Shared speed "
        "scale saved locally: 0.25..3.5 source velocity units.",
    ]
    assert owner.material_statuses == [
        "All configured production Streamlines caches are VALID. Shared speed "
        "scale saved locally: 0.25..3.5 source velocity units."
    ]
    assert owner.enabled == [True]
