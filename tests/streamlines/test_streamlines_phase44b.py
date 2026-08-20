from __future__ import annotations

import asyncio
import sys
from dataclasses import replace
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from digital_twin_runtime_suite.app.config import (
    RuntimeConfig,
    StreamlinesPresentationConfig,
)
from digital_twin_runtime_suite.app.flow.static_source import (
    StaticVelocitySourceDescriptor,
)
from digital_twin_runtime_suite.app.streamlines.cache import (
    CACHE_SCHEMA_VERSION,
    StreamlinesCacheOwnership,
    StreamlinesCacheSpeedEvidence,
    streamlines_cache_paths,
    streamlines_settings_signature,
)
from digital_twin_runtime_suite.app.streamlines.cache_runtime import (
    StreamlinesCacheRuntimeMixin,
)
from digital_twin_runtime_suite.app.streamlines.presentation import (
    PaletteStop,
    PhysicalSpeedScale,
    StreamlinesPresentation,
    normalize_speed,
    palette_color,
)
from digital_twin_runtime_suite.app.streamlines.presentation_runtime import (
    StreamlinesPresentationRuntimeMixin,
)
from digital_twin_runtime_suite.app.streamlines.profile import (
    DEFAULT_STREAMLINES_PROFILE,
    FINAL_GLOBAL_FLOW_PATH_GEOMETRY_CONTRACT,
    FINAL_VOLUME_COVERAGE_GEOMETRY_CONTRACT,
    StreamlinesProfileId,
)
from digital_twin_runtime_suite.app.streamlines.profile_state import (
    StreamlinesProfileState,
)
from digital_twin_runtime_suite.app.streamlines.profile_transition import (
    StreamlinesProfileTransitionMixin,
)
from digital_twin_runtime_suite.app.streamlines.speed import (
    validate_persisted_speed_magnitudes,
)
from digital_twin_runtime_suite.app.streamlines.speed_distribution import (
    SpeedDistribution,
    SpeedDistributionAccumulator,
    build_streamlines_cache_speed_evidence,
    distributed_manifest_state_indices,
    fixed_scale_coverage,
    fixed_scale_coverage_from_cache_evidence,
    proposed_speed_max,
    speed_scale_candidate_from_critical_volume,
    volume_scale_from_cache_evidence,
)
from digital_twin_runtime_suite.app.streamlines.speed_distribution_runtime import (
    StreamlinesSpeedDistributionRuntimeMixin,
)
from digital_twin_runtime_suite.app.visualization_mode.model import VisualizationMode


def _descriptor(spacing=(0.01, 0.01, 0.01)) -> StaticVelocitySourceDescriptor:
    return StaticVelocitySourceDescriptor(
        workload="Nominal",
        dataset_identity="server/load_normal",
        sample_index=0,
        vti_path=Path("nominal.vti"),
        dataset_prim_path="/DTRS/VTKImageData",
        velocity_field_prim_path="/DTRS/PointData/vel",
        world_bounds=((0.0, 0.0, 0.0), (1.0, 0.5, 1.5)),
        dimensions=(101, 51, 151),
        spacing=spacing,
        origin=(0.0, 0.0, 0.0),
        source_origin=(0.0, 0.0, 0.0),
        stage_meters_per_unit=1.0,
    )


def _presentation(**changes) -> StreamlinesPresentation:
    base = StreamlinesPresentation(
        PhysicalSpeedScale(0.0, 4.0),
        (
            PaletteStop(0.0, (0.0, 0.0, 0.2)),
            PaletteStop(0.25, (0.0, 1.0, 1.0)),
            PaletteStop(0.5, (0.0, 1.0, 0.0)),
            PaletteStop(0.75, (1.0, 1.0, 0.0)),
            PaletteStop(1.0, (1.0, 0.0, 0.0)),
        ),
        0.85,
        1.5,
        0.2,
    )
    return replace(base, **changes)


def test_final_profiles_and_default_are_exact() -> None:
    assert DEFAULT_STREAMLINES_PROFILE is StreamlinesProfileId.VOLUME_COVERAGE
    assert FINAL_VOLUME_COVERAGE_GEOMETRY_CONTRACT == replace(
        FINAL_VOLUME_COVERAGE_GEOMETRY_CONTRACT,
        section_count=24,
        seed_count=256,
        max_steps=20,
        min_step_cell_multiplier=0.01,
        initial_step_cell_multiplier=0.2,
        max_step_cell_multiplier=0.5,
    )
    assert FINAL_GLOBAL_FLOW_PATH_GEOMETRY_CONTRACT.seed_count == 256
    assert FINAL_GLOBAL_FLOW_PATH_GEOMETRY_CONTRACT.max_steps == 200
    assert (
        FINAL_GLOBAL_FLOW_PATH_GEOMETRY_CONTRACT.min_step_cell_multiplier,
        FINAL_GLOBAL_FLOW_PATH_GEOMETRY_CONTRACT.initial_step_cell_multiplier,
        FINAL_GLOBAL_FLOW_PATH_GEOMETRY_CONTRACT.max_step_cell_multiplier,
    ) == (0.02, 0.4, 1.0)


def test_eight_profile_aware_cache_identities_and_paths_are_unique(tmp_path) -> None:
    identities = set()
    paths = set()
    for workload, dataset in (
        ("Idle", "server/load_idle"),
        ("Nominal", "server/load_normal"),
        ("Surge", "server/load_surge"),
        ("Critical", "server/load_critical"),
    ):
        for profile in StreamlinesProfileId:
            ownership = StreamlinesCacheOwnership(workload, dataset, profile.value)
            identities.add(ownership.identity)
            paths.add(streamlines_cache_paths(tmp_path, ownership).geometry_path)
    assert len(identities) == len(paths) == 8
    assert any("volume_coverage" in str(path) for path in paths)
    assert any("global_flow_path" in str(path) for path in paths)
    assert CACHE_SCHEMA_VERSION == 5


def test_source_config_owns_the_one_shared_five_stop_palette() -> None:
    config = RuntimeConfig.load(
        Path(__file__).resolve().parents[2] / "configs/digital_twin_runtime_suite.toml",
        apply_local_overrides=False,
    ).streamlines_presentation

    assert tuple(position for position, _color in config.palette) == (
        0.0,
        0.25,
        0.5,
        0.75,
        1.0,
    )
    assert config.speed_units == "source velocity units"
    assert (config.opacity, config.emission_intensity, config.lighting_influence) == (
        0.85,
        1.5,
        0.2,
    )


def test_frozen_profile_requests_use_exact_point_grids_and_signatures() -> None:
    descriptor = _descriptor()
    volume = StreamlinesCacheRuntimeMixin._build_streamlines_cache_request(
        None,
        descriptor,
        profile_id=StreamlinesProfileId.VOLUME_COVERAGE,
    )
    global_path = StreamlinesCacheRuntimeMixin._build_streamlines_cache_request(
        None,
        descriptor,
        profile_id=StreamlinesProfileId.GLOBAL_FLOW_PATH,
    )
    assert volume.profile_id == "volume_coverage"
    assert volume.seed_section_count == 24
    assert len(volume.seed_points) == 24 * 256
    assert volume.max_steps == 20
    assert (volume.min_step_size, volume.initial_step_size, volume.max_step_size) == (
        0.01,
        0.2,
        0.5,
    )
    assert global_path.profile_id == "global_flow_path"
    assert len(global_path.seed_points) == 256
    assert global_path.max_steps == 200
    assert (
        global_path.min_step_size,
        global_path.initial_step_size,
        global_path.max_step_size,
    ) == (0.02, 0.4, 1.0)
    assert streamlines_settings_signature(volume) != streamlines_settings_signature(
        global_path
    )


def test_presentation_changes_never_change_cache_signature() -> None:
    request = StreamlinesCacheRuntimeMixin._build_streamlines_cache_request(
        None,
        _descriptor(),
        profile_id=StreamlinesProfileId.VOLUME_COVERAGE,
    )
    cache_signature = streamlines_settings_signature(request)
    assert _presentation().signature != _presentation(opacity=0.4).signature
    assert streamlines_settings_signature(request) == cache_signature


def test_fixed_scale_maps_same_speed_and_clamps() -> None:
    presentation = _presentation()
    assert normalize_speed(2.0, presentation.speed_scale) == 0.5
    assert palette_color(2.0, presentation) == (0.0, 1.0, 0.0)
    assert palette_color(0.0, presentation) == palette_color(-0.0, presentation)
    assert palette_color(40.0, presentation) == (1.0, 0.0, 0.0)
    with pytest.raises(ValueError):
        normalize_speed(float("nan"), presentation.speed_scale)


@pytest.mark.parametrize("values", ((float("nan"),), (-0.1,), (1.0,)))
def test_invalid_or_mismatched_speed_is_rejected(values) -> None:
    with pytest.raises(ValueError):
        validate_persisted_speed_magnitudes(values, expected_point_count=2)


def test_distribution_and_fixed_scale_coverage_are_bounded_and_deterministic() -> None:
    accumulator = SpeedDistributionAccumulator(max_samples=8)
    accumulator.add(range(10))
    distribution = accumulator.finish()
    assert distribution.value_count == 10
    assert distribution.minimum == 0.0
    assert distribution.maximum == 9.0
    assert proposed_speed_max((distribution,)) == distribution.p99
    coverage = fixed_scale_coverage(((0.0, 1.0, 2.0, 4.0),), minimum=0.0, maximum=2.0)
    assert coverage.below_percent == 0.0
    assert coverage.inside_percent == 75.0
    assert coverage.above_percent == 25.0


def test_manifest_driven_critical_speed_scale_uses_five_real_states() -> None:
    metadata = SimpleNamespace(sample_count=7, states=tuple(range(7)))
    indices = distributed_manifest_state_indices(metadata)
    distributions = tuple(
        SpeedDistribution(4, 0.0, 0.1, 0.2, 1.0, 3.0, p99, 5.0)
        for p99 in (2.0, 4.0, 6.0, 8.0, 10.0)
    )

    evidence = speed_scale_candidate_from_critical_volume(
        distributions,
        state_indices=indices,
    )

    assert indices == (0, 2, 3, 4, 6)
    assert evidence.state_p99_values == (2.0, 4.0, 6.0, 8.0, 10.0)
    assert evidence.candidate_maximum == pytest.approx(6.0)


def test_volume_build_evidence_selects_shared_p05_p95_and_clipping() -> None:
    accumulator = SpeedDistributionAccumulator()
    accumulator.add(range(101))
    critical_states = tuple(SpeedDistributionAccumulator() for _ in range(5))
    for state, offset in zip(critical_states, (0, 1, 2, 3, 4)):
        state.add(range(offset, offset + 101))

    evidence = build_streamlines_cache_speed_evidence(
        accumulator,
        critical_state_indices=(0, 2, 4, 6, 8),
        critical_state_accumulators=critical_states,
    )

    assert isinstance(evidence, StreamlinesCacheSpeedEvidence)
    assert len(evidence.quantile_values) == 101
    assert StreamlinesCacheSpeedEvidence.from_dict(evidence.to_dict()) == evidence
    assert evidence.critical_state_indices == (0, 2, 4, 6, 8)
    assert evidence.critical_state_p99_values == pytest.approx(
        (99.0, 100.0, 101.0, 102.0, 103.0)
    )
    minimum, maximum = volume_scale_from_cache_evidence((evidence,) * 4)
    assert minimum == pytest.approx(5.0)
    assert maximum == pytest.approx(95.0)
    coverage = fixed_scale_coverage_from_cache_evidence(
        evidence,
        minimum=minimum,
        maximum=maximum,
    )
    assert coverage.below_percent == pytest.approx(5.0)
    assert coverage.above_percent == pytest.approx(5.0)


def test_velocity_scale_uses_only_compact_volume_evidence() -> None:
    class Runtime(StreamlinesSpeedDistributionRuntimeMixin):
        pass

    accumulator = SpeedDistributionAccumulator()
    accumulator.add(range(101))
    critical_states = tuple(SpeedDistributionAccumulator() for _ in range(5))
    for state in critical_states:
        state.add(range(101))
    critical_evidence = build_streamlines_cache_speed_evidence(
        accumulator,
        critical_state_indices=(0, 2, 4, 6, 8),
        critical_state_accumulators=critical_states,
    )
    volume_evidence = build_streamlines_cache_speed_evidence(accumulator)
    entries = []
    for workload, evidence in (
        ("Idle", volume_evidence),
        ("Nominal", volume_evidence),
        ("Surge", volume_evidence),
        ("Critical", critical_evidence),
    ):
        entries.append(
            SimpleNamespace(
                valid=True,
                speed_evidence=evidence,
                entry=SimpleNamespace(
                    workload=workload,
                    dataset_identity=f"server/load_{workload.lower()}",
                    profile_id="volume_coverage",
                ),
            )
        )
        entries.append(
            SimpleNamespace(
                valid=True,
                speed_evidence=None,
                entry=SimpleNamespace(
                    workload=workload,
                    dataset_identity=f"server/load_{workload.lower()}",
                    profile_id="global_flow_path",
                ),
            )
        )

    progress = []
    proposal = asyncio.run(
        Runtime().collect_streamlines_speed_scale_proposal(
            status_callback=progress.append,
            ready_entries=entries,
        )
    )

    assert proposal.scale.minimum == pytest.approx(5.0)
    assert proposal.scale.maximum == pytest.approx(95.0)
    assert len(proposal.receipts) == 4
    assert len(progress) == 4


def test_profile_state_rejects_stale_commit_and_keeps_explicit_preference() -> None:
    state = StreamlinesProfileState()
    first = state.begin(StreamlinesProfileId.GLOBAL_FLOW_PATH)
    second = state.begin(StreamlinesProfileId.VOLUME_COVERAGE)
    assert first is not None and second is not None
    assert not state.commit(first)
    assert state.commit(second)
    state.set_preference(StreamlinesProfileId.GLOBAL_FLOW_PATH)
    assert state.snapshot.preferred_profile is StreamlinesProfileId.GLOBAL_FLOW_PATH


def test_profile_preference_survives_runtime_reset_without_preview_state() -> None:
    runtime = _ProfileTransitionRuntime(classification="VALID", advancing=True)

    runtime.set_streamlines_profile_preference(StreamlinesProfileId.GLOBAL_FLOW_PATH)
    runtime.reset_streamlines_profile_transition_state()

    assert (
        runtime.streamlines_profile_preference_snapshot().preferred_profile
        is StreamlinesProfileId.GLOBAL_FLOW_PATH
    )


def test_cached_profile_switch_commits_only_after_target_advancement() -> None:
    runtime = _ProfileTransitionRuntime(classification="VALID", advancing=True)

    result = asyncio.run(
        runtime.request_streamlines_profile_transition_in_kit(
            StreamlinesProfileId.GLOBAL_FLOW_PATH
        )
    )

    assert result.success is True
    assert result.committed_profile is StreamlinesProfileId.GLOBAL_FLOW_PATH
    assert runtime.events == ["prepare", "scheduler", "advance", "visible"]
    assert runtime.scheduler_tasks == 1
    assert runtime.build_calls == runtime.recompute_calls == runtime.vti_imports == 0


def test_cached_profile_switch_remains_active_with_streamlines_xray() -> None:
    runtime = _ProfileTransitionRuntime(classification="VALID", advancing=True)
    runtime.visualization_snapshot = lambda: SimpleNamespace(
        committed=VisualizationMode.STREAMLINES_XRAY
    )

    result = asyncio.run(
        runtime.request_streamlines_profile_transition_in_kit(
            StreamlinesProfileId.GLOBAL_FLOW_PATH
        )
    )

    assert result.success is True
    assert result.committed_profile is StreamlinesProfileId.GLOBAL_FLOW_PATH
    assert runtime.scheduler_tasks == 1


def test_invalid_profile_target_preserves_loaded_profile_without_mutation() -> None:
    runtime = _ProfileTransitionRuntime(classification="STALE", advancing=True)

    result = asyncio.run(
        runtime.request_streamlines_profile_transition_in_kit(
            StreamlinesProfileId.GLOBAL_FLOW_PATH
        )
    )

    assert result.success is False
    assert result.committed_profile is StreamlinesProfileId.VOLUME_COVERAGE
    assert runtime.events == []
    assert runtime.scheduler_tasks == 1


def test_profile_transition_supports_forward_and_reverse_cached_switches() -> None:
    runtime = _ProfileTransitionRuntime(classification="VALID", advancing=True)

    forward = asyncio.run(
        runtime.request_streamlines_profile_transition_in_kit(
            StreamlinesProfileId.GLOBAL_FLOW_PATH
        )
    )
    reverse = asyncio.run(
        runtime.request_streamlines_profile_transition_in_kit(
            StreamlinesProfileId.VOLUME_COVERAGE
        )
    )

    assert forward.success is True
    assert reverse.success is True
    assert reverse.committed_profile is StreamlinesProfileId.VOLUME_COVERAGE
    assert runtime.scheduler_tasks == 1
    assert runtime.build_calls == runtime.recompute_calls == runtime.vti_imports == 0


def test_cached_profile_transition_has_no_legacy_single_geometry_dependency() -> None:
    source = (
        Path(__file__).parents[2]
        / "src/digital_twin_runtime_suite/app/streamlines/profile_transition.py"
    ).read_text(encoding="utf-8")

    assert "apply_streamlines_presentation_in_kit" not in source
    assert "CACHE_PLAYBACK_CURVES_PATH" not in source


def test_profile_transition_supersession_preserves_the_newest_profile() -> None:
    runtime = _SupersedingProfileTransitionRuntime()

    async def run():
        stale = asyncio.create_task(
            runtime.request_streamlines_profile_transition_in_kit(
                StreamlinesProfileId.GLOBAL_FLOW_PATH
            )
        )
        await runtime.prepare_started.wait()
        newest = await runtime.request_streamlines_profile_transition_in_kit(
            StreamlinesProfileId.VOLUME_COVERAGE
        )
        runtime.release_prepare.set()
        return await stale, newest

    stale, newest = asyncio.run(run())

    assert stale.success is False
    assert stale.rolled_back is True
    assert newest.success is True
    assert newest.committed_profile is StreamlinesProfileId.VOLUME_COVERAGE
    assert runtime.scheduler_tasks == 1


def test_profile_transition_rollback_restores_the_previous_cached_profile() -> None:
    runtime = _RollbackProfileTransitionRuntime()

    result = asyncio.run(
        runtime.request_streamlines_profile_transition_in_kit(
            StreamlinesProfileId.GLOBAL_FLOW_PATH
        )
    )

    assert result.success is False
    assert result.rolled_back is True
    assert result.committed_profile is StreamlinesProfileId.VOLUME_COVERAGE
    assert runtime.scheduler_tasks == 1


def test_mdl_reads_raw_speed_without_python_display_color_rewrite() -> None:
    mdl = (
        Path(__file__).resolve().parents[2]
        / "src/digital_twin_runtime_suite/ext/msp.dtrs/data/materials"
        / "DTRS_Streamlines_Velocity.mdl"
    ).read_text(encoding="utf-8")
    assert 'scene::data_lookup_float("dtrs:speed"' in mdl
    assert "displayColor" not in mdl
    assert "cutout_opacity" in mdl


def test_material_runtime_reuses_one_material_and_binding(monkeypatch) -> None:
    stage = _install_fake_usd_material_runtime(monkeypatch)
    runtime = _PresentationRuntime()
    _install_snapshot_ownership(runtime, stage)

    first = runtime.apply_streamlines_presentation_in_kit(_presentation())
    second = runtime.apply_streamlines_presentation_in_kit(_presentation(opacity=0.55))

    assert first.material_create_count == 1
    assert second.material_create_count == 1
    assert second.apply_count == 2
    assert second.material_bound is True
    assert all(geometry.bound is stage.material for geometry in stage.geometries)
    assert second.snapshot_count == 3


def test_material_runtime_rejects_missing_raw_speed(monkeypatch) -> None:
    stage = _install_fake_usd_material_runtime(monkeypatch)
    runtime = _PresentationRuntime()
    _install_snapshot_ownership(runtime, stage)
    stage.geometries[0].attributes.clear()

    with pytest.raises(RuntimeError, match="primvars:dtrs:speed"):
        runtime.apply_streamlines_presentation_in_kit(_presentation())


def test_accepted_fixed_scale_drives_shared_material_contract() -> None:
    runtime = _PresentationRuntime()
    runtime._streamlines_accepted_speed_scale = PhysicalSpeedScale(0.0, 7.5)

    assert runtime.streamlines_presentation_contract().speed_scale.maximum == 7.5


def test_material_settings_update_only_the_current_snapshot_material(
    monkeypatch,
) -> None:
    stage = _install_fake_usd_material_runtime(monkeypatch)
    runtime = _FastPresentationRuntime()
    _install_snapshot_ownership(runtime, stage)

    receipt = asyncio.run(
        runtime.apply_streamlines_material_settings_in_kit(_presentation())
    )

    assert receipt.material.snapshot_count == 3
    assert all(geometry.bound is stage.material for geometry in stage.geometries)


def test_applying_material_settings_persists_only_the_tuning_values() -> None:
    runtime = _PresentationRuntime()
    candidate = replace(
        _presentation(),
        opacity=0.61,
        emission_intensity=2.4,
        lighting_influence=0.35,
    )
    local_path = runtime.save_streamlines_material_settings(candidate)

    assert local_path == Path("runtime.local.toml")
    assert runtime.saved_presentation == StreamlinesPresentationConfig(
        speed_min=0.0,
        speed_max=4.0,
        speed_units="source velocity units",
        opacity=0.61,
        emission_intensity=2.4,
        lighting_influence=0.35,
        palette=tuple((stop.position, stop.color) for stop in _presentation().palette),
    )


def test_superseded_material_application_cannot_publish_late() -> None:
    runtime = _PresentationRuntime()
    runtime._streamlines_material_preview_generation = 4
    runtime.cancel_streamlines_material_preview_measurement()

    with pytest.raises(asyncio.CancelledError):
        runtime._require_current_streamlines_material_preview(4)


class _PresentationRuntime(StreamlinesPresentationRuntimeMixin):
    def __init__(self) -> None:
        self.config = SimpleNamespace(
            streamlines_presentation=StreamlinesPresentationConfig(
                speed_min=0.0,
                speed_max=4.0,
                speed_units="source velocity units",
                palette=tuple(
                    (stop.position, stop.color) for stop in _presentation().palette
                ),
                opacity=0.85,
                emission_intensity=1.5,
                lighting_influence=0.2,
            )
        )
        self.reset_streamlines_presentation_runtime_state()

    def save_streamlines_presentation_override(self, presentation) -> Path:
        self.saved_presentation = presentation
        return Path("runtime.local.toml")


class _FastPresentationRuntime(_PresentationRuntime):
    @staticmethod
    async def _await_streamlines_material_viewport_update():
        await asyncio.sleep(0)


class _ProfileTransitionRuntime(StreamlinesProfileTransitionMixin):
    def __init__(self, *, classification: str, advancing: bool) -> None:
        self._streamlines_profile_preference = StreamlinesProfileState()
        self._streamlines_profile_preference.mark_loaded(
            StreamlinesProfileId.VOLUME_COVERAGE
        )
        binding = SimpleNamespace(
            workload_mode="Nominal",
            dataset_identity="server/load_normal",
        )
        sample = SimpleNamespace(sample_index=3, source_vti=Path("nominal_1031.vti"))
        self._airflow_state = SimpleNamespace(
            committed=SimpleNamespace(binding=binding, dataset=object()),
            resolve_phase=lambda _dataset: SimpleNamespace(
                phase_seconds=1.2,
                normalized_phase_seconds=1.2,
                sample=sample,
            ),
        )
        self.classification = classification
        self.advancing = advancing
        self.scheduler_tasks = 1
        self.events = []
        self.build_calls = 0
        self.recompute_calls = 0
        self.vti_imports = 0

    def visualization_snapshot(self):
        return SimpleNamespace(committed=VisualizationMode.STREAMLINES)

    async def ensure_streamlines_cache_validation_in_background(
        self, *_args, **_kwargs
    ):
        return SimpleNamespace(
            inspection=SimpleNamespace(classification=self.classification)
        )

    async def prepare_streamlines_cached_target_in_kit(self, *_args, **_kwargs):
        self.events.append("prepare")
        return SimpleNamespace(
            sample=SimpleNamespace(sample_index=3),
            normalized_phase_seconds=1.2,
        )

    async def start_streamlines_cached_playback_in_kit(self):
        self.events.append("scheduler")
        self.scheduler_tasks = 1

    async def await_streamlines_cached_playback_advancement_in_kit(
        self, *_args, **_kwargs
    ):
        self.events.append("advance")
        return SimpleNamespace(
            sample_advanced=self.advancing,
            scheduler_tasks=self.scheduler_tasks,
        )

    def _active_streamlines_playback_task_count(self):
        return self.scheduler_tasks

    def set_streamlines_cached_presentation_visible_in_kit(self, visible):
        self.events.append("visible")
        return visible

    def apply_streamlines_presentation_in_kit(self):
        self.events.append("material")


class _SupersedingProfileTransitionRuntime(_ProfileTransitionRuntime):
    def __init__(self) -> None:
        super().__init__(classification="VALID", advancing=True)
        self.prepare_started = asyncio.Event()
        self.release_prepare = asyncio.Event()
        self._prepare_calls = 0

    async def prepare_streamlines_cached_target_in_kit(self, *_args, **_kwargs):
        self.events.append("prepare")
        self._prepare_calls += 1
        if self._prepare_calls == 1:
            self.prepare_started.set()
            await self.release_prepare.wait()
        return SimpleNamespace(
            sample=SimpleNamespace(sample_index=3),
            normalized_phase_seconds=1.2,
        )


class _RollbackProfileTransitionRuntime(_ProfileTransitionRuntime):
    def __init__(self) -> None:
        super().__init__(classification="VALID", advancing=True)
        self._advancements = iter((False, True))

    async def await_streamlines_cached_playback_advancement_in_kit(
        self, *_args, **_kwargs
    ):
        self.events.append("advance")
        return SimpleNamespace(
            sample_advanced=next(self._advancements),
            scheduler_tasks=self.scheduler_tasks,
        )


def _install_fake_usd_material_runtime(monkeypatch):
    class Attr:
        def __init__(self):
            self.value = None

        def IsValid(self):
            return True

        def Set(self, value):
            self.value = value
            return self

    class Prim:
        def __init__(self, path):
            self.path = path
            self.attributes = {"primvars:dtrs:speed": Attr()}
            self.bound = None

        def IsValid(self):
            return True

        def GetPath(self):
            return self.path

        def GetAttribute(self, name):
            return self.attributes.get(name)

    class Output:
        def ConnectToSource(self, *_args):
            return True

    class Shader:
        def __init__(self, prim):
            self.prim = prim
            self.inputs = {}

        def CreateImplementationSourceAttr(self):
            return Attr()

        def SetSourceAsset(self, *_args):
            return None

        def SetSourceAssetSubIdentifier(self, *_args):
            return None

        def CreateOutput(self, *_args):
            return SimpleNamespace(SetRenderType=lambda *_: None)

        def ConnectableAPI(self):
            return self

        def CreateInput(self, name, _value_type):
            attr = self.inputs.setdefault(name, Attr())
            return attr

    class Material:
        def __init__(self, prim):
            self.prim = prim

        def __bool__(self):
            return True

        def GetPrim(self):
            return self.prim

        def GetPath(self):
            return self.prim.path

        def CreateSurfaceOutput(self, *_args):
            return Output()

    class Stage:
        def __init__(self):
            self.geometries = tuple(
                Prim(f"/DTRS_StreamlinesCachePlayback/Snapshots/State_{index:06d}")
                for index in range(3)
            )
            self.geometry = self.geometries[0]
            self.material = None
            self.shader = None
            self.target = object()
            self.session = object()

        def GetPrimAtPath(self, path):
            for geometry in self.geometries:
                if geometry.path == path:
                    return geometry
            return Prim(path)

        def GetEditTarget(self):
            return self.target

        def SetEditTarget(self, target):
            self.target = target

        def GetSessionLayer(self):
            return self.session

    stage = Stage()
    usdshade = SimpleNamespace()

    class MaterialAPI:
        @staticmethod
        def Get(_stage, _path):
            return stage.material

        @staticmethod
        def Define(_stage, path):
            stage.material = Material(Prim(path))
            return stage.material

    class ShaderAPI:
        @staticmethod
        def Get(_stage, _path):
            return stage.shader

        @staticmethod
        def Define(_stage, path):
            stage.shader = Shader(Prim(path))
            return stage.shader

    class BindingAPI:
        def __init__(self, prim):
            self.prim = prim

        @staticmethod
        def Apply(prim):
            return BindingAPI(prim)

        def Bind(self, material):
            self.prim.bound = material

        def ComputeBoundMaterial(self):
            return self.prim.bound, None

    usdshade.Material = MaterialAPI
    usdshade.Shader = ShaderAPI
    usdshade.MaterialBindingAPI = BindingAPI
    usdshade.Tokens = SimpleNamespace(sourceAsset="sourceAsset")
    sdf = SimpleNamespace(
        AssetPath=lambda value: value,
        ValueTypeNames=SimpleNamespace(Float="float", Color3f="color3f", Token="token"),
    )
    gf = SimpleNamespace(Vec3f=lambda *values: tuple(values))
    pxr = ModuleType("pxr")
    pxr.Gf = gf
    pxr.Sdf = sdf
    pxr.UsdShade = usdshade
    omni = ModuleType("omni")
    omni_usd = ModuleType("omni.usd")
    omni_usd.get_context = lambda: SimpleNamespace(get_stage=lambda: stage)
    omni.usd = omni_usd
    monkeypatch.setitem(sys.modules, "omni", omni)
    monkeypatch.setitem(sys.modules, "omni.usd", omni_usd)
    monkeypatch.setitem(sys.modules, "pxr", pxr)
    return stage


def _install_snapshot_ownership(runtime, stage) -> None:
    runtime._streamlines_snapshot_set_ownership = SimpleNamespace(
        root_path="/DTRS_StreamlinesCachePlayback/Snapshots",
        states=tuple(
            SimpleNamespace(prim_path=geometry.path) for geometry in stage.geometries
        ),
    )
