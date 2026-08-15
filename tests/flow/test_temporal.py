from pathlib import Path

import pytest

from digital_twin_runtime_suite.app.airflow_validation import preflight
from digital_twin_runtime_suite.app.airflow_validation.preflight import (
    TemporalVtiValidationCancelled,
)
from digital_twin_runtime_suite.app.flow.temporal import (
    kit_cae_temporal_loop_proof_summary,
    kit_cae_vti_source_frame,
)


def test_temporal_loop_proof_requires_sixteen_distinct_sources_and_closure(
    tmp_path: Path,
) -> None:
    velocity_paths = tuple(
        tmp_path / f"server_airflow_velocity_{frame}.vti"
        for frame in range(1001, 1752, 50)
    )
    records = [
        {
            "sequence_index": index,
            "source_frame": kit_cae_vti_source_frame(asset),
            "asset": asset.name,
            "asset_hash": f"{index % len(velocity_paths):012x}",
            "transition": (
                "INITIAL" if index == 0 else "LOOP" if index == 16 else "SWAP"
            ),
            "operator_ready": True,
            "timeline_advancing": True,
            "flow_reset": False,
            "origin_match": True,
            "grid_match": True,
        }
        for index, asset in enumerate((*velocity_paths, velocity_paths[0]))
    ]

    summary = kit_cae_temporal_loop_proof_summary(records, velocity_paths)

    assert summary["passed"] is True
    assert summary["forward_transitions"] == 15
    assert summary["loop_transitions"] == 1
    assert summary["loop_closure"] is True


def test_temporal_vti_validation_stops_between_completed_samples(
    monkeypatch, tmp_path: Path
) -> None:
    """A Detach request must not make the worker read the remaining VTI assets."""

    velocity_paths = tuple(tmp_path / f"velocity_{index}.vti" for index in range(3))
    read_assets: list[Path] = []

    def read_metadata(path: Path, _field_name: str) -> dict[str, object]:
        read_assets.append(path)
        return {
            "dimensions": (2, 2, 2),
            "spacing": (1.0, 1.0, 1.0),
            "vti_header_origin": (0.0, 0.0, 0.0),
        }

    monkeypatch.setattr(preflight, "read_kit_cae_vti_metadata", read_metadata)

    with pytest.raises(TemporalVtiValidationCancelled):
        preflight.validate_kit_cae_temporal_vti_contract(
            velocity_paths,
            "vel",
            cancel_requested=lambda: len(read_assets) >= 1,
        )

    assert read_assets == [velocity_paths[0]]
