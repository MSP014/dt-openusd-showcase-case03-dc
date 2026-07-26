from digital_twin_runtime_suite.app.flow.performance import (
    FlowPerformanceSample,
    flow_performance_statistics,
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
