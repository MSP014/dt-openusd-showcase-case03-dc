# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""Telemetry binding coverage separated from calibration and presentation policy."""

from __future__ import annotations

from digital_twin_runtime_suite.app.heatmaps.bindings import (
    HardwareIdentity,
    SemanticKey,
    resolve_telemetry_binding,
)


def test_bindings_answer_only_semantic_target_to_metric() -> None:
    gpu = resolve_telemetry_binding(
        SemanticKey(HardwareIdentity("gpu", 1), "gpu_core", "gb203_die")
    )
    motherboard_dimm = resolve_telemetry_binding(
        SemanticKey(HardwareIdentity("ram", 3), "memory", "dimm_slot")
    )

    assert gpu.metric_id == "gpu_1_hotspot_temp_c"
    assert motherboard_dimm.metric_id == "ram_3_temp_c"
    assert not hasattr(gpu, "presentation_temperature_offset_celsius")
