"""Deep Kit-CAE and Flow diagnostics kept out of lifecycle orchestration."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from digital_twin_runtime_suite.app.flow import smoke as flow_smoke

if TYPE_CHECKING:
    from digital_twin_runtime_suite.app.flow.runtime import SimulationCacheResult


class FlowDiagnosticsMixin:
    """Own optional diagnostics and spatial/field validation helpers."""

    @staticmethod
    def _kit_cae_vectors_match(expected, actual, tolerance: float = 1e-6) -> bool:
        """Compare three-component grid values without exposing diagnostic internals."""

        if expected is None or actual is None:
            return False
        try:
            return len(expected) == len(actual) == 3 and all(
                abs(float(expected[index]) - float(actual[index])) <= tolerance
                for index in range(3)
            )
        except (TypeError, ValueError):
            return False

    def set_kit_cae_debug_overlays_visible_in_kit(
        self,
        visible: bool,
    ) -> "SimulationCacheResult":
        """Show or hide the optional Flow spatial-sanity wireframes."""

        import omni.usd
        from pxr import UsdGeom

        from digital_twin_runtime_suite.app.flow.runtime import SimulationCacheResult

        stage = omni.usd.get_context().get_stage()
        if not stage:
            return SimulationCacheResult(
                False, "Debug overlays skipped: no open stage."
            )
        if not flow_smoke.set_kit_cae_spatial_sanity_wireframes_visibility(
            stage,
            visible,
            UsdGeom,
        ):
            return SimulationCacheResult(
                False,
                "Attach the airflow cache before changing debug overlays.",
            )
        return SimulationCacheResult(
            True,
            f"Flow debug overlays {'shown' if visible else 'hidden'}.",
        )

    @staticmethod
    def _log_kit_cae_render_probe(
        stage,
        flow_environment_path: str,
        smoke_probe_phase: str,
        carb,
    ) -> None:
        """Report the active Flow render mode after the control run settles."""

        flow_environment = stage.GetPrimAtPath(flow_environment_path)
        simulate = (
            flow_environment.GetChild("flowSimulate") if flow_environment else None
        )
        offscreen = (
            flow_environment.GetChild("flowOffscreen") if flow_environment else None
        )
        render = flow_environment.GetChild("flowRender") if flow_environment else None
        debug_volume = offscreen.GetChild("debugVolume") if offscreen else None
        ray_march = render.GetChild("rayMarch") if render else None

        def attr_value(prim, name: str):
            attribute = prim.GetAttribute(name) if prim else None
            return attribute.Get() if attribute and attribute.IsValid() else None

        diagnostics = {
            "smoke_probe_phase": smoke_probe_phase,
            "debug_volume_present": bool(debug_volume and debug_volume.IsValid()),
            "enableVelocityAsDensity": attr_value(
                debug_volume,
                "enableVelocityAsDensity",
            ),
            "debug_velocityScale": attr_value(debug_volume, "velocityScale"),
            "rayMarch_enableRawMode": attr_value(ray_march, "enableRawMode"),
            "rayMarch_enableBlockWireframe": attr_value(
                ray_march,
                "enableBlockWireframe",
            ),
            "rayMarch_attenuation": attr_value(ray_march, "attenuation"),
            "flow_offscreen_layer": attr_value(offscreen, "layer"),
            "flow_render_layer": attr_value(render, "layer"),
            "flow_simulate_layer": attr_value(simulate, "layer"),
        }
        details = ", ".join(f"{key}={value}" for key, value in diagnostics.items())
        carb.log_warn(f"DTRS Kit-CAE render probe: {details}")

    @staticmethod
    def _log_kit_cae_origin_trace(
        metadata: dict[str, object],
        origin_after_import: dict[str, object],
        origin_after_dtrs_composition: dict[str, object],
        dav_origin_trace: dict[str, object],
        carb,
    ) -> None:
        """Log the origin handoff from VTI bytes through DAV's Flow input."""

        diagnostics = {
            "raw_vti_header_origin": metadata["vti_header_origin"],
            "vtkXMLImageDataReader_output_origin": metadata["vtk_reader_origin"],
            "ImageDataAPI_origin_after_import": origin_after_import["origin"],
            "ImageDataAPI_origin_after_dtrs_composition": (
                origin_after_dtrs_composition["origin"]
            ),
            "composed_usd_origin": origin_after_dtrs_composition["origin"],
            "ImageDataAPI_origin_property_stack": (
                origin_after_dtrs_composition["property_stack"]
            ),
            "dav_dataset_origin_before_FlowNanoVDBEmitter": (
                dav_origin_trace["origin"]
            ),
            "dav_dataset_bounds_before_FlowNanoVDBEmitter": (
                dav_origin_trace["bounds"]
            ),
            "dav_velocity_voxel_size_before_FlowNanoVDBEmitter": (
                dav_origin_trace["voxel_size"]
            ),
        }
        details = ", ".join(f"{key}={value}" for key, value in diagnostics.items())
        carb.log_warn(f"DTRS Kit-CAE origin trace: {details}")

    @staticmethod
    def _log_kit_cae_flow_full_diagnostics(
        stage,
        velocity_path: Path,
        metadata: dict[str, object],
        imported_grid: dict[str, object],
        dataset_path: str,
        flow_environment_path: str,
        tracer_root_path: str,
        boundary_emitter_path: str,
        dataset_emitter_path: str,
        bbox_path: str,
        field_path: str,
        velocity_selector,
        timeline,
        timeline_time_before: float,
        timeline_time_after: float,
        operator_readiness: dict[str, object],
        smoke_probe_phase: str,
        Usd,
        UsdGeom,
        carb,
    ) -> None:
        """Report one post-settle checkpoint for the VTI -> Kit-CAE -> Flow route."""

        dimensions = metadata["dimensions"]
        vti_header_origin = metadata["vti_header_origin"]
        vti_header_spacing = metadata["spacing"]
        vti_header_max = tuple(
            vti_header_origin[index]
            + (dimensions[index] - 1) * vti_header_spacing[index]
            for index in range(3)
        )
        bbox_cache = UsdGeom.BBoxCache(
            Usd.TimeCode.Default(),
            [UsdGeom.Tokens.default_, UsdGeom.Tokens.render, UsdGeom.Tokens.proxy],
        )

        def world_bounds(
            path: str,
        ) -> tuple[tuple[float, float, float], tuple[float, float, float]] | None:
            prim = stage.GetPrimAtPath(path)
            if not prim or not prim.IsValid():
                return None
            bounds = bbox_cache.ComputeWorldBound(prim).ComputeAlignedRange()
            if bounds.IsEmpty():
                return None
            return tuple(bounds.GetMin()), tuple(bounds.GetMax())

        def attr_value(prim, name: str):
            if not prim or not prim.IsValid():
                return None
            attribute = prim.GetAttribute(name)
            return attribute.Get() if attribute and attribute.IsValid() else None

        def relationship_targets(prim, name: str) -> list[str]:
            if not prim or not prim.IsValid():
                return []
            relationship = prim.GetRelationship(name)
            if not relationship or not relationship.IsValid():
                return []
            return [str(path) for path in relationship.GetTargets()]

        def array_count(prim, name: str) -> int | None:
            value = attr_value(prim, name)
            return len(value) if value is not None else None

        dataset_prim = stage.GetPrimAtPath(dataset_path)
        field_prim = stage.GetPrimAtPath(field_path)
        flow_environment = stage.GetPrimAtPath(flow_environment_path)
        flow_simulate = (
            flow_environment.GetChild("flowSimulate") if flow_environment else None
        )
        flow_offscreen = (
            flow_environment.GetChild("flowOffscreen") if flow_environment else None
        )
        flow_render = (
            flow_environment.GetChild("flowRender") if flow_environment else None
        )
        flow_colormap = flow_offscreen.GetChild("colormap") if flow_offscreen else None
        dataset_emitter = stage.GetPrimAtPath(dataset_emitter_path)
        tracer_root = stage.GetPrimAtPath(tracer_root_path)
        tracer_meshes = (
            [prim for prim in tracer_root.GetChildren() if prim.IsA(UsdGeom.Mesh)]
            if tracer_root and tracer_root.IsValid()
            else []
        )
        smoke_injector = tracer_meshes[0] if tracer_meshes else None
        smoke_emitter = (
            smoke_injector.GetChild("EmitterSphere") if smoke_injector else None
        )
        smoke_position = None
        smoke_local_scale = None
        if smoke_injector and smoke_injector.IsValid():
            injector_xform = UsdGeom.Xformable(smoke_injector)
            smoke_position = tuple(
                injector_xform.ComputeLocalToWorldTransform(
                    Usd.TimeCode.Default()
                ).ExtractTranslation()
            )
            scale_op = next(
                (
                    op
                    for op in injector_xform.GetOrderedXformOps()
                    if op.GetOpType() == UsdGeom.XformOp.TypeScale
                ),
                None,
            )
            smoke_local_scale = (
                tuple(scale_op.Get())
                if scale_op and scale_op.Get() is not None
                else None
            )

        bbox_world_bounds = world_bounds(bbox_path)
        colormap_rgba_points = attr_value(flow_colormap, "rgbaPoints")
        colormap_alpha_values = (
            tuple(float(point[3]) for point in colormap_rgba_points)
            if colormap_rgba_points is not None
            else None
        )
        smoke_injector_mesh_visible = (
            UsdGeom.Imageable(smoke_injector).ComputeVisibility()
            != UsdGeom.Tokens.invisible
            if smoke_injector and smoke_injector.IsValid()
            else None
        )
        server_prim = stage.GetPrimAtPath(flow_smoke.KIT_CAE_SERVER_ROOT)
        server_visible = (
            UsdGeom.Imageable(server_prim).ComputeVisibility()
            != UsdGeom.Tokens.invisible
            if server_prim and server_prim.IsValid()
            else None
        )
        smoke_radius = attr_value(smoke_emitter, "radius")
        radius_is_world_space = attr_value(smoke_emitter, "radiusIsWorldSpace")
        world_radius = None
        if smoke_radius is not None:
            world_radius = (
                float(smoke_radius)
                if radius_is_world_space
                else float(smoke_radius) * max(smoke_local_scale or (1.0,))
            )
        injector_inside_bounds = bool(
            smoke_position is not None
            and world_radius is not None
            and bbox_world_bounds is not None
            and all(
                bbox_world_bounds[0][index] <= smoke_position[index] - world_radius
                and smoke_position[index] + world_radius <= bbox_world_bounds[1][index]
                for index in range(3)
            )
        )

        boundary_root = stage.GetPrimAtPath(boundary_emitter_path)
        boundary_emitters = (
            [
                prim
                for prim in Usd.PrimRange(boundary_root)
                if prim.GetTypeName() == "FlowEmitterBox"
            ]
            if boundary_root and boundary_root.IsValid()
            else []
        )
        target_paths = [
            str(path) for path in velocity_selector.GetTargetRel().GetTargets()
        ]
        advection = flow_simulate.GetChild("advection") if flow_simulate else None
        ray_march = flow_render.GetChild("rayMarch") if flow_render else None
        data_set_bbox_match = bbox_world_bounds is not None and all(
            abs(
                bbox_world_bounds[bound][axis]
                - imported_grid["world_bounds"][bound][axis]
            )
            < 1e-5
            for bound in range(2)
            for axis in range(3)
        )
        diagnostics = [
            ("active_route", "VTI_KIT_CAE_FLOW"),
            ("vti_asset_path", velocity_path),
            ("dataset_path", dataset_path),
            ("dataset_prim_type", dataset_prim.GetTypeName()),
            ("velocity_field_path", field_path),
            ("velocity_field_association", attr_value(field_prim, "fieldAssociation")),
            ("velocity_field_components", metadata["components"]),
            ("velocity_field_dtype", metadata["data_type"]),
            ("vti_header_origin", vti_header_origin),
            ("vti_header_spacing", vti_header_spacing),
            ("usd_imagedata_origin", imported_grid["origin"]),
            ("vti_world_bounds", (vti_header_origin, vti_header_max)),
            ("dataset_world_bounds", imported_grid["world_bounds"]),
            ("kit_cae_imported_spacing", imported_grid["spacing"]),
            ("vti_dimensions", dimensions),
            ("server_bounds", world_bounds("/blackwell_rig")),
            ("bbox_world_bounds", bbox_world_bounds),
            ("flow_world_bounds", bbox_world_bounds),
            ("dataset_bbox_bounds_match", data_set_bbox_match),
            ("flow_environment_path", flow_environment_path),
            ("flow_simulate_path", flow_simulate.GetPath() if flow_simulate else None),
            ("flow_simulate_layer", attr_value(flow_simulate, "layer")),
            ("densityCellSize", attr_value(flow_simulate, "densityCellSize")),
            ("forceDisableEmitters", attr_value(flow_simulate, "forceDisableEmitters")),
            (
                "forceDisableCoreSimulation",
                attr_value(flow_simulate, "forceDisableCoreSimulation"),
            ),
            ("forceClear", attr_value(flow_simulate, "forceClear")),
            ("forceSimulate", attr_value(flow_simulate, "forceSimulate")),
            ("flow_offscreen_layer", attr_value(flow_offscreen, "layer")),
            ("flow_render_layer", attr_value(flow_render, "layer")),
            ("buoyancyPerTemp", attr_value(advection, "buoyancyPerTemp")),
            ("burnPerTemp", attr_value(advection, "burnPerTemp")),
            ("fuelPerBurn", attr_value(advection, "fuelPerBurn")),
            ("ignitionTemp", attr_value(advection, "ignitionTemp")),
            ("rayMarch_attenuation", attr_value(ray_march, "attenuation")),
            ("rayMarch_colormap_alphas", colormap_alpha_values),
            ("dataset_emitter_path", dataset_emitter_path),
            (
                "dataset_emitter_prim_type",
                dataset_emitter.GetTypeName() if dataset_emitter else None,
            ),
            ("dataset_emitter_layer", attr_value(dataset_emitter, "layer")),
            (
                "operator_enabled",
                attr_value(dataset_emitter, "cae:viz:operator:enabled"),
            ),
            (
                "source_targets",
                relationship_targets(
                    dataset_emitter,
                    "cae:viz:dataset_selection:source:target",
                ),
            ),
            ("velocity_targets", target_paths),
            (
                "rescaleMode",
                attr_value(
                    dataset_emitter,
                    "cae:viz:configure_flow_environment:source:rescaleMode",
                ),
            ),
            (
                "densityCellSizeIncludes",
                relationship_targets(
                    dataset_emitter,
                    "cae:viz:configure_flow_environment:source:densityCellSizeIncludes",
                ),
            ),
            (
                "nanoVdbVelocities_present",
                attr_value(dataset_emitter, "nanoVdbVelocities") is not None,
            ),
            (
                "nanoVdbVelocities_type",
                (
                    dataset_emitter.GetAttribute("nanoVdbVelocities").GetTypeName()
                    if dataset_emitter
                    and dataset_emitter.GetAttribute("nanoVdbVelocities")
                    else None
                ),
            ),
            (
                "nanoVdbVelocities_uint_count",
                array_count(dataset_emitter, "nanoVdbVelocities"),
            ),
            ("velocityScale", attr_value(dataset_emitter, "velocityScale")),
            (
                "coupleRateVelocity",
                attr_value(dataset_emitter, "coupleRateVelocity"),
            ),
            ("operator_ready", operator_readiness["ready"]),
            ("operator_wait_cycles", operator_readiness["cycles"]),
            ("operator_wait_seconds", f"{operator_readiness['seconds']:.3f}"),
            ("operator_wait_timed_out", operator_readiness["timed_out"]),
            ("allocationScale", attr_value(dataset_emitter, "allocationScale")),
            ("applyPostPressure", attr_value(dataset_emitter, "applyPostPressure")),
            ("tracer_root_path", tracer_root_path),
            ("tracer_mesh_count", len(tracer_meshes)),
            (
                "smoke_emitter_path",
                smoke_emitter.GetPath() if smoke_emitter else None,
            ),
            (
                "smoke_emitter_prim_type",
                smoke_emitter.GetTypeName() if smoke_emitter else None,
            ),
            ("smoke_probe_phase", smoke_probe_phase),
            ("server_visible", server_visible),
            ("smoke_injector_mesh_visible", smoke_injector_mesh_visible),
            ("smoke_emitter_enabled", attr_value(smoke_emitter, "enabled")),
            (
                "smoke_emitter_allocationScale",
                attr_value(smoke_emitter, "allocationScale"),
            ),
            ("smoke_injector_local_scale", smoke_local_scale),
            ("smoke_injector_world_scale", smoke_local_scale),
            ("emitter_position", smoke_position),
            ("emitter_layer", attr_value(smoke_emitter, "layer")),
            ("radius", smoke_radius),
            ("radiusIsWorldSpace", radius_is_world_space),
            ("smoke", attr_value(smoke_emitter, "smoke")),
            ("coupleRateSmoke", attr_value(smoke_emitter, "coupleRateSmoke")),
            ("burn", attr_value(smoke_emitter, "burn")),
            ("coupleRateBurn", attr_value(smoke_emitter, "coupleRateBurn")),
            ("fuel", attr_value(smoke_emitter, "fuel")),
            ("coupleRateFuel", attr_value(smoke_emitter, "coupleRateFuel")),
            ("temperature", attr_value(smoke_emitter, "temperature")),
            (
                "coupleRateTemperature",
                attr_value(smoke_emitter, "coupleRateTemperature"),
            ),
            (
                "smoke_emitter_coupleRateVelocity",
                attr_value(smoke_emitter, "coupleRateVelocity"),
            ),
            ("injector_inside_flow_bounds", injector_inside_bounds),
            ("boundary_emitter_path", boundary_emitter_path),
            ("boundary_emitter_count", len(boundary_emitters)),
            (
                "boundary_layers",
                [attr_value(prim, "layer") for prim in boundary_emitters],
            ),
            (
                "all_boundary_emitters_valid",
                len(boundary_emitters) == 6
                and all(prim.IsValid() for prim in boundary_emitters),
            ),
            ("timeline_is_playing", timeline.is_playing()),
            ("timeline_time_before", timeline_time_before),
            ("timeline_time_after", timeline_time_after),
            ("timeline_advancing", timeline_time_after > timeline_time_before),
            ("stage_timeCodesPerSecond", stage.GetTimeCodesPerSecond()),
        ]
        details = ", ".join(f"{key}={value}" for key, value in diagnostics)
        carb.log_warn(f"DTRS Kit-CAE Flow full diagnostics: {details}")

    @staticmethod
    def _validate_kit_cae_velocity_field(
        dataset_prim,
        field_prim,
        metadata: dict[str, object],
        cae,
        cae_vtk,
    ) -> dict[str, object]:
        """Verify that Kit-CAE represented the Houdini VTI as a point vector field."""

        if not dataset_prim or not dataset_prim.IsA(cae.DataSet):
            raise RuntimeError("Kit-CAE did not create a CaeDataSet from the VTI.")
        if not dataset_prim.HasAPI(cae.DenseVolumeAPI):
            raise RuntimeError("Kit-CAE VTI dataset is missing DenseVolumeAPI.")
        if not field_prim or field_prim.GetTypeName() != "CaeVtkFieldArray":
            raise RuntimeError("Kit-CAE did not create the expected CaeVtkFieldArray.")
        association = str(field_prim.GetAttribute("fieldAssociation").Get())
        if association != str(cae.Tokens.vertex):
            raise RuntimeError(
                "Kit-CAE velocity field is not associated with VTI PointData."
            )

        dense_volume = cae.DenseVolumeAPI(dataset_prim)
        min_extent = dense_volume.GetMinExtentAttr().Get()
        max_extent = dense_volume.GetMaxExtentAttr().Get()
        imported_dimensions = tuple(
            int(max_extent[index] - min_extent[index] + 1) for index in range(3)
        )
        if imported_dimensions != metadata["dimensions"]:
            raise RuntimeError(
                "Kit-CAE VTI dimensions do not match the source VTI PointData grid."
            )
        imported_spacing = tuple(
            float(value) for value in dense_volume.GetSpacingAttr().Get()
        )
        expected_spacing = metadata["spacing"]
        if any(
            abs(imported_spacing[index] - expected_spacing[index]) > 1e-6
            for index in range(3)
        ):
            raise RuntimeError(
                "Kit-CAE VTI spacing does not match the source VTI grid."
            )

        image_data = cae_vtk.ImageDataAPI(dataset_prim)
        imported_origin = tuple(
            float(value) for value in image_data.GetOriginAttr().Get()
        )
        imported_min = tuple(
            imported_origin[index] + min_extent[index] * imported_spacing[index]
            for index in range(3)
        )
        imported_max = tuple(
            imported_origin[index] + max_extent[index] * imported_spacing[index]
            for index in range(3)
        )
        return {
            "origin": imported_origin,
            "spacing": imported_spacing,
            "world_bounds": (imported_min, imported_max),
        }

    @staticmethod
    def _read_kit_cae_vti_origin_opinion(
        dataset_prim,
        cae_vtk,
    ) -> dict[str, object]:
        """Capture the composed ImageData origin and each authored USD opinion."""

        if not dataset_prim or not dataset_prim.IsValid():
            raise RuntimeError("Kit-CAE did not create a VTI dataset to inspect.")
        origin_attr = cae_vtk.ImageDataAPI(dataset_prim).GetOriginAttr()
        if not origin_attr or not origin_attr.IsValid():
            raise RuntimeError("Kit-CAE VTI dataset is missing ImageDataAPI.origin.")

        def serialise_value(value):
            if value is None:
                return None
            try:
                return tuple(float(component) for component in value)
            except TypeError:
                return str(value)

        return {
            "origin": serialise_value(origin_attr.Get()),
            "property_stack": [
                {
                    "layer": spec.layer.identifier,
                    "path": str(spec.path),
                    "default": serialise_value(spec.default),
                }
                for spec in origin_attr.GetPropertyStack()
            ],
        }

    @staticmethod
    def _author_kit_cae_vti_origin_session_opinion(
        dataset_prim,
        vti_header_origin: tuple[float, float, float],
        cae_vtk,
        Gf,
    ) -> None:
        """Restore the VTI origin through the active DTRS session layer."""

        if not dataset_prim or not dataset_prim.IsValid():
            raise RuntimeError("Kit-CAE did not create a VTI dataset to register.")
        origin_attr = cae_vtk.ImageDataAPI(dataset_prim).GetOriginAttr()
        if not origin_attr or not origin_attr.IsValid():
            raise RuntimeError("Kit-CAE VTI dataset is missing ImageDataAPI.origin.")
        origin_attr.Set(Gf.Vec3f(*vti_header_origin))

    @staticmethod
    def _author_kit_cae_spatial_sanity_wireframes(
        stage,
        dataset_world_bounds: tuple[
            tuple[float, float, float], tuple[float, float, float]
        ],
        Gf,
        Usd,
        UsdGeom,
    ) -> None:
        """Draw probe-only dataset and server bounds in distinct colors."""

        bbox_cache = UsdGeom.BBoxCache(
            Usd.TimeCode.Default(),
            [UsdGeom.Tokens.default_, UsdGeom.Tokens.render, UsdGeom.Tokens.proxy],
        )
        server_prim = stage.GetPrimAtPath("/blackwell_rig")
        server_range = bbox_cache.ComputeWorldBound(server_prim).ComputeAlignedRange()
        if server_range.IsEmpty():
            raise RuntimeError(
                "Cannot draw Flow spatial sanity check: server bounds are empty."
            )
        server_world_bounds = (
            tuple(server_range.GetMin()),
            tuple(server_range.GetMax()),
        )
        root_path = "/DTRS_KitCAE/SpatialSanity"
        stage.RemovePrim(root_path)
        root = UsdGeom.Xform.Define(stage, root_path)
        UsdGeom.Imageable(root.GetPrim()).CreateVisibilityAttr().Set(
            UsdGeom.Tokens.invisible
        )

        def author_wireframe(
            name: str,
            bounds: tuple[tuple[float, float, float], tuple[float, float, float]],
            color: tuple[float, float, float],
            width: float,
        ) -> None:
            minimum, maximum = bounds
            corners = (
                (minimum[0], minimum[1], minimum[2]),
                (maximum[0], minimum[1], minimum[2]),
                (maximum[0], maximum[1], minimum[2]),
                (minimum[0], maximum[1], minimum[2]),
                (minimum[0], minimum[1], maximum[2]),
                (maximum[0], minimum[1], maximum[2]),
                (maximum[0], maximum[1], maximum[2]),
                (minimum[0], maximum[1], maximum[2]),
            )
            edges = (
                (0, 1),
                (1, 2),
                (2, 3),
                (3, 0),
                (4, 5),
                (5, 6),
                (6, 7),
                (7, 4),
                (0, 4),
                (1, 5),
                (2, 6),
                (3, 7),
            )
            points = [Gf.Vec3f(*corners[index]) for edge in edges for index in edge]
            curve = UsdGeom.BasisCurves.Define(stage, f"{root_path}/{name}")
            curve.CreateTypeAttr(UsdGeom.Tokens.linear)
            curve.CreateCurveVertexCountsAttr([2] * len(edges))
            curve.CreatePointsAttr(points)
            curve.CreateWidthsAttr([width] * len(points))
            curve.CreateDisplayColorPrimvar(UsdGeom.Tokens.vertex).Set(
                [Gf.Vec3f(*color)] * len(points)
            )

        # The wider server frame remains visible around an aligned dataset frame.
        author_wireframe(
            "ServerBounds",
            server_world_bounds,
            (1.0, 0.28, 0.55),
            0.003,
        )
        author_wireframe(
            "DatasetBounds",
            dataset_world_bounds,
            (0.1, 0.9, 1.0),
            0.0015,
        )

    # FLOW_RUNTIME_METHODS
