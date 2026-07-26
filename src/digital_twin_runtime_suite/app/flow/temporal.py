"""Temporal VTI sample mapping and loop-proof helpers for DTRS Flow."""

from __future__ import annotations

import re
from pathlib import Path

from digital_twin_runtime_suite.app.flow.validation import read_kit_cae_vti_metadata


def kit_cae_vectors_match(expected, actual, tolerance: float = 1e-6) -> bool:
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


def validate_kit_cae_temporal_vti_contract(
    velocity_paths: tuple[Path, ...],
    field_name: str,
) -> tuple[dict[str, object], bool]:
    """Require each Stage 6 temporal fixture to share the imported grid contract."""

    metadata_by_path = [
        (path, read_kit_cae_vti_metadata(path, field_name)) for path in velocity_paths
    ]
    primary_path, primary_metadata = metadata_by_path[0]
    for path, metadata in metadata_by_path[1:]:
        for key in ("dimensions", "spacing", "vti_header_origin"):
            if metadata[key] != primary_metadata[key]:
                raise RuntimeError(
                    "Temporal VTI grid contract mismatch: "
                    f"{path.name} {key} differs from {primary_path.name}."
                )
    return primary_metadata, True


def kit_cae_vti_source_frame(asset: Path) -> str:
    """Extract the Houdini frame suffix for compact temporal evidence."""

    match = re.search(r"(\d+)$", asset.stem)
    return match.group(1) if match else asset.stem


def flow_log_value(value) -> object:
    """Keep compact Flow evidence stable for scalar Kit attribute values."""

    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return value


def kit_cae_temporal_loop_proof_summary(
    records: list[dict[str, object]],
    velocity_paths: tuple[Path, ...],
) -> dict[str, object]:
    """Reduce the fixed Stage 6 loop contract into explicit proof evidence."""

    expected_assets = (*velocity_paths, velocity_paths[0]) if velocity_paths else ()
    expected_names = [asset.name for asset in expected_assets]
    observed_names = [str(record.get("asset", "unavailable")) for record in records]
    frames = [str(record.get("source_frame", "unavailable")) for record in records]
    hashes = {
        str(record["asset_hash"])
        for record in records
        if record.get("asset_hash") is not None
    }
    transitions = [str(record.get("transition", "")) for record in records[1:]]
    forward_transitions = sum(transition == "SWAP" for transition in transitions)
    loop_transitions = sum(transition == "LOOP" for transition in transitions)
    operator_ready_all = all(bool(record.get("operator_ready")) for record in records)
    origin_match_all = all(bool(record.get("origin_match")) for record in records)
    grid_match_all = all(bool(record.get("grid_match")) for record in records)
    timeline_continuous = all(
        bool(record.get("timeline_advancing")) for record in records
    )
    flow_resets = sum(bool(record.get("flow_reset")) for record in records)
    loop_closure = (
        len(records) == len(expected_assets)
        and bool(records)
        and observed_names[-1] == expected_names[0]
        and transitions[-1:] == ["LOOP"]
    )
    mismatch = next(
        (
            (expected_name, observed_name)
            for expected_name, observed_name in zip(expected_names, observed_names)
            if expected_name != observed_name
        ),
        None,
    )
    if mismatch is None and len(observed_names) < len(expected_names):
        mismatch = (expected_names[len(observed_names)], "unavailable")
    passed = (
        len(velocity_paths) == 16
        and len(records) == 17
        and observed_names == expected_names
        and len(set(observed_names)) == 16
        and len(hashes) == 16
        and transitions == ["SWAP"] * 15 + ["LOOP"]
        and forward_transitions == 15
        and loop_transitions == 1
        and loop_closure
        and operator_ready_all
        and origin_match_all
        and grid_match_all
        and timeline_continuous
        and flow_resets == 0
    )
    return {
        "frames": frames,
        "unique_assets": len(set(observed_names)),
        "unique_hashes": len(hashes),
        "forward_transitions": forward_transitions,
        "loop_transitions": loop_transitions,
        "operator_ready_all": operator_ready_all,
        "origin_match_all": origin_match_all,
        "grid_match_all": grid_match_all,
        "timeline_continuous": timeline_continuous,
        "flow_resets": flow_resets,
        "loop_closure": loop_closure,
        "mismatch": mismatch,
        "passed": passed,
    }


def author_kit_cae_temporal_velocity_samples(
    field_prim,
    velocity_paths: tuple[Path, ...],
    time_codes_per_second: float,
    cae_vtk,
    Sdf,
    Usd,
) -> tuple[float, ...]:
    """Map the bounded Stage 6 probe to time samples on one VTK field."""

    file_names_attr = cae_vtk.FieldArray(field_prim).GetFileNamesAttr()
    if not file_names_attr or not file_names_attr.IsValid():
        raise RuntimeError("Kit-CAE velocity field is missing fileNames.")
    if time_codes_per_second <= 0:
        raise RuntimeError("Stage timeCodesPerSecond must be positive.")
    time_codes = tuple(
        float(index) * float(time_codes_per_second)
        for index in range(len(velocity_paths))
    )
    for time_code, velocity_path in zip(time_codes, velocity_paths):
        file_names_attr.Set(
            [Sdf.AssetPath(velocity_path.as_posix())],
            Usd.TimeCode(time_code),
        )
    return time_codes


def kit_cae_file_names_value_at_time(field_prim, time_code, cae_vtk, Usd):
    """Read the VTK source assets selected at one USD time code."""

    file_names_attr = cae_vtk.FieldArray(field_prim).GetFileNamesAttr()
    return file_names_attr.Get(Usd.TimeCode(time_code))


def kit_cae_file_names_value_repr(value) -> list[str]:
    """Serialize a composed USD asset array for temporal evidence."""

    return [asset.resolvedPath or asset.path or str(asset) for asset in (value or [])]


def kit_cae_file_names_time_samples(field_prim, cae_vtk, Usd) -> list[str]:
    """Format authored VTI source samples for compact time-domain evidence."""

    file_names_attr = cae_vtk.FieldArray(field_prim).GetFileNamesAttr()
    return [
        f"{time_code}:"
        + "|".join(
            kit_cae_file_names_value_repr(
                kit_cae_file_names_value_at_time(
                    field_prim,
                    time_code,
                    cae_vtk,
                    Usd,
                )
            )
        )
        for time_code in file_names_attr.GetTimeSamples()
    ]


def kit_cae_file_names_property_stack(field_prim, cae_vtk) -> list[dict[str, object]]:
    """Expose only composed fileNames opinions needed to debug time samples."""

    file_names_attr = cae_vtk.FieldArray(field_prim).GetFileNamesAttr()
    stack = []
    for spec in file_names_attr.GetPropertyStack():
        try:
            time_samples = spec.GetInfo("timeSamples") or {}
        except Exception:
            time_samples = {}
        stack.append(
            {
                "layer": spec.layer.identifier,
                "time_codes_per_second": spec.layer.timeCodesPerSecond,
                "default": kit_cae_file_names_value_repr(spec.default),
                "authored_time_samples": {
                    str(time_code): kit_cae_file_names_value_repr(value)
                    for time_code, value in time_samples.items()
                },
            }
        )
    return stack


def kit_cae_selected_velocity_asset(field_prim, time_code, cae_vtk, Usd) -> Path | None:
    """Resolve the source VTI selected by the current USD time code."""

    file_names = kit_cae_file_names_value_at_time(
        field_prim,
        time_code,
        cae_vtk,
        Usd,
    )
    if not file_names or len(file_names) != 1:
        return None
    asset_path = file_names[0]
    resolved = asset_path.resolvedPath or asset_path.path
    return Path(resolved).resolve() if resolved else None
