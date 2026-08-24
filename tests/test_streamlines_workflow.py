# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""Focused Streamlines UI-workflow contracts."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace


def test_inactive_profile_change_persists_preference_without_task(monkeypatch):
    workflow, controller, _messages = _workflow()
    scheduled = []
    monkeypatch.setattr(asyncio, "ensure_future", scheduled.append)

    workflow.request_profile("volume_coverage", streamlines_active=False)

    assert controller.preference == "volume_coverage"
    assert scheduled == []


def test_active_profile_change_replaces_the_previous_ui_task(monkeypatch):
    workflow, _controller, _messages = _workflow()
    previous = _Task()
    workflow._profile_task = previous
    scheduled = []

    def capture(coroutine):
        scheduled.append(coroutine)
        return _Task()

    monkeypatch.setattr(asyncio, "ensure_future", capture)

    workflow.request_profile("global_flow_path", streamlines_active=True)

    assert previous.cancelled is True
    assert len(scheduled) == 1
    scheduled[0].close()


def test_material_settings_apply_and_persist_from_the_controller_contract():
    workflow, controller, messages = _workflow()

    asyncio.run(
        workflow._apply_material_settings(
            opacity=0.7,
            emission_intensity=2.0,
            lighting_influence=0.2,
        )
    )

    assert controller.material_arguments == (0.7, 2.0, 0.2)
    assert controller.material_settings_persisted is True
    assert any("applied and saved locally" in message for message in messages)


def test_cancel_stops_tasks_and_controller_measurement():
    workflow, controller, _messages = _workflow()
    profile_task = _Task()
    material_task = _Task()
    workflow._profile_task = profile_task
    workflow._material_apply_task = material_task

    workflow.cancel()

    assert profile_task.cancelled is True
    assert material_task.cancelled is True
    assert controller.measurement_cancelled is True


def _workflow():
    module = _load_workflow()
    messages = []
    controller = _Controller()
    workflow = module.StreamlinesWorkflow(
        controller,
        report_status=messages.append,
        report_material_status=messages.append,
        restore_profile_selection=messages.append,
        log_error=messages.append,
    )
    return workflow, controller, messages


class _Task:
    def __init__(self) -> None:
        self.cancelled = False

    def done(self) -> bool:
        return False

    def cancel(self) -> None:
        self.cancelled = True


class _Controller:
    def __init__(self) -> None:
        self.preference = None
        self.material_arguments = None
        self.measurement_cancelled = False
        self.material_settings_persisted = False

    def set_streamlines_profile_preference(self, profile_id) -> None:
        self.preference = profile_id

    def cancel_streamlines_material_apply(self) -> None:
        self.measurement_cancelled = True

    def streamlines_presentation_contract(self, **kwargs):
        self.material_arguments = (
            kwargs["opacity"],
            kwargs["emission_intensity"],
            kwargs["lighting_influence"],
        )
        return "presentation"

    def save_streamlines_material_settings(self, presentation):
        assert presentation == "presentation"
        self.material_settings_persisted = True
        return Path("runtime.local.toml")

    async def apply_streamlines_material_settings_in_kit(
        self,
        _presentation,
        status_callback,
    ):
        status_callback("Applying material")
        return SimpleNamespace(
            viewport_fps_average=60.0,
            material=SimpleNamespace(presentation_signature="abc123"),
        )


def _load_workflow():
    path = (
        Path(__file__).parents[1]
        / "src"
        / "digital_twin_runtime_suite"
        / "ext"
        / "msp.dtrs"
        / "msp"
        / "dtrs"
        / "workflows"
        / "streamlines.py"
    )
    spec = importlib.util.spec_from_file_location("streamlines_workflow", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
