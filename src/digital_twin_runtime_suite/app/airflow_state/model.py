# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""Immutable data exchanged by consumer-neutral airflow state transitions."""

from __future__ import annotations

from dataclasses import dataclass

from digital_twin_runtime_suite.app.airflow_dataset import AirflowDataset
from digital_twin_runtime_suite.app.workload_binding.runtime import (
    WorkloadAirflowBinding,
)


@dataclass(frozen=True)
class AirflowResolvedTarget:
    """One semantic workload resolved to its authoritative airflow dataset."""

    workload_mode: str
    binding: WorkloadAirflowBinding
    dataset: AirflowDataset


@dataclass(frozen=True)
class AirflowTransition:
    """A pending generation that only its requesting consumer may terminally end."""

    generation: int
    transition_id: str
    target: AirflowResolvedTarget
    superseded_transition_id: str | None = None


@dataclass(frozen=True)
class AirflowTransitionFailure:
    """Truthful terminal failure that preserves the previously committed target."""

    semantic_workload: str
    requested_airflow_selector: str
    active_airflow_selector: str
    reason: str
    failure_stage: str
    action: str


@dataclass(frozen=True)
class AirflowStateSnapshot:
    """The consumer-neutral committed/pending state at one instant."""

    committed: AirflowResolvedTarget | None
    pending: AirflowTransition | None
    requested_workload: str | None
    failure: AirflowTransitionFailure | None
