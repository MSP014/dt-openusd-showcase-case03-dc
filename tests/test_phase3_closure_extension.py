"""Focused retirement checks for the completed Phase 3.6 acceptance surface."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


def test_phase36_controls_and_callbacks_are_retired(monkeypatch) -> None:
    module = _load_extension(monkeypatch)
    extension = module.DigitalTwinRuntimeSuiteExtension()
    sections: list[str] = []

    class _Scope:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    module.ui.ScrollingFrame = lambda **_kwargs: _Scope()
    module.ui.VStack = lambda **_kwargs: _Scope()
    module.ui.ScrollBarPolicy = types.SimpleNamespace(
        SCROLLBAR_ALWAYS_OFF=object(),
        SCROLLBAR_ALWAYS_ON=object(),
    )
    extension._build_config_section = lambda title, *_args, **_kwargs: sections.append(
        title
    )

    extension._build_view_tab(config=object())

    assert "Streamlines" not in sections
    assert "Airflow cache" in sections
    assert not hasattr(module, "PHASE36_MANUAL_ACCEPTANCE_ENABLED")
    assert not hasattr(
        module.DigitalTwinRuntimeSuiteExtension,
        "_run_phase36_streamlines_final_check",
    )
    assert not hasattr(
        module.DigitalTwinRuntimeSuiteExtension,
        "_run_phase36_recompute_fallback_check",
    )


def test_phase3_acceptance_wiring_is_retired_without_removing_flow_controls(
    monkeypatch,
) -> None:
    module = _load_extension(monkeypatch)
    extension = module.DigitalTwinRuntimeSuiteExtension

    assert not hasattr(module, "PHASE33_MANUAL_ACCEPTANCE_ENABLED")
    assert not hasattr(module, "PHASE35_MANUAL_ACCEPTANCE_ENABLED")
    assert not hasattr(extension, "_report_airflow_acceptance")
    assert not hasattr(extension, "_report_airflow_waiting")
    assert not hasattr(extension, "_schedule_run_production_cache_sanity")
    assert not hasattr(extension, "_schedule_streamlines_cadence_characterization")
    assert hasattr(extension, "_schedule_attach_airflow")
    assert hasattr(extension, "_run_attached_workload_transition")
    assert hasattr(extension, "_schedule_detach_airflow")


def _load_extension(monkeypatch):
    carb = types.ModuleType("carb")
    carb.log_warn = lambda _message: None
    carb.log_error = lambda _message: None
    monkeypatch.setitem(sys.modules, "carb", carb)
    for name in ("settings", "tokens", "windowing"):
        child = types.ModuleType(f"carb.{name}")
        setattr(carb, name, child)
        monkeypatch.setitem(sys.modules, f"carb.{name}", child)

    omni = types.ModuleType("omni")
    omni.__path__ = []
    monkeypatch.setitem(sys.modules, "omni", omni)
    for name in ("appwindow", "ext", "ui"):
        child = types.ModuleType(f"omni.{name}")
        setattr(omni, name, child)
        monkeypatch.setitem(sys.modules, f"omni.{name}", child)
    omni.ext.IExt = object

    path = (
        Path(__file__).parents[1]
        / "src"
        / "digital_twin_runtime_suite"
        / "ext"
        / "msp.dtrs"
        / "msp"
        / "dtrs"
        / "extension.py"
    )
    spec = importlib.util.spec_from_file_location("phase3_closure_extension", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
