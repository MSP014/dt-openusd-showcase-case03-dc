"""Own the disposable RTX time-sampled Mesh playback probe."""

from __future__ import annotations

PROBE_PRIM_PATH = "/DTRS_RendererDiagnosticMesh"


def _probe_shapes(stage):
    from pxr import Gf, Usd, UsdGeom

    cache = UsdGeom.BBoxCache(
        Usd.TimeCode.Default(),
        [UsdGeom.Tokens.default_, UsdGeom.Tokens.proxy, UsdGeom.Tokens.render],
    )
    bounds = cache.ComputeWorldBound(stage.GetPseudoRoot()).ComputeAlignedRange()
    if bounds.IsEmpty():
        center = Gf.Vec3d(0.0, 0.0, 0.0)
        maximum_y = 0.0
        span = 1.0
    else:
        center = bounds.GetMidpoint()
        size = bounds.GetSize()
        maximum_y = float(bounds.GetMax()[1])
        span = max(float(size[0]), float(size[1]), float(size[2]), 1.0)

    half = span * 0.12
    x = float(center[0])
    y = maximum_y + span * 0.08
    z = float(center[2])
    shape_a = [
        Gf.Vec3f(x - half, y, z - half),
        Gf.Vec3f(x + half, y, z - half),
        Gf.Vec3f(x + half, y, z + half),
        Gf.Vec3f(x - half, y, z + half),
    ]
    shape_b = [
        Gf.Vec3f(x - 2.0 * half, y, z - half),
        Gf.Vec3f(x + 2.0 * half, y, z - half),
        Gf.Vec3f(x + 0.25 * half, y + 3.0 * half, z + half),
        Gf.Vec3f(x - 0.25 * half, y + 0.5 * half, z + half),
    ]
    return shape_a, shape_b


def _extent(points):
    from pxr import Gf

    minimum = Gf.Vec3f(
        min(point[0] for point in points),
        min(point[1] for point in points),
        min(point[2] for point in points),
    )
    maximum = Gf.Vec3f(
        max(point[0] for point in points),
        max(point[1] for point in points),
        max(point[2] for point in points),
    )
    return [minimum, maximum]


def run_time_sampled_mesh_probe_in_kit() -> bool:
    """Print renderer state, then play one isolated Mesh when streaming is off."""

    import carb
    import carb.settings
    import omni.timeline
    import omni.usd
    from pxr import Gf, Usd, UsdGeom

    settings = carb.settings.get_settings()
    persistent_geometry = settings.get_as_bool("/persistent/UJITSO/geometry")
    active_geometry = settings.get_as_bool(
        "/rtx-transient/hydra/geometrystreaming/active"
    )
    fabric_delegate = settings.get_as_bool("/app/useFabricSceneDelegate")
    carb.log_warn(
        "DTRS RTX MESH PROBE | SETTINGS\n"
        f"/persistent/UJITSO/geometry={persistent_geometry}\n"
        "/rtx-transient/hydra/geometrystreaming/active="
        f"{active_geometry}\n"
        f"/app/useFabricSceneDelegate={fabric_delegate}"
    )
    if active_geometry:
        carb.log_error(
            "DTRS RTX MESH PROBE | STOP | Geometry Streaming is still active."
        )
        return False

    stage = omni.usd.get_context().get_stage()
    if stage is None:
        carb.log_error("DTRS RTX MESH PROBE | STOP | No open USD stage.")
        return False

    shape_a, shape_b = _probe_shapes(stage)
    time_codes_per_second = float(stage.GetTimeCodesPerSecond())
    with Usd.EditContext(stage, stage.GetSessionLayer()):
        stage.RemovePrim(PROBE_PRIM_PATH)
        mesh = UsdGeom.Mesh.Define(stage, PROBE_PRIM_PATH)
        mesh.CreateFaceVertexCountsAttr([3, 3])
        mesh.CreateFaceVertexIndicesAttr([0, 1, 2, 0, 2, 3])
        mesh.CreateSubdivisionSchemeAttr(UsdGeom.Tokens.none)
        mesh.CreateDoubleSidedAttr(True)
        mesh.CreateDisplayColorAttr([Gf.Vec3f(1.0, 0.05, 0.8)])
        points = mesh.CreatePointsAttr()
        extent = mesh.CreateExtentAttr()
        points.Set(shape_a, 0.0)
        extent.Set(_extent(shape_a), 0.0)
        points.Set(shape_b, time_codes_per_second)
        extent.Set(_extent(shape_b), time_codes_per_second)

    timeline = omni.timeline.get_timeline_interface()
    timeline.stop()
    timeline.set_start_time(0.0)
    timeline.set_end_time(1.0)
    timeline.set_looping(True)
    timeline.set_current_time(0.0)
    timeline.play()
    carb.log_warn(
        "DTRS RTX MESH PROBE | PLAYING | "
        f"prim={PROBE_PRIM_PATH}; sequence=A(0s)->B(1s)->A(loop)"
    )
    return True
