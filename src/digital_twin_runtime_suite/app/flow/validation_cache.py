"""Session-local receipts for expensive Kit-CAE VTI validation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from digital_twin_runtime_suite.app.airflow_dataset import AirflowDataset

VALIDATION_CONTRACT_VERSION = "kit-cae-vti-validation-v1"


@dataclass(frozen=True)
class DatasetValidationSignature:
    """Cheap identity of the exact dataset version accepted in this session."""

    selector: str
    digest: str

    @property
    def compact_digest(self) -> str:
        """Return a log-friendly stable identifier without exposing full paths."""

        return self.digest[:12]


@dataclass(frozen=True)
class PreflightValidationReceipt:
    """Plain worker result that permits safe VTI preflight reuse."""

    signature: DatasetValidationSignature
    metadata: dict[str, object]
    grid_match: bool


@dataclass(frozen=True)
class TemporalProofReceipt:
    """Successful full-proof result, never a live Kit or USD handle."""

    signature: DatasetValidationSignature
    validated_sample_count: int
    duration_seconds: float


@dataclass(frozen=True)
class ValidationCacheLookup:
    """One cache decision made before a new Attach starts Kit work."""

    signature: DatasetValidationSignature
    result: str
    reason: str
    preflight: PreflightValidationReceipt | None
    temporal_proof: TemporalProofReceipt | None


class SessionValidationCache:
    """Keep successful VTI validation receipts only for one DTRS process."""

    def __init__(self) -> None:
        self._preflight_by_digest: dict[str, PreflightValidationReceipt] = {}
        self._proof_by_digest: dict[str, TemporalProofReceipt] = {}
        self._latest_digest_by_selector: dict[str, str] = {}

    def lookup(self, signature: DatasetValidationSignature) -> ValidationCacheLookup:
        """Return reusable receipts or explain why the dataset needs validation."""

        previous_digest = self._latest_digest_by_selector.get(signature.selector)
        preflight = self._preflight_by_digest.get(signature.digest)
        temporal_proof = self._proof_by_digest.get(signature.digest)
        if preflight:
            return ValidationCacheLookup(
                signature=signature,
                result="HIT",
                reason="Session receipt matches current dataset signature",
                preflight=preflight,
                temporal_proof=temporal_proof,
            )
        if previous_digest and previous_digest != signature.digest:
            return ValidationCacheLookup(
                signature=signature,
                result="INVALIDATED",
                reason="Dataset manifest or sample metadata changed",
                preflight=None,
                temporal_proof=None,
            )
        return ValidationCacheLookup(
            signature=signature,
            result="MISS",
            reason="No session receipt",
            preflight=None,
            temporal_proof=None,
        )

    def store_preflight(
        self,
        signature: DatasetValidationSignature,
        metadata: dict[str, object],
        grid_match: bool,
    ) -> PreflightValidationReceipt:
        """Remember a completed worker result after main-thread contract checks."""

        receipt = PreflightValidationReceipt(
            signature=signature,
            metadata=dict(metadata),
            grid_match=grid_match,
        )
        self._preflight_by_digest[signature.digest] = receipt
        self._latest_digest_by_selector[signature.selector] = signature.digest
        return receipt

    def store_temporal_proof(
        self,
        signature: DatasetValidationSignature,
        validated_sample_count: int,
        duration_seconds: float,
    ) -> TemporalProofReceipt:
        """Remember only a completed PASS for a matching preflight receipt."""

        if signature.digest not in self._preflight_by_digest:
            raise RuntimeError("Temporal proof cannot be cached before preflight.")
        receipt = TemporalProofReceipt(
            signature=signature,
            validated_sample_count=validated_sample_count,
            duration_seconds=duration_seconds,
        )
        self._proof_by_digest[signature.digest] = receipt
        return receipt

    def clear(self) -> None:
        """Drop all receipts when configuration or the DTRS session ends."""

        self._preflight_by_digest.clear()
        self._proof_by_digest.clear()
        self._latest_digest_by_selector.clear()


def build_dataset_validation_signature(
    dataset: AirflowDataset,
    velocity_field_name: str,
) -> DatasetValidationSignature:
    """Fingerprint manifest content plus ordered VTI metadata without VTK reads."""

    manifest_path = dataset.manifest_path.resolve()
    manifest_bytes = manifest_path.read_bytes()
    samples = []
    for sample_path in dataset.velocity_vti_sequence_paths:
        resolved_path = sample_path.resolve()
        stat = resolved_path.stat()
        samples.append(
            {
                "path": resolved_path.as_posix(),
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
            }
        )
    selector = f"{dataset.manifest.scope}/{dataset.manifest.state}"
    payload = {
        "contract_version": VALIDATION_CONTRACT_VERSION,
        "dataset_root": dataset.root.resolve().as_posix(),
        "selector": selector,
        "velocity_field_name": velocity_field_name,
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "samples": samples,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return DatasetValidationSignature(selector=selector, digest=digest)
