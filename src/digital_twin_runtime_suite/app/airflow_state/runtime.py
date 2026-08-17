"""Kit-neutral owner of shared airflow binding, phase, and transition truth."""

from __future__ import annotations

import time
from collections.abc import Callable

from digital_twin_runtime_suite.app.airflow_dataset import (
    AirflowDataset,
    resolve_airflow_dataset_from_registry,
)
from digital_twin_runtime_suite.app.airflow_state.model import (
    AirflowResolvedTarget,
    AirflowStateSnapshot,
    AirflowTransition,
    AirflowTransitionFailure,
)
from digital_twin_runtime_suite.app.airflow_state.temporal import (
    TemporalSampleResolution,
    resolve_manifest_sample,
    temporal_samples_from_airflow_dataset,
)
from digital_twin_runtime_suite.app.workload_binding.runtime import (
    WorkloadAirflowBinding,
    WorkloadBindingRuntime,
)


class AirflowStateRuntime:
    """Own one shared logical airflow state machine for all runtime consumers.

    The registry is provided by composition and is never rediscovered here.
    Consumers may perform their own Kit-specific proof, but only this owner can
    commit or roll back the generic airflow transition that surrounds it.
    """

    def __init__(
        self,
        binding_runtime: WorkloadBindingRuntime,
        registry: tuple[AirflowDataset, ...],
        *,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._binding_runtime = binding_runtime
        self._registry = registry
        self._monotonic = monotonic
        self._phase_started_at = monotonic()
        self._committed: AirflowResolvedTarget | None = None
        self._pending: AirflowTransition | None = None
        self._requested_workload: str | None = None
        self._failure: AirflowTransitionFailure | None = None
        self._generation = 0

    @property
    def snapshot(self) -> AirflowStateSnapshot:
        """Return an immutable view without exposing mutable runtime state."""

        return AirflowStateSnapshot(
            committed=self._committed,
            pending=self._pending,
            requested_workload=self._requested_workload,
            failure=self._failure,
        )

    @property
    def committed(self) -> AirflowResolvedTarget | None:
        """Return the last consumer-proven airflow target, if any."""

        return self._committed

    @property
    def pending(self) -> AirflowTransition | None:
        """Return the only generation still eligible to commit."""

        return self._pending

    @property
    def generation(self) -> int:
        """Return the monotonic transition generation for diagnostics/tests."""

        return self._generation

    @property
    def registry(self) -> tuple[AirflowDataset, ...]:
        """Return the composition-owned registry without rediscovering manifests."""

        return self._registry

    @property
    def failure(self) -> AirflowTransitionFailure | None:
        """Return the latest shared transition failure, if one was terminal."""

        return self._failure

    def rebind_binding_runtime(self, binding_runtime: WorkloadBindingRuntime) -> None:
        """Update the semantic workload source without changing committed airflow."""

        self._binding_runtime = binding_runtime

    def resolve_binding(self, workload_mode: str) -> WorkloadAirflowBinding:
        """Delegate semantic workload interpretation to WorkloadBindingRuntime."""

        return self._binding_runtime.resolve(workload_mode)

    def resolve_current(self) -> AirflowResolvedTarget:
        """Resolve current Telemetry semantics through the cached registry only."""

        binding = self._binding_runtime.resolve_current()
        return self.resolve_target(binding)

    def resolve_target(self, binding: WorkloadAirflowBinding) -> AirflowResolvedTarget:
        """Resolve a binding against the composition-owned authoritative registry."""

        return AirflowResolvedTarget(
            workload_mode=binding.workload_mode,
            binding=binding,
            dataset=resolve_airflow_dataset_from_registry(
                self._registry,
                binding.dataset,
            ),
        )

    def begin(
        self,
        target: AirflowResolvedTarget,
        *,
        force: bool = False,
    ) -> AirflowTransition | None:
        """Make one resolved target pending, superseding an older pending target.

        A request already represented by committed or pending state is a true
        NO_OP unless a consumer has reported that its live runtime diverged.
        ``force`` creates the repair transition needed to reconcile that case.
        """

        self._requested_workload = target.workload_mode
        if self._pending and self._pending.target.binding == target.binding:
            return None
        if not force and self._committed and self._committed.binding == target.binding:
            self._pending = None
            self._failure = None
            return None
        superseded = self._pending.transition_id if self._pending else None
        self._generation += 1
        transition = AirflowTransition(
            generation=self._generation,
            transition_id=f"T{self._generation:04d}",
            target=target,
            superseded_transition_id=superseded,
        )
        self._pending = transition
        self._failure = None
        return transition

    def begin_for_workload(self, workload_mode: str) -> AirflowTransition | None:
        """Resolve one semantic request and make it pending when work is needed."""

        return self.begin(self.resolve_target(self.resolve_binding(workload_mode)))

    def commit(self, transition_id: str) -> bool:
        """Commit only the currently pending generation after consumer proof."""

        if self._pending is None or self._pending.transition_id != transition_id:
            return False
        self._committed = self._pending.target
        self._pending = None
        self._failure = None
        return True

    def commit_target(
        self,
        target: AirflowResolvedTarget,
        *,
        transition_id: str | None = None,
    ) -> bool:
        """Commit a proven target, rejecting stale or mismatched generations."""

        if transition_id is not None:
            if self._pending is None or self._pending.target != target:
                return False
            return self.commit(transition_id)
        if self._pending is not None and self._pending.target != target:
            return False
        self._committed = target
        self._pending = None
        self._failure = None
        return True

    def fail(
        self,
        transition_id: str | None,
        *,
        semantic_workload: str,
        requested_binding: WorkloadAirflowBinding | None,
        reason: str,
        failure_stage: str,
        attached: bool,
    ) -> AirflowTransitionFailure | None:
        """Clear only the active pending generation and retain committed truth."""

        if transition_id is not None and (
            self._pending is None or self._pending.transition_id != transition_id
        ):
            return None
        if transition_id is None and self._pending is not None:
            if requested_binding and self._pending.target.binding != requested_binding:
                return None
        self._pending = None
        active_selector = (
            self._committed.binding.dataset_identity
            if attached and self._committed is not None
            else "DETACHED"
        )
        requested_selector = (
            requested_binding.dataset_identity
            if requested_binding is not None
            else "unresolved"
        )
        failure = AirflowTransitionFailure(
            semantic_workload=semantic_workload,
            requested_airflow_selector=requested_selector,
            active_airflow_selector=active_selector,
            reason=reason,
            failure_stage=failure_stage,
            action=("kept_previous_safe_dataset" if attached else "remained_detached"),
        )
        self._failure = failure
        return failure

    def fail_unreconciled_runtime(
        self,
        transition_id: str,
        *,
        semantic_workload: str,
        requested_binding: WorkloadAirflowBinding,
        reason: str,
    ) -> AirflowTransitionFailure | None:
        """Clear unsafe truth after a consumer mutation cannot be rolled back.

        A failed runtime rollback leaves the live Flow source unknown.  The
        previous committed dataset can no longer be presented as consumer
        truth, so this terminal path deliberately clears it instead.
        """

        if self._pending is None or self._pending.transition_id != transition_id:
            return None
        self._committed = None
        self._pending = None
        failure = AirflowTransitionFailure(
            semantic_workload=semantic_workload,
            requested_airflow_selector=requested_binding.dataset_identity,
            active_airflow_selector="UNRECONCILED",
            reason=reason,
            failure_stage="runtime_reconciliation",
            action="runtime_reconciliation_required",
        )
        self._failure = failure
        return failure

    def is_current(self, transition_id: str, binding: WorkloadAirflowBinding) -> bool:
        """Return whether a consumer still owns the pending generation."""

        return bool(
            self._pending
            and self._pending.transition_id == transition_id
            and self._pending.target.binding == binding
        )

    def phase_seconds(self, *, now: float | None = None) -> float:
        """Return shared logical airflow elapsed time from one monotonic origin."""

        current = self._monotonic() if now is None else now
        return current - self._phase_started_at

    def resolve_phase(
        self,
        dataset: AirflowDataset | None = None,
        *,
        active_sample_index: int | None = None,
        now: float | None = None,
    ) -> TemporalSampleResolution:
        """Resolve exact real-source truth for a dataset at the shared phase."""

        selected = dataset or (self._committed.dataset if self._committed else None)
        if selected is None:
            selected = self.resolve_current().dataset
        return resolve_manifest_sample(
            temporal_samples_from_airflow_dataset(selected),
            sample_interval_seconds=selected.sample_interval_seconds,
            phase_seconds=self.phase_seconds(now=now),
            active_sample_index=active_sample_index,
        )

    def resolve_transition_phase_pair(
        self,
        active_dataset: AirflowDataset,
        target_dataset: AirflowDataset,
        *,
        now: float | None = None,
    ) -> tuple[TemporalSampleResolution, TemporalSampleResolution]:
        """Resolve active and target datasets at one absolute shared-clock instant.

        ``resolve_phase(now=...)`` accepts a monotonic timestamp, not an
        already elapsed phase.  Sampling that timestamp once keeps a live Flow
        retarget on the same normalized phase for both datasets.
        """

        current = self._monotonic() if now is None else now
        return (
            self.resolve_phase(active_dataset, now=current),
            self.resolve_phase(target_dataset, now=current),
        )

    def replace_committed_binding(self, binding: WorkloadAirflowBinding | None) -> None:
        """Compatibility seam for legacy tests; production state remains shared."""

        self._committed = self.resolve_target(binding) if binding else None

    def replace_pending_binding(self, binding: WorkloadAirflowBinding | None) -> None:
        """Compatibility seam that preserves the current generation where possible."""

        if binding is None:
            self._pending = None
            return
        target = self.resolve_target(binding)
        transition_id = (
            self._pending.transition_id
            if self._pending is not None
            else f"T{max(self._generation, 1):04d}"
        )
        generation = int(transition_id[1:])
        self._generation = max(self._generation, generation)
        self._pending = AirflowTransition(generation, transition_id, target)

    def replace_active_transition_id(self, transition_id: str | None) -> None:
        """Compatibility seam for tests that model an in-flight async consumer."""

        if transition_id is None:
            self._pending = None
            return
        if self._pending is None:
            return
        generation = int(transition_id[1:]) if transition_id[1:].isdigit() else 0
        self._generation = max(self._generation, generation)
        self._pending = AirflowTransition(
            generation,
            transition_id,
            self._pending.target,
            self._pending.superseded_transition_id,
        )

    def replace_generation(self, generation: int) -> None:
        """Compatibility seam for tests that seed a known transition generation."""

        self._generation = generation

    def clear_failure(self) -> None:
        """Forget a prior consumer failure after a later successful proof."""

        self._failure = None

    def replace_failure(self, failure: AirflowTransitionFailure | None) -> None:
        """Compatibility seam for legacy diagnostic state restoration in tests."""

        self._failure = failure

    def reset(self) -> None:
        """Clear ownership on detach/reload while retaining no stale generation."""

        self._committed = None
        self._pending = None
        self._requested_workload = None
        self._failure = None
        self._generation = 0
        self._phase_started_at = self._monotonic()
