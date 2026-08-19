"""Focused renderer-safe Streamlines cache topology contracts."""

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from digital_twin_runtime_suite.app.streamlines import cache_runtime
from digital_twin_runtime_suite.app.streamlines.cache import (
    CACHE_SCHEMA_VERSION,
    topology_signature,
    validate_streamlines_cache,
)
from digital_twin_runtime_suite.app.streamlines.cache_runtime import (
    StreamlinesCacheBuildResult,
    StreamlinesCacheRuntimeMixin,
)
from digital_twin_runtime_suite.app.streamlines.constant_topology import (
    SOURCE_CURVE_VERTEX_COUNTS_ATTRIBUTE,
    authentic_values_from_padded_curves,
    pad_streamlines_sample_for_renderer,
    renderer_topology_for_profile,
    streamlines_point_array_signature,
    terminal_padding_is_exact,
)
from digital_twin_runtime_suite.app.streamlines.profile import (
    PRODUCTION_STREAMLINES_PROFILE,
    StreamlinesProfileId,
)


def test_volume_renderer_topology_is_6144_by_20() -> None:
    topology = renderer_topology_for_profile(StreamlinesProfileId.VOLUME_COVERAGE)

    assert topology.curve_count == 6144
    assert topology.vertices_per_curve == 20
    assert topology.point_count == 122880
    assert topology.curve_vertex_counts == (20,) * 6144


def test_global_renderer_topology_is_256_by_200() -> None:
    topology = renderer_topology_for_profile(StreamlinesProfileId.GLOBAL_FLOW_PATH)

    assert topology.curve_count == 256
    assert topology.vertices_per_curve == 200
    assert topology.point_count == 51200


def _global_source_sample(count: int = 4):
    counts = (count,) * 256
    points = tuple(
        (float(curve), float(vertex), 0.0)
        for curve in range(256)
        for vertex in range(count)
    )
    speeds = tuple(float(index) for index in range(len(points)))
    return points, counts, speeds


def test_authentic_points_and_speeds_survive_padding_unchanged() -> None:
    points, counts, speeds = _global_source_sample()
    padded = pad_streamlines_sample_for_renderer(
        profile_id=StreamlinesProfileId.GLOBAL_FLOW_PATH,
        points=points,
        curve_vertex_counts=counts,
        speeds=speeds,
    )

    authentic_points = authentic_values_from_padded_curves(
        padded.points,
        padded.source_curve_vertex_counts,
        vertices_per_curve=200,
    )
    authentic_speeds = authentic_values_from_padded_curves(
        padded.speeds,
        padded.source_curve_vertex_counts,
        vertices_per_curve=200,
    )
    assert authentic_points == points
    assert authentic_speeds == speeds
    assert all(actual is original for actual, original in zip(authentic_points, points))


def test_padding_repeats_only_curve_terminal_point_and_speed() -> None:
    points, counts, speeds = _global_source_sample(count=5)
    padded = pad_streamlines_sample_for_renderer(
        profile_id=StreamlinesProfileId.GLOBAL_FLOW_PATH,
        points=points,
        curve_vertex_counts=counts,
        speeds=speeds,
    )

    assert terminal_padding_is_exact(
        padded.points,
        counts,
        vertices_per_curve=200,
    )
    assert terminal_padding_is_exact(
        padded.speeds,
        counts,
        vertices_per_curve=200,
    )
    assert len(padded.points) == len(padded.speeds) == 51200


def test_source_curve_counts_preserve_original_topology() -> None:
    counts = tuple(4 if index % 2 else 5 for index in range(256))
    source_count = sum(counts)
    points = tuple((float(index), 0.0, 0.0) for index in range(source_count))
    speeds = tuple(float(index) for index in range(source_count))

    padded = pad_streamlines_sample_for_renderer(
        profile_id=StreamlinesProfileId.GLOBAL_FLOW_PATH,
        points=points,
        curve_vertex_counts=counts,
        speeds=speeds,
    )

    assert padded.source_curve_vertex_counts == counts
    assert SOURCE_CURVE_VERTEX_COUNTS_ATTRIBUTE in (
        PRODUCTION_STREAMLINES_PROFILE.persisted_attributes
    )


@pytest.mark.parametrize("invalid_count", [0, 3, 201])
def test_invalid_or_over_budget_source_count_fails(invalid_count: int) -> None:
    counts = (invalid_count,) + (4,) * 255
    point_count = max(0, sum(counts))

    with pytest.raises(ValueError, match="outside the frozen profile"):
        pad_streamlines_sample_for_renderer(
            profile_id=StreamlinesProfileId.GLOBAL_FLOW_PATH,
            points=tuple(range(point_count)),
            curve_vertex_counts=counts,
            speeds=(0.0,) * point_count,
        )


def test_point_sized_source_arrays_must_be_aligned() -> None:
    points, counts, speeds = _global_source_sample()

    with pytest.raises(ValueError, match="misaligned"):
        pad_streamlines_sample_for_renderer(
            profile_id=StreamlinesProfileId.GLOBAL_FLOW_PATH,
            points=points,
            curve_vertex_counts=counts,
            speeds=speeds[:-1],
        )


def test_authentic_speed_helper_excludes_terminal_padding() -> None:
    points, counts, speeds = _global_source_sample(count=4)
    padded = pad_streamlines_sample_for_renderer(
        profile_id=StreamlinesProfileId.GLOBAL_FLOW_PATH,
        points=points,
        curve_vertex_counts=counts,
        speeds=speeds,
    )

    authentic = authentic_values_from_padded_curves(
        padded.speeds,
        counts,
        vertices_per_curve=200,
    )

    assert authentic == speeds
    assert len(authentic) == 1024
    assert len(padded.speeds) == 51200


def test_renderer_topology_signature_is_constant_across_source_states() -> None:
    first = renderer_topology_for_profile(StreamlinesProfileId.GLOBAL_FLOW_PATH)
    second = renderer_topology_for_profile(StreamlinesProfileId.GLOBAL_FLOW_PATH)

    assert topology_signature(first.curve_vertex_counts) == topology_signature(
        second.curve_vertex_counts
    )


def test_point_signature_detects_real_temporal_position_changes() -> None:
    first = streamlines_point_array_signature(((0.0, 0.0, 0.0), (1.0, 1.0, 1.0)))
    same = streamlines_point_array_signature(((0.0, 0.0, 0.0), (1.0, 1.0, 1.0)))
    changed = streamlines_point_array_signature(((0.0, 0.0, 0.0), (1.0, 1.0, 1.25)))

    assert first.sha256 == same.sha256
    assert first.sha256 != changed.sha256
    assert first.point_count == changed.point_count == 2


def test_schema_five_invalidates_old_variable_topology_cache() -> None:
    assert CACHE_SCHEMA_VERSION == 5
    validation = validate_streamlines_cache(
        SimpleNamespace(schema_version=4),
        source=None,
        settings_signature="unused",
        geometry_path=Path("unused.usdc"),
    )

    assert not validation.valid
    assert validation.message == "Cache schema version is stale."


def test_prototype_builder_targets_only_volume_nominal(monkeypatch, tmp_path) -> None:
    metadata = SimpleNamespace()
    proofs = tuple(SimpleNamespace(passed=True) for _ in range(4))

    class Runtime(StreamlinesCacheRuntimeMixin):
        def __init__(self) -> None:
            self.config = SimpleNamespace(repo_root=tmp_path)
            self.builds = []

        @staticmethod
        def resolve_configured_airflow_targets():
            return (
                SimpleNamespace(
                    binding=SimpleNamespace(
                        workload_mode="Nominal",
                        dataset_identity="server/load_normal",
                    ),
                    dataset=object(),
                ),
            )

        async def build_streamlines_cache_in_kit(self, **kwargs):
            self.builds.append(kwargs)
            return StreamlinesCacheBuildResult(True, "built", metadata)

        async def ensure_streamlines_cache_validation_in_background(
            self, *_args, **_kwargs
        ):
            return SimpleNamespace(
                inspection=SimpleNamespace(valid=True, metadata=metadata)
            )

    monkeypatch.setattr(
        cache_runtime,
        "validate_persisted_constant_topology_cache",
        lambda *_args, **_kwargs: proofs,
    )
    runtime = Runtime()

    result = asyncio.run(runtime.build_validate_constant_topology_prototype_in_kit())

    assert result.success
    assert len(runtime.builds) == 1
    assert runtime.builds[0]["binding"].workload_mode == "Nominal"
    assert runtime.builds[0]["profile_id"] is StreamlinesProfileId.VOLUME_COVERAGE
