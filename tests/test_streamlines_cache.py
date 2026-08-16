"""Focused cache-contract tests without Kit-CAE execution."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from digital_twin_runtime_suite.app.flow.static_source import (
    StaticVelocitySourceDescriptor,
)
from digital_twin_runtime_suite.app.streamlines.cache import (
    CACHE_SCHEMA_VERSION,
    StreamlinesCacheMetadata,
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
        generation_ms=10.0 + index,
        bounds=bounds,
    )


def _metadata(tmp_path: Path):
    source = _source(tmp_path)
    geometry_path = streamlines_cache_paths(tmp_path).geometry_path
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
        source_signature=source_signature_from_temporal_source(source),
        settings_signature=streamlines_settings_signature(request),
        workload=source.workload,
        dataset_identity=source.dataset_identity,
        sample_count=source.sample_count,
        geometry_path=geometry_path,
    )
    rejected = validate_streamlines_cache(
        metadata,
        source_signature=source_signature_from_temporal_source(source),
        settings_signature=streamlines_settings_signature(
            replace(request, width=request.width * 2.0)
        ),
        workload=source.workload,
        dataset_identity=source.dataset_identity,
        sample_count=source.sample_count,
        geometry_path=geometry_path,
    )

    assert metadata.schema_version == CACHE_SCHEMA_VERSION
    assert metadata.valid is True
    assert metadata.topology_consistent is True
    assert accepted.valid is True
    assert rejected.valid is False
    assert rejected.message == "Cache settings or seed are stale."


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
        source_signature=source_signature_from_temporal_source(source),
        settings_signature=streamlines_settings_signature(request),
        workload=source.workload,
        dataset_identity=source.dataset_identity,
        sample_count=source.sample_count,
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
        source_signature=source_signature_from_temporal_source(source),
        settings_signature=streamlines_settings_signature(request),
        workload=source.workload,
        dataset_identity=source.dataset_identity,
        sample_count=source.sample_count,
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
    paths = streamlines_cache_paths(tmp_path)
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
    paths = streamlines_cache_paths(tmp_path)
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
    paths = streamlines_cache_paths(tmp_path)
    paths.geometry_path.unlink()
    _write_cache_pair(paths, "partial", partial=True)

    validation = validate_streamlines_cache(
        metadata,
        source_signature=source_signature_from_temporal_source(source),
        settings_signature=streamlines_settings_signature(request),
        workload=source.workload,
        dataset_identity=source.dataset_identity,
        sample_count=source.sample_count,
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
        source_signature=source_signature_from_temporal_source(source),
        settings_signature=streamlines_settings_signature(
            replace(request, seed_radius=request.seed_radius * 2.0)
        ),
        workload=source.workload,
        dataset_identity=source.dataset_identity,
        sample_count=source.sample_count,
        geometry_path=geometry_path,
    )

    assert validation.valid is False
    assert validation.message == "Cache settings or seed are stale."
    assert streamlines_cache_build_mode(streamlines_cache_paths(tmp_path)) == "REBUILD"
    assert geometry_path.read_bytes() == original_geometry


def test_cache_startup_inspection_never_starts_a_build(tmp_path: Path) -> None:
    paths = streamlines_cache_paths(tmp_path)

    assert streamlines_cache_build_mode(paths) == "NEW"
    assert paths.directory.exists() is False
