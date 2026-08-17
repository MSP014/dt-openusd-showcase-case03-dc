"""Session and persisted receipts for manifest-backed VTI validation."""

from __future__ import annotations

import hashlib
import json
import logging
import math
from dataclasses import dataclass

from digital_twin_runtime_suite.app.airflow_dataset import AirflowDataset
from digital_twin_runtime_suite.app.validation_receipts import (
    ValidationReceiptStore,
)

VALIDATION_CONTRACT_VERSION = "kit-cae-vti-validation-v3"
LOGGER = logging.getLogger(__name__)

_PREFLIGHT_TUPLE_FIELDS = {
    "dimensions": (3, int),
    "origin": (3, float),
    "vti_header_origin": (3, float),
    "vtk_reader_origin": (3, float),
    "spacing": (3, float),
    "bounds": (6, float),
}
_PREFLIGHT_INT_FIELDS = ("components", "point_count")
_PREFLIGHT_FLOAT_FIELDS = (
    "velocity_magnitude_max",
    "kit_cae_direct_attach_base_velocity_scale",
)
_PREFLIGHT_STRING_FIELDS = (
    "data_type",
    "velocity_field_name",
    "velocity_field_association",
)
_PREFLIGHT_BASE_FIELDS = frozenset(
    {
        *_PREFLIGHT_TUPLE_FIELDS,
        *_PREFLIGHT_INT_FIELDS,
        *_PREFLIGHT_FLOAT_FIELDS,
        "data_type",
    }
)
_PREFLIGHT_SUPPORTED_FIELDS = _PREFLIGHT_BASE_FIELDS | frozenset(
    _PREFLIGHT_STRING_FIELDS
)


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
    """Successful live temporal-proof evidence without Kit or USD handles."""

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
    receipt_source: str = "NONE"
    cache_location: str = "NONE"


def canonical_preflight_metadata(
    metadata: object,
    *,
    require_complete: bool,
) -> dict[str, object]:
    """Restore the exact plain-data types consumed by Flow and diagnostics."""

    if not isinstance(metadata, dict):
        raise ValueError("VTI preflight metadata must be an object.")
    unknown = set(metadata) - _PREFLIGHT_SUPPORTED_FIELDS
    if unknown:
        names = ", ".join(sorted(unknown))
        raise ValueError(f"Unsupported VTI preflight metadata fields: {names}.")
    missing = _PREFLIGHT_BASE_FIELDS - set(metadata)
    if require_complete and missing:
        names = ", ".join(sorted(missing))
        raise ValueError(f"VTI preflight metadata is incomplete: {names}.")

    canonical: dict[str, object] = {}
    for name, (length, value_type) in _PREFLIGHT_TUPLE_FIELDS.items():
        if name not in metadata:
            continue
        canonical[name] = _canonical_tuple(
            metadata[name],
            name=name,
            length=length,
            value_type=value_type,
        )
    for name in _PREFLIGHT_INT_FIELDS:
        if name in metadata:
            canonical[name] = _canonical_int(metadata[name], name)
    for name in _PREFLIGHT_FLOAT_FIELDS:
        if name in metadata:
            canonical[name] = _canonical_float(metadata[name], name)
    for name in _PREFLIGHT_STRING_FIELDS:
        if name not in metadata:
            continue
        value = metadata[name]
        if not isinstance(value, str):
            raise ValueError(f"VTI preflight metadata {name} must be a string.")
        canonical[name] = value
    return canonical


def serialise_preflight_metadata(metadata: object) -> dict[str, object]:
    """Return the versioned JSON payload for one complete preflight result."""

    canonical = canonical_preflight_metadata(metadata, require_complete=True)
    return {
        name: list(value) if name in _PREFLIGHT_TUPLE_FIELDS else value
        for name, value in canonical.items()
    }


def deserialise_preflight_metadata(metadata: object) -> dict[str, object]:
    """Rehydrate persisted JSON vectors as canonical tuples."""

    return canonical_preflight_metadata(metadata, require_complete=True)


def _canonical_tuple(
    value: object,
    *,
    name: str,
    length: int,
    value_type: type,
) -> tuple[object, ...]:
    if not isinstance(value, (list, tuple)) or len(value) != length:
        raise ValueError(f"VTI preflight metadata {name} must contain {length} values.")
    if value_type is int:
        return tuple(_canonical_int(item, name) for item in value)
    return tuple(_canonical_float(item, name) for item in value)


def _canonical_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"VTI preflight metadata {name} must contain integers.")
    return value


def _canonical_float(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"VTI preflight metadata {name} must contain numbers.")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"VTI preflight metadata {name} must be finite.")
    return result


class SessionValidationCache:
    """Own session receipts and optional persisted preflight evidence.

    A receipt is reusable only when the caller supplies the exact same
    :class:`DatasetValidationSignature`.  Reloading runtime/UI configuration
    therefore leaves this evidence intact; changed validation inputs naturally
    select a different digest instead of relying on a manual invalidation list.
    Live temporal proof remains session-only even when preflight persistence is
    enabled.
    """

    def __init__(
        self,
        *,
        persisted_store: ValidationReceiptStore | None = None,
        reuse_persisted: bool = False,
    ) -> None:
        self._preflight_by_digest: dict[str, PreflightValidationReceipt] = {}
        self._proof_by_digest: dict[str, TemporalProofReceipt] = {}
        self._preflight_source_by_digest: dict[str, str] = {}
        self._latest_digest_by_selector: dict[str, str] = {}
        self._persisted_store = persisted_store
        self._reuse_persisted = reuse_persisted

    def configure_persistence(
        self,
        *,
        persisted_store: ValidationReceiptStore | None,
        reuse_persisted: bool,
    ) -> None:
        """Update opt-in persistence without discarding session receipts."""

        self._persisted_store = persisted_store
        self._reuse_persisted = reuse_persisted

    def lookup(self, signature: DatasetValidationSignature) -> ValidationCacheLookup:
        """Return reusable receipts or explain why the dataset needs validation."""

        previous_digest = self._latest_digest_by_selector.get(signature.selector)
        preflight = self._preflight_by_digest.get(signature.digest)
        temporal_proof = self._proof_by_digest.get(signature.digest)
        if preflight:
            receipt_source = self._preflight_source_by_digest.get(
                signature.digest,
                "SESSION",
            )
            if self._persisted_store:
                self._persisted_store.record_reuse(
                    "vti",
                    receipt_source,
                    signature.selector,
                )
            return ValidationCacheLookup(
                signature=signature,
                result="HIT",
                reason="Session receipt matches current dataset signature",
                preflight=preflight,
                temporal_proof=temporal_proof,
                receipt_source=receipt_source,
                cache_location="SESSION",
            )
        persisted = self._lookup_persisted_preflight(signature)
        if persisted is not None:
            self._preflight_by_digest[signature.digest] = persisted
            self._preflight_source_by_digest[signature.digest] = "PERSISTED"
            self._latest_digest_by_selector[signature.selector] = signature.digest
            return ValidationCacheLookup(
                signature=signature,
                result="HIT",
                reason="Persisted receipt matches current dataset signature",
                preflight=persisted,
                temporal_proof=None,
                receipt_source="PERSISTED",
                cache_location="SESSION",
            )
        if previous_digest and previous_digest != signature.digest:
            return ValidationCacheLookup(
                signature=signature,
                result="INVALIDATED",
                reason="Dataset manifest or sample metadata changed",
                preflight=None,
                temporal_proof=None,
                receipt_source="NONE",
            )
        return ValidationCacheLookup(
            signature=signature,
            result="MISS",
            reason="No session receipt",
            preflight=None,
            temporal_proof=None,
            receipt_source="NONE",
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
            metadata=canonical_preflight_metadata(
                metadata,
                require_complete=False,
            ),
            grid_match=grid_match,
        )
        self._preflight_by_digest[signature.digest] = receipt
        self._latest_digest_by_selector[signature.selector] = signature.digest
        self._preflight_source_by_digest[signature.digest] = "FRESH"
        if self._persisted_store:
            self._persisted_store.record_reuse("vti", "FRESH", signature.selector)
        if self._reuse_persisted:
            self._persist_preflight(receipt)
        return receipt

    def persist_session_preflight_receipts(self) -> None:
        """Publish completed session preflights when persistence becomes enabled."""

        if not self._reuse_persisted:
            return
        for receipt in self._preflight_by_digest.values():
            self._persist_preflight(receipt)

    def record_expensive_preflight_call(self) -> None:
        """Instrument the actual worker invocation, never a cache lookup."""

        if self._persisted_store:
            self._persisted_store.record_expensive_validation("vti")

    def _lookup_persisted_preflight(
        self,
        signature: DatasetValidationSignature,
    ) -> PreflightValidationReceipt | None:
        if not self._reuse_persisted or self._persisted_store is None:
            return None
        lookup = self._persisted_store.lookup_vti(
            signature.selector,
            signature.digest,
        )
        if lookup.status != "HIT" or lookup.payload is None:
            return None
        payload = lookup.payload
        if payload.get("validation_contract_version") != VALIDATION_CONTRACT_VERSION:
            self._persisted_store.record_invalidation(
                "vti",
                signature.selector,
            )
            return None
        metadata_payload = payload.get("metadata")
        grid_match = payload.get("grid_match")
        try:
            metadata = deserialise_preflight_metadata(metadata_payload)
        except ValueError as error:
            LOGGER.warning(
                "Ignoring malformed persisted VTI receipt for %s: %s",
                signature.selector,
                error,
            )
            self._persisted_store.record_invalidation(
                "vti",
                signature.selector,
            )
            return None
        if not isinstance(grid_match, bool):
            LOGGER.warning(
                "Ignoring malformed persisted VTI grid result for %s.",
                signature.selector,
            )
            self._persisted_store.record_invalidation(
                "vti",
                signature.selector,
            )
            return None
        self._persisted_store.record_reuse(
            "vti",
            "PERSISTED",
            signature.selector,
        )
        return PreflightValidationReceipt(
            signature=signature,
            metadata=metadata,
            grid_match=grid_match,
        )

    def _persist_preflight(self, receipt: PreflightValidationReceipt) -> None:
        store = self._persisted_store
        if store is None:
            return
        try:
            store.store_vti(
                selector=receipt.signature.selector,
                signature_digest=receipt.signature.digest,
                metadata=serialise_preflight_metadata(receipt.metadata),
                grid_match=receipt.grid_match,
                validation_contract_version=VALIDATION_CONTRACT_VERSION,
            )
        except (OSError, TypeError, ValueError) as error:
            LOGGER.warning(
                "Could not persist VTI validation receipt for %s: %s",
                receipt.signature.selector,
                error,
            )

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
        """Drop all receipts only at an explicit session/lifecycle boundary.

        ``RuntimeController.reload_config()`` intentionally does *not* call
        this: an unchanged dataset remains preflight-valid across config reload.
        """

        self._preflight_by_digest.clear()
        self._proof_by_digest.clear()
        self._preflight_source_by_digest.clear()
        self._latest_digest_by_selector.clear()


def build_dataset_validation_signature(
    dataset: AirflowDataset,
    velocity_field_name: str,
) -> DatasetValidationSignature:
    """Fingerprint the validation contract without rereading VTI payloads.

    The digest includes the full manifest bytes, selector, chosen velocity
    field, validation-contract version, and each ordered sample's resolved
    path/size/mtime.  That makes normal Houdini re-exports invalidate receipts
    cheaply while avoiding byte-hashing multi-gigabyte VTI sequences at startup.
    """

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
