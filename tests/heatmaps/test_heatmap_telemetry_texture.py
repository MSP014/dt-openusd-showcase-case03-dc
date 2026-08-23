"""Focused dynamic-texture telemetry transport contracts."""

from __future__ import annotations

import pytest

from digital_twin_runtime_suite.app.heatmaps.material import (
    HeatmapMaterialPresenter,
)
from digital_twin_runtime_suite.app.heatmaps.telemetry_texture import (
    HeatmapTelemetryTexture,
)


class _Provider:
    def __init__(self) -> None:
        self.uploads: list[tuple[object, list[int], object]] = []

    def set_raw_bytes_data(self, capsule, dimensions, texture_format) -> None:
        self.uploads.append((capsule, dimensions, texture_format))


def test_texture_assigns_stable_sorted_texels_and_uploads_one_r32_row() -> None:
    provider = _Provider()
    texture = HeatmapTelemetryTexture(provider, "R32", width=4)

    indices = texture.register_material_keys(("gpu_03", "cpu", "gpu_01"))
    uploaded = texture.update({"gpu_03": 73.25, "cpu": 54.5, "gpu_01": 61.0})

    assert indices == {"cpu": 0, "gpu_01": 1, "gpu_03": 2}
    assert uploaded
    assert texture._pixels == pytest.approx((54.5, 61.0, 73.25, 0.0))
    assert len(provider.uploads) == 1
    assert provider.uploads[0][1:] == ([4, 1], "R32")


def test_texture_skips_upload_when_r32_payload_is_unchanged() -> None:
    provider = _Provider()
    texture = HeatmapTelemetryTexture(provider, "R32", width=2)
    texture.register_material_keys(("gpu_01",))

    assert texture.update({"gpu_01": 60.125})
    assert not texture.update({"gpu_01": 60.125})

    assert len(provider.uploads) == 1


def test_texture_release_invalidates_stage_specific_provider_and_indices() -> None:
    texture = HeatmapTelemetryTexture(_Provider(), "R32", width=1)
    texture.register_material_keys(("gpu_01",))

    texture.release()

    assert not texture.active
    assert texture._indices == {}
    with pytest.raises(RuntimeError, match="inactive"):
        texture.update({"gpu_01": 60.0})


def test_periodic_presenter_update_only_uploads_texture_data() -> None:
    presenter = HeatmapMaterialPresenter()
    texture = _Texture()
    presenter._material_keys.add("gpu_01")
    presenter._telemetry_texture = texture
    presenter._session_layer_id = "current"
    stage = _Stage()

    result = presenter.update_telemetry(stage, {"gpu_01": 67.0})

    assert result.success
    assert texture.updates == [{"gpu_01": 67.0}]


def test_stage_replacement_releases_the_old_texture_owner() -> None:
    presenter = HeatmapMaterialPresenter()
    texture = _Texture()
    presenter._session_layer_id = "old"
    presenter._telemetry_texture = texture

    presenter.discard_stale_stage(_Stage(identifier="replacement"))

    assert texture.released
    assert presenter._telemetry_texture is None


class _Texture:
    def __init__(self) -> None:
        self.updates: list[dict[str, float]] = []
        self.released = False

    def update(self, telemetry_by_material_key) -> bool:
        self.updates.append(dict(telemetry_by_material_key))
        return True

    def release(self) -> None:
        self.released = True


class _Stage:
    def __init__(self, *, identifier: str = "current") -> None:
        self._identifier = identifier

    def GetSessionLayer(self):
        return type("_Session", (), {"identifier": self._identifier})()
