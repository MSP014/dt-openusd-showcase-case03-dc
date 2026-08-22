"""Focused telemetry configuration workflow validation contracts."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from digital_twin_runtime_suite.app.telemetry.config import (
    COMPONENT_TUNING_GROUPS,
    TelemetryConfig,
)
from digital_twin_runtime_suite.app.telemetry.provider import SyntheticTelemetryProvider

CONFIG_PATH = Path("configs/telemetry_provider.toml")


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


@pytest.mark.parametrize("group_metric", ("nvme_temp_c", "ram_temp_c"))
def test_grouped_thermal_tuning_updates_every_repeated_metric(tmp_path, group_metric):
    module = _load_workflow()
    config_path = tmp_path / "telemetry_provider.toml"
    config_path.write_text(CONFIG_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    config = TelemetryConfig.load(config_path, apply_local_overrides=False)
    provider = SyntheticTelemetryProvider(config, seed=1)
    edit = module.TelemetryConfigEdit(
        default_mode="Nominal",
        default_refresh_interval_s=1.0,
        provider_tick_seconds=1.0,
        interpolation_factor=0.5,
        mode_name="Nominal",
        metric_ids=COMPONENT_TUNING_GROUPS[group_metric],
        target=45.0,
        jitter=0.4,
        minimum=35.0,
        maximum=55.0,
    )

    replacement = module.TelemetryConfigWorkflow(config_path).save(provider, edit)

    assert all(
        replacement.config.modes["Nominal"].numeric[metric_id].target == 45.0
        for metric_id in COMPONENT_TUNING_GROUPS[group_metric]
    )


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
