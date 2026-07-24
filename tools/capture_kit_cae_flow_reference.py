"""Run the unchanged NVIDIA NPZ Flow sample and capture its effective Flow state."""

from __future__ import annotations

import asyncio
import runpy
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from blackwell_monitoring_suite.app.kit_cae_flow_parity import (  # noqa: E402
    capture_flow_scene,
    write_flow_snapshot,
)

REFERENCE_ROOT = Path(r"E:\omniverse_kit_cae")
REFERENCE_SCRIPT = REFERENCE_ROOT / "scripts" / "example_npz_flow.py"
OUTPUT_PATH = (
    PROJECT_ROOT / "out" / "diagnostics" / "kit_cae_flow_snapshot_reference_npz.json"
)
REFERENCE_PATHS = {
    "dataset": "/World/disk_out_ref_npz/NumPyDataSet",
    "velocity_field": "/World/disk_out_ref_npz/NumPyArrays/V",
    "bounding_box": "/World/CAE/BoundingBox_NumPyDataSet",
    "flow_environment": "/World/CAE/FlowSimulation_L0",
    "flow_simulate": "/World/CAE/FlowSimulation_L0/flowSimulate",
    "flow_offscreen": "/World/CAE/FlowSimulation_L0/flowOffscreen",
    "flow_render": "/World/CAE/FlowSimulation_L0/flowRender",
    "ray_march": "/World/CAE/FlowSimulation_L0/flowRender/rayMarch",
    "debug_volume": "/World/CAE/FlowSimulation_L0/flowOffscreen/debugVolume",
    "smoke_injector": "/World/CAE/SmokeInjector_NumPyDataSet",
    "smoke_emitter": "/World/CAE/SmokeInjector_NumPyDataSet/EmitterSphere",
    "boundary_emitter_root": "/World/CAE/BoundaryEmitter_NumPyDataSet",
    "dataset_emitter": "/World/CAE/DataSetEmitter_NumPyDataSet",
}


async def capture_after_settle() -> None:
    import carb
    import omni.kit.app
    import omni.usd

    app = omni.kit.app.get_app()
    stage = omni.usd.get_context().get_stage()
    emitter = None
    for _ in range(600):
        await app.next_update_async()
        emitter = stage.GetPrimAtPath(REFERENCE_PATHS["dataset_emitter"])
        payload = emitter.GetAttribute("nanoVdbVelocities") if emitter else None
        if payload and payload.IsValid() and payload.Get() and len(payload.Get()) > 0:
            break
    else:
        raise RuntimeError("NVIDIA reference Flow DataSetEmitter did not settle.")

    for _ in range(20):
        await app.next_update_async()
    snapshot = capture_flow_scene(
        stage,
        label="WORKING_NVIDIA_FLOW_NPZ",
        paths=REFERENCE_PATHS,
    )
    output_path = write_flow_snapshot(snapshot, OUTPUT_PATH)
    carb.log_warn(f"BMS Kit-CAE parity reference snapshot saved: {output_path}")


if not REFERENCE_SCRIPT.is_file():
    raise RuntimeError(f"Kit-CAE reference script is missing: {REFERENCE_SCRIPT}")

runpy.run_path(str(REFERENCE_SCRIPT), run_name="__main__")
asyncio.ensure_future(capture_after_settle())
