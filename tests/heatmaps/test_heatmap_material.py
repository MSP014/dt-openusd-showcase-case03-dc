"""Generic MDL contract coverage independent of a running Kit application."""

from __future__ import annotations

from pathlib import Path


def test_generic_mdl_uses_direct_weight_and_configurable_palette() -> None:
    mdl_path = (
        Path(__file__).parents[2]
        / "src"
        / "digital_twin_runtime_suite"
        / "ext"
        / "msp.dtrs"
        / "data"
        / "materials"
        / "DTRS_Heatmap.mdl"
    )
    source = mdl_path.read_text(encoding="utf-8")

    assert "DTRS_Heatmap(" in source
    assert "active_stop_count" in source
    assert "temperature_offset_celsius" in source
    assert "minimum_clamp_scalar" in source
    assert "maximum_clamp_scalar" in source
    assert "temperature_preview" not in source
    assert "cold_biased" not in source
    assert "thermal_weight_remap" not in source
