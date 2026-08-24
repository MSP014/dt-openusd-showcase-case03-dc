# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""Smoke emitters, Cloud presentation, and smoke-tuning authoring."""

from __future__ import annotations

import math
from dataclasses import dataclass

from digital_twin_runtime_suite.app.config import (
    EmitterLayoutConfig,
    SmokeTuningConfig,
    validate_emitter_layout,
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


@dataclass(frozen=True)
class EmitterLayoutDerived:
    """Runtime geometry derived from normalized operator layout values."""

    positions: tuple[tuple[float, float, float], ...]
    radius: float
    minimum_radius: float
    maximum_radius: float
    depth_world_plane: float
    deep_world_plane: float
    front_world_plane: float


def derive_emitter_layout(
    layout: EmitterLayoutConfig,
    *,
    flow_world_bounds: tuple[tuple[float, float, float], tuple[float, float, float]],
    intake_world_bounds: tuple[tuple[float, float, float], tuple[float, float, float]],
    component_front_z: float | None,
    minimum_radius: float,
    front_inward_offset: float,
) -> EmitterLayoutDerived:
    """Derive a centered tracer grid that stays inside the active Flow bounds."""

    validate_emitter_layout(layout)
    if not math.isfinite(minimum_radius) or minimum_radius <= 0:
        raise ValueError("Emitter minimum radius must be finite and positive.")

    flow_min, flow_max = flow_world_bounds
    intake_min, intake_max = intake_world_bounds
    safe_min_radius = minimum_radius
    x_min = max(float(flow_min[0]), float(intake_min[0]))
    x_max = min(float(flow_max[0]), float(intake_max[0]))
    y_min = max(float(flow_min[1]), float(intake_min[1]))
    y_max = min(float(flow_max[1]), float(intake_max[1]))
    if x_max <= x_min or y_max <= y_min:
        raise ValueError(
            "The intake region is too small for one Flow density cell "
            f"(x span={x_max - x_min:.6g}, y span={y_max - y_min:.6g}, "
            f"densityCellSize={safe_min_radius:.6g})."
        )

    x_span = x_max - x_min
    y_span = y_max - y_min
    edge_limited_max = min(x_span, y_span) / 2
    column_limited_max = (
        x_span / (2 * layout.emitters_per_row) * 0.9
        if layout.emitters_per_row > 1
        else edge_limited_max
    )
    row_limited_max = (
        y_span / (2 * layout.rows) * 0.9 if layout.rows > 1 else edge_limited_max
    )
    maximum_radius = min(edge_limited_max, column_limited_max, row_limited_max)
    if maximum_radius < safe_min_radius:
        raise ValueError(
            "The selected emitter grid cannot fit reliable Flow sampling spheres."
        )

    radius = safe_min_radius + layout.size * (maximum_radius - safe_min_radius)
    raw_front = min(float(flow_max[2]), float(intake_max[2])) - front_inward_offset
    front_plane = min(raw_front, float(flow_max[2]) - radius)
    fallback_deep = float(flow_min[2]) + (front_plane - float(flow_min[2])) * 0.35
    component_clearance = max(radius, front_inward_offset)
    deep_plane = (
        max(float(flow_min[2]) + radius, component_front_z + component_clearance)
        if component_front_z is not None
        else fallback_deep
    )
    if deep_plane >= front_plane:
        raise ValueError("No safe intake-to-component depth corridor is available.")
    depth_world_plane = deep_plane + layout.depth * (front_plane - deep_plane)
    x_positions = _evenly_spaced_positions(
        x_min + radius,
        x_max - radius,
        layout.emitters_per_row,
    )
    y_positions = _evenly_spaced_positions(
        y_min + radius,
        y_max - radius,
        layout.rows,
    )
    positions = tuple(
        (x, y, depth_world_plane) for y in y_positions for x in x_positions
    )
    for position in positions:
        if any(
            position[axis] - radius < float(flow_min[axis])
            or position[axis] + radius > float(flow_max[axis])
            for axis in range(3)
        ):
            raise ValueError("Emitter layout extends outside the imported Flow bounds.")
    return EmitterLayoutDerived(
        positions=positions,
        radius=radius,
        minimum_radius=safe_min_radius,
        maximum_radius=maximum_radius,
        depth_world_plane=depth_world_plane,
        deep_world_plane=deep_plane,
        front_world_plane=front_plane,
    )


def _evenly_spaced_positions(start: float, end: float, count: int) -> tuple[float, ...]:
    if count == 1:
        return ((start + end) / 2,)
    return tuple(start + (end - start) * index / (count - 1) for index in range(count))


def inset_emitter_layout_panel_bounds(
    panel_world_bounds: tuple[tuple[float, float, float], tuple[float, float, float]],
    *,
    horizontal_margin: float,
    vertical_margin: float,
    minimum_inset: float,
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """Inset a front-panel envelope by independent per-side layout margins."""

    panel_min, panel_max = panel_world_bounds
    x_span = float(panel_max[0]) - float(panel_min[0])
    y_span = float(panel_max[1]) - float(panel_min[1])
    horizontal_inset = max(minimum_inset, x_span * horizontal_margin)
    vertical_inset = max(minimum_inset, y_span * vertical_margin)
    if x_span <= 2 * horizontal_inset or y_span <= 2 * vertical_inset:
        raise ValueError("Emitter layout margins leave no usable panel envelope.")
    return (
        (
            float(panel_min[0]) + horizontal_inset,
            float(panel_min[1]) + vertical_inset,
            float(panel_min[2]),
        ),
        (
            float(panel_max[0]) - horizontal_inset,
            float(panel_max[1]) - vertical_inset,
            float(panel_max[2]),
        ),
    )


def kit_cae_front_intake_emitter_layout(
    stage,
    layout: EmitterLayoutConfig,
    fan_bindings,
    flow_world_bounds,
    minimum_radius: float,
    front_inward_offset: float,
    Gf,
    Usd,
    UsdGeom,
) -> EmitterLayoutDerived:
    """Derive the layout from front-fan geometry and the nearest interior mesh."""

    validate_emitter_layout(layout)
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
    fan_ranges = []
    fan_paths = set()
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
        fan_ranges.append(fan_range)
        fan_paths.add(str(fan_prim.GetPath()))

    fan_min = tuple(
        min(float(item.GetMin()[axis]) for item in fan_ranges) for axis in range(3)
    )
    fan_max = tuple(
        max(float(item.GetMax()[axis]) for item in fan_ranges) for axis in range(3)
    )
    panel_min, panel_max = inset_emitter_layout_panel_bounds(
        (
            tuple(float(server_range.GetMin()[axis]) for axis in range(3)),
            tuple(float(server_range.GetMax()[axis]) for axis in range(3)),
        ),
        horizontal_margin=layout.horizontal_margin,
        vertical_margin=layout.vertical_margin,
        minimum_inset=front_inward_offset,
    )
    # The operator layout samples the front-panel envelope, not just the three
    # P120 centres. Independent margins keep maximum-size spheres inside it.
    intake_min = (
        panel_min[0],
        panel_min[1],
        min(fan_min[2], float(server_range.GetMin()[2])),
    )
    intake_max = (
        panel_max[0],
        panel_max[1],
        max(fan_max[2], float(server_range.GetMax()[2])),
    )
    fan_rear_z = fan_min[2]
    component_front_z = _nearest_intake_component_front_z(
        server_prim,
        bbox_cache,
        fan_paths,
        fan_rear_z,
        flow_world_bounds,
        Usd,
        UsdGeom,
    )
    derived = derive_emitter_layout(
        layout,
        flow_world_bounds=flow_world_bounds,
        intake_world_bounds=(intake_min, intake_max),
        component_front_z=component_front_z,
        minimum_radius=minimum_radius,
        front_inward_offset=front_inward_offset,
    )
    return EmitterLayoutDerived(
        positions=tuple(Gf.Vec3d(*position) for position in derived.positions),
        radius=derived.radius,
        minimum_radius=derived.minimum_radius,
        maximum_radius=derived.maximum_radius,
        depth_world_plane=derived.depth_world_plane,
        deep_world_plane=derived.deep_world_plane,
        front_world_plane=derived.front_world_plane,
    )


def _nearest_intake_component_front_z(
    server_prim,
    bbox_cache,
    fan_paths: set[str],
    fan_rear_z: float,
    flow_world_bounds,
    Usd,
    UsdGeom,
) -> float | None:
    """Find the first interior mesh behind the front fans, excluding enclosure shell."""

    flow_min, flow_max = flow_world_bounds
    server_depth = float(flow_max[2]) - float(flow_min[2])
    closest_front_z: float | None = None
    for prim in Usd.PrimRange(server_prim):
        if not prim.IsA(UsdGeom.Mesh) or str(prim.GetPath()) in fan_paths:
            continue
        name = prim.GetName().lower()
        if any(token in name for token in ("front", "fan", "grille", "panel", "shell")):
            continue
        bounds = bbox_cache.ComputeWorldBound(prim).ComputeAlignedRange()
        if bounds.IsEmpty():
            continue
        bound_min = float(bounds.GetMin()[2])
        bound_max = float(bounds.GetMax()[2])
        if bound_max >= fan_rear_z or bound_max - bound_min >= server_depth * 0.75:
            continue
        if closest_front_z is None or bound_max > closest_front_z:
            closest_front_z = bound_max
    return closest_front_z


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
    *,
    dataset_emitter_path: str | None = None,
    base_velocity_scale: float | None = None,
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
    ray_march_cloud.GetAttribute("volumeBaseColor").Set(smoke_tuning.base_color)
    advection.GetAttribute("combustionEnabled").Set(False)
    advection.GetAttribute("buoyancyPerSmoke").Set(0.0)
    advection.GetAttribute("buoyancyPerTemp").Set(0.0)
    vorticity.GetAttribute("smokeMask").Set(1.0)
    vorticity.GetAttribute("velocityMask").Set(0.0)
    vorticity.GetAttribute("velocityLinearMask").Set(0.0)
    vorticity.GetAttribute("constantMask").Set(0.0)
    author_kit_cae_smoke_tuning(
        stage,
        flow_environment_path,
        smoke_tuning,
        dataset_emitter_path=dataset_emitter_path,
        base_velocity_scale=base_velocity_scale,
    )


def read_kit_cae_base_velocity_scale(dataset_emitter) -> float:
    """Read the finite positive Kit-CAE auto scale before DTRS overrides it."""

    attribute = (
        dataset_emitter.GetAttribute("velocityScale") if dataset_emitter else None
    )
    if not attribute or not attribute.IsValid():
        raise RuntimeError("Kit-CAE DataSetEmitter is missing velocityScale.")
    value = attribute.Get()
    try:
        scale = float(value)
    except (TypeError, ValueError) as error:
        raise RuntimeError(
            f"Kit-CAE DataSetEmitter velocityScale is invalid: {value!r}."
        ) from error
    if not math.isfinite(scale) or scale <= 0.0:
        raise RuntimeError(
            "Kit-CAE DataSetEmitter velocityScale must be finite and positive, "
            f"got {scale!r}."
        )
    return scale


def apply_kit_cae_direct_attach_velocity_scale(
    dataset_emitter,
    *,
    base_velocity_scale: float,
    velocity_scale_multiplier: float,
) -> float:
    """Author the same locked transport scale used by the direct-Attach path."""

    if not math.isfinite(base_velocity_scale) or base_velocity_scale <= 0.0:
        raise RuntimeError("Kit-CAE base velocityScale must be finite and positive.")
    if not math.isfinite(velocity_scale_multiplier) or velocity_scale_multiplier <= 0.0:
        raise RuntimeError(
            "Kit-CAE velocityScale multiplier must be finite and positive."
        )
    attribute = (
        dataset_emitter.GetAttribute("velocityScale") if dataset_emitter else None
    )
    if not attribute or not attribute.IsValid():
        raise RuntimeError("Kit-CAE DataSetEmitter is missing velocityScale.")
    effective_velocity_scale = base_velocity_scale * velocity_scale_multiplier
    attribute.SetCustomDataByKey("omni:kit:locked", True)
    attribute.Set(effective_velocity_scale)
    actual = attribute.Get()
    if actual is None or abs(float(actual) - effective_velocity_scale) >= 1e-6:
        raise RuntimeError(
            "Kit-CAE did not retain the direct-Attach-equivalent velocityScale."
        )
    if not attribute.GetCustomDataByKey("omni:kit:locked"):
        raise RuntimeError("Kit-CAE velocityScale did not retain its lock.")
    return effective_velocity_scale


def author_kit_cae_smoke_tuning(
    stage,
    flow_environment_path: str,
    tuning: SmokeTuningConfig,
    Gf=None,
    *,
    dataset_emitter_path: str | None = None,
    base_velocity_scale: float | None = None,
) -> float | None:
    """Author and verify supported live Flow Cloud and transport attributes."""

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
    dataset_emitter = (
        stage.GetPrimAtPath(dataset_emitter_path) if dataset_emitter_path else None
    )
    required = (
        (cloud, "enableCloudMode"),
        (cloud, "densityMultiplier"),
        (cloud, "volumeBaseColor"),
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
    effective_velocity_scale = None
    if dataset_emitter_path is not None:
        if base_velocity_scale is None:
            raise RuntimeError("Kit-CAE base velocityScale is unavailable.")
        if not math.isfinite(base_velocity_scale) or base_velocity_scale <= 0.0:
            raise RuntimeError(
                "Kit-CAE base velocityScale must be finite and positive."
            )
        effective_velocity_scale = (
            base_velocity_scale * tuning.velocity_scale_multiplier
        )
        required += (
            (dataset_emitter, "velocityScale"),
            (simulate, "timeScale"),
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
    if effective_velocity_scale is not None:
        assignments += (("timeScale", tuning.time_scale),)
    for attribute_name, value in assignments:
        attributes[attribute_name].Set(value)
    attributes["attenuationMultiplier"].Set(
        Gf.Vec3f(
            tuning.shadow_density,
            tuning.shadow_density,
            tuning.shadow_density,
        )
    )
    attributes["volumeBaseColor"].Set(Gf.Vec3f(*tuning.base_color))

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
    base_color = attributes["volumeBaseColor"].Get()
    if base_color is None or any(
        abs(float(value) - expected) >= 1e-6
        for value, expected in zip(base_color, tuning.base_color)
    ):
        raise RuntimeError("Kit-CAE did not retain Cloud volumeBaseColor.")
    if effective_velocity_scale is not None:
        effective_velocity_scale = apply_kit_cae_direct_attach_velocity_scale(
            dataset_emitter,
            base_velocity_scale=base_velocity_scale,
            velocity_scale_multiplier=tuning.velocity_scale_multiplier,
        )
    return effective_velocity_scale


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


def verify_kit_cae_intake_tracer_emitters(
    stage,
    tracer_root_path: str,
    expected_count: int,
    UsdGeom,
) -> int:
    """Verify every rebuilt sphere source exists after Kit/Fabric settles."""

    tracer_root = stage.GetPrimAtPath(tracer_root_path)
    tracer_meshes = (
        [prim for prim in tracer_root.GetChildren() if prim.IsA(UsdGeom.Mesh)]
        if tracer_root and tracer_root.IsValid()
        else []
    )
    if len(tracer_meshes) != expected_count:
        raise RuntimeError(
            "Kit-CAE tracer rebuild produced "
            f"{len(tracer_meshes)} meshes, expected {expected_count}."
        )
    for index in range(1, expected_count + 1):
        tracer_path = f"{tracer_root_path}/intake_{index:02d}"
        tracer_mesh = stage.GetPrimAtPath(tracer_path)
        emitter = tracer_mesh.GetChild("EmitterSphere") if tracer_mesh else None
        if not tracer_mesh or not tracer_mesh.IsA(UsdGeom.Mesh) or not emitter:
            raise RuntimeError(
                f"Kit-CAE tracer source is unavailable after rebuild: {tracer_path}."
            )
        for attribute_name in ("smoke", "coupleRateSmoke", "coupleRateVelocity"):
            attribute = emitter.GetAttribute(attribute_name)
            if not attribute or not attribute.IsValid():
                raise RuntimeError(
                    "Kit-CAE tracer source is missing "
                    f"{attribute_name}: {tracer_path}."
                )
    return len(tracer_meshes)


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
