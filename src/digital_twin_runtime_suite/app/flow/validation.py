"""VTI, CAE, and spatial validation for the DTRS Flow route."""

from __future__ import annotations

import math
import time

from digital_twin_runtime_suite.app.airflow_validation.preflight import (
    calculate_kit_cae_direct_attach_base_velocity_scale,
)


def resolve_kit_cae_direct_attach_runtime_contract(
    metadata: dict[str, object],
    velocity_scale_multiplier: float,
) -> dict[str, float]:
    """Resolve the transport values that a direct Attach would configure."""

    try:
        base_velocity_scale = float(
            metadata["kit_cae_direct_attach_base_velocity_scale"]
        )
        multiplier = float(velocity_scale_multiplier)
    except (KeyError, TypeError, ValueError) as error:
        raise RuntimeError(
            "Validated VTI metadata lacks the Kit-CAE direct-Attach "
            "velocityScale contract."
        ) from error
    if not (
        math.isfinite(base_velocity_scale)
        and base_velocity_scale > 0.0
        and math.isfinite(multiplier)
        and multiplier > 0.0
    ):
        raise RuntimeError("Kit-CAE direct-Attach velocityScale contract is invalid.")
    return {
        "base_velocity_scale": base_velocity_scale,
        "effective_velocity_scale": base_velocity_scale * multiplier,
    }


async def resolve_live_kit_cae_direct_attach_runtime_contract(
    dataset_emitter,
    Usd,
    velocity_scale_multiplier: float,
    time_code,
) -> dict[str, float]:
    """Use the live Kit-CAE source representation shared by Attach and switching."""

    from omni.cae.viz import utils as cae_viz_utils

    source_dataset = await cae_viz_utils.get_input_dataset(
        dataset_emitter,
        "source",
        timeCode=time_code,
        device="cuda:0",
    )
    bounds_min, bounds_max = source_dataset.get_bounds()
    velocity_max = source_dataset.get_field("velocities").get_range()[1]
    bounds = tuple(
        component
        for minimum, maximum in zip(bounds_min, bounds_max)
        for component in (float(minimum), float(maximum))
    )
    base_velocity_scale = calculate_kit_cae_direct_attach_base_velocity_scale(
        bounds,
        float(velocity_max),
    )
    return resolve_kit_cae_direct_attach_runtime_contract(
        {"kit_cae_direct_attach_base_velocity_scale": base_velocity_scale},
        velocity_scale_multiplier,
    )


async def wait_for_kit_cae_dataset_emitter_ready(
    app,
    dataset_emitter,
    *,
    timeout_seconds: float = 5.0,
    max_update_cycles: int = 300,
) -> dict[str, object]:
    """Wait for Kit-CAE to materialize its internal Flow velocity payload."""

    started_at = time.monotonic()
    cycles = 0

    def readiness() -> tuple[bool, int, float]:
        payload_attribute = dataset_emitter.GetAttribute("nanoVdbVelocities")
        payload = (
            payload_attribute.Get()
            if payload_attribute and payload_attribute.IsValid()
            else None
        )
        payload_count = len(payload) if payload is not None else 0
        couple_rate = dataset_emitter.GetAttribute("coupleRateVelocity")
        couple_rate_raw = (
            couple_rate.Get() if couple_rate and couple_rate.IsValid() else None
        )
        couple_rate_value = (
            float(couple_rate_raw) if couple_rate_raw is not None else 0.0
        )
        return (
            payload_count > 0 and couple_rate_value > 0.0,
            payload_count,
            couple_rate_value,
        )

    ready, payload_count, couple_rate_value = readiness()
    while (
        not ready
        and cycles < max_update_cycles
        and time.monotonic() - started_at < timeout_seconds
    ):
        await app.next_update_async()
        cycles += 1
        ready, payload_count, couple_rate_value = readiness()

    waited_seconds = time.monotonic() - started_at
    return {
        "ready": ready,
        "cycles": cycles,
        "seconds": waited_seconds,
        "timed_out": not ready,
        "payload_count": payload_count,
        "couple_rate_velocity": couple_rate_value,
    }


async def trace_kit_cae_dav_velocity_dataset(dataset_emitter, Usd) -> dict[str, object]:
    """Read the exact CAE source dataset consumed by FlowNanoVDBEmitter."""

    from omni.cae.viz import utils as cae_viz_utils

    source_dataset = await cae_viz_utils.get_input_dataset(
        dataset_emitter,
        "source",
        timeCode=Usd.TimeCode.Default(),
        device="cuda:0",
    )
    bounds_min, bounds_max = source_dataset.get_bounds()
    velocity_field = source_dataset.get_field("velocities")
    velocity_volume = velocity_field.get_data()
    return {
        "bounds": (
            tuple(float(value) for value in bounds_min),
            tuple(float(value) for value in bounds_max),
        ),
        "origin": tuple(float(value) for value in bounds_min),
        "voxel_size": tuple(float(value) for value in velocity_volume.get_voxel_size()),
    }
