"""Focused persisted temporal-geometry liveness contracts."""

from pathlib import Path
from types import SimpleNamespace

from pxr import Gf, Sdf, Usd, UsdGeom, Vt

from digital_twin_runtime_suite.app.streamlines.cache import (
    CACHE_PLAYBACK_CURVES_PATH,
    CACHE_PLAYBACK_ROOT_PATH,
)
from digital_twin_runtime_suite.app.streamlines.constant_topology import (
    SOURCE_CURVE_VERTEX_COUNTS_ATTRIBUTE,
    pad_streamlines_sample_for_renderer,
)
from digital_twin_runtime_suite.app.streamlines.profile import StreamlinesProfileId
from digital_twin_runtime_suite.app.streamlines.temporal_liveness import (
    distributed_manifest_sample_indices,
    inspect_persisted_streamlines_temporal_geometry,
)


def test_persisted_moving_geometry_passes_without_renderer_assumptions(tmp_path):
    metadata = _write_cache(tmp_path / "moving.usdc", moving=True)

    evidence = inspect_persisted_streamlines_temporal_geometry(
        tmp_path / "moving.usdc",
        metadata,
    )

    assert evidence.passed is True
    assert evidence.distinct_geometry_state_hashes == len(evidence.sampled_states)
    assert evidence.nonzero_temporal_pair_count == len(evidence.temporal_pairs)


def test_identical_persisted_states_fail_temporal_liveness(tmp_path):
    metadata = _write_cache(tmp_path / "static.usdc", moving=False)

    evidence = inspect_persisted_streamlines_temporal_geometry(
        tmp_path / "static.usdc",
        metadata,
    )

    assert evidence.passed is False
    assert evidence.distinct_geometry_state_hashes == 1
    assert evidence.nonzero_temporal_pair_count == 0


def test_renderer_padding_cannot_create_temporal_liveness(tmp_path):
    metadata = _write_cache(tmp_path / "padding.usdc", moving=False, padding_moves=True)

    evidence = inspect_persisted_streamlines_temporal_geometry(
        tmp_path / "padding.usdc",
        metadata,
    )

    assert evidence.passed is False
    assert evidence.nonzero_temporal_pair_count == 0


def test_distributed_samples_derive_only_from_manifest_count():
    assert distributed_manifest_sample_indices(7) == (0, 1, 3, 4, 6)


def _write_cache(
    path: Path,
    *,
    moving: bool,
    padding_moves: bool = False,
):
    profile = StreamlinesProfileId.GLOBAL_FLOW_PATH
    sample_count = 7
    source_counts = (4,) * 256
    stage = Usd.Stage.CreateNew(str(path))
    UsdGeom.Xform.Define(stage, CACHE_PLAYBACK_ROOT_PATH)
    curves = UsdGeom.BasisCurves.Define(stage, CACHE_PLAYBACK_CURVES_PATH)
    source_counts_attribute = curves.GetPrim().CreateAttribute(
        SOURCE_CURVE_VERTEX_COUNTS_ATTRIBUTE,
        Sdf.ValueTypeNames.IntArray,
        custom=True,
    )
    states = []
    for index in range(sample_count):
        offset = float(index if moving else 0)
        source_points = tuple(
            Gf.Vec3f(offset + curve, vertex, 0.0)
            for curve in range(256)
            for vertex in range(4)
        )
        padded = list(
            pad_streamlines_sample_for_renderer(
                profile_id=profile,
                points=source_points,
                curve_vertex_counts=source_counts,
                speeds=(1.0,) * len(source_points),
            ).points
        )
        if padding_moves:
            padded[4] = Gf.Vec3f(float(index), 100.0, 100.0)
        time_code = Usd.TimeCode(float(index))
        curves.CreatePointsAttr().Set(Vt.Vec3fArray(padded), time_code)
        source_counts_attribute.Set(Vt.IntArray(source_counts), time_code)
        states.append(
            SimpleNamespace(
                sample_index=index,
                time_code=float(index),
                source_time_seconds=float(index),
                source_vti_identity=f"source-{index}",
            )
        )
    stage.GetRootLayer().Save()
    return SimpleNamespace(
        workload="Fixture",
        profile_id=profile.value,
        sample_count=sample_count,
        states=tuple(states),
    )
