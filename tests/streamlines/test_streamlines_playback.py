# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""Focused plain contracts for persisted Streamlines cache playback."""

from __future__ import annotations

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
    source_signature_from_temporal_source,
)
from digital_twin_runtime_suite.app.streamlines.playback import (
    cached_playback_contract_from_validated_cache,
    resolve_cached_playback_state,
)
from digital_twin_runtime_suite.app.streamlines.temporal import (
    TemporalVelocitySourceDescriptor,
)


def test_cached_playback_selects_exact_real_states_and_wraps(tmp_path: Path) -> None:
    source = _source(tmp_path)
    contract = cached_playback_contract_from_validated_cache(_metadata(source), source)

    expected_indices = {
        0.0: 0,
        0.2: 1,
        0.399: 1,
        0.4: 2,
        0.599: 2,
        0.6: 0,
    }

    for phase_seconds, expected_index in expected_indices.items():
        resolution = resolve_cached_playback_state(contract, phase_seconds)
        assert resolution.sample.sample_index == expected_index
        assert resolution.decision == "SELECT"


def test_cached_playback_same_visible_state_is_no_op(tmp_path: Path) -> None:
    source = _source(tmp_path)
    contract = cached_playback_contract_from_validated_cache(_metadata(source), source)

    resolution = resolve_cached_playback_state(
        contract,
        0.21,
        active_sample_index=1,
    )

    assert resolution.sample.sample_index == 1
    assert resolution.is_no_op is True


def test_cached_playback_rejects_unusable_or_wrongly_bound_cache(
    tmp_path: Path,
) -> None:
    source = _source(tmp_path)
    metadata = _metadata(source)
    wrong_workload_source = replace(
        source,
        static_descriptor=replace(source.static_descriptor, workload="Surge"),
    )

    with pytest.raises(ValueError, match="valid persisted cache"):
        cached_playback_contract_from_validated_cache(
            replace(metadata, state="PARTIAL"),
            source,
        )
    with pytest.raises(ValueError, match="workload"):
        cached_playback_contract_from_validated_cache(
            metadata,
            wrong_workload_source,
        )
    with pytest.raises(ValueError, match="VTI identity"):
        cached_playback_contract_from_validated_cache(
            replace(
                metadata,
                states=(
                    replace(metadata.states[0], source_vti="wrong.vti"),
                    *metadata.states[1:],
                ),
            ),
            source,
        )
    with pytest.raises(ValueError, match="source time"):
        cached_playback_contract_from_validated_cache(
            replace(
                metadata,
                states=(
                    metadata.states[0],
                    replace(metadata.states[1], source_time_seconds=9.0),
                    metadata.states[2],
                ),
            ),
            source,
        )
    with pytest.raises(ValueError, match="time code"):
        cached_playback_contract_from_validated_cache(
            replace(
                metadata,
                states=(
                    metadata.states[0],
                    metadata.states[1],
                    replace(metadata.states[2], time_code=999.0),
                ),
            ),
            source,
        )


def test_presentation_period_is_absent_from_cached_playback_identity(
    tmp_path: Path,
) -> None:
    source = _source(tmp_path)
    metadata = _metadata(source)

    first = cached_playback_contract_from_validated_cache(metadata, source)
    second = cached_playback_contract_from_validated_cache(metadata, source)

    assert first == second
    assert first.loop_duration_seconds == pytest.approx(0.6)


def _source(tmp_path: Path) -> TemporalVelocitySourceDescriptor:
    paths = []
    for index in range(3):
        path = tmp_path / f"sample_{index}.vti"
        path.write_bytes(f"sample-{index}".encode("utf-8"))
        paths.append(path)
    descriptor = StaticVelocitySourceDescriptor(
        workload="Nominal",
        dataset_identity="server/load_normal",
        sample_index=0,
        vti_path=paths[0],
        dataset_prim_path="/DTRS_HoudiniVelocity/VTKImageData",
        velocity_field_prim_path="/DTRS_HoudiniVelocity/PointData/vel",
        world_bounds=((0.0, 0.0, 0.0), (1.0, 1.0, 1.0)),
        dimensions=(2, 2, 2),
        spacing=(1.0, 1.0, 1.0),
        origin=(0.0, 0.0, 0.0),
        source_origin=(0.0, 0.0, 0.0),
        stage_meters_per_unit=1.0,
    )
    return TemporalVelocitySourceDescriptor(
        static_descriptor=descriptor,
        velocity_paths=tuple(paths),
        sample_time_codes=(0.0, 12.0, 24.0),
        time_codes_per_second=60.0,
        sample_interval_seconds=0.2,
    )


def _metadata(source: TemporalVelocitySourceDescriptor) -> StreamlinesCacheMetadata:
    states = tuple(
        StreamlinesCacheState(
            sample_index=index,
            source_time_seconds=index * source.sample_interval_seconds,
            time_code=source.sample_time_codes[index],
            source_vti=source.velocity_paths[index].resolve().as_posix(),
            source_vti_identity=f"identity-{index}",
            curve_count=1,
            point_count=4,
            topology_signature="topology",
            geometry_signature=f"geometry-{index}",
            generation_ms=1.0,
            bounds=((0.0, 0.0, 0.0), (1.0, 1.0, 1.0)),
        )
        for index in range(source.sample_count)
    )
    return StreamlinesCacheMetadata(
        schema_version=CACHE_SCHEMA_VERSION,
        state="VALID",
        workload=source.workload,
        dataset_identity=source.dataset_identity,
        source_signature=source_signature_from_temporal_source(source),
        settings_signature="settings",
        settings=None,
        sample_count=source.sample_count,
        sample_interval_seconds=source.sample_interval_seconds,
        time_codes_per_second=source.time_codes_per_second,
        topology_consistent=True,
        geometry_file_name="cache.usdc",
        geometry_sha256="geometry",
        states=states,
    )
