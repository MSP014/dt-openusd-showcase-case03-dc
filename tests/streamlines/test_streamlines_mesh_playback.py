from __future__ import annotations

import asyncio
import sys
from dataclasses import replace
from pathlib import Path
from types import ModuleType, SimpleNamespace

import numpy as np
import pytest

from digital_twin_runtime_suite.app.manual_acceptance import (
    GuidedAcceptanceSession,
)
from digital_twin_runtime_suite.app.streamlines.mesh_cache import (
    PROTOTYPE_CURVE_COUNT,
    PROTOTYPE_POINTS_PER_CURVE,
    load_streamlines_mesh_cache_receipt,
    mesh_cache_paths,
    validate_streamlines_mesh_prototype_cache,
)
from digital_twin_runtime_suite.app.streamlines.mesh_conversion import (
    build_streamlines_tube_mesh_topology,
    convert_streamlines_centerlines_to_tube_mesh,
    validate_streamlines_tube_mesh_topology,
)
from digital_twin_runtime_suite.app.streamlines.mesh_playback_acceptance import (
    StreamlinesMeshPlaybackAcceptanceMixin,
)
from digital_twin_runtime_suite.app.streamlines.mesh_playback_runtime import (
    StreamlinesMeshPlaybackRuntimeMixin,
)


def _small_source():
    points = np.asarray(
        [
            (0.0, 0.0, 0.0),
            (0.0, 0.0, 1.0),
            (0.0, 0.0, 1.0),
            (2.0, 0.0, 0.0),
            (2.0, 0.0, 1.0),
            (2.0, 0.0, 2.0),
        ],
        dtype=np.float32,
    )
    return (
        points,
        np.asarray((3, 3), dtype=np.int32),
        np.asarray((2, 3), dtype=np.int32),
        np.asarray((1.0, 2.0, 2.0, 3.0, 4.0, 5.0), dtype=np.float32),
    )


def test_installed_vtk_curve_to_mesh_is_deterministic_and_fixed_topology():
    topology = build_streamlines_tube_mesh_topology(
        curve_count=2,
        centerline_points_per_curve=3,
    )
    source = _small_source()
    first = convert_streamlines_centerlines_to_tube_mesh(
        *source,
        radius=0.1,
        topology=topology,
    )
    second = convert_streamlines_centerlines_to_tube_mesh(
        *source,
        radius=0.1,
        topology=topology,
    )
    assert topology.point_count == 24
    assert len(topology.face_vertex_counts) == 32
    assert np.array_equal(first.points, second.points)
    assert np.array_equal(first.speeds, second.speeds)


def test_mesh_mapping_repeats_exact_authoritative_source_speed():
    topology = build_streamlines_tube_mesh_topology(
        curve_count=2,
        centerline_points_per_curve=3,
    )
    state = convert_streamlines_centerlines_to_tube_mesh(
        *_small_source(),
        radius=0.1,
        topology=topology,
    )
    assert np.array_equal(
        state.speeds,
        _small_source()[3][topology.source_point_indices],
    )
    assert topology.source_point_indices.min() == 0
    assert topology.source_point_indices.max() == 5


def test_terminal_centerline_padding_repeats_only_terminal_mesh_ring():
    topology = build_streamlines_tube_mesh_topology(
        curve_count=2,
        centerline_points_per_curve=3,
    )
    state = convert_streamlines_centerlines_to_tube_mesh(
        *_small_source(),
        radius=0.1,
        topology=topology,
    )
    rings = state.points.reshape((6, 4, 3))
    assert np.array_equal(rings[2], rings[1])
    assert not np.array_equal(rings[4], rings[5])


def test_static_mesh_face_indices_reference_only_existing_vertices():
    topology = build_streamlines_tube_mesh_topology(
        curve_count=2,
        centerline_points_per_curve=3,
    )
    assert topology.face_vertex_indices.min() == 0
    assert topology.face_vertex_indices.max() < topology.point_count
    broken = replace(
        topology,
        face_vertex_indices=np.asarray(
            [*topology.face_vertex_indices[:-1], topology.point_count],
            dtype=np.int32,
        ),
    )
    with pytest.raises(ValueError, match="out-of-range"):
        validate_streamlines_tube_mesh_topology(broken)


@pytest.mark.parametrize("source_counts", [(0, 3), (4, 3)])
def test_invalid_authentic_curve_count_is_rejected(source_counts):
    topology = build_streamlines_tube_mesh_topology(
        curve_count=2,
        centerline_points_per_curve=3,
    )
    points, renderer_counts, _counts, speeds = _small_source()
    with pytest.raises(ValueError, match="authentic curve"):
        convert_streamlines_centerlines_to_tube_mesh(
            points,
            renderer_counts,
            np.asarray(source_counts, dtype=np.int32),
            speeds,
            radius=0.1,
            topology=topology,
        )


def test_built_volume_nominal_prototype_passes_complete_offline_gate():
    source = Path(
        "cache/streamlines/nominal/server_load_normal/volume_coverage/"
        "streamlines_cache.usdc"
    )
    mesh, metadata = mesh_cache_paths(source)
    if not source.is_file() or not mesh.is_file() or not metadata.is_file():
        pytest.skip("Local Volume/Nominal Mesh prototype is unavailable.")
    receipt = load_streamlines_mesh_cache_receipt(metadata)
    validate_streamlines_mesh_prototype_cache(
        mesh,
        receipt,
        source_geometry_path=source,
    )
    assert receipt.curve_count == PROTOTYPE_CURVE_COUNT
    assert receipt.centerline_points_per_curve == PROTOTYPE_POINTS_PER_CURVE
    assert receipt.mesh_point_count == 491_520
    assert receipt.triangle_count == 933_888
    hashes = {receipt.states[index].mesh_points_sha256 for index in (0, 1, 2, 10, 79)}
    assert len(hashes) == 5


class _Timeline:
    def __init__(self):
        self.current = 7.0
        self.playing = True
        self.pause_calls = 0
        self.set_calls = []
        self.play_calls = 0

    def get_current_time(self):
        return self.current

    def is_playing(self):
        return self.playing

    def pause(self):
        self.pause_calls += 1
        self.playing = False

    def set_current_time(self, value):
        self.current = value
        self.set_calls.append(value)

    def play(self):
        self.play_calls += 1
        self.playing = True


class _MeshPrim:
    def IsValid(self):
        return True

    def GetTypeName(self):
        return "Mesh"


class _Stage:
    def GetPrimAtPath(self, _path):
        return _MeshPrim()


class _Runtime(StreamlinesMeshPlaybackRuntimeMixin):
    def __init__(self):
        self.reset_streamlines_mesh_playback_state()
        state = SimpleNamespace(
            sample_index=1,
            source_time_seconds=0.2,
            time_code=10.0,
        )
        self._streamlines_mesh_cache_receipt = SimpleNamespace(states=(state,))
        self._streamlines_mesh_points_time_codes = (10.0,)
        self._streamlines_mesh_speed_time_codes = (10.0,)
        self._streamlines_cache_active_sample_index = 0


def _install_fake_omni(monkeypatch, timeline, app):
    omni = ModuleType("omni")
    timeline_module = ModuleType("omni.timeline")
    timeline_module.get_timeline_interface = lambda: timeline
    kit_module = ModuleType("omni.kit")
    app_module = ModuleType("omni.kit.app")
    app_module.get_app = lambda: app
    usd_module = ModuleType("omni.usd")
    usd_module.get_context = lambda: SimpleNamespace(get_stage=lambda: _Stage())
    omni.timeline = timeline_module
    omni.kit = kit_module
    omni.usd = usd_module
    kit_module.app = app_module
    monkeypatch.setitem(sys.modules, "omni", omni)
    monkeypatch.setitem(sys.modules, "omni.timeline", timeline_module)
    monkeypatch.setitem(sys.modules, "omni.kit", kit_module)
    monkeypatch.setitem(sys.modules, "omni.kit.app", app_module)
    monkeypatch.setitem(sys.modules, "omni.usd", usd_module)


def test_mesh_tick_selects_time_only_and_copies_no_python_points(monkeypatch):
    timeline = _Timeline()
    app = SimpleNamespace(next_update_async=lambda: asyncio.sleep(0))
    _install_fake_omni(monkeypatch, timeline, app)
    runtime = _Runtime()
    runtime.acquire_streamlines_timeline_control_in_kit()
    asyncio.run(
        runtime.select_streamlines_mesh_state_in_kit(SimpleNamespace(sample_index=1))
    )
    assert timeline.pause_calls == 1
    assert timeline.set_calls == [0.2]
    assert runtime._streamlines_cache_active_sample_index == 1
    assert runtime.streamlines_mesh_runtime_counters() == {
        "runtime_mesh_conversion": 0,
        "python_point_copy": 0,
    }


def test_missing_mesh_state_preserves_previous_active_sample(monkeypatch):
    timeline = _Timeline()
    app = SimpleNamespace(next_update_async=lambda: asyncio.sleep(0))
    _install_fake_omni(monkeypatch, timeline, app)
    runtime = _Runtime()
    runtime.acquire_streamlines_timeline_control_in_kit()
    with pytest.raises(RuntimeError, match="unavailable"):
        asyncio.run(
            runtime.select_streamlines_mesh_state_in_kit(
                SimpleNamespace(sample_index=2)
            )
        )
    assert runtime._streamlines_cache_active_sample_index == 0
    assert timeline.set_calls == []


def test_superseded_mesh_update_cannot_late_commit(monkeypatch):
    timeline = _Timeline()
    runtime = _Runtime()

    async def supersede():
        runtime.invalidate_streamlines_mesh_playback_updates()

    app = SimpleNamespace(next_update_async=supersede)
    _install_fake_omni(monkeypatch, timeline, app)
    runtime.acquire_streamlines_timeline_control_in_kit()
    with pytest.raises(RuntimeError, match="superseded"):
        asyncio.run(
            runtime.select_streamlines_mesh_state_in_kit(
                SimpleNamespace(sample_index=1)
            )
        )
    assert runtime._streamlines_cache_active_sample_index == 0


def test_timeline_is_paused_once_and_restored_after_mesh_playback(monkeypatch):
    timeline = _Timeline()
    app = SimpleNamespace(next_update_async=lambda: asyncio.sleep(0))
    _install_fake_omni(monkeypatch, timeline, app)
    runtime = _Runtime()
    runtime.acquire_streamlines_timeline_control_in_kit()
    runtime.acquire_streamlines_timeline_control_in_kit()
    asyncio.run(runtime.release_streamlines_mesh_timeline_control_in_kit())
    assert timeline.pause_calls == 1
    assert timeline.set_calls == [7.0]
    assert timeline.play_calls == 1


class _Acceptance(StreamlinesMeshPlaybackAcceptanceMixin):
    def __init__(self):
        self.messages = []
        self.reset_streamlines_mesh_playback_acceptance_state()

    def _streamlines_mesh_acceptance_emit(self, message):
        self.messages.append(message)


def test_technical_complete_cannot_emit_terminal_without_manual_approval():
    runtime = _Acceptance()
    session = GuidedAcceptanceSession(("start", "technical", "visual"))
    session.begin()
    assert session.record("start")
    assert session.record("technical")
    runtime._streamlines_mesh_acceptance_session = session
    assert not session.complete()
    assert runtime.confirm_streamlines_mesh_playback()
    assert sum("TEST COMPLETE" in item for item in runtime.messages) == 1


def test_manual_failure_blocks_mesh_playback_success():
    runtime = _Acceptance()
    session = GuidedAcceptanceSession(("start", "technical", "visual"))
    session.begin()
    assert session.record("start")
    assert session.record("technical")
    runtime._streamlines_mesh_acceptance_session = session
    assert runtime.reject_streamlines_mesh_playback()
    assert not runtime.confirm_streamlines_mesh_playback()
    assert not any("TEST COMPLETE" in item for item in runtime.messages)
