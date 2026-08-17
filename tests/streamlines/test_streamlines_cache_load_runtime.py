"""Production-path regressions for Streamlines cache-load verification."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from digital_twin_runtime_suite.app.streamlines import cache_runtime
from digital_twin_runtime_suite.app.streamlines.cache import (
    CACHE_PLAYBACK_CURVES_PATH,
)
from digital_twin_runtime_suite.app.streamlines.cache_runtime import (
    StreamlinesCacheRuntimeMixin,
    StreamlinesPresentationCancelled,
)
from digital_twin_runtime_suite.app.streamlines.speed import (
    SPEED_PRIMVAR_ATTRIBUTE,
)


def test_cache_load_verifies_speed_primvar_with_usd_time_codes(
    monkeypatch,
    tmp_path,
) -> None:
    stage = _Stage(with_speed=True)
    runtime, paths = _runtime(tmp_path, stage)
    _install_cache_load_modules(monkeypatch, stage)
    _install_validated_cache_contract(monkeypatch, runtime, paths, runtime.metadata)

    result = asyncio.run(runtime.load_streamlines_cache_in_kit())

    assert result.active_sample_index == 0
    assert runtime.selected is True
    assert stage.GetSessionLayer().subLayerPaths == [
        paths.geometry_path.resolve().as_posix()
    ]
    assert runtime.stop_count == 1


def test_sanity_load_verifies_the_real_cache_without_automatic_playback(
    monkeypatch,
    tmp_path,
) -> None:
    stage = _Stage(with_speed=True)
    runtime, paths = _runtime(tmp_path, stage)
    runtime.config.simulation_cache.streamlines_presentation_period_seconds = 0.2
    _install_cache_load_modules(monkeypatch, stage)
    _install_validated_cache_contract(monkeypatch, runtime, paths, runtime.metadata)

    asyncio.run(runtime.load_streamlines_cache_in_kit(start_playback=False))

    assert runtime.playback_start_count == 0


def test_failed_cache_load_detaches_geometry_and_clears_playback_state(
    monkeypatch,
    tmp_path,
) -> None:
    stage = _Stage(with_speed=False)
    runtime, paths = _runtime(tmp_path, stage)
    _install_cache_load_modules(monkeypatch, stage)
    _install_validated_cache_contract(monkeypatch, runtime, paths, runtime.metadata)

    with pytest.raises(RuntimeError, match="missing its raw vertex speed"):
        asyncio.run(runtime.load_streamlines_cache_in_kit())

    assert stage.GetSessionLayer().subLayerPaths == []
    assert runtime._streamlines_loaded_cache_metadata is None
    assert runtime._streamlines_loaded_cache_paths is None
    assert runtime._streamlines_cache_playback_contract is None
    assert runtime._streamlines_cache_active_sample_index is None


def test_stale_cache_load_cannot_start_playback_after_composition(
    monkeypatch,
    tmp_path,
) -> None:
    """A cancelled 4.2 candidate cannot start its scheduler after a late load."""

    stage = _Stage(with_speed=True)
    runtime, paths = _runtime(tmp_path, stage)
    runtime.config.simulation_cache.streamlines_presentation_period_seconds = 0.2
    _install_cache_load_modules(monkeypatch, stage)
    _install_validated_cache_contract(monkeypatch, runtime, paths, runtime.metadata)
    cancellation_requested = False

    async def select_then_cancel(_phase_seconds: float):
        nonlocal cancellation_requested
        runtime.selected = True
        cancellation_requested = True
        return SimpleNamespace(
            sample=SimpleNamespace(ordinal=1, total=2, sample_index=0)
        )

    runtime.select_streamlines_cache_state_in_kit = select_then_cancel

    with pytest.raises(StreamlinesPresentationCancelled):
        asyncio.run(
            runtime.load_streamlines_cache_in_kit(
                cancellation_requested=lambda: cancellation_requested,
            )
        )

    assert runtime.playback_start_count == 0
    assert stage.GetSessionLayer().subLayerPaths == []
    assert runtime._streamlines_cache_playback_contract is None


def _runtime(tmp_path: Path, stage: "_Stage") -> tuple["_LoadRuntime", object]:
    geometry_path = tmp_path / "streamlines.usdc"
    metadata_path = tmp_path / "streamlines.json"
    geometry_path.write_bytes(b"persisted cache")
    metadata_path.write_text("{}", encoding="utf-8")
    states = (
        SimpleNamespace(time_code=0.0, source_time_seconds=0.0, point_count=2),
        SimpleNamespace(time_code=12.0, source_time_seconds=0.2, point_count=2),
    )
    metadata = SimpleNamespace(
        states=states,
        sample_count=2,
        settings=object(),
        time_codes_per_second=60.0,
    )
    paths = SimpleNamespace(
        geometry_path=geometry_path,
        metadata_path=metadata_path,
    )
    return _LoadRuntime(stage, metadata), paths


def _install_validated_cache_contract(monkeypatch, runtime, paths, metadata) -> None:
    monkeypatch.setattr(cache_runtime, "streamlines_cache_paths", lambda *_: paths)
    monkeypatch.setattr(
        cache_runtime,
        "load_streamlines_cache_metadata",
        lambda _path: metadata,
    )
    monkeypatch.setattr(
        cache_runtime,
        "validate_streamlines_cache",
        lambda *_args, **_kwargs: SimpleNamespace(valid=True),
    )
    monkeypatch.setattr(
        cache_runtime,
        "cached_playback_contract_from_validated_cache",
        lambda *_args: "validated-playback-contract",
    )

    async def validated_receipt():
        return SimpleNamespace(
            inspection=SimpleNamespace(
                classification="VALID",
                message="Cache receipt is valid.",
                metadata=metadata,
                paths=paths,
            ),
            source=object(),
        )

    runtime.ensure_current_streamlines_cache_validation_in_background = (
        validated_receipt
    )


def _install_cache_load_modules(monkeypatch, stage: "_Stage") -> None:
    omni = _package("omni")
    kit = _package("omni.kit")
    kit_app = ModuleType("omni.kit.app")
    kit_app.get_app = lambda: _App()
    usd_context = ModuleType("omni.usd")
    usd_context.get_context = lambda: SimpleNamespace(get_stage=lambda: stage)
    pxr = _package("pxr")
    usd = ModuleType("pxr.Usd")
    usd.TimeCode = float
    usd_geom = ModuleType("pxr.UsdGeom")
    usd_geom.BasisCurves = lambda _prim: stage.curves

    omni.kit = kit
    omni.usd = usd_context
    kit.app = kit_app
    pxr.Usd = usd
    pxr.UsdGeom = usd_geom
    for module in (omni, kit, kit_app, usd_context, pxr, usd, usd_geom):
        monkeypatch.setitem(sys.modules, module.__name__, module)


class _LoadRuntime(StreamlinesCacheRuntimeMixin):
    def __init__(self, stage: "_Stage", metadata) -> None:
        self._flow_lifecycle_state = "DETACHED"
        self.config = SimpleNamespace(
            repo_root=Path("."),
            simulation_cache=SimpleNamespace(
                streamlines_presentation_period_seconds=None,
            ),
        )
        self.stage = stage
        self.metadata = metadata
        self.stop_count = 0
        self.playback_start_count = 0
        self.selected = False
        self._streamlines_loaded_cache_metadata = "stale-metadata"
        self._streamlines_loaded_cache_paths = None
        self._streamlines_cache_playback_contract = "stale-contract"
        self._streamlines_cache_active_sample_index = 9

    def resolve_current_airflow_dataset(self):
        binding = SimpleNamespace(
            workload_mode="Nominal",
            dataset_identity="server/load_normal",
        )
        return binding, object()

    def _streamlines_cache_expected_contract(self, **_kwargs):
        return {"source": object(), "settings_signature": "settings"}

    async def stop_streamlines_cached_playback_in_kit(self):
        self.stop_count += 1
        return None

    async def release_streamlines_timeline_control_in_kit(self):
        return await self.stop_streamlines_cached_playback_in_kit()

    async def select_streamlines_cache_state_in_kit(self, _phase_seconds: float):
        self.selected = True
        return SimpleNamespace(
            sample=SimpleNamespace(ordinal=1, total=2, sample_index=0)
        )

    async def start_streamlines_cached_playback_in_kit(self, **_kwargs) -> None:
        self.playback_start_count += 1

    def _streamlines_carb_logger(self):
        return None


class _App:
    async def next_update_async(self) -> None:
        return None


class _Stage:
    def __init__(self, *, with_speed: bool) -> None:
        self._session_layer = SimpleNamespace(subLayerPaths=[])
        self._edit_target = object()
        self.curves_prim = _Prim(valid=True)
        speed = (
            _Attribute({0.0: (5.0, 2.0), 12.0: (3.0, 4.0)})
            if with_speed
            else _InvalidAttribute()
        )
        self.curves = _Curves(speed)

    def GetTimeCodesPerSecond(self) -> float:
        return 60.0

    def GetSessionLayer(self):
        return self._session_layer

    def GetEditTarget(self):
        return self._edit_target

    def SetEditTarget(self, target) -> None:
        self._edit_target = target

    def RemovePrim(self, _path: str) -> None:
        return None

    def GetPrimAtPath(self, path: str):
        if path == CACHE_PLAYBACK_CURVES_PATH:
            return self.curves_prim
        return _Prim(valid=False)


class _Curves:
    def __init__(self, speed) -> None:
        self._prim = _CurvePrim(speed)

    def GetPointsAttr(self):
        return _Attribute({0.0: (), 12.0: ()})

    def GetPrim(self):
        return self._prim


class _CurvePrim:
    def __init__(self, speed) -> None:
        self._attributes = {
            "dtrs:sourceTime": _Attribute({0.0: 0.0, 12.0: 0.2}),
            SPEED_PRIMVAR_ATTRIBUTE: speed,
        }

    def GetAttribute(self, name: str):
        return self._attributes.get(name)


class _Prim:
    def __init__(self, *, valid: bool) -> None:
        self._valid = valid

    def IsValid(self) -> bool:
        return self._valid


class _Attribute:
    def __init__(self, values_by_time: dict[float, object]) -> None:
        self._values_by_time = values_by_time

    def IsValid(self) -> bool:
        return True

    def GetTimeSamples(self):
        return tuple(self._values_by_time)

    def Get(self, time_code: float):
        return self._values_by_time.get(time_code)


class _InvalidAttribute:
    def IsValid(self) -> bool:
        return False


def _package(name: str) -> ModuleType:
    package = ModuleType(name)
    package.__path__ = []
    return package
