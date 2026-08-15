from __future__ import annotations

import asyncio
import time
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest

from digital_twin_runtime_suite.app.commands import (
    FlowPerformanceSample,
    RuntimeController,
)
from digital_twin_runtime_suite.app.config import RuntimeConfig, SmokeTuningConfig
from digital_twin_runtime_suite.app.simulation_cache import (
    run_simulation_cache_preflight,
)


def _write_test_cache_wrapper(tmp_path: Path) -> Path:
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    for frame in (1001, 1002):
        (frames_dir / f"test.{frame}.vdb").write_bytes(b"placeholder")

    wrapper_path = tmp_path / "test.usda"
    wrapper_path.write_text(
        """#usda 1.0
(
    defaultPrim = "sim"
    endTimeCode = 1002
    framesPerSecond = 25
    metersPerUnit = 1
    startTimeCode = 1001
    timeCodesPerSecond = 25
    upAxis = "Y"
)

def Xform "sim"
{
    def Volume "test"
    {
        float3[] extent = [(-1, -1, -1), (1, 1, 1)]
        rel field:density = </sim/test/density>

        def OpenVDBAsset "density"
        {
            token fieldDataType = "float"
            token fieldName = "density"
            asset filePath.timeSamples = {
                1001: @frames/test.1001.vdb@,
                1002: @frames/test.1002.vdb@,
            }
        }
    }
}
""",
        encoding="utf-8",
    )
    return wrapper_path


def _test_cache_config() -> tuple[RuntimeConfig, object]:
    config = RuntimeConfig.load(
        Path("configs/digital_twin_runtime_suite.toml"),
        apply_local_overrides=False,
    )
    return config, replace(
        config.simulation_cache,
        root_prim_path="/sim",
        volume_prim_path="/sim/test",
    )


def test_flow_performance_statistics_use_viewport_samples() -> None:
    samples = [
        FlowPerformanceSample(0.0, 50.0, 20.0, 4.5, 6.0, "1014.vti"),
        FlowPerformanceSample(0.5, 40.0, 25.0, 4.6, 6.1, "1015.vti"),
        FlowPerformanceSample(1.0, 60.0, 16.0, 4.7, 6.2, "1016.vti"),
    ]

    statistics = RuntimeController._flow_performance_statistics(samples)

    assert statistics["fps_average"] == 50.0
    assert statistics["fps_minimum"] == 40.0
    assert statistics["fps_maximum"] == 60.0
    assert abs(float(statistics["frame_time_average"]) - 20.333333333) < 1e-8


def test_airflow_cache_preflight_accepts_a_hydrated_wrapper(tmp_path):
    _, cache_config = _test_cache_config()
    wrapper_path = _write_test_cache_wrapper(tmp_path)

    result = run_simulation_cache_preflight(
        wrapper_path,
        cache_config,
    )

    assert result.success is True
    assert result.contract is not None
    assert result.contract.start_time_code == 1001.0
    assert result.contract.end_time_code == 1002.0
    assert result.contract.time_codes_per_second == 25.0
    assert result.contract.field_data_type == "float"
    assert len(result.contract.file_samples) == 2


def test_airflow_cache_authors_only_session_layer_native_volume_reference(tmp_path):
    _, cache_config = _test_cache_config()
    wrapper_path = _write_test_cache_wrapper(tmp_path)
    preflight = run_simulation_cache_preflight(
        wrapper_path,
        cache_config,
    )
    assert preflight.contract is not None

    from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade

    stage = Usd.Stage.CreateInMemory()
    stage.SetEditTarget(stage.GetSessionLayer())
    RuntimeController._author_airflow_cache_session_layer(
        stage,
        cache_config,
        preflight.contract,
        Gf,
        Sdf,
        UsdGeom,
        UsdShade,
    )

    volume = stage.GetPrimAtPath("/DTRS_Runtime/Airflow/test")
    field = stage.GetPrimAtPath("/DTRS_Runtime/Airflow/test/density")

    assert volume.GetTypeName() == "Volume"
    assert field.GetTypeName() == "OpenVDBAsset"
    assert field.GetAttribute("fieldDataType").Get() == "float"
    assert volume.GetAttribute("nvindex:composite").Get() is True
    assert volume.GetAttribute("omni:rtx:skip").Get() is True
    assert (
        volume.GetCustomDataByKey("nvindex.renderSettings")["filterMode"] == "nearest"
    )
    assert stage.GetPrimAtPath("/DTRS_Runtime/Looks/AirflowIndex").IsValid()
    session_text = stage.GetSessionLayer().ExportToString()
    assert "references = @" in session_text
    assert "outputs:nvindex:volume.connect" in session_text
    assert "OmniVolumeDensity.mdl" not in session_text


def test_kit_cae_spatial_sanity_wireframes_are_hidden_by_default_and_toggle():
    from pxr import Gf, Usd, UsdGeom

    stage = Usd.Stage.CreateInMemory()
    server = UsdGeom.Cube.Define(stage, "/blackwell_rig")
    server.CreateSizeAttr(2.0)

    RuntimeController._author_kit_cae_spatial_sanity_wireframes(
        stage,
        ((-0.5, -0.25, -1.0), (0.5, 0.25, 0.0)),
        Gf,
        Usd,
        UsdGeom,
    )

    dataset_wireframe = stage.GetPrimAtPath("/DTRS_KitCAE/SpatialSanity/DatasetBounds")
    server_wireframe = stage.GetPrimAtPath("/DTRS_KitCAE/SpatialSanity/ServerBounds")

    assert dataset_wireframe.GetTypeName() == "BasisCurves"
    assert server_wireframe.GetTypeName() == "BasisCurves"
    overlays_root = stage.GetPrimAtPath("/DTRS_KitCAE/SpatialSanity")
    flow_bounds = UsdGeom.Cube.Define(stage, "/DTRS_KitCAE/BoundingBox")
    assert (
        UsdGeom.Imageable(overlays_root).ComputeVisibility() == UsdGeom.Tokens.invisible
    )
    assert RuntimeController._set_kit_cae_spatial_sanity_wireframes_visibility(
        stage,
        False,
        UsdGeom,
    )
    assert (
        UsdGeom.Imageable(flow_bounds).ComputeVisibility() == UsdGeom.Tokens.invisible
    )
    assert RuntimeController._set_kit_cae_spatial_sanity_wireframes_visibility(
        stage,
        True,
        UsdGeom,
    )
    assert (
        UsdGeom.Imageable(overlays_root).ComputeVisibility() == UsdGeom.Tokens.inherited
    )
    assert (
        UsdGeom.Imageable(flow_bounds).ComputeVisibility() == UsdGeom.Tokens.inherited
    )
    assert RuntimeController._set_kit_cae_spatial_sanity_wireframes_visibility(
        stage,
        False,
        UsdGeom,
    )
    assert (
        UsdGeom.Imageable(overlays_root).ComputeVisibility() == UsdGeom.Tokens.invisible
    )
    assert len(dataset_wireframe.GetAttribute("points").Get()) == 24
    assert len(server_wireframe.GetAttribute("points").Get()) == 24
    assert abs(dataset_wireframe.GetAttribute("widths").Get()[0] - 0.0015) < 1e-6
    assert abs(server_wireframe.GetAttribute("widths").Get()[0] - 0.003) < 1e-6


def test_kit_cae_flow_deactivation_precedes_runtime_prim_removal():
    from pxr import Sdf, Usd, UsdGeom

    stage = Usd.Stage.CreateInMemory()
    emitter = UsdGeom.Xform.Define(stage, "/DTRS_KitCAE/DataSetEmitter").GetPrim()
    enabled = emitter.CreateAttribute("enabled", Sdf.ValueTypeNames.Bool)
    enabled.Set(True)

    simulate = UsdGeom.Xform.Define(
        stage,
        "/DTRS_KitCAE/FlowSimulation/flowSimulate",
    ).GetPrim()
    disable_emitters = simulate.CreateAttribute(
        "forceDisableEmitters",
        Sdf.ValueTypeNames.Bool,
    )
    disable_core = simulate.CreateAttribute(
        "forceDisableCoreSimulation",
        Sdf.ValueTypeNames.Bool,
    )
    disable_emitters.Set(False)
    disable_core.Set(False)
    offscreen = UsdGeom.Xform.Define(
        stage,
        "/DTRS_KitCAE/FlowSimulation/flowOffscreen",
    ).GetPrim()
    render = UsdGeom.Xform.Define(
        stage,
        "/DTRS_KitCAE/FlowSimulation/flowRender",
    ).GetPrim()

    class FakeOperatorAPI:
        def __init__(self, prim):
            self._prim = prim

        def CreateEnabledAttr(self):
            return self._prim.GetAttribute("enabled")

    class FakeCaeViz:
        OperatorAPI = FakeOperatorAPI

    assert RuntimeController._deactivate_kit_cae_flow_for_detach(stage, FakeCaeViz)

    assert enabled.Get() is False
    assert disable_emitters.Get() is True
    assert disable_core.Get() is True
    assert offscreen.IsActive() is False
    assert render.IsActive() is False


def test_kit_cae_front_intake_tracer_positions_follow_p120_bounds():
    from pxr import Gf, Usd, UsdGeom

    config = RuntimeConfig.load(
        Path("configs/digital_twin_runtime_suite.toml"),
        apply_local_overrides=False,
    )
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.Xform.Define(stage, "/blackwell_rig")

    def define_box(path, translate, scale):
        cube = UsdGeom.Cube.Define(stage, path)
        transform = UsdGeom.XformCommonAPI(cube)
        transform.SetTranslate(Gf.Vec3d(*translate))
        transform.SetScale(Gf.Vec3f(*scale))

    define_box("/blackwell_rig/chassis", (0.0, 0.08, -0.25), (0.24, 0.08, 0.27))
    for index, x_position in enumerate((-0.1, 0.025, 0.15), start=1):
        binding = next(
            item
            for item in config.fan_motion_bindings
            if item.binding_id == f"front_p120_0{index}"
        )
        define_box(binding.mesh_path, (x_position, 0.08, -0.03), (0.06, 0.06, 0.01))

    positions = RuntimeController._kit_cae_front_intake_tracer_positions(
        stage,
        config.simulation_cache.intake_tracers,
        config.fan_motion_bindings,
        ((-0.25, -0.01, -0.55), (0.25, 0.18, 0.05)),
        Gf,
        Usd,
        UsdGeom,
    )

    assert len(positions) == 7
    assert tuple(round(float(position[0]), 6) for position in positions) == (
        -0.1625,
        -0.1,
        -0.0375,
        0.025,
        0.0875,
        0.15,
        0.2125,
    )
    assert all(round(float(position[1]), 6) == 0.08 for position in positions)
    assert all(round(float(position[2]), 6) == 0.028 for position in positions)


def test_kit_cae_smoke_only_tracer_setup_applies_cloud_tuning_without_reset():
    from pxr import Sdf, Usd, UsdGeom

    config = RuntimeConfig.load(
        Path("configs/digital_twin_runtime_suite.toml"),
        apply_local_overrides=False,
    )
    stage = Usd.Stage.CreateInMemory()

    def define_prim(path):
        return UsdGeom.Xform.Define(stage, path).GetPrim()

    def define_attribute(prim, name, value_type, value):
        return prim.CreateAttribute(name, value_type).Set(value)

    environment = define_prim("/DTRS_KitCAE/FlowSimulation")
    simulate = define_prim(f"{environment.GetPath()}/flowSimulate")
    define_attribute(simulate, "forceClear", Sdf.ValueTypeNames.Bool, False)
    define_attribute(simulate, "timeScale", Sdf.ValueTypeNames.Float, 1.0)
    advection = define_prim(f"{simulate.GetPath()}/advection")
    smoke = define_prim(f"{advection.GetPath()}/smoke")
    vorticity = define_prim(f"{simulate.GetPath()}/vorticity")
    offscreen = define_prim(f"{environment.GetPath()}/flowOffscreen")
    debug_volume = define_prim(f"{offscreen.GetPath()}/debugVolume")
    render = define_prim(f"{environment.GetPath()}/flowRender")
    ray_march = define_prim(f"{render.GetPath()}/rayMarch")
    ray_march_cloud = define_prim(f"{ray_march.GetPath()}/cloud")

    define_attribute(
        debug_volume, "enableSpeedAsTemperature", Sdf.ValueTypeNames.Bool, True
    )
    define_attribute(
        debug_volume, "enableVelocityAsDensity", Sdf.ValueTypeNames.Bool, True
    )
    define_attribute(ray_march, "enableRawMode", Sdf.ValueTypeNames.Bool, True)
    define_attribute(ray_march_cloud, "enableCloudMode", Sdf.ValueTypeNames.Bool, False)
    define_attribute(
        ray_march_cloud, "densityMultiplier", Sdf.ValueTypeNames.Float, 0.0
    )
    define_attribute(
        ray_march_cloud, "volumeColorMultiplier", Sdf.ValueTypeNames.Float, 0.0
    )
    define_attribute(
        ray_march_cloud, "ambientMultiplier", Sdf.ValueTypeNames.Float, 0.0
    )
    define_attribute(
        ray_march_cloud,
        "attenuationMultiplier",
        Sdf.ValueTypeNames.Float3,
        (0.0, 0.0, 0.0),
    )
    define_attribute(
        ray_march_cloud,
        "volumeBaseColor",
        Sdf.ValueTypeNames.Float3,
        (0.0, 0.0, 0.0),
    )
    define_attribute(advection, "combustionEnabled", Sdf.ValueTypeNames.Bool, True)
    define_attribute(advection, "buoyancyPerSmoke", Sdf.ValueTypeNames.Float, 1.0)
    define_attribute(advection, "buoyancyPerTemp", Sdf.ValueTypeNames.Float, 1.0)
    define_attribute(smoke, "damping", Sdf.ValueTypeNames.Float, 0.3)
    define_attribute(smoke, "fade", Sdf.ValueTypeNames.Float, 0.65)
    define_attribute(smoke, "secondOrderBlendFactor", Sdf.ValueTypeNames.Float, 0.0)
    define_attribute(vorticity, "enabled", Sdf.ValueTypeNames.Bool, True)
    for attribute_name in (
        "forceScale",
        "smokeMask",
        "velocityMask",
        "velocityLinearMask",
        "constantMask",
    ):
        define_attribute(vorticity, attribute_name, Sdf.ValueTypeNames.Float, 0.0)
    define_attribute(ray_march, "stepSizeScale", Sdf.ValueTypeNames.Float, 0.0)
    dataset_emitter = define_prim("/DTRS_KitCAE/DataSetEmitter")
    define_attribute(
        dataset_emitter,
        "velocityScale",
        Sdf.ValueTypeNames.Float,
        0.73,
    )

    RuntimeController._configure_kit_cae_smoke_only_tracer_flow(
        stage,
        str(environment.GetPath()),
        config.simulation_cache.intake_tracers,
        config.simulation_cache.smoke_tuning,
    )

    assert debug_volume.GetAttribute("enableSpeedAsTemperature").Get() is False
    assert debug_volume.GetAttribute("enableVelocityAsDensity").Get() is False
    assert ray_march.GetAttribute("enableRawMode").Get() is False
    assert ray_march_cloud.GetAttribute("enableCloudMode").Get() is True
    assert ray_march_cloud.GetAttribute("densityMultiplier").Get() == 0.5
    assert ray_march_cloud.GetAttribute("volumeColorMultiplier").Get() == 1.0
    assert ray_march_cloud.GetAttribute("ambientMultiplier").Get() == 1.0
    assert tuple(
        ray_march_cloud.GetAttribute("attenuationMultiplier").Get()
    ) == pytest.approx((1.0, 1.0, 1.0))
    assert tuple(
        ray_march_cloud.GetAttribute("volumeBaseColor").Get()
    ) == pytest.approx((0.58, 0.64, 0.69))
    assert advection.GetAttribute("combustionEnabled").Get() is False
    assert advection.GetAttribute("buoyancyPerSmoke").Get() == 0.0
    assert advection.GetAttribute("buoyancyPerTemp").Get() == 0.0
    assert smoke.GetAttribute("damping").Get() == 0.0
    assert smoke.GetAttribute("fade").Get() == pytest.approx(0.0)
    assert smoke.GetAttribute("secondOrderBlendFactor").Get() == pytest.approx(0.9)
    assert vorticity.GetAttribute("enabled").Get() is True
    assert vorticity.GetAttribute("forceScale").Get() == pytest.approx(0.6)
    assert ray_march.GetAttribute("stepSizeScale").Get() == pytest.approx(0.75)
    assert vorticity.GetAttribute("smokeMask").Get() == 1.0
    assert vorticity.GetAttribute("velocityMask").Get() == 0.0
    assert vorticity.GetAttribute("velocityLinearMask").Get() == 0.0
    assert vorticity.GetAttribute("constantMask").Get() == 0.0
    custom_tuning = SmokeTuningConfig(
        density=1.5,
        brightness=1.25,
        ambient=0.75,
        shadow_density=1.5,
        damping=0.005,
        fade=0.01,
        sharpness=0.5,
        vorticity=0.0,
        velocity_scale_multiplier=4.0,
        time_scale=2.0,
        raymarch_quality=0.75,
        base_color=(0.2, 0.3, 0.4),
    )

    RuntimeController._author_kit_cae_smoke_tuning(
        stage,
        str(environment.GetPath()),
        custom_tuning,
        dataset_emitter_path=str(dataset_emitter.GetPath()),
        base_velocity_scale=0.73,
    )

    assert ray_march_cloud.GetAttribute("densityMultiplier").Get() == 1.5
    assert ray_march_cloud.GetAttribute("volumeColorMultiplier").Get() == 1.25
    assert ray_march_cloud.GetAttribute("ambientMultiplier").Get() == 0.75
    assert tuple(
        ray_march_cloud.GetAttribute("attenuationMultiplier").Get()
    ) == pytest.approx((1.5, 1.5, 1.5))
    assert tuple(
        ray_march_cloud.GetAttribute("volumeBaseColor").Get()
    ) == pytest.approx((0.2, 0.3, 0.4))
    assert smoke.GetAttribute("damping").Get() == pytest.approx(0.005)
    assert smoke.GetAttribute("fade").Get() == pytest.approx(0.01)
    assert smoke.GetAttribute("secondOrderBlendFactor").Get() == pytest.approx(0.5)
    assert vorticity.GetAttribute("enabled").Get() is False
    assert vorticity.GetAttribute("forceScale").Get() == 0.0
    assert ray_march.GetAttribute("stepSizeScale").Get() == pytest.approx(0.75)
    assert dataset_emitter.GetAttribute("velocityScale").Get() == pytest.approx(2.92)
    assert (
        dataset_emitter.GetAttribute("velocityScale").GetCustomDataByKey(
            "omni:kit:locked"
        )
        is True
    )
    assert simulate.GetAttribute("timeScale").Get() == pytest.approx(2.0)
    assert simulate.GetAttribute("forceClear").Get() is False


def test_kit_cae_temporal_velocity_samples_author_manifest_derived_cadence(tmp_path):
    from pxr import Sdf, Usd, UsdGeom

    stage = Usd.Stage.CreateInMemory()
    field = UsdGeom.Xform.Define(stage, "/DTRS_HoudiniVelocity/PointData/vel")
    file_names_attr = field.GetPrim().CreateAttribute(
        "fileNames",
        Sdf.ValueTypeNames.AssetArray,
    )

    class FakeFieldArray:
        def __init__(self, prim):
            self._prim = prim

        def GetFileNamesAttr(self):
            return self._prim.GetAttribute("fileNames")

    class FakeCaeVtk:
        FieldArray = FakeFieldArray

    paths = tuple(
        tmp_path / f"server_airflow_velocity_{frame}.vti"
        for frame in range(1001, 1801, 10)
    )
    time_codes = RuntimeController._author_kit_cae_temporal_velocity_samples(
        field.GetPrim(),
        paths,
        50.0,
        0.2,
        FakeCaeVtk,
        Sdf,
        Usd,
    )

    assert time_codes == tuple(float(time_code) for time_code in range(0, 800, 10))
    assert time_codes[1] - time_codes[0] == pytest.approx(10.0)
    assert (time_codes[1] - time_codes[0]) / 50.0 == pytest.approx(0.2)
    assert (time_codes[-1] + (time_codes[-1] - time_codes[-2])) / 50.0 == pytest.approx(
        16.0
    )
    assert [
        file_names_attr.Get(Usd.TimeCode(time_code))[0].path for time_code in time_codes
    ] == [path.as_posix() for path in paths]


def test_kit_cae_temporal_velocity_samples_yield_between_batches(tmp_path):
    from pxr import Sdf, Usd, UsdGeom

    from digital_twin_runtime_suite.app.flow.temporal import (
        author_kit_cae_temporal_velocity_samples_in_batches,
    )

    stage = Usd.Stage.CreateInMemory()
    field = UsdGeom.Xform.Define(stage, "/DTRS_HoudiniVelocity/PointData/vel")
    file_names_attr = field.GetPrim().CreateAttribute(
        "fileNames",
        Sdf.ValueTypeNames.AssetArray,
    )

    class FakeFieldArray:
        def __init__(self, prim):
            self._prim = prim

        def GetFileNamesAttr(self):
            return self._prim.GetAttribute("fileNames")

    class FakeCaeVtk:
        FieldArray = FakeFieldArray

    paths = tuple(
        tmp_path / f"server_airflow_velocity_{index}.vti" for index in range(5)
    )
    yields = []
    progress = []

    async def next_update():
        yields.append("update")

    time_codes = asyncio.run(
        author_kit_cae_temporal_velocity_samples_in_batches(
            field.GetPrim(),
            paths,
            50.0,
            0.2,
            FakeCaeVtk,
            Sdf,
            Usd,
            next_update,
            2,
            lambda completed, total: progress.append((completed, total)),
        )
    )

    assert time_codes == (0.0, 10.0, 20.0, 30.0, 40.0)
    assert yields == ["update", "update"]
    assert progress == [(2, 5), (4, 5)]
    assert [
        file_names_attr.Get(Usd.TimeCode(time_code))[0].path for time_code in time_codes
    ] == [path.as_posix() for path in paths]


def test_kit_cae_temporal_loop_proof_requires_all_distinct_sources_and_closure(
    tmp_path,
):
    velocity_paths = tuple(
        tmp_path / f"server_airflow_velocity_{frame}.vti"
        for frame in range(1001, 1801, 10)
    )
    records = []
    for index, asset in enumerate((*velocity_paths, velocity_paths[0])):
        records.append(
            {
                "sequence_index": index,
                "source_frame": RuntimeController._kit_cae_vti_source_frame(asset),
                "asset": asset.name,
                "asset_hash": f"{index % len(velocity_paths):012x}",
                "transition": (
                    "INITIAL"
                    if index == 0
                    else "LOOP" if index == len(velocity_paths) else "SWAP"
                ),
                "operator_ready": True,
                "timeline_advancing": True,
                "flow_reset": False,
                "origin_match": True,
                "grid_match": True,
            }
        )

    summary = RuntimeController._kit_cae_temporal_loop_proof_summary(
        records,
        velocity_paths,
    )

    assert summary["passed"] is True
    assert summary["forward_transitions"] == 79
    assert summary["loop_transitions"] == 1
    assert summary["loop_closure"] is True
    assert summary["unique_assets"] == 80
    assert summary["unique_hashes"] == 80

    incomplete_summary = RuntimeController._kit_cae_temporal_loop_proof_summary(
        records[:-1],
        velocity_paths,
    )
    assert incomplete_summary["passed"] is False
    assert incomplete_summary["loop_closure"] is False


def test_kit_cae_vti_origin_compatibility_opinion_uses_session_layer():
    from pxr import Gf, Sdf, Usd, UsdGeom

    stage = Usd.Stage.CreateInMemory()
    dataset = UsdGeom.Xform.Define(stage, "/DTRS_HoudiniVelocity/VTKImageData")
    origin_attr = dataset.GetPrim().CreateAttribute(
        "cae:vtk:origin",
        Sdf.ValueTypeNames.Float3,
    )
    origin_attr.Set(Gf.Vec3f(0.0, 0.0, 0.0))

    class FakeImageDataAPI:
        def __init__(self, prim):
            self._prim = prim

        def GetOriginAttr(self):
            return self._prim.GetAttribute("cae:vtk:origin")

    class FakeCaeVtk:
        ImageDataAPI = FakeImageDataAPI

    stage.SetEditTarget(stage.GetSessionLayer())
    expected_origin = (-0.233962506, -0.003162505, -0.543325543)
    RuntimeController._author_kit_cae_vti_origin_session_opinion(
        dataset.GetPrim(),
        expected_origin,
        FakeCaeVtk,
        Gf,
    )

    assert all(
        abs(actual - expected) < 1e-6
        for actual, expected in zip(origin_attr.Get(), expected_origin)
    )
    assert origin_attr.GetPropertyStack()[0].layer == stage.GetSessionLayer()


def test_legacy_flow_presentation_path_is_removed():
    assert not hasattr(RuntimeController, "_author_kit_cae_flow_presentation")


def _temporal_progress_controller():
    from digital_twin_runtime_suite.app.flow.progress import TemporalProofProgress

    controller = object.__new__(RuntimeController)
    controller._flow_temporal_proof_generation = 7
    controller._flow_temporal_proof_task = None
    controller._flow_temporal_progress = TemporalProofProgress(generation_id=7)
    return controller


def test_temporal_proof_progress_uses_real_sample_percentage():
    from digital_twin_runtime_suite.app.flow.progress import TemporalProofProgress

    progress = TemporalProofProgress(validated_sample_count=37, total_sample_count=80)

    assert progress.percentage == 46


def test_temporal_proof_progress_ignores_stale_generation():
    from digital_twin_runtime_suite.app.flow.progress import TemporalProofState

    controller = _temporal_progress_controller()
    started_at = time.monotonic()

    assert (
        controller._update_temporal_proof_progress(
            generation_id=6,
            state=TemporalProofState.RUNNING,
            total_sample_count=80,
            validated_sample_count=37,
            current_asset_name="server_airflow_velocity_1371.vti",
            started_at=started_at,
        )
        is False
    )
    assert controller.temporal_proof_progress().validated_sample_count == 0

    assert (
        controller._update_temporal_proof_progress(
            generation_id=7,
            state=TemporalProofState.RUNNING,
            total_sample_count=80,
            validated_sample_count=37,
            current_asset_name="server_airflow_velocity_1371.vti",
            started_at=started_at,
        )
        is True
    )
    assert controller.temporal_proof_progress().validated_sample_count == 37


def test_temporal_proof_progress_is_cancelled_on_teardown():
    from digital_twin_runtime_suite.app.flow.progress import TemporalProofState

    controller = _temporal_progress_controller()
    controller._set_temporal_proof_progress(
        state=TemporalProofState.RUNNING,
        generation_id=7,
        total_sample_count=80,
        validated_sample_count=18,
        current_asset_name="server_airflow_velocity_1181.vti",
        started_at=time.monotonic(),
    )

    controller._cancel_kit_cae_temporal_proof()

    progress = controller.temporal_proof_progress()
    assert progress.state is TemporalProofState.CANCELLED
    assert progress.validated_sample_count == 18
    assert progress.generation_id == 8


def test_temporal_vti_validation_wrapper_forwards_worker_progress(
    monkeypatch,
    tmp_path,
):
    from digital_twin_runtime_suite.app.airflow_validation import preflight

    paths = (tmp_path / "server_airflow_velocity_1001.vti",)
    from queue import SimpleQueue

    progress_queue = SimpleQueue()

    received_cancel_requested = []

    def validate(
        velocity_paths,
        field_name,
        progress_callback,
        cancel_requested=None,
    ):
        received_cancel_requested.append(cancel_requested)
        progress_callback(1, 1, velocity_paths[0].name)
        return {"dimensions": (1, 1, 1)}, True

    monkeypatch.setattr(preflight, "validate_kit_cae_temporal_vti_contract", validate)

    metadata, grid_match = RuntimeController._validate_kit_cae_temporal_vti_contract(
        paths,
        "vel",
        lambda completed, total, asset_name: progress_queue.put(
            (completed, total, asset_name)
        ),
    )

    assert metadata["dimensions"] == (1, 1, 1)
    assert grid_match is True
    assert progress_queue.get_nowait() == (1, 1, "server_airflow_velocity_1001.vti")
    assert received_cancel_requested == [None]


def _write_airflow_validation_dataset(tmp_path: Path):
    from digital_twin_runtime_suite.app.airflow_dataset import (
        AirflowDatasetSelector,
        discover_airflow_dataset,
    )

    directory = tmp_path / "airflows" / "server" / "load_normal"
    directory.mkdir(parents=True)
    (directory / "manifest.toml").write_text(
        "\n".join(
            (
                'scope = "server"',
                'state = "load_normal"',
                "source_fps = 50",
                "sample_step_frames = 10",
                "sample_rate_hz = 5",
                "sample_count = 2",
                "grid = [2, 2, 2]",
                "",
            )
        ),
        encoding="utf-8",
    )
    for frame, content in ((1001, b"first"), (1011, b"second")):
        (directory / f"server_airflow_velocity_{frame}.vti").write_bytes(content)
    selector = AirflowDatasetSelector(
        root="airflows",
        scope="server",
        state="load_normal",
    )
    return discover_airflow_dataset(tmp_path, selector)


def test_session_validation_signature_tracks_manifest_and_vti_metadata(tmp_path):
    from digital_twin_runtime_suite.app.airflow_dataset import (
        AirflowDatasetSelector,
        discover_airflow_dataset,
    )
    from digital_twin_runtime_suite.app.airflow_validation.cache import (
        build_dataset_validation_signature,
    )

    dataset = _write_airflow_validation_dataset(tmp_path)
    initial = build_dataset_validation_signature(dataset, "vel")
    unchanged = build_dataset_validation_signature(dataset, "vel")
    assert unchanged == initial

    first_sample = dataset.velocity_vti_sequence_paths[0]
    first_sample.write_bytes(b"first sample changed")
    changed_sample = build_dataset_validation_signature(dataset, "vel")
    assert changed_sample != initial

    dataset.manifest_path.write_text(
        dataset.manifest_path.read_text(encoding="utf-8") + "# changed\n",
        encoding="utf-8",
    )
    changed_manifest = build_dataset_validation_signature(dataset, "vel")
    assert changed_manifest != changed_sample
    assert build_dataset_validation_signature(dataset, "velocity") != changed_manifest

    rediscovered = discover_airflow_dataset(
        tmp_path,
        AirflowDatasetSelector(root="airflows", scope="server", state="load_normal"),
    )
    assert build_dataset_validation_signature(rediscovered, "vel") != initial


def test_session_validation_signature_tracks_sequence_addition_and_removal(tmp_path):
    from dataclasses import replace

    from digital_twin_runtime_suite.app.airflow_validation.cache import (
        build_dataset_validation_signature,
    )

    dataset = _write_airflow_validation_dataset(tmp_path)
    initial = build_dataset_validation_signature(dataset, "vel")
    added_sample = dataset.directory / "server_airflow_velocity_1021.vti"
    added_sample.write_bytes(b"third")
    with_added = replace(
        dataset,
        velocity_vti_sequence_paths=(
            *dataset.velocity_vti_sequence_paths,
            added_sample,
        ),
    )
    added_signature = build_dataset_validation_signature(with_added, "vel")
    without_first = replace(
        with_added,
        velocity_vti_sequence_paths=with_added.velocity_vti_sequence_paths[1:],
    )

    assert added_signature != initial
    assert build_dataset_validation_signature(without_first, "vel") != added_signature


def test_session_validation_signature_changes_only_for_validation_field_config(
    tmp_path,
):
    from digital_twin_runtime_suite.app.airflow_validation.cache import (
        SessionValidationCache,
        build_dataset_validation_signature,
    )

    dataset = _write_airflow_validation_dataset(tmp_path)
    base = build_dataset_validation_signature(dataset, "vel")
    cache = SessionValidationCache()
    cache.store_preflight(base, {"dimensions": (2, 2, 2)}, grid_match=True)

    changed_field = build_dataset_validation_signature(dataset, "velocity")
    assert changed_field != base
    assert cache.lookup(changed_field).result == "INVALIDATED"
    # Smoke/UI tuning never enters the builder; unchanged field selection is a HIT.
    assert build_dataset_validation_signature(dataset, "vel") == base
    assert cache.lookup(base).result == "HIT"


def test_session_validation_cache_reuses_only_successful_receipts(tmp_path):
    from digital_twin_runtime_suite.app.airflow_validation.cache import (
        SessionValidationCache,
        build_dataset_validation_signature,
    )

    dataset = _write_airflow_validation_dataset(tmp_path)
    signature = build_dataset_validation_signature(dataset, "vel")
    cache = SessionValidationCache()

    miss = cache.lookup(signature)
    assert miss.result == "MISS"
    assert miss.preflight is None
    assert miss.temporal_proof is None

    cache.store_preflight(signature, {"dimensions": (2, 2, 2)}, grid_match=True)
    preflight_hit = cache.lookup(signature)
    assert preflight_hit.result == "HIT"
    assert preflight_hit.preflight is not None
    assert preflight_hit.temporal_proof is None

    cache.store_temporal_proof(
        signature, validated_sample_count=2, duration_seconds=1.2
    )
    full_hit = cache.lookup(signature)
    assert full_hit.temporal_proof is not None
    assert full_hit.temporal_proof.validated_sample_count == 2

    dataset.velocity_vti_sequence_paths[1].write_bytes(b"changed second sample")
    invalidated_signature = build_dataset_validation_signature(dataset, "vel")
    invalidated = cache.lookup(invalidated_signature)
    assert invalidated.result == "INVALIDATED"
    assert invalidated.preflight is None
    assert invalidated.temporal_proof is None

    cache.clear()
    assert cache.lookup(invalidated_signature).result == "MISS"


def test_attach_cancellation_request_sets_only_the_active_generation() -> None:
    """The UI may request cancellation while a background VTI preflight is running."""

    controller = RuntimeController("configs/digital_twin_runtime_suite.toml")
    controller._flow_lifecycle_state = "ATTACHING"
    controller._flow_attach_cancel_event = Event()

    assert controller.request_flow_attach_cancellation() is True
    assert controller._flow_attach_cancel_event.is_set() is True

    controller._flow_lifecycle_state = "DETACHED"
    assert controller.request_flow_attach_cancellation() is False


def test_kit_cae_operator_event_path_uses_single_argument_event_get() -> None:
    """Carbonite events accept only the key argument in Event.get()."""

    class SingleArgumentEvent:
        def get(self, key_name: str):
            assert key_name == "prim_path"
            return "/DTRS_KitCAE/DataSetEmitter"

    assert (
        RuntimeController._kit_cae_operator_event_path(SingleArgumentEvent())
        == "/DTRS_KitCAE/DataSetEmitter"
    )


@pytest.mark.parametrize("state", ("ATTACHING", "ATTACHED", "DETACHING"))
def test_reload_config_rejects_active_airflow_without_clearing_receipts(
    tmp_path: Path,
    state: str,
) -> None:
    """Reload must not invalidate a live Flow session or its accepted receipts."""

    from digital_twin_runtime_suite.app.airflow_validation.cache import (
        build_dataset_validation_signature,
    )

    controller = RuntimeController("configs/digital_twin_runtime_suite.toml")
    signature = build_dataset_validation_signature(
        _write_airflow_validation_dataset(tmp_path), "vel"
    )
    controller._flow_validation_cache.store_preflight(
        signature,
        {"dimensions": (2, 2, 2)},
        grid_match=True,
    )
    original_config = controller.config
    controller._flow_lifecycle_state = state

    with pytest.raises(RuntimeError, match="Detach airflow before reloading config"):
        controller.reload_config()

    assert controller._flow_lifecycle_state == state
    assert controller.config is original_config
    assert controller._flow_validation_cache.lookup(signature).preflight is not None


def test_reload_config_resets_transient_state_but_reuses_matching_receipts(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Reload resets runtime work without discarding matching VTI preflight."""

    from digital_twin_runtime_suite.app.airflow_validation.cache import (
        build_dataset_validation_signature,
    )

    controller = RuntimeController("configs/digital_twin_runtime_suite.toml")
    signature = build_dataset_validation_signature(
        _write_airflow_validation_dataset(tmp_path), "vel"
    )
    controller._flow_validation_cache.store_preflight(
        signature,
        {"dimensions": (2, 2, 2)},
        grid_match=True,
    )
    callback_stops = []
    background_stops = []
    loaded_paths = []
    expected_config = controller.config

    def stop_callbacks() -> None:
        callback_stops.append(True)

    def stop_background() -> None:
        background_stops.append(True)

    def load_config(path: Path) -> RuntimeConfig:
        loaded_paths.append(path)
        return expected_config

    monkeypatch.setattr(controller, "stop_flow_runtime_callbacks", stop_callbacks)
    monkeypatch.setattr(
        controller, "stop_background_airflow_validation", stop_background
    )
    monkeypatch.setattr(RuntimeConfig, "load", staticmethod(load_config))
    controller._flow_session_workload_binding = (
        controller.resolve_workload_airflow_binding("Nominal")
    )
    controller._flow_pending_workload_binding = (
        controller.resolve_workload_airflow_binding("Critical")
    )
    controller._flow_last_airflow_failure = {"reason": "old"}
    controller._flow_transition_sequence = 42
    controller._flow_active_transition_id = "T0042"
    controller._airflow_validation_coordinator = object()

    reloaded = controller.reload_config()

    assert callback_stops == [True]
    assert background_stops == [True]
    assert loaded_paths == [controller._config_path]
    assert reloaded is expected_config
    assert controller._flow_lifecycle_state == "DETACHED"
    assert controller._flow_validation_cache.lookup(signature).result == "HIT"
    assert controller._flow_session_workload_binding is None
    assert controller._flow_pending_workload_binding is None
    assert controller._flow_last_airflow_failure is None
    assert controller._flow_transition_sequence == 0
    assert controller._flow_active_transition_id is None
    assert controller._airflow_validation_coordinator is None


def test_runtime_only_config_reload_preserves_matching_dataset_receipt(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Smoke/UI tuning changes do not enter dataset preflight identity."""

    from dataclasses import replace

    from digital_twin_runtime_suite.app.airflow_validation.cache import (
        build_dataset_validation_signature,
    )

    controller = RuntimeController("configs/digital_twin_runtime_suite.toml")
    signature = build_dataset_validation_signature(
        _write_airflow_validation_dataset(tmp_path), "vel"
    )
    controller._flow_validation_cache.store_preflight(
        signature,
        {"dimensions": (2, 2, 2)},
        grid_match=True,
    )
    runtime_only_config = replace(
        controller.config,
        simulation_cache=replace(
            controller.config.simulation_cache,
            smoke_tuning=replace(
                controller.config.simulation_cache.smoke_tuning,
                density=0.73,
            ),
        ),
    )
    monkeypatch.setattr(
        RuntimeConfig,
        "load",
        staticmethod(lambda _path: runtime_only_config),
    )

    controller.reload_config()

    assert controller.config is runtime_only_config
    assert controller._flow_validation_cache.lookup(signature).result == "HIT"
