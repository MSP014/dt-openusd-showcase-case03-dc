"""Focused Stage 09 Package A static airflow-source contracts."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from digital_twin_runtime_suite.app.airflow_dataset import (
    AirflowDatasetError,
    AirflowDatasetSelector,
)
from digital_twin_runtime_suite.app.commands import RuntimeController
from digital_twin_runtime_suite.app.flow import static_source
from digital_twin_runtime_suite.app.streamlines.diagnostics import (
    StaticSourceRuntimeEvidence,
    _runtime_subtree_paths,
    format_static_source_acceptance,
)
from digital_twin_runtime_suite.app.streamlines.runtime import (
    report_streamlines_static_test_task_failure,
)
from digital_twin_runtime_suite.app.workload_binding.runtime import (
    WorkloadAirflowBinding,
)


def test_static_source_resolves_manifest_dataset_and_deterministic_sample_zero(
    tmp_path,
    monkeypatch,
):
    binding = _binding()
    _write_dataset(tmp_path)
    monkeypatch.setattr(
        static_source.airflow_preflight,
        "read_kit_cae_vti_metadata",
        lambda path, field_name: _metadata(path, field_name),
    )

    first = static_source.resolve_static_velocity_sample(tmp_path, binding, "vel", 0)
    repeated = static_source.resolve_static_velocity_sample(tmp_path, binding, "vel", 0)

    assert first.workload == "Nominal"
    assert first.dataset_identity == "server/load_normal"
    assert first.sample_index == repeated.sample_index == 0
    assert first.vti_path == repeated.vti_path
    assert first.vti_path.name == "server_velocity.0000.vti"


def test_static_source_rejects_sample_index_outside_manifest_sequence(
    tmp_path, monkeypatch
):
    _write_dataset(tmp_path)
    monkeypatch.setattr(
        static_source.airflow_preflight,
        "read_kit_cae_vti_metadata",
        lambda path, field_name: _metadata(path, field_name),
    )

    with pytest.raises(AirflowDatasetError, match="outside the manifest-backed"):
        static_source.resolve_static_velocity_sample(tmp_path, _binding(), "vel", 2)


def test_static_source_rejects_missing_configured_velocity_field(tmp_path, monkeypatch):
    _write_dataset(tmp_path)

    def missing_field(_path, field_name):
        raise RuntimeError(f"VTI PointData array '{field_name}' was not found.")

    monkeypatch.setattr(
        static_source.airflow_preflight,
        "read_kit_cae_vti_metadata",
        missing_field,
    )

    with pytest.raises(RuntimeError, match="PointData array 'velocity' was not found"):
        static_source.resolve_static_velocity_sample(
            tmp_path, _binding(), "velocity", 0
        )


def test_static_source_descriptor_preserves_imported_spatial_contract(
    tmp_path, monkeypatch
):
    _write_dataset(tmp_path)
    monkeypatch.setattr(
        static_source.airflow_preflight,
        "read_kit_cae_vti_metadata",
        lambda path, field_name: _metadata(path, field_name),
    )
    sample = static_source.resolve_static_velocity_sample(tmp_path, _binding(), "vel")

    descriptor = static_source.describe_imported_static_velocity_source(
        sample,
        dataset_prim_path="/DTRS_HoudiniVelocity/VTKImageData",
        velocity_field_prim_path="/DTRS_HoudiniVelocity/PointData/vel",
        imported_grid={
            "origin": (-1.0, 2.0, 3.0),
            "spacing": (0.5, 1.0, 2.0),
            "world_bounds": ((-1.0, 2.0, 3.0), (0.0, 4.0, 9.0)),
        },
        stage_meters_per_unit=0.01,
    )

    assert descriptor.dataset_identity == "server/load_normal"
    assert descriptor.sample_index == 0
    assert descriptor.dimensions == (3, 3, 4)
    assert descriptor.origin == descriptor.source_origin == (-1.0, 2.0, 3.0)
    assert descriptor.world_bounds == ((-1.0, 2.0, 3.0), (0.0, 4.0, 9.0))
    assert descriptor.stage_meters_per_unit == 0.01


def test_static_test_rejects_full_airflow_attach_without_importing_kit():
    controller = RuntimeController("configs/digital_twin_runtime_suite.toml")
    controller._flow_lifecycle_state = "ATTACHED"

    result = asyncio.run(controller.run_streamlines_static_test_in_kit())

    assert result.success is False
    assert "Attach is active" in result.message
    assert controller.streamlines_static_source_descriptor() is None


def test_unexpected_static_test_task_failure_is_logged_visible_and_retry_safe():
    statuses = []
    logs = []

    result = report_streamlines_static_test_task_failure(
        LookupError("Kit diagnostic callback failed"),
        status_callback=statuses.append,
        error_logger=logs.append,
    )

    assert result.success is False
    assert statuses == [
        "Streamlines static source failed: Kit diagnostic callback failed"
    ]
    assert len(logs) == 1
    assert "DTRS STREAMLINES | STATIC_SOURCE | FAIL" in logs[0]
    assert "boundary=UI_TASK" in logs[0]


def test_static_test_controller_contains_an_unexpected_runtime_exception(
    monkeypatch,
):
    controller = RuntimeController("configs/digital_twin_runtime_suite.toml")

    async def fail_prepare(*_args, **_kwargs):
        raise LookupError("unexpected Kit runtime error")

    monkeypatch.setattr(
        controller, "prepare_static_velocity_sample_in_kit", fail_prepare
    )

    result = asyncio.run(controller.run_streamlines_static_test_in_kit())

    assert result.success is False
    assert "unexpected Kit runtime error" in result.message


def test_task_failure_reporting_survives_faulty_logger_and_status_callback():
    def raise_error(*_args):
        raise RuntimeError("secondary reporting failure")

    result = report_streamlines_static_test_task_failure(
        RuntimeError("primary failure"),
        status_callback=raise_error,
        error_logger=raise_error,
    )

    assert result.success is False
    assert result.message == "Streamlines static source failed: primary failure"


def test_repeated_static_test_replaces_prior_descriptor_without_accumulating_state(
    monkeypatch,
):
    controller = RuntimeController("configs/digital_twin_runtime_suite.toml")
    first = _descriptor(sample_index=0)
    replacement = _descriptor(sample_index=0)
    prepared = iter((first, replacement))

    async def prepare(*_args, **_kwargs):
        descriptor = next(prepared)
        controller._streamlines_static_source_descriptor = descriptor
        return descriptor

    monkeypatch.setattr(controller, "prepare_static_velocity_sample_in_kit", prepare)

    first_result = asyncio.run(controller.run_streamlines_static_test_in_kit())
    repeated_result = asyncio.run(controller.run_streamlines_static_test_in_kit())

    assert first_result.success is repeated_result.success is True
    assert controller.streamlines_static_source_descriptor() is replacement


def test_static_source_acceptance_block_reports_forbidden_runtime_states():
    evidence = StaticSourceRuntimeEvidence(
        authored_prims=(
            "/DTRS_HoudiniVelocity",
            "/DTRS_HoudiniVelocity/VTKImageData",
        ),
        duplicate_runtime_prim_count=0,
        flow_environment="ABSENT",
        dataset_emitter="ABSENT",
        boundary_emitter="ABSENT",
        smoke_injectors="ABSENT",
        streamlines_operator="ABSENT",
        temporal_sequence="ABSENT",
        timeline_playback="INACTIVE",
    )
    cleanup = static_source.StaticVelocitySourceCleanup(False, True)

    log_block = format_static_source_acceptance(
        _descriptor(sample_index=0), cleanup, evidence
    )

    assert "DTRS STREAMLINES | STATIC_SOURCE_TEST | PASS" in log_block
    assert "FlowEnvironment=ABSENT" in log_block
    assert "TemporalSequence=ABSENT" in log_block
    assert "TimelinePlayback=INACTIVE" in log_block
    assert "duplicate_runtime_prim_count=0" in log_block


def test_runtime_prim_enumeration_uses_supported_children_traversal():
    velocity = _FakePrim("/DTRS_HoudiniVelocity/PointData/vel")
    point_data = _FakePrim("/DTRS_HoudiniVelocity/PointData", (velocity,))
    image_data = _FakePrim("/DTRS_HoudiniVelocity/VTKImageData", (point_data,))
    root = _FakePrim("/DTRS_HoudiniVelocity", (image_data,))

    paths = _runtime_subtree_paths(root)

    assert paths == (
        "/DTRS_HoudiniVelocity",
        "/DTRS_HoudiniVelocity/VTKImageData",
        "/DTRS_HoudiniVelocity/PointData",
        "/DTRS_HoudiniVelocity/PointData/vel",
    )


def _binding() -> WorkloadAirflowBinding:
    return WorkloadAirflowBinding(
        workload_mode="Nominal",
        dataset=AirflowDatasetSelector("airflows", "server", "load_normal"),
    )


def _write_dataset(tmp_path) -> None:
    dataset = tmp_path / "airflows" / "server" / "load_normal"
    dataset.mkdir(parents=True)
    (dataset / "manifest.toml").write_text(
        "\n".join(
            (
                'scope = "server"',
                'state = "load_normal"',
                "source_fps = 24",
                "sample_step_frames = 1",
                "sample_rate_hz = 24",
                "sample_count = 2",
                "grid = [3, 3, 4]",
            )
        ),
        encoding="utf-8",
    )
    (dataset / "server_velocity.0000.vti").touch()
    (dataset / "server_velocity.0001.vti").touch()


def _metadata(_path, _field_name) -> dict[str, object]:
    return {
        "dimensions": (3, 3, 4),
        "spacing": (0.5, 1.0, 2.0),
        "vti_header_origin": (-1.0, 2.0, 3.0),
    }


def _descriptor(
    sample_index: int,
) -> static_source.StaticVelocitySourceDescriptor:
    return static_source.StaticVelocitySourceDescriptor(
        workload="Nominal",
        dataset_identity="server/load_normal",
        sample_index=sample_index,
        vti_path=Path("server_velocity.0000.vti"),
        dataset_prim_path="/DTRS_HoudiniVelocity/VTKImageData",
        velocity_field_prim_path="/DTRS_HoudiniVelocity/PointData/vel",
        world_bounds=((0.0, 0.0, 0.0), (1.0, 1.0, 1.0)),
        dimensions=(2, 2, 2),
        spacing=(1.0, 1.0, 1.0),
        origin=(0.0, 0.0, 0.0),
        source_origin=(0.0, 0.0, 0.0),
        stage_meters_per_unit=0.01,
    )


class _FakePrim:
    """Minimal USD-prim double exposing only the supported traversal surface."""

    def __init__(self, path: str, children=()):
        self._path = path
        self._children = children

    def IsValid(self) -> bool:
        return True

    def GetPath(self) -> str:
        return self._path

    def GetChildren(self):
        return self._children
