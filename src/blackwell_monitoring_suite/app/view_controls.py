"""Pure-Python helpers for BMS view-control state."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


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
