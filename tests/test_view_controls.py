import pytest

from digital_twin_runtime_suite.app.config import (
    EMITTER_LAYOUT_VALUE_OPTIONS,
    SMOKE_TUNING_VALUE_OPTIONS,
    EmitterLayoutConfig,
    SmokeTuningConfig,
)
from digital_twin_runtime_suite.app.view_controls import (
    bool_model_value,
    build_emitter_layout_from_models,
    build_face_panel_state,
    build_smoke_base_color_from_models,
    build_smoke_tuning_from_models,
    build_visibility_state,
    emitter_layout_option_index,
    face_panel_action_label,
    hex_to_rgb,
    hsv_to_rgb,
    rgb_to_hex,
    rgb_to_hsv,
    smoke_tuning_option_index,
)


class BoolPropertyModel:
    def __init__(self, value):
        self._value = value

    @property
    def as_bool(self):
        return self._value


class BoolMethodModel:
    def __init__(self, value):
        self._value = value

    def as_bool(self):
        return self._value


class BoolGetterModel:
    def __init__(self, value):
        self._value = value

    def get_value_as_bool(self):
        return self._value


class IntGetterModel:
    def __init__(self, value):
        self._value = value

    def get_value_as_int(self):
        return self._value


class FloatGetterModel:
    def __init__(self, value):
        self._value = value

    def get_value_as_float(self):
        return self._value


class StringGetterModel:
    def __init__(self, value):
        self._value = value

    def get_value_as_string(self):
        return self._value


class TruthyModel:
    def __init__(self, value):
        self._value = value

    def __bool__(self):
        return bool(self._value)


def test_build_visibility_state_reads_checked_and_unchecked_models():
    state = build_visibility_state(
        {
            "top_cover": BoolPropertyModel(True),
            "left_side_panel": BoolPropertyModel(False),
        },
        ("top_cover", "left_side_panel"),
    )

    assert state == {"top_cover": True, "left_side_panel": False}


def test_build_visibility_state_filters_stale_models_not_in_configured_groups():
    state = build_visibility_state(
        {
            "top_cover": BoolPropertyModel(True),
            "removed_group": BoolPropertyModel(True),
        },
        ("top_cover",),
    )

    assert state == {"top_cover": True}


def test_build_visibility_state_omits_missing_configured_models():
    state = build_visibility_state(
        {"top_cover": BoolPropertyModel(True)},
        ("top_cover", "right_side_panel"),
    )

    assert state == {"top_cover": True}


def test_build_visibility_state_without_group_filter_includes_all_models():
    state = build_visibility_state(
        {
            "left_ear": BoolPropertyModel(False),
            "right_ear": BoolPropertyModel(True),
        }
    )

    assert state == {"left_ear": False, "right_ear": True}


def test_build_visibility_state_handles_empty_controls():
    assert build_visibility_state({}, ("top_cover",)) == {}


def test_bool_model_value_accepts_callable_as_bool_model():
    assert bool_model_value(BoolMethodModel(1)) is True
    assert bool_model_value(BoolMethodModel(0)) is False


def test_bool_model_value_accepts_get_value_as_bool_fallback():
    assert bool_model_value(BoolGetterModel(True)) is True
    assert bool_model_value(BoolGetterModel(False)) is False


def test_bool_model_value_accepts_integer_and_truthiness_fallbacks():
    assert bool_model_value(IntGetterModel(1)) is True
    assert bool_model_value(IntGetterModel(0)) is False
    assert bool_model_value(TruthyModel("checked")) is True
    assert bool_model_value(TruthyModel("")) is False


def test_face_panel_action_label_describes_next_available_action():
    assert face_panel_action_label(False) == "Open front panel"
    assert face_panel_action_label(True) == "Close front panel"


def test_build_face_panel_state_reads_open_and_closed_model_values():
    assert build_face_panel_state(BoolPropertyModel(True)) is True
    assert build_face_panel_state(BoolPropertyModel(False)) is False


def test_build_face_panel_state_accepts_missing_control():
    assert build_face_panel_state(None) is None


def test_smoke_tuning_models_build_a_pending_batch_without_runtime_side_effects():
    selected_values = {
        "density": 1.5,
        "brightness": 1.25,
        "ambient": 0.75,
        "shadow_density": 1.5,
        "damping": 0.005,
        "fade": 0.01,
        "sharpness": 0.5,
        "vorticity": 0.8,
        "velocity_scale_multiplier": 4.0,
        "time_scale": 2.0,
        "raymarch_quality": 0.75,
    }
    models = {
        field_name: IntGetterModel(
            smoke_tuning_option_index(field_name, selected_value)
        )
        for field_name, selected_value in selected_values.items()
    }

    assert build_smoke_tuning_from_models(models) == SmokeTuningConfig(
        **selected_values
    )


def test_smoke_tuning_models_reject_missing_or_invalid_dropdowns():
    complete_models = {
        field_name: IntGetterModel(0) for field_name in SMOKE_TUNING_VALUE_OPTIONS
    }
    missing_models = dict(complete_models)
    missing_models.pop("vorticity")
    with pytest.raises(ValueError, match="vorticity"):
        build_smoke_tuning_from_models(missing_models)

    complete_models["density"] = IntGetterModel(99)
    with pytest.raises(ValueError, match="density"):
        build_smoke_tuning_from_models(complete_models)


def test_smoke_tuning_dropdown_index_rejects_unsupported_resolved_values():
    with pytest.raises(ValueError, match="density"):
        smoke_tuning_option_index("density", 9.0)


def test_smoke_color_hex_and_hsv_forms_build_the_same_pending_rgb_value():
    current_color = (0.58, 0.64, 0.69)
    hue, saturation, value = rgb_to_hsv(current_color)

    assert rgb_to_hex(current_color) == "#94A3B0"
    assert hsv_to_rgb(hue, saturation, value) == pytest.approx(current_color)
    assert hex_to_rgb("#94A3B0") == pytest.approx((148 / 255, 163 / 255, 176 / 255))
    assert build_smoke_base_color_from_models(
        source="hsv",
        hex_model=StringGetterModel("#000000"),
        hue_model=FloatGetterModel(hue),
        saturation_model=FloatGetterModel(saturation),
        value_model=FloatGetterModel(value),
    ) == pytest.approx(current_color)


def test_smoke_color_rejects_invalid_hex_and_hsv_values():
    with pytest.raises(ValueError, match="#RRGGBB"):
        hex_to_rgb("blue")
    with pytest.raises(ValueError, match="hue"):
        hsv_to_rgb(361.0, 50.0, 50.0)
    with pytest.raises(ValueError, match="saturation"):
        hsv_to_rgb(120.0, -1.0, 50.0)


def test_emitter_layout_models_build_a_pending_payload_without_side_effects():
    selected_values = {
        "emitters_per_row": 8,
        "rows": 4,
        "depth": 0.5,
        "size": 0.75,
        "horizontal_margin": 0.08,
        "vertical_margin": 0.1,
    }
    models = {
        field_name: IntGetterModel(
            emitter_layout_option_index(field_name, selected_value)
        )
        for field_name, selected_value in selected_values.items()
    }

    assert build_emitter_layout_from_models(models) == EmitterLayoutConfig(
        **selected_values
    )


def test_emitter_layout_models_reject_missing_or_invalid_dropdowns():
    complete_models = {
        field_name: IntGetterModel(0) for field_name in EMITTER_LAYOUT_VALUE_OPTIONS
    }
    missing_models = dict(complete_models)
    missing_models.pop("rows")
    with pytest.raises(ValueError, match="rows"):
        build_emitter_layout_from_models(missing_models)

    complete_models["depth"] = IntGetterModel(99)
    with pytest.raises(ValueError, match="depth"):
        build_emitter_layout_from_models(complete_models)
    build_emitter_layout_from_models,
    emitter_layout_option_index,
