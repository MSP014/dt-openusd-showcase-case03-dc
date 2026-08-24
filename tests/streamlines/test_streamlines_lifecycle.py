# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""Focused contracts for DTRS-owned Streamlines teardown."""

from __future__ import annotations

from digital_twin_runtime_suite.app.streamlines.lifecycle import (
    STATIC_VELOCITY_SOURCE_ROOT,
    StreamlinesCleanupReceipt,
    format_streamlines_cleanup_receipt,
    inspect_streamlines_runtime_cleanup,
    remove_streamlines_runtime_roots_from_layers,
)


def test_package_d_cleanup_removes_canonical_and_suffixed_runtime_roots():
    stage = _FakeStage(
        {
            STATIC_VELOCITY_SOURCE_ROOT,
            "/DTRS_HoudiniVelocity/VTKImageData",
            "/DTRS_KitCAE/Streamlines_001",
            "/DTRS_KitCAE/Streamlines_001/StaticVelocityProof",
            "/DTRS_KitCAE/StreamlineSeeds",
            "/DTRS_KitCAE/StreamlineSeeds/DiagnosticUnitSphere",
        }
    )

    removed = remove_streamlines_runtime_roots_from_layers(stage)
    receipt = inspect_streamlines_runtime_cleanup(stage, pending_tasks=0)

    assert STATIC_VELOCITY_SOURCE_ROOT in removed
    assert "/DTRS_KitCAE/Streamlines_001" in removed
    assert stage.paths == set()
    assert receipt.clean
    assert receipt.duplicate_prims == 0


def test_package_d_cleanup_receipt_is_compact_and_explicit_when_clean():
    receipt = StreamlinesCleanupReceipt(
        source_present=False,
        operator_present=False,
        seed_present=False,
        runtime_preview_present=False,
        stale_relationships=0,
        remaining_layer_specs=0,
        duplicate_prims=0,
        pending_tasks=0,
    )

    report = format_streamlines_cleanup_receipt(receipt)

    assert receipt.clean
    assert "source_present=False" in report
    assert "remaining_layer_specs=0" in report
    assert "pending_tasks=0" in report
    assert report.endswith("result=CLEAN")


class _FakePrim:
    def __init__(self, path: str, children=()):
        self._path = path
        self._children = tuple(children)

    def GetPath(self):
        return self._path

    def GetChildren(self):
        return self._children

    def GetRelationships(self):
        return ()

    def IsValid(self):
        return bool(self._path)


class _InvalidPrim(_FakePrim):
    def __init__(self):
        super().__init__("")

    def IsValid(self):
        return False


class _FakeLayer:
    identifier = "fake"

    def GetPrimAtPath(self, _path):
        return None


class _FakeStage:
    def __init__(self, paths):
        self.paths = set(paths)
        self._layer = _FakeLayer()
        self._edit_target = self._layer

    def GetPseudoRoot(self):
        return _FakePrim("/", tuple(_FakePrim(path) for path in sorted(self.paths)))

    def GetEditTarget(self):
        return self._edit_target

    def SetEditTarget(self, target):
        self._edit_target = target

    def GetSessionLayer(self):
        return self._layer

    def GetRootLayer(self):
        return self._layer

    def GetPrimAtPath(self, path):
        return _FakePrim(path) if path in self.paths else _InvalidPrim()

    def RemovePrim(self, path):
        self.paths = {
            candidate
            for candidate in self.paths
            if candidate != path and not candidate.startswith(f"{path}/")
        }
