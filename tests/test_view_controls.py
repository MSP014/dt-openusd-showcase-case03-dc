from blackwell_monitoring_suite.app.view_controls import (
    bool_model_value,
    build_face_panel_state,
    build_visibility_state,
    face_panel_action_label,
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
