from pathlib import Path

from blackwell_monitoring_suite.app.commands import RuntimeController

# isort: off
from blackwell_monitoring_suite.app.config import (
    CameraConfig,
    LightingConfig,
    RotationConfig,
    RuntimeConfig,
)

# isort: on


def test_v02_runtime_config_resolves_default_asset():
    config_path = Path("configs/blackwell_monitoring_suite.toml")

    config = RuntimeConfig.load(config_path, apply_local_overrides=False)

    assert config.app_name == "Blackwell Monitoring Suite"
    assert config.app_version == "0.2.0"
    assert config.default_asset.asset_id == "noctua_nh_d9_tr5_sp6"
    assert config.default_asset_path.name == "cpu_fan.usd"
    assert config.default_asset_path.exists()


def test_v02_runtime_config_resolves_default_lighting():
    config_path = Path("configs/blackwell_monitoring_suite.toml")

    config = RuntimeConfig.load(config_path, apply_local_overrides=False)

    assert config.lighting.hdri_path == (
        "hdri/kloofendal_48d_partly_cloudy_puresky_4k.exr"
    )
    assert config.lighting.exposure == 0.0
    assert config.lighting.intensity == 500.0
    assert config.lighting.show_hdri_background is True
    assert config.lighting.review_key_light_enabled is True
    assert config.lighting.review_key_light_intensity == 1200.0
    assert config.lighting.rotation.x == 0.0
    assert config.lighting.rotation.y == 0.0
    assert config.lighting.rotation.z == 0.0
    assert config.default_hdri_path.name == (
        "kloofendal_48d_partly_cloudy_puresky_4k.exr"
    )
    assert config.default_hdri_path.exists()


def test_local_lighting_override_wins_over_base_config(tmp_path):
    config_path = _write_runtime_config(tmp_path)
    local_path = RuntimeConfig.local_config_path_for(config_path)
    local_path.write_text(
        "\n".join(
            [
                "[lighting]",
                'default_hdri_path = "hdri/local.exr"',
                "exposure = 1.5",
                "intensity = 42.0",
                "show_hdri_background = false",
                "review_key_light_enabled = false",
                "review_key_light_intensity = 250.0",
                "",
                "[lighting.rotation]",
                "x = 10.0",
                "y = 20.0",
                "z = 30.0",
            ]
        ),
        encoding="utf-8",
    )

    config = RuntimeConfig.load(config_path)
    base_config = RuntimeConfig.load(config_path, apply_local_overrides=False)

    assert config.lighting.hdri_path == "hdri/local.exr"
    assert config.lighting.exposure == 1.5
    assert config.lighting.intensity == 42.0
    assert config.lighting.show_hdri_background is False
    assert config.lighting.review_key_light_enabled is False
    assert config.lighting.review_key_light_intensity == 250.0
    assert config.lighting.rotation.x == 10.0
    assert config.lighting.rotation.y == 20.0
    assert config.lighting.rotation.z == 30.0
    assert base_config.lighting.hdri_path == "hdri/base.exr"
    assert base_config.lighting.intensity == 10.0


def test_local_camera_override_wins_over_base_config(tmp_path):
    config_path = _write_runtime_config(tmp_path)
    local_path = RuntimeConfig.local_config_path_for(config_path)
    local_path.write_text(
        "\n".join(
            [
                "[camera.position]",
                "x = 1.0",
                "y = 2.0",
                "z = 3.0",
                "",
                "[camera.rotation]",
                "x = 10.0",
                "y = 20.0",
                "z = 30.0",
            ]
        ),
        encoding="utf-8",
    )

    config = RuntimeConfig.load(config_path)
    base_config = RuntimeConfig.load(config_path, apply_local_overrides=False)

    assert config.camera is not None
    assert config.camera.position.x == 1.0
    assert config.camera.position.y == 2.0
    assert config.camera.position.z == 3.0
    assert config.camera.rotation.x == 10.0
    assert config.camera.rotation.y == 20.0
    assert config.camera.rotation.z == 30.0
    assert base_config.camera is None


def test_runtime_controller_saves_and_clears_lighting_override(tmp_path):
    config_path = _write_runtime_config(tmp_path)
    controller = RuntimeController(config_path)
    local_path = RuntimeConfig.local_config_path_for(config_path)

    controller.save_lighting_override(
        LightingConfig(
            hdri_path="hdri/saved.exr",
            exposure=2.0,
            intensity=84.0,
            show_hdri_background=False,
            review_key_light_enabled=False,
            review_key_light_intensity=125.0,
            rotation=RotationConfig(x=1.0, y=2.0, z=3.0),
        )
    )

    assert local_path.exists()
    assert RuntimeConfig.load(config_path).lighting.hdri_path == "hdri/saved.exr"
    assert RuntimeConfig.load(config_path).lighting.intensity == 84.0
    assert RuntimeConfig.load(config_path).lighting.show_hdri_background is False

    config = controller.clear_lighting_override()

    assert not local_path.exists()
    assert config.lighting.hdri_path == "hdri/base.exr"
    assert config.lighting.intensity == 10.0


def test_runtime_controller_saves_camera_override(tmp_path):
    config_path = _write_runtime_config(tmp_path)
    controller = RuntimeController(config_path)

    controller.save_runtime_override(
        LightingConfig(
            hdri_path="hdri/saved.exr",
            exposure=2.0,
            intensity=84.0,
            show_hdri_background=True,
            review_key_light_enabled=False,
            review_key_light_intensity=125.0,
            rotation=RotationConfig(x=1.0, y=2.0, z=3.0),
        ),
        CameraConfig(
            position=RotationConfig(x=11.0, y=22.0, z=33.0),
            rotation=RotationConfig(x=-10.0, y=45.0, z=5.0),
        ),
    )

    config = RuntimeConfig.load(config_path)

    assert config.camera is not None
    assert config.camera.position.x == 11.0
    assert config.camera.position.y == 22.0
    assert config.camera.position.z == 33.0
    assert config.camera.rotation.x == -10.0
    assert config.camera.rotation.y == 45.0
    assert config.camera.rotation.z == 5.0


def _write_runtime_config(tmp_path: Path) -> Path:
    config_dir = tmp_path / "configs"
    app_root = tmp_path / "src" / "blackwell_monitoring_suite"
    asset_root = tmp_path / "assets" / "_external"
    config_dir.mkdir()
    app_root.mkdir(parents=True)
    (asset_root / "usd" / "cpu_fan").mkdir(parents=True)
    (asset_root / "hdri").mkdir(parents=True)
    (asset_root / "usd" / "cpu_fan" / "cpu_fan.usd").write_text(
        "#usda 1.0\n",
        encoding="utf-8",
    )
    (asset_root / "hdri" / "base.exr").write_bytes(b"base")

    config_path = config_dir / "bms.toml"
    config_path.write_text(
        "\n".join(
            [
                "[app]",
                'name = "Blackwell Monitoring Suite"',
                'version = "0.2.0"',
                "",
                "[paths]",
                'app_root = "src/blackwell_monitoring_suite"',
                'asset_root = "../../assets/_external"',
                "",
                "[assets]",
                'default_asset_id = "noctua_nh_d9_tr5_sp6"',
                "",
                "[assets.entries.noctua_nh_d9_tr5_sp6]",
                'label = "Noctua NH-D9 TR5-SP6"',
                'path = "usd/cpu_fan/cpu_fan.usd"',
                'kind = "usd_stage"',
                "",
                "[lighting]",
                'default_hdri_path = "hdri/base.exr"',
                "exposure = 0.0",
                "intensity = 10.0",
                "show_hdri_background = true",
                "review_key_light_enabled = true",
                "review_key_light_intensity = 1200.0",
                "",
                "[lighting.rotation]",
                "x = 0.0",
                "y = 0.0",
                "z = 0.0",
            ]
        ),
        encoding="utf-8",
    )
    return config_path
