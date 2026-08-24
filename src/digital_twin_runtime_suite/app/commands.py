# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""Runtime commands for Digital Twin Runtime Suite."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from threading import Event, Lock
from typing import Callable

# isort: off
from digital_twin_runtime_suite.app.config import (
    RuntimeConfig,
)
from digital_twin_runtime_suite.app.front_panel_indicators import (
    front_panel_indicator_state,
)
from digital_twin_runtime_suite.app.flow.performance import (
    FlowPerformanceSample,
)
from digital_twin_runtime_suite.app.airflow_validation.cache import (
    SessionValidationCache,
    build_dataset_validation_signature,
)
from digital_twin_runtime_suite.app.airflow_validation.family import (
    AirflowDatasetFamilyCompatibilityError,
    validate_airflow_dataset_family,
    validate_airflow_dataset_family_compatibility,
)
from digital_twin_runtime_suite.app.status_log import format_dtrs_diagnostic_content
from digital_twin_runtime_suite.app.flow.progress import TemporalProofProgress
from digital_twin_runtime_suite.app.flow.runtime import (
    FlowRuntimeMixin,
    SimulationCacheResult,
    VtiReceiptConsumerCheck,
)
from digital_twin_runtime_suite.app.flow.quality_runtime import (
    FlowQualityRuntimeMixin,
)
from digital_twin_runtime_suite.app.flow.workload_transition import (
    AttachedWorkloadTransitionMixin,
)
from digital_twin_runtime_suite.app.heatmaps.runtime import HeatmapRuntimeMixin
from digital_twin_runtime_suite.app.operator_settings.runtime import (
    OperatorSettingsRuntimeMixin,
)
from digital_twin_runtime_suite.app.review.runtime import ReviewRuntimeMixin
from digital_twin_runtime_suite.app.smoke.runtime import SmokeRuntimeMixin
from digital_twin_runtime_suite.app.streamlines.runtime import (
    StreamlinesRuntimeMixin,
)
from digital_twin_runtime_suite.app.telemetry_presentation.runtime import (
    TelemetryPresentationRuntimeMixin,
)
from digital_twin_runtime_suite.app.visualization_mode import (
    VisualizationMode,
    VisualizationModeRuntimeMixin,
)
from digital_twin_runtime_suite.app.xray import XRayRuntimeMixin, XRayTargetState
from digital_twin_runtime_suite.app.workload_binding import (
    AttachValidationLease,
    BackgroundAirflowValidationCoordinator,
    WorkloadAirflowBinding,
    WorkloadBindingRuntime,
)
from digital_twin_runtime_suite.app.airflow_dataset import (
    AirflowDataset,
    AirflowDatasetError,
    discover_airflow_dataset_registry,
)
from digital_twin_runtime_suite.app.airflow_state.model import AirflowTransitionFailure
from digital_twin_runtime_suite.app.airflow_state.runtime import AirflowStateRuntime
from digital_twin_runtime_suite.app.chassis.runtime import ChassisRuntimeMixin
from digital_twin_runtime_suite.app.simulation_cache import (
    SimulationCacheContract,
    run_simulation_cache_preflight,
)
from digital_twin_runtime_suite.app.telemetry.model import WORKLOAD_MODES
from digital_twin_runtime_suite.app.validation_receipts import (
    ValidationReceiptStore,
)

# isort: on

StatusCallback = Callable[[str], None]


@dataclass(frozen=True)
class LoadResult:
    """Result of a runtime stage-load command."""

    success: bool
    message: str
    stage_path: Path
    root_identifier: str = ""


@dataclass(frozen=True)
class LightingResult:
    """Result of applying runtime review lighting."""

    success: bool
    message: str
    hdri_path: Path


@dataclass(frozen=True)
class NormalMapScaleResult:
    """Result of applying the temporary renderer-facing normal-map scale."""

    success: bool
    message: str
    texture_count: int = 0


@dataclass(frozen=True)
class FacePanelApplyResult:
    """Result of preparing or applying the runtime front-panel hinge."""

    success: bool
    message: str
    start_angle: float = 0.0
    target_angle: float = 0.0
    rotate_op: object | None = None


class RuntimeController(
    OperatorSettingsRuntimeMixin,
    ReviewRuntimeMixin,
    ChassisRuntimeMixin,
    TelemetryPresentationRuntimeMixin,
    HeatmapRuntimeMixin,
    VisualizationModeRuntimeMixin,
    StreamlinesRuntimeMixin,
    FlowRuntimeMixin,
    FlowQualityRuntimeMixin,
    AttachedWorkloadTransitionMixin,
    SmokeRuntimeMixin,
    XRayRuntimeMixin,
):
    """Coordinate config-backed application commands for the DTRS viewer.

    The controller remains the public command facade and application-lifecycle
    owner.  X-Ray implementation is composed from ``app.xray``; this class
    retains its established UI-facing command API while Flow, telemetry, and
    X-Ray responsibilities stay in their dedicated runtime modules.
    """

    FLOW_PERFORMANCE_SAMPLE_INTERVAL_SECONDS = 0.5
    FLOW_PERFORMANCE_LOG_INTERVAL_SECONDS = 30.0
    FLOW_DETACH_SETTLE_UPDATE_COUNT = 3
    FLOW_DETACH_OPERATOR_QUIESCE_SECONDS = 0.75
    FLOW_DETACH_OPERATOR_QUIESCE_TIMEOUT_SECONDS = 5.0

    def __init__(self, config_path: Path | str):
        self._config_path = Path(config_path)
        # RuntimeController owns application-lifetime state because stage,
        # config, and extension cleanup all converge here.  The X-Ray mixin
        # owns the behaviour that consumes it; retaining these fields avoids
        # inventing cooperative mixin constructors for a refactor-only pass.
        # Snapshots contain only a previous Session Layer material-binding
        # property spec, never prim or stage references.  They make X-Ray an
        # overlay rather than an owner of somebody else's Session opinion.
        self._xray_session_binding_layer_id: str | None = None
        self._xray_session_binding_snapshots: dict[str, object] = {}
        from digital_twin_runtime_suite.app.heatmaps.runtime import (
            initialise_heatmap_runtime,
        )

        initialise_heatmap_runtime(self, self._config_path)
        self._xray_baseline_composed_bindings: dict[str, str] = {}
        self._xray_last_lifecycle_diagnostics: list[dict[str, object]] = []
        self._xray_target_state = XRayTargetState()
        self._front_panel_indicator_last_snapshot = None
        self._front_panel_indicator_last_state = None
        self._xray_material_active = False
        self.config = RuntimeConfig.load(self._config_path)
        self._validation_receipt_store = ValidationReceiptStore(
            ValidationReceiptStore.default_path(self.config.repo_root)
        )
        self._workload_source: Callable[[], str] | None = None
        self._airflow_state = self._create_airflow_state()
        self._flow_last_temporal_proof_selector: str | None = None
        self._airflow_validation_coordinator: (
            BackgroundAirflowValidationCoordinator | None
        ) = None
        self._airflow_dataset_family_compatible: bool | None = None
        self._airflow_dataset_family_failure: str | None = None
        self._simulation_cache_contract: SimulationCacheContract | None = None
        self._simulation_cache_time_code: int | None = None
        self._flow_airflow_simulate_path: str | None = None
        self._flow_base_velocity_scale: float | None = None
        self._flow_world_bounds: (
            tuple[tuple[float, float, float], tuple[float, float, float]] | None
        ) = None
        self._flow_density_cell_size: float | None = None
        self._flow_intake_tracer_radius_to_cell: float | None = None
        self._flow_vti_spacing: tuple[float, float, float] | None = None
        self._flow_voxel_max_resolution: int | None = None
        self._flow_lifecycle_state = "DETACHED"
        self._smoke_presentation_visible = True
        self._streamlines_cached_presentation_visible = False
        self.reset_visualization_mode_state()
        self.reset_streamlines_cache_validation_receipts()
        self.reset_streamlines_runtime_state()
        self._flow_attach_cancel_event: Event | None = None
        self._flow_kit_cae_operator_lock = Lock()
        self._flow_kit_cae_active_operator_paths: set[str] = set()
        self._flow_kit_cae_operator_begin_counts: dict[str, int] = {}
        self._flow_kit_cae_operator_completion_counts: dict[str, int] = {}
        self._flow_kit_cae_operator_completion_success: dict[str, bool] = {}
        self._flow_kit_cae_operator_completion_success_by_count: dict[
            str, dict[int, bool]
        ] = {}
        self._flow_kit_cae_operator_completion_begin_counts: dict[
            str, dict[int, int]
        ] = {}
        self._flow_kit_cae_operator_subscriptions: tuple[object, ...] = ()
        self._flow_temporal_asset_hashes: dict[Path, str] = {}
        self._flow_temporal_records: list[dict[str, object]] = []
        self._flow_temporal_failure: dict[str, str] | None = None
        self._flow_runtime_mutation_context: dict[str, object] | None = None
        self._flow_temporal_end_time_code: float | None = None
        self._flow_temporal_sample_time_codes: tuple[float, ...] = ()
        self._flow_temporal_proof_task: asyncio.Task | None = None
        self._flow_temporal_proof_generation = 0
        self._flow_temporal_progress = TemporalProofProgress()
        self._flow_last_vti_receipt_consumer_check = VtiReceiptConsumerCheck()
        self._flow_validation_cache = SessionValidationCache(
            persisted_store=self._validation_receipt_store,
            reuse_persisted=(
                self.config.validation_receipts.reuse_verified_vti_receipts
            ),
        )
        self._flow_performance_task: asyncio.Task | None = None
        self._flow_performance_session_id = 0
        self._flow_performance_attached_at: float | None = None
        self._flow_performance_samples: list[FlowPerformanceSample] = []
        self._flow_performance_camera_bookmark = "Unspecified"
        self._front_panel_indicator_state_key: (
            tuple[int, bool, bool, bool, bool] | None
        ) = None

    @staticmethod
    def _new_load_result(*args, **kwargs) -> LoadResult:
        """Build the facade-owned stage-load result for review commands."""

        return LoadResult(*args, **kwargs)

    @staticmethod
    def _new_lighting_result(*args, **kwargs) -> LightingResult:
        """Build the facade-owned lighting result for review commands."""

        return LightingResult(*args, **kwargs)

    @staticmethod
    def _new_normal_map_scale_result(*args, **kwargs) -> NormalMapScaleResult:
        """Build the facade-owned normal-map result for review commands."""

        return NormalMapScaleResult(*args, **kwargs)

    @staticmethod
    def _new_face_panel_apply_result(*args, **kwargs) -> FacePanelApplyResult:
        """Build the facade-owned face-panel result for chassis commands."""

        return FacePanelApplyResult(*args, **kwargs)

    @staticmethod
    def _front_panel_indicator_state(*args, **kwargs):
        """Retain the controller-local indicator-calculation seam."""

        return front_panel_indicator_state(*args, **kwargs)

    def reload_config(self) -> RuntimeConfig:
        """Reload configuration only after the current Flow session is detached."""

        if self._flow_lifecycle_state != "DETACHED":
            raise RuntimeError("Detach airflow before reloading config.")

        # A new configuration resets transient runtime work. Plain-data
        # receipts remain reusable when their input signature still matches.
        self.stop_flow_runtime_callbacks()
        self.stop_background_airflow_validation()
        self._stop_kit_cae_operator_tracking()
        self._airflow_validation_coordinator = None
        self._airflow_dataset_family_compatible = None
        self._airflow_dataset_family_failure = None
        self.config = RuntimeConfig.load(self._config_path)
        self._flow_validation_cache.configure_persistence(
            persisted_store=self._validation_receipt_store,
            reuse_persisted=(
                self.config.validation_receipts.reuse_verified_vti_receipts
            ),
        )
        self._airflow_state = self._create_airflow_state()
        self._xray_target_state = XRayTargetState()
        self._xray_material_active = False
        self._simulation_cache_contract = None
        self._simulation_cache_time_code = None
        self._flow_airflow_simulate_path = None
        self._flow_base_velocity_scale = None
        self._flow_world_bounds = None
        self._flow_density_cell_size = None
        self._flow_intake_tracer_radius_to_cell = None
        self._flow_vti_spacing = None
        self._flow_voxel_max_resolution = None
        self._flow_lifecycle_state = "DETACHED"
        self._smoke_presentation_visible = True
        self._streamlines_cached_presentation_visible = False
        self.reset_visualization_mode_state()
        self.reset_streamlines_cache_validation_receipts()
        self.reset_streamlines_runtime_state()
        self._flow_attach_cancel_event = None
        self._flow_temporal_asset_hashes = {}
        self._flow_temporal_records = []
        self._flow_temporal_failure = None
        self._flow_runtime_mutation_context = None
        self._flow_temporal_end_time_code = None
        self._flow_temporal_sample_time_codes = ()
        self._flow_performance_attached_at = None
        self._flow_performance_samples = []
        self._flow_performance_camera_bookmark = "Unspecified"
        self._front_panel_indicator_state_key = None
        return self.config

    def validation_receipt_identity_snapshot(self) -> dict[str, object]:
        """Return cheap current identities for controlled restart comparison."""

        cache = self.config.simulation_cache

        vti = {}

        for dataset in self.airflow_dataset_registry():

            signature = build_dataset_validation_signature(
                dataset,
                cache.velocity_field_name,
            )

            vti[signature.selector] = signature.digest

        return {
            "vti": vti,
            "streamlines": self.streamlines_validation_identity_snapshot(),
        }

    def validation_receipt_coverage_snapshot(
        self,
        identities: dict[str, object],
    ) -> dict[str, object]:
        """Check persisted coverage without running either strong validator."""

        vti_identities = identities.get("vti", {})

        streamlines_identities = identities.get("streamlines", {})

        vti_valid = sum(
            self._validation_receipt_store.has_vti(selector, digest)
            for selector, digest in vti_identities.items()
        )

        streamlines_missing_or_mismatched = tuple(
            key
            for key, value in streamlines_identities.items()
            if not self._validation_receipt_store.has_streamlines(
                key=key,
                resource_fingerprint=tuple(value["resource_fingerprint"]),
                dependency_identity=tuple(value["dependency_identity"]),
            )
        )

        streamlines_valid = len(streamlines_identities) - len(
            streamlines_missing_or_mismatched
        )

        return {
            "vti_valid": vti_valid,
            "vti_total": len(vti_identities),
            "streamlines_valid": streamlines_valid,
            "streamlines_total": len(streamlines_identities),
            "streamlines_missing_or_mismatched": streamlines_missing_or_mismatched,
            "store_path": self._validation_receipt_store.path,
        }

    def validation_receipt_metrics_snapshot(self):
        """Expose cheap instrumentation for startup summary and acceptance."""

        return self._validation_receipt_store.metrics_snapshot()

    def flow_lifecycle_state(self) -> str:
        """Expose Flow lifecycle truth for application-level cleanup checks."""

        return self._flow_lifecycle_state

    def load_validation_receipt_acceptance_checkpoint(self):
        """Load restart orchestration without treating it as evidence."""

        return self._validation_receipt_store.load_acceptance_checkpoint()

    def write_validation_receipt_acceptance_checkpoint(
        self,
        payload: dict[str, object],
    ) -> None:
        """Persist only the next acceptance session and controlled identities."""

        self._validation_receipt_store.write_acceptance_checkpoint(payload)

    def clear_validation_receipt_acceptance_checkpoint(self) -> None:
        """Clear terminal acceptance state while retaining verified receipts."""

        self._validation_receipt_store.clear_acceptance_checkpoint()

    def describe_default_asset(self) -> str:
        """Return a compact operator-facing description of the default asset."""

        asset = self.config.default_asset
        return f"{asset.label} ({asset.asset_id})"

    def describe_default_lighting(self) -> str:
        """Return a compact operator-facing description of the lighting preset."""

        return self.config.lighting.hdri_path

    def resolve_workload_airflow_binding(
        self, workload_mode: str
    ) -> WorkloadAirflowBinding:
        """Resolve airflow for Telemetry workload without changing Flow lifecycle."""

        return self._airflow_state.resolve_binding(workload_mode)

    def airflow_dataset_registry(self) -> tuple[AirflowDataset, ...]:
        """Expose the application-owned manifest registry without rediscovery."""

        self._require_airflow_dataset_registry()
        return self._airflow_state.registry

    def set_workload_source(self, workload_source: Callable[[], str]) -> None:
        """Bind the semantic workload source without exposing it to Flow."""

        self._workload_source = workload_source
        self._airflow_state.rebind_binding_runtime(self._workload_binding_runtime())

    def resolve_current_workload_airflow_binding(
        self,
    ) -> WorkloadAirflowBinding:
        """Resolve the workload current when a Flow Attach begins."""

        return self._airflow_state.resolve_current().binding

    def resolve_airflow_dataset_for_binding(
        self,
        binding: WorkloadAirflowBinding,
    ) -> AirflowDataset:
        """Resolve one workload binding through the authoritative registry only."""

        self._require_airflow_dataset_registry()
        return self._airflow_state.resolve_target(binding).dataset

    def resolve_current_airflow_dataset(
        self,
    ) -> tuple[WorkloadAirflowBinding, AirflowDataset]:
        """Return the current semantic binding and its resolved dataset together."""

        self._require_airflow_dataset_registry()
        target = self._airflow_state.resolve_current()
        return target.binding, target.dataset

    def resolve_configured_airflow_targets(self):
        """Resolve every configured workload through the one shared registry."""

        self._require_airflow_dataset_registry()
        return tuple(
            self._airflow_state.resolve_target(
                self.resolve_workload_airflow_binding(workload_mode)
            )
            for workload_mode in WORKLOAD_MODES
        )

    def airflow_cache_selector_identity(self) -> str:
        """Return the selector that is next or currently bound to Flow."""

        binding = self._flow_session_workload_binding
        if binding is None:
            binding = self.resolve_current_workload_airflow_binding()
        return binding.dataset_identity

    def airflow_transition_state(self) -> dict[str, str | None]:
        """Expose semantic, active, and pending airflow state without UI ownership."""

        snapshot = self._airflow_state.snapshot
        return {
            "semantic_workload": (
                self._workload_source() if self._workload_source else None
            ),
            "active_airflow_selector": (
                snapshot.committed.binding.dataset_identity
                if snapshot.committed
                else None
            ),
            "pending_airflow_selector": (
                snapshot.pending.target.binding.dataset_identity
                if snapshot.pending
                else None
            ),
        }

    def airflow_failure_state(self) -> dict[str, str | None] | None:
        """Return the last truthful airflow failure without changing workload state."""

        failure = self._airflow_state.failure
        if failure is None:
            return None
        return {
            "semantic_workload": failure.semantic_workload,
            "requested_airflow_selector": failure.requested_airflow_selector,
            "active_airflow_selector": failure.active_airflow_selector,
            "reason": failure.reason,
            "failure_stage": failure.failure_stage,
            "action": failure.action,
        }

    async def request_workload_transition_in_kit(
        self,
        workload_mode: str,
        status_callback: StatusCallback | None = None,
    ):
        """Route one semantic workload request to the active primary consumer."""

        mode = self.visualization_snapshot().committed
        if mode in {
            VisualizationMode.STREAMLINES,
            VisualizationMode.STREAMLINES_XRAY,
        }:
            return await self.request_streamlines_workload_transition_in_kit(
                workload_mode,
                status_callback=status_callback,
            )
        return await self.request_attached_workload_transition_in_kit(
            workload_mode,
            status_callback=status_callback,
        )

    def _workload_binding_runtime(self) -> WorkloadBindingRuntime:
        """Build the binding coordinator from current runtime configuration."""

        return WorkloadBindingRuntime(
            self.config.simulation_cache,
            self._workload_source,
        )

    def _create_airflow_state(self) -> AirflowStateRuntime:
        """Compose one lifetime shared state from the sole discovered registry."""

        cache = self.config.simulation_cache
        try:
            registry = discover_airflow_dataset_registry(
                self.config.asset_root,
                cache.airflow_dataset.root,
            )
        except AirflowDatasetError as error:
            # Config-only commands remain usable without hydrated external
            # assets. Airflow actions surface this same discovery error before
            # they can author Kit state or substitute another source.
            self._airflow_dataset_registry_error = error
            registry = ()
        else:
            self._airflow_dataset_registry_error = None
        return AirflowStateRuntime(self._workload_binding_runtime(), registry)

    def _require_airflow_dataset_registry(self) -> None:
        """Fail airflow work with the original registry error, never a fallback."""

        if self._airflow_dataset_registry_error is not None:
            raise self._airflow_dataset_registry_error

    @property
    def _flow_session_workload_binding(self) -> WorkloadAirflowBinding | None:
        """Legacy test seam forwarding to shared committed airflow state."""

        committed = self._airflow_state.committed
        return committed.binding if committed else None

    @_flow_session_workload_binding.setter
    def _flow_session_workload_binding(
        self, binding: WorkloadAirflowBinding | None
    ) -> None:
        self._airflow_state.replace_committed_binding(binding)

    @property
    def _flow_pending_workload_binding(self) -> WorkloadAirflowBinding | None:
        """Legacy test seam forwarding to the shared pending generation."""

        pending = self._airflow_state.pending
        return pending.target.binding if pending else None

    @_flow_pending_workload_binding.setter
    def _flow_pending_workload_binding(
        self, binding: WorkloadAirflowBinding | None
    ) -> None:
        self._airflow_state.replace_pending_binding(binding)

    @property
    def _flow_transition_sequence(self) -> int:
        """Legacy diagnostic readout for the shared transition generation."""

        return self._airflow_state.generation

    @_flow_transition_sequence.setter
    def _flow_transition_sequence(self, generation: int) -> None:
        self._airflow_state.replace_generation(generation)

    @property
    def _flow_active_transition_id(self) -> str | None:
        """Legacy diagnostic readout for the one shared pending transition."""

        pending = self._airflow_state.pending
        return pending.transition_id if pending else None

    @_flow_active_transition_id.setter
    def _flow_active_transition_id(self, transition_id: str | None) -> None:
        self._airflow_state.replace_active_transition_id(transition_id)

    @property
    def _flow_last_airflow_failure(self) -> dict[str, str | None] | None:
        """Legacy diagnostic readout forwarding to shared terminal failure state."""

        return self.airflow_failure_state()

    @_flow_last_airflow_failure.setter
    def _flow_last_airflow_failure(self, value: dict[str, str | None] | None) -> None:
        if value is None:
            self._airflow_state.clear_failure()
            return
        self._airflow_state.replace_failure(
            AirflowTransitionFailure(
                semantic_workload=value.get("semantic_workload", "unavailable"),
                requested_airflow_selector=value.get(
                    "requested_airflow_selector", "unresolved"
                ),
                active_airflow_selector=value.get(
                    "active_airflow_selector", "DETACHED"
                ),
                reason=value.get("reason", "unavailable"),
                failure_stage=value.get("failure_stage", "unavailable"),
                action=value.get("action", "remained_detached"),
            )
        )

    def start_background_airflow_validation(
        self,
    ) -> BackgroundAirflowValidationCoordinator:
        """Return the session's single owner of expensive VTI preflight."""

        if self._airflow_validation_coordinator is not None:
            return self._airflow_validation_coordinator

        self._require_airflow_dataset_registry()
        cache = self.config.simulation_cache
        self._airflow_validation_coordinator = BackgroundAirflowValidationCoordinator(
            self._airflow_state.registry,
            self.resolve_current_workload_airflow_binding(),
            cache.velocity_field_name,
            self._flow_validation_cache,
            flow_attached=lambda: self._flow_lifecycle_state == "ATTACHED",
        )
        return self._airflow_validation_coordinator

    async def acquire_airflow_validation_for_attach(
        self, binding: WorkloadAirflowBinding
    ) -> AttachValidationLease:
        """Give manual Attach priority through the sole validation coordinator."""

        return await self.start_background_airflow_validation().acquire_for_attach(
            binding
        )

    async def acquire_airflow_validation_for_transition(
        self, binding: WorkloadAirflowBinding
    ) -> AttachValidationLease:
        """Validate an attached workload target through the existing arbiter."""

        return await self.start_background_airflow_validation().acquire_for_transition(
            binding
        )

    async def run_background_airflow_validation(
        self,
        log: Callable[[str], None],
        progress_callback: Callable[[str, int, int, str], None] | None = None,
    ):
        """Run VTI preflight while projecting optional per-file live progress."""

        result = await self.start_background_airflow_validation().run(
            log,
            progress_callback=progress_callback,
        )
        if not result.cancelled and result.failed == 0:
            try:
                family = self.validate_registered_airflow_dataset_family()
            except AirflowDatasetFamilyCompatibilityError as error:
                log(
                    format_dtrs_diagnostic_content(
                        owner="AIRFLOW DATASET FAMILY",
                        process="COMPATIBILITY CHECK",
                        state="FAILED",
                        details={
                            "family_compatible": False,
                            "reason": error,
                        },
                    )
                )
            else:
                log(
                    format_dtrs_diagnostic_content(
                        owner="AIRFLOW DATASET FAMILY",
                        process="COMPATIBILITY CHECK",
                        state="PASS",
                        details={
                            "members": ", ".join(family.member_selectors),
                            "family_compatible": family.family_compatible,
                            "duration_seconds": f"{family.loop_duration_seconds:g}",
                            "phase_mapping": family.phase_mapping,
                        },
                    )
                )
        return result

    def validate_registered_airflow_dataset_family(self):
        """Check every already-preflighted registry member without VTI reads."""

        try:
            cache = self.config.simulation_cache
            members = []
            for dataset in self._airflow_state.registry:
                signature = build_dataset_validation_signature(
                    dataset,
                    cache.velocity_field_name,
                )
                receipt = self._flow_validation_cache.lookup(signature).preflight
                if receipt is None:
                    raise AirflowDatasetFamilyCompatibilityError(
                        "Airflow family compatibility mismatch: "
                        f"dataset={dataset.manifest.scope}/{dataset.manifest.state}; "
                        "property=preflight_receipt; expected=present; actual=missing."
                    )
                members.append((dataset, receipt))
            verdict = validate_airflow_dataset_family(
                tuple(members), velocity_field_name=cache.velocity_field_name
            )
        except (
            AirflowDatasetError,
            AirflowDatasetFamilyCompatibilityError,
            RuntimeError,
        ) as error:
            self._airflow_dataset_family_compatible = False
            self._airflow_dataset_family_failure = str(error)
            raise
        self._airflow_dataset_family_compatible = verdict.family_compatible
        self._airflow_dataset_family_failure = None
        return verdict

    def validate_attached_airflow_transition_pair(
        self,
        *,
        target_dataset: AirflowDataset,
        target_receipt,
        target_signature,
    ):
        """Validate only committed-to-target compatibility for one live switch.

        Background validation may still establish a whole-family readiness
        verdict, but an attached Flow transition requires evidence only for the
        source it is currently consuming and the target it is about to consume.
        """

        committed = self._airflow_state.committed
        if committed is None:
            raise AirflowDatasetFamilyCompatibilityError(
                "Airflow transition compatibility requires a committed dataset."
            )
        cache = self.config.simulation_cache
        active_signature = build_dataset_validation_signature(
            committed.dataset,
            cache.velocity_field_name,
        )
        active_receipt = self._flow_validation_cache.lookup(active_signature).preflight
        if active_receipt is None:
            raise AirflowDatasetFamilyCompatibilityError(
                "Airflow family compatibility mismatch: "
                f"dataset={active_signature.selector}; "
                "property=preflight_receipt; expected=present; actual=missing."
            )
        if target_receipt is None:
            raise AirflowDatasetFamilyCompatibilityError(
                "Airflow family compatibility mismatch: "
                f"dataset={target_signature.selector}; "
                "property=preflight_receipt; expected=present; actual=missing."
            )
        if target_receipt.signature != target_signature:
            raise AirflowDatasetFamilyCompatibilityError(
                "Airflow family compatibility mismatch: "
                f"dataset={target_signature.selector}; "
                "property=preflight_receipt.signature; expected=current; "
                "actual=stale."
            )
        return validate_airflow_dataset_family_compatibility(
            committed.dataset,
            active_receipt,
            target_dataset,
            target_receipt,
            velocity_field_name=cache.velocity_field_name,
        )

    def stop_background_airflow_validation(self) -> None:
        """Cooperatively stop the session validator during extension shutdown."""

        if self._airflow_validation_coordinator is not None:
            self._airflow_validation_coordinator.cancel()

    @staticmethod
    def _enable_index_compositing(stage, cache, carb) -> None:
        """Enable the global RTX compositing switch used by the NVIDIA fixture."""

        settings = carb.settings.get_settings()
        settings.set("/rtx/index/compositeEnabled", True)
        settings.set("/rtx/index/compositeDepthMode", 3)
        settings.set("/rtx/index/resolutionScale", cache.resolution_scale)
        settings.set("/rtx/index/renderingSamples", cache.rendering_samples)

        session_layer = stage.GetSessionLayer()
        layer_data = dict(session_layer.customLayerData)
        render_settings = dict(layer_data.get("renderSettings", {}))
        render_settings["rtx:index:compositeEnabled"] = True
        render_settings["rtx:index:compositeDepthMode"] = 3
        layer_data["renderSettings"] = render_settings
        session_layer.customLayerData = layer_data

    async def attach_simulation_cache_in_kit(
        self,
        status_callback: StatusCallback | None = None,
    ) -> SimulationCacheResult:
        """Attach the configured cache through RTX / NVIDIA IndeX compositing."""

        cache = self.config.simulation_cache
        if not cache.enabled:
            return SimulationCacheResult(
                success=False,
                message="Airflow cache is disabled in the runtime config.",
            )

        if cache.runtime_mode == "kit_cae":
            return await self._attach_kit_cae_airflow_in_kit(status_callback)

        if status_callback:
            status_callback("Checking airflow cache")
        preflight = run_simulation_cache_preflight(
            self.config.simulation_cache_path,
            cache,
        )
        if not preflight.success or not preflight.contract:
            return SimulationCacheResult(False, preflight.format_summary())

        import omni.kit.app
        import omni.timeline
        import omni.usd

        extension_manager = omni.kit.app.get_app().get_extension_manager()
        if not extension_manager.is_extension_enabled("omni.rtx.index_composite"):
            return SimulationCacheResult(
                False,
                (
                    "Airflow cache is valid, but RTX / NVIDIA IndeX Compositing "
                    "is unavailable in this Kit build. Playback remains disabled."
                ),
            )

        import carb
        import omni.kit.viewport.utility as viewport_utility
        from pxr import Gf, Sdf, UsdGeom, UsdShade

        stage = omni.usd.get_context().get_stage()
        if not stage:
            return SimulationCacheResult(
                False,
                "Airflow cache skipped: no open stage.",
            )

        # IndeX compositing is an RTX feature, not the standalone Scientific
        # renderer. Set it before the Volume enters the composed stage.
        self._enable_index_compositing(stage, cache, carb)
        viewport = viewport_utility.get_active_viewport()
        if viewport and hasattr(viewport, "set_hd_engine"):
            viewport.set_hd_engine("rtx")

        # Session-layer metrics give the cache its authored time domain without
        # modifying the referenced rig USD on disk.
        session_layer = stage.GetSessionLayer()
        session_layer.timeCodesPerSecond = preflight.contract.time_codes_per_second
        session_layer.framesPerSecond = preflight.contract.frames_per_second

        timeline = omni.timeline.get_timeline_interface()
        previous_target = stage.GetEditTarget()
        stage.SetEditTarget(stage.GetSessionLayer())
        try:
            self._author_airflow_cache_session_layer(
                stage,
                cache,
                preflight.contract,
                Gf,
                Sdf,
                UsdGeom,
                UsdShade,
            )
        finally:
            stage.SetEditTarget(previous_target)

        self._simulation_cache_contract = preflight.contract
        self._simulation_cache_time_code = int(preflight.contract.start_time_code)

        timeline.pause()
        timeline.set_current_time(
            preflight.contract.start_time_code
            / preflight.contract.time_codes_per_second
        )
        await omni.kit.app.get_app().next_update_async()
        timeline.play(
            preflight.contract.start_time_code,
            preflight.contract.end_time_code,
            True,
        )
        return SimulationCacheResult(
            True,
            "Airflow cache is playing through RTX / NVIDIA IndeX Compositing.",
        )

    def _author_airflow_cache_session_layer(
        stage,
        cache,
        contract,
        Gf,
        Sdf,
        UsdGeom,
        UsdShade,
    ) -> None:
        """Author native NVIDIA IndeX compositing opinions in the session layer."""

        runtime_path = Sdf.Path("/DTRS_Runtime/Airflow")
        stage.RemovePrim(runtime_path)
        stage.RemovePrim("/DTRS_Runtime/Looks/AirflowIndex")

        UsdGeom.Xform.Define(stage, "/DTRS_Runtime")
        cache_root = UsdGeom.Xform.Define(stage, runtime_path)
        cache_root.GetPrim().GetReferences().AddReference(
            contract.wrapper_path.as_posix(),
            Sdf.Path(cache.root_prim_path),
        )

        volume_prim = next(
            (
                prim
                for prim in cache_root.GetPrim().GetChildren()
                if prim.GetTypeName() == "Volume"
            ),
            None,
        )
        if not volume_prim:
            raise RuntimeError("The airflow wrapper did not compose a USD Volume.")

        volume_prim.CreateAttribute(
            "nvindex:composite",
            Sdf.ValueTypeNames.Bool,
            custom=True,
        ).Set(True)
        volume_prim.CreateAttribute(
            "omni:rtx:skip",
            Sdf.ValueTypeNames.Bool,
            custom=True,
        ).Set(True)
        volume_prim.SetCustomDataByKey(
            "nvindex.renderSettings",
            {
                "filterMode": cache.filter_mode,
                "samplingDistance": cache.sampling_distance,
            },
        )

        material_path = Sdf.Path("/DTRS_Runtime/Looks/AirflowIndex")
        material = UsdShade.Material.Define(stage, material_path)
        colormap = stage.DefinePrim(material_path.AppendChild("Colormap"), "Colormap")
        colormap.CreateAttribute(
            "colormapSource",
            Sdf.ValueTypeNames.Token,
            custom=True,
        ).Set("rgbaPoints")
        colormap.CreateAttribute(
            "domain",
            Sdf.ValueTypeNames.Float2,
            custom=True,
        ).Set(Gf.Vec2f(0.0, 12.5))
        colormap.CreateAttribute(
            "domainBoundaryMode",
            Sdf.ValueTypeNames.Token,
            custom=False,
            variability=Sdf.VariabilityUniform,
        ).Set("clampToTransparent")
        colormap_output = colormap.CreateAttribute(
            "outputs:colormap",
            Sdf.ValueTypeNames.Token,
            custom=True,
        )
        colormap.CreateAttribute(
            "rgbaPoints",
            Sdf.ValueTypeNames.Float4Array,
            custom=True,
        ).Set(
            [
                Gf.Vec4f(0.03, 0.12, 0.16, 0.0),
                Gf.Vec4f(0.05, 0.48, 0.64, 0.025),
                Gf.Vec4f(0.13, 0.82, 0.87, 0.16),
                Gf.Vec4f(0.62, 0.98, 0.88, 0.34),
            ]
        )
        colormap.CreateAttribute(
            "xPoints",
            Sdf.ValueTypeNames.FloatArray,
            custom=True,
        ).Set([0.0, 0.15, 1.5, 12.5])

        shader = UsdShade.Shader.Define(
            stage, material_path.AppendChild("VolumeShader")
        )
        shader_input = shader.CreateInput("colormap", Sdf.ValueTypeNames.Token)
        shader_input.GetAttr().AddConnection(colormap_output.GetPath())
        shader_output = shader.CreateOutput("volume", Sdf.ValueTypeNames.Token)
        material_output = material.GetPrim().CreateAttribute(
            "outputs:nvindex:volume",
            Sdf.ValueTypeNames.Token,
            custom=True,
        )
        material_output.AddConnection(shader_output.GetAttr().GetPath())
        UsdShade.MaterialBindingAPI.Apply(volume_prim).Bind(material)
