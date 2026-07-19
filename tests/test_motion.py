from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from blackwell_monitoring_suite.app.motion import (
    MultiRotationMotionController,
    RotationMotionController,
    TopologyPivotResolver,
    VisualRpmMapper,
)


def test_visual_rpm_mapping_clamps_and_interpolates():
    mapper = VisualRpmMapper(
        telemetry_min_rpm=650.0,
        telemetry_max_rpm=2300.0,
        visual_min_rpm=40.0,
        visual_max_rpm=360.0,
    )

    assert mapper.map(400.0) == pytest.approx(40.0)
    assert mapper.map(2300.0) == pytest.approx(360.0)
    assert mapper.map(3000.0) == pytest.approx(360.0)
    assert mapper.map(1475.0) == pytest.approx(200.0)


def test_topology_resolver_finds_hub_pivot_and_axis_from_high_valence_poles():
    points, counts, indices = _make_synthetic_fan_hub(centre=(0.4, -0.25, 2.0))

    resolution = TopologyPivotResolver().resolve(points, counts, indices)

    assert resolution.axis_name == "Z"
    assert resolution.axis == pytest.approx((0.0, 0.0, 1.0))
    assert resolution.pivot == pytest.approx((0.4, -0.25, 2.0))
    assert {candidate.valence for candidate in resolution.candidates} == {64}
    assert len(resolution.candidates) == 4


def test_rotation_controller_uses_authored_origin_when_axis_is_valid():
    from pxr import Gf, UsdGeom

    stage = _make_stage_with_synthetic_fan(
        centre=(0.0, 0.0, 2.0),
        parent_translation=(1.0, 2.0, 0.0),
    )
    parent_path = RotationMotionController.DEFAULT_MESH_PATH.rsplit("/", 1)[0]

    root_before = stage.GetRootLayer().ExportToString()
    controller = RotationMotionController()
    snapshot = SimpleNamespace(metrics={"cpu_fan_rpm": SimpleNamespace(value=1475.0)})

    controller.update(stage, snapshot, 10.0)
    controller.update(stage, snapshot, 10.1)

    root_after = stage.GetRootLayer().ExportToString()
    session_text = stage.GetSessionLayer().ExportToString()

    assert root_after == root_before
    assert "xformOp:rotateZ:mspMotionSpin" in session_text
    assert "xformOp:translate:mspMotionPivot" not in session_text
    assert "!invert!xformOp:translate:mspMotionPivot" not in session_text
    assert controller.angle_degrees == pytest.approx(120.0)

    transform = UsdGeom.Xformable(stage.GetPrimAtPath(parent_path))
    matrix = transform.GetLocalTransformation()
    transformed_origin = matrix.Transform(Gf.Vec3d(0.0, 0.0, 0.0))
    assert tuple(transformed_origin) == pytest.approx((1.0, 2.0, 0.0))


def test_rotation_controller_falls_back_to_runtime_pivot_stack():
    from pxr import Gf, UsdGeom

    stage = _make_stage_with_synthetic_fan(centre=(0.4, -0.25, 2.0))
    parent_path = RotationMotionController.DEFAULT_MESH_PATH.rsplit("/", 1)[0]

    root_before = stage.GetRootLayer().ExportToString()
    controller = RotationMotionController()
    snapshot = SimpleNamespace(metrics={"cpu_fan_rpm": SimpleNamespace(value=1475.0)})

    controller.update(stage, snapshot, 10.0)
    controller.update(stage, snapshot, 10.1)

    root_after = stage.GetRootLayer().ExportToString()
    session_text = stage.GetSessionLayer().ExportToString()

    assert root_after == root_before
    assert "xformOp:translate:mspMotionPivot" in session_text
    assert "xformOp:rotateZ:mspMotionSpin" in session_text
    assert "!invert!xformOp:translate:mspMotionPivot" in session_text
    assert controller.angle_degrees == pytest.approx(120.0)

    transform = UsdGeom.Xformable(stage.GetPrimAtPath(parent_path))
    matrix = transform.GetLocalTransformation()
    transformed_pivot = matrix.Transform(Gf.Vec3d(0.4, -0.25, 2.0))
    assert tuple(transformed_pivot) == pytest.approx((0.4, -0.25, 2.0))


def test_rotation_controller_reacquires_binding_when_stage_changes():
    stage_one = _make_stage_with_synthetic_fan(centre=(0.0, 0.0, 0.0))
    stage_two = _make_stage_with_synthetic_fan(centre=(0.4, -0.25, 2.0))
    controller = RotationMotionController()
    snapshot = SimpleNamespace(metrics={"cpu_fan_rpm": SimpleNamespace(value=1475.0)})

    controller.update(stage_one, snapshot, 10.0)
    controller.update(stage_one, snapshot, 10.1)
    controller.update(stage_two, snapshot, 10.2)
    controller.update(stage_two, snapshot, 10.3)

    assert "mspMotionSpin" in stage_two.GetSessionLayer().ExportToString()


def test_rotation_controller_uses_explicit_authored_target_and_axis():
    stage = _make_stage_with_synthetic_fan(centre=(0.0, 0.0, 0.0))
    target_path = RotationMotionController.DEFAULT_MESH_PATH.rsplit("/", 1)[0]
    controller = RotationMotionController(
        rotation_target_path=target_path,
        rotation_axis="X",
        pivot_mode="authored_origin",
    )
    snapshot = SimpleNamespace(metrics={"cpu_fan_rpm": SimpleNamespace(value=1475.0)})

    controller.update(stage, snapshot, 10.0)
    controller.update(stage, snapshot, 10.1)

    session_text = stage.GetSessionLayer().ExportToString()
    assert "xformOp:rotateX:mspMotionSpin" in session_text
    assert "xformOp:rotateZ:mspMotionSpin" not in session_text
    assert "xformOp:translate:mspMotionPivot" not in session_text


def test_multi_rotation_controller_drives_configured_bindings():
    stage = _make_stage_with_synthetic_fan(centre=(0.0, 0.0, 0.0))
    target_path = RotationMotionController.DEFAULT_MESH_PATH.rsplit("/", 1)[0]
    binding = SimpleNamespace(
        mesh_path=RotationMotionController.DEFAULT_MESH_PATH,
        rotation_target_path=target_path,
        rotation_axis="Y",
        pivot_mode="authored_origin",
        metric_id="cpu_fan_rpm",
        telemetry_min_rpm=650.0,
        telemetry_max_rpm=2300.0,
        visual_min_rpm=40.0,
        visual_max_rpm=360.0,
    )
    controller = MultiRotationMotionController((binding,))
    snapshot = SimpleNamespace(metrics={"cpu_fan_rpm": SimpleNamespace(value=1475.0)})

    controller.update(stage, snapshot, 10.0)
    controller.update(stage, snapshot, 10.1)

    assert "xformOp:rotateY:mspMotionSpin" in stage.GetSessionLayer().ExportToString()


def _make_stage_with_synthetic_fan(
    *,
    centre: tuple[float, float, float],
    parent_translation: tuple[float, float, float] | None = None,
):
    from pxr import Gf, Usd, UsdGeom, Vt

    stage = Usd.Stage.CreateInMemory()
    mesh_path = RotationMotionController.DEFAULT_MESH_PATH
    parent_path = mesh_path.rsplit("/", 1)[0]
    parent = UsdGeom.Xform.Define(stage, parent_path)
    if parent_translation is not None:
        transform_op = parent.AddTransformOp()
        transform_op.Set(Gf.Matrix4d().SetTranslate(Gf.Vec3d(*parent_translation)))

    points, counts, indices = _make_synthetic_fan_hub(centre=centre)
    mesh = UsdGeom.Mesh.Define(stage, mesh_path)
    mesh.GetPointsAttr().Set(Vt.Vec3fArray(points))
    mesh.GetFaceVertexCountsAttr().Set(counts)
    mesh.GetFaceVertexIndicesAttr().Set(indices)
    return stage


def _make_synthetic_fan_hub(
    *,
    segments: int = 64,
    centre: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> tuple[list[tuple[float, float, float]], list[int], list[int]]:
    points: list[tuple[float, float, float]] = []
    counts: list[int] = []
    indices: list[int] = []
    radius = 0.2

    cx, cy, cz = centre

    for z_offset in (-1.0, -0.5, 0.5, 1.0):
        z = cz + z_offset
        pole_index = len(points)
        points.append((cx, cy, z))
        ring_start = len(points)
        for segment in range(segments):
            angle = (math.tau * segment) / segments
            points.append(
                (
                    cx + (math.cos(angle) * radius),
                    cy + (math.sin(angle) * radius),
                    z,
                )
            )
        for segment in range(segments):
            counts.append(3)
            indices.extend(
                [
                    pole_index,
                    ring_start + segment,
                    ring_start + ((segment + 1) % segments),
                ]
            )

    points.extend([(1.4, 0.2, 0.1), (1.8, 0.1, 0.0), (1.5, -0.2, -0.1)])
    counts.append(3)
    indices.extend([len(points) - 3, len(points) - 2, len(points) - 1])
    return points, counts, indices
