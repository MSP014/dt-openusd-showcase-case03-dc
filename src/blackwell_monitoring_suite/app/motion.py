"""Runtime motion helpers for telemetry-driven scene behaviour."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Sequence

Vector3 = tuple[float, float, float]


@dataclass(frozen=True)
class PivotCandidate:
    """High-valence mesh vertex that may be a cylinder-cap centre pole."""

    index: int
    position: Vector3
    valence: int
    min_neighbour_distance: float


@dataclass(frozen=True)
class PivotResolution:
    """Resolved local-space pivot and axis for a rotating mesh."""

    pivot: Vector3
    axis: Vector3
    axis_name: str
    candidates: tuple[PivotCandidate, ...]


@dataclass
class _MotionBinding:
    stage_id: int
    target_path: str
    mesh_path: str
    pivot: Vector3
    axis_name: str
    rotate_op: object
    uses_authored_origin: bool


class TopologyPivotResolver:
    """Resolve fan/blower pivot data from cylinder-derived mesh topology."""

    def __init__(
        self,
        *,
        minimum_valence: int = 32,
        centre_window_fraction: float = 0.45,
    ) -> None:
        self.minimum_valence = minimum_valence
        self.centre_window_fraction = centre_window_fraction

    def resolve(
        self,
        points: Sequence[Sequence[float]],
        face_vertex_counts: Sequence[int],
        face_vertex_indices: Sequence[int],
    ) -> PivotResolution:
        if not points:
            raise ValueError("Cannot resolve pivot from an empty point list.")

        adjacency = self._build_adjacency(
            len(points), face_vertex_counts, face_vertex_indices
        )
        candidates = self._find_candidates(points, adjacency)
        if len(candidates) < 2:
            raise ValueError("No high-valence hub pole candidates found.")

        selected = self._select_central_candidates(points, candidates)
        pivot = _mean_position(candidate.position for candidate in selected)
        axis_name = _dominant_axis(selected)
        axis = _axis_vector(axis_name)
        return PivotResolution(
            pivot=pivot,
            axis=axis,
            axis_name=axis_name,
            candidates=tuple(selected),
        )

    @staticmethod
    def _build_adjacency(
        point_count: int,
        face_vertex_counts: Sequence[int],
        face_vertex_indices: Sequence[int],
    ) -> tuple[set[int], ...]:
        adjacency: list[set[int]] = [set() for _ in range(point_count)]
        offset = 0
        for count in face_vertex_counts:
            face = face_vertex_indices[offset : offset + count]
            if len(face) != count:
                raise ValueError("Face vertex index buffer ended early.")
            for index, vertex in enumerate(face):
                neighbour = face[(index + 1) % count]
                adjacency[vertex].add(neighbour)
                adjacency[neighbour].add(vertex)
            offset += count
        if offset != len(face_vertex_indices):
            raise ValueError("Face vertex counts do not consume the index buffer.")
        return tuple(adjacency)

    def _find_candidates(
        self,
        points: Sequence[Sequence[float]],
        adjacency: Sequence[set[int]],
    ) -> list[PivotCandidate]:
        candidates: list[PivotCandidate] = []
        for index, neighbours in enumerate(adjacency):
            valence = len(neighbours)
            if valence < self.minimum_valence:
                continue
            position = _to_vector3(points[index])
            min_distance = min(
                _distance(position, _to_vector3(points[neighbour]))
                for neighbour in neighbours
            )
            candidates.append(
                PivotCandidate(
                    index=index,
                    position=position,
                    valence=valence,
                    min_neighbour_distance=min_distance,
                )
            )
        return candidates

    def _select_central_candidates(
        self,
        points: Sequence[Sequence[float]],
        candidates: Sequence[PivotCandidate],
    ) -> tuple[PivotCandidate, ...]:
        bbox_min, bbox_max = _bounds(points)
        bbox_centre = tuple(
            (bbox_min[index] + bbox_max[index]) * 0.5 for index in range(3)
        )
        bbox_diagonal = max(_distance(bbox_min, bbox_max), 1e-9)
        max_valence = max(candidate.valence for candidate in candidates)
        valence_floor = max(self.minimum_valence, int(max_valence * 0.75))
        centre_radius = bbox_diagonal * self.centre_window_fraction
        high_valence = [
            candidate for candidate in candidates if candidate.valence >= valence_floor
        ]
        if len(high_valence) <= 8:
            selected = high_valence
        else:
            selected = [
                candidate
                for candidate in high_valence
                if _distance(candidate.position, bbox_centre) <= centre_radius
            ]

        if len(selected) < 2:
            selected = high_valence
        return tuple(
            sorted(
                selected,
                key=lambda candidate: (
                    -candidate.valence,
                    -candidate.min_neighbour_distance,
                    _distance(candidate.position, bbox_centre),
                    candidate.index,
                ),
            )
        )


class VisualRpmMapper:
    """Map realistic telemetry RPM to readable viewport presentation RPM."""

    def __init__(
        self,
        *,
        telemetry_min_rpm: float = 650.0,
        telemetry_max_rpm: float = 2300.0,
        visual_min_rpm: float = 40.0,
        visual_max_rpm: float = 360.0,
    ) -> None:
        self.telemetry_min_rpm = telemetry_min_rpm
        self.telemetry_max_rpm = telemetry_max_rpm
        self.visual_min_rpm = visual_min_rpm
        self.visual_max_rpm = visual_max_rpm

    def map(self, telemetry_rpm: float) -> float:
        span = self.telemetry_max_rpm - self.telemetry_min_rpm
        if span <= 0.0:
            return self.visual_min_rpm
        t = (telemetry_rpm - self.telemetry_min_rpm) / span
        t = min(1.0, max(0.0, t))
        return self.visual_min_rpm + ((self.visual_max_rpm - self.visual_min_rpm) * t)


class RotationMotionController:
    """Drive one rotating USD prim from a telemetry RPM metric."""

    DEFAULT_MESH_PATH = "/cpu_fan/geo/render/cpu_cooler/cpu_fan/blades/blades"
    PIVOT_OP_SUFFIX = "mspMotionPivot"
    ROTATE_OP_SUFFIX = "mspMotionSpin"

    def __init__(
        self,
        *,
        mesh_path: str = DEFAULT_MESH_PATH,
        rotation_target_path: str | None = None,
        rotation_axis: str | None = None,
        pivot_mode: str = "auto",
        metric_id: str = "cpu_fan_rpm",
        resolver: TopologyPivotResolver | None = None,
        rpm_mapper: VisualRpmMapper | None = None,
        max_dt: float = 0.1,
        authored_origin_tolerance: float = 0.005,
    ) -> None:
        self.mesh_path = mesh_path
        self.rotation_target_path = rotation_target_path
        self.rotation_axis = rotation_axis.upper() if rotation_axis else None
        self.pivot_mode = pivot_mode
        self.metric_id = metric_id
        self.resolver = resolver or TopologyPivotResolver()
        self.rpm_mapper = rpm_mapper or VisualRpmMapper()
        self.max_dt = max_dt
        self.authored_origin_tolerance = authored_origin_tolerance
        self._binding: _MotionBinding | None = None
        self._last_update_time: float | None = None
        self._angle_degrees = 0.0
        self._warned_messages: set[str] = set()

    @property
    def angle_degrees(self) -> float:
        return self._angle_degrees

    def reset(self) -> None:
        self._binding = None
        self._last_update_time = None
        self._angle_degrees = 0.0

    def update(self, stage: object | None, snapshot: object | None, now: float) -> None:
        if stage is None or snapshot is None:
            return
        try:
            telemetry_rpm = self._read_metric(snapshot)
            binding = self._binding
            if (
                binding is None
                or binding.stage_id != id(stage)
                or not _stage_has_prim(stage, binding.target_path)
            ):
                binding = self._resolve_binding(stage)
                self._binding = binding

            if self._last_update_time is None:
                self._last_update_time = now
                return

            dt = min(max(0.0, now - self._last_update_time), self.max_dt)
            self._last_update_time = now
            visual_rpm = self.rpm_mapper.map(telemetry_rpm)
            self._angle_degrees = (
                self._angle_degrees + (dt * visual_rpm * 6.0)
            ) % 360.0
            self._set_rotation(stage, binding, self._angle_degrees)
        except Exception as exc:  # noqa: BLE001
            self._warn_once(f"motion update skipped: {exc}")

    def _read_metric(self, snapshot: object) -> float:
        metrics = getattr(snapshot, "metrics")
        metric = metrics[self.metric_id]
        return float(getattr(metric, "value"))

    def _resolve_binding(self, stage: object) -> _MotionBinding:
        from pxr import UsdGeom

        mesh_prim = stage.GetPrimAtPath(self.mesh_path)
        if not mesh_prim or not mesh_prim.IsValid():
            raise ValueError(f"Motion mesh not found: {self.mesh_path}")

        target_prim = self._resolve_target_prim(stage, mesh_prim)
        if self.pivot_mode == "authored_origin":
            axis_name = self._configured_axis()
            rotate_op = self._ensure_direct_rotation_op(
                stage,
                target_prim,
                axis_name,
            )
            return _MotionBinding(
                stage_id=id(stage),
                target_path=str(target_prim.GetPath()),
                mesh_path=self.mesh_path,
                pivot=(0.0, 0.0, 0.0),
                axis_name=axis_name,
                rotate_op=rotate_op,
                uses_authored_origin=True,
            )

        mesh = UsdGeom.Mesh(mesh_prim)
        points = mesh.GetPointsAttr().Get()
        counts = mesh.GetFaceVertexCountsAttr().Get()
        indices = mesh.GetFaceVertexIndicesAttr().Get()
        resolution = self.resolver.resolve(points, counts, indices)
        axis_name = self.rotation_axis or resolution.axis_name
        if self.pivot_mode == "topology_pivot":
            uses_authored_origin = False
        else:
            uses_authored_origin = _pivot_axis_is_near_origin(
                resolution.pivot,
                axis_name,
                self.authored_origin_tolerance,
            )

        if uses_authored_origin:
            rotate_op = self._ensure_direct_rotation_op(
                stage,
                target_prim,
                axis_name,
            )
        else:
            rotate_op = self._ensure_motion_ops(
                stage,
                target_prim,
                resolution.pivot,
                axis_name,
            )
        return _MotionBinding(
            stage_id=id(stage),
            target_path=str(target_prim.GetPath()),
            mesh_path=self.mesh_path,
            pivot=resolution.pivot,
            axis_name=axis_name,
            rotate_op=rotate_op,
            uses_authored_origin=uses_authored_origin,
        )

    def _resolve_target_prim(self, stage: object, mesh_prim: object) -> object:
        if self.rotation_target_path:
            target_prim = stage.GetPrimAtPath(self.rotation_target_path)
            if not target_prim or not target_prim.IsValid():
                raise ValueError(
                    f"Motion target not found: {self.rotation_target_path}"
                )
            return target_prim
        target_prim = mesh_prim.GetParent()
        if not target_prim or not target_prim.IsValid():
            return mesh_prim
        return target_prim

    def _configured_axis(self) -> str:
        if self.rotation_axis in {"X", "Y", "Z"}:
            return self.rotation_axis
        raise ValueError(
            f"Motion binding {self.mesh_path} requires rotation_axis for "
            f"{self.pivot_mode} pivot mode."
        )

    def _ensure_direct_rotation_op(
        self,
        stage: object,
        target_prim: object,
        axis_name: str,
    ) -> object:
        from pxr import Usd, UsdGeom

        session_layer = stage.GetSessionLayer()
        edit_target = stage.GetEditTargetForLocalLayer(session_layer)
        with Usd.EditContext(stage, edit_target):
            xformable = UsdGeom.Xformable(target_prim)
            ops = list(xformable.GetOrderedXformOps())
            rotate_name = f"xformOp:rotate{axis_name}:{self.ROTATE_OP_SUFFIX}"
            rotate_op = _find_op(ops, rotate_name)
            if rotate_op is None:
                rotate_op = _add_rotate_op(xformable, axis_name, self.ROTATE_OP_SUFFIX)
                ops.append(rotate_op)
            xformable.SetXformOpOrder(_dedupe_ops(ops))
            return rotate_op

    def _ensure_motion_ops(
        self,
        stage: object,
        target_prim: object,
        pivot: Vector3,
        axis_name: str,
    ) -> object:
        from pxr import Gf, Usd, UsdGeom

        session_layer = stage.GetSessionLayer()
        edit_target = stage.GetEditTargetForLocalLayer(session_layer)
        with Usd.EditContext(stage, edit_target):
            xformable = UsdGeom.Xformable(target_prim)
            ops = list(xformable.GetOrderedXformOps())
            pivot_name = f"xformOp:translate:{self.PIVOT_OP_SUFFIX}"
            rotate_name = f"xformOp:rotate{axis_name}:{self.ROTATE_OP_SUFFIX}"
            inverse_pivot_name = f"!invert!{pivot_name}"

            pivot_op = _find_op(ops, pivot_name)
            if pivot_op is None:
                pivot_op = xformable.AddTranslateOp(opSuffix=self.PIVOT_OP_SUFFIX)
                ops.append(pivot_op)
            pivot_op.Set(Gf.Vec3d(*pivot))

            rotate_op = _find_op(ops, rotate_name)
            if rotate_op is None:
                rotate_op = _add_rotate_op(xformable, axis_name, self.ROTATE_OP_SUFFIX)
                ops.append(rotate_op)

            inverse_pivot_op = _find_op(ops, inverse_pivot_name)
            if inverse_pivot_op is None:
                inverse_pivot_op = xformable.AddTranslateOp(
                    opSuffix=self.PIVOT_OP_SUFFIX,
                    isInverseOp=True,
                )
                ops.append(inverse_pivot_op)

            xformable.SetXformOpOrder(_dedupe_ops(ops))
            return rotate_op

    def _set_rotation(
        self, stage: object, binding: _MotionBinding, angle: float
    ) -> None:
        from pxr import Usd

        session_layer = stage.GetSessionLayer()
        edit_target = stage.GetEditTargetForLocalLayer(session_layer)
        with Usd.EditContext(stage, edit_target):
            binding.rotate_op.Set(float(angle))

    def _warn_once(self, message: str) -> None:
        if message in self._warned_messages:
            return
        self._warned_messages.add(message)
        try:
            import carb

            carb.log_warn(f"Blackwell motion: {message}")
        except Exception:  # noqa: BLE001
            return


class MultiRotationMotionController:
    """Drive every configured fan or blower rotation binding."""

    def __init__(self, bindings: Sequence[object] = ()) -> None:
        self.controllers = tuple(
            RotationMotionController(
                mesh_path=binding.mesh_path,
                rotation_target_path=binding.rotation_target_path,
                rotation_axis=binding.rotation_axis,
                pivot_mode=binding.pivot_mode,
                metric_id=binding.metric_id,
                rpm_mapper=VisualRpmMapper(
                    telemetry_min_rpm=binding.telemetry_min_rpm,
                    telemetry_max_rpm=binding.telemetry_max_rpm,
                    visual_min_rpm=binding.visual_min_rpm,
                    visual_max_rpm=binding.visual_max_rpm,
                ),
            )
            for binding in bindings
        )

    def reset(self) -> None:
        for controller in self.controllers:
            controller.reset()

    def update(self, stage: object | None, snapshot: object | None, now: float) -> None:
        for controller in self.controllers:
            controller.update(stage, snapshot, now)


def _find_op(ops: Iterable[object], name: str) -> object | None:
    for op in ops:
        if op.GetOpName() == name:
            return op
    return None


def _add_rotate_op(xformable: object, axis_name: str, suffix: str) -> object:
    if axis_name == "X":
        return xformable.AddRotateXOp(opSuffix=suffix)
    if axis_name == "Y":
        return xformable.AddRotateYOp(opSuffix=suffix)
    if axis_name == "Z":
        return xformable.AddRotateZOp(opSuffix=suffix)
    raise ValueError(f"Unsupported rotation axis: {axis_name}")


def _dedupe_ops(ops: Sequence[object]) -> list[object]:
    seen: set[str] = set()
    ordered: list[object] = []
    for op in ops:
        name = op.GetOpName()
        if name in seen:
            continue
        seen.add(name)
        ordered.append(op)
    return ordered


def _stage_has_prim(stage: object, path: str) -> bool:
    prim = stage.GetPrimAtPath(path)
    return bool(prim and prim.IsValid())


def _to_vector3(value: Sequence[float]) -> Vector3:
    return (float(value[0]), float(value[1]), float(value[2]))


def _bounds(points: Sequence[Sequence[float]]) -> tuple[Vector3, Vector3]:
    vectors = [_to_vector3(point) for point in points]
    return (
        tuple(min(point[index] for point in vectors) for index in range(3)),
        tuple(max(point[index] for point in vectors) for index in range(3)),
    )


def _mean_position(points: Iterable[Vector3]) -> Vector3:
    values = list(points)
    if not values:
        raise ValueError("Cannot average an empty point set.")
    return tuple(
        sum(point[index] for point in values) / len(values) for index in range(3)
    )


def _dominant_axis(candidates: Sequence[PivotCandidate]) -> str:
    ranges = []
    for index in range(3):
        values = [candidate.position[index] for candidate in candidates]
        ranges.append(max(values) - min(values))
    axis_index = max(range(3), key=lambda index: ranges[index])
    return ("X", "Y", "Z")[axis_index]


def _axis_vector(axis_name: str) -> Vector3:
    if axis_name == "X":
        return (1.0, 0.0, 0.0)
    if axis_name == "Y":
        return (0.0, 1.0, 0.0)
    if axis_name == "Z":
        return (0.0, 0.0, 1.0)
    raise ValueError(f"Unsupported rotation axis: {axis_name}")


def _pivot_axis_is_near_origin(
    pivot: Vector3,
    axis_name: str,
    tolerance: float,
) -> bool:
    if axis_name == "X":
        distances = (abs(pivot[1]), abs(pivot[2]))
    elif axis_name == "Y":
        distances = (abs(pivot[0]), abs(pivot[2]))
    elif axis_name == "Z":
        distances = (abs(pivot[0]), abs(pivot[1]))
    else:
        raise ValueError(f"Unsupported rotation axis: {axis_name}")
    return max(distances) <= tolerance


def _distance(left: Vector3, right: Vector3) -> float:
    return math.sqrt(sum((left[index] - right[index]) ** 2 for index in range(3)))
