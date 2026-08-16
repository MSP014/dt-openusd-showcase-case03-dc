"""Focused exact-manifest temporal resolver contracts without Kit."""

from __future__ import annotations

from pathlib import Path

from digital_twin_runtime_suite.app.flow.static_source import (
    StaticVelocitySourceDescriptor,
)
from digital_twin_runtime_suite.app.streamlines.temporal import (
    TemporalVelocitySourceDescriptor,
    manifest_samples,
    resolve_temporal_source_sample,
)


def _source(tmp_path: Path) -> TemporalVelocitySourceDescriptor:
    paths = tuple(tmp_path / f"velocity_{index:04d}.vti" for index in range(3))
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
        sample_time_codes=(0.0, 12.0, 24.0),
        time_codes_per_second=60.0,
        sample_interval_seconds=0.2,
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
