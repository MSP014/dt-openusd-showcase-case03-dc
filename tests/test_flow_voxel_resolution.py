import asyncio

import pytest

from digital_twin_runtime_suite.app.flow.quality import (
    validate_kit_cae_flow_voxel_resolution,
)
from digital_twin_runtime_suite.app.flow.runtime import FlowRuntimeMixin


class _PendingTask:
    def done(self) -> bool:
        return False


class _RuntimeProbe(FlowRuntimeMixin):
    def __init__(
        self,
        *,
        lifecycle_state: str = "DETACHED",
        temporal_proof_task=None,
        airflow_simulate_path: str | None = None,
    ) -> None:
        self._flow_lifecycle_state = lifecycle_state
        self._flow_temporal_proof_task = temporal_proof_task
        self._flow_airflow_simulate_path = airflow_simulate_path


class _TimelineProbe:
    def __init__(self) -> None:
        self.calls = []

    def pause(self) -> None:
        self.calls.append(("pause",))

    def set_current_time(self, value: float) -> None:
        self.calls.append(("set_current_time", value))

    def play(self, *args) -> None:
        self.calls.append(("play", *args))


@pytest.mark.parametrize("value", (128, 192, 256))
def test_flow_voxel_resolution_accepts_only_the_ab_test_values(value):
    validate_kit_cae_flow_voxel_resolution(value)


@pytest.mark.parametrize("value", (127, 257, 192.0, True, "192"))
def test_flow_voxel_resolution_rejects_non_ab_values(value):
    with pytest.raises(ValueError, match="must be one of"):
        validate_kit_cae_flow_voxel_resolution(value)


def test_apply_flow_voxel_resolution_rejects_invalid_value_before_kit_import():
    result = asyncio.run(_RuntimeProbe().apply_kit_cae_voxel_resolution_in_kit(96))

    assert not result.success
    assert "invalid" in result.message


def test_apply_flow_voxel_resolution_requires_an_attached_flow_before_kit_import():
    result = asyncio.run(_RuntimeProbe().apply_kit_cae_voxel_resolution_in_kit(128))

    assert not result.success
    assert "Attach the airflow cache" in result.message


def test_apply_flow_voxel_resolution_waits_for_the_temporal_proof():
    result = asyncio.run(
        _RuntimeProbe(
            lifecycle_state="ATTACHED",
            temporal_proof_task=_PendingTask(),
            airflow_simulate_path="/DTRS_KitCAE/FlowSimulation/flowSimulate",
        ).apply_kit_cae_voxel_resolution_in_kit(128)
    )

    assert not result.success
    assert "temporal proof" in result.message


def test_apply_flow_voxel_resolution_requires_a_live_flow_handle_before_kit_import():
    result = asyncio.run(
        _RuntimeProbe(lifecycle_state="ATTACHED").apply_kit_cae_voxel_resolution_in_kit(
            128
        )
    )

    assert not result.success
    assert "simulation path" in result.message


def test_restart_temporal_loop_reuses_attach_bounded_playback_contract():
    runtime = _RuntimeProbe()
    runtime._flow_temporal_end_time_code = 24.0
    timeline = _TimelineProbe()

    runtime._restart_kit_cae_temporal_loop(timeline)

    assert timeline.calls == [
        ("pause",),
        ("set_current_time", 0.0),
        ("play", 0.0, 24.0, True),
    ]


def test_restart_temporal_loop_keeps_plain_playback_available_without_loop_end():
    runtime = _RuntimeProbe()
    runtime._flow_temporal_end_time_code = None
    timeline = _TimelineProbe()

    runtime._restart_kit_cae_temporal_loop(timeline)

    assert timeline.calls == [
        ("pause",),
        ("set_current_time", 0.0),
        ("play",),
    ]


def test_nano_vdb_fingerprint_samples_only_payload_edges():
    payload = tuple(range(10))

    fingerprint = FlowRuntimeMixin._kit_cae_nano_vdb_payload_fingerprint(
        payload,
        len(payload),
    )

    assert fingerprint == "len=10; head=(0, 1, 2, 3); tail=(6, 7, 8, 9)"


def test_tracer_emitter_radius_diagnostics_use_authored_world_scale():
    fields = FlowRuntimeMixin._kit_cae_tracer_emitter_log_fields(
        0.005153,
        0.005153,
        1.0,
    )

    assert fields == (
        ("Radius:", "5.153 mm"),
        ("Flow density cell:", "5.153 mm"),
        ("Radius / cell size:", "1.000"),
    )
    assert FlowRuntimeMixin._kit_cae_tracer_radius_changed(0.005153, 0.005153) is False
    assert FlowRuntimeMixin._kit_cae_tracer_radius_changed(0.005153, 0.002566) is True
    assert FlowRuntimeMixin._kit_cae_tracer_radius_changed(None, 0.002566) is None


def test_live_voxel_switch_scales_the_attached_tracer_footprint():
    baseline_ratio = FlowRuntimeMixin._kit_cae_tracer_radius_cell_ratio(
        0.01,
        0.005153,
    )

    assert baseline_ratio == pytest.approx(1.940616)
    assert FlowRuntimeMixin._kit_cae_scaled_tracer_radius(
        0.003426,
        baseline_ratio,
    ) == pytest.approx(0.00664855)
    assert FlowRuntimeMixin._kit_cae_scaled_tracer_radius(
        0.002566,
        baseline_ratio,
    ) == pytest.approx(0.004979624)
    assert FlowRuntimeMixin._kit_cae_scaled_tracer_radius(0.002566, None) is None


@pytest.mark.parametrize(
    ("requested", "previous", "old_density", "new_density", "payload_changed"),
    (
        (192, 128, 0.005153, 0.0034, True),
        (256, 192, 0.0034, 0.002566, True),
        (128, 256, 0.002566, 0.005153, True),
        (128, 128, 0.005153, 0.005153, False),
    ),
)
def test_fresh_voxel_rebuild_requires_resolution_consistent_output(
    requested,
    previous,
    old_density,
    new_density,
    payload_changed,
):
    assert FlowRuntimeMixin._kit_cae_voxel_rebuild_is_fresh(
        requested_max_resolution=requested,
        previous_max_resolution=previous,
        previous_density_cell_size=old_density,
        density_cell_size=new_density,
        operator_completed=True,
        payload_changed=payload_changed,
    )


@pytest.mark.parametrize(
    ("operator_completed", "new_density", "payload_changed"),
    (
        (False, 0.002566, True),
        (True, 0.005153, True),
        (True, 0.002566, False),
    ),
)
def test_fresh_voxel_rebuild_rejects_stale_data_emitter_output(
    operator_completed,
    new_density,
    payload_changed,
):
    assert not FlowRuntimeMixin._kit_cae_voxel_rebuild_is_fresh(
        requested_max_resolution=256,
        previous_max_resolution=128,
        previous_density_cell_size=0.005153,
        density_cell_size=new_density,
        operator_completed=operator_completed,
        payload_changed=payload_changed,
    )
