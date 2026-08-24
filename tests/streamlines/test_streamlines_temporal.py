# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""Focused exact-manifest temporal resolver contracts without Kit."""

from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path

import pytest

from digital_twin_runtime_suite.app.flow.static_source import (
    StaticVelocitySourceDescriptor,
)
from digital_twin_runtime_suite.app.streamlines.temporal import (
    TemporalVelocitySourceDescriptor,
    manifest_samples,
    resolve_temporal_source_sample,
)


def _source(
    tmp_path: Path,
    *,
    sample_count: int = 3,
    sample_interval_seconds: float = 0.2,
) -> TemporalVelocitySourceDescriptor:
    paths = tuple(
        tmp_path / f"velocity_{index:04d}.vti" for index in range(sample_count)
    )
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
        spacing=(1.0, 1.0, 1.0),
        origin=(0.0, 0.0, 0.0),
        source_origin=(0.0, 0.0, 0.0),
        stage_meters_per_unit=1.0,
    )
    return TemporalVelocitySourceDescriptor(
        static_descriptor=descriptor,
        velocity_paths=paths,
        sample_time_codes=tuple(
            index * 60.0 * sample_interval_seconds for index in range(sample_count)
        ),
        time_codes_per_second=60.0,
        sample_interval_seconds=sample_interval_seconds,
    )


def test_resolver_uses_latest_real_manifest_sample_without_interpolation(
    tmp_path: Path,
) -> None:
    source = _source(tmp_path)

    resolution = resolve_temporal_source_sample(source, 0.399)

    assert resolution.decision == "SELECT"
    assert resolution.sample.sample_index == 1
    assert resolution.sample.source_vti == source.velocity_paths[1]
    assert resolution.sample.source_time_seconds == 0.2


def test_resolver_wraps_loop_and_returns_no_op_for_same_identity(
    tmp_path: Path,
) -> None:
    source = _source(tmp_path)

    wrapped = resolve_temporal_source_sample(source, 0.6)
    unchanged = resolve_temporal_source_sample(
        source,
        0.21,
        active_sample_index=1,
    )

    assert wrapped.normalized_phase_seconds == 0.0
    assert wrapped.sample.sample_index == 0
    assert unchanged.decision == "NO_OP"
    assert unchanged.is_no_op is True
    assert manifest_samples(source)[1] == unchanged.sample


@pytest.mark.parametrize(
    ("phase_seconds", "expected_index"),
    (
        (0.0, 0),
        (0.2, 1),
        (0.199999, 0),
        (0.200001, 1),
    ),
)
def test_resolver_preserves_exact_manifest_boundaries(
    tmp_path: Path,
    phase_seconds: float,
    expected_index: int,
) -> None:
    source = _source(tmp_path, sample_count=4)

    resolution = resolve_temporal_source_sample(source, phase_seconds)

    assert resolution.sample.sample_index == expected_index
    assert resolution.decision == "SELECT"


@pytest.mark.parametrize("phase_seconds", (math.nan, math.inf, -math.inf))
def test_resolver_rejects_non_finite_phase(
    tmp_path: Path,
    phase_seconds: float,
) -> None:
    source = _source(tmp_path)

    with pytest.raises(ValueError, match="finite"):
        resolve_temporal_source_sample(source, phase_seconds)


def test_temporal_contract_rejects_inconsistent_manifest_clock(tmp_path: Path) -> None:
    source = _source(tmp_path)
    inconsistent_clock = replace(
        source,
        sample_time_codes=(0.0, 12.0, 25.0),
    )

    with pytest.raises(ValueError, match="must match its sample interval"):
        manifest_samples(inconsistent_clock)


def test_temporal_contract_rejects_empty_or_non_positive_interval(
    tmp_path: Path,
) -> None:
    source = _source(tmp_path)

    with pytest.raises(ValueError, match="at least one"):
        manifest_samples(replace(source, velocity_paths=()))
    with pytest.raises(ValueError, match="sample interval"):
        manifest_samples(replace(source, sample_interval_seconds=0.0))
