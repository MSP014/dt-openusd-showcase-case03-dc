"""Isolated Custom MDL Fresnel validation harness for DTRS.

Owns Debug Probe 01 geometry, its temporary scene state, review-camera world
position synchronisation, and probe-specific diagnostics.  It deliberately
does not control production chassis material bindings or Server Enclosure
visibility; those remain production lifecycle and presentation responsibilities.
"""

from __future__ import annotations

import math
import time

from digital_twin_runtime_suite.app.xray import performance
from digital_twin_runtime_suite.app.xray.material import (
    XRayApplyResult,
    XRayMaterialMixin,
)


class XRayProbeMixin(XRayMaterialMixin):
    """Manage the Cube/Sphere Custom MDL proof without production side effects.

    The probe writes only its own debug prims and temporary server-visibility
    opinion.  Its camera synchronisation supplies ReviewCamera world position
    to the MDL; it never changes ReviewCamera or production X-Ray bindings.
    """

    XRAY_PROBE_ROOT_PATH = "/DTRS_Runtime/Debug/XRayProbe01"
    XRAY_PROBE_MATERIAL_PATH = "/DTRS_Runtime/Debug/Looks/FresnelProbe01"
    XRAY_PROBE_SERVER_PATH = "/blackwell_rig"
    # Probe 01 is derived only from the server extent, keeping it visible in
    # the review framing without introducing a hard-coded world-space size.
    XRAY_PROBE_SIZE_FRACTION = 0.64
    XRAY_PROBE_BOUND_PURPOSES = (
        "default_",
        "render",
        "proxy",
        "guide",
    )
    XRAY_PROBE_SPHERE_LONGITUDE_SEGMENTS = 64
    XRAY_PROBE_SPHERE_LATITUDE_SEGMENTS = 32
    XRAY_PROBE_PERFORMANCE_SAMPLE_INTERVAL_SECONDS = 0.5
    XRAY_PROBE_PERFORMANCE_LOG_INTERVAL_SECONDS = 10.0

    def _format_xray_fresnel_probe_clear_state(
        self,
        stage,
        Usd,
        UsdGeom,
        UsdShade,
        *,
        prior_visibility_state,
        camera_before_clear,
        review_camera_after_clear,
    ) -> str:
        del Usd, UsdShade
        server = stage.GetPrimAtPath(self.XRAY_PROBE_SERVER_PATH)
        session = stage.GetSessionLayer()
        visibility_path = f"{self.XRAY_PROBE_SERVER_PATH}.visibility"
        camera_changed = self._xray_probe_diagnostic_value(
            lambda: not self._xray_probe_camera_positions_match(
                camera_before_clear["review_camera_position"],
                review_camera_after_clear,
            )
        )
        camera_match_before_clear = self._xray_probe_diagnostic_value(
            lambda: self._xray_probe_camera_positions_match(
                camera_before_clear["review_camera_position"],
                camera_before_clear["camera_position_input"],
            )
        )
        statistics = self._xray_probe_diagnostic_value(
            lambda: performance.viewport_performance_state(
                self._xray_probe_performance_samples
            )
        )
        opacity_before_clear = self._xray_fresnel_probe_opacity_state()
        roughness_before_clear = self._xray_fresnel_probe_roughness_state()
        emission_before_clear = self._xray_fresnel_probe_emission_state()
        probe_root_present = stage.GetPrimAtPath(self.XRAY_PROBE_ROOT_PATH).IsValid()
        probe_material_present = stage.GetPrimAtPath(
            self.XRAY_PROBE_MATERIAL_PATH
        ).IsValid()
        server_session_visibility_spec = (
            session.GetPropertyAtPath(visibility_path) is not None
        )
        server_composed_visibility = (
            UsdGeom.Imageable(server).ComputeVisibility() if server else "<missing>"
        )
        return "\n".join(
            (
                "DTRS Custom MDL Fresnel Probe 01",
                "  action: Clear Probe",
                "  shader_mode: static controllable NdotV mask",
                "  review_camera_position_before_clear="
                f"{camera_before_clear['review_camera_position']}",
                "  camera_position_input_before_clear="
                f"{camera_before_clear['camera_position_input']}",
                f"  camera_match_before_clear={camera_match_before_clear}",
                "  live_camera_sync_updates="
                f"{self._xray_probe_live_camera_sync_updates}",
                "  performance:",
                f"    fps_current={statistics['fps_current']}",
                "    frame_time_ms_current=" f"{statistics['frame_time_ms_current']}",
                f"    probe_avg_fps={statistics['average_fps']}",
                "    probe_avg_frame_time_ms=" f"{statistics['average_frame_time_ms']}",
                f"    probe_min_fps={statistics['minimum_fps']}",
                f"    probe_max_fps={statistics['maximum_fps']}",
                f"    gpu_used_gib={statistics['gpu_used_gib']}",
                f"    process_used_gib={statistics['process_used_gib']}",
                f"  opacity_before_clear={opacity_before_clear}",
                f"  roughness_before_clear={roughness_before_clear}",
                f"  emission_before_clear={emission_before_clear}",
                "  review_camera_position_after_clear=" f"{review_camera_after_clear}",
                f"  camera_changed_by_clear={camera_changed}",
                f"  probe_root_present={probe_root_present}",
                f"  probe_material_present={probe_material_present}",
                f"  server_valid={server.IsValid() if server else False}",
                "  prior_server_session_visibility="
                f"{prior_visibility_state[0] if prior_visibility_state else '<none>'}",
                f"  server_session_visibility_spec={server_session_visibility_spec}",
                f"  server_composed_visibility={server_composed_visibility}",
            )
        )

    def _format_xray_fresnel_probe_state(
        self, stage, Usd, UsdGeom, UsdShade, *, action: str, values
    ) -> str:
        material = UsdShade.Material.Get(stage, self.XRAY_PROBE_MATERIAL_PATH)
        shader = UsdShade.Shader.Get(stage, f"{self.XRAY_PROBE_MATERIAL_PATH}/Shader")
        light_paths = []
        for prim in Usd.PrimRange(stage.GetPseudoRoot()):
            if prim.GetTypeName().endswith("Light"):
                visibility = UsdGeom.Imageable(prim).ComputeVisibility()
                light_paths.append(f"{prim.GetPath()}={visibility}")
        cube = stage.GetPrimAtPath(f"{self.XRAY_PROBE_ROOT_PATH}/Cube")
        sphere = stage.GetPrimAtPath(f"{self.XRAY_PROBE_ROOT_PATH}/Sphere")
        (
            facing,
            edge,
            center,
            softness,
            sharpness,
            facing_roughness,
            edge_roughness,
            facing_opacity,
            edge_opacity,
            facing_emission,
            edge_emission,
            emission_scale,
        ) = values
        cube_binding = UsdShade.MaterialBindingAPI(cube).ComputeBoundMaterial()[0]
        sphere_binding = UsdShade.MaterialBindingAPI(sphere).ComputeBoundMaterial()[0]
        sphere_mesh = UsdGeom.Mesh(sphere)
        face_count = len(sphere_mesh.GetFaceVertexCountsAttr().Get() or [])
        point_count = len(sphere_mesh.GetPointsAttr().Get() or [])
        camera_snapshot = self._xray_fresnel_probe_camera_snapshot(
            stage, Usd, UsdGeom, UsdShade
        )
        camera_position = camera_snapshot["camera_position_input"]
        review_camera_position = camera_snapshot["review_camera_position"]
        camera_match = self._xray_probe_diagnostic_value(
            lambda: self._xray_probe_camera_positions_match(
                review_camera_position, camera_position
            )
        )
        statistics = self._xray_probe_diagnostic_value(
            lambda: performance.viewport_performance_state(
                self._xray_probe_performance_samples
            )
        )
        geometry = self._xray_fresnel_probe_geometry_state(stage, Usd, UsdGeom)
        shader_asset = shader.GetSourceAsset("mdl").path if shader else "<missing>"
        cube_binding_path = cube_binding.GetPath() if cube_binding else "<none>"
        sphere_binding_path = sphere_binding.GetPath() if sphere_binding else "<none>"
        server_session_visibility = (
            stage.GetSessionLayer().GetPropertyAtPath("/blackwell_rig.visibility")
            is not None
        )
        scene_lights = ", ".join(light_paths) or "<none>"
        return "\n".join(
            (
                "DTRS Custom MDL Fresnel Probe 01",
                f"  action: {action}",
                "  shader_mode: static controllable NdotV mask",
                f"  camera_position_input: {camera_position}",
                f"  review_camera_position: {review_camera_position}",
                f"  camera_match: {camera_match}",
                "  live_camera_sync: enabled",
                "  live_camera_sync_updates="
                f"{self._xray_probe_live_camera_sync_updates}",
                "  performance:",
                f"    fps_current={statistics['fps_current']}",
                "    frame_time_ms_current=" f"{statistics['frame_time_ms_current']}",
                f"    probe_avg_fps={statistics['average_fps']}",
                "    probe_avg_frame_time_ms=" f"{statistics['average_frame_time_ms']}",
                f"    probe_min_fps={statistics['minimum_fps']}",
                f"    probe_max_fps={statistics['maximum_fps']}",
                f"    gpu_used_gib={statistics['gpu_used_gib']}",
                f"    process_used_gib={statistics['process_used_gib']}",
                "  viewport_framing: disabled",
                (
                    "  parameters: "
                    f"facing_color={facing}; edge_color={edge}; "
                    f"edge_center={center:g}; edge_softness={softness:g}; "
                    f"edge_sharpness={sharpness:g}"
                ),
                (
                    "  roughness: "
                    f"facing_roughness={facing_roughness:g}; "
                    f"edge_roughness={edge_roughness:g}"
                ),
                (
                    "  opacity: "
                    f"facing_opacity={facing_opacity:g}; "
                    f"edge_opacity={edge_opacity:g}"
                ),
                (
                    "  emission: "
                    f"facing_emission={facing_emission:g}; "
                    f"edge_emission={edge_emission:g}; "
                    f"emission_scale={emission_scale:.2f}; "
                    "effective_facing_emission="
                    f"{facing_emission * emission_scale:.2f}; "
                    "effective_edge_emission="
                    f"{edge_emission * emission_scale:.2f}"
                ),
                "  probe_geometry:",
                f"    server_bbox_min={geometry['server_bbox_min']}",
                f"    server_bbox_max={geometry['server_bbox_max']}",
                f"    server_bbox_extent={geometry['server_bbox_extent']}",
                f"    server_bbox_max_extent={geometry['server_bbox_max_extent']:g}",
                f"    probe_scale_fraction={self.XRAY_PROBE_SIZE_FRACTION:g}",
                f"    probe_size={geometry['probe_size']:g}",
                f"    cube_size={geometry['cube_size']:g}",
                f"    sphere_radius={geometry['sphere_radius']:g}",
                f"    cube_center={geometry['cube_center']}",
                f"    sphere_center={geometry['sphere_center']}",
                f"    center_distance={geometry['center_distance']:g}",
                f"    gap={geometry['gap']:g}",
                (
                    "  scene: "
                    f"cube={cube.IsValid()} ({cube.GetTypeName()}); "
                    f"sphere={sphere.IsValid()} ({sphere.GetTypeName()}, "
                    f"points={point_count}, triangles={face_count}, "
                    "segments="
                    f"{self.XRAY_PROBE_SPHERE_LONGITUDE_SEGMENTS}x"
                    f"{self.XRAY_PROBE_SPHERE_LATITUDE_SEGMENTS})"
                ),
                (
                    "  material: "
                    f"exists={bool(material)}; "
                    f"shader_asset={shader_asset}; "
                    f"cube_binding={cube_binding_path}; "
                    f"sphere_binding={sphere_binding_path}"
                ),
                f"  server_session_visibility={server_session_visibility}",
                (
                    "  preserved_lights="
                    f"{len(self._xray_probe_light_visibility_states)}; "
                    f"scene_lights={scene_lights}"
                ),
            )
        )

    def _clear_xray_fresnel_probe(self, stage) -> None:
        from pxr import UsdGeom

        stage.RemovePrim(self.XRAY_PROBE_ROOT_PATH)
        stage.RemovePrim(self.XRAY_PROBE_MATERIAL_PATH)
        server = stage.GetPrimAtPath(self.XRAY_PROBE_SERVER_PATH)
        prior = getattr(self, "_xray_probe_visibility_state", None)
        if server and server.IsValid() and prior is not None:
            had_session_spec, value = prior
            visibility = server.GetAttribute("visibility")
            if had_session_spec:
                visibility.Set(value)
            else:
                server.RemoveProperty("visibility")
                self._remove_xray_probe_session_property_spec(
                    stage, visibility.GetPath()
                )
        for path, had_session_spec, value in getattr(
            self, "_xray_probe_light_visibility_states", []
        ):
            prim = stage.GetPrimAtPath(path)
            if not prim or not prim.IsValid():
                continue
            if had_session_spec:
                UsdGeom.Imageable(prim).GetVisibilityAttr().Set(value)
            else:
                prim.RemoveProperty("visibility")
                self._remove_xray_probe_session_property_spec(
                    stage, UsdGeom.Imageable(prim).GetVisibilityAttr().GetPath()
                )
        self._xray_probe_visibility_state = None
        self._xray_probe_light_visibility_states = []
        self._xray_probe_server_bbox_snapshot = None

    @staticmethod
    def _remove_xray_probe_session_property_spec(stage, property_path) -> None:
        """Remove a probe-owned property spec if the Usd convenience call left it."""

        session_prim = stage.GetSessionLayer().GetPrimAtPath(
            property_path.GetPrimPath()
        )
        property_spec = stage.GetSessionLayer().GetPropertyAtPath(property_path)
        if session_prim and property_spec:
            session_prim.RemoveProperty(property_spec)

    @classmethod
    def _define_xray_fresnel_probe_sphere(cls, stage, path, radius, Gf, UsdGeom):
        """Define a smooth UV mesh because UsdGeom.Sphere has no resolution field."""

        longitude_count = cls.XRAY_PROBE_SPHERE_LONGITUDE_SEGMENTS
        latitude_count = cls.XRAY_PROBE_SPHERE_LATITUDE_SEGMENTS
        points = [Gf.Vec3f(0.0, float(radius), 0.0)]
        normals = [Gf.Vec3f(0.0, 1.0, 0.0)]
        for latitude in range(1, latitude_count):
            theta = math.pi * latitude / latitude_count
            sin_theta = math.sin(theta)
            y = math.cos(theta)
            for longitude in range(longitude_count):
                phi = 2.0 * math.pi * longitude / longitude_count
                normal = Gf.Vec3f(
                    sin_theta * math.cos(phi), y, sin_theta * math.sin(phi)
                )
                normals.append(normal)
                points.append(normal * radius)
        bottom_index = len(points)
        points.append(Gf.Vec3f(0.0, -float(radius), 0.0))
        normals.append(Gf.Vec3f(0.0, -1.0, 0.0))

        face_counts = []
        face_indices = []
        first_ring = 1
        last_ring = 1 + (latitude_count - 2) * longitude_count
        for longitude in range(longitude_count):
            current = first_ring + longitude
            following = first_ring + (longitude + 1) % longitude_count
            face_counts.append(3)
            face_indices.extend((0, following, current))
        for latitude in range(latitude_count - 2):
            ring = first_ring + latitude * longitude_count
            next_ring = ring + longitude_count
            for longitude in range(longitude_count):
                current = ring + longitude
                following = ring + (longitude + 1) % longitude_count
                next_current = next_ring + longitude
                next_following = next_ring + (longitude + 1) % longitude_count
                face_counts.extend((3, 3))
                face_indices.extend(
                    (
                        current,
                        following,
                        next_following,
                        current,
                        next_following,
                        next_current,
                    )
                )
        for longitude in range(longitude_count):
            current = last_ring + longitude
            following = last_ring + (longitude + 1) % longitude_count
            face_counts.append(3)
            face_indices.extend((bottom_index, current, following))

        sphere = UsdGeom.Mesh.Define(stage, path)
        sphere.CreatePointsAttr(points)
        sphere.CreateNormalsAttr(normals)
        sphere.SetNormalsInterpolation(UsdGeom.Tokens.vertex)
        sphere.CreateFaceVertexCountsAttr(face_counts)
        sphere.CreateFaceVertexIndicesAttr(face_indices)
        sphere.CreateExtentAttr(
            [
                Gf.Vec3f(-radius, -radius, -radius),
                Gf.Vec3f(radius, radius, radius),
            ]
        )
        sphere.CreateDoubleSidedAttr(True)
        return sphere

    def _xray_fresnel_probe_geometry_state(self, stage, Usd, UsdGeom) -> dict:
        """Read the authored Probe 01 dimensions for a compact operator log."""

        bbox = self._xray_probe_server_bbox_snapshot
        if bbox is None:
            raise ValueError("pre-hide server bounds were not captured")
        bbox_min = bbox.GetMin()
        bbox_max = bbox.GetMax()
        bbox_extent = bbox.GetSize()
        max_extent = max(float(component) for component in bbox_extent)
        cube = UsdGeom.Cube.Get(stage, f"{self.XRAY_PROBE_ROOT_PATH}/Cube")
        sphere = UsdGeom.Mesh.Get(stage, f"{self.XRAY_PROBE_ROOT_PATH}/Sphere")
        cube_size = float(cube.GetSizeAttr().Get())
        sphere_points = sphere.GetPointsAttr().Get() or []
        sphere_radius = max(
            (
                math.sqrt(
                    float(point[0]) ** 2 + float(point[1]) ** 2 + float(point[2]) ** 2
                )
                for point in sphere_points
            ),
            default=0.0,
        )
        xform_cache = UsdGeom.XformCache(Usd.TimeCode.Default())
        cube_center = xform_cache.GetLocalToWorldTransform(
            cube.GetPrim()
        ).ExtractTranslation()
        sphere_center = xform_cache.GetLocalToWorldTransform(
            sphere.GetPrim()
        ).ExtractTranslation()
        center_distance = math.sqrt(
            sum(
                (float(sphere_center[index]) - float(cube_center[index])) ** 2
                for index in range(3)
            )
        )
        return {
            "server_bbox_min": tuple(float(value) for value in bbox_min),
            "server_bbox_max": tuple(float(value) for value in bbox_max),
            "server_bbox_extent": tuple(float(value) for value in bbox_extent),
            "server_bbox_max_extent": max_extent,
            "probe_size": max_extent * self.XRAY_PROBE_SIZE_FRACTION,
            "cube_size": cube_size,
            "sphere_radius": sphere_radius,
            "cube_center": tuple(float(value) for value in cube_center),
            "sphere_center": tuple(float(value) for value in sphere_center),
            "center_distance": center_distance,
            "gap": center_distance - cube_size * 0.5 - sphere_radius,
        }

    def _xray_fresnel_probe_camera_snapshot(self, stage, Usd, UsdGeom, UsdShade):
        """Collect camera diagnostics without allowing inspection to affect cleanup."""

        shader = UsdShade.Shader.Get(stage, f"{self.XRAY_PROBE_MATERIAL_PATH}/Shader")
        camera_input = shader.GetInput("camera_position") if shader else None
        return {
            "review_camera_position": self._xray_probe_diagnostic_value(
                lambda: self._xray_fresnel_probe_camera_position(stage, Usd, UsdGeom)
            ),
            "camera_position_input": self._xray_probe_diagnostic_value(
                lambda: (
                    camera_input.Get()
                    if camera_input and camera_input.GetAttr().HasAuthoredValue()
                    else "<missing>"
                )
            ),
        }

    @staticmethod
    def _xray_probe_camera_positions_match(current, authored, tolerance=1.0e-4):
        if current is None or authored is None:
            raise ValueError("camera position is missing")
        return all(
            abs(float(current[index]) - float(authored[index])) <= tolerance
            for index in range(3)
        )

    @classmethod
    def _xray_fresnel_probe_camera_position(cls, stage, Usd, UsdGeom):
        """Return the ReviewCamera world-space position for the static MDL probe."""

        camera = stage.GetPrimAtPath("/DTRS_Runtime/ReviewCamera")
        if not camera or not camera.IsValid():
            return None
        matrix = UsdGeom.XformCache(Usd.TimeCode.Default()).GetLocalToWorldTransform(
            camera
        )
        position = matrix.ExtractTranslation()
        return (float(position[0]), float(position[1]), float(position[2]))

    @classmethod
    def _xray_fresnel_probe_layout(cls, bbox):
        """Return a non-overlapping cube/sphere layout within the server scale."""

        size = (
            max(float(component) for component in bbox.GetSize())
            * cls.XRAY_PROBE_SIZE_FRACTION
        )
        center = (bbox.GetMin() + bbox.GetMax()) * 0.5
        gap = size * 0.25
        # Cube half-width + sphere radius + visible gap.
        distance = size * 0.5 + size * 0.5 + gap
        return size, center, distance, gap

    @classmethod
    def _define_xray_fresnel_probe_geometry(cls, stage, bbox, Gf, UsdGeom):
        """Author probe geometry from server bounds without moving the camera."""

        size, center, distance, _gap = cls._xray_fresnel_probe_layout(bbox)
        cube = UsdGeom.Cube.Define(stage, f"{cls.XRAY_PROBE_ROOT_PATH}/Cube")
        cube.CreateSizeAttr(size)
        sphere = cls._define_xray_fresnel_probe_sphere(
            stage,
            f"{cls.XRAY_PROBE_ROOT_PATH}/Sphere",
            size * 0.5,
            Gf,
            UsdGeom,
        )
        cube.AddTranslateOp().Set(
            Gf.Vec3d(center[0] - distance * 0.5, center[1], center[2])
        )
        sphere.AddTranslateOp().Set(
            Gf.Vec3d(center[0] + distance * 0.5, center[1], center[2])
        )
        return cube, sphere

    @classmethod
    def _xray_fresnel_probe_server_bbox(cls, server, Usd, UsdGeom):
        """Return valid server bounds without depending on composed visibility."""

        purposes = [
            getattr(UsdGeom.Tokens, name) for name in cls.XRAY_PROBE_BOUND_PURPOSES
        ]
        bbox = (
            UsdGeom.BBoxCache(
                Usd.TimeCode.Default(),
                purposes,
                useExtentsHint=True,
                ignoreVisibility=True,
            )
            .ComputeWorldBound(server)
            .ComputeAlignedBox()
        )
        extent = bbox.GetSize()
        max_extent = max(float(component) for component in extent)
        return bbox if math.isfinite(max_extent) and max_extent > 0.0 else None

    @staticmethod
    def _log_xray_fresnel_probe_diagnostic(carb, *, action: str, formatter) -> None:
        """Diagnostics must not alter the result of an already-authored probe."""

        try:
            carb.log_warn(formatter())
        except Exception as error:
            carb.log_warn(
                "DTRS Custom MDL Fresnel Probe 01\n"
                f"  action: {action}\n"
                f"  diagnostic: <inspection failed: {error}>"
            )

    @staticmethod
    def _xray_probe_diagnostic_value(reader):
        try:
            return reader()
        except Exception as error:
            return f"<inspection failed: {error}>"

    def _capture_and_hide_xray_probe_server(self, stage, Usd, UsdGeom) -> None:
        server = stage.GetPrimAtPath(self.XRAY_PROBE_SERVER_PATH)
        visibility = UsdGeom.Imageable(server).GetVisibilityAttr()
        spec = stage.GetSessionLayer().GetPropertyAtPath(visibility.GetPath())
        self._xray_probe_visibility_state = (
            spec is not None,
            visibility.Get() if spec is not None else None,
        )
        visibility.Set(UsdGeom.Tokens.invisible)
        self._xray_probe_light_visibility_states = []
        for prim in Usd.PrimRange(server):
            if not prim.GetTypeName().endswith("Light"):
                continue
            light_visibility = UsdGeom.Imageable(prim).GetVisibilityAttr()
            light_spec = stage.GetSessionLayer().GetPropertyAtPath(
                light_visibility.GetPath()
            )
            self._xray_probe_light_visibility_states.append(
                (str(prim.GetPath()), light_spec is not None, light_visibility.Get())
            )
            light_visibility.Set(UsdGeom.Tokens.inherited)

    def _xray_fresnel_probe_opacity_state(self) -> dict[str, str]:
        try:
            values = self._xray_probe_last_values
            return {
                "facing_opacity": (
                    f"{float(values[7]):.2f}" if values is not None else "<unavailable>"
                ),
                "edge_opacity": (
                    f"{float(values[8]):.2f}" if values is not None else "<unavailable>"
                ),
            }
        except Exception as error:
            unavailable = f"<inspection failed: {error}>"
            return {"facing_opacity": unavailable, "edge_opacity": unavailable}

    def _xray_fresnel_probe_emission_state(self) -> dict[str, str]:
        try:
            values = self._xray_probe_last_values
            return {
                "facing_emission": (
                    f"{float(values[9]):.2f}" if values is not None else "<unavailable>"
                ),
                "edge_emission": (
                    f"{float(values[10]):.2f}"
                    if values is not None
                    else "<unavailable>"
                ),
                "emission_scale": (
                    f"{float(values[11]):.2f}"
                    if values is not None
                    else "<unavailable>"
                ),
                "effective_facing_emission": (
                    f"{float(values[9]) * float(values[11]):.2f}"
                    if values is not None
                    else "<unavailable>"
                ),
                "effective_edge_emission": (
                    f"{float(values[10]) * float(values[11]):.2f}"
                    if values is not None
                    else "<unavailable>"
                ),
            }
        except Exception as error:
            unavailable = f"<inspection failed: {error}>"
            return {
                "facing_emission": unavailable,
                "edge_emission": unavailable,
                "emission_scale": unavailable,
                "effective_facing_emission": unavailable,
                "effective_edge_emission": unavailable,
            }

    def _xray_fresnel_probe_roughness_state(self) -> dict[str, str]:
        try:
            values = self._xray_probe_last_values
            return {
                "facing_roughness": (
                    f"{float(values[5]):.2f}" if values is not None else "<unavailable>"
                ),
                "edge_roughness": (
                    f"{float(values[6]):.2f}" if values is not None else "<unavailable>"
                ),
            }
        except Exception as error:
            unavailable = f"<inspection failed: {error}>"
            return {"facing_roughness": unavailable, "edge_roughness": unavailable}

    def _format_xray_fresnel_probe_performance_interval(
        self, samples: list[performance.ViewportPerformanceSample]
    ) -> str:
        statistics = performance.viewport_performance_state(samples)
        latest = samples[-1] if samples else None
        started_at = self._xray_probe_performance_started_at
        elapsed = (
            latest.captured_at - started_at
            if latest is not None and started_at is not None
            else None
        )
        opacity = self._xray_fresnel_probe_opacity_state()
        roughness = self._xray_fresnel_probe_roughness_state()
        emission = self._xray_fresnel_probe_emission_state()
        elapsed_text = f"{elapsed:.1f} s" if elapsed is not None else "<unavailable>"
        return "\n".join(
            (
                "DTRS Custom MDL Fresnel Probe 01 - PERFORMANCE",
                f"  elapsed={elapsed_text}",
                "  live_camera_sync_updates="
                f"{self._xray_probe_live_camera_sync_updates}",
                "  opacity:",
                f"    facing_opacity={opacity['facing_opacity']}",
                f"    edge_opacity={opacity['edge_opacity']}",
                "  roughness: "
                f"facing={roughness['facing_roughness']}; "
                f"edge={roughness['edge_roughness']}",
                "  emission:",
                f"    facing_emission={emission['facing_emission']}",
                f"    edge_emission={emission['edge_emission']}",
                f"    emission_scale={emission['emission_scale']}",
                "    effective_facing=" f"{emission['effective_facing_emission']}",
                "    effective_edge=" f"{emission['effective_edge_emission']}",
                "  FPS:",
                f"    current={statistics['fps_current']}",
                f"    average={statistics['average_fps']}",
                f"    minimum={statistics['minimum_fps']}",
                f"    maximum={statistics['maximum_fps']}",
                "  Frame time:",
                f"    current={statistics['frame_time_ms_current']} ms",
                f"    average={statistics['average_frame_time_ms']} ms",
                "  Memory:",
                f"    gpu_used_gib={statistics['gpu_used_gib']}",
                f"    process_used_gib={statistics['process_used_gib']}",
            )
        )

    def sync_xray_fresnel_probe_camera_in_kit(self) -> bool:
        """Update the active probe's MDL camera input only when it moved."""

        import omni.usd
        from pxr import Gf, Usd, UsdGeom, UsdShade

        stage = omni.usd.get_context().get_stage()
        if not stage:
            self._stop_xray_fresnel_probe_performance_sampler()
            return False
        probe_root = stage.GetPrimAtPath(self.XRAY_PROBE_ROOT_PATH)
        material_prim = stage.GetPrimAtPath(self.XRAY_PROBE_MATERIAL_PATH)
        if not (
            probe_root
            and probe_root.IsValid()
            and material_prim
            and material_prim.IsValid()
        ):
            self._stop_xray_fresnel_probe_performance_sampler()
            return False
        shader = UsdShade.Shader.Get(stage, f"{self.XRAY_PROBE_MATERIAL_PATH}/Shader")
        if not shader or not shader.GetPrim().IsValid():
            self._stop_xray_fresnel_probe_performance_sampler()
            return False
        camera_input = shader.GetInput("camera_position")
        if not camera_input or not camera_input.GetAttr().HasAuthoredValue():
            self._stop_xray_fresnel_probe_performance_sampler()
            return False
        self._advance_xray_fresnel_probe_performance_sampler()
        current_position = self._xray_fresnel_probe_camera_position(stage, Usd, UsdGeom)
        if current_position is None:
            return False
        authored_position = camera_input.Get()
        if authored_position is None or self._xray_probe_camera_positions_match(
            current_position, authored_position
        ):
            return False
        previous_target = stage.GetEditTarget()
        stage.SetEditTarget(stage.GetSessionLayer())
        try:
            camera_input.Set(Gf.Vec3f(*current_position))
            self._xray_probe_live_camera_sync_updates += 1
        finally:
            stage.SetEditTarget(previous_target)
        return True

    def _start_xray_fresnel_probe_performance_sampler(self) -> None:
        """Reset one HUD-backed sampler when a new Probe 01 is created."""

        initial_sample = performance.capture_viewport_performance_sample()
        started_at = initial_sample.captured_at
        self._xray_probe_performance_started_at = started_at
        self._xray_probe_performance_next_sample_at = (
            started_at + self.XRAY_PROBE_PERFORMANCE_SAMPLE_INTERVAL_SECONDS
        )
        self._xray_probe_performance_next_log_at = (
            started_at + self.XRAY_PROBE_PERFORMANCE_LOG_INTERVAL_SECONDS
        )
        self._xray_probe_performance_interval_started_at = started_at
        self._xray_probe_performance_samples = [initial_sample]

    def _stop_xray_fresnel_probe_performance_sampler(self) -> None:
        """Clear the probe sampler when its transient material no longer exists."""

        self._xray_probe_performance_started_at = None
        self._xray_probe_performance_next_sample_at = None
        self._xray_probe_performance_next_log_at = None
        self._xray_probe_performance_interval_started_at = None
        self._xray_probe_performance_samples = []

    def _advance_xray_fresnel_probe_performance_sampler(self) -> None:
        """Collect HUD samples in the existing camera-sync loop without a task."""

        started_at = self._xray_probe_performance_started_at
        next_sample_at = self._xray_probe_performance_next_sample_at
        next_log_at = self._xray_probe_performance_next_log_at
        if started_at is None or next_sample_at is None or next_log_at is None:
            self._start_xray_fresnel_probe_performance_sampler()
            return
        now = time.monotonic()
        if now < next_sample_at:
            return
        sample = performance.capture_viewport_performance_sample()
        self._xray_probe_performance_samples.append(sample)
        self._xray_probe_performance_next_sample_at = (
            now + self.XRAY_PROBE_PERFORMANCE_SAMPLE_INTERVAL_SECONDS
        )
        if now < next_log_at:
            return
        interval_started_at = self._xray_probe_performance_interval_started_at
        interval_samples = [
            item
            for item in self._xray_probe_performance_samples
            if interval_started_at is None or item.captured_at >= interval_started_at
        ]
        import carb

        self._log_xray_fresnel_probe_diagnostic(
            carb,
            action="PERFORMANCE",
            formatter=lambda: self._format_xray_fresnel_probe_performance_interval(
                interval_samples
            ),
        )
        self._xray_probe_performance_interval_started_at = sample.captured_at
        self._xray_probe_performance_next_log_at = (
            now + self.XRAY_PROBE_PERFORMANCE_LOG_INTERVAL_SECONDS
        )

    def apply_xray_fresnel_probe_in_kit(
        self,
        values: tuple[
            tuple[float, float, float],
            tuple[float, float, float],
            float,
            float,
            float,
            float,
            float,
            float,
            float,
            float,
            float,
            float,
        ],
        *,
        rebuild: bool,
    ) -> XRayApplyResult:
        """Author or update the non-persistent Custom MDL Fresnel probe."""
        import carb
        import omni.usd
        from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade

        stage = omni.usd.get_context().get_stage()
        if not stage:
            return XRayApplyResult(False, "Fresnel probe skipped: no open stage.")
        server = stage.GetPrimAtPath(self.XRAY_PROBE_SERVER_PATH)
        if not server or not server.IsValid():
            return XRayApplyResult(
                False, "Fresnel probe skipped: server root not found."
            )
        previous_target = stage.GetEditTarget()
        stage.SetEditTarget(stage.GetSessionLayer())
        try:
            camera_position = None
            if rebuild or not stage.GetPrimAtPath(self.XRAY_PROBE_ROOT_PATH):
                camera_position = self._xray_fresnel_probe_camera_position(
                    stage, Usd, UsdGeom
                )
                if camera_position is None:
                    return XRayApplyResult(
                        False, "Fresnel probe skipped: review camera not found."
                    )
                self._clear_xray_fresnel_probe(stage)
                # BBoxCache prunes a subtree with resolved visibility=invisible.
                # Snapshot bounds before the probe's Session Layer hides the server.
                bbox = self._xray_fresnel_probe_server_bbox(server, Usd, UsdGeom)
                if bbox is None:
                    return XRayApplyResult(
                        False, "Fresnel probe skipped: server bounds are unavailable."
                    )
                self._xray_probe_server_bbox_snapshot = bbox
                self._capture_and_hide_xray_probe_server(stage, Usd, UsdGeom)
                # The review camera is already framed for the server. Keep the
                # isolated objects small enough to fit that existing framing;
                # Probe 01 must not move the camera after sampling it for MDL.
                cube, sphere = self._define_xray_fresnel_probe_geometry(
                    stage, bbox, Gf, UsdGeom
                )
                material = self._define_xray_fresnel_probe_material(
                    stage, Sdf, UsdShade
                )
                for prim in (cube.GetPrim(), sphere.GetPrim()):
                    UsdShade.MaterialBindingAPI.Apply(prim).Bind(material)
                self._xray_probe_live_camera_sync_updates = 0
                self._start_xray_fresnel_probe_performance_sampler()
            self._set_xray_fresnel_probe_values(
                stage,
                values,
                Gf,
                Sdf,
                UsdShade,
                camera_position=camera_position,
            )
            self._xray_probe_last_values = values
            self._log_xray_fresnel_probe_diagnostic(
                carb,
                action="Probe 01" if rebuild else "Apply Probe Parameters",
                formatter=lambda: self._format_xray_fresnel_probe_state(
                    stage,
                    Usd,
                    UsdGeom,
                    UsdShade,
                    action="Probe 01" if rebuild else "Apply Probe Parameters",
                    values=values,
                ),
            )
            return XRayApplyResult(True, "Custom MDL Fresnel Probe 01 ready.", 2)
        finally:
            stage.SetEditTarget(previous_target)

    def clear_xray_fresnel_probe_in_kit(self) -> XRayApplyResult:
        """Remove Probe 01 and release only the visibility state it captured."""

        import carb
        import omni.usd
        from pxr import Usd, UsdGeom, UsdShade

        stage = omni.usd.get_context().get_stage()
        if not stage:
            self._stop_xray_fresnel_probe_performance_sampler()
            return XRayApplyResult(True, "Fresnel probe is inactive; no open stage.")
        previous_target = stage.GetEditTarget()
        stage.SetEditTarget(stage.GetSessionLayer())
        try:
            prior_visibility_state = self._xray_probe_visibility_state
            camera_before_clear = self._xray_fresnel_probe_camera_snapshot(
                stage, Usd, UsdGeom, UsdShade
            )
            self._clear_xray_fresnel_probe(stage)
            review_camera_after_clear = self._xray_probe_diagnostic_value(
                lambda: self._xray_fresnel_probe_camera_position(stage, Usd, UsdGeom)
            )
            self._log_xray_fresnel_probe_diagnostic(
                carb,
                action="Clear Probe",
                formatter=lambda: self._format_xray_fresnel_probe_clear_state(
                    stage,
                    Usd,
                    UsdGeom,
                    UsdShade,
                    prior_visibility_state=prior_visibility_state,
                    camera_before_clear=camera_before_clear,
                    review_camera_after_clear=review_camera_after_clear,
                ),
            )
            self._stop_xray_fresnel_probe_performance_sampler()
        finally:
            stage.SetEditTarget(previous_target)
        return XRayApplyResult(True, "Custom MDL Fresnel Probe cleared.")
