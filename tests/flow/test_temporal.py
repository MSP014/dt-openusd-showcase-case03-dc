from pathlib import Path

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
