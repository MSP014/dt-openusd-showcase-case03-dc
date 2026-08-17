"""Immutable production geometry contract for standard Streamlines caches."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass

PROFILE_STATE_CANDIDATE = "CANDIDATE"
PROFILE_STATE_FROZEN = "FROZEN"


@dataclass(frozen=True)
class ProductionStreamlinesProfile:
    """All geometry and persisted-attribute choices for one cache generation."""

    name: str = "dtrs_standard_streamlines_v2"
    operator_type: str = "standard"
    seed_preset: str = "front_center_unit_sphere"
    seed_resolution: int = 16
    direction: str = "forward"
    seed_radius_domain_fraction: float = 0.1
    seed_radius_cell_multiplier: float = 4.0
    seed_front_inset_radius_multiplier: float = 1.5
    seed_front_inset_cell_multiplier: float = 4.0
    min_step_cell_multiplier: float = 0.5
    initial_step_cell_multiplier: float = 2.0
    max_step_cell_multiplier: float = 4.0
    max_steps: int = 200
    width_cell_multiplier: float = 0.4
    persisted_attributes: tuple[str, ...] = (
        "points",
        "curveVertexCounts",
        "extent",
        "widths",
        "dtrs:sourceTime",
        "primvars:dtrs:speed",
    )

    def __post_init__(self) -> None:
        """Reject a profile that cannot produce deterministic standard geometry."""

        finite_positive = (
            self.seed_radius_domain_fraction,
            self.seed_radius_cell_multiplier,
            self.seed_front_inset_radius_multiplier,
            self.seed_front_inset_cell_multiplier,
            self.min_step_cell_multiplier,
            self.initial_step_cell_multiplier,
            self.max_step_cell_multiplier,
            self.width_cell_multiplier,
        )
        if (
            self.operator_type != "standard"
            or self.seed_preset != "front_center_unit_sphere"
            or self.direction != "forward"
            or self.seed_resolution < 3
            or self.max_steps <= 0
            or not self.persisted_attributes
            or any(
                not math.isfinite(value) or value <= 0.0 for value in finite_positive
            )
        ):
            raise ValueError("Production Streamlines profile is invalid.")

    def to_dict(self) -> dict[str, object]:
        """Return the complete geometry contract in canonical JSON-safe form."""

        return {
            "name": self.name,
            "operator_type": self.operator_type,
            "seed_preset": self.seed_preset,
            "seed_resolution": self.seed_resolution,
            "direction": self.direction,
            "seed_radius_domain_fraction": self.seed_radius_domain_fraction,
            "seed_radius_cell_multiplier": self.seed_radius_cell_multiplier,
            "seed_front_inset_radius_multiplier": (
                self.seed_front_inset_radius_multiplier
            ),
            "seed_front_inset_cell_multiplier": (self.seed_front_inset_cell_multiplier),
            "min_step_cell_multiplier": self.min_step_cell_multiplier,
            "initial_step_cell_multiplier": self.initial_step_cell_multiplier,
            "max_step_cell_multiplier": self.max_step_cell_multiplier,
            "max_steps": self.max_steps,
            "width_cell_multiplier": self.width_cell_multiplier,
            "persisted_attributes": list(self.persisted_attributes),
        }

    @property
    def settings_signature(self) -> str:
        """Return the stable signature for all cache-affecting profile choices."""

        encoded = json.dumps(
            self.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


PRODUCTION_STREAMLINES_PROFILE = ProductionStreamlinesProfile()


@dataclass(frozen=True)
class ProductionStreamlinesProfileState:
    """Session acceptance state; it never changes the profile signature."""

    profile: ProductionStreamlinesProfile = PRODUCTION_STREAMLINES_PROFILE
    state: str = PROFILE_STATE_CANDIDATE
    previewed: bool = False

    @property
    def frozen(self) -> bool:
        """Return whether this session may promote production caches."""

        return self.state == PROFILE_STATE_FROZEN

    def mark_previewed(self) -> "ProductionStreamlinesProfileState":
        """Record successful representative previews before operator acceptance."""

        return ProductionStreamlinesProfileState(
            profile=self.profile,
            state=self.state,
            previewed=True,
        )

    def freeze(self) -> "ProductionStreamlinesProfileState":
        """Freeze only a previewed profile for the four-cache production build."""

        if not self.previewed:
            raise RuntimeError("Preview Production Profile before accepting it.")
        return ProductionStreamlinesProfileState(
            profile=self.profile,
            state=PROFILE_STATE_FROZEN,
            previewed=True,
        )
