from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from digital_twin_runtime_suite.app.commands import (
    FlowPerformanceSample,
    RuntimeController,
)
from digital_twin_runtime_suite.app.config import RuntimeConfig
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


def test_kit_cae_temporal_velocity_samples_author_three_vti_frames(tmp_path):
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
        for frame in (1014, 1015, 1016)
    )
    time_codes = RuntimeController._author_kit_cae_temporal_velocity_samples(
        field.GetPrim(),
        paths,
        50.0,
        FakeCaeVtk,
        Sdf,
        Usd,
    )

    assert time_codes == (0.0, 50.0, 100.0)
    assert [
        file_names_attr.Get(Usd.TimeCode(time_code))[0].path for time_code in time_codes
    ] == [path.as_posix() for path in paths]


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


def test_kit_cae_native_fuel_probe_disables_only_render_debug_overrides():
    from pxr import Sdf, Usd, UsdGeom

    stage = Usd.Stage.CreateInMemory()
    environment = UsdGeom.Xform.Define(stage, "/DTRS_KitCAE/FlowSimulation")
    offscreen = UsdGeom.Xform.Define(
        stage,
        "/DTRS_KitCAE/FlowSimulation/flowOffscreen",
    )
    render = UsdGeom.Xform.Define(
        stage,
        "/DTRS_KitCAE/FlowSimulation/flowRender",
    )
    debug_volume = UsdGeom.Xform.Define(
        stage,
        "/DTRS_KitCAE/FlowSimulation/flowOffscreen/debugVolume",
    )
    ray_march = UsdGeom.Xform.Define(
        stage,
        "/DTRS_KitCAE/FlowSimulation/flowRender/rayMarch",
    )
    debug_volume.GetPrim().CreateAttribute(
        "enableVelocityAsDensity",
        Sdf.ValueTypeNames.Bool,
    ).Set(True)
    ray_march.GetPrim().CreateAttribute(
        "enableRawMode",
        Sdf.ValueTypeNames.Bool,
    ).Set(True)

    RuntimeController._configure_kit_cae_native_fuel_smoke_probe(
        stage,
        str(environment.GetPath()),
    )

    assert debug_volume.GetPrim().GetAttribute("enableVelocityAsDensity").Get() is False
    assert ray_march.GetPrim().GetAttribute("enableRawMode").Get() is False
    assert offscreen.GetPrim().IsValid()
    assert render.GetPrim().IsValid()


def test_kit_cae_flow_presentation_authors_tracer_ramp_and_opacity_only():
    from pxr import Gf, Sdf, Usd, UsdGeom

    stage = Usd.Stage.CreateInMemory()
    environment = UsdGeom.Xform.Define(stage, "/DTRS_KitCAE/FlowSimulation")
    UsdGeom.Xform.Define(
        stage,
        "/DTRS_KitCAE/FlowSimulation/flowOffscreen",
    )
    UsdGeom.Xform.Define(
        stage,
        "/DTRS_KitCAE/FlowSimulation/flowRender",
    )
    ray_march = UsdGeom.Xform.Define(
        stage,
        "/DTRS_KitCAE/FlowSimulation/flowRender/rayMarch",
    )
    ray_march.GetPrim().CreateAttribute(
        "attenuation",
        Sdf.ValueTypeNames.Float,
    ).Set(3.0)
    colormap = UsdGeom.Xform.Define(
        stage,
        "/DTRS_KitCAE/FlowSimulation/flowOffscreen/colormap",
    )
    colormap.GetPrim().CreateAttribute(
        "rgbaPoints",
        Sdf.ValueTypeNames.Float4Array,
    ).Set(
        [
            Gf.Vec4f(0.2, 0.3, 0.8, 0.3),
            Gf.Vec4f(1.0, 1.0, 0.0, 0.3),
            Gf.Vec4f(0.7, 0.01, 0.14, 1.0),
        ]
    )
    injector = UsdGeom.Mesh.Define(stage, "/DTRS_KitCAE/SmokeInjector")
    emitter = UsdGeom.Xform.Define(stage, "/DTRS_KitCAE/SmokeInjector/EmitterSphere")
    stage.SetEditTarget(stage.GetSessionLayer())

    alphas = RuntimeController._author_kit_cae_flow_presentation(
        stage,
        str(environment.GetPath()),
        str(injector.GetPath()),
        10.0,
        "medium",
        Gf,
        UsdGeom,
    )

    rgba_points = colormap.GetPrim().GetAttribute("rgbaPoints").Get()
    assert alphas == (0.6, 0.6, 1.0)
    assert ray_march.GetPrim().GetAttribute("attenuation").Get() == 10.0
    assert [round(point[3], 2) for point in rgba_points] == [0.6, 0.6, 1.0]
    assert [
        tuple(round(float(point[index]), 3) for index in range(3))
        for point in rgba_points
    ] == [
        (0.015, 0.08, 0.3),
        (0.0, 0.72, 0.88),
        (0.82, 1.0, 1.0),
    ]
    assert (
        UsdGeom.Imageable(injector.GetPrim()).ComputeVisibility()
        == UsdGeom.Tokens.invisible
    )
    assert emitter.GetPrim().IsValid()
