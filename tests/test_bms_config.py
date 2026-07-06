from pathlib import Path

from blackwell_monitoring_suite.app.config import RuntimeConfig


def test_v01_runtime_config_resolves_default_asset():
    config_path = Path("configs/blackwell_monitoring_suite.v0.1.toml")

    config = RuntimeConfig.load(config_path)

    assert config.app_name == "Blackwell Monitoring Suite"
    assert config.app_version == "0.1"
    assert config.default_asset.asset_id == "noctua_nh_d9_tr5_sp6"
    assert config.default_asset_path.name == "cpu_fan.usd"
    assert config.default_asset_path.exists()
