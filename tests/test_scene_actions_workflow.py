# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""Focused lifecycle regressions for production Reload Config sequencing."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace


def test_reload_config_leaves_active_production_heatmap_before_reopen(
    monkeypatch,
) -> None:
    events: list[str] = []
    mixin = _scene_actions_mixin(monkeypatch, events)

    class Owner(mixin):
        def __init__(self, *, heatmap_active: bool = False) -> None:
            self._controller = _Controller(heatmap_active=heatmap_active)
            self._motion_controller = _Motion(events, "previous_motion_reset")
            self._asset_label = _Text()
            self._lighting_status_label = _Text()
            self._reload_task = None

        def _set_lighting_controls(self, _lighting) -> None:
            events.append("lighting_controls")

        def _set_grid_controls(self, _grid) -> None:
            events.append("grid_controls")

        def _set_chassis_visibility_controls(self, _presentation) -> None:
            events.append("chassis_controls")

        def _set_camera_controls(self, _camera) -> None:
            events.append("camera_controls")

        def _set_airflow_status(self, status: str) -> None:
            events.append(f"airflow_status={status}")

        def _set_status(self, status: str) -> None:
            events.append(f"status={status}")

        async def _load_default_asset(self, event_label: str):
            events.append(f"stage_open={event_label}")
            return SimpleNamespace(success=True)

    owner = Owner()
    asyncio.run(owner._reload_config_and_stage())

    assert owner._controller.calls == [
        "cancel_transition",
        "xray_cleanup",
        "streamlines_cleanup",
        "reload_config",
    ]
    assert events == [
        "previous_motion_reset",
        "replacement_motion_created",
        "lighting_controls",
        "grid_controls",
        "chassis_controls",
        "airflow_status=Not attached",
        "stage_open=Reload Config (stage open)",
        "status=Configuration reloaded and stage reopened.",
    ]
    assert owner._asset_label.text == "Blackwell Rig"
    assert owner._lighting_status_label.text == "HDRI: review.hdr"


def test_reload_config_releases_active_heatmap_before_xray_cleanup(
    monkeypatch,
) -> None:
    events: list[str] = []
    mixin = _scene_actions_mixin(monkeypatch, events)

    class Owner(mixin):
        def __init__(self) -> None:
            self._controller = _Controller(heatmap_active=True)
            self._motion_controller = _Motion(events, "previous_motion_reset")
            self._asset_label = _Text()
            self._lighting_status_label = _Text()
            self._reload_task = None

        def _set_lighting_controls(self, _lighting) -> None:
            return None

        def _set_grid_controls(self, _grid) -> None:
            return None

        def _set_chassis_visibility_controls(self, _presentation) -> None:
            return None

        def _set_camera_controls(self, _camera) -> None:
            return None

        def _set_airflow_status(self, _status: str) -> None:
            return None

        def _set_status(self, _status: str) -> None:
            return None

        async def _load_default_asset(self, _event_label: str):
            return SimpleNamespace(success=True)

    owner = Owner()
    asyncio.run(owner._reload_config_and_stage())

    assert owner._controller.calls[:3] == [
        "cancel_transition",
        "heatmap_cleanup",
        "xray_cleanup",
    ]
    assert not owner._controller.heatmap_production_active()


def _scene_actions_mixin(monkeypatch, events: list[str]):
    monkeypatch.setitem(sys.modules, "carb", ModuleType("carb"))
    from digital_twin_runtime_suite.app import motion

    def _replacement_motion(_bindings):
        events.append("replacement_motion_created")
        return _Motion(events, "replacement_motion_reset")

    monkeypatch.setattr(
        motion,
        "MultiRotationMotionController",
        _replacement_motion,
    )
    path = (
        Path(__file__).parents[1]
        / "src/digital_twin_runtime_suite/ext/msp.dtrs/msp/dtrs/workflows"
        / "scene_actions.py"
    )
    spec = importlib.util.spec_from_file_location("scene_actions_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.SceneActionsWorkflowMixin


class _Controller:
    def __init__(self, *, heatmap_active: bool = False) -> None:
        self.calls: list[str] = []
        self._heatmap_active = heatmap_active

    def clear_xray_material_in_kit(self):
        self.calls.append("xray_cleanup")
        return SimpleNamespace(success=True, message="ok")

    def cancel_visualization_transition(self) -> None:
        self.calls.append("cancel_transition")

    def heatmap_production_active(self) -> bool:
        return self._heatmap_active

    def deactivate_heatmap_production_in_kit(self):
        self.calls.append("heatmap_cleanup")
        self._heatmap_active = False
        return SimpleNamespace(success=True, message="Heatmap restored")

    def clear_streamlines_static_runtime_from_open_stage(self):
        self.calls.append("streamlines_cleanup")
        return SimpleNamespace(clean=True)

    def reload_config(self):
        self.calls.append("reload_config")
        return SimpleNamespace(
            fan_motion_bindings=(),
            default_asset=SimpleNamespace(label="Blackwell Rig"),
            lighting=SimpleNamespace(),
            grid=SimpleNamespace(),
            chassis_presentation=SimpleNamespace(),
            camera=None,
            default_hdri_path=Path("review.hdr"),
        )


class _Motion:
    def __init__(self, events: list[str], event: str) -> None:
        self._events = events
        self._event = event

    def reset(self) -> None:
        self._events.append(self._event)


class _Text:
    def __init__(self) -> None:
        self.text = ""
        self.tooltip = ""
