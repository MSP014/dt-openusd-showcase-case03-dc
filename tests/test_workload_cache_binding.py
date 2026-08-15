"""Stage 08 workload-to-cache ownership and selector-display contracts."""

import re
from pathlib import Path

import pytest

from digital_twin_runtime_suite.app.commands import RuntimeController


@pytest.mark.parametrize(
    ("workload_mode", "dataset_identity"),
    (
        ("Idle", "server/load_idle"),
        ("Nominal", "server/load_normal"),
        ("Surge", "server/load_surge"),
        ("Critical", "server/load_critical"),
    ),
)
def test_runtime_controller_resolves_workload_through_binding_boundary(
    workload_mode,
    dataset_identity,
):
    controller = RuntimeController(Path("configs/digital_twin_runtime_suite.toml"))

    binding = controller.resolve_workload_airflow_binding(workload_mode)

    assert binding.dataset_identity == dataset_identity
    mapping_log = binding.format_mapping_log()
    assert mapping_log.startswith(
        "DTRS WORKLOAD CACHE MAPPING | "
        f"workload={workload_mode} | dataset={dataset_identity}"
    )
    assert re.search(
        r"Local time: \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} [+-]\d{2}:\d{2}$",
        mapping_log,
    )


@pytest.mark.parametrize(
    ("workload_mode", "dataset_identity"),
    (
        ("Idle", "server/load_idle"),
        ("Nominal", "server/load_normal"),
        ("Surge", "server/load_surge"),
        ("Critical", "server/load_critical"),
    ),
)
def test_kit_cae_attach_resolves_current_workload_dataset(
    workload_mode,
    dataset_identity,
):
    controller = RuntimeController(Path("configs/digital_twin_runtime_suite.toml"))
    controller.set_workload_source(lambda: workload_mode)

    binding, dataset = controller._resolve_kit_cae_attach_airflow_dataset()

    assert binding.dataset_identity == dataset_identity
    assert f"{dataset.manifest.scope}/{dataset.manifest.state}" == dataset_identity


def test_kit_cae_attach_nominal_preserves_stage_six_dataset_selection():
    controller = RuntimeController(Path("configs/digital_twin_runtime_suite.toml"))
    controller.set_workload_source(lambda: "Nominal")

    binding, dataset = controller._resolve_kit_cae_attach_airflow_dataset()

    assert binding.dataset == controller.config.simulation_cache.airflow_dataset
    assert dataset.manifest.state == "load_normal"


def test_airflow_cache_selector_keeps_attached_dataset_until_detach():
    controller = RuntimeController(Path("configs/digital_twin_runtime_suite.toml"))
    controller.set_workload_source(lambda: "Surge")

    assert controller.airflow_cache_selector_identity() == "server/load_surge"

    controller._flow_session_workload_binding = (
        controller.resolve_workload_airflow_binding("Surge")
    )
    controller.set_workload_source(lambda: "Critical")

    assert controller.airflow_cache_selector_identity() == "server/load_surge"

    controller._flow_session_workload_binding = None

    assert controller.airflow_cache_selector_identity() == "server/load_critical"


def test_telemetry_has_no_authored_airflow_dataset_knowledge():
    telemetry_root = Path("src/digital_twin_runtime_suite/app/telemetry")
    telemetry_source = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(telemetry_root.glob("*.py"))
    )

    for authored_dataset_detail in (
        "load_idle",
        "load_normal",
        "load_surge",
        "load_critical",
        "AirflowDatasetSelector",
        "manifest.toml",
        "airflow_datasets",
    ):
        assert authored_dataset_detail not in telemetry_source
