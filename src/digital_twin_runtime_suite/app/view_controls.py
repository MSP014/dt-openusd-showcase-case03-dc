"""Pure-Python helpers for DTRS view-control state."""

from __future__ import annotations

import colorsys
import math
from collections.abc import Iterable, Mapping
from typing import Any

from digital_twin_runtime_suite.app.config import (
    EMITTER_LAYOUT_VALUE_OPTIONS,
    SMOKE_TUNING_VALUE_OPTIONS,
    EmitterLayoutConfig,
    SmokeTuningConfig,
    XRayMaterialConfig,
)


def bool_model_value(model: Any) -> bool:
    """Read a boolean value from an OmniUI-like model or test double."""

    if hasattr(model, "get_value_as_bool"):
        return bool(model.get_value_as_bool())
    if hasattr(model, "get_value_as_int"):
        return bool(model.get_value_as_int())
    if hasattr(model, "as_bool"):
        value = getattr(model, "as_bool")
        return bool(value() if callable(value) else value)
    return bool(model)


def int_model_value(model: Any) -> int:
    """Read an integer selection from an OmniUI-like model or test double."""

    if hasattr(model, "get_value_as_int"):
        return int(model.get_value_as_int())
    if hasattr(model, "as_int"):
        value = getattr(model, "as_int")
        return int(value() if callable(value) else value)
    return int(model)


def string_model_value(model: Any) -> str:
    """Read a string from an OmniUI-like model or test double."""

    if hasattr(model, "get_value_as_string"):
        return str(model.get_value_as_string())
    if hasattr(model, "as_string"):
        value = getattr(model, "as_string")
        return str(value() if callable(value) else value)
    return str(model)


def float_model_value(model: Any) -> float:
    """Read a floating-point value from an OmniUI-like model or test double."""

    if hasattr(model, "get_value_as_float"):
        return float(model.get_value_as_float())
    if hasattr(model, "as_float"):
        value = getattr(model, "as_float")
        return float(value() if callable(value) else value)
    return float(model)


def normal_map_scale_from_model(model: Any) -> float:
    """Read the temporary normal-map scale control in a safe range."""

    value = float_model_value(model)
    if not math.isfinite(value) or not 0.0 <= value <= 4.0:
        raise ValueError("Normal map scale must be between 0 and 4.")
    return value


def xray_material_config_from_models(
    chassis_selected_model: Any,
    part_a_opacity_model: Any,
    part_a_roughness_model: Any,
    part_a_fallback_color_model: Any,
    part_b_color_model: Any,
    part_b_opacity_model: Any,
    part_b_roughness_model: Any,
    part_b_emission_intensity_model: Any,
    edge_falloff_model: Any,
) -> XRayMaterialConfig:
    """Build validated persisted X-Ray settings from OmniUI-like models."""

    normalized = {
        "Part A opacity": float_model_value(part_a_opacity_model),
        "Part A roughness": float_model_value(part_a_roughness_model),
        "Part B opacity": float_model_value(part_b_opacity_model),
        "Part B roughness": float_model_value(part_b_roughness_model),
        "Edge Falloff": float_model_value(edge_falloff_model),
    }
    for label, value in normalized.items():
        if not math.isfinite(value) or not 0.0 <= value <= 1.0:
            raise ValueError(f"{label} must be between 0 and 1.")
    emission_intensity = float_model_value(part_b_emission_intensity_model)
    if not math.isfinite(emission_intensity) or not 0.0 <= emission_intensity <= 1000.0:
        raise ValueError("Emission must be between 0 and 1000.")
    return XRayMaterialConfig(
        chassis_selected=bool_model_value(chassis_selected_model),
        part_a_opacity=normalized["Part A opacity"],
        part_a_roughness=normalized["Part A roughness"],
        part_a_fallback_color=hex_to_rgb(
            string_model_value(part_a_fallback_color_model)
        ),
        part_b_color=hex_to_rgb(string_model_value(part_b_color_model)),
        part_b_opacity=normalized["Part B opacity"],
        part_b_roughness=normalized["Part B roughness"],
        part_b_emission_intensity=emission_intensity,
        edge_falloff=normalized["Edge Falloff"],
    )


def rgb_to_hex(color: tuple[float, float, float]) -> str:
    """Format a normalized Flow RGB color as an operator-facing HEX value."""

    _validate_rgb(color)
    return "#" + "".join(f"{round(component * 255):02X}" for component in color)


def hex_to_rgb(value: str) -> tuple[float, float, float]:
    """Parse a #RRGGBB operator color into normalized Flow RGB values."""

    token = value.strip()
    if token.startswith("#"):
        token = token[1:]
    if len(token) != 6 or any(
        character not in "0123456789abcdefABCDEF" for character in token
    ):
        raise ValueError("Smoke color HEX must use #RRGGBB.")
    return tuple(int(token[index : index + 2], 16) / 255.0 for index in range(0, 6, 2))


def rgb_to_hsv(color: tuple[float, float, float]) -> tuple[float, float, float]:
    """Convert normalized RGB to operator-facing degrees and percentages."""

    _validate_rgb(color)
    hue, saturation, value = colorsys.rgb_to_hsv(*color)
    return hue * 360.0, saturation * 100.0, value * 100.0


def hsv_to_rgb(
    hue_degrees: float,
    saturation_percent: float,
    value_percent: float,
) -> tuple[float, float, float]:
    """Convert operator-facing HSV degrees and percentages to normalized RGB."""

    if not 0.0 <= hue_degrees <= 360.0:
        raise ValueError("Smoke color hue must be between 0 and 360.")
    if not 0.0 <= saturation_percent <= 100.0:
        raise ValueError("Smoke color saturation must be between 0 and 100.")
    if not 0.0 <= value_percent <= 100.0:
        raise ValueError("Smoke color value must be between 0 and 100.")
    return colorsys.hsv_to_rgb(
        hue_degrees / 360.0,
        saturation_percent / 100.0,
        value_percent / 100.0,
    )


def build_smoke_base_color_from_models(
    *,
    source: str,
    hex_model: Any,
    hue_model: Any,
    saturation_model: Any,
    value_model: Any,
) -> tuple[float, float, float]:
    """Build the pending color from the most recently edited UI representation."""

    if source == "hex":
        return hex_to_rgb(string_model_value(hex_model))
    if source == "hsv":
        return hsv_to_rgb(
            float_model_value(hue_model),
            float_model_value(saturation_model),
            float_model_value(value_model),
        )
    raise ValueError("Smoke color source must be HEX or HSV.")


def rgb_to_omniui_color(color: tuple[float, float, float]) -> int:
    """Serialize normalized RGB into OmniUI's packed ABGR style color."""

    _validate_rgb(color)
    red, green, blue = (round(component * 255) for component in color)
    return 0xFF000000 | (blue << 16) | (green << 8) | red


def _validate_rgb(color: tuple[float, float, float]) -> None:
    if len(color) != 3 or any(not 0.0 <= component <= 1.0 for component in color):
        raise ValueError("Smoke color must be three RGB values in [0, 1].")


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
    *,
    base_color: tuple[float, float, float] | None = None,
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
    return SmokeTuningConfig(
        **values,
        base_color=SmokeTuningConfig().base_color if base_color is None else base_color,
    )


def emitter_layout_option_index(field_name: str, value: float | int) -> int:
    """Return the fixed dropdown index for a resolved emitter-layout value."""

    try:
        return EMITTER_LAYOUT_VALUE_OPTIONS[field_name].index(value)
    except (KeyError, ValueError) as error:
        raise ValueError(
            f"Unsupported Emitter Layout dropdown value: {field_name}={value!r}."
        ) from error


def build_emitter_layout_from_models(
    index_models: Mapping[str, Any],
) -> EmitterLayoutConfig:
    """Build a pending layout request; this function has no Kit side effects."""

    values: dict[str, float | int] = {}
    for field_name, choices in EMITTER_LAYOUT_VALUE_OPTIONS.items():
        if field_name not in index_models:
            raise ValueError(f"Emitter Layout control is unavailable: {field_name}.")
        index = int_model_value(index_models[field_name])
        if not 0 <= index < len(choices):
            raise ValueError(
                f"Emitter Layout selection is out of range: {field_name}={index}."
            )
        values[field_name] = choices[index]
    return EmitterLayoutConfig(**values)


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
