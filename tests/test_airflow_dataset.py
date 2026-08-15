from pathlib import Path

import pytest

from digital_twin_runtime_suite.app.airflow_dataset import (
    AirflowDatasetError,
    AirflowDatasetSelector,
    discover_airflow_dataset,
    discover_airflow_dataset_registry,
    format_airflow_dataset_registry,
    validate_airflow_dataset_grid,
)


def _write_dataset(
    root: Path,
    *,
    directory: tuple[str, str] = ("folder_server", "folder_normal"),
    scope: str = "server",
    state: str = "load_normal",
    frames: tuple[int, ...] = (1001, 1011, 1021),
    sample_count: int | None = None,
    source_fps: float = 50.0,
    sample_step_frames: int = 10,
    sample_rate_hz: float = 5.0,
    grid: tuple[int, int, int] = (184, 72, 232),
) -> Path:
    dataset_dir = root.joinpath(*directory)
    dataset_dir.mkdir(parents=True)
    count = len(frames) if sample_count is None else sample_count
    (dataset_dir / "manifest.toml").write_text(
        "\n".join(
            (
                f'scope = "{scope}"',
                f'state = "{state}"',
                f"source_fps = {source_fps}",
                f"sample_step_frames = {sample_step_frames}",
                f"sample_rate_hz = {sample_rate_hz}",
                f"sample_count = {count}",
                f"grid = [{grid[0]}, {grid[1]}, {grid[2]}]",
                "",
            )
        ),
        encoding="utf-8",
    )
    for frame in frames:
        (dataset_dir / f"server_airflow_velocity_{frame}.vti").touch()
    return dataset_dir


def _selector() -> AirflowDatasetSelector:
    return AirflowDatasetSelector(
        root="airflow_datasets",
        scope="server",
        state="load_normal",
    )


def test_discovers_manifest_identity_independent_of_numbered_directories(tmp_path):
    root = tmp_path / "airflow_datasets"
    _write_dataset(
        root,
        directory=("01_server", "02_load_normal"),
        frames=(1021, 1001, 1011),
    )

    dataset = discover_airflow_dataset(tmp_path, _selector())

    assert dataset.directory.name == "02_load_normal"
    assert dataset.source_frames == (1001, 1011, 1021)
    assert [path.name for path in dataset.velocity_vti_sequence_paths] == [
        "server_airflow_velocity_1001.vti",
        "server_airflow_velocity_1011.vti",
        "server_airflow_velocity_1021.vti",
    ]


def test_discovers_registry_by_manifest_identity_in_deterministic_order(tmp_path):
    root = tmp_path / "airflow_datasets"
    _write_dataset(root, directory=("99_misc", "critical"), state="load_critical")
    _write_dataset(root, directory=("02_server", "normal"), state="load_normal")
    _write_dataset(root, directory=("01_server", "idle"), state="load_idle")
    _write_dataset(root, directory=("07_misc", "surge"), state="load_surge")

    registry = discover_airflow_dataset_registry(tmp_path, "airflow_datasets")

    assert [
        (dataset.manifest.scope, dataset.manifest.state) for dataset in registry
    ] == [
        ("server", "load_idle"),
        ("server", "load_normal"),
        ("server", "load_surge"),
        ("server", "load_critical"),
    ]
    assert format_airflow_dataset_registry(registry) == "\n".join(
        (
            "========================================",
            "DTRS AIRFLOW DATASET REGISTRY",
            "Discovered: 4",
            "server/load_idle",
            "server/load_normal",
            "server/load_surge",
            "server/load_critical",
            "========================================",
        )
    )


def test_registry_rejects_duplicate_manifest_identity(tmp_path):
    root = tmp_path / "airflow_datasets"
    _write_dataset(root, directory=("01_server", "normal"))
    _write_dataset(root, directory=("99_duplicate", "copy"))

    with pytest.raises(AirflowDatasetError, match="identity is ambiguous"):
        discover_airflow_dataset_registry(tmp_path, "airflow_datasets")


def test_registry_rejects_malformed_manifest(tmp_path):
    root = tmp_path / "airflow_datasets"
    malformed_dir = root / "01_server" / "broken"
    malformed_dir.mkdir(parents=True)
    (malformed_dir / "manifest.toml").write_text("scope = [", encoding="utf-8")

    with pytest.raises(AirflowDatasetError, match="Malformed airflow dataset manifest"):
        discover_airflow_dataset_registry(tmp_path, "airflow_datasets")


def test_validates_manifest_timing_and_grid_contract(tmp_path):
    root = tmp_path / "airflow_datasets"
    _write_dataset(root)

    dataset = discover_airflow_dataset(tmp_path, _selector())

    assert dataset.manifest.sample_rate_hz == pytest.approx(5.0)
    assert dataset.sample_interval_seconds == pytest.approx(0.2)
    assert dataset.loop_duration_seconds == pytest.approx(0.6)
    validate_airflow_dataset_grid(dataset, (184, 72, 232))
    with pytest.raises(AirflowDatasetError, match="grid mismatch"):
        validate_airflow_dataset_grid(dataset, (185, 72, 232))


def test_rejects_missing_samples_duplicate_frames_and_nonuniform_spacing(tmp_path):
    root = tmp_path / "airflow_datasets"
    _write_dataset(root, sample_count=4)
    with pytest.raises(AirflowDatasetError, match="sample count mismatch"):
        discover_airflow_dataset(tmp_path, _selector())

    duplicate_root = tmp_path / "duplicate" / "airflow_datasets"
    duplicate_dir = _write_dataset(duplicate_root, sample_count=4)
    (duplicate_dir / "alternate_velocity_1011.vti").touch()
    with pytest.raises(AirflowDatasetError, match="duplicate source frames"):
        discover_airflow_dataset(tmp_path / "duplicate", _selector())

    spacing_root = tmp_path / "spacing" / "airflow_datasets"
    _write_dataset(spacing_root, frames=(1001, 1011, 1031))
    with pytest.raises(AirflowDatasetError, match="spacing does not match"):
        discover_airflow_dataset(tmp_path / "spacing", _selector())


def test_rejects_missing_dataset_malformed_manifest_and_unnumbered_vti(tmp_path):
    missing_root = tmp_path / "missing" / "airflow_datasets"
    missing_root.mkdir(parents=True)
    with pytest.raises(AirflowDatasetError, match="Airflow dataset not found"):
        discover_airflow_dataset(tmp_path / "missing", _selector())

    malformed_root = tmp_path / "malformed" / "airflow_datasets"
    malformed_dir = malformed_root / "server" / "normal"
    malformed_dir.mkdir(parents=True)
    (malformed_dir / "manifest.toml").write_text("scope = [", encoding="utf-8")
    with pytest.raises(AirflowDatasetError, match="Malformed airflow dataset manifest"):
        discover_airflow_dataset(tmp_path / "malformed", _selector())

    unnumbered_root = tmp_path / "unnumbered" / "airflow_datasets"
    unnumbered_dir = _write_dataset(unnumbered_root, frames=(1001,))
    (unnumbered_dir / "server_airflow_velocity_last.vti").touch()
    with pytest.raises(AirflowDatasetError, match="numeric source-frame suffix"):
        discover_airflow_dataset(tmp_path / "unnumbered", _selector())


def test_rejects_manifest_sample_rate_that_disagrees_with_source_timing(tmp_path):
    root = tmp_path / "airflow_datasets"
    _write_dataset(root, sample_rate_hz=2.0)

    with pytest.raises(AirflowDatasetError, match="sample rate disagrees"):
        discover_airflow_dataset(tmp_path, _selector())


def test_rejects_manifest_duration_that_disagrees_with_source_timing(tmp_path):
    root = tmp_path / "airflow_datasets"
    dataset_dir = _write_dataset(root)
    (dataset_dir / "manifest.toml").write_text(
        (dataset_dir / "manifest.toml")
        .read_text(encoding="utf-8")
        .replace("sample_count = 3\n", "sample_count = 3\nduration = 15.0\n"),
        encoding="utf-8",
    )

    with pytest.raises(AirflowDatasetError, match="duration disagrees"):
        discover_airflow_dataset(tmp_path, _selector())


def test_eighty_sample_dataset_derives_five_hz_sixteen_second_loop(tmp_path):
    root = tmp_path / "airflow_datasets"
    frames = tuple(range(1001, 1801, 10))
    _write_dataset(root, frames=frames)

    dataset = discover_airflow_dataset(tmp_path, _selector())
    time_code_step = 50.0 * dataset.sample_interval_seconds

    assert len(dataset.velocity_vti_sequence_paths) == 80
    assert dataset.source_frames == frames
    assert dataset.sample_interval_seconds == pytest.approx(0.2)
    assert time_code_step == pytest.approx(10.0)
    assert dataset.loop_duration_seconds == pytest.approx(16.0)
