# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""Presentation-plan spatial-weight normalization coverage."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from digital_twin_runtime_suite.app.heatmaps.presentation import (
    _normalized_thermal_weights,
)


def test_presentation_normalizes_every_semantic_component_independently() -> None:
    catalog = SimpleNamespace(
        targets=(
            _target("/motherboard/vrm_west/radiator", "motherboard/vrm_west"),
            _target("/motherboard/vrm_west/top", "motherboard/vrm_west"),
            _target("/gpu_01/vrm", "gpu_01/vrm"),
        ),
        preflight=SimpleNamespace(
            valid_targets=(
                _metadata("/motherboard/vrm_west/radiator", (0.56, 0.85)),
                _metadata("/motherboard/vrm_west/top", (0.56, 0.655)),
                _metadata("/gpu_01/vrm", (0.25, 0.75)),
            )
        ),
    )

    normalized = _normalized_thermal_weights(catalog)

    assert normalized["/motherboard/vrm_west/radiator"] == pytest.approx((0.0, 1.0))
    assert normalized["/motherboard/vrm_west/top"] == pytest.approx(
        (0.0, 0.3275862068965517)
    )
    assert normalized["/gpu_01/vrm"] == pytest.approx((0.0, 1.0))


def _target(prim_path: str, calibration_id: str) -> SimpleNamespace:
    return SimpleNamespace(prim_path=prim_path, calibration_id=calibration_id)


def _metadata(prim_path: str, weights: tuple[float, ...]) -> SimpleNamespace:
    return SimpleNamespace(prim_path=prim_path, thermal_weight=weights)
