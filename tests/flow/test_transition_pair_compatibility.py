"""Focused active-to-target validation gates for attached Flow transitions."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from digital_twin_runtime_suite.app import commands
from digital_twin_runtime_suite.app.airflow_validation.cache import (
    DatasetValidationSignature,
    PreflightValidationReceipt,
)
from digital_twin_runtime_suite.app.airflow_validation.family import (
    AirflowDatasetFamilyCompatibilityError,
)
from digital_twin_runtime_suite.app.commands import RuntimeController


def test_normal_to_critical_pair_ignores_unrelated_missing_receipts(
    monkeypatch,
) -> None:
    controller, active, target, active_signature, target_signature = _pair_inputs(
        monkeypatch
    )
    controller._flow_validation_cache = _ReceiptLookup(
        {active_signature.digest: _receipt(active, active_signature)}
    )
    target_receipt = _receipt(target, target_signature)
    controller.acquire_airflow_validation_for_transition = _unexpected_vti_validation

    result = controller.validate_attached_airflow_transition_pair(
        target_dataset=target,
        target_receipt=target_receipt,
        target_signature=target_signature,
    )

    assert result.family_compatible is True
    assert result.member_selectors == (
        "server/load_normal",
        "server/load_critical",
    )
    assert controller._flow_validation_cache.selectors == ["server/load_normal"]


def test_pair_rejects_missing_committed_receipt(monkeypatch) -> None:
    controller, _active, target, _active_signature, target_signature = _pair_inputs(
        monkeypatch
    )
    controller._flow_validation_cache = _ReceiptLookup({})

    with pytest.raises(
        AirflowDatasetFamilyCompatibilityError,
        match="dataset=server/load_normal; property=preflight_receipt",
    ):
        controller.validate_attached_airflow_transition_pair(
            target_dataset=target,
            target_receipt=_receipt(target, target_signature),
            target_signature=target_signature,
        )


def test_pair_rejects_missing_target_receipt(monkeypatch) -> None:
    controller, active, target, active_signature, target_signature = _pair_inputs(
        monkeypatch
    )
    controller._flow_validation_cache = _ReceiptLookup(
        {active_signature.digest: _receipt(active, active_signature)}
    )

    with pytest.raises(
        AirflowDatasetFamilyCompatibilityError,
        match="dataset=server/load_critical; property=preflight_receipt",
    ):
        controller.validate_attached_airflow_transition_pair(
            target_dataset=target,
            target_receipt=None,
            target_signature=target_signature,
        )


def test_pair_rejects_actual_active_target_contract_incompatibility(
    monkeypatch,
) -> None:
    controller, active, target, active_signature, target_signature = _pair_inputs(
        monkeypatch
    )
    controller._flow_validation_cache = _ReceiptLookup(
        {active_signature.digest: _receipt(active, active_signature)}
    )
    target_metadata = _metadata(target)
    target_metadata["spacing"] = (0.02, 0.01, 0.01)

    with pytest.raises(
        AirflowDatasetFamilyCompatibilityError,
        match="dataset=server/load_critical; property=spacing",
    ):
        controller.validate_attached_airflow_transition_pair(
            target_dataset=target,
            target_receipt=_receipt(
                target,
                target_signature,
                metadata=target_metadata,
            ),
            target_signature=target_signature,
        )


def _pair_inputs(monkeypatch):
    controller = RuntimeController("configs/digital_twin_runtime_suite.toml")
    active_binding = controller.resolve_workload_airflow_binding("Nominal")
    target_binding = controller.resolve_workload_airflow_binding("Critical")
    controller._flow_session_workload_binding = active_binding
    active = controller._airflow_state.committed.dataset
    target = controller._airflow_state.resolve_target(target_binding).dataset

    def signature(dataset, _velocity_field_name):
        selector = f"{dataset.manifest.scope}/{dataset.manifest.state}"
        return DatasetValidationSignature(selector, f"{selector}-current")

    monkeypatch.setattr(commands, "build_dataset_validation_signature", signature)
    return (
        controller,
        active,
        target,
        signature(active, "vel"),
        signature(target, "vel"),
    )


def _receipt(
    dataset,
    signature: DatasetValidationSignature,
    *,
    metadata: dict[str, object] | None = None,
) -> PreflightValidationReceipt:
    return PreflightValidationReceipt(
        signature=signature,
        metadata=metadata or _metadata(dataset),
        grid_match=True,
    )


def _metadata(dataset) -> dict[str, object]:
    return {
        "components": 3,
        "data_type": "float",
        "velocity_field_name": "vel",
        "velocity_field_association": "point_data",
        "dimensions": dataset.manifest.grid,
        "origin": (0.0, 0.0, 0.0),
        "vti_header_origin": (0.0, 0.0, 0.0),
        "spacing": (0.01, 0.01, 0.01),
        "bounds": (0.0, 1.0, 0.0, 1.0, 0.0, 1.0),
    }


class _ReceiptLookup:
    def __init__(self, receipts: dict[str, PreflightValidationReceipt]) -> None:
        self._receipts = receipts
        self.selectors: list[str] = []

    def lookup(self, signature: DatasetValidationSignature) -> SimpleNamespace:
        self.selectors.append(signature.selector)
        return SimpleNamespace(preflight=self._receipts.get(signature.digest))


def _unexpected_vti_validation(*_args) -> None:
    raise AssertionError("Pair compatibility must not trigger VTI validation.")
