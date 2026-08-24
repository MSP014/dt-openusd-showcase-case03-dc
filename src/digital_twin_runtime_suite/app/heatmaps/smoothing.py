# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""Pure time-based smoothing for dynamic Heatmap group temperatures."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

HEATMAP_PRESENTATION_CADENCE_HZ = 2
HEATMAP_PRESENTATION_PERIOD_SECONDS = 1.0 / HEATMAP_PRESENTATION_CADENCE_HZ
HEATMAP_PRESENTATION_TRANSITION_DURATION_SECONDS = 2.0


@dataclass
class _Transition:
    """Mutable interpolation state retained for one material presentation group."""

    start_celsius: float
    target_celsius: float
    started_at: float
    last_emitted_celsius: float


@dataclass
class _RetargetEvidence:
    """Mutable evidence for one latest-telemetry-wins retarget."""

    displayed_before_celsius: float
    target_celsius: float
    first_displayed_after_celsius: float | None = None
    maximum_step_celsius: float = 0.0


@dataclass(frozen=True)
class HeatmapRetargetEvidence:
    """Compact proof that a material group continued smoothly after retargeting."""

    material_group_key: str
    displayed_before_celsius: float
    target_celsius: float
    first_displayed_after_celsius: float | None
    maximum_step_celsius: float
    continuous: bool


class HeatmapPresentationSmoother:
    """Interpolate latest telemetry targets without queuing stale snapshots."""

    def __init__(
        self,
        *,
        transition_duration_seconds: float = (
            HEATMAP_PRESENTATION_TRANSITION_DURATION_SECONDS
        ),
    ) -> None:
        if transition_duration_seconds <= 0.0:
            raise ValueError("Heatmap transition duration must be positive.")
        self._transition_duration_seconds = transition_duration_seconds
        self._transitions: dict[str, _Transition] = {}
        self._retarget_evidence: dict[str, _RetargetEvidence] = {}

    @property
    def group_count(self) -> int:
        """Return the active dynamic material-group count."""

        return len(self._transitions)

    @property
    def group_keys(self) -> tuple[str, ...]:
        """Expose stable group membership for structural-change detection."""

        return tuple(sorted(self._transitions))

    @property
    def transition_duration_seconds(self) -> float:
        """Return the fixed duration shared by all presentation cadences."""

        return self._transition_duration_seconds

    @property
    def retarget_evidence(self) -> tuple[HeatmapRetargetEvidence, ...]:
        """Return one compact latest-retarget record per active material group."""

        return tuple(
            HeatmapRetargetEvidence(
                material_group_key=key,
                displayed_before_celsius=evidence.displayed_before_celsius,
                target_celsius=evidence.target_celsius,
                first_displayed_after_celsius=(evidence.first_displayed_after_celsius),
                maximum_step_celsius=evidence.maximum_step_celsius,
                continuous=_is_continuous(evidence),
            )
            for key, evidence in sorted(self._retarget_evidence.items())
        )

    def reset(self, values: Mapping[str, float], *, now: float) -> None:
        """Align smoothing state with an immediate structural presentation apply."""

        self._transitions = {
            key: _Transition(value, value, now, value)
            for key, value in sorted(values.items())
        }
        self.clear_retarget_evidence()

    def clear_retarget_evidence(self) -> None:
        """Start a new aggregate evidence window without affecting presentation."""

        self._retarget_evidence.clear()

    def set_targets(self, values: Mapping[str, float], *, now: float) -> int:
        """Retarget changed groups from their current display value at *now*."""

        changed = 0
        desired_keys = set(values)
        for key in tuple(self._transitions):
            if key not in desired_keys:
                del self._transitions[key]
                self._retarget_evidence.pop(key, None)
        for key, target in sorted(values.items()):
            transition = self._transitions.get(key)
            if transition is None:
                self._transitions[key] = _Transition(target, target, now, target)
                changed += 1
                continue
            if transition.target_celsius == target:
                continue
            # The material can only show the last scheduler-written value.
            # Restarting from a theoretical between-tick value would introduce
            # a visible jump when newer telemetry supersedes the transition.
            current = transition.last_emitted_celsius
            transition.start_celsius = current
            transition.target_celsius = target
            transition.started_at = now
            transition.last_emitted_celsius = current
            self._retarget_evidence[key] = _RetargetEvidence(
                displayed_before_celsius=current,
                target_celsius=target,
            )
            changed += 1
        return changed

    def tick(self, *, now: float) -> Mapping[str, float]:
        """Return only group values whose displayed temperature has changed."""

        changed = {}
        for key, transition in sorted(self._transitions.items()):
            value = self._displayed_value(transition, now)
            if value == transition.last_emitted_celsius:
                continue
            previous_value = transition.last_emitted_celsius
            transition.last_emitted_celsius = value
            evidence = self._retarget_evidence.get(key)
            if evidence is not None:
                if evidence.first_displayed_after_celsius is None:
                    evidence.first_displayed_after_celsius = value
                evidence.maximum_step_celsius = max(
                    evidence.maximum_step_celsius,
                    abs(value - previous_value),
                )
            changed[key] = value
        return MappingProxyType(changed)

    def _displayed_value(self, transition: _Transition, now: float) -> float:
        elapsed = max(0.0, now - transition.started_at)
        progress = min(1.0, elapsed / self._transition_duration_seconds)
        return transition.start_celsius + (
            (transition.target_celsius - transition.start_celsius) * progress
        )


def _is_continuous(evidence: _RetargetEvidence) -> bool:
    """Reject a first emitted value that lies outside the retarget segment."""

    first = evidence.first_displayed_after_celsius
    if first is None:
        return True
    lower = min(evidence.displayed_before_celsius, evidence.target_celsius)
    upper = max(evidence.displayed_before_celsius, evidence.target_celsius)
    return lower <= first <= upper
