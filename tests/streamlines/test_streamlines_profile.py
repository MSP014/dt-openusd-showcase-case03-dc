"""Focused production Streamlines profile and cache-promotion contracts."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from digital_twin_runtime_suite.app.flow.static_source import (
    StaticVelocitySourceDescriptor,
)
from digital_twin_runtime_suite.app.streamlines.cache import (
    StreamlinesCacheOwnership,
    StreamlinesCacheState,
    build_streamlines_cache_metadata,
    file_sha256,
    geometry_signature,
    streamlines_cache_paths,
    streamlines_settings_signature,
    topology_signature,
    validate_streamlines_cache,
    vti_file_identity,
)
from digital_twin_runtime_suite.app.streamlines.cache_runtime import (
    StreamlinesCacheBuildResult,
    StreamlinesCacheRuntimeMixin,
)
from digital_twin_runtime_suite.app.streamlines.profile import (
    PRODUCTION_STREAMLINES_PROFILE,
    ProductionStreamlinesProfileState,
)
from digital_twin_runtime_suite.app.streamlines.proof import (
    build_streamlines_operator_request,
)
from digital_twin_runtime_suite.app.streamlines.temporal import (
    TemporalVelocitySourceDescriptor,
)


def _source(tmp_path: Path) -> TemporalVelocitySourceDescriptor:
    paths = tuple(tmp_path / f"sample_{index}.vti" for index in range(2))
    for index, path in enumerate(paths):
        path.write_bytes(f"vti-{index}".encode("utf-8"))
    descriptor = StaticVelocitySourceDescriptor(
        workload="Nominal",
        dataset_identity="server/load_normal",
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
        sample_time_codes=(0.0, 12.0),
        time_codes_per_second=60.0,
        sample_interval_seconds=0.2,
    )


def _state(
    source: TemporalVelocitySourceDescriptor,
    index: int,
) -> StreamlinesCacheState:
    bounds = ((float(index), 0.0, 0.0), (float(index), 1.0, 0.0))
    points = ((float(index), 0.0, 0.0),) * 4
    return StreamlinesCacheState(
        sample_index=index,
        source_time_seconds=source.sample_time_codes[index] / 60.0,
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
            point_head=points[:3],
            point_tail=points[-3:],
        ),
        generation_ms=1.0,
        bounds=bounds,
    )


def test_profile_signature_covers_geometry_and_persisted_attributes() -> None:
    profile = PRODUCTION_STREAMLINES_PROFILE

    assert profile.settings_signature == replace(profile).settings_signature
    assert (
        profile.settings_signature
        != replace(
            profile,
            seed_resolution=profile.seed_resolution + 1,
        ).settings_signature
    )
    assert (
        profile.settings_signature
        != replace(
            profile,
            persisted_attributes=(*profile.persisted_attributes, "times"),
        ).settings_signature
    )
    assert "primvars:dtrs:speed" in profile.persisted_attributes


def test_runtime_only_presentation_period_is_absent_from_profile_signature(
    tmp_path: Path,
) -> None:
    profile = PRODUCTION_STREAMLINES_PROFILE
    request = build_streamlines_operator_request(_source(tmp_path).static_descriptor)

    assert profile.settings_signature == request.profile_signature
    assert streamlines_settings_signature(request) == streamlines_settings_signature(
        request
    )


def test_profile_change_makes_an_existing_cache_stale(tmp_path: Path) -> None:
    source = _source(tmp_path)
    paths = streamlines_cache_paths(
        tmp_path,
        StreamlinesCacheOwnership("Nominal", "server/load_normal"),
    )
    paths.directory.mkdir(parents=True)
    paths.geometry_path.write_bytes(b"cache")
    request = build_streamlines_operator_request(source.static_descriptor)
    metadata = build_streamlines_cache_metadata(
        source,
        request,
        tuple(_state(source, index) for index in range(source.sample_count)),
        geometry_file_name=paths.geometry_path.name,
        geometry_sha256=file_sha256(paths.geometry_path),
    )
    changed = build_streamlines_operator_request(
        source.static_descriptor,
        profile=replace(
            PRODUCTION_STREAMLINES_PROFILE,
            width_cell_multiplier=0.5,
        ),
    )

    result = validate_streamlines_cache(
        metadata,
        source=source,
        settings_signature=streamlines_settings_signature(changed),
        geometry_path=paths.geometry_path,
    )

    assert result.valid is False
    assert result.message == "Cache settings or seed are stale."


def test_cache_without_raw_speed_contract_is_stale_after_profile_extension(
    tmp_path: Path,
) -> None:
    source = _source(tmp_path)
    paths = streamlines_cache_paths(
        tmp_path,
        StreamlinesCacheOwnership("Nominal", "server/load_normal"),
    )
    paths.directory.mkdir(parents=True)
    paths.geometry_path.write_bytes(b"cache")
    legacy_profile = replace(
        PRODUCTION_STREAMLINES_PROFILE,
        name="dtrs_standard_streamlines_v1",
        persisted_attributes=tuple(
            attribute
            for attribute in PRODUCTION_STREAMLINES_PROFILE.persisted_attributes
            if attribute != "primvars:dtrs:speed"
        ),
    )
    legacy_request = build_streamlines_operator_request(
        source.static_descriptor,
        profile=legacy_profile,
    )
    metadata = build_streamlines_cache_metadata(
        source,
        legacy_request,
        tuple(_state(source, index) for index in range(source.sample_count)),
        geometry_file_name=paths.geometry_path.name,
        geometry_sha256=file_sha256(paths.geometry_path),
    )

    validation = validate_streamlines_cache(
        metadata,
        source=source,
        settings_signature=streamlines_settings_signature(
            build_streamlines_operator_request(source.static_descriptor)
        ),
        geometry_path=paths.geometry_path,
    )

    assert validation.valid is False
    assert validation.message == "Cache settings or seed are stale."


def test_source_controlled_profile_is_accepted_after_runtime_reset() -> None:
    runtime = _ProfileRuntime()

    assert runtime.is_streamlines_production_profile_frozen() is True
    assert (
        runtime.accept_streamlines_production_profile()
        == PRODUCTION_STREAMLINES_PROFILE
    )


def test_frozen_profile_reuses_four_independently_valid_caches(
    tmp_path: Path,
) -> None:
    runtime = _CacheSetRuntime(tmp_path, failed_workload=None)

    result = asyncio.run(runtime.build_validate_production_cache_set_in_kit())

    assert result.success is True
    assert [item.workload for item in result.results] == [
        "Idle",
        "Nominal",
        "Surge",
        "Critical",
    ]
    assert all(item.reused for item in result.results)
    assert runtime.build_calls == []


def test_one_invalid_workload_stops_before_rebuilding_later_workloads(
    tmp_path: Path,
) -> None:
    runtime = _CacheSetRuntime(tmp_path, failed_workload="Nominal")

    result = asyncio.run(runtime.build_validate_production_cache_set_in_kit())

    assert result.success is False
    assert result.failed_workload == "Nominal"
    assert [item.workload for item in result.results] == ["Idle"]
    assert runtime.build_calls == ["Nominal"]


class _ProfileRuntime(StreamlinesCacheRuntimeMixin):
    def __init__(self) -> None:
        self._flow_lifecycle_state = "DETACHED"
        self._streamlines_profile_state = ProductionStreamlinesProfileState()


class _CacheSetRuntime(StreamlinesCacheRuntimeMixin):
    def __init__(self, repo_root: Path, failed_workload: str | None) -> None:
        self.config = SimpleNamespace(repo_root=repo_root)
        self._flow_lifecycle_state = "DETACHED"
        self._streamlines_profile_state = ProductionStreamlinesProfileState()
        self.failed_workload = failed_workload
        self.build_calls: list[str] = []
        self.targets = tuple(
            SimpleNamespace(
                binding=SimpleNamespace(
                    workload_mode=workload,
                    dataset_identity=f"server/load_{workload.lower()}",
                ),
                dataset=object(),
            )
            for workload in ("Idle", "Nominal", "Surge", "Critical")
        )
        self.metadata = SimpleNamespace(
            states=(object(),),
            sample_count=1,
        )
        for target in self.targets:
            paths = streamlines_cache_paths(
                repo_root,
                self._streamlines_cache_ownership(target.binding),
            )
            paths.directory.mkdir(parents=True, exist_ok=True)
            paths.geometry_path.write_bytes(b"geometry")
            paths.metadata_path.write_bytes(b"metadata")

    def resolve_configured_airflow_targets(self):
        return self.targets

    def _inspect_streamlines_cache_for_target(self, binding, _dataset):
        valid = binding.workload_mode != self.failed_workload
        return SimpleNamespace(valid=valid, metadata=self.metadata)

    async def build_streamlines_cache_in_kit(self, *, binding, **_kwargs):
        self.build_calls.append(binding.workload_mode)
        return StreamlinesCacheBuildResult(False, "injected sample failure")


def test_production_cache_sanity_readiness_requires_four_valid_detached_caches(
    tmp_path: Path,
) -> None:
    ready = _CacheSetRuntime(tmp_path, failed_workload=None)

    assert ready.is_streamlines_production_cache_sanity_ready() is True
    assert ready.build_calls == []

    stale = _CacheSetRuntime(tmp_path, failed_workload="Surge")
    assert stale.is_streamlines_production_cache_sanity_ready() is False

    ready._flow_lifecycle_state = "ATTACHED"
    assert ready.is_streamlines_production_cache_sanity_ready() is False
