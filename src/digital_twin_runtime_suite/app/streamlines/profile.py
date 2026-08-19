"""Immutable production geometry contract for standard Streamlines caches."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from enum import Enum

PROFILE_STATE_FROZEN = "FROZEN"


class StreamlinesProfileId(str, Enum):
    """Identify one production-facing Streamlines geometry intent."""

    VOLUME_COVERAGE = "volume_coverage"
    GLOBAL_FLOW_PATH = "global_flow_path"


STREAMLINES_PROFILE_LABELS = {
    StreamlinesProfileId.VOLUME_COVERAGE: "Volume Coverage",
    StreamlinesProfileId.GLOBAL_FLOW_PATH: "Global Flow Path",
}
DEFAULT_STREAMLINES_PROFILE = StreamlinesProfileId.VOLUME_COVERAGE


@dataclass(frozen=True)
class StreamlinesGeometryContract:
    """Store effective geometry values without transient UI labels."""

    profile_id: StreamlinesProfileId
    seed_count: int
    max_steps: int
    min_step_cell_multiplier: float
    initial_step_cell_multiplier: float
    max_step_cell_multiplier: float
    section_count: int = 1

    def __post_init__(self) -> None:
        values = (
            self.min_step_cell_multiplier,
            self.initial_step_cell_multiplier,
            self.max_step_cell_multiplier,
        )
        if (
            self.seed_count <= 0
            or self.section_count <= 0
            or self.max_steps <= 0
            or any(not math.isfinite(value) or value <= 0.0 for value in values)
        ):
            raise ValueError("Streamlines geometry contract is invalid.")


FINAL_GLOBAL_FLOW_PATH_GEOMETRY_CONTRACT = StreamlinesGeometryContract(
    profile_id=StreamlinesProfileId.GLOBAL_FLOW_PATH,
    seed_count=256,
    max_steps=200,
    min_step_cell_multiplier=0.02,
    initial_step_cell_multiplier=0.4,
    max_step_cell_multiplier=1.0,
)
FINAL_VOLUME_COVERAGE_GEOMETRY_CONTRACT = StreamlinesGeometryContract(
    profile_id=StreamlinesProfileId.VOLUME_COVERAGE,
    seed_count=256,
    section_count=24,
    max_steps=20,
    min_step_cell_multiplier=0.01,
    initial_step_cell_multiplier=0.2,
    max_step_cell_multiplier=0.5,
)

FINAL_STREAMLINES_GEOMETRY_CONTRACTS = {
    StreamlinesProfileId.VOLUME_COVERAGE: (FINAL_VOLUME_COVERAGE_GEOMETRY_CONTRACT),
    StreamlinesProfileId.GLOBAL_FLOW_PATH: (FINAL_GLOBAL_FLOW_PATH_GEOMETRY_CONTRACT),
}


def final_geometry_contract(
    profile_id: StreamlinesProfileId,
) -> StreamlinesGeometryContract:
    """Return the frozen geometry contract for one production profile."""

    return FINAL_STREAMLINES_GEOMETRY_CONTRACTS[StreamlinesProfileId(profile_id)]


def geometry_contract_signature(contract: StreamlinesGeometryContract) -> str:
    """Hash only frozen geometry/operator values used to generate curves."""

    payload = {
        "profile_id": contract.profile_id.value,
        "seed_count": contract.seed_count,
        "section_count": contract.section_count,
        "max_steps": contract.max_steps,
        "min_step_cell_multiplier": contract.min_step_cell_multiplier,
        "initial_step_cell_multiplier": contract.initial_step_cell_multiplier,
        "max_step_cell_multiplier": contract.max_step_cell_multiplier,
        "direction": "forward",
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class ProductionStreamlinesProfile:
    """All geometry and persisted-attribute choices for one cache generation.

    Step multipliers are dimensionless DAV factors applied to each cell's
    bounding-box diagonal by the installed standard Streamlines operator.
    """

    name: str = "dtrs_standard_streamlines_v3_cell_relative_steps"
    operator_type: str = "standard"
    seed_preset: str = "front_center_unit_sphere"
    seed_resolution: int = 16
    direction: str = "forward"
    seed_radius_domain_fraction: float = 0.1
    seed_radius_cell_multiplier: float = 4.0
    seed_front_inset_radius_multiplier: float = 1.5
    seed_front_inset_cell_multiplier: float = 4.0
    min_step_cell_multiplier: float = 0.01
    initial_step_cell_multiplier: float = 0.2
    max_step_cell_multiplier: float = 0.5
    max_steps: int = 200
    width_cell_multiplier: float = 0.4
    persisted_attributes: tuple[str, ...] = (
        "points",
        "curveVertexCounts",
        "extent",
        "widths",
        "dtrs:sourceTime",
        "primvars:dtrs:speed",
        "dtrs:sourceCurveVertexCounts",
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
    """Source-controlled acceptance state for the immutable production profile."""

    profile: ProductionStreamlinesProfile = PRODUCTION_STREAMLINES_PROFILE
    state: str = PROFILE_STATE_FROZEN
    previewed: bool = True

    @property
    def frozen(self) -> bool:
        """Return whether this session may promote production caches."""

        return self.state == PROFILE_STATE_FROZEN

    def mark_previewed(self) -> "ProductionStreamlinesProfileState":
        """Retain the accepted profile after an optional maintenance preview."""

        return self

    def freeze(self) -> "ProductionStreamlinesProfileState":
        """Return the already accepted source-controlled production profile."""

        return self
