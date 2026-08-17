import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from digital_twin_runtime_suite.app.commands import RuntimeController

# isort: off
from digital_twin_runtime_suite.app.config import (
    CameraConfig,
    EmitterLayoutConfig,
    ChassisPresentationConfig,
    FacePanelConfig,
    FrontPanelIndicatorsConfig,
    GridConfig,
    LightingConfig,
    QledDisplayConfig,
    RotationConfig,
    RuntimeConfig,
    SmokeTuningConfig,
    ValidationReceiptReuseConfig,
    VisibilityGroupConfig,
    chassis_presentation_with_operator_state,
)

# isort: on


def test_v02_runtime_config_resolves_default_asset():
    config_path = Path("configs/digital_twin_runtime_suite.toml")

    config = RuntimeConfig.load(config_path, apply_local_overrides=False)

    assert config.app_name == "Digital Twin Runtime Suite"
    assert config.app_version == "0.4.0"
    assert config.display_version == "0.4"
    assert config.default_asset.asset_id == "blackwell_rig_gb203"
    assert config.default_asset_path.name == "Blackwell_Rig_server_assembly.usd"
    assert config.default_asset_path.exists()
    assert config.simulation_cache.enabled is True
    assert config.simulation_cache.runtime_mode == "kit_cae"
    assert config.simulation_cache_path.name == "sim_test.usda"
    assert config.simulation_cache.wrapper_path == "usd/server_airflows/sim_test.usda"
    assert config.simulation_cache.volume_prim_path == "/sim/test"
    assert config.simulation_cache.sampling_distance == 0.0255
    assert config.simulation_cache.resolution_scale == 25
    assert config.simulation_cache.rendering_samples == 1
    assert config.simulation_cache.filter_mode == "nearest"


@pytest.mark.parametrize(
    ("canonical_version", "display_version"),
    (("0.4.0", "0.4"), ("0.4.1", "0.4"), ("0.4.2", "0.4"), ("0.5.0", "0.5")),
)
def test_runtime_display_version_derives_major_minor(
    canonical_version, display_version
):
    config = RuntimeConfig.load(
        Path("configs/digital_twin_runtime_suite.toml"), apply_local_overrides=False
    )

    assert (
        replace(config, app_version=canonical_version).display_version
        == display_version
    )
    assert config.simulation_cache.temporal_debug_logging is False
    assert config.simulation_cache.smoke_tuning == SmokeTuningConfig(
        density=0.5,
        brightness=1.0,
        ambient=1.0,
        shadow_density=1.0,
        damping=0.0,
        fade=0.0,
        sharpness=0.9,
        vorticity=0.6,
        velocity_scale_multiplier=1.0,
        time_scale=1.0,
        raymarch_quality=0.75,
        base_color=(0.58, 0.64, 0.69),
    )
    assert config.simulation_cache.intake_tracers.count == 7
    assert config.simulation_cache.emitter_layout == EmitterLayoutConfig(
        emitters_per_row=7,
        rows=1,
        depth=1.0,
        size=0.75,
        horizontal_margin=0.04,
        vertical_margin=0.02,
    )
    assert config.simulation_cache.intake_tracers.radius == 0.01
    assert config.simulation_cache.intake_tracers.front_offset == 0.008
    assert config.simulation_cache.intake_tracers.smoke_target == 0.5
    assert config.simulation_cache.intake_tracers.smoke_couple_rate == 30.0
    assert config.simulation_cache.smoke_tuning.base_color == (
        0.58,
        0.64,
        0.69,
    )
    assert config.simulation_cache.airflow_dataset.root == "airflow_datasets"
    assert config.simulation_cache.airflow_dataset.scope == "server"
    assert config.simulation_cache.airflow_dataset.state == "load_normal"
    assert {
        workload_mode: f"{dataset.scope}/{dataset.state}"
        for workload_mode, dataset in (
            config.simulation_cache.workload_dataset_mapping.items()
        )
    } == {
        "Idle": "server/load_idle",
        "Nominal": "server/load_normal",
        "Surge": "server/load_surge",
        "Critical": "server/load_critical",
    }
    dataset = config.resolve_airflow_dataset()
    assert dataset.velocity_vti_path.name == "server_airflow_velocity_normal_1001.vti"
    assert dataset.manifest.sample_count == len(dataset.velocity_vti_sequence_paths)
    assert dataset.manifest.source_fps == 50.0
    assert dataset.manifest.sample_step_frames == 10
    assert dataset.manifest.sample_rate_hz == 5.0
    assert dataset.sample_interval_seconds == 0.2
    assert dataset.loop_duration_seconds == 16.0
    assert dataset.manifest.grid == (184, 72, 232)
    sequence_names = tuple(path.name for path in dataset.velocity_vti_sequence_paths)
    assert sequence_names[0] == "server_airflow_velocity_normal_1001.vti"
    assert sequence_names[-1] == "server_airflow_velocity_normal_1791.vti"
    assert [
        int(name.removesuffix(".vti").rsplit("_", maxsplit=1)[-1])
        for name in sequence_names
    ] == list(range(1001, 1801, 10))
    assert config.velocity_vti_sequence_paths == dataset.velocity_vti_sequence_paths


def test_kit_cae_route_requires_airflow_dataset_identity(tmp_path):
    source_config = Path("configs/digital_twin_runtime_suite.toml")
    invalid_config = source_config.read_text(encoding="utf-8").replace(
        'state = "load_normal"',
        'state = ""',
        1,
    )
    config_path = tmp_path / "digital_twin_runtime_suite.toml"
    config_path.write_text(invalid_config, encoding="utf-8")

    try:
        RuntimeConfig.load(config_path, apply_local_overrides=False)
    except ValueError as error:
        assert "airflow_dataset root, scope, and state" in str(error)
    else:
        raise AssertionError(
            "Expected missing airflow dataset identity to be rejected."
        )


def test_kit_cae_route_requires_all_workload_dataset_mappings(tmp_path):
    source_config = Path("configs/digital_twin_runtime_suite.toml")
    invalid_config = source_config.read_text(encoding="utf-8").replace(
        'Surge = { scope = "server", state = "load_surge" }\n',
        "",
        1,
    )
    config_path = tmp_path / "digital_twin_runtime_suite.toml"
    config_path.write_text(invalid_config, encoding="utf-8")

    with pytest.raises(ValueError, match="missing workload mappings: Surge"):
        RuntimeConfig.load(config_path, apply_local_overrides=False)


@pytest.mark.parametrize(
    ("workload_mode", "dataset_identity"),
    (
        ("Idle", "server/load_idle"),
        ("Nominal", "server/load_normal"),
        ("Surge", "server/load_surge"),
        ("Critical", "server/load_critical"),
    ),
)
def test_simulation_cache_resolves_each_semantic_workload_to_its_dataset(
    workload_mode,
    dataset_identity,
):
    config = RuntimeConfig.load(
        Path("configs/digital_twin_runtime_suite.toml"),
        apply_local_overrides=False,
    )

    selector = config.simulation_cache.airflow_dataset_selector_for_workload(
        workload_mode
    )

    assert f"{selector.scope}/{selector.state}" == dataset_identity


def test_v02_runtime_config_resolves_server_fan_motion_bindings():
    config_path = Path("configs/digital_twin_runtime_suite.toml")

    config = RuntimeConfig.load(config_path, apply_local_overrides=False)

    assert len(config.fan_motion_bindings) == 11
    bindings = {binding.binding_id: binding for binding in config.fan_motion_bindings}
    assert bindings["cpu_cooler"].rotation_axis == "Z"
    assert bindings["cpu_cooler"].pivot_mode == "authored_origin"
    assert bindings["gpu_01_blower"].rotation_axis == "X"
    assert bindings["gpu_01_blower"].metric_id == "gpu_1_fan_rpm"
    assert bindings["psu_fan"].metric_id == "psu_load_percent"
    assert bindings["psu_fan"].telemetry_max_rpm == 100.0
    assert bindings["motherboard_nvme_fan"].rotation_axis == "Y"
    assert bindings["rear_p8_02"].metric_id == "rear_fan_2_rpm"


def test_v02_runtime_config_opens_server_chassis_in_runtime_only():
    config = RuntimeConfig.load(
        Path("configs/digital_twin_runtime_suite.toml"),
        apply_local_overrides=False,
    )

    presentation = config.chassis_presentation
    assert presentation.open_chassis is False
    assert presentation.cover_paths == ()
    assert tuple(group.group_id for group in presentation.visibility_groups) == (
        "top_cover",
        "left_side_panel",
        "left_mounting_ear",
        "right_side_panel",
        "right_mounting_ear",
    )
    top_cover = presentation.visibility_groups[0]
    assert top_cover.label == "Top cover"
    assert top_cover.default_visible is False
    assert top_cover.paths == (
        "/blackwell_rig/chassis/geo/render/chassis/top",
        "/blackwell_rig/chassis/geo/proxy/chassis/top",
    )
    face_panel = presentation.face_panel
    assert face_panel.enabled is True
    assert face_panel.label == "Front panel"
    assert face_panel.target_path == (
        "/blackwell_rig/chassis/geo/render/chassis/face_panel"
    )
    assert face_panel.rotation_axis == "X"
    assert face_panel.closed_angle_degrees == 0.0
    assert face_panel.open_angle_degrees == 90.0
    assert face_panel.animation_duration_seconds == 1.0
    assert face_panel.default_open is False
    qled = presentation.qled_display
    assert qled.enabled is True
    assert qled.metric_id == "cpu_temp_c"
    assert qled.warning_threshold_c == 100.0
    assert qled.maximum_value == 99
    assert qled.normal_emission_color == (0.9, 0.96, 1.0)
    assert qled.warning_emission_color == (1.0, 0.32, 0.04)
    assert qled.digits["tens"]["a"] == (
        "/blackwell_rig/motherboard/geo/render/ws_wrx90e/pcb/"
        "digit_tens_seg_a/digit_tens_seg_a"
    )
    assert qled.digits["units"]["g"] == (
        "/blackwell_rig/motherboard/geo/render/ws_wrx90e/pcb/"
        "digit_units_seg_g/digit_units_seg_g"
    )
    indicators = presentation.front_panel_indicators
    assert indicators.enabled is True
    assert indicators.power_path == (
        "/blackwell_rig/chassis/geo/render/chassis/power_panel/"
        "Power_BTN_Light/Power_BTN_Light"
    )
    assert indicators.hdd_path == (
        "/blackwell_rig/chassis/geo/render/chassis/power_panel/" "Light_HDD/Light_HDD"
    )
    assert indicators.lan_01_metric_id == "lan_1_activity_percent"
    assert indicators.lan_02_metric_id == "lan_2_activity_percent"
    assert indicators.hdd_color == (0.95, 0.98, 1.0)
    assert indicators.lan_01_color == (0.95, 0.98, 1.0)
    assert indicators.lan_02_color == (0.95, 0.98, 1.0)
    assert indicators.off_color == (0.62, 0.65, 0.68)


def test_v02_runtime_config_resolves_default_lighting():
    config_path = Path("configs/digital_twin_runtime_suite.toml")

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


def test_local_simulation_cache_override_wins_over_base_config(tmp_path):
    config_path = _write_runtime_config(tmp_path)
    local_path = RuntimeConfig.local_config_path_for(config_path)
    local_path.write_text(
        "\n".join(
            [
                "[simulation_cache]",
                'wrapper_path = "usd/airflow/runtime_proxy.usda"',
                "resolution_scale = 50",
            ]
        ),
        encoding="utf-8",
    )

    config = RuntimeConfig.load(config_path)
    base_config = RuntimeConfig.load(config_path, apply_local_overrides=False)

    assert config.simulation_cache.enabled is True
    assert config.simulation_cache.wrapper_path == "usd/airflow/runtime_proxy.usda"
    assert config.simulation_cache.resolution_scale == 50
    assert base_config.simulation_cache.enabled is False


def test_local_streamlines_presentation_period_is_persisted_separately(
    tmp_path,
):
    config_path = _write_runtime_config(tmp_path)
    local_path = RuntimeConfig.local_config_path_for(config_path)
    local_path.write_text(
        "\n".join(
            [
                "[simulation_cache]",
                "streamlines_presentation_period_seconds = 0.5",
            ]
        ),
        encoding="utf-8",
    )

    config = RuntimeConfig.load(config_path)
    base_config = RuntimeConfig.load(config_path, apply_local_overrides=False)

    assert config.simulation_cache.streamlines_presentation_period_seconds == 0.5
    assert base_config.simulation_cache.streamlines_presentation_period_seconds is None


def test_local_smoke_tuning_override_wins_per_field(tmp_path):
    config_path = _write_runtime_config(tmp_path)
    local_path = RuntimeConfig.local_config_path_for(config_path)
    local_path.write_text(
        "\n".join(
            [
                "[simulation_cache.smoke_tuning]",
                "density = 1.5",
                "ambient = 0.75",
                "damping = 0.005",
                "vorticity = 0.8",
                "velocity_scale_multiplier = 4.0",
                "time_scale = 2.0",
                "base_color = [0.1, 0.2, 0.3]",
            ]
        ),
        encoding="utf-8",
    )

    tuning = RuntimeConfig.load(config_path).simulation_cache.smoke_tuning

    assert tuning.density == 1.5
    assert tuning.ambient == 0.75
    assert tuning.damping == 0.005
    assert tuning.vorticity == 0.8
    assert tuning.velocity_scale_multiplier == 4.0
    assert tuning.time_scale == 2.0
    assert tuning.base_color == (0.1, 0.2, 0.3)
    assert tuning.brightness == 1.0
    assert tuning.sharpness == 0.9


def test_invalid_local_smoke_tuning_fields_fall_back_independently(tmp_path, caplog):
    config_path = _write_runtime_config(tmp_path)
    local_path = RuntimeConfig.local_config_path_for(config_path)
    local_path.write_text(
        "\n".join(
            [
                "[simulation_cache.smoke_tuning]",
                "density = 1.5",
                "ambient = true",
                "fade = 4.0",
                "sharpness = 0.5",
                "velocity_scale_multiplier = 9.0",
                "time_scale = 5.0",
                "base_color = [1.2, 0.0, 0.0]",
            ]
        ),
        encoding="utf-8",
    )

    tuning = RuntimeConfig.load(config_path).simulation_cache.smoke_tuning

    assert tuning.density == 1.5
    assert tuning.sharpness == 0.5
    assert tuning.ambient == 1.0
    assert tuning.fade == 0.0
    assert tuning.velocity_scale_multiplier == 1.0
    assert tuning.time_scale == 1.0
    assert tuning.base_color == (0.58, 0.64, 0.69)
    assert "smoke_tuning.ambient" in caplog.text
    assert "smoke_tuning.fade" in caplog.text
    assert "smoke_tuning.base_color" in caplog.text


def test_local_emitter_layout_override_round_trips_and_falls_back_per_field(
    tmp_path, caplog
):
    config_path = _write_runtime_config(tmp_path)
    local_path = RuntimeConfig.local_config_path_for(config_path)
    local_path.write_text(
        "\n".join(
            [
                "[simulation_cache.emitter_layout]",
                "emitters_per_row = 8",
                "rows = 3.5",
                "depth = 0.5",
                "size = 9.0",
                "horizontal_margin = 0.08",
                "vertical_margin = 0.5",
            ]
        ),
        encoding="utf-8",
    )

    layout = RuntimeConfig.load(config_path).simulation_cache.emitter_layout

    assert layout == EmitterLayoutConfig(
        emitters_per_row=8,
        rows=1,
        depth=0.5,
        size=0.75,
        horizontal_margin=0.08,
        vertical_margin=0.02,
    )
    assert "emitter_layout.size" in caplog.text
    assert "emitter_layout.rows" in caplog.text
    assert "emitter_layout.vertical_margin" in caplog.text


def test_local_chassis_override_merges_known_controls_and_rejects_bad_values(
    tmp_path,
    caplog,
):
    config_path = _write_chassis_runtime_config(tmp_path)
    local_path = RuntimeConfig.local_config_path_for(config_path)
    local_path.write_text(
        "\n".join(
            [
                "[chassis_presentation]",
                "face_panel_open = true",
                "",
                "[chassis_presentation.visibility]",
                "top_cover = true",
                "left_side = false",
                'right_side = "invalid"',
                "unknown_group = true",
            ]
        ),
        encoding="utf-8",
    )

    presentation = RuntimeConfig.load(config_path).chassis_presentation
    visibility = {
        group.group_id: group.default_visible
        for group in presentation.visibility_groups
    }

    assert visibility == {
        "top_cover": True,
        "left_side": False,
        "right_side": True,
    }
    assert presentation.face_panel.default_open is True
    assert "right_side" in caplog.text
    assert "unknown chassis visibility group" in caplog.text


def test_chassis_operator_state_rejects_unknown_group_and_invalid_face_panel():
    presentation = ChassisPresentationConfig(
        visibility_groups=(
            VisibilityGroupConfig("top", "Top", False, ("/server/top",)),
        ),
    )

    with pytest.raises(ValueError, match="unknown chassis visibility groups"):
        chassis_presentation_with_operator_state(presentation, {"missing": True}, None)
    with pytest.raises(ValueError, match="no front-panel hinge"):
        chassis_presentation_with_operator_state(presentation, {"top": True}, True)


def test_controller_saves_chassis_override_without_losing_peer_overrides(tmp_path):
    config_path = _write_chassis_runtime_config(tmp_path)
    controller = RuntimeController(config_path)
    lighting = LightingConfig(
        hdri_path="hdri/saved.exr",
        exposure=2.0,
        intensity=84.0,
        show_hdri_background=False,
        review_key_light_enabled=False,
        review_key_light_intensity=125.0,
        rotation=RotationConfig(x=1.0, y=2.0, z=3.0),
    )
    tuning = SmokeTuningConfig(density=1.5)
    layout = EmitterLayoutConfig(emitters_per_row=8, rows=3, depth=0.5)
    controller.save_runtime_override(
        lighting,
        grid=GridConfig(enabled=False, step=0.5, width=0.002),
        smoke_tuning=tuning,
        emitter_layout=layout,
    )

    local_path = controller.save_chassis_presentation_override(
        {"top_cover": True, "left_side": False, "right_side": False},
        True,
    )
    reloaded = RuntimeConfig.load(config_path)
    visibility = {
        group.group_id: group.default_visible
        for group in reloaded.chassis_presentation.visibility_groups
    }

    assert local_path.exists()
    assert not local_path.with_name(f"{local_path.name}.tmp").exists()
    assert reloaded.lighting == lighting
    assert reloaded.grid == GridConfig(enabled=False, step=0.5, width=0.002)
    assert reloaded.simulation_cache.smoke_tuning == tuning
    assert reloaded.simulation_cache.emitter_layout == layout
    assert visibility == {"top_cover": True, "left_side": False, "right_side": False}
    assert reloaded.chassis_presentation.face_panel.default_open is True
    local_text = local_path.read_text(encoding="utf-8")
    assert "[chassis_presentation.visibility]" in local_text
    assert "target_path" not in local_text


def test_runtime_controller_saves_emitter_layout_without_losing_peer_overrides(
    tmp_path,
):
    config_path = _write_runtime_config(tmp_path)
    controller = RuntimeController(config_path)
    tuning = SmokeTuningConfig(density=1.5)
    controller.save_smoke_tuning_override(tuning)
    layout = EmitterLayoutConfig(
        emitters_per_row=10,
        rows=5,
        depth=0.25,
        size=1.0,
        horizontal_margin=0.08,
        vertical_margin=0.1,
    )

    local_path = controller.save_emitter_layout_override(layout)
    reloaded = RuntimeConfig.load(config_path)

    assert local_path.exists()
    assert reloaded.simulation_cache.emitter_layout == layout
    assert reloaded.simulation_cache.smoke_tuning == tuning


def test_malformed_local_override_does_not_prevent_startup(tmp_path, caplog):
    config_path = _write_runtime_config(tmp_path)
    local_path = RuntimeConfig.local_config_path_for(config_path)
    local_path.write_text(
        "[simulation_cache.smoke_tuning\ndensity = 1.5", encoding="utf-8"
    )

    config = RuntimeConfig.load(config_path)

    assert config.simulation_cache.smoke_tuning == SmokeTuningConfig()
    assert "Ignoring malformed local DTRS override" in caplog.text


def test_runtime_controller_saves_smoke_tuning_without_losing_peer_overrides(tmp_path):
    config_path = _write_runtime_config(tmp_path)
    controller = RuntimeController(config_path)
    lighting = LightingConfig(
        hdri_path="hdri/saved.exr",
        exposure=2.0,
        intensity=84.0,
        show_hdri_background=False,
        review_key_light_enabled=False,
        review_key_light_intensity=125.0,
        rotation=RotationConfig(x=1.0, y=2.0, z=3.0),
    )
    camera = CameraConfig(
        position=RotationConfig(x=11.0, y=22.0, z=33.0),
        rotation=RotationConfig(x=-10.0, y=45.0, z=5.0),
    )
    grid = GridConfig(enabled=False, step=0.5, width=0.002)
    controller.save_runtime_override(lighting, camera, grid)
    tuning = SmokeTuningConfig(
        density=1.5,
        brightness=1.25,
        ambient=0.75,
        shadow_density=1.5,
        damping=0.005,
        fade=0.01,
        sharpness=0.5,
        vorticity=0.8,
        velocity_scale_multiplier=4.0,
        time_scale=2.0,
        raymarch_quality=0.75,
        base_color=(0.2, 0.3, 0.4),
    )

    local_path = controller.save_smoke_tuning_override(tuning)
    reloaded = RuntimeConfig.load(config_path)

    assert local_path.exists()
    assert not local_path.with_name(f"{local_path.name}.tmp").exists()
    assert reloaded.lighting == lighting
    assert reloaded.camera == camera
    assert reloaded.grid == grid
    assert reloaded.simulation_cache.smoke_tuning == tuning


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


def test_validation_receipt_reuse_is_opt_in_by_default():
    config = RuntimeConfig.load(
        Path("configs/digital_twin_runtime_suite.toml"),
        apply_local_overrides=False,
    )

    assert config.validation_receipts == ValidationReceiptReuseConfig()


def test_validation_receipt_reuse_flags_survive_controller_restart(tmp_path):
    config_path = _write_runtime_config(tmp_path)
    controller = RuntimeController(config_path)

    local_path = controller.save_validation_receipt_reuse_override(
        reuse_verified_vti_receipts=True,
        reuse_verified_streamlines_cache_receipts=True,
    )
    restarted = RuntimeController(config_path)

    assert local_path.exists()
    assert restarted.config.validation_receipts == ValidationReceiptReuseConfig(
        reuse_verified_vti_receipts=True,
        reuse_verified_streamlines_cache_receipts=True,
    )


def test_validation_receipt_reuse_flags_are_independent(tmp_path):
    config_path = _write_runtime_config(tmp_path)
    controller = RuntimeController(config_path)

    controller.save_validation_receipt_reuse_override(
        reuse_verified_vti_receipts=True,
        reuse_verified_streamlines_cache_receipts=False,
    )
    assert RuntimeConfig.load(config_path).validation_receipts == (
        ValidationReceiptReuseConfig(
            reuse_verified_vti_receipts=True,
            reuse_verified_streamlines_cache_receipts=False,
        )
    )

    controller.save_validation_receipt_reuse_override(
        reuse_verified_vti_receipts=False,
        reuse_verified_streamlines_cache_receipts=True,
    )
    assert RuntimeConfig.load(config_path).validation_receipts == (
        ValidationReceiptReuseConfig(
            reuse_verified_vti_receipts=False,
            reuse_verified_streamlines_cache_receipts=True,
        )
    )


def test_saving_another_override_preserves_validation_receipt_flags(tmp_path):
    config_path = _write_runtime_config(tmp_path)
    controller = RuntimeController(config_path)
    controller.save_validation_receipt_reuse_override(
        reuse_verified_vti_receipts=True,
        reuse_verified_streamlines_cache_receipts=True,
    )

    controller.save_smoke_tuning_override(SmokeTuningConfig(density=1.5))
    reloaded = RuntimeConfig.load(config_path)

    assert reloaded.validation_receipts.reuse_verified_vti_receipts is True
    assert (
        reloaded.validation_receipts.reuse_verified_streamlines_cache_receipts is True
    )


def test_runtime_controller_persists_200ms_streamlines_presentation_period(
    tmp_path,
):
    config_path = _write_runtime_config(tmp_path)
    controller = RuntimeController(config_path)

    local_path = controller.save_streamlines_presentation_period(0.2)
    reloaded = RuntimeConfig.load(config_path)
    base_config = RuntimeConfig.load(config_path, apply_local_overrides=False)

    assert local_path.exists()
    local_override = local_path.read_text(encoding="utf-8")
    assert (
        "[simulation_cache]\n" "streamlines_presentation_period_seconds = 0.2\n"
    ) in local_override
    assert "runtime_mode" not in local_override
    assert "airflow_dataset" not in local_override
    assert "velocity_field_name" not in local_override
    assert "streamlines_presentation_period_seconds" in local_override
    assert reloaded.simulation_cache.streamlines_presentation_period_seconds == 0.2
    assert base_config.simulation_cache.streamlines_presentation_period_seconds is None
    assert (
        controller.config.simulation_cache.streamlines_presentation_period_seconds
        == 0.2
    )


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


def test_chassis_presentation_authors_reversible_visibility_in_session_layer():
    from pxr import Usd, UsdGeom

    stage = Usd.Stage.CreateInMemory()
    cover = UsdGeom.Xform.Define(stage, "/server/chassis/top").GetPrim()
    presentation = ChassisPresentationConfig(
        open_chassis=True,
        cover_paths=("/server/chassis/top",),
    )

    previous_target = stage.GetEditTarget()
    stage.SetEditTarget(stage.GetSessionLayer())
    try:
        RuntimeController._apply_chassis_presentation(
            stage,
            presentation,
            True,
            UsdGeom,
        )
    finally:
        stage.SetEditTarget(previous_target)

    assert (
        UsdGeom.Imageable(cover).GetVisibilityAttr().Get() == UsdGeom.Tokens.invisible
    )
    assert "invisible" in stage.GetSessionLayer().ExportToString()
    assert "invisible" not in stage.GetRootLayer().ExportToString()

    stage.SetEditTarget(stage.GetSessionLayer())
    try:
        RuntimeController._apply_chassis_presentation(
            stage,
            presentation,
            False,
            UsdGeom,
        )
    finally:
        stage.SetEditTarget(previous_target)
    assert (
        UsdGeom.Imageable(cover).GetVisibilityAttr().Get() == UsdGeom.Tokens.inherited
    )


def test_chassis_visibility_groups_apply_independent_session_layer_opinions():
    from pxr import Usd, UsdGeom

    stage = Usd.Stage.CreateInMemory()
    side = UsdGeom.Xform.Define(stage, "/server/chassis/side").GetPrim()
    left_panel = UsdGeom.Xform.Define(
        stage,
        "/server/chassis/side/left_side_plate",
    ).GetPrim()
    right_panel = UsdGeom.Xform.Define(
        stage,
        "/server/chassis/side/right_side_plate",
    ).GetPrim()
    presentation = ChassisPresentationConfig(
        visibility_groups=(
            VisibilityGroupConfig(
                group_id="left_side_panel",
                label="Left side panel",
                default_visible=False,
                paths=("/server/chassis/side/left_side_plate",),
            ),
            VisibilityGroupConfig(
                group_id="right_side_panel",
                label="Right side panel",
                default_visible=True,
                paths=("/server/chassis/side/right_side_plate",),
            ),
        ),
    )

    previous_target = stage.GetEditTarget()
    stage.SetEditTarget(stage.GetSessionLayer())
    try:
        RuntimeController._apply_chassis_presentation(
            stage,
            presentation,
            False,
            UsdGeom,
        )
    finally:
        stage.SetEditTarget(previous_target)

    assert (
        UsdGeom.Imageable(left_panel).GetVisibilityAttr().Get()
        == UsdGeom.Tokens.invisible
    )
    assert (
        UsdGeom.Imageable(right_panel).GetVisibilityAttr().Get()
        == UsdGeom.Tokens.inherited
    )

    UsdGeom.Imageable(side).CreateVisibilityAttr().Set(UsdGeom.Tokens.invisible)
    stage.SetEditTarget(stage.GetSessionLayer())
    try:
        matched_count = RuntimeController._apply_chassis_visibility_paths(
            stage,
            ("/server/chassis/side/left_side_plate",),
            True,
            UsdGeom,
        )
    finally:
        stage.SetEditTarget(previous_target)

    assert (
        UsdGeom.Imageable(left_panel).GetVisibilityAttr().Get()
        == UsdGeom.Tokens.inherited
    )
    assert UsdGeom.Imageable(side).GetVisibilityAttr().Get() == UsdGeom.Tokens.inherited
    assert matched_count == 1

    stage.SetEditTarget(stage.GetSessionLayer())
    try:
        missing_count = RuntimeController._apply_chassis_visibility_paths(
            stage,
            ("/server/chassis/missing_panel",),
            True,
            UsdGeom,
        )
    finally:
        stage.SetEditTarget(previous_target)

    assert missing_count == 0


def test_face_panel_hinge_authors_runtime_rotation_in_session_layer():
    from pxr import Gf, Usd, UsdGeom

    stage = Usd.Stage.CreateInMemory()
    panel = UsdGeom.Xform.Define(stage, "/server/chassis/face_panel").GetPrim()
    UsdGeom.Xformable(panel).MakeMatrixXform().Set(Gf.Matrix4d(1.0))
    face_panel = FacePanelConfig(
        enabled=True,
        target_path="/server/chassis/face_panel",
        rotation_axis="X",
        closed_angle_degrees=0.0,
        open_angle_degrees=90.0,
    )

    result = RuntimeController._prepare_face_panel_hinge(
        stage,
        face_panel,
        True,
        Usd,
        UsdGeom,
    )
    RuntimeController._set_face_panel_hinge_angle(
        stage,
        result.rotate_op,
        result.target_angle,
        Usd,
    )

    assert result.success is True
    assert result.start_angle == 0.0
    assert result.target_angle == 90.0
    op_names = [op.GetOpName() for op in UsdGeom.Xformable(panel).GetOrderedXformOps()]
    assert op_names == ["xformOp:transform", "xformOp:rotateX:mspViewHinge"]
    assert result.rotate_op.Get() == 90.0
    assert "mspViewHinge" in stage.GetSessionLayer().ExportToString()
    assert "mspViewHinge" not in stage.GetRootLayer().ExportToString()


def test_face_panel_hinge_reuses_existing_runtime_rotation_op():
    from pxr import Usd, UsdGeom

    stage = Usd.Stage.CreateInMemory()
    panel = UsdGeom.Xform.Define(stage, "/server/chassis/face_panel").GetPrim()
    face_panel = FacePanelConfig(
        enabled=True,
        target_path="/server/chassis/face_panel",
        rotation_axis="X",
        closed_angle_degrees=0.0,
        open_angle_degrees=90.0,
    )

    first = RuntimeController._prepare_face_panel_hinge(
        stage,
        face_panel,
        True,
        Usd,
        UsdGeom,
    )
    RuntimeController._set_face_panel_hinge_angle(stage, first.rotate_op, 90.0, Usd)
    second = RuntimeController._prepare_face_panel_hinge(
        stage,
        face_panel,
        False,
        Usd,
        UsdGeom,
    )

    op_names = [op.GetOpName() for op in UsdGeom.Xformable(panel).GetOrderedXformOps()]
    assert op_names.count("xformOp:rotateX:mspViewHinge") == 1
    assert second.start_angle == 90.0
    assert second.target_angle == 0.0


def test_face_panel_hinge_reports_missing_target():
    from pxr import Usd, UsdGeom

    stage = Usd.Stage.CreateInMemory()
    face_panel = FacePanelConfig(
        enabled=True,
        target_path="/server/chassis/missing_face_panel",
    )

    result = RuntimeController._prepare_face_panel_hinge(
        stage,
        face_panel,
        True,
        Usd,
        UsdGeom,
    )

    assert result.success is False
    assert "target prim not found" in result.message
    assert result.rotate_op is None


def test_qled_display_binds_normal_and_off_materials_in_session_layer():
    from pxr import Gf, Sdf, Usd, UsdShade

    stage = Usd.Stage.CreateInMemory()
    qled = _qled_test_config()
    _define_qled_test_segments(stage, qled)

    applied = RuntimeController._apply_qled_display_temperature(
        stage,
        qled,
        57.2,
        Gf,
        Sdf,
        Usd,
        UsdShade,
    )

    assert applied is True
    assert (
        _bound_material_path(
            stage,
            qled.digits["tens"]["a"],
            UsdShade,
        )
        == "/DTRS_Runtime/Looks/QLEDOnNormal"
    )
    assert (
        _bound_material_path(
            stage,
            qled.digits["tens"]["b"],
            UsdShade,
        )
        == "/DTRS_Runtime/Looks/QLEDOff"
    )
    assert (
        _bound_material_path(
            stage,
            qled.digits["units"]["a"],
            UsdShade,
        )
        == "/DTRS_Runtime/Looks/QLEDOnNormal"
    )
    assert (
        _bound_material_path(
            stage,
            qled.digits["units"]["g"],
            UsdShade,
        )
        == "/DTRS_Runtime/Looks/QLEDOff"
    )
    assert "QLEDOnNormal" in stage.GetSessionLayer().ExportToString()
    assert "QLEDOnNormal" not in stage.GetRootLayer().ExportToString()


def test_qled_display_uses_warning_material_for_over_threshold_temperature():
    from pxr import Gf, Sdf, Usd, UsdShade

    stage = Usd.Stage.CreateInMemory()
    qled = _qled_test_config()
    _define_qled_test_segments(stage, qled)

    RuntimeController._apply_qled_display_temperature(
        stage,
        qled,
        101.0,
        Gf,
        Sdf,
        Usd,
        UsdShade,
    )

    assert (
        _bound_material_path(
            stage,
            qled.digits["tens"]["a"],
            UsdShade,
        )
        == "/DTRS_Runtime/Looks/QLEDOnWarning"
    )
    assert (
        _bound_material_path(
            stage,
            qled.digits["tens"]["e"],
            UsdShade,
        )
        == "/DTRS_Runtime/Looks/QLEDOff"
    )
    assert (
        _bound_material_path(
            stage,
            qled.digits["units"]["g"],
            UsdShade,
        )
        == "/DTRS_Runtime/Looks/QLEDOnWarning"
    )


def test_qled_display_repeated_updates_do_not_duplicate_material_connections():
    from pxr import Gf, Sdf, Usd, UsdShade

    stage = Usd.Stage.CreateInMemory()
    qled = _qled_test_config()
    _define_qled_test_segments(stage, qled)

    for temperature in (57.2, 58.1):
        RuntimeController._apply_qled_display_temperature(
            stage,
            qled,
            temperature,
            Gf,
            Sdf,
            Usd,
            UsdShade,
        )

    material = UsdShade.Material.Get(stage, "/DTRS_Runtime/Looks/QLEDOnNormal")
    source_paths = material.GetSurfaceOutput().GetAttr().GetConnections()
    binding_targets = (
        stage.GetPrimAtPath(qled.digits["tens"]["a"])
        .GetRelationship("material:binding")
        .GetTargets()
    )

    assert len(source_paths) == 1
    assert len(binding_targets) == 1


def test_qled_display_reports_noop_when_segments_are_missing():
    from pxr import Gf, Sdf, Usd, UsdShade

    stage = Usd.Stage.CreateInMemory()
    qled = _qled_test_config()

    applied = RuntimeController._apply_qled_display_temperature(
        stage,
        qled,
        57.2,
        Gf,
        Sdf,
        Usd,
        UsdShade,
    )

    assert applied is False
    assert "material:binding" not in stage.GetSessionLayer().ExportToString()


def test_front_panel_indicators_bind_led_materials_in_session_layer():
    from pxr import Gf, Sdf, Usd, UsdShade

    stage = Usd.Stage.CreateInMemory()
    indicators = _front_panel_indicators_test_config()
    _define_front_panel_indicator_prims(stage, indicators)
    state = SimpleNamespace(power=True, hdd=True, lan_01=False, lan_02=True)

    applied = RuntimeController._apply_front_panel_indicator_state(
        stage,
        indicators,
        state,
        Gf,
        Sdf,
        Usd,
        UsdShade,
    )

    assert applied is True
    assert (
        _bound_material_path(
            stage,
            indicators.power_path,
            UsdShade,
        )
        == "/DTRS_Runtime/Looks/FrontPanelPowerOn"
    )
    assert (
        _bound_material_path(
            stage,
            indicators.hdd_path,
            UsdShade,
        )
        == "/DTRS_Runtime/Looks/FrontPanelHDDOn"
    )
    assert (
        _bound_material_path(
            stage,
            indicators.lan_01_path,
            UsdShade,
        )
        == "/DTRS_Runtime/Looks/FrontPanelIndicatorOff"
    )
    assert (
        _bound_material_path(
            stage,
            indicators.lan_02_path,
            UsdShade,
        )
        == "/DTRS_Runtime/Looks/FrontPanelLAN02On"
    )
    assert "FrontPanelPowerOn" in stage.GetSessionLayer().ExportToString()
    assert "FrontPanelPowerOn" not in stage.GetRootLayer().ExportToString()


def test_front_panel_indicators_keep_inactive_leds_light_but_not_emissive():
    from pxr import Gf, Sdf, Usd, UsdShade

    stage = Usd.Stage.CreateInMemory()
    indicators = _front_panel_indicators_test_config()
    _define_front_panel_indicator_prims(stage, indicators)

    RuntimeController._apply_front_panel_indicator_state(
        stage,
        indicators,
        SimpleNamespace(power=True, hdd=True, lan_01=False, lan_02=False),
        Gf,
        Sdf,
        Usd,
        UsdShade,
    )

    assert _preview_surface_input_tuple(
        stage,
        "/DTRS_Runtime/Looks/FrontPanelHDDOn",
        "diffuseColor",
        UsdShade,
    ) == (0.95, 0.98, 1.0)
    assert _preview_surface_input_tuple(
        stage,
        "/DTRS_Runtime/Looks/FrontPanelHDDOn",
        "emissiveColor",
        UsdShade,
    ) == (0.95, 0.98, 1.0)
    assert _preview_surface_input_tuple(
        stage,
        "/DTRS_Runtime/Looks/FrontPanelIndicatorOff",
        "diffuseColor",
        UsdShade,
    ) == (0.62, 0.65, 0.68)
    assert _preview_surface_input_tuple(
        stage,
        "/DTRS_Runtime/Looks/FrontPanelIndicatorOff",
        "emissiveColor",
        UsdShade,
    ) == (0.0, 0.0, 0.0)


def test_front_panel_indicators_repeated_updates_do_not_duplicate_bindings():
    from pxr import Gf, Sdf, Usd, UsdShade

    stage = Usd.Stage.CreateInMemory()
    indicators = _front_panel_indicators_test_config()
    _define_front_panel_indicator_prims(stage, indicators)

    for hdd_on in (True, False):
        RuntimeController._apply_front_panel_indicator_state(
            stage,
            indicators,
            SimpleNamespace(power=True, hdd=hdd_on, lan_01=True, lan_02=False),
            Gf,
            Sdf,
            Usd,
            UsdShade,
        )

    binding_targets = (
        stage.GetPrimAtPath(indicators.hdd_path)
        .GetRelationship("material:binding")
        .GetTargets()
    )
    assert len(binding_targets) == 1
    assert (
        _bound_material_path(
            stage,
            indicators.hdd_path,
            UsdShade,
        )
        == "/DTRS_Runtime/Looks/FrontPanelIndicatorOff"
    )


def test_front_panel_indicators_report_noop_when_led_prims_are_missing():
    from pxr import Gf, Sdf, Usd, UsdShade

    stage = Usd.Stage.CreateInMemory()
    indicators = _front_panel_indicators_test_config()

    applied = RuntimeController._apply_front_panel_indicator_state(
        stage,
        indicators,
        SimpleNamespace(power=True, hdd=True, lan_01=True, lan_02=True),
        Gf,
        Sdf,
        Usd,
        UsdShade,
    )

    assert applied is False
    assert "material:binding" not in stage.GetSessionLayer().ExportToString()


def test_gpu_profile_writer_creates_json(tmp_path):
    profile_path = RuntimeController._write_gpu_profile(
        tmp_path,
        "rtx",
        [[{"indent": 0, "duration": 406.5}]],
    )

    assert profile_path.exists()
    payload = json.loads(profile_path.read_text(encoding="utf-8"))
    assert payload["hydra_engine"] == "rtx"
    assert payload["gpu_profiler"][0][0]["duration"] == 406.5


def _qled_test_config() -> QledDisplayConfig:
    return QledDisplayConfig(
        enabled=True,
        metric_id="cpu_temp_c",
        digits={
            digit: {
                segment: f"/server/qled/{digit}_{segment}"
                for segment in ("a", "b", "c", "d", "e", "f", "g")
            }
            for digit in ("tens", "units")
        },
    )


def _define_qled_test_segments(stage, qled: QledDisplayConfig) -> None:
    from pxr import UsdGeom

    for segment_paths in qled.digits.values():
        for path in segment_paths.values():
            UsdGeom.Mesh.Define(stage, path)


def _front_panel_indicators_test_config() -> FrontPanelIndicatorsConfig:
    return FrontPanelIndicatorsConfig(
        enabled=True,
        power_path="/server/power_panel/power",
        hdd_path="/server/power_panel/hdd",
        lan_01_path="/server/power_panel/lan_01",
        lan_02_path="/server/power_panel/lan_02",
    )


def _define_front_panel_indicator_prims(
    stage,
    indicators: FrontPanelIndicatorsConfig,
) -> None:
    from pxr import UsdGeom

    for path in (
        indicators.power_path,
        indicators.hdd_path,
        indicators.lan_01_path,
        indicators.lan_02_path,
    ):
        UsdGeom.Mesh.Define(stage, path)


def _bound_material_path(stage, prim_path: str, UsdShade) -> str | None:
    prim = stage.GetPrimAtPath(prim_path)
    material, _binding = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial()
    return str(material.GetPath()) if material else None


def _preview_surface_input_tuple(stage, material_path: str, input_name: str, UsdShade):
    shader = UsdShade.Shader.Get(stage, f"{material_path}/PreviewSurface")
    value = shader.GetInput(input_name).Get()
    return tuple(round(float(component), 4) for component in value)


def _write_chassis_runtime_config(tmp_path: Path) -> Path:
    config_path = _write_runtime_config(tmp_path)
    with config_path.open("a", encoding="utf-8") as config_file:
        config_file.write(
            "\n"
            "[chassis_presentation]\n"
            "open_chassis = false\n"
            "cover_paths = []\n"
            "\n"
            "[chassis_presentation.visibility_groups.top_cover]\n"
            'label = "Top cover"\n'
            "default_visible = false\n"
            'paths = ["/server/chassis/top"]\n'
            "\n"
            "[chassis_presentation.visibility_groups.left_side]\n"
            'label = "Left side"\n'
            "default_visible = true\n"
            'paths = ["/server/chassis/left"]\n'
            "\n"
            "[chassis_presentation.visibility_groups.right_side]\n"
            'label = "Right side"\n'
            "default_visible = true\n"
            'paths = ["/server/chassis/right"]\n'
            "\n"
            "[chassis_presentation.face_panel]\n"
            "enabled = true\n"
            'target_path = "/server/chassis/front"\n'
            'rotation_axis = "X"\n'
            "closed_angle_degrees = 0.0\n"
            "open_angle_degrees = 90.0\n"
            "animation_duration_seconds = 0.0\n"
            "default_open = false\n"
        )
    return config_path


def _write_runtime_config(tmp_path: Path) -> Path:
    config_dir = tmp_path / "configs"
    app_root = tmp_path / "src" / "digital_twin_runtime_suite"
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

    config_path = config_dir / "dtrs.toml"
    config_path.write_text(
        "\n".join(
            [
                "[app]",
                'name = "Digital Twin Runtime Suite"',
                'version = "0.3.0"',
                "",
                "[paths]",
                'app_root = "src/digital_twin_runtime_suite"',
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


def test_runtime_controller_saves_normal_map_scale_override(tmp_path):
    config_path = _write_runtime_config(tmp_path)
    controller = RuntimeController(config_path)

    local_path = controller.save_normal_map_scale_override(1.25)
    reloaded = RuntimeConfig.load(config_path)

    assert local_path.exists()
    assert reloaded.chassis_presentation.materials.normal_map_scale == 1.25
    assert "[chassis_presentation.materials]" in local_path.read_text(encoding="utf-8")
