"""Regression coverage for the production-neutral in-place retarget primitive."""

from __future__ import annotations

import asyncio
from pathlib import Path

from digital_twin_runtime_suite.app.flow.temporal import (
    retarget_kit_cae_temporal_source_in_place,
)


def test_in_place_retarget_authors_reads_back_and_refreshes_without_lifecycle_calls(
    tmp_path,
):
    stage = _FakeStage()
    field_prim = _FakeFieldPrim()
    current_source = tmp_path / "source_a.vti"
    target_source = tmp_path / "source_b.vti"
    target_time_code = 42.0
    field_prim.file_names.values[target_time_code] = [_FakeAssetPath(current_source)]
    sync_calls = []

    async def sync_active_controller():
        sync_calls.append("sync")
        return True

    result = asyncio.run(
        retarget_kit_cae_temporal_source_in_place(
            stage,
            field_prim,
            target_source,
            target_time_code,
            _FakeCaeVtk,
            _FakeSdf,
            _FakeUsd,
            sync_active_controller=sync_active_controller,
        )
    )

    assert field_prim.file_names.values[target_time_code][0].path == str(target_source)
    assert result.resolved_source == target_source
    assert result.authoring_succeeded is True
    assert result.refresh_requested is True
    assert sync_calls == ["sync"]
    assert stage.edit_targets == [stage.session_layer, stage.original_edit_target]
    assert stage.lifecycle_calls == []


def test_in_place_retarget_can_defer_refresh_without_second_cae_sync(tmp_path):
    stage = _FakeStage()
    field_prim = _FakeFieldPrim()
    target_source = tmp_path / "source_b.vti"
    target_time_code = 42.0
    sync_calls = []

    async def sync_active_controller():
        sync_calls.append("sync")
        return True

    result = asyncio.run(
        retarget_kit_cae_temporal_source_in_place(
            stage,
            field_prim,
            target_source,
            target_time_code,
            _FakeCaeVtk,
            _FakeSdf,
            _FakeUsd,
            sync_active_controller=sync_active_controller,
            refresh=False,
        )
    )

    assert result.authoring_succeeded is True
    assert result.resolved_source == target_source
    assert result.refresh_requested is False
    assert sync_calls == []
    assert stage.lifecycle_calls == []


class _FakeStage:
    def __init__(self):
        self.original_edit_target = object()
        self.session_layer = object()
        self.edit_targets = []
        self.lifecycle_calls = []

    def GetEditTarget(self):
        return self.original_edit_target

    def GetSessionLayer(self):
        return self.session_layer

    def SetEditTarget(self, edit_target):
        self.edit_targets.append(edit_target)

    def Attach(self):
        self.lifecycle_calls.append("Attach")

    def Detach(self):
        self.lifecycle_calls.append("Detach")

    def Reset(self):
        self.lifecycle_calls.append("Reset")


class _FakeFieldPrim:
    def __init__(self):
        self.file_names = _FakeFileNamesAttribute()


class _FakeCaeVtk:
    @staticmethod
    def FieldArray(field_prim):
        return _FakeFieldArray(field_prim.file_names)


class _FakeFieldArray:
    def __init__(self, file_names):
        self._file_names = file_names

    def GetFileNamesAttr(self):
        return self._file_names


class _FakeFileNamesAttribute:
    def __init__(self):
        self.values = {}

    def IsValid(self):
        return True

    def Set(self, values, time_code):
        self.values[time_code] = values
        return True

    def Get(self, time_code):
        return self.values.get(time_code)


class _FakeAssetPath:
    def __init__(self, path):
        self.path = str(Path(path))
        self.resolvedPath = self.path


class _FakeSdf:
    AssetPath = _FakeAssetPath


class _FakeUsd:
    @staticmethod
    def TimeCode(value):
        return value
