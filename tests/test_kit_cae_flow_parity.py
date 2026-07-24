from blackwell_monitoring_suite.app.kit_cae_flow_parity import diff_flow_snapshots


def test_flow_parity_diff_separates_dataset_and_flow_differences():
    reference = {
        "label": "reference",
        "roles": {
            "dataset": {"prim_path": "/World/dataset", "prim_type": "CaeDataSet"},
            "flow_simulate": {
                "attributes": {
                    "densityCellSize": {"value": 0.1},
                    "forceSimulate": {"value": False},
                }
            },
            "smoke_emitter": {"attributes": {"fuel": {"value": 1.0}}},
        },
        "runtime_diagnostics": {"activeBlocks": 2},
    }
    bms = {
        "label": "bms",
        "roles": {
            "dataset": {"prim_path": "/BMS/dataset", "prim_type": "CaeDataSet"},
            "flow_simulate": {
                "attributes": {
                    "densityCellSize": {"value": 0.05},
                    "forceSimulate": {"value": True},
                }
            },
            "smoke_emitter": {"attributes": {"fuel": {"value": 0.0}}},
        },
        "runtime_diagnostics": {"activeBlocks": 0},
    }

    result = diff_flow_snapshots(reference, bms)

    assert any(
        difference["path"] == "flow_simulate.attributes.densityCellSize.value"
        for difference in result["EXPECTED_DATASET_DIFFERENCE"]
    )
    assert any(
        difference["path"] == "flow_simulate.attributes.forceSimulate.value"
        for difference in result["SUSPICIOUS_FLOW_DIFFERENCE"]
    )
    assert any(
        difference["path"] == "smoke_emitter.attributes.fuel.value"
        for difference in result["SUSPICIOUS_FLOW_DIFFERENCE"]
    )
