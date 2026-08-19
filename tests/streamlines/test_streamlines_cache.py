"""Focused cache-contract tests without Kit-CAE execution."""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import replace
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from digital_twin_runtime_suite.app.flow.static_source import (
    StaticVelocitySourceDescriptor,
)
from digital_twin_runtime_suite.app.streamlines import cache_runtime, recompute_runtime
from digital_twin_runtime_suite.app.streamlines.cache import (
    CACHE_PLAYBACK_ROOT_PATH,
    CACHE_PLAYBACK_SOURCE_PATH,
    CACHE_SCHEMA_VERSION,
    StreamlinesCacheMetadata,
    StreamlinesCacheOwnership,
    StreamlinesCacheState,
    build_streamlines_cache_metadata,
    cache_settings_differences,
    file_sha256,
    geometry_signature,
    replace_streamlines_cache_artifacts,
    serialise_streamlines_cache_metadata,
    source_signature_from_temporal_source,
    streamlines_cache_build_mode,
    streamlines_cache_paths,
    streamlines_cache_settings,
    streamlines_settings_signature,
    topology_signature,
    validate_streamlines_cache,
    vti_file_identity,
)
from digital_twin_runtime_suite.app.streamlines.cache_runtime import (
    StreamlinesCacheRuntimeMixin,
)
from digital_twin_runtime_suite.app.streamlines.proof import (
    build_streamlines_operator_request,
)
from digital_twin_runtime_suite.app.streamlines.runtime import StreamlinesRuntimeMixin
from digital_twin_runtime_suite.app.streamlines.temporal import (
    TemporalVelocitySourceDescriptor,
)


def _source(tmp_path: Path) -> TemporalVelocitySourceDescriptor:
    paths = []
    for index in range(2):
        path = tmp_path / f"sample_{index}.vti"
        path.write_bytes(f"vti-{index}".encode("utf-8"))
        paths.append(path)
    descriptor = StaticVelocitySourceDescriptor(
        workload="Nominal",
        dataset_identity="server/load_normal",
        sample_index=0,
        vti_path=paths[0],
        dataset_prim_path="/DTRS_HoudiniVelocity/VTKImageData",
        velocity_field_prim_path="/DTRS_HoudiniVelocity/PointData/vel",
        world_bounds=((0.0, 0.0, 0.0), (1.0, 1.0, 1.0)),
        dimensions=(2, 2, 101),
        spacing=(0.01, 0.01, 0.01),
        origin=(0.0, 0.0, 0.0),
        source_origin=(0.0, 0.0, 0.0),
        stage_meters_per_unit=1.0,
    )
    return TemporalVelocitySourceDescriptor(
        static_descriptor=descriptor,
        velocity_paths=tuple(paths),
        sample_time_codes=(0.0, 12.0),
        time_codes_per_second=60.0,
        sample_interval_seconds=0.2,
    )


def test_cache_load_requires_detached_flow_before_importing_kit() -> None:
    runtime = _AttachedCacheLoadRuntime()

    with pytest.raises(
        RuntimeError,
        match="Load Streamlines Cache requires Flow DETACHED.",
    ):
        asyncio.run(runtime.load_streamlines_cache_in_kit())


def test_cache_readiness_messages_preserve_utf8_punctuation() -> None:
    runtime = _CacheReadinessRuntime()

    assert runtime.announce_streamlines_cache_build_ready() == (
        'Ready — Press "Build Streamlines Cache".'
    )
    assert runtime.announce_streamlines_cache_load_ready() == (
        'Ready — Press "Load Streamlines Cache".'
    )

    assert runtime.announce_streamlines_cache_build_ready() == (
        'Ready \u2014 Press "Build Streamlines Cache".'
    )
    assert runtime.announce_streamlines_cache_load_ready() == (
        'Ready \u2014 Press "Load Streamlines Cache".'
    )


def test_cache_load_progress_reports_to_ui_and_kit_log() -> None:
    runtime = _CacheLoadProgressRuntime()
    statuses: list[str] = []

    runtime._report_streamlines_cache_load(
        event="PROGRESS",
        message="Loading Streamlines cache: attaching persisted geometry.",
        status_callback=statuses.append,
    )

    assert statuses == ["Loading Streamlines cache: attaching persisted geometry."]
    assert runtime.logger.messages == [
        "DTRS STREAMLINES | CACHE_LOAD | PROGRESS\n"
        "status=Loading Streamlines cache: attaching persisted geometry."
    ]


def test_cache_load_waiting_heartbeat_reports_stalled_kit_frame() -> None:
    runtime = _CacheLoadProgressRuntime()
    statuses: list[str] = []

    async def delayed_frame() -> None:
        await asyncio.sleep(0.01)

    async def wait_for_delayed_frame() -> None:
        await runtime._await_streamlines_cache_update(
            _CacheLoadApp(delayed_frame()),
            status_callback=statuses.append,
            started_at=0.0,
            heartbeat_seconds=0.001,
        )

    asyncio.run(wait_for_delayed_frame())

    assert statuses
    assert statuses[0].startswith(
        "Loading Streamlines cache: waiting for Kit composition "
    )
    assert all("CACHE_LOAD | WAITING" in message for message in runtime.logger.messages)


class _AttachedCacheLoadRuntime(StreamlinesCacheRuntimeMixin):
    _flow_lifecycle_state = "ATTACHED"


class _CacheReadinessRuntime(StreamlinesCacheRuntimeMixin):
    def _streamlines_carb_logger(self):
        return None


class _CacheLoadLogger:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def log_warn(self, message: str) -> None:
        self.messages.append(message.split("] ", maxsplit=1)[1])


class _CacheLoadProgressRuntime(StreamlinesCacheRuntimeMixin):
    def __init__(self) -> None:
        self.logger = _CacheLoadLogger()

    def _streamlines_carb_logger(self):
        return self.logger


class _CacheLoadApp:
    def __init__(self, update) -> None:
        self._update = update

    def next_update_async(self):
        return self._update


def _state(
    source: TemporalVelocitySourceDescriptor, index: int
) -> StreamlinesCacheState:
    points = (
        (float(index), 0.0, 0.0),
        (float(index), 0.5, 0.0),
        (float(index), 1.0, 0.0),
        (float(index), 1.5, 0.0),
    )
    bounds = ((float(index), 0.0, 0.0), (float(index), 1.5, 0.0))
    return StreamlinesCacheState(
        sample_index=index,
        source_time_seconds=(
            source.sample_time_codes[index] / source.time_codes_per_second
        ),
        time_code=source.sample_time_codes[index],
        source_vti=source.velocity_paths[index].resolve().as_posix(),
        source_vti_identity=vti_file_identity(source.velocity_paths[index]),
        curve_count=256,
        point_count=51_200,
        topology_signature=topology_signature((200,) * 256),
        geometry_signature=geometry_signature(
            curve_count=256,
            point_count=51_200,
            bounds=bounds,
            point_head=points[:3],
            point_tail=points[-3:],
        ),
        generation_ms=10.0 + index,
        bounds=bounds,
        source_point_count=4,
        source_topology_signature=topology_signature((4,)),
    )


def _metadata(tmp_path: Path):
    source = _source(tmp_path)
    geometry_path = streamlines_cache_paths(tmp_path, _ownership()).geometry_path
    geometry_path.parent.mkdir(parents=True)
    geometry_path.write_bytes(b"derived-usdc")
    request = build_streamlines_operator_request(source.static_descriptor)
    metadata = build_streamlines_cache_metadata(
        source,
        request,
        (_state(source, 0), _state(source, 1)),
        geometry_file_name=geometry_path.name,
        geometry_sha256=file_sha256(geometry_path),
    )
    return source, request, geometry_path, metadata


def _ownership() -> StreamlinesCacheOwnership:
    return StreamlinesCacheOwnership("Nominal", "server/load_normal")


def test_cache_metadata_rejects_partial_manifest_states(tmp_path: Path) -> None:
    source = _source(tmp_path)
    request = build_streamlines_operator_request(source.static_descriptor)

    with pytest.raises(ValueError, match="Partial Streamlines cache"):
        build_streamlines_cache_metadata(
            source,
            request,
            (_state(source, 0),),
            geometry_file_name="derived.usdc",
            geometry_sha256="unused",
        )


def test_cache_validation_requires_exact_source_settings_and_geometry(
    tmp_path: Path,
) -> None:
    source, request, geometry_path, metadata = _metadata(tmp_path)

    accepted = validate_streamlines_cache(
        metadata,
        source=source,
        settings_signature=streamlines_settings_signature(request),
        geometry_path=geometry_path,
    )
    rejected = validate_streamlines_cache(
        metadata,
        source=source,
        settings_signature=streamlines_settings_signature(
            replace(request, width=request.width * 2.0)
        ),
        geometry_path=geometry_path,
    )

    assert metadata.schema_version == CACHE_SCHEMA_VERSION
    assert metadata.valid is True
    assert metadata.topology_consistent is True
    assert accepted.valid is True
    assert rejected.valid is False
    assert rejected.message == "Cache settings or seed are stale."


@pytest.mark.parametrize(
    ("states_from_metadata", "expected_message"),
    (
        (lambda metadata: metadata.states[:1], "Cache state count is incomplete."),
        (
            lambda metadata: (
                metadata.states[0],
                replace(metadata.states[1], sample_index=0),
            ),
            "Cache states must have contiguous manifest indices.",
        ),
        (
            lambda metadata: (
                metadata.states[0],
                replace(metadata.states[1], sample_index=2),
            ),
            "Cache states must have contiguous manifest indices.",
        ),
        (
            lambda metadata: (
                metadata.states[0],
                replace(metadata.states[1], source_vti="unexpected.vti"),
            ),
            "Cache state VTI does not match the manifest.",
        ),
        (
            lambda metadata: (
                metadata.states[0],
                replace(metadata.states[1], source_vti_identity="unexpected"),
            ),
            "Cache state VTI identity does not match the manifest.",
        ),
        (
            lambda metadata: (
                metadata.states[0],
                replace(metadata.states[1], source_time_seconds=99.0),
            ),
            "Cache state source time does not match the manifest.",
        ),
        (
            lambda metadata: (
                metadata.states[0],
                replace(metadata.states[1], time_code=99.0),
            ),
            "Cache state time code does not match the manifest.",
        ),
    ),
)
def test_cache_validation_rejects_each_non_exact_manifest_state(
    tmp_path: Path,
    states_from_metadata,
    expected_message: str,
) -> None:
    source, request, geometry_path, metadata = _metadata(tmp_path)
    invalid_metadata = replace(
        metadata,
        states=states_from_metadata(metadata),
    )

    validation = validate_streamlines_cache(
        invalid_metadata,
        source=source,
        settings_signature=streamlines_settings_signature(request),
        geometry_path=geometry_path,
    )

    assert validation.valid is False
    assert validation.message == expected_message


@pytest.mark.parametrize("presentation_period_seconds", (0.2, 2.6, 3.0, 9.75))
def test_presentation_period_never_changes_cache_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    presentation_period_seconds: float,
) -> None:
    source, request, geometry_path, metadata = _metadata(tmp_path)
    cache_identity_before = (
        metadata.source_signature,
        metadata.settings_signature,
    )
    geometry_before = geometry_path.read_bytes()
    monkeypatch.setattr(
        recompute_runtime,
        "RECOMPUTE_PRESENTATION_PERIOD_SECONDS",
        presentation_period_seconds,
    )

    validation = validate_streamlines_cache(
        metadata,
        source=source,
        settings_signature=streamlines_settings_signature(request),
        geometry_path=geometry_path,
    )

    assert recompute_runtime.RECOMPUTE_PRESENTATION_PERIOD_SECONDS == (
        presentation_period_seconds
    )
    assert validation.valid is True
    assert metadata.source_signature == source_signature_from_temporal_source(source)
    assert (
        metadata.source_signature,
        metadata.settings_signature,
    ) == cache_identity_before
    assert geometry_path.read_bytes() == geometry_before


def test_source_timing_or_vti_identity_change_marks_cache_stale_without_mutation(
    tmp_path: Path,
) -> None:
    source, request, geometry_path, metadata = _metadata(tmp_path)
    original_geometry = geometry_path.read_bytes()
    original_metadata = serialise_streamlines_cache_metadata(metadata)
    timing_changed_source = replace(
        source,
        sample_time_codes=(0.0, 24.0),
        sample_interval_seconds=0.4,
    )

    timing_validation = validate_streamlines_cache(
        metadata,
        source=timing_changed_source,
        settings_signature=streamlines_settings_signature(request),
        geometry_path=geometry_path,
    )
    source.velocity_paths[1].write_bytes(b"replaced-vti")
    identity_validation = validate_streamlines_cache(
        metadata,
        source=source,
        settings_signature=streamlines_settings_signature(request),
        geometry_path=geometry_path,
    )

    assert timing_validation.valid is False
    assert timing_validation.message == "Cache source manifest is stale."
    assert identity_validation.valid is False
    assert identity_validation.message == "Cache source manifest is stale."
    assert geometry_path.read_bytes() == original_geometry
    assert serialise_streamlines_cache_metadata(metadata) == original_metadata


def test_workload_or_dataset_identity_change_rejects_existing_cache(
    tmp_path: Path,
) -> None:
    source, request, geometry_path, metadata = _metadata(tmp_path)
    changed_source = replace(
        source,
        static_descriptor=replace(
            source.static_descriptor,
            workload="Surge",
            dataset_identity="server/load_surge",
        ),
    )

    validation = validate_streamlines_cache(
        metadata,
        source=changed_source,
        settings_signature=streamlines_settings_signature(request),
        geometry_path=geometry_path,
    )

    assert validation.valid is False
    assert validation.message == "Cache workload or dataset differs."


def test_cache_schema_change_rejects_existing_cache(tmp_path: Path) -> None:
    source, request, geometry_path, metadata = _metadata(tmp_path)
    legacy_metadata = replace(metadata, schema_version=CACHE_SCHEMA_VERSION - 1)

    validation = validate_streamlines_cache(
        legacy_metadata,
        source=source,
        settings_signature=streamlines_settings_signature(request),
        geometry_path=geometry_path,
    )

    assert validation.valid is False
    assert validation.message == "Cache schema version is stale."


def test_cache_identity_survives_serialised_restart_reconstruction(
    tmp_path: Path,
) -> None:
    source, request, _, metadata = _metadata(tmp_path)
    persisted = StreamlinesCacheMetadata.from_dict(
        json.loads(serialise_streamlines_cache_metadata(metadata))
    )
    restart_request = replace(
        request,
        operator_path="/DTRS_KitCAE/Streamlines/RestartOnly",
        seed_path="/DTRS_KitCAE/StreamlineSeeds/RestartOnly",
        operator_type=" STANDARD ",
        direction=" FORWARD ",
    )

    assert persisted.settings == metadata.settings
    assert (
        streamlines_settings_signature(restart_request) == metadata.settings_signature
    )


def test_cache_request_ignores_importer_float_jitter(tmp_path: Path) -> None:
    source = _source(tmp_path)
    imported_descriptor = replace(
        source.static_descriptor,
        world_bounds=((-0.0000001, 0.0, 0.0), (1.0000001, 1.0, 1.0)),
    )
    build_request = StreamlinesRuntimeMixin._build_streamlines_cache_request(
        None,
        imported_descriptor,
    )
    restart_request = StreamlinesRuntimeMixin._build_streamlines_cache_request(
        None,
        source.static_descriptor,
    )

    assert streamlines_settings_signature(build_request) == (
        streamlines_settings_signature(restart_request)
    )


def test_cache_identity_changes_for_real_seed_or_settings_change(
    tmp_path: Path,
) -> None:
    _, request, _, _ = _metadata(tmp_path)
    changed = replace(
        request,
        seed_center=(request.seed_center[0] + 0.01, *request.seed_center[1:]),
    )

    assert streamlines_settings_signature(changed) != (
        streamlines_settings_signature(request)
    )
    assert cache_settings_differences(
        streamlines_cache_settings(request),
        streamlines_cache_settings(changed),
    ) == ("seed_center",)


def test_cache_validation_rejects_replaced_geometry_file(tmp_path: Path) -> None:
    source, request, geometry_path, metadata = _metadata(tmp_path)
    geometry_path.write_bytes(b"replaced-derived-usdc")

    validation = validate_streamlines_cache(
        metadata,
        source=source,
        settings_signature=streamlines_settings_signature(request),
        geometry_path=geometry_path,
    )

    assert validation.valid is False
    assert validation.message == "Cache geometry file is stale."


def test_cache_without_canonical_provenance_requires_explicit_rebuild(
    tmp_path: Path,
) -> None:
    source, request, geometry_path, metadata = _metadata(tmp_path)
    legacy_payload = metadata.to_dict()
    legacy_payload.pop("settings")
    legacy_metadata = StreamlinesCacheMetadata.from_dict(legacy_payload)

    validation = validate_streamlines_cache(
        legacy_metadata,
        source=source,
        settings_signature=streamlines_settings_signature(request),
        geometry_path=geometry_path,
    )

    assert validation.valid is False
    assert "canonical settings provenance is unavailable" in validation.message


def _write_cache_pair(paths, label: str, *, partial: bool = False) -> None:
    paths.directory.mkdir(parents=True, exist_ok=True)
    geometry_path = paths.partial_geometry_path if partial else paths.geometry_path
    metadata_path = paths.partial_metadata_path if partial else paths.metadata_path
    geometry_path.write_bytes(f"{label}-geometry".encode("utf-8"))
    metadata_path.write_text(f"{label}-metadata", encoding="utf-8")


def test_explicit_rebuild_replaces_existing_complete_cache(tmp_path: Path) -> None:
    paths = streamlines_cache_paths(tmp_path, _ownership())
    _write_cache_pair(paths, "old")
    _write_cache_pair(paths, "new", partial=True)

    assert streamlines_cache_build_mode(paths) == "REBUILD"
    replace_streamlines_cache_artifacts(paths)

    assert paths.geometry_path.read_bytes() == b"new-geometry"
    assert paths.metadata_path.read_text(encoding="utf-8") == "new-metadata"
    assert paths.partial_geometry_path.exists() is False
    assert paths.partial_metadata_path.exists() is False


def test_failed_rebuild_restores_previous_valid_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = streamlines_cache_paths(tmp_path, _ownership())
    _write_cache_pair(paths, "old")
    _write_cache_pair(paths, "new", partial=True)
    original_replace = Path.replace

    def fail_metadata_replace(path: Path, target: Path) -> Path:
        if path == paths.partial_metadata_path:
            raise OSError("simulated metadata replacement failure")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_metadata_replace)

    with pytest.raises(OSError, match="simulated metadata"):
        replace_streamlines_cache_artifacts(paths)

    assert paths.geometry_path.read_bytes() == b"old-geometry"
    assert paths.metadata_path.read_text(encoding="utf-8") == "old-metadata"
    assert paths.partial_metadata_path.exists() is True


def test_partial_cache_is_never_accepted_for_playback(tmp_path: Path) -> None:
    source, request, _, metadata = _metadata(tmp_path)
    paths = streamlines_cache_paths(tmp_path, _ownership())
    paths.geometry_path.unlink()
    _write_cache_pair(paths, "partial", partial=True)

    validation = validate_streamlines_cache(
        metadata,
        source=source,
        settings_signature=streamlines_settings_signature(request),
        geometry_path=paths.geometry_path,
    )

    assert validation.valid is False
    assert validation.message == "Cache geometry file is missing."
    assert streamlines_cache_build_mode(paths) == "REBUILD"


def test_stale_cache_requires_explicit_rebuild_without_replacing_it(
    tmp_path: Path,
) -> None:
    source, request, geometry_path, metadata = _metadata(tmp_path)
    original_geometry = geometry_path.read_bytes()

    validation = validate_streamlines_cache(
        metadata,
        source=source,
        settings_signature=streamlines_settings_signature(
            replace(request, seed_radius=request.seed_radius * 2.0)
        ),
        geometry_path=geometry_path,
    )

    assert validation.valid is False
    assert validation.message == "Cache settings or seed are stale."
    assert (
        streamlines_cache_build_mode(streamlines_cache_paths(tmp_path, _ownership()))
        == "REBUILD"
    )
    assert geometry_path.read_bytes() == original_geometry


def test_cache_startup_inspection_never_starts_a_build(tmp_path: Path) -> None:
    paths = streamlines_cache_paths(tmp_path, _ownership())

    assert streamlines_cache_build_mode(paths) == "NEW"
    assert paths.directory.exists() is False


def test_cache_layer_attach_and_detach_keep_persistence_outside_the_stage(
    monkeypatch,
    tmp_path: Path,
) -> None:
    pxr = ModuleType("pxr")
    sdf = ModuleType("pxr.Sdf")
    sdf.Reference = lambda asset, prim: SimpleNamespace(
        assetPath=asset,
        primPath=prim,
    )
    sdf.Path = str
    usd_geom = ModuleType("pxr.UsdGeom")
    usd_geom.Xform = _CacheXform
    usd_geom.Tokens = SimpleNamespace(invisible="invisible")
    pxr.Sdf = sdf
    pxr.UsdGeom = usd_geom
    monkeypatch.setitem(sys.modules, "pxr", pxr)
    monkeypatch.setitem(sys.modules, "pxr.Sdf", sdf)
    monkeypatch.setitem(sys.modules, "pxr.UsdGeom", usd_geom)
    paths = streamlines_cache_paths(tmp_path, _ownership())
    target_paths = streamlines_cache_paths(
        tmp_path,
        StreamlinesCacheOwnership("Idle", "server/load_idle"),
    )
    for cache_paths in (paths, target_paths):
        cache_paths.geometry_path.parent.mkdir(parents=True, exist_ok=True)
        cache_paths.geometry_path.write_bytes(b"mesh")
        cache_paths.metadata_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        cache_runtime,
        "mesh_cache_paths",
        lambda geometry_path: (
            geometry_path,
            geometry_path.with_suffix(".json"),
        ),
    )
    monkeypatch.setattr(
        cache_runtime,
        "load_streamlines_mesh_cache_receipt",
        lambda path: SimpleNamespace(
            workload=("Idle" if "idle" in path.as_posix() else "Nominal"),
            dataset_identity=(
                "server/load_idle"
                if "idle" in path.as_posix()
                else "server/load_normal"
            ),
            profile_id="global_flow_path",
            source_geometry_sha256="geometry",
        ),
    )
    monkeypatch.setattr(
        cache_runtime,
        "load_streamlines_cache_metadata",
        lambda path: SimpleNamespace(
            workload=("Idle" if "idle" in path.as_posix() else "Nominal"),
            dataset_identity=(
                "server/load_idle"
                if "idle" in path.as_posix()
                else "server/load_normal"
            ),
            profile_id="global_flow_path",
            geometry_sha256="geometry",
        ),
    )
    stage = _CacheStage()
    stage.GetSessionLayer().subLayerPaths.append("main-session.usda")
    stage.GetRootLayer().subLayerPaths.append("server-scene.usda")
    runtime = _CacheLayerRuntime(tmp_path)

    runtime._attach_streamlines_cache_playback_layer(stage, paths)

    assert stage.GetSessionLayer().subLayerPaths == ["main-session.usda"]
    assert stage.GetRootLayer().subLayerPaths == ["server-scene.usda"]
    assert stage.reference.assetPath == paths.geometry_path.resolve().as_posix()
    assert stage.reference.primPath == CACHE_PLAYBACK_ROOT_PATH
    runtime._attach_streamlines_cache_playback_layer(stage, target_paths)
    assert stage.reference.assetPath == (
        target_paths.geometry_path.resolve().as_posix()
    )
    assert stage.GetSessionLayer().subLayerPaths == ["main-session.usda"]
    assert stage.GetRootLayer().subLayerPaths == ["server-scene.usda"]
    runtime._detach_streamlines_cache_playback_layer(stage)
    assert stage.GetSessionLayer().subLayerPaths == ["main-session.usda"]
    assert stage.GetRootLayer().subLayerPaths == ["server-scene.usda"]
    assert stage.reference is None


class _CacheLayerRuntime(StreamlinesCacheRuntimeMixin):
    def __init__(self, repo_root: Path) -> None:
        self.config = SimpleNamespace(repo_root=repo_root)


class _CacheSessionLayer:
    def __init__(self) -> None:
        self.subLayerPaths: list[str] = []


class _CacheStage:
    def __init__(self) -> None:
        self._session_layer = _CacheSessionLayer()
        self._root_layer = _CacheSessionLayer()
        self._edit_target = object()
        self.removed_prims: list[str] = []
        self.reference = None

    def GetSessionLayer(self) -> _CacheSessionLayer:
        return self._session_layer

    def GetRootLayer(self) -> _CacheSessionLayer:
        return self._root_layer

    def GetEditTarget(self):
        return self._edit_target

    def SetEditTarget(self, edit_target) -> None:
        self._edit_target = edit_target

    def RemovePrim(self, prim_path: str) -> None:
        self.removed_prims.append(prim_path)
        if prim_path == CACHE_PLAYBACK_ROOT_PATH:
            self.reference = None

    def OverridePrim(self, prim_path: str):
        assert prim_path in (CACHE_PLAYBACK_ROOT_PATH, CACHE_PLAYBACK_SOURCE_PATH)
        return _CachePresentationPrim(self)


class _CachePresentationPrim:
    def __init__(self, stage: _CacheStage) -> None:
        self._stage = stage

    def GetReferences(self):
        return self

    def SetReferences(self, references) -> None:
        assert len(references) == 1
        self._stage.reference = references[0]


class _CacheVisibilityAttribute:
    def Set(self, _value) -> bool:
        return True


class _CacheXform:
    @staticmethod
    def Define(stage, path):
        return _CacheXform(stage.OverridePrim(path))

    def __init__(self, prim) -> None:
        self._prim = prim

    def GetPrim(self):
        return self._prim

    def CreateVisibilityAttr(self):
        return _CacheVisibilityAttribute()
