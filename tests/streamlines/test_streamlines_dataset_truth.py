# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""Registry-backed Streamlines dataset and temporal-source contracts."""

from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path

import pytest

from digital_twin_runtime_suite.app.airflow_dataset import (
    AirflowDataset,
    AirflowDatasetError,
    AirflowDatasetSelector,
    discover_airflow_dataset_registry,
    resolve_airflow_dataset_from_registry,
)
from digital_twin_runtime_suite.app.flow.static_source import (
    StaticVelocitySourceDescriptor,
)
from digital_twin_runtime_suite.app.streamlines.temporal import (
    manifest_samples,
    temporal_source_from_airflow_dataset,
)


@pytest.mark.parametrize(
    ("sample_count", "sample_interval_seconds"),
    (
        (80, 0.2),
        (40, 0.4),
        (160, 0.1),
        (1, 0.2),
    ),
)
def test_registry_dataset_drives_every_canonical_streamlines_sample(
    tmp_path: Path,
    sample_count: int,
    sample_interval_seconds: float,
) -> None:
    asset_root, selector = _write_dataset(
        tmp_path,
        sample_count=sample_count,
        sample_interval_seconds=sample_interval_seconds,
    )
    registry = discover_airflow_dataset_registry(asset_root, selector.root)
    dataset = resolve_airflow_dataset_from_registry(registry, selector)
    source = temporal_source_from_airflow_dataset(
        dataset,
        workload="Nominal",
        static_descriptor=_static_descriptor(dataset),
        time_codes_per_second=60.0,
    )
    samples = manifest_samples(source)

    assert len(registry) == 1
    assert source.sample_count == sample_count
    assert source.sample_interval_seconds == sample_interval_seconds
    assert source.loop_duration_seconds == pytest.approx(
        sample_count * sample_interval_seconds
    )
    assert tuple(sample.sample_index for sample in samples) == tuple(
        range(sample_count)
    )
    assert tuple(sample.source_vti for sample in samples) == (
        dataset.velocity_vti_sequence_paths
    )
    assert tuple(sample.source_time_seconds for sample in samples) == pytest.approx(
        tuple(index * sample_interval_seconds for index in range(sample_count))
    )
    assert tuple(sample.time_code for sample in samples) == pytest.approx(
        tuple(index * sample_interval_seconds * 60.0 for index in range(sample_count))
    )


def test_resolving_an_already_discovered_dataset_never_scans_manifests_again(
    tmp_path: Path,
) -> None:
    asset_root, selector = _write_dataset(
        tmp_path,
        sample_count=2,
        sample_interval_seconds=0.2,
    )
    registry = discover_airflow_dataset_registry(asset_root, selector.root)
    registry[0].manifest_path.unlink()

    resolved = resolve_airflow_dataset_from_registry(registry, selector)

    assert resolved is registry[0]


def test_registry_resolver_rejects_an_unknown_selector(tmp_path: Path) -> None:
    asset_root, selector = _write_dataset(
        tmp_path,
        sample_count=2,
        sample_interval_seconds=0.2,
    )
    registry = discover_airflow_dataset_registry(asset_root, selector.root)

    with pytest.raises(AirflowDatasetError, match="not found"):
        resolve_airflow_dataset_from_registry(
            registry,
            replace(selector, state="load_missing"),
        )


@pytest.mark.parametrize(
    "mutate",
    (
        lambda dataset, descriptor: (dataset, replace(descriptor, workload="Surge")),
        lambda dataset, descriptor: (
            dataset,
            replace(descriptor, dataset_identity="server/load_surge"),
        ),
        lambda dataset, descriptor: (
            replace(dataset, velocity_vti_sequence_paths=()),
            descriptor,
        ),
        lambda dataset, descriptor: (
            replace(
                dataset,
                velocity_vti_sequence_paths=dataset.velocity_vti_sequence_paths[:1],
            ),
            descriptor,
        ),
    ),
)
def test_temporal_source_rejects_inconsistent_resolved_dataset(
    tmp_path: Path,
    mutate,
) -> None:
    asset_root, selector = _write_dataset(
        tmp_path,
        sample_count=2,
        sample_interval_seconds=0.2,
    )
    dataset = resolve_airflow_dataset_from_registry(
        discover_airflow_dataset_registry(asset_root, selector.root),
        selector,
    )
    invalid_dataset, invalid_descriptor = mutate(dataset, _static_descriptor(dataset))

    with pytest.raises(ValueError):
        temporal_source_from_airflow_dataset(
            invalid_dataset,
            workload="Nominal",
            static_descriptor=invalid_descriptor,
            time_codes_per_second=60.0,
        )


@pytest.mark.parametrize("time_codes_per_second", (0.0, -1.0, math.nan, math.inf))
def test_temporal_source_rejects_non_finite_or_non_positive_time_code_rate(
    tmp_path: Path,
    time_codes_per_second: float,
) -> None:
    asset_root, selector = _write_dataset(
        tmp_path,
        sample_count=2,
        sample_interval_seconds=0.2,
    )
    dataset = resolve_airflow_dataset_from_registry(
        discover_airflow_dataset_registry(asset_root, selector.root),
        selector,
    )

    with pytest.raises(ValueError, match="time codes per second"):
        temporal_source_from_airflow_dataset(
            dataset,
            workload="Nominal",
            static_descriptor=_static_descriptor(dataset),
            time_codes_per_second=time_codes_per_second,
        )


def _write_dataset(
    tmp_path: Path,
    *,
    sample_count: int,
    sample_interval_seconds: float,
) -> tuple[Path, AirflowDatasetSelector]:
    source_fps = 10.0
    sample_step_frames = round(sample_interval_seconds * source_fps)
    assert sample_step_frames > 0
    assert sample_interval_seconds == pytest.approx(sample_step_frames / source_fps)
    asset_root = tmp_path
    directory = asset_root / "airflow_datasets" / "untrusted" / "nominal"
    directory.mkdir(parents=True)
    directory.joinpath("manifest.toml").write_text(
        "\n".join(
            (
                'scope = "server"',
                'state = "load_normal"',
                f"source_fps = {source_fps}",
                f"sample_step_frames = {sample_step_frames}",
                f"sample_rate_hz = {1.0 / sample_interval_seconds}",
                f"sample_count = {sample_count}",
                "grid = [2, 2, 101]",
            )
        ),
        encoding="utf-8",
    )
    for index in range(sample_count):
        frame = 1000 + (index * sample_step_frames)
        directory.joinpath(f"velocity_{frame:04d}.vti").write_bytes(
            f"vti-{index}".encode("utf-8")
        )
    return asset_root, AirflowDatasetSelector(
        root="airflow_datasets",
        scope="server",
        state="load_normal",
    )


def _static_descriptor(dataset: AirflowDataset) -> StaticVelocitySourceDescriptor:
    return StaticVelocitySourceDescriptor(
        workload="Nominal",
        dataset_identity=(f"{dataset.manifest.scope}/{dataset.manifest.state}"),
        sample_index=0,
        vti_path=dataset.velocity_vti_sequence_paths[0],
        dataset_prim_path="/DTRS_HoudiniVelocity/VTKImageData",
        velocity_field_prim_path="/DTRS_HoudiniVelocity/PointData/vel",
        world_bounds=((0.0, 0.0, 0.0), (1.0, 1.0, 1.0)),
        dimensions=(2, 2, 101),
        spacing=(0.1, 0.1, 0.01),
        origin=(0.0, 0.0, 0.0),
        source_origin=(0.0, 0.0, 0.0),
        stage_meters_per_unit=1.0,
    )
