"""Own the disposable Streamlines renderer Xform control probe."""

from __future__ import annotations

import asyncio
import hashlib

_PROBE_OP_SUFFIX = "dtrsXformProbe"
_PROBE_TRANSLATIONS_METRES = (0.0, 0.1, 0.0)


def _points_hash(points) -> str:
    import numpy as np

    values = np.ascontiguousarray(points, dtype=np.float32)
    return hashlib.sha256(values.tobytes()).hexdigest()


async def run_streamlines_xform_probe_in_kit(controller) -> bool:
    """Move only the existing presentation parent while preserving Mesh points."""

    import carb
    import omni.kit.app
    import omni.timeline
    import omni.usd
    from pxr import Gf, Sdf, Usd, UsdGeom

    from digital_twin_runtime_suite.app.streamlines.mesh_cache import (
        MESH_CACHE_GEOMETRY_PATH,
        MESH_CACHE_ROOT_PATH,
    )

    if not controller.streamlines_cached_presentation_is_visible_in_kit():
        carb.log_error(
            "DTRS STREAMLINES | XFORM_PROBE | FAIL | "
            "Visible Streamlines presentation is unavailable."
        )
        return False

    await controller.stop_streamlines_cached_playback_in_kit()
    stage = omni.usd.get_context().get_stage()
    if stage is None:
        carb.log_error("DTRS STREAMLINES | XFORM_PROBE | FAIL | No open USD stage.")
        return False

    mesh = stage.GetPrimAtPath(MESH_CACHE_GEOMETRY_PATH)
    parent = stage.GetPrimAtPath(MESH_CACHE_ROOT_PATH)
    if (
        not mesh
        or not mesh.IsValid()
        or mesh.GetTypeName() != "Mesh"
        or not parent
        or not parent.IsValid()
    ):
        carb.log_error(
            "DTRS STREAMLINES | XFORM_PROBE | FAIL | "
            "Existing Streamlines Mesh prototype is unavailable."
        )
        return False

    timeline = omni.timeline.get_timeline_interface()
    time_code = Usd.TimeCode(
        float(timeline.get_current_time()) * stage.GetTimeCodesPerSecond()
    )
    points_attr = mesh.GetAttribute("points")
    points_before = points_attr.Get(time_code)
    if not points_before:
        carb.log_error(
            "DTRS STREAMLINES | XFORM_PROBE | FAIL | "
            "Visible Streamlines Mesh points are unavailable."
        )
        return False
    hash_before = await asyncio.to_thread(_points_hash, points_before)

    session_layer = stage.GetSessionLayer()
    root_path = Sdf.Path(MESH_CACHE_ROOT_PATH)
    order_path = root_path.AppendProperty("xformOpOrder")
    probe_property_name = f"xformOp:translate:{_PROBE_OP_SUFFIX}"
    probe_path = root_path.AppendProperty(probe_property_name)
    had_session_prim = bool(session_layer.GetPrimAtPath(root_path))
    previous_order_spec = session_layer.GetAttributeAtPath(order_path)
    had_session_order = bool(previous_order_spec)
    previous_order = previous_order_spec.default if previous_order_spec else None
    previous_edit_target = stage.GetEditTarget()
    translate_op = None
    try:
        stage.SetEditTarget(session_layer)
        xformable = UsdGeom.Xformable(parent)
        translate_op = xformable.AddTranslateOp(
            UsdGeom.XformOp.PrecisionDouble,
            _PROBE_OP_SUFFIX,
        )
        for translate_x in _PROBE_TRANSLATIONS_METRES:
            translate_op.Set(Gf.Vec3d(translate_x, 0.0, 0.0))
            await omni.kit.app.get_app().next_update_async()
            await asyncio.sleep(1.0)

        points_after = points_attr.Get(time_code)
        hash_after = await asyncio.to_thread(_points_hash, points_after)
        points_unchanged = hash_before == hash_after
        carb.log_warn(
            "DTRS STREAMLINES | XFORM_PROBE | RESULT\n"
            f"points_hash_before={hash_before}\n"
            f"points_hash_after={hash_after}\n"
            f"points_unchanged={points_unchanged}\n"
            "authored_translate_values=[0.00, 0.10, 0.00]"
        )
        return points_unchanged
    except asyncio.CancelledError:
        raise
    except Exception as error:  # noqa: BLE001 - diagnostic must report exact failure.
        carb.log_error(f"DTRS STREAMLINES | XFORM_PROBE | FAIL | {error}")
        return False
    finally:
        stage.SetEditTarget(session_layer)
        session_prim = session_layer.GetPrimAtPath(root_path)
        if session_prim:
            probe_spec = session_layer.GetAttributeAtPath(probe_path)
            if probe_spec:
                session_prim.RemoveProperty(probe_spec)
            order_spec = session_layer.GetAttributeAtPath(order_path)
            if had_session_order and order_spec:
                order_spec.default = previous_order
            elif order_spec:
                session_prim.RemoveProperty(order_spec)
            if not had_session_prim and not session_prim.properties:
                del session_layer.pseudoRoot.nameChildren[root_path.name]
        stage.SetEditTarget(previous_edit_target)
