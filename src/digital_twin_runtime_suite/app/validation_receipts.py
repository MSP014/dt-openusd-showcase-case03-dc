# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""Versioned local persistence for previously proven validation receipts."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any

LOGGER = logging.getLogger(__name__)
RECEIPT_STORE_SCHEMA_VERSION = 1
ACCEPTANCE_CHECKPOINT_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class PersistedReceiptLookup:
    """One cheap persisted-receipt identity decision."""

    status: str
    payload: dict[str, Any] | None = None


@dataclass(frozen=True)
class ValidationReceiptKindMetrics:
    """Per-resource events observed during the current DTRS process."""

    persisted_reused: int
    session_reused: int
    fresh_validated: int
    invalidated: int
    expensive_validation_calls: int
    geometry_sha256_recomputed: int = 0


@dataclass(frozen=True)
class ValidationReceiptMetricsSnapshot:
    """VTI and Streamlines receipt activity for logging and acceptance."""

    vti: ValidationReceiptKindMetrics
    streamlines: ValidationReceiptKindMetrics


class ValidationReceiptStore:
    """Own one atomic gitignored JSON store for VTI and Streamlines evidence."""

    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self.acceptance_checkpoint_path = self.path.with_name("acceptance.local.json")
        self._lock = Lock()
        self._state: dict[str, Any] | None = None
        self._events = {
            "vti": {
                "PERSISTED": set(),
                "SESSION": set(),
                "FRESH": set(),
                "INVALIDATED": set(),
            },
            "streamlines": {
                "PERSISTED": set(),
                "SESSION": set(),
                "FRESH": set(),
                "INVALIDATED": set(),
            },
        }
        self._expensive_calls = {"vti": 0, "streamlines": 0}
        self._geometry_hash_calls = 0

    @staticmethod
    def default_path(repo_root: Path) -> Path:
        """Return the shared local-state path already covered by ``cache/``."""

        return repo_root / "cache" / "validation" / "receipts.local.json"

    def lookup_vti(self, selector: str, digest: str) -> PersistedReceiptLookup:
        """Reuse one strongly validated VTI preflight by exact signature."""

        with self._lock:
            entry = self._load_state()["vti"].get(selector)
            if not isinstance(entry, dict):
                return PersistedReceiptLookup("MISS")
            if entry.get("signature_digest") != digest:
                self._record_locked("vti", "INVALIDATED", selector)
                return PersistedReceiptLookup("INVALIDATED")
            return PersistedReceiptLookup("HIT", dict(entry))

    def store_vti(
        self,
        *,
        selector: str,
        signature_digest: str,
        metadata: dict[str, object],
        grid_match: bool,
        validation_contract_version: str,
    ) -> None:
        """Atomically persist a completed deterministic VTI preflight PASS."""

        payload = {
            "selector": selector,
            "signature_digest": signature_digest,
            "validation_contract_version": validation_contract_version,
            "metadata": metadata,
            "grid_match": bool(grid_match),
        }
        with self._lock:
            state = self._load_state()
            state["vti"][selector] = _json_safe(payload)
            self._write_state(state)

    def lookup_streamlines(
        self,
        *,
        key: str,
        resource_fingerprint: tuple[str, str],
        dependency_identity: tuple[str, str],
    ) -> PersistedReceiptLookup:
        """Reuse one valid cache only while all cheap identities still match."""

        with self._lock:
            entry = self._load_state()["streamlines"].get(key)
            if not isinstance(entry, dict):
                return PersistedReceiptLookup("MISS")
            fingerprint_matches = entry.get("resource_fingerprint") == list(
                resource_fingerprint
            )
            dependency_matches = entry.get("dependency_identity") == list(
                dependency_identity
            )
            if not fingerprint_matches or not dependency_matches:
                self._record_locked("streamlines", "INVALIDATED", key)
                return PersistedReceiptLookup("INVALIDATED")
            return PersistedReceiptLookup("HIT", dict(entry))

    def store_streamlines(self, *, key: str, payload: dict[str, object]) -> None:
        """Atomically persist one completed strong Streamlines VALID receipt."""

        with self._lock:
            state = self._load_state()
            state["streamlines"][key] = _json_safe(payload)
            self._write_state(state)

    def record_reuse(self, kind: str, source: str, key: str) -> None:
        """Record one resource source without changing persisted evidence."""

        with self._lock:
            self._record_locked(kind, source, key)

    def record_invalidation(self, kind: str, key: str) -> None:
        """Record rejected persisted evidence after owner-level payload checks."""

        with self._lock:
            self._record_locked(kind, "INVALIDATED", key)

    def record_expensive_validation(self, kind: str) -> None:
        """Instrument the actual expensive-worker boundary for acceptance."""

        with self._lock:
            self._expensive_calls[kind] += 1

    def record_geometry_sha256_recomputed(self) -> None:
        """Record an actual Streamlines geometry hash after validation reaches it."""

        with self._lock:
            self._geometry_hash_calls += 1

    def metrics_snapshot(self) -> ValidationReceiptMetricsSnapshot:
        """Return immutable counters without filesystem or validation work."""

        with self._lock:
            return ValidationReceiptMetricsSnapshot(
                vti=self._kind_metrics_locked("vti"),
                streamlines=self._kind_metrics_locked("streamlines"),
            )

    def persisted_counts(self) -> tuple[int, int]:
        """Count stored evidence without validating current resource identity."""

        with self._lock:
            state = self._load_state()
            return len(state["vti"]), len(state["streamlines"])

    def has_vti(self, selector: str, digest: str) -> bool:
        """Check current VTI coverage without recording a reuse event."""

        with self._lock:
            entry = self._load_state()["vti"].get(selector)
            return bool(
                isinstance(entry, dict)
                and entry.get("signature_digest") == digest
                and isinstance(entry.get("validation_contract_version"), str)
                and isinstance(entry.get("metadata"), dict)
                and isinstance(entry.get("grid_match"), bool)
            )

    def has_streamlines(
        self,
        *,
        key: str,
        resource_fingerprint: tuple[str, str],
        dependency_identity: tuple[str, str],
    ) -> bool:
        """Check current cache coverage without recording a reuse event."""

        with self._lock:
            entry = self._load_state()["streamlines"].get(key)
            return bool(
                isinstance(entry, dict)
                and entry.get("classification") == "VALID"
                and entry.get("resource_fingerprint") == list(resource_fingerprint)
                and entry.get("dependency_identity") == list(dependency_identity)
                and isinstance(entry.get("validation_contract_version"), str)
                and isinstance(entry.get("compatibility_identity"), list)
                and isinstance(entry.get("static_source"), dict)
                and isinstance(entry.get("geometry_sha256"), str)
            )

    def write_acceptance_checkpoint(self, payload: dict[str, object]) -> None:
        """Persist restart orchestration separately from validation evidence."""

        state = {
            "schema_version": ACCEPTANCE_CHECKPOINT_SCHEMA_VERSION,
            **_json_safe(payload),
        }
        with self._lock:
            self._atomic_write(self.acceptance_checkpoint_path, state)

    def load_acceptance_checkpoint(self) -> dict[str, Any] | None:
        """Read the tiny restart checkpoint; malformed state cancels acceptance."""

        with self._lock:
            try:
                data = json.loads(
                    self.acceptance_checkpoint_path.read_text(encoding="utf-8")
                )
            except FileNotFoundError:
                return None
            except (OSError, json.JSONDecodeError) as error:
                LOGGER.warning(
                    "Ignoring malformed validation acceptance checkpoint %s: %s",
                    self.acceptance_checkpoint_path,
                    error,
                )
                return None
            if data.get("schema_version") != ACCEPTANCE_CHECKPOINT_SCHEMA_VERSION:
                LOGGER.warning(
                    "Ignoring unsupported validation acceptance checkpoint %s.",
                    self.acceptance_checkpoint_path,
                )
                return None
            return data

    def clear_acceptance_checkpoint(self) -> None:
        """Remove only a terminal acceptance checkpoint, never receipt evidence."""

        with self._lock:
            try:
                self.acceptance_checkpoint_path.unlink()
            except FileNotFoundError:
                return

    def _load_state(self) -> dict[str, Any]:
        if self._state is not None:
            return self._state
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data.get("schema_version") != RECEIPT_STORE_SCHEMA_VERSION:
                raise ValueError("unsupported receipt-store schema")
            if not isinstance(data.get("vti"), dict) or not isinstance(
                data.get("streamlines"), dict
            ):
                raise ValueError("receipt-store sections are malformed")
        except FileNotFoundError:
            data = self._empty_state()
        except (OSError, ValueError, json.JSONDecodeError) as error:
            LOGGER.warning(
                "Ignoring malformed validation receipt store %s: %s",
                self.path,
                error,
            )
            data = self._empty_state()
        self._state = data
        return data

    @staticmethod
    def _empty_state() -> dict[str, Any]:
        return {
            "schema_version": RECEIPT_STORE_SCHEMA_VERSION,
            "vti": {},
            "streamlines": {},
        }

    def _write_state(self, state: dict[str, Any]) -> None:
        self._atomic_write(self.path, state)
        self._state = state

    @staticmethod
    def _atomic_write(path: Path, state: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f"{path.name}.tmp")
        temporary.write_text(
            json.dumps(state, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)

    def _record_locked(self, kind: str, source: str, key: str) -> None:
        if source in {"PERSISTED", "SESSION", "FRESH"}:
            for evidence_source in ("PERSISTED", "SESSION", "FRESH"):
                self._events[kind][evidence_source].discard(key)
        self._events[kind][source].add(key)

    def _kind_metrics_locked(self, kind: str) -> ValidationReceiptKindMetrics:
        events = self._events[kind]
        return ValidationReceiptKindMetrics(
            persisted_reused=len(events["PERSISTED"]),
            session_reused=len(events["SESSION"]),
            fresh_validated=len(events["FRESH"]),
            invalidated=len(events["INVALIDATED"]),
            expensive_validation_calls=self._expensive_calls[kind],
            geometry_sha256_recomputed=(
                self._geometry_hash_calls if kind == "streamlines" else 0
            ),
        )


def _json_safe(payload: Any) -> Any:
    """Return a detached JSON-compatible copy or raise before store mutation."""

    return json.loads(json.dumps(payload, sort_keys=True))
