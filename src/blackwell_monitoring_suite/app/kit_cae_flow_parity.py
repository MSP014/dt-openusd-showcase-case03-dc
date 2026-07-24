"""Read-only runtime snapshots for Kit-CAE Flow parity investigations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def capture_flow_scene(stage, *, label: str, paths: dict[str, str]) -> dict[str, Any]:
    """Capture effective USD state without serialising large Flow payloads."""

    from pxr import Usd, UsdGeom

    def json_value(value):
        if value is None or isinstance(value, (bool, int, float, str)):
            return value
        if hasattr(value, "pathString"):
            return value.pathString
        if hasattr(value, "GetAssetPath"):
            return value.GetAssetPath()
        try:
            length = len(value)
        except TypeError:
            length = None
        if length is not None:
            if length > 64:
                return {"type": type(value).__name__, "count": length}
            return [json_value(item) for item in value]
        try:
            return [json_value(value[index]) for index in range(3)]
        except (IndexError, TypeError):
            return str(value)

    def attribute_snapshot(attribute):
        return {
            "type": str(attribute.GetTypeName()),
            "authored": attribute.HasAuthoredValueOpinion(),
            "value": json_value(attribute.Get(Usd.TimeCode.Default())),
        }

    def prim_snapshot(prim):
        if not prim or not prim.IsValid():
            return None
        xform_ops = []
        if prim.IsA(UsdGeom.Xformable):
            for op in UsdGeom.Xformable(prim).GetOrderedXformOps():
                xform_ops.append(
                    {
                        "name": op.GetOpName(),
                        "type": str(op.GetOpType()),
                        "value": json_value(op.Get(Usd.TimeCode.Default())),
                    }
                )
        return {
            "prim_path": str(prim.GetPath()),
            "prim_type": str(prim.GetTypeName()),
            "applied_schemas": sorted(prim.GetAppliedSchemas()),
            "attributes": {
                attribute.GetName(): attribute_snapshot(attribute)
                for attribute in sorted(
                    prim.GetAttributes(), key=lambda item: item.GetName()
                )
            },
            "relationships": {
                relationship.GetName(): [
                    str(target) for target in relationship.GetTargets()
                ]
                for relationship in sorted(
                    prim.GetRelationships(), key=lambda item: item.GetName()
                )
            },
            "xform_ops": xform_ops,
        }

    roles = {
        role: prim_snapshot(stage.GetPrimAtPath(path))
        for role, path in paths.items()
        if role != "boundary_emitter_root"
    }
    boundary_root = stage.GetPrimAtPath(paths["boundary_emitter_root"])
    roles["boundary_emitters"] = (
        [
            prim_snapshot(prim)
            for prim in Usd.PrimRange(boundary_root)
            if prim.GetTypeName() == "FlowEmitterBox"
        ]
        if boundary_root and boundary_root.IsValid()
        else []
    )

    flow_simulate = stage.GetPrimAtPath(paths["flow_simulate"])
    runtime_names = ("activeBlocks", "maxBlocks", "simTime", "faultTime")
    runtime_diagnostics = {}
    for name in runtime_names:
        attribute = flow_simulate.GetAttribute(name) if flow_simulate else None
        runtime_diagnostics[name] = (
            json_value(attribute.Get(Usd.TimeCode.Default()))
            if attribute and attribute.IsValid()
            else None
        )

    return {
        "schema_version": 1,
        "label": label,
        "roles": roles,
        "runtime_diagnostics": runtime_diagnostics,
    }


def write_flow_snapshot(snapshot: dict[str, Any], output_path: Path) -> Path:
    """Write a deterministic JSON artifact into the ignored diagnostics folder."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(snapshot, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return output_path


def diff_flow_snapshots(
    reference: dict[str, Any], bms: dict[str, Any]
) -> dict[str, Any]:
    """Classify Flow state differences without comparing dataset ingestion."""

    expected_dataset_roles = {
        "dataset",
        "velocity_field",
        "bounding_box",
        "boundary_emitters",
    }
    expected_dataset_attributes = {
        "nanoVdbVelocities",
        "velocityScale",
        "densityCellSize",
    }

    def collect_differences(reference_value, bms_value, path=""):
        if isinstance(reference_value, dict) and isinstance(bms_value, dict):
            differences = []
            for key in sorted(set(reference_value) | set(bms_value)):
                if key == "prim_path":
                    continue
                child_path = f"{path}.{key}" if path else key
                differences.extend(
                    collect_differences(
                        reference_value.get(key),
                        bms_value.get(key),
                        child_path,
                    )
                )
            return differences
        if reference_value != bms_value:
            return [{"path": path, "reference": reference_value, "bms": bms_value}]
        return []

    expected = []
    suspicious = []
    reference_roles = reference.get("roles", {})
    bms_roles = bms.get("roles", {})
    for role in sorted(set(reference_roles) | set(bms_roles)):
        for difference in collect_differences(
            reference_roles.get(role),
            bms_roles.get(role),
            role,
        ):
            path = difference["path"]
            attribute_name = (
                path.split(".")[2] if path.startswith(f"{role}.attributes.") else ""
            )
            is_expected = (
                role in expected_dataset_roles
                or path.endswith(".xform_ops")
                or ".xform_ops." in path
                or ".relationships." in path
                or attribute_name in expected_dataset_attributes
            )
            (expected if is_expected else suspicious).append(difference)

    for difference in collect_differences(
        reference.get("runtime_diagnostics", {}),
        bms.get("runtime_diagnostics", {}),
        "runtime_diagnostics",
    ):
        suspicious.append(difference)

    return {
        "schema_version": 1,
        "reference_label": reference.get("label"),
        "bms_label": bms.get("label"),
        "EXPECTED_DATASET_DIFFERENCE": expected,
        "SUSPICIOUS_FLOW_DIFFERENCE": suspicious,
    }
