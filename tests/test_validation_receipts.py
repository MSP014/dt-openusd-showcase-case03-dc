"""Focused persisted validation-receipt storage and VTI reuse contracts."""

from __future__ import annotations

import json
from types import SimpleNamespace

from digital_twin_runtime_suite.app.airflow_validation.cache import (
    DatasetValidationSignature,
    SessionValidationCache,
)
from digital_twin_runtime_suite.app.commands import RuntimeController
from digital_twin_runtime_suite.app.validation_receipts import (
    ValidationReceiptStore,
)


def test_vti_preflight_persists_and_reuses_without_temporal_proof(tmp_path):
    store = ValidationReceiptStore(tmp_path / "receipts.local.json")
    signature = DatasetValidationSignature("server/load_normal", "digest-a")
    first = SessionValidationCache(
        persisted_store=store,
        reuse_persisted=True,
    )
    fresh_metadata = _preflight_metadata(dimensions=(10, 11, 12))
    first.store_preflight(signature, fresh_metadata, True)
    first.store_temporal_proof(signature, 80, 16.0)

    restarted_store = ValidationReceiptStore(store.path)
    restarted = SessionValidationCache(
        persisted_store=restarted_store,
        reuse_persisted=True,
    )
    lookup = restarted.lookup(signature)

    assert lookup.receipt_source == "PERSISTED"
    assert lookup.preflight is not None
    assert lookup.preflight.metadata == fresh_metadata
    for field in (
        "dimensions",
        "origin",
        "vti_header_origin",
        "vtk_reader_origin",
        "spacing",
        "bounds",
    ):
        assert isinstance(lookup.preflight.metadata[field], tuple)
        assert type(lookup.preflight.metadata[field]) is type(fresh_metadata[field])
    assert lookup.temporal_proof is None
    payload = json.loads(store.path.read_text(encoding="utf-8"))
    assert "temporal_proof" not in json.dumps(payload)
    assert not store.path.with_name(f"{store.path.name}.tmp").exists()


def test_changed_vti_signature_invalidates_only_its_workload(tmp_path):
    store = ValidationReceiptStore(tmp_path / "receipts.local.json")
    first = SessionValidationCache(
        persisted_store=store,
        reuse_persisted=True,
    )
    idle = DatasetValidationSignature("server/load_idle", "idle-a")
    nominal = DatasetValidationSignature("server/load_normal", "normal-a")
    first.store_preflight(idle, _preflight_metadata(), True)
    first.store_preflight(nominal, _preflight_metadata(), True)

    restarted_store = ValidationReceiptStore(store.path)
    restarted = SessionValidationCache(
        persisted_store=restarted_store,
        reuse_persisted=True,
    )
    unchanged = restarted.lookup(idle)
    changed = restarted.lookup(
        DatasetValidationSignature("server/load_normal", "normal-b")
    )
    metrics = restarted_store.metrics_snapshot()

    assert unchanged.receipt_source == "PERSISTED"
    assert changed.preflight is None
    assert metrics.vti.persisted_reused == 1
    assert metrics.vti.invalidated == 1


def test_disabled_vti_reuse_ignores_matching_persisted_receipt(tmp_path):
    store = ValidationReceiptStore(tmp_path / "receipts.local.json")
    signature = DatasetValidationSignature("server/load_normal", "digest-a")
    enabled = SessionValidationCache(
        persisted_store=store,
        reuse_persisted=True,
    )
    enabled.store_preflight(signature, _preflight_metadata(), True)

    disabled = SessionValidationCache(
        persisted_store=ValidationReceiptStore(store.path),
        reuse_persisted=False,
    )

    assert disabled.lookup(signature).preflight is None


def test_malformed_receipt_store_falls_back_to_empty_state(tmp_path, caplog):
    path = tmp_path / "receipts.local.json"
    path.write_text("{not json", encoding="utf-8")
    store = ValidationReceiptStore(path)

    assert store.persisted_counts() == (0, 0)
    assert "Ignoring malformed validation receipt store" in caplog.text


def test_acceptance_checkpoint_is_separate_from_validation_evidence(tmp_path):
    store = ValidationReceiptStore(tmp_path / "receipts.local.json")
    signature = DatasetValidationSignature("server/load_normal", "digest-a")
    cache = SessionValidationCache(persisted_store=store, reuse_persisted=True)
    cache.store_preflight(signature, _preflight_metadata(), True)
    store.write_acceptance_checkpoint(
        {"phase": "AWAITING_RESTART", "baseline_identities": {"vti": {}}}
    )

    assert store.load_acceptance_checkpoint()["phase"] == "AWAITING_RESTART"
    store.clear_acceptance_checkpoint()

    assert store.load_acceptance_checkpoint() is None
    assert (
        ValidationReceiptStore(store.path)
        .lookup_vti(
            signature.selector,
            signature.digest,
        )
        .status
        == "HIT"
    )


def test_persisted_metadata_is_accepted_by_real_kit_cae_grid_comparison(tmp_path):
    store = ValidationReceiptStore(tmp_path / "receipts.local.json")
    signature = DatasetValidationSignature("server/load_normal", "digest-a")
    fresh = SessionValidationCache(persisted_store=store, reuse_persisted=True)
    fresh.store_preflight(signature, _preflight_metadata(), True)
    restored_cache = SessionValidationCache(
        persisted_store=ValidationReceiptStore(store.path),
        reuse_persisted=True,
    )
    restored = restored_cache.lookup(signature).preflight

    imported = RuntimeController._validate_kit_cae_velocity_field(
        _DatasetPrim(),
        _FieldPrim(),
        restored.metadata,
        _Cae,
        _CaeVtk,
    )

    assert imported["spacing"] == restored.metadata["spacing"]
    assert restored.metadata["dimensions"] == (2, 2, 2)


def test_persisted_origin_provenance_survives_session_insertion(tmp_path):
    store = ValidationReceiptStore(tmp_path / "receipts.local.json")
    signature = DatasetValidationSignature("server/load_normal", "digest-a")
    first = SessionValidationCache(persisted_store=store, reuse_persisted=True)
    first.store_preflight(signature, _preflight_metadata(), True)
    restarted_store = ValidationReceiptStore(store.path)
    restarted = SessionValidationCache(
        persisted_store=restarted_store,
        reuse_persisted=True,
    )

    restored = restarted.lookup(signature)
    reused_from_session = restarted.lookup(signature)
    metrics = restarted_store.metrics_snapshot().vti

    assert restored.receipt_source == "PERSISTED"
    assert reused_from_session.receipt_source == "PERSISTED"
    assert reused_from_session.cache_location == "SESSION"
    assert metrics.persisted_reused == 1
    assert metrics.session_reused == 0


def _preflight_metadata(*, dimensions=(2, 2, 2)):
    return {
        "components": 3,
        "data_type": "float",
        "dimensions": dimensions,
        "point_count": dimensions[0] * dimensions[1] * dimensions[2],
        "origin": (1.0, 2.0, 3.0),
        "vti_header_origin": (1.0, 2.0, 3.0),
        "vtk_reader_origin": (1.0, 2.0, 3.0),
        "spacing": (0.1, 0.2, 0.3),
        "bounds": (1.0, 1.1, 2.0, 2.2, 3.0, 3.3),
        "velocity_magnitude_max": 4.5,
        "kit_cae_direct_attach_base_velocity_scale": 0.25,
        "velocity_field_name": "vel",
        "velocity_field_association": "point_data",
    }


class _Attribute:
    def __init__(self, value):
        self._value = value

    def Get(self):
        return self._value


class _DatasetPrim:
    def IsA(self, _type):
        return True

    def HasAPI(self, _api):
        return True


class _FieldPrim:
    @staticmethod
    def GetTypeName():
        return "CaeVtkFieldArray"

    @staticmethod
    def GetAttribute(_name):
        return _Attribute("vertex")


class _DenseVolume:
    @staticmethod
    def GetMinExtentAttr():
        return _Attribute((0, 0, 0))

    @staticmethod
    def GetMaxExtentAttr():
        return _Attribute((1, 1, 1))

    @staticmethod
    def GetSpacingAttr():
        return _Attribute((0.1, 0.2, 0.3))


class _ImageData:
    @staticmethod
    def GetOriginAttr():
        return _Attribute((1.0, 2.0, 3.0))


class _Cae:
    DataSet = object()
    DenseVolumeAPI = staticmethod(lambda _prim: _DenseVolume())
    Tokens = SimpleNamespace(vertex="vertex")


class _CaeVtk:
    ImageDataAPI = staticmethod(lambda _prim: _ImageData())
