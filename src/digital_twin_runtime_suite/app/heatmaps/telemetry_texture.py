# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""GPU-side dynamic texture transport for Heatmap telemetry scalars."""

from __future__ import annotations

import ctypes
import struct
from array import array
from collections.abc import Iterable, Mapping

_PY_CAPSULE_NEW = ctypes.pythonapi.PyCapsule_New
_PY_CAPSULE_NEW.argtypes = (ctypes.c_void_p, ctypes.c_char_p, ctypes.c_void_p)
_PY_CAPSULE_NEW.restype = ctypes.py_object


class HeatmapTelemetryTexture:
    """Own one fixed-size R32 texture without writing USD after activation."""

    NAME = "dtrs_heatmap_telemetry"
    WIDTH = 256

    def __init__(self, provider, texture_format, *, width: int = WIDTH) -> None:
        if width <= 0:
            raise ValueError("Heatmap telemetry texture width must be positive.")
        self._provider = provider
        self._texture_format = texture_format
        self._width = width
        self._indices: dict[str, int] = {}
        self._pixels = (0.0,) * width

    @classmethod
    def create_runtime(cls) -> HeatmapTelemetryTexture:
        """Create the named Kit provider retained for one active presentation."""

        try:
            import omni.ui as ui
        except ModuleNotFoundError:
            # OpenUSD-only production-stage tests verify Session composition
            # without Kit's renderer. The extension dependency supplies omni.ui
            # whenever this presentation is actually shown in Kit.
            return cls(_OpenUsdValidationProvider(), "R32_SFLOAT")

        return cls(
            ui.DynamicTextureProvider(cls.NAME),
            ui.TextureFormat.R32_SFLOAT,
        )

    @property
    def dynamic_url(self) -> str:
        """Return the activation-time MDL source URL for the shared texture."""

        return f"dynamic://{self.NAME}"

    @property
    def active(self) -> bool:
        """Return whether this instance still owns a Kit texture provider."""

        return self._provider is not None

    def register_material_keys(self, material_keys: Iterable[str]) -> dict[str, int]:
        """Assign stable texels to newly active material groups."""

        self._require_provider()
        resolved: dict[str, int] = {}
        for material_key in sorted(set(material_keys)):
            index = self._indices.get(material_key)
            if index is None:
                index = len(self._indices)
                if index >= self._width:
                    raise RuntimeError(
                        "Heatmap telemetry texture has no free material texels."
                    )
                self._indices[material_key] = index
            resolved[material_key] = index
        return resolved

    def update(self, telemetry_by_material_key: Mapping[str, float]) -> bool:
        """Upload R32 values only when the fixed texture payload changed."""

        self._require_provider()
        pixels = list(self._pixels)
        changed = False
        for material_key, telemetry_celsius in telemetry_by_material_key.items():
            index = self._indices.get(material_key)
            if index is None:
                continue
            value = _as_float32(telemetry_celsius)
            if pixels[index] == value:
                continue
            pixels[index] = value
            changed = True
        if not changed:
            return False
        self._pixels = tuple(pixels)
        self._upload_pixels()
        return True

    def release(self) -> None:
        """Drop the provider and its stage-specific index ownership."""

        self._provider = None
        self._indices.clear()
        self._pixels = (0.0,) * self._width

    def _upload_pixels(self) -> None:
        """Pass one transient contiguous R32 payload to Kit's texture provider."""

        pixels = array("f", self._pixels)
        if pixels.itemsize != 4:
            raise RuntimeError(
                "Heatmap telemetry texture requires 32-bit float pixels."
            )
        capsule = _PY_CAPSULE_NEW(
            ctypes.c_void_p(pixels.buffer_info()[0]),
            None,
            None,
        )
        self._provider.set_raw_bytes_data(
            capsule,
            [self._width, 1],
            self._texture_format,
        )

    def _require_provider(self) -> None:
        if self._provider is None:
            raise RuntimeError("Heatmap telemetry texture is inactive.")


def _as_float32(value: float) -> float:
    """Match the R32 payload before deciding whether another upload is needed."""

    return struct.unpack("<f", struct.pack("<f", float(value)))[0]


class _OpenUsdValidationProvider:
    """Accept R32 payloads when an OpenUSD-only test has no Kit renderer."""

    @staticmethod
    def set_raw_bytes_data(_capsule, _dimensions, _texture_format) -> None:
        return
