"""Single-flight plain-data validation for workload-addressable airflow data.

The coordinator owns expensive VTI preflight arbitration for a DTRS session:
background warm-up is sequential, while a manual Attach or attached workload
transition can promote or pre-empt that work.  It intentionally knows nothing
about live Flow construction; its output is only reusable preflight evidence.
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from threading import Event
from typing import Callable

from digital_twin_runtime_suite.app.airflow_dataset import (
    AirflowDataset,
    AirflowDatasetError,
    validate_airflow_dataset_grid,
)
from digital_twin_runtime_suite.app.airflow_validation import (
    preflight as airflow_preflight,
)
from digital_twin_runtime_suite.app.airflow_validation.cache import (
    DatasetValidationSignature,
    PreflightValidationReceipt,
    SessionValidationCache,
    build_dataset_validation_signature,
)
from digital_twin_runtime_suite.app.workload_binding.runtime import (
    WorkloadAirflowBinding,
)

ValidationLog = Callable[[str], None]
PreflightValidator = Callable[
    [tuple, str, Callable[[], bool]],
    tuple[dict[str, object], bool],
]


class BackgroundValidationError(RuntimeError):
    """A requested dataset exhausted its bounded validation attempts."""


@dataclass(frozen=True)
class BackgroundValidationResult:
    """Session-local outcome of one background validation run."""

    validated: int
    failed: int
    cancelled: bool = False
    background_validated: int = 0
    priority_validated: int = 0


@dataclass
class _ValidationJob:
    dataset: AirflowDataset
    attempt: int
    priority: str = "BACKGROUND"
    generation: int = 0
    cancel_requested: Event = field(default_factory=Event)
    finished: asyncio.Future | None = None
    handled: asyncio.Future | None = None

    @property
    def selector(self) -> str:
        return _dataset_identity(self.dataset)


@dataclass(frozen=True)
class _JobResult:
    status: str
    receipt: PreflightValidationReceipt | None = None
    reason: str = ""
    reused: bool = False
    receipt_source: str = "NONE"


class AttachValidationLease:
    """Hold background work while one foreground validation consumer completes.

    The name is retained for the Stage-6 Attach API, but the same lease also
    protects an attached workload transition.  Releasing it is the explicit
    hand-off that lets lower-priority warm-up resume.
    """

    def __init__(
        self,
        coordinator: "BackgroundAirflowValidationCoordinator",
        receipt: PreflightValidationReceipt,
    ):
        self.receipt = receipt
        self._coordinator = coordinator
        self._released = False

    def release(self) -> None:
        """Resume the background queue after the complete Attach attempt."""

        if self._released:
            return
        self._released = True
        self._coordinator._release_attach_priority()


class BackgroundAirflowValidationCoordinator:
    """Own the only expensive VTI preflight worker for this DTRS session.

    Jobs are deliberately single-flight: this prevents competing VTK, disk and
    memory work.  Cancellation is cooperative, and a pre-empted background job
    is requeued with its attempt number preserved rather than treated as a
    dataset failure.
    """

    MAX_ATTEMPTS = 3

    def __init__(
        self,
        datasets: tuple[AirflowDataset, ...],
        current_binding: WorkloadAirflowBinding,
        velocity_field_name: str,
        validation_cache: SessionValidationCache,
        *,
        flow_attached: Callable[[], bool] | None = None,
        signature_builder: Callable[
            [AirflowDataset, str], DatasetValidationSignature
        ] = build_dataset_validation_signature,
        preflight_validator: PreflightValidator | None = None,
    ):
        self._datasets = self._ordered_datasets(datasets, current_binding)
        self._datasets_by_selector = {
            _dataset_identity(dataset): dataset for dataset in self._datasets
        }
        self._current_binding = current_binding
        self._velocity_field_name = velocity_field_name
        self._validation_cache = validation_cache
        self._flow_attached = flow_attached or (lambda: False)
        self._signature_builder = signature_builder
        self._preflight_validator = (
            preflight_validator or self._validate_temporal_vti_contract
        )
        self._shutdown_requested = Event()
        self._queue: deque[_ValidationJob] = deque()
        self._active_job: _ValidationJob | None = None
        self._background_gate: asyncio.Event | None = None
        self._background_running = False
        self._attach_holds = 0
        self._priority_validated: set[str] = set()
        self._generation = 0
        self._log: ValidationLog = lambda _message: None

    @staticmethod
    def _ordered_datasets(
        datasets: tuple[AirflowDataset, ...],
        current_binding: WorkloadAirflowBinding,
    ) -> tuple[AirflowDataset, ...]:
        current_identity = current_binding.dataset_identity
        selected = next(
            (
                dataset
                for dataset in datasets
                if _dataset_identity(dataset) == current_identity
            ),
            None,
        )
        if selected is None:
            raise AirflowDatasetError(
                "Current workload airflow dataset is absent from the registry: "
                f"{current_identity}"
            )
        return (selected, *(dataset for dataset in datasets if dataset is not selected))

    def cancel(self) -> None:
        """Stop active plain-data work cooperatively and suppress stale receipts."""

        self._shutdown_requested.set()
        if self._active_job:
            self._active_job.cancel_requested.set()
        if self._background_gate:
            self._background_gate.set()

    async def run(self, log: ValidationLog) -> BackgroundValidationResult:
        """Run the startup queue; Attach requests may pause it through a lease."""

        self._log = log
        self._background_gate = asyncio.Event()
        self._background_gate.set()
        self._queue = deque(_ValidationJob(dataset, 1) for dataset in self._datasets)
        self._background_running = True
        validated: set[str] = set()
        reused: set[str] = set()
        terminal_failures: dict[str, str] = {}
        self._log(
            "\n".join(
                (
                    "DTRS AIRFLOW BACKGROUND VALIDATION | START",
                    f"Current workload: {self._current_binding.workload_mode}",
                    "Order: "
                    + ", ".join(
                        _dataset_identity(dataset) for dataset in self._datasets
                    ),
                    "Mode: sequential",
                )
            )
        )
        try:
            while self._queue:
                if self._shutdown_requested.is_set():
                    return BackgroundValidationResult(
                        validated=len(validated | self._priority_validated),
                        failed=len(terminal_failures),
                        cancelled=True,
                        background_validated=len(validated),
                        priority_validated=len(self._priority_validated),
                    )
                await self._background_gate.wait()
                if self._shutdown_requested.is_set():
                    continue
                job = self._queue.popleft()
                result = await self._run_job(job)
                if result.status == "CANCELLED":
                    if self._shutdown_requested.is_set():
                        return BackgroundValidationResult(
                            validated=len(validated | self._priority_validated),
                            failed=len(terminal_failures),
                            cancelled=True,
                            background_validated=len(validated),
                            priority_validated=len(self._priority_validated),
                        )
                    self._queue.appendleft(_ValidationJob(job.dataset, job.attempt))
                    self._log(
                        "DTRS AIRFLOW VALIDATION | REQUEUED "
                        f"| selector={job.selector} | attempt_preserved=True"
                    )
                elif result.status == "PASS":
                    if result.reused:
                        reused.add(job.selector)
                    else:
                        validated.add(job.selector)
                        self._log(
                            "DTRS AIRFLOW BACKGROUND VALIDATION | PASS "
                            f"| selector={job.selector} "
                            f"| attempt={job.attempt}/{self.MAX_ATTEMPTS} "
                            f"| receipt={result.receipt.signature.compact_digest}"
                        )
                elif job.priority == "ATTACH":
                    pass
                elif job.attempt == self.MAX_ATTEMPTS:
                    terminal_failures[job.selector] = result.reason
                    self._log(
                        "DTRS AIRFLOW BACKGROUND VALIDATION | TERMINAL FAILURE "
                        f"| selector={job.selector} "
                        f"| attempts={job.attempt}/{self.MAX_ATTEMPTS} "
                        f"| reason={result.reason}"
                    )
                else:
                    self._queue.append(_ValidationJob(job.dataset, job.attempt + 1))
                    self._log(
                        "DTRS AIRFLOW BACKGROUND VALIDATION | FAILED "
                        f"| selector={job.selector} "
                        f"| attempt={job.attempt}/{self.MAX_ATTEMPTS} "
                        f"| reason={result.reason} | queued_for_retry=True"
                    )
                if job.handled and not job.handled.done():
                    job.handled.set_result(None)
        finally:
            self._background_running = False
        self._log(
            "\n".join(
                (
                    "DTRS AIRFLOW BACKGROUND VALIDATION | COMPLETE",
                    f"Background validated: {len(validated)}",
                    f"Priority validated: {len(self._priority_validated)}",
                    f"Total validated: {len(validated | self._priority_validated)}",
                    f"Reused: {len(reused)}",
                    f"Failed: {len(terminal_failures)}",
                    f"Flow attached: {self._flow_attached()}",
                )
            )
        )
        return BackgroundValidationResult(
            validated=len(validated | self._priority_validated),
            failed=len(terminal_failures),
            background_validated=len(validated),
            priority_validated=len(self._priority_validated),
        )

    async def acquire_for_attach(
        self,
        binding: WorkloadAirflowBinding,
    ) -> AttachValidationLease:
        """Validate or reuse one selector while pausing lower-priority work."""

        return await self._acquire_foreground(binding, "manual_attach")

    async def acquire_for_transition(
        self,
        binding: WorkloadAirflowBinding,
    ) -> AttachValidationLease:
        """Validate one attached-transition target through the same single flight."""

        return await self._acquire_foreground(binding, "workload_transition")

    async def _acquire_foreground(
        self,
        binding: WorkloadAirflowBinding,
        reason: str,
    ) -> AttachValidationLease:
        """Share one foreground validation path without duplicating VTI work."""

        selector = binding.dataset_identity
        dataset = self._datasets_by_selector.get(selector)
        if dataset is None:
            raise BackgroundValidationError(
                f"Requested airflow dataset is absent from the registry: {selector}"
            )
        self._attach_holds += 1
        if self._background_gate:
            self._background_gate.clear()
        try:
            active = self._active_job
            if active and active.selector == selector:
                active.priority = "ATTACH"
                self._log(
                    "DTRS AIRFLOW VALIDATION | PROMOTED "
                    f"| selector={selector} | reason={reason}"
                )
                result = await active.finished
                if active.handled:
                    await active.handled
                receipt = await self._receipt_after_attach_result(
                    dataset, active, result
                )
            else:
                if active:
                    self._log(
                        "DTRS AIRFLOW VALIDATION | PREEMPT "
                        f"| active={active.selector} | requested={selector}"
                    )
                    active.cancel_requested.set()
                    await active.finished
                    if active.handled:
                        await active.handled
                receipt = await self._validate_with_attach_priority(dataset)
            return AttachValidationLease(self, receipt)
        except Exception:
            self._release_attach_priority()
            raise

    async def _receipt_after_attach_result(
        self,
        dataset: AirflowDataset,
        job: _ValidationJob,
        result: _JobResult,
    ) -> PreflightValidationReceipt:
        if result.status == "PASS":
            return result.receipt
        if result.status == "CANCELLED":
            return await self._validate_with_attach_priority(dataset, job.attempt)
        return await self._validate_with_attach_priority(dataset, job.attempt + 1)

    async def _validate_with_attach_priority(
        self,
        dataset: AirflowDataset,
        attempt: int | None = None,
    ) -> PreflightValidationReceipt:
        queued = self._take_queued_job(_dataset_identity(dataset))
        next_attempt = attempt or (queued.attempt if queued else 1)
        while next_attempt <= self.MAX_ATTEMPTS:
            job = _ValidationJob(dataset, next_attempt, priority="ATTACH")
            result = await self._run_job(job)
            if result.status == "PASS":
                if not result.reused:
                    self._priority_validated.add(job.selector)
                    self._log(
                        "DTRS AIRFLOW VALIDATION | PRIORITY PASS "
                        f"| selector={job.selector} "
                        f"| receipt={result.receipt.signature.compact_digest}"
                    )
                return result.receipt
            if result.status == "CANCELLED":
                raise BackgroundValidationError(
                    f"Attach validation cancelled for {job.selector}."
                )
            if next_attempt == self.MAX_ATTEMPTS:
                raise BackgroundValidationError(
                    f"Airflow validation failed for {job.selector} after "
                    f"{next_attempt}/{self.MAX_ATTEMPTS} attempts: {result.reason}"
                )
            self._log(
                "DTRS AIRFLOW VALIDATION | PRIORITY FAILED "
                f"| selector={job.selector} "
                f"| attempt={next_attempt}/{self.MAX_ATTEMPTS} "
                f"| reason={result.reason} | retrying=True"
            )
            next_attempt += 1
        raise AssertionError("Unreachable foreground validation state.")

    async def _run_job(self, job: _ValidationJob) -> _JobResult:
        """Run one job once, publishing only its own completion result.

        A cancelled job never reaches ``_validate_dataset``'s cache store.  The
        generation is retained for diagnostics/ownership correlation if future
        scheduling becomes more asynchronous, while the current single-flight
        worker guarantees that only ``_active_job`` can publish this result.
        """
        self._generation += 1
        job.generation = self._generation
        loop = asyncio.get_running_loop()
        job.finished = loop.create_future()
        job.handled = loop.create_future()
        self._active_job = job
        try:
            signature = self._signature_builder(job.dataset, self._velocity_field_name)
            lookup = self._validation_cache.lookup(signature)
            cached_receipt = lookup.preflight
            if cached_receipt:
                result = _JobResult(
                    "PASS",
                    receipt=cached_receipt,
                    reused=True,
                    receipt_source=lookup.receipt_source,
                )
                prefix = (
                    "DTRS AIRFLOW BACKGROUND VALIDATION"
                    if job.priority == "BACKGROUND"
                    else "DTRS AIRFLOW VALIDATION"
                )
                self._log(
                    f"{prefix} | REUSED | selector={job.selector} "
                    f"| receipt_source={lookup.receipt_source} "
                    f"| current_cache_location={lookup.cache_location} "
                    "| validation_executed=False "
                    f"| receipt={cached_receipt.signature.compact_digest}"
                )
            else:
                self._log(
                    "DTRS AIRFLOW BACKGROUND VALIDATION | BEGIN "
                    f"| selector={job.selector} "
                    f"| attempt={job.attempt}/{self.MAX_ATTEMPTS}"
                )
                receipt, reused, receipt_source = await self._validate_dataset(
                    job.dataset, job.cancel_requested
                )
                result = _JobResult(
                    "PASS",
                    receipt=receipt,
                    reused=reused,
                    receipt_source=receipt_source,
                )
                self._log(
                    "DTRS AIRFLOW VALIDATION | VALIDATED "
                    f"| selector={job.selector} | receipt_source=FRESH "
                    "| validation_executed=True "
                    f"| receipt={receipt.signature.compact_digest}"
                )
        except airflow_preflight.TemporalVtiValidationCancelled:
            result = _JobResult("CANCELLED")
        except Exception as error:
            result = _JobResult("FAILED", reason=str(error))
        finally:
            if self._active_job is job:
                self._active_job = None
        job.finished.set_result(result)
        return result

    async def _validate_dataset(
        self,
        dataset: AirflowDataset,
        cancel_requested: Event,
    ) -> tuple[PreflightValidationReceipt, bool, str]:
        signature = self._signature_builder(dataset, self._velocity_field_name)
        lookup = self._validation_cache.lookup(signature)
        if lookup.preflight:
            return lookup.preflight, True, lookup.receipt_source
        self._validation_cache.record_expensive_preflight_call()
        metadata, grid_match = await asyncio.to_thread(
            self._preflight_validator,
            dataset.velocity_vti_sequence_paths,
            self._velocity_field_name,
            cancel_requested.is_set,
        )
        if cancel_requested.is_set() or self._shutdown_requested.is_set():
            raise airflow_preflight.TemporalVtiValidationCancelled(
                "VTI preflight cancelled"
            )
        validate_airflow_dataset_grid(dataset, tuple(metadata["dimensions"]))
        metadata = {
            **metadata,
            "velocity_field_name": self._velocity_field_name,
            "velocity_field_association": "point_data",
        }
        return (
            self._validation_cache.store_preflight(signature, metadata, grid_match),
            False,
            "FRESH",
        )

    def _take_queued_job(self, selector: str) -> _ValidationJob | None:
        for index, job in enumerate(self._queue):
            if job.selector == selector:
                del self._queue[index]
                return job
        return None

    def _release_attach_priority(self) -> None:
        self._attach_holds = max(0, self._attach_holds - 1)
        if self._attach_holds or self._shutdown_requested.is_set():
            return
        if self._background_gate:
            self._background_gate.set()
        if self._queue:
            self._log(
                "DTRS AIRFLOW BACKGROUND VALIDATION | RESUME "
                f"| next={self._queue[0].selector}"
            )

    @staticmethod
    def _validate_temporal_vti_contract(
        velocity_paths: tuple,
        velocity_field_name: str,
        cancel_requested: Callable[[], bool],
    ) -> tuple[dict[str, object], bool]:
        return airflow_preflight.validate_kit_cae_temporal_vti_contract(
            velocity_paths,
            velocity_field_name,
            cancel_requested=cancel_requested,
        )


def _dataset_identity(dataset: AirflowDataset) -> str:
    return f"{dataset.manifest.scope}/{dataset.manifest.state}"
