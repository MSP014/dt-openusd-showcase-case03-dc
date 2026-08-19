"""Background orchestration for fixed-scale calibration from final caches."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Callable

from digital_twin_runtime_suite.app.diagnostics import with_dtrs_yerevan_timestamp
from digital_twin_runtime_suite.app.streamlines.presentation import PhysicalSpeedScale
from digital_twin_runtime_suite.app.streamlines.profile import StreamlinesProfileId
from digital_twin_runtime_suite.app.streamlines.speed_distribution import (
    SpeedDistribution,
    SpeedScaleCoverage,
    persisted_speed_coverage,
    persisted_speed_distribution,
    proposed_speed_max,
)

StatusCallback = Callable[[str], None]


@dataclass(frozen=True)
class StreamlinesSpeedDistributionReceipt:
    workload: str
    dataset_identity: str
    profile_id: StreamlinesProfileId
    distribution: SpeedDistribution
    coverage: SpeedScaleCoverage


@dataclass(frozen=True)
class StreamlinesSpeedScaleProposal:
    scale: PhysicalSpeedScale
    receipts: tuple[StreamlinesSpeedDistributionReceipt, ...]


class StreamlinesSpeedDistributionRuntimeMixin:
    """Read cache samples off-thread; never mutate cache or presentation."""

    async def collect_streamlines_speed_scale_proposal(
        self,
        status_callback: StatusCallback | None = None,
    ) -> StreamlinesSpeedScaleProposal:
        self._log_streamlines_speed_scale("START", "Reading 8 final raw-speed caches.")
        distributions = []
        targets = self.resolve_configured_airflow_targets()
        for target in targets:
            for profile_id in StreamlinesProfileId:
                receipt = await self.ensure_streamlines_cache_validation_in_background(
                    target.binding,
                    target.dataset,
                    profile_id=profile_id,
                )
                if not receipt.inspection.valid or receipt.inspection.metadata is None:
                    raise RuntimeError(
                        f"{target.binding.workload_mode}/{profile_id.value} cache is "
                        f"{receipt.inspection.classification}."
                    )
                if status_callback:
                    status_callback(
                        f"Speed distribution: {target.binding.workload_mode}/"
                        f"{profile_id.value}."
                    )
                distribution = await asyncio.to_thread(
                    persisted_speed_distribution,
                    receipt.inspection.paths.geometry_path,
                    receipt.inspection.metadata,
                )
                distributions.append((target, profile_id, receipt, distribution))
        upper = proposed_speed_max(
            item[3]
            for item in distributions
            if item[1] is StreamlinesProfileId.VOLUME_COVERAGE
        )
        scale = PhysicalSpeedScale(0.0, upper, "source velocity units")
        final = []
        for target, profile_id, receipt, distribution in distributions:
            coverage = await asyncio.to_thread(
                persisted_speed_coverage,
                receipt.inspection.paths.geometry_path,
                receipt.inspection.metadata,
                minimum=scale.minimum,
                maximum=scale.maximum,
            )
            final.append(
                StreamlinesSpeedDistributionReceipt(
                    target.binding.workload_mode,
                    target.binding.dataset_identity,
                    profile_id,
                    distribution,
                    coverage,
                )
            )
        proposal = StreamlinesSpeedScaleProposal(scale, tuple(final))
        self._streamlines_speed_scale_proposal = proposal
        evidence = []
        for item in proposal.receipts:
            distribution = item.distribution
            coverage = item.coverage
            evidence.append(
                f"{item.workload}/{item.profile_id.value}: "
                f"count={distribution.value_count}; min={distribution.minimum:.9g}; "
                f"p01={distribution.p01:.9g}; p05={distribution.p05:.9g}; "
                f"p50={distribution.p50:.9g}; p95={distribution.p95:.9g}; "
                f"p99={distribution.p99:.9g}; max={distribution.maximum:.9g}; "
                f"below={coverage.below_percent:.6g}%; "
                f"inside={coverage.inside_percent:.6g}%; "
                f"above={coverage.above_percent:.6g}%"
            )
        self._log_streamlines_speed_scale(
            "COMPLETE",
            f"speed_min=0; speed_max={upper:.9g}; units={scale.units}; caches=8/8.\n"
            + "\n".join(evidence)
            + "\n"
            "NEXT_ACTION | Review and accept the proposed fixed speed scale.",
        )
        return proposal

    def accept_streamlines_speed_scale_proposal(self) -> PhysicalSpeedScale:
        proposal = getattr(self, "_streamlines_speed_scale_proposal", None)
        if proposal is None:
            raise RuntimeError("Collect the final cache speed distribution first.")
        self._streamlines_accepted_speed_scale = proposal.scale
        self._log_streamlines_speed_scale(
            "TEST COMPLETE",
            "One fixed Streamlines physical speed scale accepted.",
        )
        return proposal.scale

    @staticmethod
    def _log_streamlines_speed_scale(event: str, message: str) -> None:
        try:
            import carb
        except ImportError:
            return
        carb.log_warn(
            with_dtrs_yerevan_timestamp(
                f"DTRS STREAMLINES | PHASE_4_4B_SPEED_SCALE | {event}\n{message}"
            )
        )
