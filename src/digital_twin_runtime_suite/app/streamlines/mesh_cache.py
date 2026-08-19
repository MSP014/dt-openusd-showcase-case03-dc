"""Prebaked fixed-topology Mesh cache derived from persisted centerlines."""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from digital_twin_runtime_suite.app.streamlines.constant_topology import (
    SOURCE_CURVE_VERTEX_COUNTS_ATTRIBUTE,
)
from digital_twin_runtime_suite.app.streamlines.mesh_conversion import (
    SOURCE_POINT_INDEX_ATTRIBUTE,
    build_streamlines_tube_mesh_topology,
    convert_streamlines_centerlines_to_tube_mesh,
)

MESH_CACHE_SCHEMA_VERSION = 1
MESH_CACHE_FILE_NAME = "streamlines_mesh_prototype.usdc"
MESH_CACHE_METADATA_FILE_NAME = "streamlines_mesh_prototype.json"
MESH_CACHE_ROOT_PATH = "/DTRS_StreamlinesCachePlayback"
MESH_CACHE_SOURCE_PATH = f"{MESH_CACHE_ROOT_PATH}/Source"
MESH_CACHE_GEOMETRY_PATH = f"{MESH_CACHE_ROOT_PATH}/Geometry"
MESH_SPEED_ATTRIBUTE = "primvars:dtrs:speed"
MESH_SOURCE_TIME_ATTRIBUTE = "dtrs:sourceTime"
PROTOTYPE_PROFILE_ID = "volume_coverage"
PROTOTYPE_WORKLOAD = "Nominal"
PROTOTYPE_CURVE_COUNT = 6_144
PROTOTYPE_POINTS_PER_CURVE = 20
PROTOTYPE_SAMPLE_COUNT = 80


@dataclass(frozen=True)
class StreamlinesMeshStateReceipt:
    """Compact proof for one renderer Mesh temporal state."""

    sample_index: int
    time_code: float
    source_time_seconds: float
    source_points_sha256: str
    mesh_points_sha256: str
    mesh_point_count: int
    mesh_speed_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "sample_index": self.sample_index,
            "time_code": self.time_code,
            "source_time_seconds": self.source_time_seconds,
            "source_points_sha256": self.source_points_sha256,
            "mesh_points_sha256": self.mesh_points_sha256,
            "mesh_point_count": self.mesh_point_count,
            "mesh_speed_count": self.mesh_speed_count,
        }

    @classmethod
    def from_dict(cls, value: object) -> "StreamlinesMeshStateReceipt":
        if not isinstance(value, dict):
            raise ValueError("Mesh cache state receipt must be an object.")
        return cls(
            sample_index=int(value["sample_index"]),
            time_code=float(value["time_code"]),
            source_time_seconds=float(value["source_time_seconds"]),
            source_points_sha256=str(value["source_points_sha256"]),
            mesh_points_sha256=str(value["mesh_points_sha256"]),
            mesh_point_count=int(value["mesh_point_count"]),
            mesh_speed_count=int(value["mesh_speed_count"]),
        )


@dataclass(frozen=True)
class StreamlinesMeshCacheReceipt:
    """Versioned identity and structural proof for one Mesh prototype."""

    schema_version: int
    state: str
    workload: str
    dataset_identity: str
    profile_id: str
    source_geometry_path: str
    source_geometry_sha256: str
    mesh_geometry_sha256: str
    curve_count: int
    centerline_points_per_curve: int
    mesh_point_count: int
    triangle_count: int
    side_count: int
    sample_count: int
    build_seconds: float
    states: tuple[StreamlinesMeshStateReceipt, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "state": self.state,
            "workload": self.workload,
            "dataset_identity": self.dataset_identity,
            "profile_id": self.profile_id,
            "source_geometry_path": self.source_geometry_path,
            "source_geometry_sha256": self.source_geometry_sha256,
            "mesh_geometry_sha256": self.mesh_geometry_sha256,
            "curve_count": self.curve_count,
            "centerline_points_per_curve": self.centerline_points_per_curve,
            "mesh_point_count": self.mesh_point_count,
            "triangle_count": self.triangle_count,
            "side_count": self.side_count,
            "sample_count": self.sample_count,
            "build_seconds": self.build_seconds,
            "states": [state.to_dict() for state in self.states],
        }

    @classmethod
    def from_dict(cls, value: object) -> "StreamlinesMeshCacheReceipt":
        if not isinstance(value, dict):
            raise ValueError("Mesh cache receipt must be an object.")
        raw_states = value.get("states")
        if not isinstance(raw_states, list):
            raise ValueError("Mesh cache receipt states must be a list.")
        return cls(
            schema_version=int(value["schema_version"]),
            state=str(value["state"]),
            workload=str(value["workload"]),
            dataset_identity=str(value["dataset_identity"]),
            profile_id=str(value["profile_id"]),
            source_geometry_path=str(value["source_geometry_path"]),
            source_geometry_sha256=str(value["source_geometry_sha256"]),
            mesh_geometry_sha256=str(value["mesh_geometry_sha256"]),
            curve_count=int(value["curve_count"]),
            centerline_points_per_curve=int(value["centerline_points_per_curve"]),
            mesh_point_count=int(value["mesh_point_count"]),
            triangle_count=int(value["triangle_count"]),
            side_count=int(value["side_count"]),
            sample_count=int(value["sample_count"]),
            build_seconds=float(value["build_seconds"]),
            states=tuple(
                StreamlinesMeshStateReceipt.from_dict(item) for item in raw_states
            ),
        )


def mesh_cache_paths(source_geometry_path: Path) -> tuple[Path, Path]:
    """Return prototype geometry and receipt paths beside the source cache."""

    directory = source_geometry_path.parent
    return (
        directory / MESH_CACHE_FILE_NAME,
        directory / MESH_CACHE_METADATA_FILE_NAME,
    )


def build_streamlines_mesh_prototype_cache(
    source_geometry_path: Path,
    source_metadata,
) -> StreamlinesMeshCacheReceipt:
    """Prebake the sole Volume/Nominal prototype from existing centerlines."""

    from pxr import Sdf, Usd, UsdGeom, Vt

    _require_prototype_source(source_metadata)
    geometry_path, metadata_path = mesh_cache_paths(source_geometry_path)
    geometry_path.parent.mkdir(parents=True, exist_ok=True)
    partial_geometry = geometry_path.with_suffix(".partial.usdc")
    partial_metadata = metadata_path.with_suffix(".partial.json")
    for path in (partial_geometry, partial_metadata):
        if path.exists():
            path.unlink()

    started = time.perf_counter()
    source_stage = Usd.Stage.Open(str(source_geometry_path))
    if source_stage is None:
        raise RuntimeError("Source centerline cache could not be opened.")
    source_curves = source_stage.GetPrimAtPath(MESH_CACHE_GEOMETRY_PATH)
    if not source_curves or not source_curves.IsValid():
        raise RuntimeError("Source centerline BasisCurves is unavailable.")

    topology = build_streamlines_tube_mesh_topology(
        curve_count=PROTOTYPE_CURVE_COUNT,
        centerline_points_per_curve=PROTOTYPE_POINTS_PER_CURVE,
    )
    target = Usd.Stage.CreateNew(str(partial_geometry))
    target.SetTimeCodesPerSecond(float(source_metadata.time_codes_per_second))
    target.SetStartTimeCode(float(source_metadata.states[0].time_code))
    target.SetEndTimeCode(float(source_metadata.states[-1].time_code))
    root = UsdGeom.Xform.Define(target, MESH_CACHE_ROOT_PATH)
    target.SetDefaultPrim(root.GetPrim())
    source = UsdGeom.Xform.Define(target, MESH_CACHE_SOURCE_PATH)
    source.GetPrim().GetReferences().AddReference(
        str(source_geometry_path.resolve()),
        Sdf.Path(MESH_CACHE_ROOT_PATH),
    )
    UsdGeom.Imageable(source.GetPrim()).MakeInvisible()
    mesh = UsdGeom.Mesh.Define(target, MESH_CACHE_GEOMETRY_PATH)
    mesh.CreateSubdivisionSchemeAttr().Set(UsdGeom.Tokens.none)
    mesh.CreateFaceVertexCountsAttr().Set(
        Vt.IntArray.FromNumpy(topology.face_vertex_counts)
    )
    mesh.CreateFaceVertexIndicesAttr().Set(
        Vt.IntArray.FromNumpy(topology.face_vertex_indices)
    )
    mesh.GetPrim().CreateAttribute(
        SOURCE_POINT_INDEX_ATTRIBUTE,
        Sdf.ValueTypeNames.IntArray,
    ).Set(Vt.IntArray.FromNumpy(topology.source_point_indices))
    speed_attr = mesh.GetPrim().CreateAttribute(
        MESH_SPEED_ATTRIBUTE,
        Sdf.ValueTypeNames.FloatArray,
    )
    speed_attr.SetMetadata("interpolation", "vertex")
    source_time_attr = mesh.GetPrim().CreateAttribute(
        MESH_SOURCE_TIME_ATTRIBUTE,
        Sdf.ValueTypeNames.Double,
    )

    width = float(source_metadata.settings.width)
    if not math.isfinite(width) or width <= 0.0:
        raise ValueError("Source centerline width is invalid.")
    states = []
    first_mesh_hash = None
    for source_state in source_metadata.states:
        time_code = Usd.TimeCode(float(source_state.time_code))
        centerline_points = np.asarray(
            source_curves.GetAttribute("points").Get(time_code),
            dtype=np.float32,
        )
        curve_counts = np.asarray(
            source_curves.GetAttribute("curveVertexCounts").Get(time_code),
            dtype=np.int32,
        )
        source_counts = np.asarray(
            source_curves.GetAttribute(SOURCE_CURVE_VERTEX_COUNTS_ATTRIBUTE).Get(
                time_code
            ),
            dtype=np.int32,
        )
        speeds = np.asarray(
            source_curves.GetAttribute(MESH_SPEED_ATTRIBUTE).Get(time_code),
            dtype=np.float32,
        )
        converted = convert_streamlines_centerlines_to_tube_mesh(
            centerline_points,
            curve_counts,
            source_counts,
            speeds,
            radius=width * 0.5,
            topology=topology,
        )
        mesh.CreatePointsAttr().Set(
            Vt.Vec3fArray.FromNumpy(converted.points),
            time_code,
        )
        mesh.CreateExtentAttr().Set(
            Vt.Vec3fArray.FromNumpy(converted.extent),
            time_code,
        )
        speed_attr.Set(Vt.FloatArray.FromNumpy(converted.speeds), time_code)
        source_time_attr.Set(float(source_state.source_time_seconds), time_code)
        source_hash = _array_sha256(centerline_points)
        mesh_hash = _array_sha256(converted.points)
        if first_mesh_hash is None:
            first_mesh_hash = mesh_hash
        states.append(
            StreamlinesMeshStateReceipt(
                sample_index=source_state.sample_index,
                time_code=float(source_state.time_code),
                source_time_seconds=float(source_state.source_time_seconds),
                source_points_sha256=source_hash,
                mesh_points_sha256=mesh_hash,
                mesh_point_count=len(converted.points),
                mesh_speed_count=len(converted.speeds),
            )
        )
    target.GetRootLayer().Save()
    os.replace(partial_geometry, geometry_path)
    receipt = StreamlinesMeshCacheReceipt(
        schema_version=MESH_CACHE_SCHEMA_VERSION,
        state="VALID",
        workload=source_metadata.workload,
        dataset_identity=source_metadata.dataset_identity,
        profile_id=source_metadata.profile_id,
        source_geometry_path=str(source_geometry_path.resolve()),
        source_geometry_sha256=_file_sha256(source_geometry_path),
        mesh_geometry_sha256=_file_sha256(geometry_path),
        curve_count=topology.curve_count,
        centerline_points_per_curve=topology.centerline_points_per_curve,
        mesh_point_count=topology.point_count,
        triangle_count=len(topology.face_vertex_counts),
        side_count=topology.side_count,
        sample_count=len(states),
        build_seconds=time.perf_counter() - started,
        states=tuple(states),
    )
    partial_metadata.write_text(
        json.dumps(receipt.to_dict(), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(partial_metadata, metadata_path)
    validate_streamlines_mesh_prototype_cache(
        geometry_path,
        receipt,
        source_geometry_path=source_geometry_path,
    )
    return receipt


def load_streamlines_mesh_cache_receipt(
    metadata_path: Path,
) -> StreamlinesMeshCacheReceipt:
    """Read one local Mesh prototype receipt without touching geometry."""

    return StreamlinesMeshCacheReceipt.from_dict(
        json.loads(metadata_path.read_text(encoding="utf-8"))
    )


def validate_streamlines_mesh_prototype_cache(
    geometry_path: Path,
    receipt: StreamlinesMeshCacheReceipt,
    *,
    source_geometry_path: Path,
    verify_file_hash: bool = True,
) -> None:
    """Validate the complete prototype before any renderer attachment."""

    from pxr import Usd

    _validate_receipt_identity(receipt, source_geometry_path)
    if verify_file_hash:
        if _file_sha256(source_geometry_path) != receipt.source_geometry_sha256:
            raise ValueError("Mesh cache source artifact changed.")
        if _file_sha256(geometry_path) != receipt.mesh_geometry_sha256:
            raise ValueError("Mesh cache artifact hash differs from its receipt.")
    stage = Usd.Stage.Open(str(geometry_path))
    if stage is None:
        raise ValueError("Mesh cache could not be opened.")
    meshes = [prim for prim in stage.Traverse() if prim.GetTypeName() == "Mesh"]
    if len(meshes) != 1 or meshes[0].GetPath() != MESH_CACHE_GEOMETRY_PATH:
        raise ValueError("Mesh cache must contain exactly one renderer Mesh.")
    mesh = meshes[0]
    counts_attr = mesh.GetAttribute("faceVertexCounts")
    indices_attr = mesh.GetAttribute("faceVertexIndices")
    mapping_attr = mesh.GetAttribute(SOURCE_POINT_INDEX_ATTRIBUTE)
    if (
        counts_attr.GetTimeSamples()
        or indices_attr.GetTimeSamples()
        or mapping_attr.GetTimeSamples()
    ):
        raise ValueError("Mesh topology must be authored only at default time.")
    counts = np.asarray(counts_attr.Get(), dtype=np.int32)
    indices = np.asarray(indices_attr.Get(), dtype=np.int64)
    mapping = np.asarray(mapping_attr.Get(), dtype=np.int64)
    if len(counts) != receipt.triangle_count or not np.all(counts == 3):
        raise ValueError("Mesh static face counts are invalid.")
    if len(indices) != int(counts.sum()):
        raise ValueError("Mesh static face arrays are inconsistent.")
    if indices.min(initial=0) < 0 or indices.max(initial=-1) >= len(mapping):
        raise ValueError("Mesh static topology has an out-of-range face index.")
    source_point_count = receipt.curve_count * receipt.centerline_points_per_curve
    if (
        len(mapping) != receipt.mesh_point_count
        or mapping.min(initial=0) < 0
        or mapping.max(initial=-1) >= source_point_count
    ):
        raise ValueError("Mesh source-point mapping is invalid.")
    points_attr = mesh.GetAttribute("points")
    speed_attr = mesh.GetAttribute(MESH_SPEED_ATTRIBUTE)
    extent_attr = mesh.GetAttribute("extent")
    source_time_attr = mesh.GetAttribute(MESH_SOURCE_TIME_ATTRIBUTE)
    time_samples = points_attr.GetTimeSamples()
    if len(time_samples) != receipt.sample_count:
        raise ValueError("Mesh cache temporal sample count is incomplete.")
    if speed_attr.GetTimeSamples() != time_samples:
        raise ValueError("Mesh speed samples are not aligned with points.")
    if extent_attr.GetTimeSamples() != time_samples:
        raise ValueError("Mesh extent samples are not aligned with points.")
    if source_time_attr.GetTimeSamples() != time_samples:
        raise ValueError("Mesh source-time samples are not aligned with points.")
    observed_hashes = []
    for state in receipt.states:
        time_code = Usd.TimeCode(state.time_code)
        points = np.asarray(points_attr.Get(time_code), dtype=np.float32)
        speeds = np.asarray(speed_attr.Get(time_code), dtype=np.float32)
        extent = np.asarray(extent_attr.Get(time_code), dtype=np.float32)
        if len(points) != receipt.mesh_point_count:
            raise ValueError("Mesh temporal point count drifted.")
        if len(speeds) != len(points):
            raise ValueError("Mesh temporal speed count differs from points.")
        if extent.shape != (2, 3):
            raise ValueError("Mesh temporal extent is invalid.")
        if not np.isfinite(points).all() or not np.isfinite(speeds).all():
            raise ValueError("Mesh temporal state contains non-finite values.")
        actual_hash = _array_sha256(points)
        if actual_hash != state.mesh_points_sha256:
            raise ValueError("Mesh temporal points differ from their receipt.")
        observed_hashes.append(actual_hash)
    representative = [observed_hashes[index] for index in (0, 1, 2, 10, 79)]
    if len(set(representative)) < 2:
        raise ValueError("Mesh temporal geometry is static.")


def mesh_points_signature_at_time(
    geometry_path: Path,
    time_code: float,
) -> tuple[str, int]:
    """Return a debug-only persisted Mesh points signature."""

    from pxr import Usd

    stage = Usd.Stage.Open(str(geometry_path))
    if stage is None:
        raise ValueError("Mesh cache could not be opened.")
    points = np.asarray(
        stage.GetPrimAtPath(MESH_CACHE_GEOMETRY_PATH)
        .GetAttribute("points")
        .Get(Usd.TimeCode(time_code)),
        dtype=np.float32,
    )
    return _array_sha256(points), len(points)


def _require_prototype_source(metadata) -> None:
    if (
        metadata.workload != PROTOTYPE_WORKLOAD
        or metadata.profile_id != PROTOTYPE_PROFILE_ID
        or metadata.sample_count != PROTOTYPE_SAMPLE_COUNT
        or not metadata.topology_consistent
    ):
        raise ValueError(
            "Only the valid Volume Coverage / Nominal prototype is allowed."
        )
    if metadata.settings is None:
        raise ValueError("Source centerline settings are unavailable.")


def _validate_receipt_identity(
    receipt: StreamlinesMeshCacheReceipt,
    source_geometry_path: Path,
) -> None:
    if receipt.schema_version != MESH_CACHE_SCHEMA_VERSION:
        raise ValueError("Mesh cache schema is incompatible.")
    if receipt.state != "VALID":
        raise ValueError("Mesh cache is not VALID.")
    if (
        receipt.workload != PROTOTYPE_WORKLOAD
        or receipt.profile_id != PROTOTYPE_PROFILE_ID
        or receipt.curve_count != PROTOTYPE_CURVE_COUNT
        or receipt.centerline_points_per_curve != PROTOTYPE_POINTS_PER_CURVE
        or receipt.sample_count != PROTOTYPE_SAMPLE_COUNT
    ):
        raise ValueError("Mesh cache prototype identity is incompatible.")
    if Path(receipt.source_geometry_path) != source_geometry_path.resolve():
        raise ValueError("Mesh cache source path differs from its receipt.")


def _array_sha256(values: np.ndarray) -> str:
    canonical = np.ascontiguousarray(values, dtype=np.float32)
    return hashlib.sha256(canonical.tobytes()).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
