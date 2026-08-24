# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""Worker-safe VTI preflight without live Flow or USD state."""

from __future__ import annotations

import math
import re
from pathlib import Path


class TemporalVtiValidationCancelled(RuntimeError):
    """Signal cooperative cancellation of the worker-only VTI preflight."""


def read_kit_cae_vti_metadata(
    velocity_path: Path,
    field_name: str,
) -> dict[str, object]:
    """Read one VTI's worker-safe metadata before it is eligible for Flow.

    This plain-data preflight is deliberately separate from live Kit-CAE/Flow
    proof: it creates no USD, emitter, or simulation runtime objects.  The
    small header read independently preserves the authored ImageData origin
    used by the family compatibility contract.
    """

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
    bounds = tuple(float(value) for value in image.GetBounds())
    velocity_magnitude_max = float(array.GetRange(-1)[1])
    return {
        "components": components,
        "data_type": data_type,
        "dimensions": tuple(int(value) for value in image.GetDimensions()),
        "point_count": int(image.GetNumberOfPoints()),
        "origin": reader_origin,
        "vti_header_origin": header_origin,
        "vtk_reader_origin": reader_origin,
        "spacing": tuple(float(value) for value in image.GetSpacing()),
        "bounds": bounds,
        "velocity_magnitude_max": velocity_magnitude_max,
        "kit_cae_direct_attach_base_velocity_scale": (
            calculate_kit_cae_direct_attach_base_velocity_scale(
                bounds,
                velocity_magnitude_max,
            )
        ),
    }


def calculate_kit_cae_direct_attach_base_velocity_scale(
    bounds: tuple[float, float, float, float, float, float],
    velocity_magnitude_max: float,
) -> float:
    """Derive the static Kit-CAE source scale from validated VTI metadata."""

    if len(bounds) != 6:
        raise RuntimeError("VTI bounds must contain six values.")
    if not math.isfinite(velocity_magnitude_max) or velocity_magnitude_max <= 0.0:
        raise RuntimeError(
            "VTI velocity magnitude maximum must be finite and positive."
        )
    distance = math.dist(
        (bounds[0], bounds[2], bounds[4]),
        (bounds[1], bounds[3], bounds[5]),
    )
    if not math.isfinite(distance) or distance <= 0.0:
        raise RuntimeError("VTI bounds diagonal must be finite and positive.")
    return distance / velocity_magnitude_max


def validate_kit_cae_temporal_vti_contract(
    velocity_paths: tuple[Path, ...],
    field_name: str,
    progress_callback=None,
    cancel_requested=None,
) -> tuple[dict[str, object], bool]:
    """Preflight a complete temporal sequence using worker-safe VTI metadata.

    The returned metadata describes the representative first sample after all
    samples have been checked for the invariant spatial grid.  It is reusable
    background evidence, not a claim that live temporal Kit-CAE playback has
    already been proven.
    """

    metadata_by_path = []
    for completed_count, path in enumerate(velocity_paths, start=1):
        if cancel_requested and cancel_requested():
            raise TemporalVtiValidationCancelled("VTI preflight cancelled")
        metadata_by_path.append((path, read_kit_cae_vti_metadata(path, field_name)))
        if progress_callback:
            progress_callback(completed_count, len(velocity_paths), path.name)
        if cancel_requested and cancel_requested():
            raise TemporalVtiValidationCancelled("VTI preflight cancelled")
    primary_path, primary_metadata = metadata_by_path[0]
    for path, metadata in metadata_by_path[1:]:
        for key in ("dimensions", "spacing", "vti_header_origin"):
            if metadata[key] != primary_metadata[key]:
                raise RuntimeError(
                    "Temporal VTI grid contract mismatch: "
                    f"{path.name} {key} differs from {primary_path.name}."
                )
    return primary_metadata, True
