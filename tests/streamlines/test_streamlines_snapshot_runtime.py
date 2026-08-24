# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""Focused contracts for static persisted Streamlines snapshot ownership."""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from digital_twin_runtime_suite.app.streamlines.cache import (
    CACHE_PLAYBACK_CURVES_PATH,
    CACHE_PLAYBACK_ROOT_PATH,
)
from digital_twin_runtime_suite.app.streamlines.snapshot_runtime import (
    SNAPSHOTS_ROOT_PATH,
    SOURCE_TIME_ATTRIBUTE,
    StreamlinesSnapshotRuntimeMixin,
)
from digital_twin_runtime_suite.app.streamlines.speed import (
    SPEED_PRIMVAR_ATTRIBUTE,
    SPEED_PRIMVAR_NAME,
)


class _Runtime(StreamlinesSnapshotRuntimeMixin):
    def __init__(self) -> None:
        self._streamlines_cache_active_sample_index = None
        self.reset_streamlines_snapshot_runtime_state()


def _pxr_modules():
    from pxr import Gf, Sdf, Usd, UsdGeom, Vt

    return Gf, Sdf, Usd, UsdGeom, Vt


def _install_omni_usd(monkeypatch, stage) -> None:
    omni_module = ModuleType("omni")
    usd_module = ModuleType("omni.usd")
    usd_module.get_context = lambda: SimpleNamespace(get_stage=lambda: stage)
    omni_module.usd = usd_module
    monkeypatch.setitem(sys.modules, "omni", omni_module)
    monkeypatch.setitem(sys.modules, "omni.usd", usd_module)


def _metadata(*, point_counts=(6, 6, 6)):
    states = tuple(
        SimpleNamespace(
            sample_index=index,
            time_code=float(index),
            source_time_seconds=index / 10.0,
            curve_count=2,
            point_count=point_counts[index],
        )
        for index in range(3)
    )
    return SimpleNamespace(
        valid=True,
        workload="Nominal",
        dataset_identity="server/load_normal",
        profile_id="volume_coverage",
        geometry_sha256="three-state-cache",
        sample_count=3,
        states=states,
        settings=SimpleNamespace(width=0.05),
    )


def _write_source_cache(
    path: Path,
    *,
    include_widths: bool = True,
    source_type: str = "linear",
    source_wrap: str = "nonperiodic",
    source_basis: str | None = None,
) -> None:
    Gf, Sdf, Usd, UsdGeom, Vt = _pxr_modules()

    stage = Usd.Stage.CreateNew(str(path))
    UsdGeom.Xform.Define(stage, CACHE_PLAYBACK_ROOT_PATH)
    curves = UsdGeom.BasisCurves.Define(stage, CACHE_PLAYBACK_CURVES_PATH)
    curves.CreateTypeAttr(source_type)
    curves.CreateWrapAttr(source_wrap)
    if source_basis is not None:
        curves.CreateBasisAttr(source_basis)
    curves.CreateCurveVertexCountsAttr(Vt.IntArray((3, 3)))
    if include_widths:
        curves.CreateWidthsAttr(Vt.FloatArray((0.05,)))
        curves.SetWidthsInterpolation(UsdGeom.Tokens.constant)
    speed = UsdGeom.PrimvarsAPI(curves.GetPrim()).CreatePrimvar(
        SPEED_PRIMVAR_NAME,
        Sdf.ValueTypeNames.FloatArray,
        UsdGeom.Tokens.vertex,
    )
    source_time = curves.GetPrim().CreateAttribute(
        SOURCE_TIME_ATTRIBUTE,
        Sdf.ValueTypeNames.Double,
        custom=True,
    )
    for index in range(3):
        time_code = Usd.TimeCode(float(index))
        offset = float(index)
        points = Vt.Vec3fArray(
            (
                Gf.Vec3f(offset, 0.0, 0.0),
                Gf.Vec3f(offset, 0.0, 1.0),
                Gf.Vec3f(offset, 0.0, 2.0),
                Gf.Vec3f(offset + 1.0, 0.0, 0.0),
                Gf.Vec3f(offset + 1.0, 0.0, 1.0),
                Gf.Vec3f(offset + 1.0, 0.0, 2.0),
            )
        )
        curves.CreatePointsAttr().Set(points, time_code)
        curves.CreateExtentAttr().Set(
            Vt.Vec3fArray(
                (
                    Gf.Vec3f(offset, 0.0, 0.0),
                    Gf.Vec3f(offset + 1.0, 0.0, 2.0),
                )
            ),
            time_code,
        )
        speed.Set(Vt.FloatArray((1.0 + index,) * 6), time_code)
        source_time.Set(index / 10.0, time_code)
    stage.GetRootLayer().Save()


def _prepared_runtime(tmp_path, monkeypatch, *, runtime_type=_Runtime):
    _Gf, _Sdf, Usd, _UsdGeom, _Vt = _pxr_modules()
    source_path = tmp_path / "streamlines_cache.usdc"
    _write_source_cache(source_path)
    stage = Usd.Stage.CreateInMemory()
    _install_omni_usd(monkeypatch, stage)
    runtime = runtime_type()
    ownership = runtime.prepare_streamlines_snapshots_in_kit(
        _metadata(),
        source_path,
    )
    return runtime, stage, source_path, ownership


def test_metadata_states_materialise_as_one_static_basis_curves_prim_each(
    tmp_path,
    monkeypatch,
) -> None:
    runtime, stage, _source, ownership = _prepared_runtime(tmp_path, monkeypatch)

    assert len(ownership.states) == 3
    assert [state.sample_index for state in ownership.states] == [0, 1, 2]
    assert all(
        stage.GetPrimAtPath(state.prim_path).GetTypeName() == "BasisCurves"
        for state in ownership.states
    )
    assert runtime.streamlines_snapshot_visible_count_in_kit() == 0


def test_static_snapshots_have_no_usd_time_samples(tmp_path, monkeypatch) -> None:
    _runtime, stage, _source, ownership = _prepared_runtime(tmp_path, monkeypatch)

    for state in ownership.states:
        prim = stage.GetPrimAtPath(state.prim_path)
        for name in (
            "curveVertexCounts",
            "points",
            "widths",
            "extent",
            SPEED_PRIMVAR_ATTRIBUTE,
            SOURCE_TIME_ATTRIBUTE,
        ):
            assert prim.GetAttribute(name).GetTimeSamples() == []


def test_metadata_width_is_used_when_persisted_widths_are_absent(
    tmp_path,
    monkeypatch,
) -> None:
    _Gf, _Sdf, Usd, UsdGeom, _Vt = _pxr_modules()
    source_path = tmp_path / "streamlines_cache.usdc"
    _write_source_cache(source_path, include_widths=False)
    stage = Usd.Stage.CreateInMemory()
    _install_omni_usd(monkeypatch, stage)

    ownership = _Runtime().prepare_streamlines_snapshots_in_kit(
        _metadata(),
        source_path,
    )

    snapshot = stage.GetPrimAtPath(ownership.state_path_for(0))
    assert list(snapshot.GetAttribute("widths").Get()) == pytest.approx([0.05])
    assert UsdGeom.BasisCurves(snapshot).GetWidthsInterpolation() == (
        UsdGeom.Tokens.constant
    )


def test_snapshots_use_the_proven_linear_nonperiodic_renderer_contract(
    tmp_path,
    monkeypatch,
) -> None:
    _Gf, _Sdf, Usd, UsdGeom, _Vt = _pxr_modules()
    source_path = tmp_path / "streamlines_cache.usdc"
    _write_source_cache(
        source_path,
        source_type="cubic",
        source_wrap="pinned",
        source_basis="bspline",
    )
    stage = Usd.Stage.CreateInMemory()
    _install_omni_usd(monkeypatch, stage)

    ownership = _Runtime().prepare_streamlines_snapshots_in_kit(
        _metadata(),
        source_path,
    )

    curves = UsdGeom.BasisCurves(stage.GetPrimAtPath(ownership.state_path_for(0)))
    assert curves.GetTypeAttr().Get() == UsdGeom.Tokens.linear
    assert curves.GetWrapAttr().Get() == UsdGeom.Tokens.nonperiodic


def test_each_snapshot_copies_one_matching_persisted_source_state(
    tmp_path,
    monkeypatch,
) -> None:
    _Gf, _Sdf, Usd, _UsdGeom, _Vt = _pxr_modules()
    _runtime, stage, source_path, ownership = _prepared_runtime(tmp_path, monkeypatch)
    source_stage = Usd.Stage.Open(str(source_path))
    source = source_stage.GetPrimAtPath(CACHE_PLAYBACK_CURVES_PATH)

    for state in ownership.states:
        time_code = Usd.TimeCode(float(state.sample_index))
        snapshot = stage.GetPrimAtPath(state.prim_path)
        assert list(snapshot.GetAttribute("points").Get()) == list(
            source.GetAttribute("points").Get(time_code)
        )
        assert list(snapshot.GetAttribute(SPEED_PRIMVAR_ATTRIBUTE).Get()) == list(
            source.GetAttribute(SPEED_PRIMVAR_ATTRIBUTE).Get(time_code)
        )
        assert list(snapshot.GetAttribute("extent").Get()) == list(
            source.GetAttribute("extent").Get(time_code)
        )
        assert snapshot.GetAttribute(SOURCE_TIME_ATTRIBUTE).Get() == (
            source.GetAttribute(SOURCE_TIME_ATTRIBUTE).Get(time_code)
        )
        assert state.matches_persisted_geometry is True


def test_selection_commits_one_visible_snapshot_and_active_index(
    tmp_path,
    monkeypatch,
) -> None:
    runtime, stage, _source, ownership = _prepared_runtime(tmp_path, monkeypatch)

    assert runtime.select_streamlines_snapshot_state_in_kit(0)
    assert runtime.select_streamlines_snapshot_state_in_kit(1)
    assert runtime._streamlines_cache_active_sample_index == 1
    assert runtime.streamlines_snapshot_visible_count_in_kit() == 1
    assert (
        stage.GetPrimAtPath(ownership.state_path_for(1))
        .GetAttribute("visibility")
        .Get()
        == "inherited"
    )


def test_snapshot_root_evidence_is_empty_before_kit_opens_a_stage(
    monkeypatch,
) -> None:
    _install_omni_usd(monkeypatch, None)

    assert _Runtime().streamlines_snapshot_root_count_in_kit() == 0


def test_failed_selection_preserves_the_previous_visible_snapshot(
    tmp_path,
    monkeypatch,
) -> None:
    runtime, stage, _source, ownership = _prepared_runtime(tmp_path, monkeypatch)
    runtime.select_streamlines_snapshot_state_in_kit(0)
    previous = ownership.state_path_for(0)
    target = ownership.state_path_for(1)

    original_set_visibility = runtime._set_streamlines_snapshot_visibility

    def fail_target_visibility(prim, visible: bool) -> None:
        if prim.GetPath().pathString == target and visible:
            raise RuntimeError("synthetic visibility authoring failure")
        original_set_visibility(prim, visible)

    monkeypatch.setattr(
        runtime,
        "_set_streamlines_snapshot_visibility",
        fail_target_visibility,
    )
    with pytest.raises(RuntimeError, match="synthetic visibility authoring failure"):
        runtime.select_streamlines_snapshot_state_in_kit(1)

    assert runtime._streamlines_cache_active_sample_index == 0
    assert runtime.streamlines_snapshot_visible_count_in_kit() == 1
    assert stage.GetPrimAtPath(previous).GetAttribute("visibility").Get() == "inherited"


def test_partial_preparation_failure_removes_the_snapshot_hierarchy(
    tmp_path,
    monkeypatch,
) -> None:
    _Gf, _Sdf, Usd, _UsdGeom, _Vt = _pxr_modules()
    source_path = tmp_path / "streamlines_cache.usdc"
    _write_source_cache(source_path)
    stage = Usd.Stage.CreateInMemory()
    _install_omni_usd(monkeypatch, stage)
    runtime = _Runtime()

    with pytest.raises(RuntimeError, match="bad data"):
        runtime.prepare_streamlines_snapshots_in_kit(
            _metadata(point_counts=(6, 7, 6)),
            source_path,
        )

    assert not stage.GetPrimAtPath(SNAPSHOTS_ROOT_PATH).IsValid()
    assert runtime._streamlines_snapshot_set_ownership is None


def test_cleanup_removes_snapshots_and_clears_transient_ownership(
    tmp_path,
    monkeypatch,
) -> None:
    runtime, stage, _source, _ownership = _prepared_runtime(tmp_path, monkeypatch)
    runtime.select_streamlines_snapshot_state_in_kit(0)

    assert runtime.cleanup_streamlines_snapshots_in_kit()
    assert not stage.GetPrimAtPath(SNAPSHOTS_ROOT_PATH).IsValid()
    assert runtime._streamlines_snapshot_set_ownership is None
    assert runtime._streamlines_snapshot_active_sample_index is None
    assert runtime._streamlines_cache_active_sample_index is None


def test_snapshot_runtime_has_no_current_probe_dataset_assumptions() -> None:
    source = Path(
        "src/digital_twin_runtime_suite/app/streamlines/snapshot_runtime.py"
    ).read_text(encoding="utf-8")

    for forbidden in ("Nominal", "volume_coverage", "80", "6144", "122880", "0.2"):
        assert forbidden not in source
