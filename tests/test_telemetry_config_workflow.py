"""Focused telemetry configuration workflow validation contracts."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("provider_tick_seconds", 0.0, "Provider tick"),
        ("interpolation_factor", 0.0, "Interpolation"),
        ("jitter", -0.1, "Jitter"),
    ),
)
def test_invalid_scalar_edit_is_rejected_before_persistence(field, value, message):
    module = _load_workflow()
    payload = _edit_payload()
    payload[field] = value
    edit = module.TelemetryConfigEdit(**payload)

    with pytest.raises(ValueError, match=message):
        module.TelemetryConfigWorkflow._validate(edit)


def test_target_must_stay_inside_the_safe_range():
    module = _load_workflow()
    payload = _edit_payload()
    payload["target"] = 101.0
    edit = module.TelemetryConfigEdit(**payload)

    with pytest.raises(ValueError, match="Target"):
        module.TelemetryConfigWorkflow._validate(edit)


def _edit_payload() -> dict[str, object]:
    return {
        "default_mode": "Nominal",
        "default_refresh_interval_s": 1.0,
        "provider_tick_seconds": 1.0,
        "interpolation_factor": 0.5,
        "mode_name": "Nominal",
        "metric_ids": ("cpu_utilization",),
        "target": 50.0,
        "jitter": 1.0,
        "minimum": 0.0,
        "maximum": 100.0,
    }


def _load_workflow():
    path = (
        Path(__file__).parents[1]
        / "src"
        / "digital_twin_runtime_suite"
        / "ext"
        / "msp.dtrs"
        / "msp"
        / "dtrs"
        / "workflows"
        / "telemetry_config.py"
    )
    spec = importlib.util.spec_from_file_location("telemetry_config_workflow", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module
