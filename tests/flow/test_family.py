"""Stage 08 dataset-family compatibility contracts."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from digital_twin_runtime_suite.app.airflow_dataset import (
    AirflowDataset,
    AirflowDatasetManifest,
)
from digital_twin_runtime_suite.app.airflow_validation.cache import (
    DatasetValidationSignature,
    PreflightValidationReceipt,
)
from digital_twin_runtime_suite.app.airflow_validation.family import (
    AirflowDatasetFamilyCompatibilityError,
    validate_airflow_dataset_family,
    validate_airflow_dataset_family_compatibility,
)


def test_compatible_family_allows_unequal_temporal_rates_and_sample_counts():
    source = _dataset(
        "load_normal", sample_count=80, source_fps=50.0, step=10, rate=5.0
    )
    target = _dataset(
        "load_critical", sample_count=96, source_fps=60.0, step=10, rate=6.0
    )

    result = validate_airflow_dataset_family_compatibility(
        source,
        _receipt(source),
        target,
        _receipt(target),
        velocity_field_name="vel",
    )

    assert result.source_sample_count == 80
    assert result.target_sample_count == 96
    assert result.family_compatible is True
    assert result.phase_mapping == "normalized_discrete"


def test_compatible_four_member_family_uses_existing_receipts_only():
    members = tuple(
        (
            _dataset(
                state, sample_count=count, source_fps=rate, step=10, rate=rate / 10
            ),
            None,
        )
        for state, count, rate in (
            ("load_idle", 80, 50.0),
            ("load_normal", 96, 60.0),
            ("load_surge", 112, 70.0),
            ("load_critical", 128, 80.0),
        )
    )
    receipts = tuple(_receipt(dataset) for dataset, _ in members)

    result = validate_airflow_dataset_family(
        tuple((dataset, receipt) for (dataset, _), receipt in zip(members, receipts)),
        velocity_field_name="vel",
    )

    assert result.member_selectors == (
        "server/load_idle",
        "server/load_normal",
        "server/load_surge",
        "server/load_critical",
    )
    assert result.loop_duration_seconds == 16.0


@pytest.mark.parametrize(
    "key", ["components", "data_type", "dimensions", "origin", "spacing", "bounds"]
)
def test_rejects_incompatible_field_or_spatial_contract(key):
    source = _dataset("load_normal")
    target = _dataset("load_critical")
    target_metadata = _metadata()
    target_metadata[key] = {
        "components": 1,
        "data_type": "double",
        "dimensions": (80, 72, 232),
        "origin": (1.0, 0.0, 0.0),
        "spacing": (0.02, 0.01, 0.01),
        "bounds": (1.0, 2.0, 0.0, 1.0, 0.0, 1.0),
    }[key]

    expected_reason = f"property={key}"
    with pytest.raises(AirflowDatasetFamilyCompatibilityError, match=expected_reason):
        validate_airflow_dataset_family_compatibility(
            source,
            _receipt(source),
            target,
            _receipt(target, metadata=target_metadata),
            velocity_field_name="vel",
        )


def test_rejects_manifest_timing_that_is_not_internally_coherent():
    source = _dataset("load_normal", source_fps=50.0, step=10, rate=4.0)
    target = _dataset("load_critical")

    with pytest.raises(
        AirflowDatasetFamilyCompatibilityError, match="property=sample_rate_hz"
    ):
        validate_airflow_dataset_family_compatibility(
            source,
            _receipt(source),
            target,
            _receipt(target),
            velocity_field_name="vel",
        )


def test_rejects_missing_temporal_structure_needed_for_phase_mapping():
    source = _dataset(
        "load_normal", sample_count=80, source_fps=50.0, step=10, rate=5.0
    )
    target = _dataset(
        "load_critical", sample_count=96, source_fps=60.0, step=10, rate=6.0
    )
    target = replace(
        target,
        velocity_vti_sequence_paths=target.velocity_vti_sequence_paths[:-1],
    )

    with pytest.raises(
        AirflowDatasetFamilyCompatibilityError,
        match="dataset=server/load_critical; property=temporal_sample_structure; "
        "expected=96; actual=95",
    ):
        validate_airflow_dataset_family_compatibility(
            source,
            _receipt(source),
            target,
            _receipt(target),
            velocity_field_name="vel",
        )


def test_rejects_unequal_loop_duration_even_when_spatial_contract_matches():
    source = _dataset(
        "load_normal", sample_count=80, source_fps=50.0, step=10, rate=5.0
    )
    target = _dataset(
        "load_critical", sample_count=96, source_fps=50.0, step=10, rate=5.0
    )

    with pytest.raises(
        AirflowDatasetFamilyCompatibilityError, match="property=loop_duration_seconds"
    ):
        validate_airflow_dataset_family_compatibility(
            source,
            _receipt(source),
            target,
            _receipt(target),
            velocity_field_name="vel",
        )


def test_rejects_receipt_missing_required_spatial_metadata():
    source = _dataset("load_normal")
    target = _dataset("load_critical")
    metadata = _metadata()
    del metadata["bounds"]

    with pytest.raises(AirflowDatasetFamilyCompatibilityError, match="property=bounds"):
        validate_airflow_dataset_family_compatibility(
            source,
            _receipt(source),
            target,
            _receipt(target, metadata=metadata),
            velocity_field_name="vel",
        )


def test_rejects_receipt_not_belonging_to_the_dataset():
    source = _dataset("load_normal")
    target = _dataset("load_critical")

    with pytest.raises(
        AirflowDatasetFamilyCompatibilityError, match="property=receipt.selector"
    ):
        validate_airflow_dataset_family_compatibility(
            source,
            _receipt(source),
            target,
            _receipt(target, selector="server/load_idle"),
            velocity_field_name="vel",
        )


def test_rejects_receipt_grid_that_does_not_match_its_manifest():
    source = _dataset("load_normal")
    target = _dataset("load_critical")
    metadata = _metadata()
    metadata["dimensions"] = (80, 72, 232)

    with pytest.raises(
        AirflowDatasetFamilyCompatibilityError,
        match="property=dimensions",
    ):
        validate_airflow_dataset_family_compatibility(
            source,
            _receipt(source),
            target,
            _receipt(target, metadata=metadata),
            velocity_field_name="vel",
        )


def test_rejects_empty_velocity_field_identity():
    source = _dataset("load_normal")
    target = _dataset("load_critical")

    with pytest.raises(
        AirflowDatasetFamilyCompatibilityError, match="property=velocity_field_name"
    ):
        validate_airflow_dataset_family_compatibility(
            source,
            _receipt(source),
            target,
            _receipt(target),
            velocity_field_name="",
        )


def test_rejects_velocity_field_identity_or_association_mismatch():
    source = _dataset("load_normal")
    target = _dataset("load_critical")
    metadata = _metadata()
    metadata["velocity_field_name"] = "different_vel"

    with pytest.raises(
        AirflowDatasetFamilyCompatibilityError, match="property=velocity_field_name"
    ):
        validate_airflow_dataset_family_compatibility(
            source,
            _receipt(source),
            target,
            _receipt(target, metadata=metadata),
            velocity_field_name="vel",
        )

    metadata = _metadata()
    metadata["velocity_field_association"] = "cell_data"
    with pytest.raises(
        AirflowDatasetFamilyCompatibilityError,
        match="property=velocity_field_association",
    ):
        validate_airflow_dataset_family_compatibility(
            source,
            _receipt(source),
            target,
            _receipt(target, metadata=metadata),
            velocity_field_name="vel",
        )


def _dataset(
    state: str,
    *,
    sample_count: int = 3,
    source_fps: float = 50.0,
    step: int = 10,
    rate: float = 5.0,
) -> AirflowDataset:
    root = Path("C:/airflow_datasets")
    manifest = AirflowDatasetManifest(
        scope="server",
        state=state,
        source_fps=source_fps,
        sample_step_frames=step,
        sample_rate_hz=rate,
        sample_count=sample_count,
        grid=(184, 72, 232),
    )
    return AirflowDataset(
        root=root,
        directory=root / state,
        manifest_path=root / state / "manifest.toml",
        manifest=manifest,
        velocity_vti_sequence_paths=tuple(
            root / state / f"velocity_{1001 + index * step}.vti"
            for index in range(sample_count)
        ),
        source_frames=tuple(1001 + index * step for index in range(sample_count)),
    )


def _receipt(
    dataset: AirflowDataset,
    *,
    metadata: dict[str, object] | None = None,
    selector: str | None = None,
) -> PreflightValidationReceipt:
    identity = selector or f"{dataset.manifest.scope}/{dataset.manifest.state}"
    return PreflightValidationReceipt(
        signature=DatasetValidationSignature(selector=identity, digest=identity),
        metadata=metadata or _metadata(),
        grid_match=True,
    )


def _metadata() -> dict[str, object]:
    return {
        "components": 3,
        "data_type": "float",
        "velocity_field_name": "vel",
        "velocity_field_association": "point_data",
        "dimensions": (184, 72, 232),
        "origin": (0.0, 0.0, 0.0),
        "vti_header_origin": (0.0, 0.0, 0.0),
        "spacing": (0.01, 0.01, 0.01),
        "bounds": (0.0, 1.0, 0.0, 1.0, 0.0, 1.0),
    }
