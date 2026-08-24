# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""Compatibility and phase-mapping rules for authored airflow dataset families."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from digital_twin_runtime_suite.app.airflow_dataset import AirflowDataset
from digital_twin_runtime_suite.app.airflow_validation.cache import (
    PreflightValidationReceipt,
)

_VELOCITY_ASSOCIATION = "point_data"


class AirflowDatasetFamilyCompatibilityError(RuntimeError):
    """One validated dataset cannot safely join the active airflow family."""


@dataclass(frozen=True)
class AirflowDatasetFamilyCompatibility:
    """Evidence that one family supports normalized discrete phase mapping."""

    family_compatible: bool
    source_selector: str
    target_selector: str
    source_sample_count: int
    target_sample_count: int
    member_selectors: tuple[str, ...]
    loop_duration_seconds: float
    phase_mapping: str = "normalized_discrete"


def validate_airflow_dataset_family(
    members: Sequence[tuple[AirflowDataset, PreflightValidationReceipt]],
    *,
    velocity_field_name: str,
) -> AirflowDatasetFamilyCompatibility:
    """Validate every already-preflighted member without another VTI pass.

    This is a compatibility gate for attached hot switching, not a second VTI
    validator.  Members may use different sample rates and sample counts, but
    their spatial/field contract and authored loop duration must agree so a
    normalized phase can be mapped deterministically without interpolation.
    """

    if not velocity_field_name:
        raise AirflowDatasetFamilyCompatibilityError(
            "Airflow family compatibility mismatch: dataset=family; "
            "property=velocity_field_name; expected=non-empty; actual=empty."
        )
    if len(members) < 2:
        raise AirflowDatasetFamilyCompatibilityError(
            "Airflow family compatibility mismatch: dataset=family; "
            f"property=member_count; expected=at least 2; actual={len(members)}."
        )

    baseline_dataset, baseline_receipt = members[0]
    _validate_member(baseline_dataset, baseline_receipt, velocity_field_name)
    baseline_selector = _selector(baseline_dataset)
    for dataset, receipt in members[1:]:
        _validate_member(dataset, receipt, velocity_field_name)
        selector = _selector(dataset)
        _require_equal(
            selector,
            "loop_duration_seconds",
            baseline_dataset.loop_duration_seconds,
            dataset.loop_duration_seconds,
        )
        for key in (
            "components",
            "data_type",
            "dimensions",
            "origin",
            "vti_header_origin",
            "spacing",
            "bounds",
        ):
            _require_equal(
                selector,
                key,
                _required_metadata(baseline_selector, baseline_receipt, key),
                _required_metadata(selector, receipt, key),
            )
    target_dataset, _ = members[-1]
    return AirflowDatasetFamilyCompatibility(
        family_compatible=True,
        source_selector=baseline_selector,
        target_selector=_selector(target_dataset),
        source_sample_count=baseline_dataset.manifest.sample_count,
        target_sample_count=target_dataset.manifest.sample_count,
        member_selectors=tuple(_selector(dataset) for dataset, _ in members),
        loop_duration_seconds=baseline_dataset.loop_duration_seconds,
    )


def validate_airflow_dataset_family_compatibility(
    source_dataset: AirflowDataset,
    source_receipt: PreflightValidationReceipt,
    target_dataset: AirflowDataset,
    target_receipt: PreflightValidationReceipt,
    *,
    velocity_field_name: str,
) -> AirflowDatasetFamilyCompatibility:
    """Compatibility facade for one active-to-target transition pair."""

    return validate_airflow_dataset_family(
        ((source_dataset, source_receipt), (target_dataset, target_receipt)),
        velocity_field_name=velocity_field_name,
    )


def normalized_phase_target_sample_index(
    source_sample_index: int,
    source_sample_count: int,
    target_sample_count: int,
) -> int:
    """Map ``source_index / source_count`` to the nearest target sample.

    The result is a deterministic discrete sample index, wrapped into the
    target loop.  It deliberately performs no velocity-field interpolation.
    """

    if source_sample_count <= 0 or target_sample_count <= 0:
        raise ValueError("Temporal source and target sample counts must be positive.")
    if not 0 <= source_sample_index < source_sample_count:
        raise ValueError("Source temporal sample index is outside the sequence.")
    source_phase = source_sample_index / source_sample_count
    return (
        int(math.floor(source_phase * target_sample_count + 0.5)) % target_sample_count
    )


def next_normalized_phase_target_sample_index(
    current_source_index: int,
    source_sample_count: int,
    target_sample_count: int,
) -> int:
    """Map the next source boundary, preserving phase across loop wrap-around."""

    if not 0 <= current_source_index < source_sample_count:
        raise ValueError("Current temporal sample index is outside the sequence.")
    source_boundary_index = (current_source_index + 1) % source_sample_count
    return normalized_phase_target_sample_index(
        source_boundary_index, source_sample_count, target_sample_count
    )


def _validate_member(
    dataset: AirflowDataset,
    receipt: PreflightValidationReceipt,
    velocity_field_name: str,
) -> None:
    selector = _selector(dataset)
    _validate_manifest_timing(dataset)
    if not receipt.grid_match:
        _mismatch(selector, "grid_match", True, False)
    _require_equal(selector, "receipt.selector", selector, receipt.signature.selector)
    _require_equal(
        selector,
        "velocity_field_name",
        velocity_field_name,
        _required_metadata(selector, receipt, "velocity_field_name"),
    )
    _require_equal(
        selector,
        "velocity_field_association",
        _VELOCITY_ASSOCIATION,
        _required_metadata(selector, receipt, "velocity_field_association"),
    )
    _require_equal(
        selector,
        "dimensions",
        dataset.manifest.grid,
        tuple(_required_metadata(selector, receipt, "dimensions")),
    )


def _validate_manifest_timing(dataset: AirflowDataset) -> None:
    manifest = dataset.manifest
    selector = _selector(dataset)
    derived_rate = manifest.source_fps / manifest.sample_step_frames
    if not math.isclose(
        manifest.sample_rate_hz, derived_rate, rel_tol=1e-6, abs_tol=1e-6
    ):
        _mismatch(selector, "sample_rate_hz", derived_rate, manifest.sample_rate_hz)
    if manifest.sample_count <= 0:
        _mismatch(selector, "sample_count", "positive", manifest.sample_count)
    if len(dataset.velocity_vti_sequence_paths) != manifest.sample_count:
        _mismatch(
            selector,
            "temporal_sample_structure",
            manifest.sample_count,
            len(dataset.velocity_vti_sequence_paths),
        )


def _require_equal(selector: str, property_name: str, expected, actual) -> None:
    if expected != actual:
        _mismatch(selector, property_name, expected, actual)


def _required_metadata(
    selector: str,
    receipt: PreflightValidationReceipt,
    key: str,
):
    try:
        return receipt.metadata[key]
    except KeyError as error:
        _mismatch(selector, key, "present", "missing")
        raise AssertionError("unreachable") from error


def _mismatch(selector: str, property_name: str, expected, actual) -> None:
    raise AirflowDatasetFamilyCompatibilityError(
        "Airflow family compatibility mismatch: "
        f"dataset={selector}; property={property_name}; "
        f"expected={expected}; actual={actual}."
    )


def _selector(dataset: AirflowDataset) -> str:
    return f"{dataset.manifest.scope}/{dataset.manifest.state}"
