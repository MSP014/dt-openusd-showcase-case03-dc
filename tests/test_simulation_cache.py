from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from blackwell_monitoring_suite.app.commands import RuntimeController
from blackwell_monitoring_suite.app.config import RuntimeConfig
from blackwell_monitoring_suite.app.simulation_cache import (
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
        Path("configs/blackwell_monitoring_suite.toml"),
        apply_local_overrides=False,
    )
    return config, replace(
        config.simulation_cache,
        root_prim_path="/sim",
        volume_prim_path="/sim/test",
    )


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

    volume = stage.GetPrimAtPath("/BMS_Runtime/Airflow/test")
    field = stage.GetPrimAtPath("/BMS_Runtime/Airflow/test/density")

    assert volume.GetTypeName() == "Volume"
    assert field.GetTypeName() == "OpenVDBAsset"
    assert field.GetAttribute("fieldDataType").Get() == "float"
    assert volume.GetAttribute("nvindex:composite").Get() is True
    assert volume.GetAttribute("omni:rtx:skip").Get() is True
    assert (
        volume.GetCustomDataByKey("nvindex.renderSettings")["filterMode"] == "trilinear"
    )
    assert stage.GetPrimAtPath("/BMS_Runtime/Looks/AirflowIndex").IsValid()
    session_text = stage.GetSessionLayer().ExportToString()
    assert "references = @" in session_text
    assert "outputs:nvindex:volume.connect" in session_text
    assert "OmniVolumeDensity.mdl" not in session_text
