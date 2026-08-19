"""Focused final-cache production playback sanity contracts."""

import asyncio
from types import SimpleNamespace

from digital_twin_runtime_suite.app.streamlines.cache_playback_sanity import (
    StreamlinesCachePlaybackSanityMixin,
    StreamlinesTemporalPointMatch,
    evaluate_streamlines_cache_loop,
    evaluate_streamlines_temporal_point_matches,
    probe_streamlines_sample_attributes,
    streamlines_sample_array_probe,
)
from digital_twin_runtime_suite.app.streamlines.constant_topology import (
    streamlines_point_array_signature,
)
from digital_twin_runtime_suite.app.streamlines.playback_runtime import (
    StreamlinesStateReplacementProof,
)
from digital_twin_runtime_suite.app.streamlines.profile import (
    StreamlinesProfileId,
    final_geometry_contract,
    geometry_contract_signature,
)


def _tick(index: int):
    return SimpleNamespace(
        resolution=SimpleNamespace(
            sample=SimpleNamespace(sample_index=index),
            normalized_phase_seconds=index * 0.2,
            is_no_op=False,
        )
    )


def _probe(index: int, *, point_count: int = 12):
    return streamlines_sample_array_probe(
        sample_index=index,
        requested_time_code=index * 10.0,
        timeline_current_time_seconds=index * 0.2,
        resolved_usd_time_code=index * 10.0,
        points=tuple(range(point_count)),
        curve_vertex_counts=(point_count // 2, point_count - point_count // 2),
        speed_values=tuple(float(value) for value in range(point_count)),
    )


def _point_match(index: int, *, composed_offset: float | None = None):
    persisted = streamlines_point_array_signature(
        ((float(index), 0.0, 0.0), (float(index), 1.0, 0.0))
    )
    offset = float(index) if composed_offset is None else composed_offset
    composed = streamlines_point_array_signature(
        ((offset, 0.0, 0.0), (offset, 1.0, 0.0))
    )
    return StreamlinesTemporalPointMatch(
        sample_index=index,
        requested_time_code=index * 10.0,
        selected_timeline_time_seconds=index * 0.2,
        composed_usd_time_code=index * 10.0,
        persisted=persisted,
        composed=composed,
    )


def test_distinct_matching_temporal_point_signatures_pass() -> None:
    evidence = evaluate_streamlines_temporal_point_matches(
        (_point_match(0), _point_match(1)),
        required_sample_indices=(0, 1),
        expected_point_count=2,
    )

    assert evidence.passed


def test_static_composed_points_cannot_pass_advancing_sample_ids() -> None:
    evidence = evaluate_streamlines_temporal_point_matches(
        (_point_match(0), _point_match(1, composed_offset=0.0)),
        required_sample_indices=(0, 1),
        expected_point_count=2,
    )

    assert not evidence.passed


def test_persisted_composed_point_signature_mismatch_fails() -> None:
    evidence = evaluate_streamlines_temporal_point_matches(
        (_point_match(0), _point_match(1, composed_offset=2.0)),
        required_sample_indices=(0, 1),
        expected_point_count=2,
    )

    assert not evidence.passed


def test_full_eighty_state_loop_requires_actual_79_to_0_wrap() -> None:
    ticks = tuple(_tick(index) for index in (*range(80), 0))
    proofs = tuple(
        StreamlinesStateReplacementProof(index, index) for index in (*range(80), 0)
    )

    evidence = evaluate_streamlines_cache_loop(
        profile_id=StreamlinesProfileId.VOLUME_COVERAGE,
        workload="Nominal",
        sample_count=80,
        sample_interval_seconds=0.2,
        scheduler_tasks=1,
        ticks=ticks,
        replacement_proofs=proofs,
        composed_sample_probes=tuple(_probe(index) for index in range(80)),
        renderer_integrity_passed=True,
        duplicate_presentation_prims=0,
    )

    assert evidence.passed
    assert evidence.wrap_transition == (79, 0)
    assert evidence.distinct_sample_count == 80


def test_scheduler_existence_or_nonwrapped_samples_cannot_pass() -> None:
    ticks = tuple(_tick(index) for index in range(20))
    evidence = evaluate_streamlines_cache_loop(
        profile_id=StreamlinesProfileId.VOLUME_COVERAGE,
        workload="Nominal",
        sample_count=80,
        sample_interval_seconds=0.2,
        scheduler_tasks=1,
        ticks=ticks,
        replacement_proofs=tuple(
            StreamlinesStateReplacementProof(index, index) for index in range(20)
        ),
        composed_sample_probes=tuple(_probe(index) for index in range(20)),
        renderer_integrity_passed=True,
        duplicate_presentation_prims=0,
    )

    assert not evidence.passed
    assert evidence.wrap_transition is None


def test_scheduler_advancement_alone_cannot_pass_without_composed_proof() -> None:
    ticks = tuple(_tick(index) for index in (*range(80), 0))
    evidence = evaluate_streamlines_cache_loop(
        profile_id=StreamlinesProfileId.VOLUME_COVERAGE,
        workload="Nominal",
        sample_count=80,
        sample_interval_seconds=0.2,
        scheduler_tasks=1,
        ticks=ticks,
        replacement_proofs=tuple(
            StreamlinesStateReplacementProof(index, index) for index in (*range(80), 0)
        ),
        composed_sample_probes=(),
        renderer_integrity_passed=True,
        duplicate_presentation_prims=0,
    )

    assert not evidence.passed
    assert not evidence.composed_samples_passed


def test_known_variable_topology_renderer_failure_cannot_pass_gate() -> None:
    ticks = tuple(_tick(index) for index in (*range(80), 0))
    # Curve/point counts deliberately vary; playback correctness is the authored
    # temporal state replacement, not topology equality between states.
    for index, tick in enumerate(ticks):
        tick.resolution.sample.curve_count = 100 + index
        tick.resolution.sample.point_count = 1000 + index * 7
    proofs = tuple(
        StreamlinesStateReplacementProof(index, index) for index in (*range(80), 0)
    )

    evidence = evaluate_streamlines_cache_loop(
        profile_id=StreamlinesProfileId.VOLUME_COVERAGE,
        workload="Nominal",
        sample_count=80,
        sample_interval_seconds=0.2,
        scheduler_tasks=1,
        ticks=ticks,
        replacement_proofs=proofs,
        composed_sample_probes=tuple(
            _probe(index, point_count=12 + 2 * (index % 2)) for index in range(80)
        ),
        renderer_integrity_passed=False,
        duplicate_presentation_prims=0,
    )

    assert not evidence.passed
    assert evidence.composed_samples_passed
    assert not evidence.renderer_integrity_passed


def test_failed_temporal_replacement_or_duplicate_root_rejects_loop() -> None:
    ticks = tuple(_tick(index) for index in (*range(80), 0))
    proofs = [
        StreamlinesStateReplacementProof(index, index) for index in (*range(80), 0)
    ]
    proofs[15] = StreamlinesStateReplacementProof(15, 14)

    evidence = evaluate_streamlines_cache_loop(
        profile_id=StreamlinesProfileId.VOLUME_COVERAGE,
        workload="Nominal",
        sample_count=80,
        sample_interval_seconds=0.2,
        scheduler_tasks=1,
        ticks=ticks,
        replacement_proofs=tuple(proofs),
        composed_sample_probes=tuple(_probe(index) for index in range(80)),
        renderer_integrity_passed=True,
        duplicate_presentation_prims=1,
    )

    assert not evidence.passed
    assert not evidence.replacements_passed


def test_mismatched_points_and_curve_topology_fails_probe() -> None:
    probe = streamlines_sample_array_probe(
        sample_index=1,
        requested_time_code=10.0,
        timeline_current_time_seconds=0.2,
        resolved_usd_time_code=10.0,
        points=(1, 2, 3),
        curve_vertex_counts=(2, 2),
        speed_values=(0.1, 0.2, 0.3),
    )

    assert not probe.passed
    assert probe.point_count == 3
    assert probe.required_point_count == 4


def test_mismatched_speed_and_points_fails_probe() -> None:
    probe = streamlines_sample_array_probe(
        sample_index=2,
        requested_time_code=20.0,
        timeline_current_time_seconds=0.4,
        resolved_usd_time_code=20.0,
        points=(1, 2, 3, 4),
        curve_vertex_counts=(2, 2),
        speed_values=(0.1, 0.2, 0.3),
    )

    assert not probe.passed
    assert probe.speed_count == 3


def test_exact_sample_probe_does_not_change_authored_arrays() -> None:
    points = [(1.0, 2.0, 3.0), (4.0, 5.0, 6.0)]
    counts = [2]
    speeds = [0.25, 0.5]
    before = (list(points), list(counts), list(speeds))

    probe = streamlines_sample_array_probe(
        sample_index=79,
        requested_time_code=790.0,
        timeline_current_time_seconds=15.8,
        resolved_usd_time_code=790.0,
        points=points,
        curve_vertex_counts=counts,
        speed_values=speeds,
    )

    assert probe.passed
    assert (points, counts, speeds) == before
    assert probe.requested_time_code == 790.0


def test_exact_attribute_probe_reads_all_authored_arrays_at_same_time_code() -> None:
    calls = []

    class Attribute:
        def __init__(self, value):
            self.value = value

        def Get(self, time_code):
            calls.append(time_code)
            return self.value

    points = [(1.0, 2.0, 3.0), (4.0, 5.0, 6.0)]
    counts = [2]
    speeds = [0.25, 0.5]
    probe = probe_streamlines_sample_attributes(
        sample_index=1,
        requested_time_code=10.0,
        timeline_current_time_seconds=0.2,
        resolved_usd_time_code=10.0,
        usd_time_code=10.0,
        points_attr=Attribute(points),
        curve_vertex_counts_attr=Attribute(counts),
        speed_attr=Attribute(speeds),
    )

    assert probe.passed
    assert calls == [10.0, 10.0, 10.0]
    assert points == [(1.0, 2.0, 3.0), (4.0, 5.0, 6.0)]
    assert counts == [2]
    assert speeds == [0.25, 0.5]


class _ReadinessRuntime(StreamlinesCachePlaybackSanityMixin):
    def __init__(self) -> None:
        self.logs = []
        self._streamlines_cache_build_active_sample_index = None
        self._streamlines_profile_preference = SimpleNamespace(
            snapshot=SimpleNamespace(pending_profile=None)
        )
        self._airflow_state = SimpleNamespace(snapshot=SimpleNamespace(pending=None))
        self.reset_streamlines_cache_playback_sanity_state()

    def streamlines_profile_preference_snapshot(self):
        return self._streamlines_profile_preference.snapshot

    def visualization_snapshot(self):
        return SimpleNamespace(pending=None)

    def final_streamlines_cache_readiness_snapshot(self):
        snapshots = []
        for workload in ("Idle", "Nominal", "Surge", "Critical"):
            for profile_id in StreamlinesProfileId:
                contract = final_geometry_contract(profile_id)
                snapshots.append(
                    SimpleNamespace(
                        workload=workload,
                        profile_id=profile_id,
                        inspection=SimpleNamespace(
                            classification="VALID",
                            metadata=SimpleNamespace(
                                schema_version=5,
                                profile_id=profile_id.value,
                                topology_consistent=True,
                                states=(
                                    SimpleNamespace(
                                        curve_count=(
                                            contract.seed_count * contract.section_count
                                        ),
                                        point_count=(
                                            contract.seed_count
                                            * contract.section_count
                                            * contract.max_steps
                                        ),
                                    ),
                                ),
                                settings=SimpleNamespace(
                                    profile_signature=geometry_contract_signature(
                                        contract
                                    ),
                                    persisted_attributes=(
                                        "points",
                                        "primvars:dtrs:speed",
                                    ),
                                ),
                            ),
                        ),
                    )
                )
        return tuple(snapshots)

    def _streamlines_carb_logger(self):
        return SimpleNamespace(log_warn=self.logs.append)


def test_ready_requires_all_eight_signed_speed_caches_and_emits_once() -> None:
    runtime = _ReadinessRuntime()

    assert runtime.announce_streamlines_phase44b_cache_playback_when_ready()
    assert not runtime.announce_streamlines_phase44b_cache_playback_when_ready()
    assert "PHASE_4_4B_CACHE_PLAYBACK | READY" in runtime.logs[0]
    assert "Volume Coverage" in runtime.logs[0]


def test_explicit_presentation_prototype_ready_requires_exact_fixed_counts() -> None:
    runtime = _ReadinessRuntime()

    assert runtime.announce_streamlines_phase44b_explicit_presentation_when_ready()
    assert not runtime.announce_streamlines_phase44b_explicit_presentation_when_ready()
    assert "PHASE_4_4B_EXPLICIT_PRESENTATION | READY" in runtime.logs[0]
    assert not runtime.announce_streamlines_phase44b_constant_topology_when_ready()


def test_variable_topology_prototype_cannot_announce_ready() -> None:
    runtime = _ReadinessRuntime()
    snapshots = list(runtime.final_streamlines_cache_readiness_snapshot())
    target = next(
        snapshot
        for snapshot in snapshots
        if snapshot.workload == "Nominal"
        and snapshot.profile_id is StreamlinesProfileId.VOLUME_COVERAGE
    )
    target.inspection.metadata.states[0].point_count = 121_712
    runtime.final_streamlines_cache_readiness_snapshot = lambda: tuple(snapshots)

    assert not runtime.announce_streamlines_phase44b_explicit_presentation_when_ready()
    assert runtime.logs == []


def test_explicit_prototype_requires_manual_visual_confirmation() -> None:
    runtime = _ReadinessRuntime()

    assert runtime.announce_streamlines_phase44b_explicit_presentation_when_ready()
    assert not runtime.confirm_streamlines_explicit_presentation_playback()
    session = runtime._streamlines_explicit_presentation_session
    assert session.record("technical")
    assert runtime.confirm_streamlines_explicit_presentation_playback()
    output = "\n".join(runtime.logs)
    assert output.count("TEST COMPLETE") == 1
    assert "explicit Streamlines presentation playback passed" in output


def test_bad_profile_signature_or_speed_contract_blocks_ready() -> None:
    runtime = _ReadinessRuntime()
    snapshots = list(runtime.final_streamlines_cache_readiness_snapshot())
    snapshots[3].inspection.metadata.settings.profile_signature = "wrong"
    runtime.final_streamlines_cache_readiness_snapshot = lambda: tuple(snapshots)

    assert not runtime.announce_streamlines_phase44b_cache_playback_when_ready()
    assert runtime.logs == []


def test_completed_cache_build_guidance_is_retired() -> None:
    from digital_twin_runtime_suite.app.streamlines.cache_runtime import (
        StreamlinesCacheRuntimeMixin,
    )

    runtime = StreamlinesCacheRuntimeMixin()
    assert not runtime.announce_streamlines_phase44b_cache_build_when_ready()


def test_startup_receipt_sweep_covers_all_four_workloads_and_both_profiles() -> None:
    from digital_twin_runtime_suite.app.streamlines.cache_runtime import (
        StreamlinesCacheRuntimeMixin,
    )

    class Runtime(StreamlinesCacheRuntimeMixin):
        def __init__(self):
            self.calls = []

        @staticmethod
        def resolve_configured_airflow_targets():
            return tuple(
                SimpleNamespace(
                    binding=SimpleNamespace(workload_mode=workload),
                    dataset=object(),
                )
                for workload in ("Idle", "Nominal", "Surge", "Critical")
            )

        async def ensure_streamlines_cache_validation_in_background(
            self, binding, _dataset, *, profile_id
        ):
            self.calls.append((binding.workload_mode, profile_id))
            return SimpleNamespace(
                inspection=SimpleNamespace(classification="VALID"),
                receipt_source="SESSION",
            )

    runtime = Runtime()
    receipts = asyncio.run(
        runtime.ensure_configured_streamlines_cache_validations_in_background()
    )

    assert len(receipts) == 8
    assert set(runtime.calls) == {
        (workload, profile_id)
        for workload in ("Idle", "Nominal", "Surge", "Critical")
        for profile_id in StreamlinesProfileId
    }
