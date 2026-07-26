"""Smoke emitters, Cloud presentation, and smoke-tuning authoring."""

from __future__ import annotations

from digital_twin_runtime_suite.app.config import (
    SmokeTuningConfig,
    validate_smoke_tuning,
)

KIT_CAE_SERVER_ROOT = "/blackwell_rig"
KIT_CAE_FRONT_INTAKE_BINDING_IDS = frozenset(
    {"front_p120_01", "front_p120_02", "front_p120_03"}
)
KIT_CAE_INTAKE_TRACER_PASSIVE_CHANNEL_VALUES = (
    ("radius", 1.0),
    ("radiusIsWorldSpace", False),
    ("velocity", (0.0, 0.0, 0.0)),
    ("coupleRateVelocity", 0.0),
    ("fuel", 0.0),
    ("coupleRateFuel", 0.0),
    ("temperature", 0.0),
    ("coupleRateTemperature", 0.0),
    ("burn", 0.0),
    ("coupleRateBurn", 0.0),
)


def kit_cae_front_intake_tracer_positions(
    stage,
    tracer_config,
    fan_bindings,
    flow_world_bounds,
    Gf,
    Usd,
    UsdGeom,
) -> tuple[object, ...]:
    """Place a horizontal tracer line from real front P120 and server bounds."""

    server_prim = stage.GetPrimAtPath(KIT_CAE_SERVER_ROOT)
    if not server_prim or not server_prim.IsValid():
        raise RuntimeError(
            "DTRS server root is unavailable for intake tracer placement."
        )

    intake_bindings = tuple(
        binding
        for binding in fan_bindings
        if binding.binding_id in KIT_CAE_FRONT_INTAKE_BINDING_IDS
    )
    if len(intake_bindings) != len(KIT_CAE_FRONT_INTAKE_BINDING_IDS):
        raise RuntimeError(
            "DTRS front P120 bindings are incomplete for intake tracers."
        )

    bbox_cache = UsdGeom.BBoxCache(
        Usd.TimeCode.Default(),
        [UsdGeom.Tokens.default_, UsdGeom.Tokens.render, UsdGeom.Tokens.proxy],
    )
    server_range = bbox_cache.ComputeWorldBound(server_prim).ComputeAlignedRange()
    if server_range.IsEmpty():
        raise RuntimeError("DTRS server bounds are unavailable for intake tracers.")

    fan_centers = []
    for binding in intake_bindings:
        fan_prim = stage.GetPrimAtPath(binding.mesh_path)
        if not fan_prim or not fan_prim.IsValid():
            raise RuntimeError(
                f"DTRS front P120 mesh is unavailable: {binding.mesh_path}"
            )
        fan_range = bbox_cache.ComputeWorldBound(fan_prim).ComputeAlignedRange()
        if fan_range.IsEmpty():
            raise RuntimeError(
                f"DTRS front P120 bounds are unavailable: {binding.mesh_path}"
            )
        fan_centers.append(
            (
                (float(fan_range.GetMin()[0]) + float(fan_range.GetMax()[0])) / 2,
                (float(fan_range.GetMin()[1]) + float(fan_range.GetMax()[1])) / 2,
            )
        )

    fan_x_positions = sorted(center[0] for center in fan_centers)
    if len(fan_x_positions) != 3:
        raise RuntimeError(
            "DTRS intake tracer layout requires three front P120 centers."
        )
    center_y = sum(center[1] for center in fan_centers) / len(fan_centers)
    front_z = float(server_range.GetMax()[2]) + tracer_config.front_offset
    spacing = (fan_x_positions[-1] - fan_x_positions[0]) / 4
    start_x = fan_x_positions[0] - spacing
    positions = tuple(
        Gf.Vec3d(start_x + index * spacing, center_y, front_z)
        for index in range(tracer_config.count)
    )
    for position in positions:
        if any(
            float(position[axis]) - tracer_config.radius < flow_world_bounds[0][axis]
            or float(position[axis]) + tracer_config.radius > flow_world_bounds[1][axis]
            for axis in range(3)
        ):
            raise RuntimeError(
                "DTRS intake tracer layout extends outside the imported Flow bounds."
            )
    return positions


def configure_kit_cae_intake_tracer_emitter(
    stage,
    tracer_path: str,
    position,
    tracer_config,
    Gf,
    UsdGeom,
) -> None:
    """Configure one passive smoke source without fuel, heat, or self-velocity."""

    tracer_mesh = stage.GetPrimAtPath(tracer_path)
    if not tracer_mesh or not tracer_mesh.IsA(UsdGeom.Mesh):
        raise RuntimeError(f"Kit-CAE intake tracer mesh is unavailable: {tracer_path}")
    emitter = tracer_mesh.GetChild("EmitterSphere")
    if not emitter or not emitter.IsValid():
        raise RuntimeError(
            f"Kit-CAE intake tracer emitter is unavailable: {tracer_path}"
        )

    xformable = UsdGeom.Xformable(tracer_mesh)
    translate_op = next(
        (
            op
            for op in xformable.GetOrderedXformOps()
            if op.GetOpType() == UsdGeom.XformOp.TypeTranslate
        ),
        None,
    )
    scale_op = next(
        (
            op
            for op in xformable.GetOrderedXformOps()
            if op.GetOpType() == UsdGeom.XformOp.TypeScale
        ),
        None,
    )
    if translate_op is None or scale_op is None:
        raise RuntimeError("Kit-CAE intake tracer is missing transform operations.")
    translate_op.Set(position)
    scale_op.Set(
        Gf.Vec3f(
            tracer_config.radius,
            tracer_config.radius,
            tracer_config.radius,
        )
    )
    for attribute_name, value in KIT_CAE_INTAKE_TRACER_PASSIVE_CHANNEL_VALUES:
        attribute = emitter.GetAttribute(attribute_name)
        if not attribute or not attribute.IsValid():
            raise RuntimeError(
                f"Kit-CAE intake tracer is missing {attribute_name}: {tracer_path}"
            )
        attribute.Set(value)
    for attribute_name, value in (
        ("smoke", tracer_config.smoke_target),
        ("coupleRateSmoke", tracer_config.smoke_couple_rate),
    ):
        attribute = emitter.GetAttribute(attribute_name)
        if not attribute or not attribute.IsValid():
            raise RuntimeError(
                f"Kit-CAE intake tracer is missing {attribute_name}: {tracer_path}"
            )
        attribute.Set(value)


def configure_kit_cae_smoke_only_tracer_flow(
    stage,
    flow_environment_path: str,
    tracer_config,
    smoke_tuning: SmokeTuningConfig,
) -> None:
    """Disable combustion physics and give passive smoke a finite lifetime."""

    flow_environment = stage.GetPrimAtPath(flow_environment_path)
    simulate = flow_environment.GetChild("flowSimulate") if flow_environment else None
    advection = simulate.GetChild("advection") if simulate else None
    smoke_channel = advection.GetChild("smoke") if advection else None
    vorticity = simulate.GetChild("vorticity") if simulate else None
    offscreen = flow_environment.GetChild("flowOffscreen") if flow_environment else None
    render = flow_environment.GetChild("flowRender") if flow_environment else None
    debug_volume = offscreen.GetChild("debugVolume") if offscreen else None
    ray_march = render.GetChild("rayMarch") if render else None
    ray_march_cloud = ray_march.GetChild("cloud") if ray_march else None
    required_attributes = (
        (debug_volume, "enableSpeedAsTemperature"),
        (debug_volume, "enableVelocityAsDensity"),
        (ray_march, "enableRawMode"),
        (ray_march_cloud, "enableCloudMode"),
        (ray_march_cloud, "densityMultiplier"),
        (ray_march_cloud, "volumeBaseColor"),
        (advection, "combustionEnabled"),
        (advection, "buoyancyPerSmoke"),
        (advection, "buoyancyPerTemp"),
        (smoke_channel, "damping"),
        (smoke_channel, "fade"),
        (smoke_channel, "secondOrderBlendFactor"),
        (vorticity, "enabled"),
        (vorticity, "forceScale"),
        (vorticity, "smokeMask"),
        (vorticity, "velocityMask"),
        (vorticity, "velocityLinearMask"),
        (vorticity, "constantMask"),
    )
    for prim, attribute_name in required_attributes:
        attribute = prim.GetAttribute(attribute_name) if prim else None
        if not attribute or not attribute.IsValid():
            prim_path = prim.GetPath() if prim else flow_environment_path
            raise RuntimeError(
                "Kit-CAE smoke-only tracer setup is missing "
                f"{prim_path}.{attribute_name}."
            )

    debug_volume.GetAttribute("enableSpeedAsTemperature").Set(False)
    debug_volume.GetAttribute("enableVelocityAsDensity").Set(False)
    ray_march.GetAttribute("enableRawMode").Set(False)
    ray_march_cloud.GetAttribute("enableCloudMode").Set(True)
    ray_march_cloud.GetAttribute("volumeBaseColor").Set(
        tracer_config.smoke_cloud_base_color
    )
    advection.GetAttribute("combustionEnabled").Set(False)
    advection.GetAttribute("buoyancyPerSmoke").Set(0.0)
    advection.GetAttribute("buoyancyPerTemp").Set(0.0)
    vorticity.GetAttribute("smokeMask").Set(1.0)
    vorticity.GetAttribute("velocityMask").Set(0.0)
    vorticity.GetAttribute("velocityLinearMask").Set(0.0)
    vorticity.GetAttribute("constantMask").Set(0.0)
    author_kit_cae_smoke_tuning(stage, flow_environment_path, smoke_tuning)


def author_kit_cae_smoke_tuning(
    stage,
    flow_environment_path: str,
    tuning: SmokeTuningConfig,
    Gf=None,
) -> None:
    """Author and verify the supported live Flow Cloud attributes."""

    validate_smoke_tuning(tuning)
    if Gf is None:
        from pxr import Gf as pxr_gf

        Gf = pxr_gf

    flow_environment = stage.GetPrimAtPath(flow_environment_path)
    simulate = flow_environment.GetChild("flowSimulate") if flow_environment else None
    render = flow_environment.GetChild("flowRender") if flow_environment else None
    advection = simulate.GetChild("advection") if simulate else None
    smoke_channel = advection.GetChild("smoke") if advection else None
    vorticity = simulate.GetChild("vorticity") if simulate else None
    ray_march = render.GetChild("rayMarch") if render else None
    cloud = ray_march.GetChild("cloud") if ray_march else None
    required = (
        (cloud, "enableCloudMode"),
        (cloud, "densityMultiplier"),
        (cloud, "volumeColorMultiplier"),
        (cloud, "ambientMultiplier"),
        (cloud, "attenuationMultiplier"),
        (smoke_channel, "damping"),
        (smoke_channel, "fade"),
        (smoke_channel, "secondOrderBlendFactor"),
        (vorticity, "enabled"),
        (vorticity, "forceScale"),
        (ray_march, "stepSizeScale"),
    )
    attributes = {}
    for prim, attribute_name in required:
        attribute = prim.GetAttribute(attribute_name) if prim else None
        if not attribute or not attribute.IsValid():
            prim_path = prim.GetPath() if prim else flow_environment_path
            raise RuntimeError(
                f"Kit-CAE Cloud smoke setting is missing {prim_path}.{attribute_name}."
            )
        attributes[attribute_name] = attribute
    if not bool(attributes["enableCloudMode"].Get()):
        raise RuntimeError("Kit-CAE Flow Cloud mode is not enabled.")

    assignments = (
        ("densityMultiplier", tuning.density),
        ("volumeColorMultiplier", tuning.brightness),
        ("ambientMultiplier", tuning.ambient),
        ("damping", tuning.damping),
        ("fade", tuning.fade),
        ("secondOrderBlendFactor", tuning.sharpness),
        ("enabled", tuning.vorticity > 0.0),
        ("forceScale", tuning.vorticity),
        ("stepSizeScale", tuning.raymarch_quality),
    )
    for attribute_name, value in assignments:
        attributes[attribute_name].Set(value)
    attributes["attenuationMultiplier"].Set(
        Gf.Vec3f(
            tuning.shadow_density,
            tuning.shadow_density,
            tuning.shadow_density,
        )
    )

    for attribute_name, expected in assignments:
        actual = attributes[attribute_name].Get()
        if isinstance(expected, bool):
            matches = bool(actual) is expected
        else:
            matches = actual is not None and abs(float(actual) - expected) < 1e-6
        if not matches:
            raise RuntimeError(f"Kit-CAE did not retain {attribute_name}={expected!r}.")
    attenuation = attributes["attenuationMultiplier"].Get()
    if attenuation is None or any(
        abs(float(value) - tuning.shadow_density) >= 1e-6 for value in attenuation
    ):
        raise RuntimeError("Kit-CAE did not retain Cloud attenuationMultiplier.")


def set_kit_cae_spatial_sanity_wireframes_visibility(
    stage,
    visible: bool,
    UsdGeom,
) -> bool:
    """Set visibility for optional Flow spatial-sanity wireframes."""

    overlay_prims = (
        stage.GetPrimAtPath("/DTRS_KitCAE/SpatialSanity"),
        stage.GetPrimAtPath("/DTRS_KitCAE/BoundingBox"),
    )
    valid_prims = [prim for prim in overlay_prims if prim and prim.IsValid()]
    if not valid_prims:
        return False
    for prim in valid_prims:
        UsdGeom.Imageable(prim).CreateVisibilityAttr().Set(
            UsdGeom.Tokens.inherited if visible else UsdGeom.Tokens.invisible
        )
    return True


def hide_kit_cae_intake_tracer_meshes(
    stage,
    tracer_root_path: str,
    UsdGeom,
    *,
    expected_count: int | None = None,
) -> None:
    """Hide tracer meshes while keeping their FlowEmitterSphere children active."""

    tracer_root = stage.GetPrimAtPath(tracer_root_path)
    tracer_meshes = (
        [prim for prim in tracer_root.GetChildren() if prim.IsA(UsdGeom.Mesh)]
        if tracer_root and tracer_root.IsValid()
        else []
    )
    if not tracer_meshes:
        raise RuntimeError("Kit-CAE intake tracer meshes are unavailable.")
    if expected_count is not None and len(tracer_meshes) != expected_count:
        raise RuntimeError(
            "Kit-CAE intake tracer mesh count does not match the DTRS configuration."
        )
    for tracer_mesh in tracer_meshes:
        UsdGeom.Imageable(tracer_mesh).CreateVisibilityAttr().Set(
            UsdGeom.Tokens.invisible
        )


def clear_kit_cae_server_visibility_session_opinion(stage, UsdGeom) -> bool:
    """Remove a leftover diagnostic visibility override from the server root."""

    server_prim = stage.GetPrimAtPath(KIT_CAE_SERVER_ROOT)
    if not server_prim or not server_prim.IsValid():
        return False
    UsdGeom.Imageable(server_prim).GetVisibilityAttr().Clear()
    return True


async def pulse_kit_cae_flow_clear(app, flow_environment_path: str) -> None:
    """Clear prior density before the one-phase native fuel control run."""

    import omni.usd

    stage = omni.usd.get_context().get_stage()
    flow_environment = stage.GetPrimAtPath(flow_environment_path) if stage else None
    simulate = flow_environment.GetChild("flowSimulate") if flow_environment else None
    force_clear = simulate.GetAttribute("forceClear") if simulate else None
    if not force_clear or not force_clear.IsValid():
        raise RuntimeError(
            "Kit-CAE Flow native fuel probe is missing flowSimulate.forceClear."
        )
    force_clear.Set(True)
    await app.next_update_async()
    force_clear.Set(False)
    await app.next_update_async()
