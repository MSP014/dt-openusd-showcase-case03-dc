# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
from types import SimpleNamespace

from digital_twin_runtime_suite.app.flow import performance
from digital_twin_runtime_suite.app.flow import runtime as flow_runtime
from digital_twin_runtime_suite.app.flow import workload_transition
from digital_twin_runtime_suite.app.flow.performance import (
    FlowPerformanceMixin,
    FlowPerformanceSample,
    flow_performance_statistics,
)
from digital_twin_runtime_suite.app.flow.runtime import FlowRuntimeMixin
from digital_twin_runtime_suite.app.flow.workload_transition import (
    AttachedWorkloadTransitionMixin,
)


def test_flow_performance_statistics_use_viewport_samples() -> None:
    samples = [
        FlowPerformanceSample(0.0, 50.0, 20.0, 4.5, 6.0, "1014.vti"),
        FlowPerformanceSample(0.5, 40.0, 25.0, 4.6, 6.1, "1015.vti"),
        FlowPerformanceSample(1.0, 60.0, 16.0, 4.7, 6.2, "1016.vti"),
    ]

    statistics = flow_performance_statistics(samples)

    assert statistics["fps_average"] == 50.0
    assert statistics["fps_minimum"] == 40.0
    assert statistics["fps_maximum"] == 60.0
    assert abs(float(statistics["frame_time_average"]) - 20.333333333) < 1e-8


class _Carb:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def log_warn(self, message: str) -> None:
        self.messages.append(message)


class _Runtime(FlowPerformanceMixin):
    def __init__(self) -> None:
        self._flow_performance_camera_bookmark = "Unspecified"
        self._flow_performance_attached_at = 10.0
        self._flow_airflow_simulate_path = "/DTRS_Runtime/Flow"
        self._flow_performance_task = None

    def airflow_transition_state(self):
        return {
            "semantic_workload": "Nominal",
            "active_airflow_selector": "server/load_normal",
            "pending_airflow_selector": None,
        }

    @staticmethod
    def _last_temporal_proof_log_fields():
        return ()


class _AttachRuntime(FlowRuntimeMixin):
    def __init__(self) -> None:
        self.config = SimpleNamespace(
            simulation_cache=SimpleNamespace(
                intake_tracers=SimpleNamespace(
                    smoke_target=0.5,
                    smoke_couple_rate=30.0,
                ),
                smoke_tuning=SimpleNamespace(
                    base_color=(0.839216, 0.968627, 1.0),
                    velocity_scale_multiplier=1.0,
                    time_scale=4.0,
                    density=0.5,
                    brightness=1.5,
                    ambient=1.0,
                    shadow_density=1.0,
                    damping=0.001,
                    fade=0.0,
                    sharpness=0.9,
                    vorticity=0.6,
                    raymarch_quality=0.75,
                ),
            )
        )
        self._flow_voxel_max_resolution = 128
        self._flow_density_cell_size = 0.00515271


def test_flow_performance_events_use_the_standard_dtrs_diagnostic_block(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        performance,
        "with_dtrs_local_timestamp",
        lambda content: f"{content} | Local time: fixed",
    )
    runtime = _Runtime()
    carb = _Carb()
    attached = FlowPerformanceSample(10.0, 39.8, 25.1, 5.6, 7.2, "1001.vti")
    interval = FlowPerformanceSample(40.0, 23.2, 48.7, 8.0, 8.4, "1091.vti")

    runtime._log_flow_performance_event(
        carb,
        event="FLOW_ATTACHED",
        sample=attached,
    )
    runtime._log_flow_performance_interval(carb, [attached, interval])

    attached_log, interval_log = carb.messages
    assert attached_log.splitlines()[1:4] == [
        "====================",
        "DTRS FLOW",
        "process=PERFORMANCE | state=FLOW_ATTACHED",
    ]
    assert "temporal_source=1001.vti" in attached_log
    assert interval_log.splitlines()[1:4] == [
        "====================",
        "DTRS FLOW",
        "process=PERFORMANCE | state=INTERVAL",
    ]
    assert "average_fps=31.5" in interval_log
    assert "live_temporal_source=1091.vti" in interval_log
    assert interval_log.endswith("Local time: fixed\n====================")


def test_flow_attach_summary_uses_the_standard_dtrs_diagnostic_block(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        flow_runtime,
        "with_dtrs_local_timestamp",
        lambda content: f"{content} | Local time: fixed",
    )
    runtime = _AttachRuntime()
    carb = _Carb()

    runtime._log_kit_cae_flow_attached(
        carb,
        temporal_frames=80,
        intake_tracer_count=7,
        metadata={"dimensions": (184, 72, 232), "spacing": (0.00255,) * 3},
        origin_match=True,
        grid_match=True,
        operator_ready=True,
        flow_environment_path="/DTRS_KitCAE/FlowSimulation",
        dataset_emitter_path="/DTRS_KitCAE/DataSetEmitter",
        base_velocity_scale=0.637117,
        stage_meters_per_unit=1.0,
        density_cell_size_m=0.00515271,
        intake_tracer_radius=0.01,
    )

    assert carb.messages[0].splitlines()[1:4] == [
        "====================",
        "DTRS FLOW",
        "process=ATTACH | state=COMPLETE",
    ]
    assert "spatial_origin_match=True" in carb.messages[0]
    assert "smoke_tuning_raymarch_quality=0.75" in carb.messages[0]
    assert carb.messages[0].endswith("Local time: fixed\n====================")


def test_legacy_flow_evidence_uses_the_standard_dtrs_diagnostic_block(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        flow_runtime,
        "with_dtrs_local_timestamp",
        lambda content: f"{content} | Local time: fixed",
    )

    message = FlowRuntimeMixin._format_flow_log_block(
        "VOXEL REBUILD",
        (("Invariants", (("Origin match:", True),)),),
        state="PROGRESS",
    )

    assert message.splitlines()[1:4] == [
        "====================",
        "DTRS FLOW",
        "process=VOXEL REBUILD | state=PROGRESS",
    ]
    assert "invariants_origin_match=True" in message
    assert message.endswith("Local time: fixed\n====================")


def test_airflow_transition_evidence_uses_the_standard_dtrs_diagnostic_block(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        workload_transition,
        "with_dtrs_local_timestamp",
        lambda content: f"{content} | Local time: fixed",
    )

    message = AttachedWorkloadTransitionMixin._format_airflow_transition_log_block(
        "COMMIT",
        (("Transition:", 7), ("RESULT:", "PASS")),
    )

    assert message.splitlines()[1:4] == [
        "====================",
        "DTRS AIRFLOW TRANSITION",
        "process=WORKLOAD | state=COMMIT",
    ]
    assert "transition=7" in message
    assert "result=PASS" in message
    assert message.endswith("Local time: fixed\n====================")


def test_flow_sampler_is_retained_but_disabled_by_default() -> None:
    runtime = _Runtime()

    runtime._start_flow_performance_sampler()

    assert FlowPerformanceMixin.FLOW_PERFORMANCE_SAMPLER_ENABLED is False
    assert runtime._flow_performance_task is None
