"""Pure-Python helpers for DTRS view-control state."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from digital_twin_runtime_suite.app.config import (
    SMOKE_TUNING_VALUE_OPTIONS,
    SmokeTuningConfig,
)


def bool_model_value(model: Any) -> bool:
    """Read a boolean value from an OmniUI-like model or test double."""

    if hasattr(model, "as_bool"):
        value = getattr(model, "as_bool")
        return bool(value() if callable(value) else value)
    if hasattr(model, "get_value_as_bool"):
        return bool(model.get_value_as_bool())
    if hasattr(model, "get_value_as_int"):
        return bool(model.get_value_as_int())
    return bool(model)


def int_model_value(model: Any) -> int:
    """Read an integer selection from an OmniUI-like model or test double."""

    if hasattr(model, "get_value_as_int"):
        return int(model.get_value_as_int())
    if hasattr(model, "as_int"):
        value = getattr(model, "as_int")
        return int(value() if callable(value) else value)
    return int(model)


def smoke_tuning_option_index(field_name: str, value: float) -> int:
    """Return the fixed dropdown index for a resolved smoke value."""

    try:
        return SMOKE_TUNING_VALUE_OPTIONS[field_name].index(value)
    except (KeyError, ValueError) as error:
        raise ValueError(
            f"Unsupported Smoke Tuning dropdown value: {field_name}={value!r}."
        ) from error


def build_smoke_tuning_from_models(
    index_models: Mapping[str, Any],
) -> SmokeTuningConfig:
    """Build a pending batch request; this function has no live Flow side effects."""

    values: dict[str, float] = {}
    for field_name, choices in SMOKE_TUNING_VALUE_OPTIONS.items():
        if field_name not in index_models:
            raise ValueError(f"Smoke Tuning control is unavailable: {field_name}.")
        index = int_model_value(index_models[field_name])
        if not 0 <= index < len(choices):
            raise ValueError(
                f"Smoke Tuning selection is out of range: {field_name}={index}."
            )
        values[field_name] = choices[index]
    return SmokeTuningConfig(**values)


def build_visibility_state(
    models: Mapping[str, Any],
    group_ids: Iterable[str] | None = None,
) -> dict[str, bool]:
    """Build the visibility payload submitted by the View tab Apply button."""

    selected_ids = tuple(models) if group_ids is None else tuple(group_ids)
    return {
        group_id: bool_model_value(models[group_id])
        for group_id in selected_ids
        if group_id in models
    }


def face_panel_action_label(is_open: bool) -> str:
    """Return the action label for the front-panel hinge control."""

    return "Close front panel" if is_open else "Open front panel"


def build_face_panel_state(model: Any | None) -> bool | None:
    """Build the front-panel open/close payload from a UI model."""

    if model is None:
        return None
    return bool_model_value(model)
