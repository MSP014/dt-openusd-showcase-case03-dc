"""Focused contracts for the two-profile Phase 4.4A preview harness."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest

from digital_twin_runtime_suite.app.streamlines.cache_runtime import (
    StreamlinesProfilePreviewResult,
)
from digital_twin_runtime_suite.app.streamlines.profile import (
    DEFAULT_STREAMLINES_PROFILE,
    FINAL_GLOBAL_FLOW_PATH_GEOMETRY_CONTRACT,
    FINAL_VOLUME_COVERAGE_GEOMETRY_CONTRACT,
    STREAMLINES_PROFILE_LABELS,
    StreamlinesProfileId,
)
from digital_twin_runtime_suite.app.streamlines.profile_preview_runtime import (
    StreamlinesProfilePreviewRuntimeMixin,
)
from digital_twin_runtime_suite.app.streamlines.profile_state import (
    StreamlinesProfileState,
)
from digital_twin_runtime_suite.app.streamlines.seed_layout import (
    derive_global_flow_path_layout,
    derive_volume_coverage_layout,
    exact_budget_row_counts,
)
from digital_twin_runtime_suite.app.streamlines.seed_runtime import (
    author_streamlines_seed_mesh_in_kit,
    build_stratified_seed_mesh_topology,
    topology_connects_sections,
)
from digital_twin_runtime_suite.app.streamlines.tuning import (
    DEFAULT_GLOBAL_FLOW_PATH_TUNING,
    DEFAULT_VOLUME_COVERAGE_TUNING,
    FINAL_GLOBAL_FLOW_PATH_CANDIDATE,
    FINAL_VOLUME_COVERAGE_CANDIDATE,
    PREVIEW_WORKLOAD_OPTIONS,
    AcceptedStreamlinesCandidate,
    GlobalFlowPathTuning,
    StreamlinesPreviewSelectionMismatchError,
    StreamlinesTuningState,
    VolumeCoverageTuning,
    curves_per_section_from_starts,
)


def test_profile_ids_labels_and_default_preference() -> None:
    state = StreamlinesProfileState()

    assert DEFAULT_STREAMLINES_PROFILE is StreamlinesProfileId.VOLUME_COVERAGE
    assert state.snapshot.preferred_profile is StreamlinesProfileId.VOLUME_COVERAGE
    assert tuple(StreamlinesProfileId) == (
        StreamlinesProfileId.VOLUME_COVERAGE,
        StreamlinesProfileId.GLOBAL_FLOW_PATH,
    )
    assert STREAMLINES_PROFILE_LABELS == {
        StreamlinesProfileId.VOLUME_COVERAGE: "Volume Coverage",
        StreamlinesProfileId.GLOBAL_FLOW_PATH: "Global Flow Path",
    }


def test_explicit_global_preference_survives_preview_state_reset() -> None:
    runtime = _PreviewRuntime()
    signatures = (
        AcceptedStreamlinesCandidate.capture(
            FINAL_GLOBAL_FLOW_PATH_CANDIDATE
        ).signature,
        AcceptedStreamlinesCandidate.capture(FINAL_VOLUME_COVERAGE_CANDIDATE).signature,
    )

    runtime.set_streamlines_profile_preference(StreamlinesProfileId.GLOBAL_FLOW_PATH)
    runtime.reset_streamlines_profile_preview_state()

    assert (
        runtime.streamlines_profile_preference_snapshot().preferred_profile
        is StreamlinesProfileId.GLOBAL_FLOW_PATH
    )
    assert signatures == (
        AcceptedStreamlinesCandidate.capture(
            FINAL_GLOBAL_FLOW_PATH_CANDIDATE
        ).signature,
        AcceptedStreamlinesCandidate.capture(FINAL_VOLUME_COVERAGE_CANDIDATE).signature,
    )


def test_global_and_volume_tuning_are_independent() -> None:
    state = StreamlinesTuningState()
    changed = GlobalFlowPathTuning(seed_count=256, max_steps=800, step_scale=0.5)

    state.set_selection(changed)

    assert state.global_flow_path == changed
    assert state.volume_coverage == DEFAULT_VOLUME_COVERAGE_TUNING


def test_profile_defaults_match_the_current_candidates() -> None:
    assert DEFAULT_GLOBAL_FLOW_PATH_TUNING == GlobalFlowPathTuning(
        seed_count=256,
        max_steps=200,
        step_scale=2.0,
    )
    assert DEFAULT_VOLUME_COVERAGE_TUNING == VolumeCoverageTuning(
        section_count=24,
        seeds_per_section=256,
        max_steps=20,
        step_scale=1.0,
    )
    assert (
        DEFAULT_GLOBAL_FLOW_PATH_TUNING.geometry_contract
        == FINAL_GLOBAL_FLOW_PATH_GEOMETRY_CONTRACT
    )
    assert (
        DEFAULT_VOLUME_COVERAGE_TUNING.geometry_contract
        == FINAL_VOLUME_COVERAGE_GEOMETRY_CONTRACT
    )


@pytest.mark.parametrize("budget", (64, 128, 256))
def test_exact_seed_budgets_are_centred_and_deterministic(budget: int) -> None:
    first = derive_global_flow_path_layout(
        _bounds(),
        seed_count=budget,
        front_intake_z=9.0,
        max_cell_spacing=0.25,
    )
    second = derive_global_flow_path_layout(
        _bounds(),
        seed_count=budget,
        front_intake_z=9.0,
        max_cell_spacing=0.25,
    )

    assert first == second
    assert first.seed_count == budget
    assert max(first.row_counts) - min(first.row_counts) <= 1
    assert sum(point[0] for point in first.points) / budget == pytest.approx(0.0)
    assert sum(point[1] for point in first.points) / budget == pytest.approx(0.0)


def test_128_seed_budget_remains_exactly_16_by_8() -> None:
    assert exact_budget_row_counts(128) == (16,) * 8


def test_all_stratified_xy_points_are_strictly_inside_bounds() -> None:
    layout = derive_global_flow_path_layout(
        _bounds(),
        seed_count=256,
        front_intake_z=9.0,
        max_cell_spacing=0.25,
    )

    assert all(-17.0 < x < 17.0 and -9.0 < y < 9.0 for x, y, _z in layout.points)


def test_volume_sections_use_depth_over_s_plus_one() -> None:
    layout = derive_volume_coverage_layout(
        _bounds(),
        section_count=8,
        seeds_per_section=64,
    )

    spacing = 20.0 / 9.0
    assert layout.section_planes[0] == pytest.approx(10.0 - spacing)
    assert layout.section_planes[-1] == pytest.approx(-10.0 + spacing)
    assert all(-10.0 < plane < 10.0 for plane in layout.section_planes)


def test_volume_total_seed_count_is_sections_times_budget() -> None:
    layout = derive_volume_coverage_layout(
        _bounds(),
        section_count=16,
        seeds_per_section=128,
    )

    assert layout.seed_count == 2048
    assert layout.seeds_per_section == 128


def test_volume_mesh_never_connects_adjacent_sections() -> None:
    layout = derive_volume_coverage_layout(
        _bounds(),
        section_count=12,
        seeds_per_section=64,
    )
    topology = build_stratified_seed_mesh_topology(layout)

    assert topology_connects_sections(layout, topology) is False
    assert max(topology.face_vertex_indices) < layout.seed_count


def test_seed_topology_adds_no_vertices_for_unequal_rows() -> None:
    layout = derive_global_flow_path_layout(
        _bounds(),
        seed_count=64,
        front_intake_z=9.0,
        max_cell_spacing=0.25,
    )
    topology = build_stratified_seed_mesh_topology(layout)

    assert sum(layout.row_counts) == 64
    assert set(topology.face_vertex_counts) <= {3, 4}
    assert max(topology.face_vertex_indices) == 63


def test_seed_mesh_authoring_preserves_the_semantic_vertex_count() -> None:
    layout = derive_volume_coverage_layout(
        _bounds(),
        section_count=8,
        seeds_per_section=64,
    )
    usd_geom = _FakeUsdGeom()

    author_streamlines_seed_mesh_in_kit(
        object(),
        layout=layout,
        UsdGeom=usd_geom,
    )

    assert len(usd_geom.mesh.points.Get()) == layout.seed_count


def test_volume_curve_membership_uses_curve_start_z() -> None:
    points = (
        (0.0, 0.0, 8.1),
        (0.0, 0.0, 7.0),
        (0.0, 0.0, -7.9),
        (0.0, 0.0, -8.5),
    )

    assert curves_per_section_from_starts(points, (2, 2), (8.0, -8.0)) == (1, 1)


@pytest.mark.parametrize(
    "bounds",
    (
        ((0.0, 0.0, 0.0), (0.0, 1.0, 1.0)),
        ((0.0, 0.0, 0.0), (1.0, -1.0, 1.0)),
    ),
)
def test_degenerate_bounds_fail_explicitly(bounds) -> None:
    with pytest.raises(ValueError):
        derive_volume_coverage_layout(
            bounds,
            section_count=8,
            seeds_per_section=64,
        )


def test_preview_uses_selected_profile_and_workload_without_cache_mutation() -> None:
    runtime = _PreviewRuntime()
    before = runtime.production_state

    result = asyncio.run(
        runtime.run_streamlines_profile_preview(
            profile_id=StreamlinesProfileId.VOLUME_COVERAGE,
            workload="Surge",
            tuning_selection=DEFAULT_VOLUME_COVERAGE_TUNING,
        )
    )[0]

    assert runtime.calls == [
        (
            StreamlinesProfileId.VOLUME_COVERAGE,
            "Surge",
            DEFAULT_VOLUME_COVERAGE_TUNING,
        )
    ]
    assert result.expected_curve_count == 6144
    assert runtime.production_state is before
    assert runtime.cache_build_calls == runtime.cache_rebuild_calls == 0


def test_repeated_previews_replace_one_preview_without_duplicate_state() -> None:
    runtime = _PreviewRuntime()

    for workload in ("Idle", "Nominal", "Surge"):
        asyncio.run(
            runtime.run_streamlines_profile_preview(
                profile_id=StreamlinesProfileId.GLOBAL_FLOW_PATH,
                workload=workload,
                tuning_selection=DEFAULT_GLOBAL_FLOW_PATH_TUNING,
            )
        )

    assert runtime.active_preview_count == 1
    assert len(runtime.calls) == 3


def test_guided_validation_rejects_wrong_profile_and_workload() -> None:
    wrong_profile_runtime = _PreviewRuntime()
    _begin_final_delta_validation(wrong_profile_runtime)

    with pytest.raises(StreamlinesPreviewSelectionMismatchError):
        asyncio.run(
            wrong_profile_runtime.run_streamlines_profile_preview(
                profile_id=StreamlinesProfileId.GLOBAL_FLOW_PATH,
                workload="Idle",
                tuning_selection=DEFAULT_GLOBAL_FLOW_PATH_TUNING,
            )
        )
    wrong_workload_runtime = _PreviewRuntime()
    _begin_final_delta_validation(wrong_workload_runtime)
    with pytest.raises(StreamlinesPreviewSelectionMismatchError):
        asyncio.run(
            wrong_workload_runtime.run_streamlines_profile_preview(
                profile_id=StreamlinesProfileId.VOLUME_COVERAGE,
                workload="Nominal",
                tuning_selection=DEFAULT_VOLUME_COVERAGE_TUNING,
            )
        )

    assert wrong_profile_runtime.calls == []
    assert wrong_workload_runtime.calls == []
    assert not wrong_profile_runtime._streamlines_phase44a_validation_session.failed
    assert not wrong_workload_runtime._streamlines_phase44a_validation_session.failed
    assert "expected_profile=volume_coverage" in "\n".join(
        wrong_profile_runtime.messages
    )
    assert "selected_workload=Nominal" in "\n".join(wrong_workload_runtime.messages)


def test_accepted_candidates_are_immutable_effective_snapshots() -> None:
    global_candidate = AcceptedStreamlinesCandidate.capture(
        DEFAULT_GLOBAL_FLOW_PATH_TUNING
    )
    volume_candidate = AcceptedStreamlinesCandidate.capture(
        DEFAULT_VOLUME_COVERAGE_TUNING
    )

    old_volume_candidate = AcceptedStreamlinesCandidate.capture(
        VolumeCoverageTuning(
            section_count=24,
            seeds_per_section=256,
            max_steps=15,
            step_scale=1.0,
        )
    )

    assert global_candidate.geometry_contract.seed_count == 256
    assert global_candidate.geometry_contract.max_step_cell_multiplier == 1.0
    assert volume_candidate.geometry_contract.section_count == 24
    assert volume_candidate.geometry_contract.seed_count == 256
    assert volume_candidate.geometry_contract.max_steps == 20
    assert volume_candidate.signature != old_volume_candidate.signature
    assert global_candidate.signature != volume_candidate.signature


def test_validation_ignores_live_tuning_and_uses_accepted_snapshot() -> None:
    runtime = _PreviewRuntime()
    _begin_final_delta_validation(runtime)
    changed_live = VolumeCoverageTuning(
        section_count=8,
        seeds_per_section=64,
        max_steps=10,
        step_scale=2.0,
    )

    asyncio.run(
        runtime.run_streamlines_profile_preview(
            profile_id=StreamlinesProfileId.VOLUME_COVERAGE,
            workload="Idle",
            tuning_selection=changed_live,
        )
    )

    assert runtime.calls[-1][2] == FINAL_VOLUME_COVERAGE_CANDIDATE
    receipt = "\n".join(runtime.messages)
    assert "candidate_source=ACCEPTED_SESSION" in receipt
    assert "live_tuning_ignored=True" in receipt
    assert "accepted_candidate_signature=" in receipt


def test_validation_mismatch_keeps_same_action_and_does_not_execute() -> None:
    runtime = _PreviewRuntime()
    _begin_final_delta_validation(runtime)
    before_calls = tuple(runtime.calls)
    expected = runtime._streamlines_phase44a_validation_session.expected_milestone

    with pytest.raises(StreamlinesPreviewSelectionMismatchError):
        asyncio.run(
            runtime.run_streamlines_profile_preview(
                profile_id=StreamlinesProfileId.VOLUME_COVERAGE,
                workload="Critical",
                tuning_selection=DEFAULT_VOLUME_COVERAGE_TUNING,
            )
        )

    assert tuple(runtime.calls) == before_calls
    assert (
        runtime._streamlines_phase44a_validation_session.expected_milestone == expected
    )
    assert runtime.messages[-1].count('Select "Volume Coverage"') == 1
    assert 'select "Idle" in "Workload"' in runtime.messages[-1]


def test_preview_complete_contains_stabilized_multi_sample_performance(
    monkeypatch,
) -> None:
    from digital_twin_runtime_suite.app.flow.performance import (
        ViewportPerformanceSample,
    )
    from digital_twin_runtime_suite.app.streamlines import profile_preview_runtime

    values = iter((80.0, 78.0, 76.0, 74.0, 72.0, 70.0, 68.0, 66.0))

    def sample():
        fps = next(values)
        return ViewportPerformanceSample(
            captured_at=0.0,
            fps=fps,
            frame_time_ms=1000.0 / fps,
            gpu_memory_used_gib=4.5,
            process_memory_used_gib=6.5,
        )

    monkeypatch.setattr(
        profile_preview_runtime,
        "capture_viewport_performance_sample",
        sample,
    )
    runtime = _PreviewRuntime()
    _begin_final_delta_validation(runtime)

    asyncio.run(
        runtime.run_streamlines_profile_preview(
            profile_id=StreamlinesProfileId.VOLUME_COVERAGE,
            workload="Idle",
            tuning_selection=DEFAULT_VOLUME_COVERAGE_TUNING,
        )
    )

    receipt = "\n".join(runtime.messages)
    assert runtime.measurement_waits[0] == 10.0
    assert len(runtime.measurement_waits) == 8
    assert "performance_samples=8" in receipt
    assert "viewport_fps_current=66.0" in receipt
    assert "viewport_fps_minimum=66.0" in receipt
    assert receipt.index("Allowing viewport to stabilize") < receipt.rindex("COMPLETE")


def test_superseded_preview_cancels_delayed_performance_receipt() -> None:
    async def scenario():
        runtime = _BlockingPerformanceRuntime()
        first = asyncio.create_task(
            runtime.run_streamlines_profile_preview(
                profile_id=StreamlinesProfileId.GLOBAL_FLOW_PATH,
                workload="Idle",
                tuning_selection=DEFAULT_GLOBAL_FLOW_PATH_TUNING,
            )
        )
        await runtime.measurement_started.wait()
        second = asyncio.create_task(
            runtime.run_streamlines_profile_preview(
                profile_id=StreamlinesProfileId.GLOBAL_FLOW_PATH,
                workload="Nominal",
                tuning_selection=DEFAULT_GLOBAL_FLOW_PATH_TUNING,
            )
        )
        with pytest.raises(asyncio.CancelledError):
            await first
        runtime.cancel_streamlines_profile_preview_measurement()
        with pytest.raises(asyncio.CancelledError):
            await second
        assert not any(
            "workload=Idle" in message and "COMPLETE" in message
            for message in runtime.messages
        )

    asyncio.run(scenario())


def test_lifecycle_cancel_stops_pending_measurement() -> None:
    async def scenario():
        runtime = _BlockingPerformanceRuntime()
        task = asyncio.create_task(
            runtime.run_streamlines_profile_preview(
                profile_id=StreamlinesProfileId.GLOBAL_FLOW_PATH,
                workload="Idle",
                tuning_selection=DEFAULT_GLOBAL_FLOW_PATH_TUNING,
            )
        )
        await runtime.measurement_started.wait()
        runtime.cancel_streamlines_profile_preview_measurement()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert runtime._streamlines_preview_performance_task is None

    asyncio.run(scenario())


def test_final_volume_delta_validation_uses_one_accepted_candidate() -> None:
    runtime = _PreviewRuntime()
    _begin_final_delta_validation(runtime)
    results = {}

    for workload in PREVIEW_WORKLOAD_OPTIONS:
        results[workload] = asyncio.run(
            runtime.run_streamlines_profile_preview(
                profile_id=StreamlinesProfileId.VOLUME_COVERAGE,
                workload=workload,
                tuning_selection=DEFAULT_VOLUME_COVERAGE_TUNING,
            )
        )[0]

    assert runtime._streamlines_phase44a_validation_session.terminal_emitted
    receipt = "\n".join(runtime.messages)
    assert "passed final geometry validation" in receipt
    assert "expected_curves=6144; actual_curves=6144" in receipt
    volume_signature = runtime._streamlines_phase44a_accepted_candidates[
        StreamlinesProfileId.VOLUME_COVERAGE
    ].signature
    assert receipt.count("candidate_source=ACCEPTED_SESSION") == 4
    assert receipt.count(f"accepted_candidate_signature={volume_signature}") == 4
    assert results["Nominal"].point_count == 122_880
    assert all(
        call[0] is StreamlinesProfileId.VOLUME_COVERAGE
        and call[2] == FINAL_VOLUME_COVERAGE_CANDIDATE
        for call in runtime.calls
    )


def test_final_volume_validation_rejects_changed_curve_count() -> None:
    runtime = _CurveCountMismatchRuntime()
    _begin_final_delta_validation(runtime)

    with pytest.raises(RuntimeError, match="curve count changed"):
        asyncio.run(
            runtime.run_streamlines_profile_preview(
                profile_id=StreamlinesProfileId.VOLUME_COVERAGE,
                workload="Idle",
                tuning_selection=DEFAULT_VOLUME_COVERAGE_TUNING,
            )
        )

    assert runtime._streamlines_phase44a_validation_session.failed
    assert "TEST COMPLETE" not in "\n".join(runtime.messages)


def _begin_final_delta_validation(runtime) -> None:
    runtime.announce_streamlines_phase44a_acceptance_when_ready(
        no_pending_visualization=True,
        no_pending_airflow=True,
    )
    assert (
        runtime._streamlines_phase44a_validation_session.expected_milestone
        == "volume_coverage:Idle"
    )
    assert (
        runtime._streamlines_phase44a_accepted_candidates[
            StreamlinesProfileId.GLOBAL_FLOW_PATH
        ].selection
        == FINAL_GLOBAL_FLOW_PATH_CANDIDATE
    )
    assert runtime._streamlines_phase44a_tuning_session is None
    assert "PHASE_4_4A_TUNING" not in "\n".join(runtime.messages)


class _PreviewRuntime(StreamlinesProfilePreviewRuntimeMixin):
    def __init__(self) -> None:
        self._flow_lifecycle_state = "DETACHED"
        self.messages = []
        self.calls = []
        self.active_preview_count = 0
        self.cache_build_calls = 0
        self.cache_rebuild_calls = 0
        self.production_state = object()
        self.targets = tuple(
            SimpleNamespace(
                binding=SimpleNamespace(
                    workload_mode=workload,
                    dataset_identity=f"server/load_{workload.lower()}",
                ),
                dataset=SimpleNamespace(),
            )
            for workload in PREVIEW_WORKLOAD_OPTIONS
        )
        self.reset_streamlines_profile_preview_state()
        self.measurement_waits = []

    def resolve_configured_airflow_targets(self):
        return self.targets

    def streamlines_phase44a_preview_ready(self):
        return True

    def _streamlines_carb_logger(self):
        return SimpleNamespace(log_warn=self.messages.append)

    async def _await_one_preview_viewport_update(self):
        await asyncio.sleep(0)

    async def _wait_preview_measurement_interval(self, seconds):
        self.measurement_waits.append(seconds)
        await asyncio.sleep(0)

    async def _preview_streamlines_profile_target_in_kit(
        self,
        *,
        binding,
        airflow_dataset,
        profile_id,
        tuning,
    ):
        del airflow_dataset
        self.calls.append((profile_id, binding.workload_mode, tuning))
        self.active_preview_count = 1
        expected = tuning.geometry_contract.seed_count
        expected *= tuning.geometry_contract.section_count
        return StreamlinesProfilePreviewResult(
            workload=binding.workload_mode,
            dataset_identity=binding.dataset_identity,
            sample_index=0,
            source_vti=f"{binding.workload_mode.lower()}.vti",
            curve_count=expected,
            point_count=expected * tuning.max_steps,
            generation_ms=1.0,
            seed_type="point_grid",
            seed_columns=16,
            seed_rows=8,
            seed_points=expected,
            horizontal_spacing=1.0,
            vertical_spacing=1.0,
            edge_margin_x=1.0,
            edge_margin_y=1.0,
            seed_plane_z=8.0,
            operator_type="standard",
            profile_id=profile_id.value,
            section_count=tuning.geometry_contract.section_count,
            seeds_per_section=tuning.geometry_contract.seed_count,
            expected_curve_count=expected,
        )


class _BlockingPerformanceRuntime(_PreviewRuntime):
    def __init__(self) -> None:
        super().__init__()
        self.measurement_started = asyncio.Event()
        self.release_measurement = asyncio.Event()

    async def _wait_preview_measurement_interval(self, seconds):
        self.measurement_waits.append(seconds)
        if seconds == 10.0:
            self.measurement_started.set()
            await self.release_measurement.wait()
        else:
            await asyncio.sleep(0)


class _CurveCountMismatchRuntime(_PreviewRuntime):
    async def _preview_streamlines_profile_target_in_kit(self, **kwargs):
        result = await super()._preview_streamlines_profile_target_in_kit(**kwargs)
        return replace(result, curve_count=result.curve_count - 1)


def _bounds():
    return ((-17.0, -9.0, -10.0), (17.0, 9.0, 10.0))


class _FakeAttr:
    def __init__(self) -> None:
        self.value = None

    def Set(self, value):
        self.value = value

    def Get(self):
        return self.value


class _FakeMesh:
    def __init__(self) -> None:
        self.points = _FakeAttr()
        self.counts = _FakeAttr()
        self.indices = _FakeAttr()
        self.extent = _FakeAttr()

    def CreatePointsAttr(self):
        return self.points

    def CreateFaceVertexCountsAttr(self):
        return self.counts

    def CreateFaceVertexIndicesAttr(self):
        return self.indices

    def CreateExtentAttr(self):
        return self.extent

    def GetPointsAttr(self):
        return self.points

    def GetFaceVertexCountsAttr(self):
        return self.counts

    def GetFaceVertexIndicesAttr(self):
        return self.indices


class _FakeUsdGeom:
    def __init__(self) -> None:
        self.mesh = _FakeMesh()
        mesh = self.mesh

        class Mesh:
            @staticmethod
            def Define(_stage, _path):
                return mesh

        self.Mesh = Mesh
