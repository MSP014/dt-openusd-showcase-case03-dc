"""Focused plain-data coverage for the Stage 09 Package E temporal probe."""

from pathlib import Path

import pytest

from digital_twin_runtime_suite.app.flow.static_source import (
    StaticVelocitySourceDescriptor,
)
from digital_twin_runtime_suite.app.streamlines.temporal import (
    StreamlinesGeometrySignature,
    TemporalVelocitySourceDescriptor,
    build_temporal_probe_indices,
    build_temporal_probe_samples,
    geometry_signatures_match,
)


def _source(sample_count: int) -> TemporalVelocitySourceDescriptor:
    descriptor = StaticVelocitySourceDescriptor(
        workload="Nominal",
        dataset_identity="server/load_normal",
        sample_index=0,
        vti_path=Path("sample_000.vti"),
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
        velocity_paths=tuple(
            Path(f"sample_{index:03}.vti") for index in range(sample_count)
        ),
        sample_time_codes=tuple(float(index) * 4.8 for index in range(sample_count)),
        time_codes_per_second=24.0,
        sample_interval_seconds=0.2,
    )


def test_temporal_probe_sequence_comes_from_count_and_keeps_loop_return():
    assert build_temporal_probe_indices(80) == (0, 1, 2, 20, 40, 79, 0)


def test_temporal_probe_short_sequence_deduplicates_except_final_return():
    assert build_temporal_probe_indices(1) == (0, 0)
    assert build_temporal_probe_indices(2) == (0, 1, 0)


def test_temporal_probe_samples_preserve_manifest_timecode_mapping():
    samples = build_temporal_probe_samples(_source(80))

    assert tuple(sample.sample_index for sample in samples) == (
        0,
        1,
        2,
        20,
        40,
        79,
        0,
    )
    assert samples[3].source_vti == Path("sample_020.vti")
    assert samples[3].time_code == 96.0
    assert samples[3].source_time_seconds == 4.0


def test_temporal_probe_rejects_empty_manifest_sequence():
    with pytest.raises(ValueError, match="at least one manifest sample"):
        build_temporal_probe_indices(0)


def test_geometry_signature_comparison_accepts_loop_return_and_detects_stale_final():
    first = StreamlinesGeometrySignature(
        curve_count=256,
        point_count=51200,
        bounds=((0.0, 0.0, 0.0), (1.0, 1.0, 1.0)),
        point_head=((0.0, 0.0, 0.0),),
        point_tail=((1.0, 1.0, 1.0),),
    )
    final = StreamlinesGeometrySignature(
        curve_count=256,
        point_count=51200,
        bounds=((2.0, 0.0, 0.0), (3.0, 1.0, 1.0)),
        point_head=((2.0, 0.0, 0.0),),
        point_tail=((3.0, 1.0, 1.0),),
    )

    assert geometry_signatures_match(first, first)
    assert not geometry_signatures_match(first, final)
