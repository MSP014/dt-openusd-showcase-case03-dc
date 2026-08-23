"""Runtime coordination between semantic workload and authored airflow data."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from digital_twin_runtime_suite.app.airflow_dataset import AirflowDatasetSelector
from digital_twin_runtime_suite.app.config import SimulationCacheConfig
from digital_twin_runtime_suite.app.diagnostics import with_dtrs_local_timestamp
from digital_twin_runtime_suite.app.status_log import format_dtrs_diagnostic_block


@dataclass(frozen=True)
class WorkloadAirflowBinding:
    """One resolved semantic workload-to-airflow dataset binding."""

    workload_mode: str
    dataset: AirflowDatasetSelector

    @property
    def dataset_identity(self) -> str:
        """Return the manifest identity without exposing filesystem layout."""

        return f"{self.dataset.scope}/{self.dataset.state}"

    def format_mapping_log(self) -> str:
        """Return the diagnostic without implying a Flow lifecycle change."""

        return format_dtrs_diagnostic_block(
            owner="WORKLOAD CACHE",
            process="MAPPING",
            state="RESOLVED",
            details={
                "workload": self.workload_mode,
                "dataset": self.dataset_identity,
            },
            append_local_timestamp=with_dtrs_local_timestamp,
        )


class WorkloadBindingRuntime:
    """Resolve Simulation Cache configuration for the current Telemetry workload.

    This is the boundary between telemetry's semantic vocabulary and authored
    airflow identities.  It neither owns telemetry state nor inspects/manages
    Flow, Kit-CAE, or filesystem paths; callers resolve a binding at the moment
    they need an airflow selector.
    """

    def __init__(
        self,
        simulation_cache: SimulationCacheConfig,
        workload_source: Callable[[], str] | None = None,
    ):
        self._simulation_cache = simulation_cache
        self._workload_source = workload_source

    def resolve(self, workload_mode: str) -> WorkloadAirflowBinding:
        """Resolve one workload without attaching or changing Flow."""

        return WorkloadAirflowBinding(
            workload_mode=workload_mode,
            dataset=self._simulation_cache.airflow_dataset_selector_for_workload(
                workload_mode
            ),
        )

    def resolve_current(self) -> WorkloadAirflowBinding:
        """Resolve the current Telemetry workload through the configured source."""

        if self._workload_source is None:
            raise RuntimeError(
                "No current workload source is bound to Simulation Cache."
            )
        return self.resolve(self._workload_source())
