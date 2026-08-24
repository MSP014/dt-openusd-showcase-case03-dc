# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""Background orchestration for fixed-scale calibration from final caches."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable

from digital_twin_runtime_suite.app.streamlines.presentation import PhysicalSpeedScale
from digital_twin_runtime_suite.app.streamlines.profile import StreamlinesProfileId
from digital_twin_runtime_suite.app.streamlines.speed_distribution import (
    SpeedDistribution,
    SpeedScaleCoverage,
    fixed_scale_coverage_from_cache_evidence,
    speed_distribution_from_cache_evidence,
    volume_scale_from_cache_evidence,
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
    """Calibrate from compact Volume build evidence without opening cache USD."""

    async def collect_streamlines_speed_scale_proposal(
        self,
        status_callback: StatusCallback | None = None,
        *,
        ready_entries=(),
    ) -> StreamlinesSpeedScaleProposal:
        """Choose one shared p05/p95 scale from four Volume cache summaries."""

        entries = tuple(ready_entries)
        if len(entries) != 8 or not all(entry.valid for entry in entries):
            raise RuntimeError(
                "Eight readiness-approved production caches are required."
            )
        volume_entries = tuple(
            entry
            for entry in entries
            if entry.entry.profile_id == StreamlinesProfileId.VOLUME_COVERAGE.value
        )
        if len(volume_entries) != 4 or any(
            entry.speed_evidence is None for entry in volume_entries
        ):
            raise RuntimeError(
                "Four Volume Coverage cache speed-evidence records are required."
            )
        for entry in volume_entries:
            if status_callback:
                status_callback(
                    f"Volume speed evidence: {entry.entry.workload}/"
                    f"{StreamlinesProfileId.VOLUME_COVERAGE.value}."
                )
        evidence_by_workload = {
            entry.entry.workload: entry.speed_evidence for entry in volume_entries
        }
        scale_minimum, scale_maximum = volume_scale_from_cache_evidence(
            tuple(evidence_by_workload.values())
        )
        scale = PhysicalSpeedScale(
            scale_minimum,
            scale_maximum,
            "source velocity units",
        )
        final = []
        for entry in volume_entries:
            evidence = entry.speed_evidence
            if evidence is None:
                raise RuntimeError(
                    "Persisted Volume Coverage cache speed evidence is required."
                )
            coverage = fixed_scale_coverage_from_cache_evidence(
                evidence,
                minimum=scale.minimum,
                maximum=scale.maximum,
            )
            final.append(
                StreamlinesSpeedDistributionReceipt(
                    entry.entry.workload,
                    entry.entry.dataset_identity,
                    StreamlinesProfileId.VOLUME_COVERAGE,
                    speed_distribution_from_cache_evidence(evidence),
                    coverage,
                )
            )
        proposal = StreamlinesSpeedScaleProposal(
            scale,
            tuple(final),
        )
        self._streamlines_speed_scale_proposal = proposal
        self._streamlines_accepted_speed_scale = proposal.scale
        save_presentation = getattr(
            self,
            "save_streamlines_presentation_override",
            None,
        )
        if save_presentation is not None:
            save_presentation(
                replace(
                    self.config.streamlines_presentation,
                    speed_min=proposal.scale.minimum,
                    speed_max=proposal.scale.maximum,
                    speed_units=proposal.scale.units,
                )
            )
        return proposal

    def accept_streamlines_speed_scale_proposal(self) -> PhysicalSpeedScale:
        proposal = getattr(self, "_streamlines_speed_scale_proposal", None)
        if proposal is None:
            raise RuntimeError("Collect the final cache speed distribution first.")
        self._streamlines_accepted_speed_scale = proposal.scale
        return proposal.scale
