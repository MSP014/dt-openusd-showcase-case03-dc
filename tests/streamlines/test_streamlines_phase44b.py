from __future__ import annotations

import asyncio
import sys
from dataclasses import replace
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from digital_twin_runtime_suite.app.config import RuntimeConfig
from digital_twin_runtime_suite.app.flow.performance import ViewportPerformanceSample
from digital_twin_runtime_suite.app.flow.static_source import (
    StaticVelocitySourceDescriptor,
)
from digital_twin_runtime_suite.app.streamlines import presentation_runtime
from digital_twin_runtime_suite.app.streamlines.cache import (
    CACHE_SCHEMA_VERSION,
    StreamlinesCacheOwnership,
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
    SpeedDistributionAccumulator,
    fixed_scale_coverage,
    proposed_speed_max,
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
        Path(__file__).resolve().parents[2] / "configs/digital_twin_runtime_suite.toml"
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


def test_profile_state_rejects_stale_commit_and_keeps_explicit_preference() -> None:
    state = StreamlinesProfileState()
    first = state.begin(StreamlinesProfileId.GLOBAL_FLOW_PATH)
    second = state.begin(StreamlinesProfileId.VOLUME_COVERAGE)
    assert first is not None and second is not None
    assert not state.commit(first)
    assert state.commit(second)
    state.set_preference(StreamlinesProfileId.GLOBAL_FLOW_PATH)
    assert state.snapshot.preferred_profile is StreamlinesProfileId.GLOBAL_FLOW_PATH


def test_cached_profile_switch_commits_only_after_target_advancement() -> None:
    runtime = _ProfileTransitionRuntime(classification="VALID", advancing=True)

    result = asyncio.run(
        runtime.request_streamlines_profile_transition_in_kit(
            StreamlinesProfileId.GLOBAL_FLOW_PATH
        )
    )

    assert result.success is True
    assert result.committed_profile is StreamlinesProfileId.GLOBAL_FLOW_PATH
    assert runtime.events == ["prepare", "scheduler", "advance", "visible", "material"]
    assert runtime.scheduler_tasks == 1
    assert runtime.build_calls == runtime.recompute_calls == runtime.vti_imports == 0


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

    first = runtime.apply_streamlines_presentation_in_kit(_presentation())
    second = runtime.apply_streamlines_presentation_in_kit(_presentation(opacity=0.55))

    assert first.material_create_count == 1
    assert second.material_create_count == 1
    assert second.apply_count == 2
    assert second.material_bound is True
    assert stage.geometry.bound is stage.material
    assert "displayColor" not in stage.geometry.attributes


def test_material_runtime_rejects_missing_raw_speed(monkeypatch) -> None:
    stage = _install_fake_usd_material_runtime(monkeypatch)
    stage.geometry.attributes.clear()
    runtime = _PresentationRuntime()

    with pytest.raises(RuntimeError, match="primvars:dtrs:speed"):
        runtime.apply_streamlines_presentation_in_kit(_presentation())


def test_accepted_fixed_scale_drives_shared_material_contract() -> None:
    runtime = _PresentationRuntime()
    runtime._streamlines_accepted_speed_scale = PhysicalSpeedScale(0.0, 7.5)

    assert runtime.streamlines_presentation_contract().speed_scale.maximum == 7.5


def test_material_preview_completes_only_after_several_stable_samples(
    monkeypatch,
) -> None:
    _install_fake_usd_material_runtime(monkeypatch)
    runtime = _FastPresentationRuntime()
    samples = iter(
        ViewportPerformanceSample(index, 80.0 - index, 12.5 + index, 3.0, 6.0)
        for index in range(8)
    )
    monkeypatch.setattr(
        presentation_runtime,
        "capture_viewport_performance_sample",
        lambda: next(samples),
    )

    receipt = asyncio.run(
        runtime.apply_streamlines_material_preview_in_kit(_presentation())
    )

    assert receipt.performance_settle_seconds == 10.0
    assert receipt.performance_sample_window_seconds == 2.0
    assert receipt.performance_samples == 8
    assert receipt.viewport_fps_minimum == 73.0
    assert runtime.accept_streamlines_material_candidate() == _presentation()


def test_superseded_material_measurement_cannot_publish_candidate() -> None:
    runtime = _PresentationRuntime()
    runtime._streamlines_material_preview_generation = 4
    runtime._streamlines_material_candidate = _presentation()

    runtime.cancel_streamlines_material_preview_measurement()

    with pytest.raises(asyncio.CancelledError):
        runtime._require_current_streamlines_material_preview(4)


class _PresentationRuntime(StreamlinesPresentationRuntimeMixin):
    def __init__(self) -> None:
        self.config = SimpleNamespace(
            streamlines_presentation=SimpleNamespace(
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


class _FastPresentationRuntime(_PresentationRuntime):
    @staticmethod
    async def _wait_streamlines_material_measurement_interval(_seconds):
        await asyncio.sleep(0)

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
            self.geometry = Prim("/DTRS_StreamlinesCachePlayback/Geometry")
            self.material = None
            self.shader = None
            self.target = object()
            self.session = object()

        def GetPrimAtPath(self, path):
            if path.endswith("/Geometry"):
                return self.geometry
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
