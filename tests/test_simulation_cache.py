from __future__ import annotations

from dataclasses import replace
from pathlib import Path

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
        raymarch_quality=0.75,
    )

    RuntimeController._author_kit_cae_smoke_tuning(
        stage,
        str(environment.GetPath()),
        custom_tuning,
    )

    assert ray_march_cloud.GetAttribute("densityMultiplier").Get() == 1.5
    assert ray_march_cloud.GetAttribute("volumeColorMultiplier").Get() == 1.25
    assert ray_march_cloud.GetAttribute("ambientMultiplier").Get() == 0.75
    assert tuple(
        ray_march_cloud.GetAttribute("attenuationMultiplier").Get()
    ) == pytest.approx((1.5, 1.5, 1.5))
    assert smoke.GetAttribute("damping").Get() == pytest.approx(0.005)
    assert smoke.GetAttribute("fade").Get() == pytest.approx(0.01)
    assert smoke.GetAttribute("secondOrderBlendFactor").Get() == pytest.approx(0.5)
    assert vorticity.GetAttribute("enabled").Get() is False
    assert vorticity.GetAttribute("forceScale").Get() == 0.0
    assert ray_march.GetAttribute("stepSizeScale").Get() == pytest.approx(0.75)
    assert simulate.GetAttribute("forceClear").Get() is False


def test_kit_cae_temporal_velocity_samples_author_sixteen_sparse_vti_frames(tmp_path):
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
        for frame in (
            1001,
            1051,
            1101,
            1151,
            1201,
            1251,
            1301,
            1351,
            1401,
            1451,
            1501,
            1551,
            1601,
            1651,
            1701,
            1751,
        )
    )
    time_codes = RuntimeController._author_kit_cae_temporal_velocity_samples(
        field.GetPrim(),
        paths,
        50.0,
        FakeCaeVtk,
        Sdf,
        Usd,
    )

    assert time_codes == tuple(float(time_code) for time_code in range(0, 800, 50))
    assert [
        file_names_attr.Get(Usd.TimeCode(time_code))[0].path for time_code in time_codes
    ] == [path.as_posix() for path in paths]


def test_kit_cae_temporal_loop_proof_requires_sixteen_distinct_sources_and_closure(
    tmp_path,
):
    velocity_paths = tuple(
        tmp_path / f"server_airflow_velocity_{frame}.vti"
        for frame in (
            1001,
            1051,
            1101,
            1151,
            1201,
            1251,
            1301,
            1351,
            1401,
            1451,
            1501,
            1551,
            1601,
            1651,
            1701,
            1751,
        )
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
                    "INITIAL" if index == 0 else "LOOP" if index == 16 else "SWAP"
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
    assert summary["forward_transitions"] == 15
    assert summary["loop_transitions"] == 1
    assert summary["loop_closure"] is True
    assert summary["unique_assets"] == 16
    assert summary["unique_hashes"] == 16

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
