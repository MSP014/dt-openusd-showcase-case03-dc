"""Own the disposable full-density ten-state renderer probe."""

from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass

PROBE_ROOT_PATH = "/DTRS_FullStateABProbe"
PROBE_STATE_PATHS = tuple(f"{PROBE_ROOT_PATH}/State_{index:02d}" for index in range(80))
_EXPECTED_STATES = 80
_EXPECTED_CURVES = 6_144
_EXPECTED_POINTS = 122_880
_PROBE_TRANSLATE_METRES = (0.0, 0.0, 0.0)
_PRODUCTION_PERIOD_SECONDS = 0.2
_PLAYBACK_LOOPS = 2


@dataclass(frozen=True)
class _StaticStates:
    points: tuple[object, ...]
    curve_vertex_counts: object
    width: float
    hashes: tuple[str, ...]


@dataclass
class _ActiveProbe:
    stage: object
    bundle_had_visibility: bool
    bundle_previous_visibility: object


_active_probe: _ActiveProbe | None = None


def _points_hash(points) -> str:
    import numpy as np

    values = np.ascontiguousarray(points, dtype=np.float32)
    return hashlib.sha256(values.tobytes()).hexdigest()


def _load_static_states(controller) -> _StaticStates:
    """Read all 80 states from the existing schema-5 cache."""

    from pxr import Usd

    from digital_twin_runtime_suite.app.streamlines.cache import (
        CACHE_PLAYBACK_CURVES_PATH,
        StreamlinesCacheOwnership,
        load_streamlines_cache_metadata,
        streamlines_cache_paths,
    )

    ownership = StreamlinesCacheOwnership(
        workload="Nominal",
        dataset_identity="server/load_normal",
        profile_id="volume_coverage",
    )
    paths = streamlines_cache_paths(controller.config.repo_root, ownership)
    metadata = load_streamlines_cache_metadata(paths.metadata_path)
    if metadata.schema_version != 5 or len(metadata.states) < _EXPECTED_STATES:
        raise RuntimeError(
            "Volume/Nominal schema-5 states 0 through 79 are unavailable."
        )
    source_stage = Usd.Stage.Open(str(paths.geometry_path))
    if source_stage is None:
        raise RuntimeError("Volume/Nominal centerline cache could not be opened.")
    source_curves = source_stage.GetPrimAtPath(CACHE_PLAYBACK_CURVES_PATH)
    if not source_curves or not source_curves.IsValid():
        raise RuntimeError("Centerline cache BasisCurves prim is unavailable.")
    points_attr = source_curves.GetAttribute("points")
    counts = source_curves.GetAttribute("curveVertexCounts").Get()
    points = tuple(
        points_attr.Get(Usd.TimeCode(state.time_code))
        for state in metadata.states[:_EXPECTED_STATES]
    )
    if (
        len(counts) != _EXPECTED_CURVES
        or any(int(value) != 20 for value in counts)
        or sum(int(value) for value in counts) != _EXPECTED_POINTS
        or any(len(state_points) != _EXPECTED_POINTS for state_points in points)
    ):
        raise RuntimeError("Full-state fixed-topology cache contract is invalid.")
    hashes = tuple(_points_hash(state_points) for state_points in points)
    if len(set(hashes)) < 2:
        raise RuntimeError("Cached states 0 through 79 have identical point arrays.")
    return _StaticStates(
        points=points,
        curve_vertex_counts=counts,
        width=float(metadata.settings.width),
        hashes=hashes,
    )


def _author_state(stage, path: str, points, counts, width: float) -> object:
    from pxr import Gf, UsdGeom

    curves = UsdGeom.BasisCurves.Define(stage, path)
    curves.CreateTypeAttr(UsdGeom.Tokens.linear)
    curves.CreateWrapAttr(UsdGeom.Tokens.nonperiodic)
    curves.CreateCurveVertexCountsAttr(counts)
    curves.CreatePointsAttr(points)
    curves.CreateWidthsAttr([width])
    curves.SetWidthsInterpolation(UsdGeom.Tokens.constant)
    curves.CreateVisibilityAttr(UsdGeom.Tokens.invisible)
    display_color = curves.CreateDisplayColorAttr([Gf.Vec3f(0.0, 0.8, 1.0)])
    UsdGeom.Primvar(display_color).SetInterpolation(UsdGeom.Tokens.constant)
    return curves.GetPrim()


def _author_static_states(stage, states: _StaticStates) -> tuple[object, ...]:
    """Create 80 immutable full-density states under one fixed transform."""

    from pxr import Gf, UsdGeom

    stage.RemovePrim(PROBE_ROOT_PATH)
    root = UsdGeom.Xform.Define(stage, PROBE_ROOT_PATH)
    root.AddTranslateOp().Set(Gf.Vec3d(*_PROBE_TRANSLATE_METRES))
    return tuple(
        _author_state(
            stage,
            path,
            points,
            states.curve_vertex_counts,
            states.width,
        )
        for path, points in zip(PROBE_STATE_PATHS, states.points, strict=True)
    )


def _set_visible(prim, visible: bool) -> None:
    from pxr import UsdGeom

    value = UsdGeom.Tokens.inherited if visible else UsdGeom.Tokens.invisible
    UsdGeom.Imageable(prim).GetVisibilityAttr().Set(value)


async def _run_production_cadence(states) -> tuple[int, int, tuple]:
    """Show all 80 states twice at fixed 200 ms deadlines."""

    import omni.kit.app
    from pxr import UsdGeom

    from digital_twin_runtime_suite.app.flow.performance import (
        capture_viewport_performance_sample,
    )

    started_at = time.monotonic()
    missed_deadlines = 0
    visible_states_max = 0
    performance = []
    total_ticks = _EXPECTED_STATES * _PLAYBACK_LOOPS
    previous_index = None
    for tick_index in range(total_ticks):
        deadline = started_at + tick_index * _PRODUCTION_PERIOD_SECONDS
        delay = deadline - time.monotonic()
        if delay > 0.0:
            await asyncio.sleep(delay)
        tick_started_at = time.monotonic()
        visible_index = tick_index % _EXPECTED_STATES
        if previous_index is not None:
            _set_visible(states[previous_index], False)
        _set_visible(states[visible_index], True)
        await omni.kit.app.get_app().next_update_async()
        visible_count = sum(
            state.GetAttribute("visibility").Get() != UsdGeom.Tokens.invisible
            for state in states
        )
        visible_states_max = max(visible_states_max, visible_count)
        if visible_count != 1:
            raise RuntimeError(
                "Static playback requires exactly one visible state; "
                f"observed={visible_count}."
            )
        performance.append(capture_viewport_performance_sample())
        missed_deadlines += int(
            tick_started_at - deadline >= _PRODUCTION_PERIOD_SECONDS
        )
        previous_index = visible_index
    final_deadline = started_at + total_ticks * _PRODUCTION_PERIOD_SECONDS
    final_delay = final_deadline - time.monotonic()
    if final_delay > 0.0:
        await asyncio.sleep(final_delay)
    return missed_deadlines, visible_states_max, tuple(performance)


def full_state_ab_probe_ready_in_kit() -> bool:
    """Return whether the normal Streamlines presentation is available."""

    import omni.usd

    from digital_twin_runtime_suite.app.streamlines.mesh_cache import (
        MESH_CACHE_GEOMETRY_PATH,
    )

    stage = omni.usd.get_context().get_stage()
    if stage is None:
        return False
    bundle = stage.GetPrimAtPath(MESH_CACHE_GEOMETRY_PATH)
    return bool(bundle and bundle.IsValid())


def cleanup_full_state_ab_probe_in_kit() -> bool:
    """Remove all 80 states and restore normal presentation visibility."""

    global _active_probe

    active = _active_probe
    if active is None:
        return False
    from pxr import Sdf, UsdGeom

    from digital_twin_runtime_suite.app.streamlines.mesh_cache import (
        MESH_CACHE_GEOMETRY_PATH,
    )

    stage = active.stage
    session = stage.GetSessionLayer()
    previous_target = stage.GetEditTarget()
    bundle_path = Sdf.Path(MESH_CACHE_GEOMETRY_PATH)
    visibility_path = bundle_path.AppendProperty("visibility")
    try:
        stage.SetEditTarget(session)
        stage.RemovePrim(PROBE_ROOT_PATH)
        bundle = stage.GetPrimAtPath(MESH_CACHE_GEOMETRY_PATH)
        bundle_spec = session.GetPrimAtPath(bundle_path)
        visibility_spec = session.GetAttributeAtPath(visibility_path)
        if active.bundle_had_visibility and visibility_spec:
            visibility_spec.default = active.bundle_previous_visibility
        elif visibility_spec and bundle_spec:
            bundle_spec.RemoveProperty(visibility_spec)
        if bundle and bundle.IsValid() and active.bundle_had_visibility:
            UsdGeom.Imageable(bundle).GetVisibilityAttr().Set(
                active.bundle_previous_visibility
            )
    finally:
        stage.SetEditTarget(previous_target)
        _active_probe = None
    return True


async def run_full_state_ab_probe_in_kit(controller) -> str:
    """Author 80 static states, then run two visibility-only loops."""

    global _active_probe

    import carb
    import omni.usd
    from pxr import Sdf

    from digital_twin_runtime_suite.app.flow.performance import (
        capture_viewport_performance_sample,
    )
    from digital_twin_runtime_suite.app.streamlines.mesh_cache import (
        MESH_CACHE_GEOMETRY_PATH,
    )

    stage = omni.usd.get_context().get_stage()
    bundle = stage.GetPrimAtPath(MESH_CACHE_GEOMETRY_PATH) if stage else None
    if stage is None or not bundle or not bundle.IsValid():
        carb.log_error(
            "DTRS STREAMLINES | FULL_80_STATE_PROBE | FAIL | "
            "Visible Streamlines presentation is unavailable."
        )
        return "FAILED"
    session = stage.GetSessionLayer()
    bundle_path = Sdf.Path(MESH_CACHE_GEOMETRY_PATH)
    visibility_path = bundle_path.AppendProperty("visibility")
    previous_visibility_spec = session.GetAttributeAtPath(visibility_path)
    previous_target = stage.GetEditTarget()
    try:
        await controller.release_streamlines_timeline_control_in_kit()
        if controller._active_streamlines_playback_task_count() != 0:
            raise RuntimeError("Production Streamlines scheduler did not stop.")
        memory_before = capture_viewport_performance_sample()
        source_states = _load_static_states(controller)
        stage.SetEditTarget(session)
        _active_probe = _ActiveProbe(
            stage=stage,
            bundle_had_visibility=bool(previous_visibility_spec),
            bundle_previous_visibility=(
                previous_visibility_spec.default if previous_visibility_spec else None
            ),
        )
        states = _author_static_states(stage, source_states)
        expected_hashes = source_states.hashes
        authored_hashes = tuple(
            _points_hash(state.GetAttribute("points").Get()) for state in states
        )
        if authored_hashes != expected_hashes:
            raise RuntimeError("Authored static state points changed during setup.")
        del source_states
        _set_visible(bundle, False)
        import omni.kit.app

        await omni.kit.app.get_app().next_update_async()
        memory_after = capture_viewport_performance_sample()
        missed_deadlines, visible_states_max, performance = (
            await _run_production_cadence(states)
        )
        points_attributes = tuple(state.GetAttribute("points") for state in states)
        if any(attribute.GetTimeSamples() for attribute in points_attributes):
            raise RuntimeError("Static full-state probe authored time samples.")
        final_hashes = tuple(
            _points_hash(attribute.Get()) for attribute in points_attributes
        )
        if final_hashes != expected_hashes:
            raise RuntimeError("Authored static state points changed during probe.")
        fps = [sample.fps for sample in performance if sample.fps is not None]
        gpu_during = _maximum_metric(
            performance,
            "gpu_memory_used_gib",
        )
        process_during = _maximum_metric(
            performance,
            "process_memory_used_gib",
        )
        carb.log_warn(
            "DTRS STREAMLINES | FULL_80_STATE_PROBE | COMPLETE\n"
            "status=technical evidence only\n"
            "states=80\n"
            "curves_per_state=6144\n"
            "scheduler_tasks=1\n"
            f"missed_deadlines={missed_deadlines}\n"
            f"visible_states_max={visible_states_max}\n"
            f"viewport_fps_average={_average(fps)}\n"
            f"viewport_fps_minimum={_minimum(fps)}\n\n"
            "gpu_used_gib_before_states="
            f"{_metric(memory_before, 'gpu_memory_used_gib')}\n"
            "gpu_used_gib_after_states="
            f"{_metric(memory_after, 'gpu_memory_used_gib')}\n"
            f"gpu_used_gib_during_playback={gpu_during}\n"
            "process_used_gib_before_states="
            f"{_metric(memory_before, 'process_memory_used_gib')}\n"
            "process_used_gib_after_states="
            f"{_metric(memory_after, 'process_memory_used_gib')}\n"
            f"process_used_gib_during_playback={process_during}\n\n"
            "NEXT_ACTION | Confirm visually: Streamlines continuously evolve "
            "through all 80 states; no flicker/disappearance or frozen states; "
            "79 -> 0 wrap is acceptable; playback remains usable."
        )
        return "ACTIVE"
    except asyncio.CancelledError:
        raise
    except Exception as error:  # noqa: BLE001 - isolate the diagnostic failure.
        carb.log_error(f"DTRS STREAMLINES | FULL_80_STATE_PROBE | FAIL | {error}")
        cleanup_full_state_ab_probe_in_kit()
        return "FAILED"
    finally:
        stage.SetEditTarget(previous_target)


def _average(values) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def _minimum(values) -> float | None:
    return round(min(values), 2) if values else None


def _metric(sample, name: str) -> float | None:
    value = getattr(sample, name, None)
    return round(float(value), 3) if value is not None else None


def _maximum_metric(samples, name: str) -> float | None:
    values = [
        float(value)
        for sample in samples
        if (value := getattr(sample, name, None)) is not None
    ]
    return round(max(values), 3) if values else None
