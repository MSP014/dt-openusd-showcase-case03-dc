"""Own the disposable static real-curve A/B renderer probe."""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass

PROBE_ROOT_PATH = "/DTRS_RealCurveABProbe"
PROBE_CURVE_A_PATH = f"{PROBE_ROOT_PATH}/Curve_A"
PROBE_CURVE_B_PATH = f"{PROBE_ROOT_PATH}/Curve_B"
SELECTED_CURVE_INDEX = 4_603
_POINTS_PER_CURVE = 20
_PROBE_TRANSLATE_METRES = (0.20, 0.10, 0.0)
_PROBE_WIDTH_METRES = 0.00408
_CURVE_A_POINTS = (
    (0.1354687363, 0.1627999842, -0.3784357607),
    (0.1353489161, 0.1625493616, -0.3775972426),
    (0.1352812499, 0.1622738838, -0.3765758872),
    (0.1353323162, 0.1620524228, -0.3753243387),
    (0.1353662461, 0.1619541496, -0.3738014698),
    (0.1352162510, 0.1619201303, -0.3719762266),
    (0.1350826919, 0.1618846059, -0.3697825372),
    (0.1350421309, 0.1618345082, -0.3675751090),
    (0.1350344867, 0.1617686003, -0.3653677404),
    (0.1349984258, 0.1617357433, -0.3631599247),
    (0.1348597705, 0.1618338227, -0.3609580994),
    (0.1346721798, 0.1621097028, -0.3587750793),
    (0.1350591481, 0.1622456908, -0.3566051424),
    (0.1353848577, 0.1625067145, -0.3544365764),
    (0.1354024112, 0.1626022160, -0.3522303402),
    (0.1353955120, 0.1626227200, -0.3500220776),
    (0.1354238987, 0.1626153886, -0.3478139043),
    (0.1354908943, 0.1623587906, -0.3456215262),
    (0.1360452622, 0.1621501595, -0.3434940875),
    (0.1369463354, 0.1621811986, -0.3414781392),
)
_CURVE_B_POINTS = (
    (0.1354687363, 0.1627999842, -0.3784357607),
    (0.1354131997, 0.1622678190, -0.3777329028),
    (0.1360305697, 0.1614335775, -0.3775171936),
    (0.1370485276, 0.1610461324, -0.3781742156),
    (0.1380548328, 0.1608307511, -0.3793015778),
    (0.1389791071, 0.1606616974, -0.3808739185),
    (0.1400782317, 0.1605552435, -0.3827744424),
    (0.1412398666, 0.1606432199, -0.3846505284),
    (0.1424469501, 0.1610771269, -0.3864481747),
    (0.1437143236, 0.1614968926, -0.3882072866),
    (0.1450099796, 0.1616678983, -0.3899874389),
    (0.1462661922, 0.1615793556, -0.3918015361),
    (0.1475143731, 0.1614041328, -0.3936148882),
    (0.1489847302, 0.1616526544, -0.3952437341),
    (0.1504456401, 0.1620787084, -0.3968440890),
    (0.1518769711, 0.1623500586, -0.3985037804),
    (0.1532646567, 0.1625401378, -0.4002111256),
    (0.1545349509, 0.1626406610, -0.4020147622),
    (0.1558085233, 0.1626979709, -0.4038179815),
    (0.1570829302, 0.1627398133, -0.4056210518),
)


@dataclass(frozen=True)
class RealCurveABEvidence:
    """Exact source-curve selection and displacement evidence."""

    curve_index: int
    real_point_count: int
    seed_displacement_m: float
    endpoint_displacement_m: float
    point_displacement_median_m: float
    point_displacement_p95_m: float
    point_displacement_max_m: float
    curve_a_hash: str
    curve_b_hash: str


@dataclass
class _ActiveProbe:
    stage: object
    bundle_had_visibility: bool
    bundle_previous_visibility: object


_active_probe: _ActiveProbe | None = None
_probe_stop_event: asyncio.Event | None = None


def _points_hash(points) -> str:
    import numpy as np

    values = np.ascontiguousarray(points, dtype=np.float32)
    return hashlib.sha256(values.tobytes()).hexdigest()


def _load_selected_real_curve(controller) -> tuple[object, object, float]:
    import numpy as np
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
    source_stage = Usd.Stage.Open(str(paths.geometry_path))
    source_curves = source_stage.GetPrimAtPath(CACHE_PLAYBACK_CURVES_PATH)
    points_attr = source_curves.GetAttribute("points")
    counts_attr = source_curves.GetAttribute("dtrs:sourceCurveVertexCounts")
    states = (metadata.states[0], metadata.states[1])
    points = []
    counts = []
    for state in states:
        time_code = Usd.TimeCode(state.time_code)
        values = np.asarray(points_attr.Get(time_code), dtype=np.float32)
        values = values.reshape(metadata.states[0].curve_count, _POINTS_PER_CURVE, 3)
        points.append(values[SELECTED_CURVE_INDEX].copy())
        counts.append(int(counts_attr.Get(time_code)[SELECTED_CURVE_INDEX]))
    if counts[0] != counts[1] or counts[0] <= 0:
        raise RuntimeError("Selected real curve no longer has stable source topology.")
    real_count = counts[0]
    return points[0][:real_count], points[1][:real_count], metadata.settings.width


def _evidence(points_a, points_b) -> RealCurveABEvidence:
    import numpy as np

    displacement = np.linalg.norm(points_b - points_a, axis=1)
    return RealCurveABEvidence(
        curve_index=SELECTED_CURVE_INDEX,
        real_point_count=len(points_a),
        seed_displacement_m=float(displacement[0]),
        endpoint_displacement_m=float(displacement[-1]),
        point_displacement_median_m=float(np.median(displacement)),
        point_displacement_p95_m=float(np.percentile(displacement, 95)),
        point_displacement_max_m=float(np.max(displacement)),
        curve_a_hash=_points_hash(points_a),
        curve_b_hash=_points_hash(points_b),
    )


def _author_curve(stage, path: str, points, width: float, color) -> None:
    from pxr import Gf, UsdGeom

    curves = UsdGeom.BasisCurves.Define(stage, path)
    curves.CreateTypeAttr(UsdGeom.Tokens.linear)
    curves.CreateWrapAttr(UsdGeom.Tokens.nonperiodic)
    curves.CreateCurveVertexCountsAttr([len(points)])
    curves.CreatePointsAttr(
        [
            Gf.Vec3f(float(point[0]), float(point[1]), float(point[2]))
            for point in points
        ]
    )
    curves.CreateWidthsAttr([width])
    curves.SetWidthsInterpolation(UsdGeom.Tokens.constant)
    display_color = curves.CreateDisplayColorAttr([Gf.Vec3f(*color)])
    UsdGeom.Primvar(display_color).SetInterpolation(UsdGeom.Tokens.constant)


def _ensure_static_probe_geometry(stage) -> tuple[object, object]:
    """Restore the immutable A/B curves without reopening the cache."""

    from pxr import Gf, UsdGeom

    curve_a = stage.GetPrimAtPath(PROBE_CURVE_A_PATH)
    curve_b = stage.GetPrimAtPath(PROBE_CURVE_B_PATH)
    if curve_a and curve_a.IsValid() and curve_b and curve_b.IsValid():
        return curve_a, curve_b

    stage.RemovePrim(PROBE_ROOT_PATH)
    root = UsdGeom.Xform.Define(stage, PROBE_ROOT_PATH)
    root.AddTranslateOp().Set(Gf.Vec3d(*_PROBE_TRANSLATE_METRES))
    _author_curve(
        stage,
        PROBE_CURVE_A_PATH,
        _CURVE_A_POINTS,
        _PROBE_WIDTH_METRES,
        (1.0, 0.15, 0.05),
    )
    _author_curve(
        stage,
        PROBE_CURVE_B_PATH,
        _CURVE_B_POINTS,
        _PROBE_WIDTH_METRES,
        (0.05, 0.75, 1.0),
    )
    return (
        stage.GetPrimAtPath(PROBE_CURVE_A_PATH),
        stage.GetPrimAtPath(PROBE_CURVE_B_PATH),
    )


def _set_visible(prim, visible: bool) -> None:
    from pxr import UsdGeom

    value = UsdGeom.Tokens.inherited if visible else UsdGeom.Tokens.invisible
    UsdGeom.Imageable(prim).GetVisibilityAttr().Set(value)


async def _show_until_stopped(
    stop_event: asyncio.Event,
    seconds: float,
    *states: tuple[object, bool],
) -> bool:
    import omni.kit.app

    for prim, visible in states:
        _set_visible(prim, visible)
    await omni.kit.app.get_app().next_update_async()
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=seconds)
    except TimeoutError:
        return False
    return True


def real_curve_ab_probe_active() -> bool:
    """Return whether the static comparison remains visible for inspection."""

    return _active_probe is not None


def request_stop_real_curve_ab_probe() -> bool:
    """Request a clean stop of the repeating visibility comparison."""

    if _probe_stop_event is None:
        return False
    _probe_stop_event.set()
    return True


def real_curve_ab_probe_ready_in_kit() -> bool:
    """Return whether the visible Streamlines bundle can host the probe."""

    import omni.usd

    from digital_twin_runtime_suite.app.streamlines.mesh_cache import (
        MESH_CACHE_GEOMETRY_PATH,
    )

    stage = omni.usd.get_context().get_stage()
    if stage is None:
        return False
    bundle = stage.GetPrimAtPath(MESH_CACHE_GEOMETRY_PATH)
    return bool(bundle and bundle.IsValid())


def cleanup_real_curve_ab_probe_in_kit() -> bool:
    """Remove the static curves and restore the prior bundle visibility."""

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


async def run_real_curve_ab_probe_in_kit(controller) -> str:
    """Repeat the static A/B visibility switch until explicitly stopped."""

    global _active_probe, _probe_stop_event

    import carb
    import omni.kit.app
    import omni.usd
    from pxr import Sdf

    from digital_twin_runtime_suite.app.streamlines.mesh_cache import (
        MESH_CACHE_GEOMETRY_PATH,
    )

    stage = omni.usd.get_context().get_stage()
    bundle = stage.GetPrimAtPath(MESH_CACHE_GEOMETRY_PATH) if stage else None
    if stage is None or not bundle or not bundle.IsValid():
        carb.log_error(
            "DTRS STREAMLINES | REAL_CURVE_STATIC_SWITCH | FAIL | "
            "Visible Streamlines presentation is unavailable."
        )
        return "FAILED"

    session = stage.GetSessionLayer()
    bundle_path = Sdf.Path(MESH_CACHE_GEOMETRY_PATH)
    visibility_path = bundle_path.AppendProperty("visibility")
    previous_visibility_spec = session.GetAttributeAtPath(visibility_path)
    previous_target = stage.GetEditTarget()
    try:
        stage.SetEditTarget(session)
        curve_a, curve_b = _ensure_static_probe_geometry(stage)
        points_a_attr = curve_a.GetAttribute("points")
        points_b_attr = curve_b.GetAttribute("points")
        if points_a_attr.GetTimeSamples() or points_b_attr.GetTimeSamples():
            raise RuntimeError("Probe curves are not static.")
        hash_a_before = _points_hash(points_a_attr.Get())
        hash_b_before = _points_hash(points_b_attr.Get())
        if _active_probe is None:
            _active_probe = _ActiveProbe(
                stage=stage,
                bundle_had_visibility=bool(previous_visibility_spec),
                bundle_previous_visibility=(
                    previous_visibility_spec.default
                    if previous_visibility_spec
                    else None
                ),
            )
        _set_visible(bundle, False)
        _probe_stop_event = asyncio.Event()
        carb.log_warn(
            "DTRS STREAMLINES | REAL_CURVE_STATIC_SWITCH | START\n"
            "status=Repeating A/B every 2 seconds; press the same button "
            "again to stop."
        )
        completed_states = 0
        while not _probe_stop_event.is_set():
            stopped = await _show_until_stopped(
                _probe_stop_event,
                2.0,
                (curve_a, True),
                (curve_b, False),
            )
            completed_states += 1
            if stopped:
                break
            stopped = await _show_until_stopped(
                _probe_stop_event,
                2.0,
                (curve_a, False),
                (curve_b, True),
            )
            completed_states += 1
            if stopped:
                break
        _set_visible(curve_a, True)
        _set_visible(curve_b, True)
        await omni.kit.app.get_app().next_update_async()
        hash_a_after = _points_hash(points_a_attr.Get())
        hash_b_after = _points_hash(points_b_attr.Get())
        carb.log_warn(
            "DTRS STREAMLINES | REAL_CURVE_STATIC_SWITCH | RESULT\n"
            f"Curve_A_points_unchanged={hash_a_before == hash_a_after}\n"
            f"Curve_B_points_unchanged={hash_b_before == hash_b_after}\n"
            "visibility_sequence=A,B repeated_until_stopped\n"
            f"completed_visibility_states={completed_states}"
        )
        return "ACTIVE"
    except asyncio.CancelledError:
        raise
    except Exception as error:  # noqa: BLE001 - report the isolated probe failure.
        carb.log_error(f"DTRS STREAMLINES | REAL_CURVE_STATIC_SWITCH | FAIL | {error}")
        return "FAILED"
    finally:
        _probe_stop_event = None
        stage.SetEditTarget(previous_target)
