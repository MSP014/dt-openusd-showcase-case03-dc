"""Runtime-only quality choices for Kit-CAE Flow A/B testing."""

from __future__ import annotations

from typing import Any

KIT_CAE_FLOW_VOXEL_RESOLUTION_OPTIONS = (128, 192, 256)


def kit_cae_flow_voxel_resolution_from_index(index_model: Any) -> int:
    """Resolve a pending OmniUI combo selection without applying it to Flow."""

    if hasattr(index_model, "get_value_as_int"):
        index = int(index_model.get_value_as_int())
    elif hasattr(index_model, "as_int"):
        value = getattr(index_model, "as_int")
        index = int(value() if callable(value) else value)
    else:
        index = int(index_model)
    if not 0 <= index < len(KIT_CAE_FLOW_VOXEL_RESOLUTION_OPTIONS):
        raise ValueError(f"Flow voxel resolution selection is out of range: {index}.")
    return KIT_CAE_FLOW_VOXEL_RESOLUTION_OPTIONS[index]


def validate_kit_cae_flow_voxel_resolution(max_resolution: int) -> None:
    """Reject values outside the temporary, tested Kit-CAE A/B range."""

    if (
        type(max_resolution) is not int
        or max_resolution not in KIT_CAE_FLOW_VOXEL_RESOLUTION_OPTIONS
    ):
        supported = ", ".join(
            str(value) for value in KIT_CAE_FLOW_VOXEL_RESOLUTION_OPTIONS
        )
        raise ValueError(
            f"Flow voxel resolution must be one of {{{supported}}}, "
            f"got {max_resolution!r}."
        )
