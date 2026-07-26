"""VTI, CAE, and spatial validation for the DTRS Flow route."""

from __future__ import annotations

import re
import time
from pathlib import Path


def read_kit_cae_vti_metadata(
    velocity_path: Path,
    field_name: str,
) -> dict[str, object]:
    """Read the VTI header through Kit-CAE's VTK runtime before Flow binds it."""

    from vtkmodules.vtkIOXML import vtkXMLImageDataReader

    header = velocity_path.read_bytes()[:16384].decode("utf-8", errors="ignore")
    header_match = re.search(r'<ImageData[^>]*\bOrigin="([^"]+)"', header)
    if header_match is None:
        raise RuntimeError("VTI ImageData header is missing its Origin attribute.")
    header_origin = tuple(float(value) for value in header_match.group(1).split())
    if len(header_origin) != 3:
        raise RuntimeError("VTI ImageData header Origin must have three components.")

    reader = vtkXMLImageDataReader()
    reader.SetFileName(str(velocity_path))
    reader.Update()
    image = reader.GetOutput()
    array = image.GetPointData().GetArray(field_name) if image else None
    if array is None:
        raise RuntimeError(f"VTI PointData array '{field_name}' was not found.")
    components = int(array.GetNumberOfComponents())
    data_type = str(array.GetDataTypeAsString()).lower()
    if components != 3:
        raise RuntimeError(
            f"VTI PointData/{field_name} must have 3 components, got {components}."
        )
    if data_type not in {"float", "float32"}:
        raise RuntimeError(
            f"VTI PointData/{field_name} must be float32, got {data_type}."
        )
    reader_origin = tuple(float(value) for value in image.GetOrigin())
    return {
        "components": components,
        "data_type": data_type,
        "dimensions": tuple(int(value) for value in image.GetDimensions()),
        "point_count": int(image.GetNumberOfPoints()),
        "origin": reader_origin,
        "vti_header_origin": header_origin,
        "vtk_reader_origin": reader_origin,
        "spacing": tuple(float(value) for value in image.GetSpacing()),
    }


async def wait_for_kit_cae_dataset_emitter_ready(
    app,
    dataset_emitter,
    *,
    timeout_seconds: float = 5.0,
    max_update_cycles: int = 300,
) -> dict[str, object]:
    """Wait for Kit-CAE to materialize its internal Flow velocity payload."""

    started_at = time.monotonic()
    cycles = 0

    def readiness() -> tuple[bool, int, float]:
        payload_attribute = dataset_emitter.GetAttribute("nanoVdbVelocities")
        payload = (
            payload_attribute.Get()
            if payload_attribute and payload_attribute.IsValid()
            else None
        )
        payload_count = len(payload) if payload is not None else 0
        couple_rate = dataset_emitter.GetAttribute("coupleRateVelocity")
        couple_rate_raw = (
            couple_rate.Get() if couple_rate and couple_rate.IsValid() else None
        )
        couple_rate_value = (
            float(couple_rate_raw) if couple_rate_raw is not None else 0.0
        )
        return (
            payload_count > 0 and couple_rate_value > 0.0,
            payload_count,
            couple_rate_value,
        )

    ready, payload_count, couple_rate_value = readiness()
    while (
        not ready
        and cycles < max_update_cycles
        and time.monotonic() - started_at < timeout_seconds
    ):
        await app.next_update_async()
        cycles += 1
        ready, payload_count, couple_rate_value = readiness()

    waited_seconds = time.monotonic() - started_at
    return {
        "ready": ready,
        "cycles": cycles,
        "seconds": waited_seconds,
        "timed_out": not ready,
        "payload_count": payload_count,
        "couple_rate_velocity": couple_rate_value,
    }


async def trace_kit_cae_dav_velocity_dataset(dataset_emitter, Usd) -> dict[str, object]:
    """Read the exact CAE source dataset consumed by FlowNanoVDBEmitter."""

    from omni.cae.viz import utils as cae_viz_utils

    source_dataset = await cae_viz_utils.get_input_dataset(
        dataset_emitter,
        "source",
        timeCode=Usd.TimeCode.Default(),
        device="cuda:0",
    )
    bounds_min, bounds_max = source_dataset.get_bounds()
    velocity_field = source_dataset.get_field("velocities")
    velocity_volume = velocity_field.get_data()
    return {
        "bounds": (
            tuple(float(value) for value in bounds_min),
            tuple(float(value) for value in bounds_max),
        ),
        "origin": tuple(float(value) for value in bounds_min),
        "voxel_size": tuple(float(value) for value in velocity_volume.get_voxel_size()),
    }
