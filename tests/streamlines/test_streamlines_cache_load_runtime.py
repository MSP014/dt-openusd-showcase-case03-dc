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
    CACHE_PLAYBACK_ROOT_PATH,
    CACHE_PLAYBACK_SOURCE_CURVES_PATH,
    CACHE_PLAYBACK_SOURCE_PATH,
)
from digital_twin_runtime_suite.app.streamlines.cache_runtime import (
    StreamlinesCacheRuntimeMixin,
    StreamlinesPresentationCancelled,
)
from digital_twin_runtime_suite.app.streamlines.mesh_cache import (
    MESH_CACHE_GEOMETRY_PATH,
    MESH_SPEED_ATTRIBUTE,
)
from digital_twin_runtime_suite.app.streamlines.playback import (
    CachedPlaybackContract,
)
from digital_twin_runtime_suite.app.streamlines.temporal import (
    TemporalSourceSample,
)


def _prepared_contract(binding) -> CachedPlaybackContract:
    return CachedPlaybackContract(
        workload=binding.workload_mode,
        dataset_identity=binding.dataset_identity,
        sample_interval_seconds=0.2,
        samples=(
            TemporalSourceSample(
                ordinal=1,
                total=1,
                sample_index=0,
                source_vti=Path("nominal_1001.vti"),
                source_time_seconds=0.0,
                time_code=0.0,
            ),
        ),
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
    assert runtime._streamlines_mesh_points_time_codes == (0.0, 12.0)
    assert stage.GetSessionLayer().subLayerPaths == []
    assert stage.reference.assetPath == paths.geometry_path.resolve().as_posix()
    assert stage.reference.primPath == CACHE_PLAYBACK_ROOT_PATH
    assert stage.reference_owner == CACHE_PLAYBACK_SOURCE_PATH
    assert stage.source_visibility is None
    assert runtime.stop_count == 1


def test_normal_to_streamlines_load_changes_only_local_reference(
    monkeypatch,
    tmp_path,
) -> None:
    stage = _Stage(with_speed=True)
    stage.GetSessionLayer().subLayerPaths.append("main-session.usda")
    stage.GetRootLayer().subLayerPaths.append("server-scene.usda")
    runtime, paths = _runtime(tmp_path, stage)
    _install_cache_load_modules(monkeypatch, stage)
    _install_validated_cache_contract(monkeypatch, runtime, paths, runtime.metadata)

    asyncio.run(runtime.load_streamlines_cache_in_kit())

    evidence = runtime.streamlines_presentation_reference_snapshot()
    assert stage.GetSessionLayer().subLayerPaths == ["main-session.usda"]
    assert stage.GetRootLayer().subLayerPaths == ["server-scene.usda"]
    assert evidence.reference_swap_passed is True
    assert stage.GetPrimAtPath(CACHE_PLAYBACK_CURVES_PATH).IsValid()


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

    with pytest.raises(RuntimeError, match="Mesh speed samples"):
        asyncio.run(runtime.load_streamlines_cache_in_kit())

    assert stage.GetSessionLayer().subLayerPaths == []
    assert stage.reference is None
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
    cancellation_checks = 0

    def cancellation_requested() -> bool:
        nonlocal cancellation_checks
        cancellation_checks += 1
        return cancellation_checks >= 4

    with pytest.raises(StreamlinesPresentationCancelled):
        asyncio.run(
            runtime.load_streamlines_cache_in_kit(
                cancellation_requested=cancellation_requested,
            )
        )

    assert runtime.playback_start_count == 0
    assert stage.GetSessionLayer().subLayerPaths == []
    assert stage.reference is None
    assert runtime._streamlines_cache_playback_contract is None


def test_target_explicit_preparation_uses_exact_binding_dataset_and_phase() -> None:
    runtime = _LoadRuntime(_Stage(with_speed=True), metadata=object())
    runtime._flow_lifecycle_state = "ATTACHED"
    binding = SimpleNamespace(
        workload_mode="Nominal",
        dataset_identity="server/load_normal",
    )
    dataset = object()
    receipt = SimpleNamespace(
        inspection=SimpleNamespace(
            classification="VALID",
            message="Cache receipt is valid.",
        ),
        source=object(),
    )
    observed = {}

    async def ensure(received_binding, received_dataset):
        observed["binding"] = received_binding
        observed["dataset"] = received_dataset
        return receipt

    async def load(**kwargs):
        observed["load"] = kwargs
        runtime._streamlines_cache_playback_contract = _prepared_contract(binding)

    runtime.ensure_streamlines_cache_validation_in_background = ensure
    runtime.load_streamlines_cache_in_kit = load

    resolution = asyncio.run(
        runtime.prepare_streamlines_cached_target_in_kit(
            binding,
            dataset,
            7.2,
            expected_sample_index=0,
            expected_source_vti=Path("nominal_1001.vti"),
        )
    )

    assert observed["binding"] is binding
    assert observed["dataset"] is dataset
    assert observed["load"]["validated_receipt"] is receipt
    assert observed["load"]["start_playback"] is False
    assert observed["load"]["presentation_hidden"] is True
    assert observed["load"]["allow_attached_flow"] is True
    assert resolution.sample.source_vti == Path("nominal_1001.vti")


def test_target_explicit_preparation_reuses_the_supplied_valid_receipt() -> None:
    runtime = _LoadRuntime(_Stage(with_speed=True), metadata=object())
    binding = SimpleNamespace(
        workload_mode="Critical",
        dataset_identity="server/load_critical",
    )
    receipt = SimpleNamespace(
        inspection=SimpleNamespace(
            classification="VALID",
            message="Cache receipt is valid.",
        )
    )

    async def unexpected_validation(*_args):
        raise AssertionError("validated target receipt must be reused")

    async def load(**kwargs):
        assert kwargs["validated_receipt"] is receipt
        runtime._streamlines_cache_playback_contract = _prepared_contract(binding)

    runtime.ensure_streamlines_cache_validation_in_background = unexpected_validation
    runtime.load_streamlines_cache_in_kit = load

    result = asyncio.run(
        runtime.prepare_streamlines_cached_target_in_kit(
            binding,
            object(),
            7.2,
            expected_sample_index=0,
            expected_source_vti=Path("nominal_1001.vti"),
            validated_receipt=receipt,
        )
    )

    assert result.sample.sample_index == 0


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
    binding = SimpleNamespace(
        workload_mode="Nominal",
        dataset_identity="server/load_normal",
    )
    monkeypatch.setattr(
        cache_runtime,
        "cached_playback_contract_from_validated_cache",
        lambda *_args: _prepared_contract(binding),
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
    # These tests isolate reference attachment and playback lifecycle. Constant-
    # topology array verification has its own focused contract tests.
    monkeypatch.setattr(
        cache_runtime,
        "_validate_composed_constant_topology_cache",
        lambda *_args, **_kwargs: None,
    )

    def attach_centerline_fixture(runtime, target_stage, cache_paths) -> None:
        runtime._detach_streamlines_cache_playback_layer(target_stage)
        source = target_stage.OverridePrim(CACHE_PLAYBACK_SOURCE_PATH)
        source.GetReferences().SetReferences(
            [
                _Reference(
                    cache_paths.geometry_path.resolve().as_posix(),
                    CACHE_PLAYBACK_ROOT_PATH,
                )
            ]
        )
        runtime._streamlines_loaded_cache_paths = cache_paths
        runtime._streamlines_presentation_reference_snapshot = SimpleNamespace(
            reference_swap_passed=True,
        )

    monkeypatch.setattr(
        cache_runtime.StreamlinesCacheRuntimeMixin,
        "_attach_streamlines_cache_playback_layer",
        attach_centerline_fixture,
    )
    omni = _package("omni")
    kit = _package("omni.kit")
    kit_app = ModuleType("omni.kit.app")
    kit_app.get_app = lambda: _App()
    usd_context = ModuleType("omni.usd")
    usd_context.get_context = lambda: SimpleNamespace(get_stage=lambda: stage)
    pxr = _package("pxr")
    sdf = ModuleType("pxr.Sdf")
    sdf.Reference = _Reference
    sdf.Path = str
    usd = ModuleType("pxr.Usd")
    usd.TimeCode = float
    usd_geom = ModuleType("pxr.UsdGeom")
    usd_geom.Mesh = lambda _prim: stage.mesh
    usd_geom.Xform = _Xform
    usd_geom.Tokens = SimpleNamespace(invisible="invisible")

    omni.kit = kit
    omni.usd = usd_context
    kit.app = kit_app
    pxr.Usd = usd
    pxr.UsdGeom = usd_geom
    pxr.Sdf = sdf
    for module in (omni, kit, kit_app, usd_context, pxr, sdf, usd, usd_geom):
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
        self.material_apply_count = 0
        self.selected = False
        self.selected_phase = None
        self._streamlines_loaded_cache_metadata = "stale-metadata"
        self._streamlines_loaded_cache_paths = None
        self._streamlines_presentation_reference_snapshot = None
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
        return await self.select_streamlines_cached_contract_state_in_kit(
            self._streamlines_cache_playback_contract,
            _phase_seconds,
        )

    async def select_streamlines_cached_contract_state_in_kit(
        self,
        _contract,
        phase_seconds: float,
    ):
        self.selected = True
        self.selected_phase = phase_seconds
        return SimpleNamespace(
            sample=SimpleNamespace(
                ordinal=1,
                total=2,
                sample_index=0,
                source_vti=Path("nominal_1001.vti"),
            )
        )

    async def start_streamlines_cached_playback_in_kit(self, **_kwargs) -> None:
        self.playback_start_count += 1

    def apply_streamlines_presentation_in_kit(self):
        self.material_apply_count += 1
        return SimpleNamespace(material_bound=True)

    def invalidate_streamlines_cached_state_updates(self) -> None:
        return None

    def prepare_streamlines_cached_geometry_in_kit(self, *_args, **_kwargs):
        return None

    def _streamlines_carb_logger(self):
        return None


class _App:
    async def next_update_async(self) -> None:
        return None


class _Stage:
    def __init__(self, *, with_speed: bool) -> None:
        self._session_layer = SimpleNamespace(subLayerPaths=[])
        self._root_layer = SimpleNamespace(subLayerPaths=[])
        self._edit_target = object()
        self.reference = None
        self.reference_owner = None
        self.source_visibility = None
        self.presentation_prim = _PresentationPrim(self)
        self.source_prim = _PresentationPrim(self, CACHE_PLAYBACK_SOURCE_PATH)
        self.mesh_prim = _MeshPrim(with_speed=with_speed)
        self.mesh = _Mesh(self.mesh_prim)

    def GetTimeCodesPerSecond(self) -> float:
        return 60.0

    def GetSessionLayer(self):
        return self._session_layer

    def GetRootLayer(self):
        return self._root_layer

    def GetEditTarget(self):
        return self._edit_target

    def SetEditTarget(self, target) -> None:
        self._edit_target = target

    def RemovePrim(self, path: str) -> None:
        if path == CACHE_PLAYBACK_ROOT_PATH:
            self.reference = None

    def OverridePrim(self, path: str):
        if path == CACHE_PLAYBACK_ROOT_PATH:
            return self.presentation_prim
        if path == CACHE_PLAYBACK_SOURCE_PATH:
            return self.source_prim
        raise AssertionError(path)

    def GetPrimAtPath(self, path: str):
        if path == MESH_CACHE_GEOMETRY_PATH:
            return self.mesh_prim
        if path in (CACHE_PLAYBACK_CURVES_PATH, CACHE_PLAYBACK_SOURCE_CURVES_PATH):
            return _Prim(valid=True)
        if path == CACHE_PLAYBACK_ROOT_PATH:
            return self.presentation_prim
        if path == CACHE_PLAYBACK_SOURCE_PATH:
            return self.source_prim
        return _Prim(valid=False)


class _Reference:
    def __init__(self, asset_path: str, prim_path: str) -> None:
        self.assetPath = asset_path
        self.primPath = prim_path


class _References:
    def __init__(self, stage: _Stage, owner=None) -> None:
        self._stage = stage
        self._owner = owner

    def SetReferences(self, references) -> None:
        assert len(references) == 1
        self._stage.reference = references[0]
        self._stage.reference_owner = self._owner


class _PresentationPrim:
    def __init__(self, stage: _Stage, path=None) -> None:
        self._stage = stage
        self.path = path

    def IsValid(self) -> bool:
        return self._stage.reference is not None

    def GetReferences(self):
        return _References(self._stage, self.path)


class _VisibilityAttribute:
    def __init__(self, prim) -> None:
        self._prim = prim

    def Set(self, _value) -> bool:
        self._prim._stage.source_visibility = _value
        return True


class _Xform:
    @staticmethod
    def Define(stage: _Stage, path: str):
        return _Xform(stage.OverridePrim(path))

    def __init__(self, prim) -> None:
        self._prim = prim

    def GetPrim(self):
        return self._prim

    def CreateVisibilityAttr(self):
        return _VisibilityAttribute(self._prim)


class _Mesh:
    def __init__(self, prim) -> None:
        self._prim = prim

    def GetPointsAttr(self):
        return _Attribute({0.0: ((0.0, 0.0, 0.0),), 12.0: ((1.0, 0.0, 0.0),)})

    def GetFaceVertexCountsAttr(self):
        return _Attribute({})

    def GetFaceVertexIndicesAttr(self):
        return _Attribute({})


class _MeshPrim:
    def __init__(self, *, with_speed: bool) -> None:
        speed = (
            _Attribute({0.0: (5.0, 2.0), 12.0: (3.0, 4.0)})
            if with_speed
            else _Attribute({})
        )
        self._attributes = {
            "dtrs:sourceTime": _Attribute({0.0: 0.0, 12.0: 0.2}),
            MESH_SPEED_ATTRIBUTE: speed,
        }

    def IsValid(self) -> bool:
        return True

    def GetTypeName(self) -> str:
        return "Mesh"

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


def _package(name: str) -> ModuleType:
    package = ModuleType(name)
    package.__path__ = []
    return package
