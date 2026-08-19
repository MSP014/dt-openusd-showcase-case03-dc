"""Focused contracts for explicit stable-prim cached state application."""

from __future__ import annotations

import asyncio
import sys
from types import ModuleType, SimpleNamespace

import pytest

from digital_twin_runtime_suite.app.streamlines.cache import (
    CACHE_PLAYBACK_CURVES_PATH,
    CACHE_PLAYBACK_SOURCE_CURVES_PATH,
)
from digital_twin_runtime_suite.app.streamlines.cached_state_runtime import (
    SOURCE_TIME_ATTRIBUTE,
    CachedStreamlinesState,
    StreamlinesCachedStateRuntimeMixin,
    validate_cached_streamlines_state,
)
from digital_twin_runtime_suite.app.streamlines.speed import (
    SPEED_PRIMVAR_ATTRIBUTE,
)


def test_explicit_state_updates_points_speed_extent_without_time_samples(
    monkeypatch,
) -> None:
    runtime, stage, app = _runtime(monkeypatch)

    receipt = asyncio.run(runtime.apply_streamlines_cached_state_in_kit(_sample(1)))

    visible = stage.prims[CACHE_PLAYBACK_CURVES_PATH]
    assert visible.attributes["points"].Get() == [(2.0, 0.0, 0.0)] * 4
    assert visible.attributes[SPEED_PRIMVAR_ATTRIBUTE].Get() == [2.0] * 4
    assert visible.attributes["extent"].Get() == [(2.0, 0.0, 0.0)] * 2
    assert visible.attributes[SOURCE_TIME_ATTRIBUTE].Get() == 0.2
    assert visible.attributes["curveVertexCounts"].Get() == [2, 2]
    assert all(not attr.GetTimeSamples() for attr in visible.attributes.values())
    assert receipt.sample_index == 1
    assert runtime._streamlines_cache_active_sample_index == 1
    assert app.updates == 1
    assert stage.get_paths == [
        CACHE_PLAYBACK_SOURCE_CURVES_PATH,
        CACHE_PLAYBACK_CURVES_PATH,
    ]


def test_failed_explicit_state_preserves_previous_complete_visible_state(
    monkeypatch,
) -> None:
    runtime, stage, _app = _runtime(monkeypatch)
    visible = stage.prims[CACHE_PLAYBACK_CURVES_PATH]
    visible.attributes[SPEED_PRIMVAR_ATTRIBUTE].fail_next_set = True

    with pytest.raises(RuntimeError, match="speed"):
        asyncio.run(runtime.apply_streamlines_cached_state_in_kit(_sample(1)))

    assert visible.attributes["points"].Get() == [(1.0, 0.0, 0.0)] * 4
    assert visible.attributes[SPEED_PRIMVAR_ATTRIBUTE].Get() == [1.0] * 4
    assert visible.attributes["extent"].Get() == [(1.0, 0.0, 0.0)] * 2
    assert runtime._streamlines_cache_active_sample_index == 0


def test_superseded_explicit_state_cannot_late_commit(monkeypatch) -> None:
    runtime, _stage, app = _runtime(monkeypatch)
    app.on_update = runtime.invalidate_streamlines_cached_state_updates

    with pytest.raises(RuntimeError, match="superseded"):
        asyncio.run(runtime.apply_streamlines_cached_state_in_kit(_sample(1)))

    assert runtime._streamlines_cache_active_sample_index == 0
    assert runtime.streamlines_cached_state_apply_receipts() == ()


def test_state_validation_rejects_points_or_speed_mismatch() -> None:
    with pytest.raises(ValueError, match="fixed topology"):
        validate_cached_streamlines_state(
            CachedStreamlinesState(0, 0.0, 0.0, [1], [1], [(0, 0, 0)] * 2),
            expected_point_count=2,
        )
    with pytest.raises(ValueError, match="speed count"):
        validate_cached_streamlines_state(
            CachedStreamlinesState(0, 0.0, 0.0, [1, 2], [1], [(0, 0, 0)] * 2),
            expected_point_count=2,
        )


class _Runtime(StreamlinesCachedStateRuntimeMixin):
    pass


class _Attr:
    def __init__(self, default=None, samples=None, name="attribute") -> None:
        self.default = default
        self.samples = dict(samples or {})
        self.name = name
        self.fail_next_set = False

    def Get(self, time_code=None):
        if time_code is None:
            return self.default
        return self.samples[float(time_code.value)]

    def Set(self, value) -> bool:
        if self.fail_next_set:
            self.fail_next_set = False
            return False
        self.default = value
        return True

    def Clear(self) -> None:
        self.default = None

    def GetTimeSamples(self):
        return tuple(sorted(self.samples))

    def GetName(self) -> str:
        return self.name


class _Prim:
    def __init__(self, attributes) -> None:
        self.attributes = attributes

    def IsValid(self) -> bool:
        return True

    def GetAttribute(self, name):
        return self.attributes[name]


class _Curves:
    def __init__(self, prim) -> None:
        self.prim = prim

    def GetPointsAttr(self):
        return self.prim.GetAttribute("points")

    def GetCurveVertexCountsAttr(self):
        return self.prim.GetAttribute("curveVertexCounts")

    def GetExtentAttr(self):
        return self.prim.GetAttribute("extent")


class _Stage:
    def __init__(self, prims) -> None:
        self.prims = prims
        self.get_paths = []
        self.target = "root"
        self.session = "session"

    def GetPrimAtPath(self, path):
        self.get_paths.append(path)
        return self.prims[path]

    def GetEditTarget(self):
        return self.target

    def SetEditTarget(self, target) -> None:
        self.target = target

    def GetSessionLayer(self):
        return self.session


class _App:
    def __init__(self) -> None:
        self.updates = 0
        self.on_update = None

    async def next_update_async(self) -> None:
        self.updates += 1
        if self.on_update:
            self.on_update()


def _runtime(monkeypatch):
    source = _Prim(
        {
            "points": _Attr(samples={0.2: [(2.0, 0.0, 0.0)] * 4}),
            "curveVertexCounts": _Attr(default=[2, 2]),
            "extent": _Attr(samples={0.2: [(2.0, 0.0, 0.0)] * 2}),
            SPEED_PRIMVAR_ATTRIBUTE: _Attr(samples={0.2: [2.0] * 4}),
        }
    )
    visible = _Prim(
        {
            "points": _Attr(default=[(1.0, 0.0, 0.0)] * 4, name="points"),
            "extent": _Attr(default=[(1.0, 0.0, 0.0)] * 2, name="extent"),
            SPEED_PRIMVAR_ATTRIBUTE: _Attr(default=[1.0] * 4, name="speed"),
            SOURCE_TIME_ATTRIBUTE: _Attr(default=0.0, name="sourceTime"),
            "curveVertexCounts": _Attr(default=[2, 2], name="curveVertexCounts"),
        }
    )
    stage = _Stage(
        {
            CACHE_PLAYBACK_SOURCE_CURVES_PATH: source,
            CACHE_PLAYBACK_CURVES_PATH: visible,
        }
    )
    app = _App()
    _install_modules(monkeypatch, stage, app)
    runtime = _Runtime()
    runtime.reset_streamlines_cached_state_runtime_state()
    runtime._streamlines_cache_active_sample_index = 0
    runtime._streamlines_loaded_cache_metadata = SimpleNamespace(
        states=(
            SimpleNamespace(sample_index=1, time_code=0.2, source_time_seconds=0.2),
        )
    )
    return runtime, stage, app


def _sample(index):
    return SimpleNamespace(sample_index=index)


def _install_modules(monkeypatch, stage, app) -> None:
    omni = ModuleType("omni")
    omni.__path__ = []
    kit = ModuleType("omni.kit")
    kit.__path__ = []
    kit_app = ModuleType("omni.kit.app")
    kit_app.get_app = lambda: app
    usd_module = ModuleType("omni.usd")
    usd_module.get_context = lambda: SimpleNamespace(get_stage=lambda: stage)
    pxr = ModuleType("pxr")
    pxr.__path__ = []
    sdf = ModuleType("pxr.Sdf")
    sdf.ChangeBlock = _ChangeBlock
    usd = ModuleType("pxr.Usd")
    usd.TimeCode = _TimeCode
    usd_geom = ModuleType("pxr.UsdGeom")
    usd_geom.BasisCurves = _Curves
    omni.kit = kit
    omni.usd = usd_module
    kit.app = kit_app
    pxr.Sdf = sdf
    pxr.Usd = usd
    pxr.UsdGeom = usd_geom
    for module in (omni, kit, kit_app, usd_module, pxr, sdf, usd, usd_geom):
        monkeypatch.setitem(sys.modules, module.__name__, module)


class _ChangeBlock:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _TimeCode:
    def __init__(self, value) -> None:
        self.value = value
