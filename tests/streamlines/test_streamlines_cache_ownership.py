"""Focused Phase 3.4 workload-aware cache ownership and discovery contracts."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from digital_twin_runtime_suite.app.airflow_dataset import AirflowDatasetSelector
from digital_twin_runtime_suite.app.flow.static_source import (
    StaticVelocitySourceDescriptor,
)
from digital_twin_runtime_suite.app.streamlines.cache import (
    CACHE_SCHEMA_VERSION,
    StreamlinesCacheMetadata,
    StreamlinesCacheOwnership,
    StreamlinesCacheState,
    build_streamlines_cache_metadata,
    file_sha256,
    geometry_signature,
    serialise_streamlines_cache_metadata,
    streamlines_cache_paths,
    streamlines_settings_signature,
    topology_signature,
    vti_file_identity,
)
from digital_twin_runtime_suite.app.streamlines.cache_discovery import (
    inspect_streamlines_cache,
)
from digital_twin_runtime_suite.app.streamlines.cache_runtime import (
    StreamlinesCacheRuntimeMixin,
)
from digital_twin_runtime_suite.app.streamlines.proof import (
    build_streamlines_operator_request,
)
from digital_twin_runtime_suite.app.streamlines.temporal import (
    TemporalVelocitySourceDescriptor,
)
from digital_twin_runtime_suite.app.workload_binding import WorkloadAirflowBinding


def _source(
    tmp_path: Path,
    *,
    workload: str,
    state: str,
    sample_count: int,
    interval_seconds: float,
) -> TemporalVelocitySourceDescriptor:
    dataset_identity = f"server/{state}"
    paths = tuple(
        tmp_path / workload.lower() / f"velocity_{index:04d}.vti"
        for index in range(sample_count)
    )
    for index, path in enumerate(paths):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"{workload}-{index}".encode("utf-8"))
    descriptor = StaticVelocitySourceDescriptor(
        workload=workload,
        dataset_identity=dataset_identity,
        sample_index=0,
        vti_path=paths[0],
        dataset_prim_path="/DTRS_HoudiniVelocity/VTKImageData",
        velocity_field_prim_path="/DTRS_HoudiniVelocity/PointData/vel",
        world_bounds=((0.0, 0.0, 0.0), (1.0, 1.0, 1.0)),
        dimensions=(2, 2, 2),
        spacing=(0.1, 0.1, 0.1),
        origin=(0.0, 0.0, 0.0),
        source_origin=(0.0, 0.0, 0.0),
        stage_meters_per_unit=1.0,
    )
    return TemporalVelocitySourceDescriptor(
        static_descriptor=descriptor,
        velocity_paths=paths,
        sample_time_codes=tuple(
            60.0 * interval_seconds * index for index in range(sample_count)
        ),
        time_codes_per_second=60.0,
        sample_interval_seconds=interval_seconds,
    )


def _ownership(source: TemporalVelocitySourceDescriptor) -> StreamlinesCacheOwnership:
    return StreamlinesCacheOwnership(source.workload, source.dataset_identity)


def _state(
    source: TemporalVelocitySourceDescriptor,
    index: int,
) -> StreamlinesCacheState:
    bounds = ((float(index), 0.0, 0.0), (float(index), 1.0, 1.0))
    return StreamlinesCacheState(
        sample_index=index,
        source_time_seconds=(
            source.sample_time_codes[index] / source.time_codes_per_second
        ),
        time_code=source.sample_time_codes[index],
        source_vti=source.velocity_paths[index].resolve().as_posix(),
        source_vti_identity=vti_file_identity(source.velocity_paths[index]),
        curve_count=1,
        point_count=4,
        topology_signature=topology_signature((4,)),
        geometry_signature=geometry_signature(
            curve_count=1,
            point_count=4,
            bounds=bounds,
            point_head=((0.0, 0.0, 0.0),),
            point_tail=((1.0, 1.0, 1.0),),
        ),
        generation_ms=1.0,
        bounds=bounds,
    )


def _persist_cache(
    repo_root: Path,
    source: TemporalVelocitySourceDescriptor,
    *,
    metadata_source: TemporalVelocitySourceDescriptor | None = None,
    request=None,
) -> tuple[StreamlinesCacheMetadata, object]:
    metadata_source = metadata_source or source
    ownership = _ownership(source)
    paths = streamlines_cache_paths(repo_root, ownership)
    paths.directory.mkdir(parents=True, exist_ok=True)
    paths.geometry_path.write_bytes(b"derived-usdc")
    request = request or build_streamlines_operator_request(
        metadata_source.static_descriptor
    )
    metadata = build_streamlines_cache_metadata(
        metadata_source,
        request,
        tuple(
            _state(metadata_source, index)
            for index in range(metadata_source.sample_count)
        ),
        geometry_file_name=paths.geometry_path.name,
        geometry_sha256=file_sha256(paths.geometry_path),
    )
    paths.metadata_path.write_text(
        serialise_streamlines_cache_metadata(metadata),
        encoding="utf-8",
    )
    return metadata, request


def _inspect(
    repo_root: Path,
    source: TemporalVelocitySourceDescriptor,
    *,
    ownership: StreamlinesCacheOwnership | None = None,
    settings_signature: str | None = None,
):
    ownership = ownership or _ownership(source)
    paths = streamlines_cache_paths(repo_root, ownership)
    request = build_streamlines_operator_request(source.static_descriptor)
    return inspect_streamlines_cache(
        paths,
        ownership,
        source=source,
        settings_signature=(
            settings_signature or streamlines_settings_signature(request)
        ),
    )


def test_all_configured_workloads_have_distinct_ownership_paths(tmp_path: Path) -> None:
    sources = tuple(
        _source(
            tmp_path,
            workload=workload,
            state=state,
            sample_count=2,
            interval_seconds=0.2,
        )
        for workload, state in (
            ("Idle", "load_idle"),
            ("Nominal", "load_normal"),
            ("Surge", "load_surge"),
            ("Critical", "load_critical"),
        )
    )

    paths = tuple(
        streamlines_cache_paths(tmp_path, _ownership(source)) for source in sources
    )

    assert len({path.ownership.identity for path in paths}) == 4
    assert len({path.geometry_path for path in paths}) == 4
    assert all(path.directory.name.startswith("server_load_") for path in paths)


@pytest.mark.parametrize(
    ("workload", "state", "sample_count", "interval_seconds"),
    (
        ("Nominal", "load_normal", 80, 0.2),
        ("Idle", "load_idle", 1, 0.4),
        ("Surge", "load_surge", 40, 0.4),
        ("Critical", "load_critical", 160, 0.1),
    ),
)
def test_ownership_cache_is_valid_for_its_own_dataset_timing(
    tmp_path: Path,
    workload: str,
    state: str,
    sample_count: int,
    interval_seconds: float,
) -> None:
    source = _source(
        tmp_path,
        workload=workload,
        state=state,
        sample_count=sample_count,
        interval_seconds=interval_seconds,
    )
    _persist_cache(tmp_path, source)

    inspection = _inspect(tmp_path, source)

    assert inspection.classification == "VALID"
    assert inspection.metadata is not None
    assert inspection.metadata.sample_count == sample_count
    assert inspection.metadata.sample_interval_seconds == interval_seconds


def test_missing_cache_never_creates_an_artifact(tmp_path: Path) -> None:
    source = _source(
        tmp_path,
        workload="Idle",
        state="load_idle",
        sample_count=2,
        interval_seconds=0.2,
    )
    paths = streamlines_cache_paths(tmp_path, _ownership(source))

    inspection = inspect_streamlines_cache(paths, _ownership(source))

    assert inspection.classification == "MISSING"
    assert paths.directory.exists() is False


@pytest.mark.parametrize("drift", ("source", "settings", "coverage"))
def test_mutable_source_settings_or_coverage_drift_is_stale(
    tmp_path: Path,
    drift: str,
) -> None:
    source = _source(
        tmp_path,
        workload="Nominal",
        state="load_normal",
        sample_count=2,
        interval_seconds=0.2,
    )
    metadata, request = _persist_cache(tmp_path, source)
    paths = streamlines_cache_paths(tmp_path, _ownership(source))
    expected_source = source
    expected_signature = streamlines_settings_signature(request)
    if drift == "source":
        source.velocity_paths[1].write_bytes(b"changed-source")
    elif drift == "settings":
        expected_signature = streamlines_settings_signature(
            replace(request, width=request.width * 2.0)
        )
    else:
        metadata = replace(metadata, states=metadata.states[:1])
        paths.metadata_path.write_text(
            serialise_streamlines_cache_metadata(metadata),
            encoding="utf-8",
        )

    inspection = _inspect(
        tmp_path,
        expected_source,
        settings_signature=expected_signature,
    )

    assert inspection.classification == "STALE"
    assert paths.geometry_path.read_bytes() == b"derived-usdc"


@pytest.mark.parametrize(
    "defect",
    ("workload", "dataset", "schema", "malformed"),
)
def test_wrong_ownership_schema_or_metadata_is_incompatible(
    tmp_path: Path,
    defect: str,
) -> None:
    source = _source(
        tmp_path,
        workload="Nominal",
        state="load_normal",
        sample_count=2,
        interval_seconds=0.2,
    )
    metadata, _request = _persist_cache(tmp_path, source)
    paths = streamlines_cache_paths(tmp_path, _ownership(source))
    if defect == "workload":
        metadata = replace(metadata, workload="Surge")
    elif defect == "dataset":
        metadata = replace(metadata, dataset_identity="server/load_surge")
    elif defect == "schema":
        metadata = replace(metadata, schema_version=CACHE_SCHEMA_VERSION - 1)
    else:
        paths.metadata_path.write_text("{}", encoding="utf-8")
    if defect != "malformed":
        paths.metadata_path.write_text(
            serialise_streamlines_cache_metadata(metadata),
            encoding="utf-8",
        )

    inspection = _inspect(tmp_path, source)

    assert inspection.classification == "INCOMPATIBLE"


def test_runtime_discovery_is_read_only_for_all_configured_workloads(
    tmp_path: Path,
) -> None:
    sources = tuple(
        _source(
            tmp_path,
            workload=workload,
            state=state,
            sample_count=count,
            interval_seconds=interval,
        )
        for workload, state, count, interval in (
            ("Idle", "load_idle", 1, 0.4),
            ("Nominal", "load_normal", 80, 0.2),
            ("Surge", "load_surge", 40, 0.4),
            ("Critical", "load_critical", 160, 0.1),
        )
    )
    for source in sources:
        _persist_cache(tmp_path, source)
    runtime = _DiscoveryRuntime(tmp_path, sources)

    inspections = runtime.inspect_streamlines_caches()

    assert [inspection.classification for inspection in inspections] == ["VALID"] * 4
    assert runtime.builder_calls == 0
    assert runtime.vti_import_calls == 0
    assert runtime.kit_cae_recompute_calls == 0


class _DiscoveryRuntime(StreamlinesCacheRuntimeMixin):
    def __init__(
        self,
        repo_root: Path,
        sources: tuple[TemporalVelocitySourceDescriptor, ...],
    ) -> None:
        self.config = SimpleNamespace(repo_root=repo_root)
        self._sources = {source.workload: source for source in sources}
        self.builder_calls = 0
        self.vti_import_calls = 0
        self.kit_cae_recompute_calls = 0

    def resolve_configured_airflow_targets(self):
        return tuple(
            SimpleNamespace(
                binding=WorkloadAirflowBinding(
                    workload_mode=source.workload,
                    dataset=AirflowDatasetSelector(
                        root="airflow_datasets",
                        scope="server",
                        state=source.dataset_identity.split("/", maxsplit=1)[1],
                    ),
                ),
                dataset=object(),
            )
            for source in self._sources.values()
        )

    def _streamlines_cache_expected_contract(
        self,
        *,
        binding,
        airflow_dataset,
        stage_time_codes_per_second: float,
    ) -> dict[str, object]:
        source = self._sources[binding.workload_mode]
        request = build_streamlines_operator_request(source.static_descriptor)
        return {
            "source": source,
            "settings_signature": streamlines_settings_signature(request),
        }

    async def prepare_streamlines_temporal_velocity_source_in_kit(self, **_kwargs):
        self.vti_import_calls += 1
        raise AssertionError("Cache discovery must not import VTI through Kit-CAE.")

    async def _build_cache_geometry_in_kit(self, *_args, **_kwargs):
        self.builder_calls += 1
        raise AssertionError("Cache discovery must not build cache geometry.")

    async def _run_fresh_streamlines_operator_in_kit(self, *_args, **_kwargs):
        self.kit_cae_recompute_calls += 1
        raise AssertionError("Cache discovery must not run the Streamlines operator.")
