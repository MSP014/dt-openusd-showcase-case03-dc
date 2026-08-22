"""Reversible Session Layer isolation for the Stage 10 Heatmap test control."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Mapping

from digital_twin_runtime_suite.app.telemetry.model import TelemetrySnapshot

from .bindings import (
    HeatmapSemanticRegistry,
    HeatmapTelemetrySnapshot,
    build_heatmap_semantic_registry,
)
from .discovery import discover_thermal_geometry
from .material import HeatmapMaterialTarget, HeatmapMaterialWriteCounts
from .preflight import HeatmapAssetPreflightResult, run_heatmap_asset_preflight
from .scalar import (
    DEFAULT_HEATMAP_DELTA_PROFILE,
    FULL_SPECTRUM_HEATMAP_PALETTE,
    THERMAL_WEIGHT_REMAP_COLD_BIASED,
    THERMAL_WEIGHT_REMAP_LINEAR,
    DeltaProfile,
    ThermalScaleResolution,
    effective_delta_range,
    evaluate_heatmap_scalar,
    resolve_provider_temperature_profile,
    resolve_server_wide_celsius_scale,
)
from .smoothing import HeatmapRetargetEvidence


@dataclass(frozen=True)
class HeatmapVerticalSliceTarget:
    """One focused GPU-internal target retained without a live USD prim."""

    material_key: str
    prim_path: str
    semantic_key: object
    metric_id: str
    thermal_weights: tuple[float, ...]
    thermal_weight_interpolation: str
    delta_profiles: Mapping[str, DeltaProfile]


@dataclass(frozen=True)
class HeatmapVerticalSliceContract:
    """Static scalar evidence for the focused GPU-internal demo."""

    targets: tuple[HeatmapVerticalSliceTarget, ...]
    unavailable_target_paths: tuple[str, ...]
    scale_resolution: ThermalScaleResolution
    provider_profiles: Mapping[str, Mapping[str, tuple[float, float, float, float]]]


@dataclass(frozen=True)
class HeatmapVerticalSliceState:
    """Small immutable snapshot for the GPU03 PCB material presentation."""

    success: bool
    enabled: bool
    message: str
    target_path: str = ""
    target_paths: tuple[str, ...] = ()
    unavailable_target_paths: tuple[str, ...] = ()
    material_creations: int = 0
    parameter_updates: int = 0


@dataclass(frozen=True)
class HeatmapGpu03GradientAudit:
    """Nominal authored-weight evidence for one GPU03 thermal semantic group."""

    thermal_zone: str
    thermal_component: str
    metric_id: str
    target_count: int
    weight_minimum: float
    weight_maximum: float
    delta_minimum_celsius: tuple[float, float]
    delta_maximum_celsius: tuple[float, float]
    effective_display_span_celsius: float
    variation: str


@dataclass(frozen=True)
class HeatmapFullServerTarget:
    """One renderable or X-Ray-suppressed target without a live USD prim."""

    material_key: str
    prim_path: str
    semantic_key: object
    metric_id: str
    presentation_temperature_offset_celsius: float
    thermal_weights: tuple[float, ...]
    thermal_weight_interpolation: str
    thermal_weight_remap: str
    thermal_weight_minimum: float
    thermal_weight_maximum: float
    delta_profiles: Mapping[str, DeltaProfile]


@dataclass(frozen=True)
class HeatmapFullServerContract:
    """Validated full-server plan separated into render and suppression paths."""

    total_thermal_targets: int
    renderable_targets: tuple[HeatmapFullServerTarget, ...]
    unavailable_target_paths: tuple[str, ...]
    unavailable_reasons: Mapping[str, str]
    xray_precedence_target_paths: tuple[str, ...]
    xray_precedence_targets: tuple[HeatmapFullServerTarget, ...]
    scale_resolution: ThermalScaleResolution
    provider_profiles: Mapping[str, Mapping[str, tuple[float, float, float, float]]]
    registry_fingerprint: tuple[object, ...]


@dataclass(frozen=True)
class HeatmapNodeMetricEvidence:
    """Current truthful telemetry and derived range for one hardware metric."""

    metric_id: str
    value: float | None
    quality: str
    derived_minimum_celsius: float | None
    derived_maximum_celsius: float | None


@dataclass(frozen=True)
class HeatmapFullServerNodeEvidence:
    """Concise per-hardware evidence prepared by runtime for manual review."""

    hardware_identity: str
    rendered_target_count: int
    semantic_groups: tuple[str, ...]
    telemetry: tuple[HeatmapNodeMetricEvidence, ...]
    unavailable_target_paths: tuple[str, ...]


@dataclass(frozen=True)
class HeatmapFullServerState:
    """Immutable evidence for one full-server Heatmap presentation state."""

    success: bool
    enabled: bool
    message: str
    workload: str = ""
    total_thermal_targets: int = 0
    renderable_target_paths: tuple[str, ...] = ()
    rendered_target_paths: tuple[str, ...] = ()
    unavailable_target_paths: tuple[str, ...] = ()
    xray_precedence_target_paths: tuple[str, ...] = ()
    semantic_group_count: int = 0
    rendered_semantic_group_count: int = 0
    unavailable_semantic_group_count: int = 0
    material_group_count: int = 0
    session_binding_count: int = 0
    registry_fingerprint: tuple[object, ...] = ()
    scale_resolution: ThermalScaleResolution | None = None
    palette_identity: str = "full_spectrum_violet_blue_to_red"
    node_evidence: tuple[HeatmapFullServerNodeEvidence, ...] = ()


@dataclass(frozen=True)
class HeatmapBindingCalibrationFocus:
    """One acceptance-only metric projection with exact renderer evidence."""

    success: bool
    metric_ids: tuple[str, ...]
    isolation_path: str
    expected_target_paths: tuple[str, ...]
    rendered_target_paths: tuple[str, ...]
    foreign_rendered_target_paths: tuple[str, ...]
    message: str


@dataclass(frozen=True)
class HeatmapPresentationDiagnostics:
    """One bounded scheduler interval's aggregate material-write evidence."""

    cadence_hz: int
    scheduler_tick_count: int
    telemetry_target_changes: int
    semantic_groups_considered: int
    shader_parameter_writes: int
    skipped_unchanged_parameter_writes: int
    structural_material_writes: int
    material_binding_writes: int
    primvar_st_writes: int
    material_prim_creations: int


@dataclass(frozen=True)
class HeatmapMotherboardDeltaProfile:
    """One workload's authored-weight-aware motherboard temperature envelope."""

    workload: str
    delta_minimum_celsius: float
    delta_maximum_celsius: float
    display_minimum_celsius: float
    display_maximum_celsius: float
    effective_span_celsius: float


@dataclass(frozen=True)
class HeatmapMotherboardDeltaCalibration:
    """Immutable matrix row for one calibrated motherboard semantic group."""

    thermal_zone: str
    thermal_component: str
    metric_id: str
    presentation_temperature_offset_celsius: float
    target_count: int
    weight_minimum: float
    weight_maximum: float
    calibration_kind: str
    profiles: tuple[HeatmapMotherboardDeltaProfile, ...]


@dataclass(frozen=True)
class HeatmapTestIsolationResult:
    """Report one deterministic Heatmap test-isolation request outcome."""

    success: bool
    enabled: bool
    message: str
    target_path: str
    target_paths: tuple[str, ...] = ()
    owned_visibility_paths: tuple[str, ...] = ()
    focus_evidence: "HeatmapFocusedIsolationEvidence | None" = None
    preflight: HeatmapAssetPreflightResult | None = None
    registry: HeatmapSemanticRegistry | None = None
    telemetry: HeatmapTelemetrySnapshot | None = None
    vertical_slice: HeatmapVerticalSliceState | None = None
    full_server: HeatmapFullServerState | None = None
    calibration_focus: HeatmapBindingCalibrationFocus | None = None


@dataclass(frozen=True)
class HeatmapFocusedIsolationEvidence:
    """Prove the temporary motherboard, RAM, GPU, NIC, PSU, and cooler scope."""

    ready: bool
    motherboard_path: str
    motherboard_visible: bool
    ram_module_paths: tuple[str, ...]
    visible_ram_module_paths: tuple[str, ...]
    cpu_cooler_render_paths: tuple[str, ...]
    visible_cpu_cooler_render_paths: tuple[str, ...]
    cpu_cooler_fan_path: str
    cpu_cooler_fan_hidden: bool
    gpu_internal_paths: tuple[str, ...]
    visible_gpu_internal_paths: tuple[str, ...]
    gpu_plug_paths: tuple[str, ...]
    visible_gpu_plug_paths: tuple[str, ...]
    nic_render_path: str
    nic_visible: bool
    unrelated_server_hardware_hidden: bool
    outside_server_visibility_untouched: bool


class HeatmapRuntimeMixin:
    """Own reversible Heatmap test presentation and legacy PCB isolation."""

    HEATMAP_TEST_ISOLATION_OWNER = "heatmap_test_isolation"
    HEATMAP_TEST_SERVER_ROOT_PATH = "/blackwell_rig"
    HEATMAP_TEST_TARGET_PATH = "/blackwell_rig/compute/gpu_03/geo/render/RTX4500/pcb"
    HEATMAP_GPU_ROOT_PATHS = tuple(
        f"/blackwell_rig/compute/gpu_{instance:02d}" for instance in (1, 2, 3)
    )
    HEATMAP_GPU_INTERNAL_TARGET_PATHS = tuple(
        f"{path}/geo/render/RTX4500/pcb" for path in HEATMAP_GPU_ROOT_PATHS
    )
    HEATMAP_GPU_PLUG_SEMANTIC = ("gpu_body", "plug")
    HEATMAP_GPU_PLUG_TARGETS_PER_GPU = 4
    HEATMAP_GPU_EXTERNAL_SEMANTICS = frozenset(
        {
            ("gpu_body", "shroud"),
            ("gpu_cooling", "blower"),
        }
    )
    HEATMAP_MOTHERBOARD_PATH = "/blackwell_rig/motherboard"
    HEATMAP_RAM_ASSEMBLY_PATH = "/blackwell_rig/ram"
    HEATMAP_COMPUTE_PATH = "/blackwell_rig/compute"
    HEATMAP_POWER_PATH = "/blackwell_rig/power"
    HEATMAP_PSU_PATH = f"{HEATMAP_POWER_PATH}/psu"
    HEATMAP_NIC_PATH = "/blackwell_rig/connectx_7"
    HEATMAP_NIC_RENDER_PATH = f"{HEATMAP_NIC_PATH}/geo/render/connectx_7"
    HEATMAP_CPU_COOLER_PATH = "/blackwell_rig/cpu_cooler"
    HEATMAP_CPU_COOLER_RENDER_PATH = f"{HEATMAP_CPU_COOLER_PATH}/geo/render/cpu_cooler"
    HEATMAP_CPU_COOLER_FAN_PATH = f"{HEATMAP_CPU_COOLER_RENDER_PATH}/cpu_fan"
    HEATMAP_CPU_COOLER_THERMAL_PATHS = (
        f"{HEATMAP_CPU_COOLER_RENDER_PATH}/cpu_radiator",
        f"{HEATMAP_CPU_COOLER_RENDER_PATH}/cooler_base",
    )

    def set_heatmap_full_server_test_in_kit(
        self,
        enabled: bool,
    ) -> HeatmapTestIsolationResult:
        """Apply or restore the Stage 10.3 full-server Session presentation."""

        import omni.usd

        stage = omni.usd.get_context().get_stage()
        if not stage:
            return HeatmapTestIsolationResult(
                success=not enabled,
                enabled=False,
                message=(
                    "Heatmap full-server test requires an open stage."
                    if enabled
                    else "Heatmap full-server test is inactive; no open stage."
                ),
                target_path=self.HEATMAP_TEST_SERVER_ROOT_PATH,
            )
        if enabled:
            self._heatmap_test_presentation_scope_paths = ()
            preflight = self._run_heatmap_asset_preflight(stage)
            registry = self._build_heatmap_semantic_registry(preflight)
            contract = self._prepare_heatmap_full_server_contract(
                preflight,
                registry,
            )
            state = self._apply_heatmap_full_server(stage)
            success = bool(
                preflight.success
                and registry.success
                and contract is not None
                and state.success
            )
            return HeatmapTestIsolationResult(
                success=success,
                enabled=state.enabled,
                message=state.message,
                target_path=self.HEATMAP_TEST_SERVER_ROOT_PATH,
                preflight=preflight,
                registry=registry,
                telemetry=self._heatmap_telemetry_snapshot,
                full_server=state,
            )
        state = self._clear_heatmap_full_server_in_stage(stage)
        self._heatmap_test_presentation_scope_paths = ()
        return HeatmapTestIsolationResult(
            success=state.success,
            enabled=state.enabled,
            message=state.message,
            target_path=self.HEATMAP_TEST_SERVER_ROOT_PATH,
            full_server=state,
        )

    def clear_heatmap_full_server_test_in_kit(self) -> HeatmapTestIsolationResult:
        """Restore full-server Session presentation during reload or shutdown."""

        if self._heatmap_binding_calibration_active:
            return self.set_heatmap_binding_calibration_test_in_kit(False)
        return self.set_heatmap_full_server_test_in_kit(False)

    def heatmap_full_server_test_active(self) -> bool:
        """Return whether the Stage 10.3 presentation currently owns Session state."""

        state = self._heatmap_full_server_state
        return bool(state and state.enabled)

    def set_heatmap_binding_calibration_test_in_kit(
        self,
        enabled: bool,
    ) -> HeatmapTestIsolationResult:
        """Run the temporary motherboard binding proof without Stage 10.3."""

        import omni.usd
        from pxr import Sdf, UsdGeom

        stage = omni.usd.get_context().get_stage()
        if not stage:
            return HeatmapTestIsolationResult(
                success=not enabled,
                enabled=False,
                message="Heatmap binding calibration requires an open stage.",
                target_path=self.HEATMAP_TEST_SERVER_ROOT_PATH,
            )
        if not enabled:
            presentation = self._clear_heatmap_full_server_in_stage(stage)
            isolation = self._clear_heatmap_test_isolation(stage, Sdf)
            self._clear_heatmap_binding_calibration_filter()
            self._heatmap_binding_calibration_active = False
            self._heatmap_binding_calibration_focus = None
            self._heatmap_binding_calibration_scope_path = None
            return HeatmapTestIsolationResult(
                success=presentation.success and isolation.success,
                enabled=False,
                message=f"{presentation.message} {isolation.message}",
                target_path=self.HEATMAP_TEST_SERVER_ROOT_PATH,
                full_server=presentation,
            )

        preflight = self._run_heatmap_asset_preflight(stage)
        registry = self._build_heatmap_semantic_registry(preflight)
        contract = self._prepare_heatmap_full_server_contract(preflight, registry)
        if not preflight.success or not registry.success or contract is None:
            return HeatmapTestIsolationResult(
                success=False,
                enabled=False,
                message="Heatmap binding calibration prerequisites failed.",
                target_path=self.HEATMAP_TEST_SERVER_ROOT_PATH,
                preflight=preflight,
                registry=registry,
            )
        self._heatmap_binding_calibration_active = True
        presentation = self._clear_heatmap_full_server_in_stage(stage)
        if not presentation.success:
            self._heatmap_binding_calibration_active = False
            return HeatmapTestIsolationResult(
                success=False,
                enabled=False,
                message=presentation.message,
                target_path=self.HEATMAP_MOTHERBOARD_PATH,
                preflight=preflight,
                registry=registry,
            )
        current_path = self._heatmap_test_isolation_target_path
        if (
            self._heatmap_test_isolation_active
            and current_path != self.HEATMAP_MOTHERBOARD_PATH
        ):
            cleared = self._clear_heatmap_test_isolation(stage, Sdf)
            if not cleared.success:
                self._heatmap_binding_calibration_active = False
                return HeatmapTestIsolationResult(
                    success=False,
                    enabled=False,
                    message=cleared.message,
                    target_path=self.HEATMAP_MOTHERBOARD_PATH,
                    preflight=preflight,
                    registry=registry,
                )
        isolation = self._enable_heatmap_test_isolation(
            stage,
            Sdf,
            UsdGeom,
            target_path=self.HEATMAP_MOTHERBOARD_PATH,
        )
        if not isolation.success:
            self._heatmap_binding_calibration_active = False
            return replace(
                isolation,
                preflight=preflight,
                registry=registry,
                telemetry=self._heatmap_telemetry_snapshot,
            )
        self._clear_heatmap_binding_calibration_filter()
        self._heatmap_binding_calibration_focus = None
        self._heatmap_binding_calibration_scope_path = None
        snapshot = self._heatmap_current_telemetry_snapshot
        state = self._set_heatmap_full_server_state(
            True,
            False,
            "Motherboard calibration isolation is prepared without Heatmap material.",
            workload=snapshot.operational_state if snapshot is not None else "",
        )
        return HeatmapTestIsolationResult(
            success=state.success,
            enabled=state.success,
            message=state.message,
            target_path=self.HEATMAP_MOTHERBOARD_PATH,
            preflight=preflight,
            registry=registry,
            telemetry=self._heatmap_telemetry_snapshot,
            full_server=state,
        )

    def set_heatmap_binding_calibration_focus_in_kit(
        self,
        metric_ids: tuple[str, ...],
        isolation_path: str,
    ) -> HeatmapBindingCalibrationFocus:
        """Apply one temporary telemetry focus while retaining static bindings."""

        import omni.usd
        from pxr import Sdf, UsdGeom

        stage = omni.usd.get_context().get_stage()
        if not self._heatmap_binding_calibration_active or not stage:
            return HeatmapBindingCalibrationFocus(
                success=False,
                metric_ids=tuple(sorted(metric_ids)),
                isolation_path=isolation_path,
                expected_target_paths=(),
                rendered_target_paths=(),
                foreign_rendered_target_paths=(),
                message="Heatmap binding calibration is not active.",
            )
        return self._set_heatmap_binding_calibration_focus(
            stage,
            Sdf,
            UsdGeom,
            metric_ids,
            isolation_path,
        )

    def set_heatmap_binding_calibration_full_scope_in_kit(
        self,
        isolation_path: str,
    ) -> HeatmapBindingCalibrationFocus:
        """Remove the telemetry projection while retaining the focused viewport."""

        return self.set_heatmap_binding_calibration_focus_in_kit((), isolation_path)

    def heatmap_binding_calibration_focus_snapshot(
        self,
    ) -> HeatmapBindingCalibrationFocus | None:
        """Expose immutable current proof evidence without renderer internals."""

        return self._heatmap_binding_calibration_focus

    def heatmap_binding_calibration_test_active(self) -> bool:
        """Return whether the temporary corrective guided test owns presentation."""

        return self._heatmap_binding_calibration_active

    def heatmap_binding_calibration_filter_active(self) -> bool:
        """Return whether an acceptance-only telemetry projection remains active."""

        return bool(self._heatmap_acceptance_filter_metric_ids)

    def set_heatmap_test_isolation_in_kit(
        self, enabled: bool
    ) -> HeatmapTestIsolationResult:
        """Enable or restore the focused motherboard-and-RAM Session presentation."""

        import omni.usd
        from pxr import Sdf, UsdGeom

        if enabled and self._heatmap_binding_calibration_active:
            cleanup = self.set_heatmap_binding_calibration_test_in_kit(False)
            if not cleanup.success:
                return replace(
                    cleanup,
                    message=(
                        "Focused Heatmap test could not clear the active "
                        f"binding calibration: {cleanup.message}"
                    ),
                )
        stage = omni.usd.get_context().get_stage()
        if not stage:
            self._reset_heatmap_test_isolation_state()
            return HeatmapTestIsolationResult(
                success=not enabled,
                enabled=False,
                message=(
                    "Heatmap test isolation requires an open stage."
                    if enabled
                    else "Heatmap test isolation is inactive; no open stage."
                ),
                target_path=self.HEATMAP_TEST_TARGET_PATH,
            )

        self._discard_stale_heatmap_test_isolation_state(stage)
        if enabled:
            try:
                target_paths = self._resolve_heatmap_focused_scope_paths(stage)
            except RuntimeError as error:
                return HeatmapTestIsolationResult(
                    success=False,
                    enabled=False,
                    message=str(error),
                    target_path=self.HEATMAP_MOTHERBOARD_PATH,
                )
            preflight = self._run_heatmap_asset_preflight(stage)
            registry = self._build_heatmap_semantic_registry(preflight)
            full_server = self._prepare_heatmap_full_server_contract(
                preflight,
                registry,
            )
            vertical_slice = self._prepare_heatmap_vertical_slice_contract(
                preflight,
                registry,
            )
            isolation = self._enable_heatmap_test_isolation(
                stage,
                Sdf,
                UsdGeom,
                target_path=self.HEATMAP_MOTHERBOARD_PATH,
                target_paths=target_paths,
            )
            evidence = None
            if isolation.success:
                evidence = self._heatmap_focused_isolation_evidence(
                    stage,
                    UsdGeom,
                    target_paths=target_paths,
                    owned_visibility_paths=isolation.owned_visibility_paths,
                )
                if not evidence.ready:
                    cleanup = self._clear_heatmap_test_isolation(stage, Sdf)
                    return HeatmapTestIsolationResult(
                        success=False,
                        enabled=False,
                        message=(
                            "Heatmap focused isolation proof failed: "
                            f"{cleanup.message}"
                        ),
                        target_path=self.HEATMAP_MOTHERBOARD_PATH,
                        target_paths=target_paths,
                        focus_evidence=evidence,
                        preflight=preflight,
                        registry=registry,
                        telemetry=self._heatmap_telemetry_snapshot,
                        vertical_slice=vertical_slice,
                    )
            presentation = None
            if full_server is not None:
                self._heatmap_test_presentation_scope_paths = target_paths
                presentation = self._apply_heatmap_full_server(stage)
            return replace(
                isolation,
                focus_evidence=evidence,
                preflight=preflight,
                registry=registry,
                telemetry=self._heatmap_telemetry_snapshot,
                vertical_slice=vertical_slice,
                full_server=presentation,
            )
        # Release the later vertical-slice overlay before its full-server base.
        presentation = self._clear_heatmap_vertical_slice_in_stage(stage)
        full_server = self._clear_heatmap_full_server_in_stage(stage)
        self._heatmap_test_presentation_scope_paths = ()
        isolation = self._clear_heatmap_test_isolation(stage, Sdf)
        if presentation.success and full_server.success:
            return replace(
                isolation,
                vertical_slice=presentation,
                full_server=full_server,
            )
        return replace(
            isolation,
            success=False,
            message=(
                f"{isolation.message} {presentation.message} " f"{full_server.message}"
            ),
            vertical_slice=presentation,
            full_server=full_server,
        )

    def clear_heatmap_test_isolation_in_kit(self) -> HeatmapTestIsolationResult:
        """Restore Heatmap-test visibility during reload or extension shutdown."""

        return self.set_heatmap_test_isolation_in_kit(False)

    def heatmap_test_isolation_active(self) -> bool:
        """Return the controller-owned active state for the single test control."""

        return self._heatmap_test_isolation_active

    def heatmap_semantic_registry_snapshot(self) -> HeatmapSemanticRegistry | None:
        """Return the current immutable Heatmap semantic registry."""

        return self._heatmap_semantic_registry

    def heatmap_telemetry_binding_snapshot(self) -> HeatmapTelemetrySnapshot | None:
        """Return current resolved Heatmap values without rebuilding bindings."""

        return self._heatmap_telemetry_snapshot

    def configure_heatmap_telemetry_config(self, telemetry_config) -> None:
        """Provide the resolved provider envelope used by the scalar contract."""

        if telemetry_config is self._heatmap_telemetry_config:
            return
        self._heatmap_telemetry_config = telemetry_config
        self._heatmap_vertical_slice_contract = None
        self._heatmap_full_server_contract = None

    def heatmap_vertical_slice_snapshot(self) -> HeatmapVerticalSliceState | None:
        """Return the immutable vertical-slice state without exposing the presenter."""

        return self._heatmap_vertical_slice_state

    def heatmap_vertical_slice_contract_snapshot(
        self,
    ) -> HeatmapVerticalSliceContract | None:
        """Return static target/scale evidence without mutable runtime state."""

        return self._heatmap_vertical_slice_contract

    def heatmap_gpu03_gradient_audit_snapshot(
        self,
    ) -> tuple[HeatmapGpu03GradientAudit, ...]:
        """Expose nominal GPU-internal gradient evidence without mutable state."""

        contract = self._heatmap_vertical_slice_contract
        if contract is None:
            return ()
        grouped: dict[tuple[str, str, str], list[HeatmapVerticalSliceTarget]] = {}
        for target in contract.targets:
            key = (
                target.semantic_key.thermal_zone,
                target.semantic_key.thermal_component,
                target.metric_id,
            )
            grouped.setdefault(key, []).append(target)
        audit = []
        for (zone, component, metric_id), targets in sorted(
            grouped.items(),
            key=_gpu03_gradient_sort_key,
        ):
            weights = tuple(
                weight for target in targets for weight in target.thermal_weights
            )
            profiles = tuple(target.delta_profiles["Nominal"] for target in targets)
            effective_ranges = tuple(
                effective_delta_range(
                    profile,
                    weight_minimum=min(target.thermal_weights),
                    weight_maximum=max(target.thermal_weights),
                )
                for target, profile in zip(targets, profiles)
            )
            has_internal_variation = any(
                min(target.thermal_weights) != max(target.thermal_weights)
                for target in targets
            )
            variation = "inside GPrim"
            if not has_internal_variation:
                variation = (
                    "only between GPrims" if min(weights) != max(weights) else "flat"
                )
            audit.append(
                HeatmapGpu03GradientAudit(
                    thermal_zone=zone,
                    thermal_component=component,
                    metric_id=metric_id,
                    target_count=len(targets),
                    weight_minimum=min(weights),
                    weight_maximum=max(weights),
                    delta_minimum_celsius=(
                        min(profile.minimum_celsius for profile in profiles),
                        max(profile.minimum_celsius for profile in profiles),
                    ),
                    delta_maximum_celsius=(
                        min(profile.maximum_celsius for profile in profiles),
                        max(profile.maximum_celsius for profile in profiles),
                    ),
                    effective_display_span_celsius=(
                        max(item[1] for item in effective_ranges)
                        - min(item[0] for item in effective_ranges)
                    ),
                    variation=variation,
                )
            )
        return tuple(audit)

    def heatmap_full_server_snapshot(self) -> HeatmapFullServerState | None:
        """Return compact full-server evidence without renderer-owned dictionaries."""

        return self._heatmap_full_server_state

    def heatmap_full_server_contract_snapshot(
        self,
    ) -> HeatmapFullServerContract | None:
        """Return static coverage evidence needed by tests and guided acceptance."""

        return self._heatmap_full_server_contract

    def heatmap_motherboard_delta_calibration_snapshot(
        self,
    ) -> tuple[HeatmapMotherboardDeltaCalibration, ...]:
        """Expose the complete calibrated motherboard matrix for manual review."""

        contract = self._heatmap_full_server_contract
        if contract is None:
            return ()
        grouped: dict[tuple[str, str, str], list[HeatmapFullServerTarget]] = {}
        for target in contract.renderable_targets:
            if not target.prim_path.startswith(f"{self.HEATMAP_MOTHERBOARD_PATH}/"):
                continue
            semantic = target.semantic_key
            key = (
                semantic.thermal_zone,
                semantic.thermal_component,
                target.metric_id,
            )
            grouped.setdefault(key, []).append(target)
        rows = []
        for (zone, component, metric_id), targets in sorted(grouped.items()):
            weights = tuple(
                weight for target in targets for weight in target.thermal_weights
            )
            weight_minimum = min(weights)
            weight_maximum = max(weights)
            profiles = targets[0].delta_profiles
            provider_profiles = contract.provider_profiles[metric_id]
            workload_profiles = []
            for workload in _heatmap_workload_order(profiles):
                profile = profiles[workload]
                delta_minimum, delta_maximum = effective_delta_range(
                    profile,
                    weight_minimum=weight_minimum,
                    weight_maximum=weight_maximum,
                )
                telemetry_target = (
                    provider_profiles[workload][0]
                    + targets[0].presentation_temperature_offset_celsius
                )
                workload_profiles.append(
                    HeatmapMotherboardDeltaProfile(
                        workload=workload,
                        delta_minimum_celsius=profile.minimum_celsius,
                        delta_maximum_celsius=profile.maximum_celsius,
                        display_minimum_celsius=(telemetry_target + delta_minimum),
                        display_maximum_celsius=(telemetry_target + delta_maximum),
                        effective_span_celsius=(delta_maximum - delta_minimum),
                    )
                )
            rows.append(
                HeatmapMotherboardDeltaCalibration(
                    thermal_zone=zone,
                    thermal_component=component,
                    metric_id=metric_id,
                    presentation_temperature_offset_celsius=(
                        targets[0].presentation_temperature_offset_celsius
                    ),
                    target_count=len(targets),
                    weight_minimum=weight_minimum,
                    weight_maximum=weight_maximum,
                    calibration_kind=_motherboard_calibration_kind((zone, component)),
                    profiles=tuple(workload_profiles),
                )
            )
        return tuple(rows)

    def heatmap_full_server_node_evidence_snapshot(
        self,
    ) -> tuple[HeatmapFullServerNodeEvidence, ...]:
        """Return runtime-owned node evidence for the active manual checkpoint."""

        state = self._heatmap_full_server_state
        return state.node_evidence if state else ()

    def set_heatmap_presentation_cadence_hz(self, cadence_hz: int) -> None:
        """Select bounded presentation cadence independently of telemetry."""

        if cadence_hz not in {2, 5}:
            raise ValueError("Heatmap presentation cadence must be 2 Hz or 5 Hz.")
        if cadence_hz == self._heatmap_presentation_cadence_hz:
            return
        self._heatmap_presentation_cadence_hz = cadence_hz
        task = self._heatmap_presentation_task
        if task is not None and not task.done():
            # A cancelled scheduler never performs another tick; its replacement
            # starts with the newly requested period rather than an old sleep.
            self._heatmap_presentation_scheduler_id += 1
            self._heatmap_presentation_task = None
            task.cancel()
        self._ensure_heatmap_presentation_scheduler()

    def heatmap_presentation_cadence_hz(self) -> int:
        """Expose the active development cadence without coupling it to telemetry UI."""

        return self._heatmap_presentation_cadence_hz

    def heatmap_presentation_transition_duration_seconds(self) -> float:
        """Expose the shared time-based transition duration for acceptance logs."""

        return self._heatmap_presentation_smoother.transition_duration_seconds

    def begin_heatmap_presentation_measurement(self) -> None:
        """Reset diagnostics after structural setup and before a probe window."""

        self._heatmap_presentation_smoother.clear_retarget_evidence()
        self._heatmap_presentation_measurement_start = (
            self._heatmap_presentation_scheduler_ticks,
            self._heatmap_presentation_target_changes,
            self._heatmap_presentation_groups_considered,
            self._heatmap_presentation_write_counts(),
        )

    def heatmap_presentation_retarget_evidence_snapshot(
        self,
    ) -> tuple[HeatmapRetargetEvidence, ...]:
        """Return aggregate latest-telemetry-wins continuity evidence."""

        return self._heatmap_presentation_smoother.retarget_evidence

    def heatmap_presentation_diagnostics_snapshot(
        self,
    ) -> HeatmapPresentationDiagnostics:
        """Return scheduler and owned-write evidence for the current window."""

        baseline = self._heatmap_presentation_measurement_start
        current_counts = self._heatmap_presentation_write_counts()
        if baseline is None:
            baseline = (0, 0, 0, HeatmapMaterialWriteCounts())
        ticks, target_changes, groups, previous_counts = baseline
        return HeatmapPresentationDiagnostics(
            cadence_hz=self._heatmap_presentation_cadence_hz,
            scheduler_tick_count=self._heatmap_presentation_scheduler_ticks - ticks,
            telemetry_target_changes=(
                self._heatmap_presentation_target_changes - target_changes
            ),
            semantic_groups_considered=(
                self._heatmap_presentation_groups_considered - groups
            ),
            shader_parameter_writes=(
                current_counts.shader_parameter_writes
                - previous_counts.shader_parameter_writes
            ),
            skipped_unchanged_parameter_writes=(
                current_counts.skipped_unchanged_parameter_writes
                - previous_counts.skipped_unchanged_parameter_writes
            ),
            structural_material_writes=(
                current_counts.structural_material_writes
                - previous_counts.structural_material_writes
            ),
            material_binding_writes=(
                current_counts.material_binding_writes
                - previous_counts.material_binding_writes
            ),
            primvar_st_writes=(
                current_counts.primvar_st_writes - previous_counts.primvar_st_writes
            ),
            material_prim_creations=(
                current_counts.material_prim_creations
                - previous_counts.material_prim_creations
            ),
        )

    def advance_heatmap_presentation_in_kit(self, now: float | None = None) -> bool:
        """Advance one due smoothing tick; ordinary Kit frames never call this path."""

        import omni.usd

        stage = omni.usd.get_context().get_stage()
        if not stage:
            return False
        return self._advance_heatmap_presentation(stage, now or time.monotonic())

    def enable_heatmap_vertical_slice_in_kit(self) -> HeatmapVerticalSliceState:
        """Apply the prepared scalar/material contract to its single target."""

        import omni.usd

        stage = omni.usd.get_context().get_stage()
        if not stage:
            return self._set_heatmap_vertical_slice_state(
                False,
                False,
                "Heatmap vertical slice requires an open stage.",
            )
        return self._apply_heatmap_vertical_slice(stage)

    def refresh_heatmap_telemetry_snapshot(
        self,
        snapshot,
    ) -> HeatmapTelemetrySnapshot | None:
        """Refresh values and quality while preserving the static registry."""

        self._heatmap_current_telemetry_snapshot = snapshot
        registry = self._heatmap_semantic_registry
        if registry is None:
            self._heatmap_telemetry_snapshot = None
            return None
        self._heatmap_telemetry_snapshot = registry.resolve_telemetry(
            self._heatmap_effective_telemetry_snapshot(snapshot)
        )
        if self._heatmap_full_server_material_presenter.active:
            import omni.usd

            stage = omni.usd.get_context().get_stage()
            if stage:
                self._queue_heatmap_full_server_targets(stage)
        elif self._heatmap_material_presenter.active:
            import omni.usd

            stage = omni.usd.get_context().get_stage()
            if stage:
                self._queue_heatmap_vertical_slice_targets(stage)
        return self._heatmap_telemetry_snapshot

    def _queue_heatmap_full_server_targets(self, stage) -> None:
        """Retarget active full-server materials only when provider data changes."""

        targets = self._full_server_group_telemetry_values()
        if not self._heatmap_presentation_matches("full_server", targets):
            self._apply_heatmap_full_server(stage)
            return
        self._queue_heatmap_presentation_targets(targets)

    def _queue_heatmap_vertical_slice_targets(self, stage) -> None:
        """Retarget active GPU03 presentation without rebuilding Session topology."""

        targets = self._vertical_slice_group_telemetry_values()
        if not self._heatmap_presentation_matches("vertical_slice", targets):
            self._apply_heatmap_vertical_slice(stage)
            return
        self._queue_heatmap_presentation_targets(targets)

    def _heatmap_presentation_scope_paths(self) -> tuple[str, ...]:
        """Return the active temporary scope without changing binding identity."""

        calibration_scope = self._heatmap_binding_calibration_scope_path
        if calibration_scope is not None:
            return (calibration_scope,)
        return self._heatmap_test_presentation_scope_paths

    @staticmethod
    def _heatmap_target_is_in_presentation_scope(
        prim_path: str,
        scope_paths: tuple[str, ...],
    ) -> bool:
        """Keep focused tests from materializing unrelated server targets."""

        return not scope_paths or any(
            _path_is_within(prim_path, scope_path) for scope_path in scope_paths
        )

    def _heatmap_focused_test_overrides_xray_precedence(
        self,
        target: HeatmapFullServerTarget,
        scope_paths: tuple[str, ...],
    ) -> bool:
        """Render explicitly selected GPU exterior targets during the focused test."""

        semantic = (
            target.semantic_key.thermal_zone,
            target.semantic_key.thermal_component,
        )
        return bool(scope_paths) and semantic in self.HEATMAP_GPU_EXTERNAL_SEMANTICS

    def _full_server_group_telemetry_values(self) -> dict[str, float]:
        """Extract the active scope's group targets once per provider snapshot."""

        contract = self._heatmap_full_server_contract
        values = self._heatmap_telemetry_snapshot
        if contract is None or values is None:
            return {}
        scope_paths = self._heatmap_presentation_scope_paths()
        groups = {}
        presentation_targets = (
            *contract.renderable_targets,
            *(
                target
                for target in contract.xray_precedence_targets
                if self._heatmap_focused_test_overrides_xray_precedence(
                    target,
                    scope_paths,
                )
            ),
        )
        for target in presentation_targets:
            if not self._heatmap_target_is_in_presentation_scope(
                target.prim_path,
                scope_paths,
            ):
                continue
            current = values.for_prim(target.prim_path)
            if (
                current is None
                or not current.available
                or not isinstance(
                    current.value,
                    (int, float),
                )
            ):
                continue
            groups[target.material_key] = (
                float(current.value) + target.presentation_temperature_offset_celsius
            )
        return groups

    def _vertical_slice_group_telemetry_values(self) -> dict[str, float]:
        """Extract GPU03 target telemetry once per provider snapshot."""

        contract = self._heatmap_vertical_slice_contract
        values = self._heatmap_telemetry_snapshot
        if contract is None or values is None:
            return {}
        groups = {}
        for target in contract.targets:
            current = values.for_prim(target.prim_path)
            if (
                current is None
                or not current.available
                or not isinstance(
                    current.value,
                    (int, float),
                )
            ):
                continue
            groups[target.material_key] = float(current.value)
        return groups

    def _heatmap_presentation_matches(
        self,
        owner: str,
        targets: dict[str, float],
    ) -> bool:
        """Require a structural apply when active material-group membership changes."""

        return (
            self._heatmap_presentation_owner == owner
            and self._heatmap_presentation_smoother.group_keys == tuple(sorted(targets))
        )

    def _queue_heatmap_presentation_targets(
        self,
        targets: dict[str, float],
    ) -> None:
        """Accept latest telemetry targets without presenting a discontinuous jump."""

        changes = self._heatmap_presentation_smoother.set_targets(
            targets,
            now=time.monotonic(),
        )
        self._heatmap_presentation_target_changes += changes
        self._ensure_heatmap_presentation_scheduler()

    def _activate_heatmap_presentation_smoothing(
        self,
        owner: str,
        targets: tuple[HeatmapMaterialTarget, ...],
    ) -> None:
        """Reset dynamic state after an immediate structural material operation."""

        values = {target.material_key: target.telemetry_celsius for target in targets}
        self._heatmap_presentation_smoother.reset(values, now=time.monotonic())
        self._heatmap_presentation_owner = owner
        self._ensure_heatmap_presentation_scheduler()

    def _ensure_heatmap_presentation_scheduler(self) -> None:
        """Own one sleeping scheduler only while dynamic Heatmap presentation exists."""

        if (
            self._heatmap_presentation_owner is None
            or not self._heatmap_presentation_smoother.group_count
        ):
            return
        task = self._heatmap_presentation_task
        if task is not None and not task.done():
            return
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        self._heatmap_presentation_scheduler_id += 1
        scheduler_id = self._heatmap_presentation_scheduler_id
        self._heatmap_presentation_task = asyncio.ensure_future(
            self._run_heatmap_presentation_scheduler(scheduler_id)
        )

    async def _run_heatmap_presentation_scheduler(self, scheduler_id: int) -> None:
        """Yield between bounded dynamic updates; no rendering-frame polling occurs."""

        try:
            while scheduler_id == self._heatmap_presentation_scheduler_id:
                await asyncio.sleep(1.0 / self._heatmap_presentation_cadence_hz)
                if scheduler_id != self._heatmap_presentation_scheduler_id:
                    return
                self.advance_heatmap_presentation_in_kit()
                if self._heatmap_presentation_owner is None:
                    return
        except asyncio.CancelledError:
            return
        finally:
            if scheduler_id == self._heatmap_presentation_scheduler_id:
                self._heatmap_presentation_task = None

    def _advance_heatmap_presentation(self, stage, now: float) -> bool:
        """Write only changed telemetry inputs for one bounded smoothing tick."""

        owner = self._heatmap_presentation_owner
        if owner is None:
            return False
        presenter = (
            self._heatmap_full_server_material_presenter
            if owner == "full_server"
            else self._heatmap_material_presenter
        )
        if not presenter.active:
            self._stop_heatmap_presentation_scheduler()
            return False
        self._heatmap_presentation_scheduler_ticks += 1
        self._heatmap_presentation_groups_considered += (
            self._heatmap_presentation_smoother.group_count
        )
        changed = self._heatmap_presentation_smoother.tick(now=now)
        if not changed:
            return True
        return presenter.update_telemetry(stage, changed).success

    def _stop_heatmap_presentation_scheduler(self, *, owner: str | None = None) -> None:
        """Cancel only the owner's task during disable or structural teardown."""

        if owner is not None and self._heatmap_presentation_owner != owner:
            return
        self._heatmap_presentation_scheduler_id += 1
        task = self._heatmap_presentation_task
        self._heatmap_presentation_task = None
        if task is not None and not task.done():
            task.cancel()
        self._heatmap_presentation_owner = None
        self._heatmap_presentation_smoother.reset({}, now=time.monotonic())

    def _heatmap_presentation_write_counts(self) -> HeatmapMaterialWriteCounts:
        """Read the active presenter's aggregate owned-write counters."""

        owner = self._heatmap_presentation_owner
        if owner == "full_server":
            return self._heatmap_full_server_material_presenter.write_counts
        if owner == "vertical_slice":
            return self._heatmap_material_presenter.write_counts
        return HeatmapMaterialWriteCounts()

    def _heatmap_effective_telemetry_snapshot(self, snapshot):
        """Project only an acceptance focus; production bindings always see all data."""

        if snapshot is None:
            return None
        metric_ids = self._heatmap_acceptance_filter_metric_ids
        if not metric_ids:
            return snapshot
        return TelemetrySnapshot.create(
            schema_version=snapshot.schema_version,
            provider_id=snapshot.provider_id,
            provider_type=snapshot.provider_type,
            timestamp=snapshot.timestamp,
            operational_state=snapshot.operational_state,
            refresh_interval_s=snapshot.refresh_interval_s,
            metrics={
                metric_id: metric
                for metric_id, metric in snapshot.metrics.items()
                if metric_id in metric_ids
            },
        )

    def _clear_heatmap_binding_calibration_filter(self) -> None:
        """Restore complete telemetry resolution without rebuilding the registry."""

        self._heatmap_acceptance_filter_metric_ids = ()
        registry = self._heatmap_semantic_registry
        snapshot = self._heatmap_current_telemetry_snapshot
        if registry is not None:
            self._heatmap_telemetry_snapshot = registry.resolve_telemetry(snapshot)

    def _run_heatmap_asset_preflight(self, stage) -> HeatmapAssetPreflightResult:
        """Validate the production server contract before entering the PCB sandbox."""

        xray_target_paths = tuple(
            path
            for group in self.config.chassis_presentation.xray_target_groups
            for path in group.paths
        )
        return run_heatmap_asset_preflight(
            stage,
            root_path=self.HEATMAP_TEST_SERVER_ROOT_PATH,
            xray_target_paths=xray_target_paths,
        )

    def _build_heatmap_semantic_registry(
        self,
        preflight: HeatmapAssetPreflightResult,
    ) -> HeatmapSemanticRegistry:
        """Build binding evidence from preflight-validated discovery only."""

        registry = build_heatmap_semantic_registry(
            preflight.valid_targets,
            xray_overlap_paths=preflight.xray_overlap_targets,
        )
        self._heatmap_semantic_registry = registry
        self._heatmap_telemetry_snapshot = registry.resolve_telemetry(
            self._heatmap_effective_telemetry_snapshot(
                self._heatmap_current_telemetry_snapshot
            )
        )
        return registry

    def _prepare_heatmap_full_server_contract(
        self,
        preflight: HeatmapAssetPreflightResult,
        registry: HeatmapSemanticRegistry,
    ) -> HeatmapFullServerContract | None:
        """Build all supported semantic groups before any Session presentation."""

        config = self._heatmap_telemetry_config
        if config is None or not preflight.success or not registry.success:
            self._heatmap_full_server_contract = None
            return None
        metadata_by_path = {
            target.prim_path: target for target in preflight.valid_targets
        }
        metric_ids = tuple(
            target.telemetry_binding.metric_id
            for target in registry.targets
            if target.telemetry_binding.metric_id is not None
        )
        try:
            scale_resolution = resolve_server_wide_celsius_scale(config, metric_ids)
        except ValueError as error:
            self._set_heatmap_full_server_state(False, False, str(error))
            return None

        renderable: list[HeatmapFullServerTarget] = []
        xray_precedence: list[HeatmapFullServerTarget] = []
        xray_precedence_paths: list[str] = []
        unavailable_paths: list[str] = []
        unavailable_reasons: dict[str, str] = {}
        group_index = 0
        for semantic_key, paths in registry.semantic_groups.items():
            bindings = tuple(registry.targets_by_prim_path[path] for path in paths)
            binding = bindings[0]
            xray_precedence_paths.extend(
                item.prim_path
                for item in bindings
                if item.presentation_policy.xray_precedence
            )
            telemetry = binding.telemetry_binding
            if not telemetry.available or telemetry.metric_id is None:
                reason = telemetry.unavailable_reason or "Telemetry unavailable."
                unavailable_paths.extend(paths)
                unavailable_reasons.update({path: reason for path in paths})
                continue
            try:
                metadata = tuple(metadata_by_path[path] for path in paths)
                group_weights = _thermal_weights(metadata)
                delta_profiles = _calibrate_group_delta_profiles(
                    config,
                    telemetry.metric_id,
                    metadata,
                )
            except ValueError as error:
                self._set_heatmap_full_server_state(
                    False,
                    False,
                    f"Heatmap calibration failed for {semantic_key.label}: {error}",
                )
                return None
            group_index += 1
            material_key = f"group_{group_index:03d}"
            for target_binding in bindings:
                target_metadata = metadata_by_path[target_binding.prim_path]
                target = HeatmapFullServerTarget(
                    material_key=material_key,
                    prim_path=target_binding.prim_path,
                    semantic_key=target_binding.semantic_key,
                    metric_id=telemetry.metric_id,
                    presentation_temperature_offset_celsius=(
                        telemetry.presentation_temperature_offset_celsius
                        + _psu_presentation_temperature_correction(
                            (
                                semantic_key.thermal_zone,
                                semantic_key.thermal_component,
                            )
                        )
                    ),
                    thermal_weights=tuple(
                        float(value) for value in target_metadata.thermal_weight or ()
                    ),
                    thermal_weight_interpolation=(
                        target_metadata.thermal_weight_interpolation or ""
                    ),
                    thermal_weight_remap=_motherboard_weight_remap(
                        (semantic_key.thermal_zone, semantic_key.thermal_component)
                    ),
                    thermal_weight_minimum=min(group_weights),
                    thermal_weight_maximum=max(group_weights),
                    delta_profiles=delta_profiles,
                )
                if target_binding.presentation_policy.xray_precedence:
                    xray_precedence.append(target)
                else:
                    renderable.append(target)

        all_targets = (*renderable, *xray_precedence)
        used_metric_ids = tuple(sorted({target.metric_id for target in all_targets}))
        self._heatmap_full_server_contract = HeatmapFullServerContract(
            total_thermal_targets=registry.target_count,
            renderable_targets=tuple(renderable),
            unavailable_target_paths=tuple(sorted(unavailable_paths)),
            unavailable_reasons=MappingProxyType(
                dict(sorted(unavailable_reasons.items()))
            ),
            xray_precedence_target_paths=tuple(sorted(xray_precedence_paths)),
            xray_precedence_targets=tuple(xray_precedence),
            scale_resolution=scale_resolution,
            provider_profiles=_provider_profiles(config, used_metric_ids),
            registry_fingerprint=registry.fingerprint,
        )
        return self._heatmap_full_server_contract

    def _set_heatmap_binding_calibration_focus(
        self,
        stage,
        Sdf,
        UsdGeom,
        metric_ids: tuple[str, ...],
        isolation_path: str,
    ) -> HeatmapBindingCalibrationFocus:
        """Render exactly one accepted metric set in one visible hardware scope."""

        contract = self._heatmap_full_server_contract
        registry = self._heatmap_semantic_registry
        snapshot = self._heatmap_current_telemetry_snapshot
        metric_ids = tuple(sorted(set(metric_ids)))
        if contract is None or registry is None or snapshot is None:
            return self._set_heatmap_binding_calibration_focus_state(
                False,
                metric_ids,
                isolation_path,
                (),
                (),
                (),
                "Heatmap binding calibration contract or telemetry is unavailable.",
            )
        current_path = self._heatmap_test_isolation_target_path
        if self._heatmap_test_isolation_active and current_path != isolation_path:
            cleared = self._clear_heatmap_test_isolation(stage, Sdf)
            if not cleared.success:
                return self._set_heatmap_binding_calibration_focus_state(
                    False,
                    metric_ids,
                    isolation_path,
                    (),
                    (),
                    (),
                    cleared.message,
                )
        if not self._heatmap_test_isolation_active:
            isolation = self._enable_heatmap_test_isolation(
                stage,
                Sdf,
                UsdGeom,
                target_path=isolation_path,
            )
            if not isolation.success:
                return self._set_heatmap_binding_calibration_focus_state(
                    False,
                    metric_ids,
                    isolation_path,
                    (),
                    (),
                    (),
                    isolation.message,
                )
        self._heatmap_acceptance_filter_metric_ids = metric_ids
        self._heatmap_binding_calibration_scope_path = isolation_path
        self._heatmap_telemetry_snapshot = registry.resolve_telemetry(
            self._heatmap_effective_telemetry_snapshot(snapshot)
        )
        state = self._apply_heatmap_full_server(stage)
        expected = tuple(
            target.prim_path
            for target in contract.renderable_targets
            if (not metric_ids or target.metric_id in metric_ids)
            and _path_is_within(target.prim_path, isolation_path)
        )
        rendered = state.rendered_target_paths
        foreign = tuple(sorted(set(rendered) - set(expected)))
        missing = tuple(sorted(set(expected) - set(rendered)))
        success = state.success and bool(expected) and not foreign and not missing
        message = state.message
        if not expected:
            message = "No Heatmap target matches the requested acceptance metric."
        elif foreign or missing:
            message = (
                "Heatmap binding calibration rendered an unexpected target set: "
                f"foreign={len(foreign)} missing={len(missing)}."
            )
        return self._set_heatmap_binding_calibration_focus_state(
            success,
            metric_ids,
            isolation_path,
            expected,
            rendered,
            foreign,
            message,
        )

    def _set_heatmap_binding_calibration_focus_state(
        self,
        success: bool,
        metric_ids: tuple[str, ...],
        isolation_path: str,
        expected_target_paths: tuple[str, ...],
        rendered_target_paths: tuple[str, ...],
        foreign_rendered_target_paths: tuple[str, ...],
        message: str,
    ) -> HeatmapBindingCalibrationFocus:
        """Publish only the focus evidence required by the corrective workflow."""

        focus = HeatmapBindingCalibrationFocus(
            success=success,
            metric_ids=metric_ids,
            isolation_path=isolation_path,
            expected_target_paths=expected_target_paths,
            rendered_target_paths=rendered_target_paths,
            foreign_rendered_target_paths=foreign_rendered_target_paths,
            message=message,
        )
        self._heatmap_binding_calibration_focus = focus
        return focus

    def _apply_heatmap_full_server(self, stage) -> HeatmapFullServerState:
        """Present every currently available non-X-Ray full-server target."""

        contract = self._heatmap_full_server_contract
        values = self._heatmap_telemetry_snapshot
        snapshot = self._heatmap_current_telemetry_snapshot
        registry = self._heatmap_semantic_registry
        if contract is None or values is None or snapshot is None or registry is None:
            return self._set_heatmap_full_server_state(
                False,
                False,
                "Heatmap full-server contract or current telemetry is unavailable.",
            )
        material_targets = []
        unavailable_paths = list(contract.unavailable_target_paths)
        scope_paths = self._heatmap_presentation_scope_paths()
        for target in contract.renderable_targets:
            if not self._heatmap_target_is_in_presentation_scope(
                target.prim_path,
                scope_paths,
            ):
                continue
            current = values.for_prim(target.prim_path)
            profile = target.delta_profiles.get(snapshot.operational_state)
            if (
                current is None
                or not current.available
                or not isinstance(
                    current.value,
                    (int, float),
                )
            ):
                unavailable_paths.append(target.prim_path)
                continue
            if profile is None:
                return self._set_heatmap_full_server_state(
                    False,
                    False,
                    "Missing Heatmap delta profile for "
                    f"{target.semantic_key.label}/{snapshot.operational_state}.",
                )
            telemetry_celsius = (
                float(current.value) + target.presentation_temperature_offset_celsius
            )
            try:
                _validate_target_scalar_range(
                    target,
                    telemetry_celsius,
                    current.quality,
                    profile,
                    contract.scale_resolution.scale,
                )
            except ValueError as error:
                return self._set_heatmap_full_server_state(
                    False,
                    False,
                    f"Heatmap scalar evaluation failed at {target.prim_path}: {error}",
                )
            material_targets.append(
                HeatmapMaterialTarget(
                    material_key=target.material_key,
                    prim_path=target.prim_path,
                    thermal_weights=target.thermal_weights,
                    telemetry_celsius=telemetry_celsius,
                    delta_profile=profile,
                    thermal_weight_remap=target.thermal_weight_remap,
                    thermal_weight_minimum=target.thermal_weight_minimum,
                    thermal_weight_maximum=target.thermal_weight_maximum,
                )
            )
        for target in contract.xray_precedence_targets:
            if not self._heatmap_target_is_in_presentation_scope(
                target.prim_path,
                scope_paths,
            ):
                continue
            current = values.for_prim(target.prim_path)
            profile = target.delta_profiles.get(snapshot.operational_state)
            if (
                current is None
                or not current.available
                or not isinstance(
                    current.value,
                    (int, float),
                )
            ):
                unavailable_paths.append(target.prim_path)
                continue
            if profile is None:
                return self._set_heatmap_full_server_state(
                    False,
                    False,
                    "Missing X-Ray-precedence Heatmap profile for "
                    f"{target.semantic_key.label}/{snapshot.operational_state}.",
                )
            telemetry_celsius = (
                float(current.value) + target.presentation_temperature_offset_celsius
            )
            try:
                _validate_target_scalar_range(
                    target,
                    telemetry_celsius,
                    current.quality,
                    profile,
                    contract.scale_resolution.scale,
                )
            except ValueError as error:
                return self._set_heatmap_full_server_state(
                    False,
                    False,
                    "X-Ray-precedence Heatmap scalar failed at "
                    f"{target.prim_path}: {error}",
                )
            if self._heatmap_focused_test_overrides_xray_precedence(
                target,
                scope_paths,
            ):
                material_targets.append(
                    HeatmapMaterialTarget(
                        material_key=target.material_key,
                        prim_path=target.prim_path,
                        thermal_weights=target.thermal_weights,
                        telemetry_celsius=telemetry_celsius,
                        delta_profile=profile,
                        thermal_weight_remap=target.thermal_weight_remap,
                        thermal_weight_minimum=target.thermal_weight_minimum,
                        thermal_weight_maximum=target.thermal_weight_maximum,
                    )
                )
        presenter = self._heatmap_full_server_material_presenter
        result = presenter.refresh(
            stage,
            targets=tuple(material_targets),
            scale=contract.scale_resolution.scale,
            palette=FULL_SPECTRUM_HEATMAP_PALETTE,
        )
        if result.success and result.enabled:
            self._activate_heatmap_presentation_smoothing(
                "full_server",
                tuple(material_targets),
            )
        return self._set_heatmap_full_server_state(
            result.success,
            result.enabled,
            result.message,
            workload=snapshot.operational_state,
            rendered_target_paths=result.target_paths,
            unavailable_target_paths=tuple(sorted(unavailable_paths)),
            material_group_count=result.material_group_count,
            session_binding_count=result.session_binding_count,
            node_evidence=self._heatmap_full_server_node_evidence(
                contract,
                values,
                snapshot.operational_state,
                result.target_paths,
                tuple(sorted(unavailable_paths)),
            ),
        )

    def _clear_heatmap_full_server_in_stage(self, stage) -> HeatmapFullServerState:
        """Release only full-server Heatmap Session materials and bindings."""

        self._stop_heatmap_presentation_scheduler(owner="full_server")
        result = self._heatmap_full_server_material_presenter.disable(stage)
        return self._set_heatmap_full_server_state(
            result.success,
            result.enabled,
            result.message,
            material_group_count=result.material_group_count,
            session_binding_count=result.session_binding_count,
        )

    def _set_heatmap_full_server_state(
        self,
        success: bool,
        enabled: bool,
        message: str,
        *,
        workload: str = "",
        rendered_target_paths: tuple[str, ...] = (),
        unavailable_target_paths: tuple[str, ...] = (),
        material_group_count: int = 0,
        session_binding_count: int = 0,
        node_evidence: tuple[HeatmapFullServerNodeEvidence, ...] = (),
    ) -> HeatmapFullServerState:
        """Publish immutable coverage evidence without exposing presenter state."""

        contract = self._heatmap_full_server_contract
        registry = self._heatmap_semantic_registry
        renderable_targets = contract.renderable_targets if contract else ()
        unavailable_paths = (
            unavailable_target_paths
            if unavailable_target_paths
            else (contract.unavailable_target_paths if contract else ())
        )
        rendered_groups = {
            target.semantic_key
            for target in renderable_targets
            if target.prim_path in rendered_target_paths
        }
        unavailable_groups = {
            registry.targets_by_prim_path[path].semantic_key
            for path in unavailable_paths
            if registry is not None and path in registry.targets_by_prim_path
        }
        state = HeatmapFullServerState(
            success=success,
            enabled=enabled,
            message=message,
            workload=workload,
            total_thermal_targets=contract.total_thermal_targets if contract else 0,
            renderable_target_paths=tuple(
                target.prim_path for target in renderable_targets
            ),
            rendered_target_paths=rendered_target_paths,
            unavailable_target_paths=unavailable_paths,
            xray_precedence_target_paths=(
                contract.xray_precedence_target_paths if contract else ()
            ),
            semantic_group_count=registry.semantic_group_count if registry else 0,
            rendered_semantic_group_count=len(rendered_groups),
            unavailable_semantic_group_count=len(unavailable_groups),
            material_group_count=material_group_count,
            session_binding_count=session_binding_count,
            registry_fingerprint=registry.fingerprint if registry else (),
            scale_resolution=contract.scale_resolution if contract else None,
            node_evidence=node_evidence,
        )
        self._heatmap_full_server_state = state
        return state

    def _heatmap_full_server_node_evidence(
        self,
        contract: HeatmapFullServerContract,
        values: HeatmapTelemetrySnapshot,
        workload: str,
        rendered_paths: tuple[str, ...],
        unavailable_paths: tuple[str, ...],
    ) -> tuple[HeatmapFullServerNodeEvidence, ...]:
        """Prepare only current per-node inspection evidence outside the workflow."""

        registry = self._heatmap_semantic_registry
        if registry is None:
            return ()
        rendered = set(rendered_paths)
        unavailable = set(unavailable_paths)
        grouped: dict[str, list[HeatmapFullServerTarget]] = {}
        for target in contract.renderable_targets:
            grouped.setdefault(target.semantic_key.hardware.label, []).append(target)
        evidence = []
        for identity, targets in sorted(grouped.items(), key=_hardware_sort_key):
            metrics = []
            for metric_id in sorted({target.metric_id for target in targets}):
                metric_targets = tuple(
                    target for target in targets if target.metric_id == metric_id
                )
                current = values.for_prim(metric_targets[0].prim_path)
                temperatures = _derived_temperature_range(
                    metric_targets,
                    current,
                    workload,
                    contract.scale_resolution.scale,
                )
                metrics.append(
                    HeatmapNodeMetricEvidence(
                        metric_id=metric_id,
                        value=(
                            float(current.value)
                            if current and isinstance(current.value, (int, float))
                            else None
                        ),
                        quality=current.quality if current else "unavailable",
                        derived_minimum_celsius=temperatures[0],
                        derived_maximum_celsius=temperatures[1],
                    )
                )
            node_unavailable = tuple(
                sorted(
                    path
                    for path in unavailable
                    if (
                        path in registry.targets_by_prim_path
                        and registry.targets_by_prim_path[
                            path
                        ].semantic_key.hardware.label
                        == identity
                    )
                )
            )
            evidence.append(
                HeatmapFullServerNodeEvidence(
                    hardware_identity=identity,
                    rendered_target_count=sum(
                        target.prim_path in rendered for target in targets
                    ),
                    semantic_groups=tuple(
                        sorted({target.semantic_key.label for target in targets})
                    ),
                    telemetry=tuple(metrics),
                    unavailable_target_paths=node_unavailable,
                )
            )
        return tuple(evidence)

    def _prepare_heatmap_vertical_slice_contract(
        self,
        preflight: HeatmapAssetPreflightResult,
        registry: HeatmapSemanticRegistry,
    ) -> HeatmapVerticalSliceState | None:
        """Resolve every GPU 1/2/3 PCB semantic target through telemetry."""

        config = self._heatmap_telemetry_config
        if config is None or not preflight.success or not registry.success:
            return None
        metadata_by_path = {
            target.prim_path: target for target in preflight.valid_targets
        }
        gpu_targets = tuple(
            target
            for target in registry.targets
            if any(
                target.prim_path.startswith(path + "/")
                for path in self.HEATMAP_GPU_INTERNAL_TARGET_PATHS
            )
            and target.semantic_key.hardware.family == "gpu"
            and target.semantic_key.hardware.instance in {1, 2, 3}
        )
        if not gpu_targets:
            return self._set_heatmap_vertical_slice_state(
                False,
                False,
                "No Heatmap-capable GPU internal targets were resolved.",
            )
        metric_ids = tuple(
            target.telemetry_binding.metric_id
            for target in registry.targets
            if target.telemetry_binding.metric_id is not None
        )
        try:
            scale_resolution = resolve_server_wide_celsius_scale(config, metric_ids)
        except ValueError as error:
            return self._set_heatmap_vertical_slice_state(False, False, str(error))

        targets: list[HeatmapVerticalSliceTarget] = []
        unavailable_paths = []
        for index, binding in enumerate(gpu_targets, start=1):
            metric_id = binding.telemetry_binding.metric_id
            if metric_id is None:
                unavailable_paths.append(binding.prim_path)
                continue
            metadata = metadata_by_path.get(binding.prim_path)
            if metadata is None or metadata.thermal_weight is None:
                return self._set_heatmap_vertical_slice_state(
                    False,
                    False,
                    f"GPU internal target has no thermal weights: {binding.prim_path}.",
                )
            weights = tuple(float(value) for value in metadata.thermal_weight)
            try:
                calibration = _uniform_delta_profiles(config)
            except ValueError as error:
                return self._set_heatmap_vertical_slice_state(
                    False,
                    False,
                    f"GPU internal calibration failed at {binding.prim_path}: {error}",
                )
            targets.append(
                HeatmapVerticalSliceTarget(
                    material_key=f"target_{index:03d}",
                    prim_path=binding.prim_path,
                    semantic_key=binding.semantic_key,
                    metric_id=metric_id,
                    thermal_weights=weights,
                    thermal_weight_interpolation=(
                        metadata.thermal_weight_interpolation or ""
                    ),
                    delta_profiles=calibration,
                )
            )
        if not targets:
            return self._set_heatmap_vertical_slice_state(
                False,
                False,
                "GPU internal demo has no truthfully telemetry-bound Heatmap targets.",
            )
        used_metric_ids = tuple(sorted({target.metric_id for target in targets}))
        self._heatmap_vertical_slice_contract = HeatmapVerticalSliceContract(
            targets=tuple(targets),
            unavailable_target_paths=tuple(sorted(unavailable_paths)),
            scale_resolution=scale_resolution,
            provider_profiles=MappingProxyType(
                {
                    metric_id: MappingProxyType(
                        {
                            workload: (
                                float(profile.numeric[metric_id].target),
                                float(profile.numeric[metric_id].jitter),
                                float(profile.numeric[metric_id].minimum),
                                float(profile.numeric[metric_id].maximum),
                            )
                            for workload, profile in config.modes.items()
                        }
                    )
                    for metric_id in used_metric_ids
                }
            ),
        )
        return self._set_heatmap_vertical_slice_state(
            True,
            False,
            "Heatmap GPU 1/2/3 internal scalar contract is ready.",
            target_path=targets[0].prim_path,
            target_paths=tuple(target.prim_path for target in targets),
            unavailable_target_paths=tuple(sorted(unavailable_paths)),
        )

    def _apply_heatmap_vertical_slice(self, stage) -> HeatmapVerticalSliceState:
        """Present every currently available focused GPU target independently."""

        contract = self._heatmap_vertical_slice_contract
        values = self._heatmap_telemetry_snapshot
        snapshot = self._heatmap_current_telemetry_snapshot
        if contract is None or values is None or snapshot is None:
            return self._set_heatmap_vertical_slice_state(
                False,
                False,
                "Heatmap vertical-slice contract or current telemetry is unavailable.",
            )
        material_targets = []
        unavailable_paths = list(contract.unavailable_target_paths)
        for target in contract.targets:
            current = values.for_prim(target.prim_path)
            profile = target.delta_profiles.get(snapshot.operational_state)
            if (
                current is None
                or not current.available
                or not isinstance(
                    current.value,
                    (int, float),
                )
            ):
                unavailable_paths.append(target.prim_path)
                continue
            if profile is None:
                unavailable_paths.append(target.prim_path)
                continue
            try:
                for weight in (
                    min(target.thermal_weights),
                    max(target.thermal_weights),
                ):
                    evaluate_heatmap_scalar(
                        component_telemetry_celsius=float(current.value),
                        telemetry_quality=current.quality,
                        thermal_weight=weight,
                        delta_profile=profile,
                        scale=contract.scale_resolution.scale,
                    )
            except ValueError as error:
                return self._set_heatmap_vertical_slice_state(
                    False,
                    False,
                    "Heatmap GPU internal scalar evaluation failed at "
                    f"{target.prim_path}: {error}",
                    target_path=target.prim_path,
                )
            material_targets.append(
                HeatmapMaterialTarget(
                    material_key=target.material_key,
                    prim_path=target.prim_path,
                    thermal_weights=target.thermal_weights,
                    telemetry_celsius=float(current.value),
                    delta_profile=profile,
                )
            )
        presenter = self._heatmap_material_presenter
        if material_targets:
            result = presenter.refresh(
                stage,
                targets=tuple(material_targets),
                scale=contract.scale_resolution.scale,
                palette=FULL_SPECTRUM_HEATMAP_PALETTE,
            )
        else:
            result = presenter.disable(stage)
        if result.success and result.enabled:
            self._activate_heatmap_presentation_smoothing(
                "vertical_slice",
                tuple(material_targets),
            )
        elif not result.enabled:
            self._stop_heatmap_presentation_scheduler(owner="vertical_slice")
        return self._set_heatmap_vertical_slice_state(
            result.success,
            result.enabled,
            result.message,
            target_path=material_targets[0].prim_path if material_targets else "",
            target_paths=result.target_paths,
            unavailable_target_paths=tuple(sorted(unavailable_paths)),
            material_creations=result.material_creations,
            parameter_updates=result.parameter_updates,
        )

    def _clear_heatmap_vertical_slice_in_stage(
        self,
        stage,
    ) -> HeatmapVerticalSliceState:
        """Remove only the material presenter's owned Session Layer state."""

        self._stop_heatmap_presentation_scheduler(owner="vertical_slice")
        result = self._heatmap_material_presenter.disable(stage)
        return self._set_heatmap_vertical_slice_state(
            result.success,
            result.enabled,
            result.message,
            target_paths=result.target_paths,
            material_creations=result.material_creations,
            parameter_updates=result.parameter_updates,
        )

    def _set_heatmap_vertical_slice_state(
        self,
        success: bool,
        enabled: bool,
        message: str,
        *,
        target_path: str = "",
        target_paths: tuple[str, ...] = (),
        unavailable_target_paths: tuple[str, ...] = (),
        material_creations: int = 0,
        parameter_updates: int = 0,
    ) -> HeatmapVerticalSliceState:
        state = HeatmapVerticalSliceState(
            success=success,
            enabled=enabled,
            message=message,
            target_path=target_path,
            target_paths=target_paths,
            unavailable_target_paths=unavailable_target_paths,
            material_creations=material_creations,
            parameter_updates=parameter_updates,
        )
        self._heatmap_vertical_slice_state = state
        return state

    def _enable_heatmap_test_isolation(
        self,
        stage,
        Sdf,
        UsdGeom,
        *,
        target_path: str | None = None,
        target_paths: tuple[str, ...] | None = None,
    ):
        """Author only visibility opinions needed to reveal requested subtrees."""

        target_paths = target_paths or (
            (target_path,)
            if target_path is not None
            else self._resolve_heatmap_focused_scope_paths(stage)
        )
        target_path = target_path or target_paths[-1]
        if self._heatmap_test_isolation_active:
            return HeatmapTestIsolationResult(
                success=True,
                enabled=True,
                message="Heatmap test isolation is already enabled.",
                target_path=self._heatmap_test_isolation_target_path or target_path,
                target_paths=target_paths,
                owned_visibility_paths=self._heatmap_test_isolation_owned_paths(),
            )

        try:
            visibility_by_path = self._heatmap_test_isolation_visibility_plan(
                stage,
                UsdGeom,
                target_paths=target_paths,
            )
        except RuntimeError as error:
            return HeatmapTestIsolationResult(
                success=False,
                enabled=False,
                message=str(error),
                target_path=target_path,
                target_paths=target_paths,
            )

        previous_target = stage.GetEditTarget()
        stage.SetEditTarget(stage.GetSessionLayer())
        try:
            with Sdf.ChangeBlock():
                for path, visibility in visibility_by_path.items():
                    self._capture_heatmap_test_visibility_spec(stage, path, Sdf)
                    prim = stage.GetPrimAtPath(path)
                    UsdGeom.Imageable(prim).CreateVisibilityAttr().Set(visibility)
            self._heatmap_test_isolation_active = True
            self._heatmap_test_isolation_target_path = target_path
        except Exception as error:  # noqa: BLE001 - restore the prior scene state.
            self._restore_heatmap_test_visibility_state(stage, Sdf)
            return HeatmapTestIsolationResult(
                success=False,
                enabled=False,
                message=f"Heatmap test isolation failed: {error}",
                target_path=target_path,
                target_paths=target_paths,
            )
        finally:
            stage.SetEditTarget(previous_target)

        return HeatmapTestIsolationResult(
            success=True,
            enabled=True,
            message=_heatmap_isolation_enabled_message(target_paths),
            target_path=target_path,
            target_paths=target_paths,
            owned_visibility_paths=self._heatmap_test_isolation_owned_paths(),
        )

    def _clear_heatmap_test_isolation(self, stage, Sdf):
        """Release only Session visibility properties captured by this feature."""

        target_path = (
            self._heatmap_test_isolation_target_path or self.HEATMAP_TEST_TARGET_PATH
        )
        if not self._heatmap_test_isolation_active:
            return HeatmapTestIsolationResult(
                success=True,
                enabled=False,
                message="Heatmap test isolation is already disabled.",
                target_path=target_path,
            )

        previous_target = stage.GetEditTarget()
        stage.SetEditTarget(stage.GetSessionLayer())
        try:
            self._restore_heatmap_test_visibility_state(stage, Sdf)
        except (
            Exception
        ) as error:  # noqa: BLE001 - report deterministic cleanup failure.
            return HeatmapTestIsolationResult(
                success=False,
                enabled=True,
                message=f"Heatmap test isolation restore failed: {error}",
                target_path=target_path,
                owned_visibility_paths=self._heatmap_test_isolation_owned_paths(),
            )
        finally:
            stage.SetEditTarget(previous_target)

        return HeatmapTestIsolationResult(
            success=True,
            enabled=False,
            message="Heatmap test isolation restored the prior scene presentation.",
            target_path=target_path,
        )

    def _heatmap_test_isolation_visibility_plan(
        self,
        stage,
        UsdGeom,
        target_path: str | None = None,
        *,
        target_paths: tuple[str, ...] | None = None,
    ):
        """Return minimal visibility mutations for one or more preserved paths."""

        target_paths = target_paths or (
            (target_path,)
            if target_path is not None
            else self._resolve_heatmap_focused_scope_paths(stage)
        )
        root = stage.GetPrimAtPath(self.HEATMAP_TEST_SERVER_ROOT_PATH)
        if not root or not root.IsValid():
            raise RuntimeError(
                "Heatmap test isolation target root is unavailable: "
                f"{self.HEATMAP_TEST_SERVER_ROOT_PATH}."
            )
        chains = []
        for requested_path in target_paths:
            target = stage.GetPrimAtPath(requested_path)
            if not target or not target.IsValid():
                raise RuntimeError(
                    "Heatmap test isolation target is unavailable: "
                    f"{requested_path}."
                )
            chain = [target]
            current = target
            while str(current.GetPath()) != self.HEATMAP_TEST_SERVER_ROOT_PATH:
                current = current.GetParent()
                if not current or not current.IsValid():
                    raise RuntimeError(
                        "Heatmap test isolation target is not beneath server root: "
                        f"{requested_path}."
                    )
                chain.append(current)
            chains.append(tuple(reversed(chain)))

        preserved_paths = {str(prim.GetPath()) for chain in chains for prim in chain}
        visibility_by_path = {}
        for chain in chains:
            visibility_by_path[str(chain[-1].GetPath())] = UsdGeom.Tokens.inherited
            for ancestor in chain[1:-1]:
                visibility_by_path[str(ancestor.GetPath())] = UsdGeom.Tokens.inherited
            for parent in chain[:-1]:
                for sibling in parent.GetChildren():
                    sibling_path = str(sibling.GetPath())
                    if sibling_path not in preserved_paths:
                        for path in _visibility_override_paths(sibling, UsdGeom):
                            visibility_by_path[path] = UsdGeom.Tokens.invisible
        return visibility_by_path

    def _resolve_heatmap_focused_scope_paths(self, stage) -> tuple[str, ...]:
        """Resolve the focused server hardware without mutating authored USD."""

        ram_assembly = stage.GetPrimAtPath(self.HEATMAP_RAM_ASSEMBLY_PATH)
        if not ram_assembly or not ram_assembly.IsValid():
            raise RuntimeError(
                "Heatmap test isolation RAM assembly is unavailable: "
                f"{self.HEATMAP_RAM_ASSEMBLY_PATH}."
            )
        ram_paths = tuple(
            sorted(str(prim.GetPath()) for prim in ram_assembly.GetChildren())
        )
        if len(ram_paths) != 8:
            raise RuntimeError(
                "Heatmap test isolation requires eight RAM module instances; "
                f"resolved {len(ram_paths)} below {self.HEATMAP_RAM_ASSEMBLY_PATH}."
            )
        for path in self.HEATMAP_CPU_COOLER_THERMAL_PATHS:
            cooler_prim = stage.GetPrimAtPath(path)
            if not cooler_prim or not cooler_prim.IsValid():
                raise RuntimeError(
                    "Heatmap test isolation CPU cooler render path is unavailable: "
                    f"{path}."
                )
        for path in self.HEATMAP_GPU_INTERNAL_TARGET_PATHS:
            gpu_prim = stage.GetPrimAtPath(path)
            if not gpu_prim or not gpu_prim.IsValid():
                raise RuntimeError(
                    "Heatmap test isolation GPU internal path is unavailable: "
                    f"{path}."
                )
        gpu_plug_paths = self._resolve_heatmap_gpu_plug_paths(stage)
        gpu_external_paths = self._resolve_heatmap_gpu_external_paths(stage)
        psu_thermal_paths = self._resolve_heatmap_psu_thermal_paths(stage)
        nic_prim = stage.GetPrimAtPath(self.HEATMAP_NIC_RENDER_PATH)
        if not nic_prim or not nic_prim.IsValid():
            raise RuntimeError(
                "Heatmap test isolation ConnectX-7 render path is unavailable: "
                f"{self.HEATMAP_NIC_RENDER_PATH}."
            )
        return (
            self.HEATMAP_MOTHERBOARD_PATH,
            *ram_paths,
            *self.HEATMAP_CPU_COOLER_THERMAL_PATHS,
            *self.HEATMAP_GPU_INTERNAL_TARGET_PATHS,
            *gpu_plug_paths,
            *gpu_external_paths,
            *psu_thermal_paths,
            self.HEATMAP_NIC_RENDER_PATH,
        )

    def _resolve_heatmap_gpu_plug_paths(self, stage) -> tuple[str, ...]:
        """Resolve every authored GPU plug target without leaf-path rules."""

        paths_by_gpu = tuple(
            tuple(
                target.prim_path
                for target in discover_thermal_geometry(stage, gpu_root)
                if (
                    target.thermal_zone,
                    target.thermal_component,
                )
                == self.HEATMAP_GPU_PLUG_SEMANTIC
            )
            for gpu_root in self.HEATMAP_GPU_ROOT_PATHS
        )
        if any(
            len(paths) != self.HEATMAP_GPU_PLUG_TARGETS_PER_GPU
            for paths in paths_by_gpu
        ):
            counts = ", ".join(str(len(paths)) for paths in paths_by_gpu)
            raise RuntimeError(
                "Heatmap test isolation requires four gpu_body/plug targets per "
                f"GPU; resolved {counts}."
            )
        return tuple(path for paths in paths_by_gpu for path in paths)

    def _resolve_heatmap_gpu_external_paths(self, stage) -> tuple[str, ...]:
        """Resolve GPU shrouds and blowers by their authored Heatmap semantics."""

        paths_by_gpu = tuple(
            tuple(
                target.prim_path
                for target in discover_thermal_geometry(stage, gpu_root)
                if (
                    target.thermal_zone,
                    target.thermal_component,
                )
                in self.HEATMAP_GPU_EXTERNAL_SEMANTICS
            )
            for gpu_root in self.HEATMAP_GPU_ROOT_PATHS
        )
        if any(not paths for paths in paths_by_gpu):
            counts = ", ".join(str(len(paths)) for paths in paths_by_gpu)
            raise RuntimeError(
                "Heatmap test isolation requires GPU shroud/blower targets per "
                f"GPU; resolved {counts}."
            )
        return tuple(path for paths in paths_by_gpu for path in paths)

    def _resolve_heatmap_psu_thermal_paths(self, stage) -> tuple[str, ...]:
        """Resolve only nonignored thermally annotated PSU leaves."""

        paths = tuple(
            sorted(
                target.prim_path
                for target in discover_thermal_geometry(stage, self.HEATMAP_PSU_PATH)
                if target.thermal_zone is not None
                and target.thermal_component is not None
                and target.thermal_weight is not None
                and (target.thermal_zone, target.thermal_component)
                != ("ignore", "ignore")
            )
        )
        if not paths:
            raise RuntimeError(
                "Heatmap test isolation requires nonignored PSU thermal targets."
            )
        return paths

    def _heatmap_focused_isolation_evidence(
        self,
        stage,
        UsdGeom,
        *,
        target_paths: tuple[str, ...],
        owned_visibility_paths: tuple[str, ...],
    ) -> HeatmapFocusedIsolationEvidence:
        """Check the temporary scope without changing any USD opinions."""

        motherboard = stage.GetPrimAtPath(self.HEATMAP_MOTHERBOARD_PATH)
        ram_paths = tuple(
            path
            for path in target_paths
            if path.startswith(f"{self.HEATMAP_RAM_ASSEMBLY_PATH}/ram_")
        )
        cooler_paths = tuple(
            path
            for path in target_paths
            if path.startswith(f"{self.HEATMAP_CPU_COOLER_RENDER_PATH}/")
        )
        gpu_paths = tuple(
            path
            for path in target_paths
            if path in self.HEATMAP_GPU_INTERNAL_TARGET_PATHS
        )
        gpu_plug_path_set = set(self._resolve_heatmap_gpu_plug_paths(stage))
        gpu_plug_paths = tuple(
            path for path in target_paths if path in gpu_plug_path_set
        )
        gpu_external_paths = tuple(
            path
            for path in target_paths
            if path.startswith(self.HEATMAP_COMPUTE_PATH)
            and path not in self.HEATMAP_GPU_INTERNAL_TARGET_PATHS
            and path not in gpu_plug_path_set
        )
        visible_ram_paths = tuple(
            path
            for path in ram_paths
            if _computed_prim_visibility(stage, UsdGeom, path)
            == UsdGeom.Tokens.inherited
        )
        visible_cooler_paths = tuple(
            path
            for path in cooler_paths
            if _computed_prim_visibility(stage, UsdGeom, path)
            == UsdGeom.Tokens.inherited
        )
        visible_gpu_paths = tuple(
            path
            for path in gpu_paths
            if _computed_prim_visibility(stage, UsdGeom, path)
            == UsdGeom.Tokens.inherited
        )
        visible_gpu_plug_paths = tuple(
            path
            for path in gpu_plug_paths
            if _computed_prim_visibility(stage, UsdGeom, path)
            == UsdGeom.Tokens.inherited
        )
        visible_gpu_external_paths = tuple(
            path
            for path in gpu_external_paths
            if _computed_prim_visibility(stage, UsdGeom, path)
            == UsdGeom.Tokens.inherited
        )
        psu_thermal_paths = tuple(
            path
            for path in target_paths
            if path.startswith(f"{self.HEATMAP_PSU_PATH}/")
        )
        visible_psu_thermal_paths = tuple(
            path
            for path in psu_thermal_paths
            if _computed_prim_visibility(stage, UsdGeom, path)
            == UsdGeom.Tokens.inherited
        )
        nic_visible = (
            self.HEATMAP_NIC_RENDER_PATH in target_paths
            and _computed_prim_visibility(
                stage,
                UsdGeom,
                self.HEATMAP_NIC_RENDER_PATH,
            )
            == UsdGeom.Tokens.inherited
        )
        cooler_fan = stage.GetPrimAtPath(self.HEATMAP_CPU_COOLER_FAN_PATH)
        cooler_fan_paths = _first_imageable_visibility_paths(cooler_fan, UsdGeom)
        cooler_fan_hidden = bool(cooler_fan_paths) and all(
            _computed_prim_visibility(stage, UsdGeom, path) == UsdGeom.Tokens.invisible
            for path in cooler_fan_paths
        )
        server_root = stage.GetPrimAtPath(self.HEATMAP_TEST_SERVER_ROOT_PATH)
        preserved_root_paths = {
            self.HEATMAP_MOTHERBOARD_PATH,
            self.HEATMAP_RAM_ASSEMBLY_PATH,
            self.HEATMAP_COMPUTE_PATH,
            self.HEATMAP_CPU_COOLER_PATH,
            self.HEATMAP_NIC_PATH,
            self.HEATMAP_POWER_PATH,
        }
        unrelated_hidden = all(
            _authored_prim_visibility(stage, UsdGeom, str(child.GetPath()))
            == UsdGeom.Tokens.invisible
            for child in server_root.GetChildren()
            if str(child.GetPath()) not in preserved_root_paths
        )
        outside_untouched = all(
            path.startswith(f"{self.HEATMAP_TEST_SERVER_ROOT_PATH}/")
            for path in owned_visibility_paths
        )
        motherboard_visible = bool(
            motherboard
            and motherboard.IsValid()
            and _computed_prim_visibility(
                stage,
                UsdGeom,
                self.HEATMAP_MOTHERBOARD_PATH,
            )
            == UsdGeom.Tokens.inherited
        )
        ready = bool(
            motherboard_visible
            and len(ram_paths) == 8
            and visible_ram_paths == ram_paths
            and cooler_paths == self.HEATMAP_CPU_COOLER_THERMAL_PATHS
            and visible_cooler_paths == cooler_paths
            and gpu_paths == self.HEATMAP_GPU_INTERNAL_TARGET_PATHS
            and visible_gpu_paths == gpu_paths
            and len(gpu_plug_paths)
            == len(self.HEATMAP_GPU_ROOT_PATHS) * self.HEATMAP_GPU_PLUG_TARGETS_PER_GPU
            and visible_gpu_plug_paths == gpu_plug_paths
            and bool(gpu_external_paths)
            and visible_gpu_external_paths == gpu_external_paths
            and bool(psu_thermal_paths)
            and visible_psu_thermal_paths == psu_thermal_paths
            and nic_visible
            and cooler_fan_hidden
            and unrelated_hidden
            and outside_untouched
        )
        return HeatmapFocusedIsolationEvidence(
            ready=ready,
            motherboard_path=self.HEATMAP_MOTHERBOARD_PATH,
            motherboard_visible=motherboard_visible,
            ram_module_paths=ram_paths,
            visible_ram_module_paths=visible_ram_paths,
            cpu_cooler_render_paths=cooler_paths,
            visible_cpu_cooler_render_paths=visible_cooler_paths,
            cpu_cooler_fan_path=self.HEATMAP_CPU_COOLER_FAN_PATH,
            cpu_cooler_fan_hidden=cooler_fan_hidden,
            gpu_internal_paths=gpu_paths,
            visible_gpu_internal_paths=visible_gpu_paths,
            gpu_plug_paths=gpu_plug_paths,
            visible_gpu_plug_paths=visible_gpu_plug_paths,
            nic_render_path=self.HEATMAP_NIC_RENDER_PATH,
            nic_visible=nic_visible,
            unrelated_server_hardware_hidden=unrelated_hidden,
            outside_server_visibility_untouched=outside_untouched,
        )

    def _discard_stale_heatmap_test_isolation_state(self, stage) -> None:
        """Never apply old-stage snapshots to a replacement Session Layer."""

        session_layer_id = stage.GetSessionLayer().identifier
        if self._heatmap_test_isolation_session_layer_id != session_layer_id:
            self._heatmap_test_isolation_session_layer_id = session_layer_id
            self._reset_heatmap_test_isolation_state(keep_session_layer_id=True)

    def _capture_heatmap_test_visibility_spec(self, stage, path, Sdf) -> None:
        """Store one exact prior Session visibility spec before feature mutation."""

        property_path = Sdf.Path(path).AppendProperty("visibility")
        key = str(property_path)
        if key in self._heatmap_test_isolation_visibility_snapshots:
            return
        session_layer = stage.GetSessionLayer()
        self._capture_heatmap_test_created_scope_paths(
            session_layer,
            property_path.GetPrimPath(),
            Sdf,
        )
        if session_layer.GetPropertyAtPath(property_path) is None:
            self._heatmap_test_isolation_visibility_snapshots[key] = None
            return
        snapshot = Sdf.Layer.CreateAnonymous("DTRS_HeatmapTestIsolationSnapshot.usda")
        Sdf.CreatePrimInLayer(snapshot, property_path.GetPrimPath())
        if not Sdf.CopySpec(session_layer, property_path, snapshot, property_path):
            raise RuntimeError(
                f"Could not snapshot Session visibility {property_path}."
            )
        self._heatmap_test_isolation_visibility_snapshots[key] = snapshot

    def _restore_heatmap_test_visibility_state(self, stage, Sdf) -> None:
        """Remove feature opinions and replay only captured Session visibility specs."""

        with Sdf.ChangeBlock():
            for (
                key,
                snapshot,
            ) in self._heatmap_test_isolation_visibility_snapshots.items():
                property_path = Sdf.Path(key)
                self._remove_heatmap_test_visibility_spec(stage, property_path)
                if snapshot is not None and not Sdf.CopySpec(
                    snapshot,
                    property_path,
                    stage.GetSessionLayer(),
                    property_path,
                ):
                    raise RuntimeError(
                        f"Could not restore Session visibility {property_path}."
                    )
        self._remove_empty_heatmap_test_scopes(stage, Sdf)
        self._reset_heatmap_test_isolation_state()

    def _capture_heatmap_test_created_scope_paths(
        self,
        session_layer,
        prim_path,
        Sdf,
    ) -> None:
        """Remember only Session overs created by visibility isolation."""

        current = prim_path
        while current != Sdf.Path.absoluteRootPath:
            if session_layer.GetPrimAtPath(current) is None:
                self._heatmap_test_isolation_created_scope_paths.add(str(current))
            current = current.GetParentPath()

    def _remove_empty_heatmap_test_scopes(self, stage, Sdf) -> None:
        """Erase only empty Session overs introduced by visibility isolation."""

        session_layer = stage.GetSessionLayer()
        for path in sorted(
            self._heatmap_test_isolation_created_scope_paths,
            key=lambda item: item.count("/"),
            reverse=True,
        ):
            sdf_path = Sdf.Path(path)
            prim_spec = session_layer.GetPrimAtPath(sdf_path)
            if prim_spec is None or prim_spec.nameChildren or prim_spec.properties:
                continue
            parent = session_layer.GetPrimAtPath(sdf_path.GetParentPath())
            if parent is not None:
                del parent.nameChildren[prim_spec.name]

    @staticmethod
    def _remove_heatmap_test_visibility_spec(stage, property_path) -> None:
        """Remove an actual Session visibility property rather than setting visible."""

        session_layer = stage.GetSessionLayer()
        property_spec = session_layer.GetPropertyAtPath(property_path)
        if property_spec is None:
            return
        prim_spec = session_layer.GetPrimAtPath(property_path.GetPrimPath())
        if prim_spec is None:
            raise RuntimeError(
                f"Session visibility owner is missing for {property_path}."
            )
        prim_spec.RemoveProperty(property_spec)
        if session_layer.GetPropertyAtPath(property_path) is not None:
            raise RuntimeError(f"Could not remove Session visibility {property_path}.")

    def _heatmap_test_isolation_owned_paths(self) -> tuple[str, ...]:
        """Return the visibility property paths currently owned by this feature."""

        return tuple(sorted(self._heatmap_test_isolation_visibility_snapshots))

    def _reset_heatmap_test_isolation_state(
        self, *, keep_session_layer_id: bool = False
    ) -> None:
        """Forget only controller-held ownership records after successful cleanup."""

        if not keep_session_layer_id:
            self._heatmap_test_isolation_session_layer_id = None
        self._heatmap_test_isolation_visibility_snapshots.clear()
        self._heatmap_test_isolation_created_scope_paths.clear()
        self._heatmap_test_isolation_active = False
        self._heatmap_test_isolation_target_path = None


def _gpu03_gradient_sort_key(item) -> tuple[str, str, str]:
    """Keep GPU03 gradient audit groups deterministic for logs and tests."""

    zone, component, metric_id = item[0]
    return zone, component, metric_id


def _derived_temperature_range(
    targets,
    current,
    workload: str,
    scale,
) -> tuple[float | None, float | None]:
    """Derive the reachable displayed range for one node telemetry channel."""

    if (
        current is None
        or not current.available
        or not isinstance(
            current.value,
            (int, float),
        )
    ):
        return None, None
    temperatures = []
    for target in targets:
        profile = target.delta_profiles.get(workload)
        if profile is None or not target.thermal_weights:
            continue
        telemetry_celsius = (
            float(current.value) + target.presentation_temperature_offset_celsius
        )
        for weight in (min(target.thermal_weights), max(target.thermal_weights)):
            result = evaluate_heatmap_scalar(
                component_telemetry_celsius=telemetry_celsius,
                telemetry_quality=current.quality,
                thermal_weight=weight,
                delta_profile=profile,
                scale=scale,
                thermal_weight_minimum=target.thermal_weight_minimum,
                thermal_weight_maximum=target.thermal_weight_maximum,
                thermal_weight_remap=target.thermal_weight_remap,
            )
            if result.display_temperature_celsius is not None:
                temperatures.append(result.display_temperature_celsius)
    if not temperatures:
        return None, None
    return min(temperatures), max(temperatures)


def _hardware_sort_key(item) -> tuple[int, str]:
    """Keep full-server hardware evidence in a stable human inspection order."""

    label = str(item[0])
    order = {
        "GPU 1": 10,
        "GPU 2": 20,
        "GPU 3": 30,
        "CPU": 40,
        "NIC": 50,
        "PSU": 60,
        "Motherboard": 70,
    }
    return order.get(label, 100), label


def _heatmap_workload_order(profiles: Mapping[str, object]) -> tuple[str, ...]:
    """Keep Heatmap evidence in the provider workload order."""

    preferred = ("Idle", "Nominal", "Surge", "Critical")
    ordered = tuple(workload for workload in preferred if workload in profiles)
    extras = tuple(
        sorted(workload for workload in profiles if workload not in preferred)
    )
    return (*ordered, *extras)


def _validate_target_scalar_range(
    target,
    telemetry_celsius: float,
    telemetry_quality: str,
    profile: DeltaProfile,
    scale,
) -> None:
    """Reject an invalid endpoint before this target reaches material presentation."""

    if not target.thermal_weights:
        raise ValueError("missing thermal_weight values")
    for weight in (min(target.thermal_weights), max(target.thermal_weights)):
        result = evaluate_heatmap_scalar(
            component_telemetry_celsius=telemetry_celsius,
            telemetry_quality=telemetry_quality,
            thermal_weight=weight,
            delta_profile=profile,
            scale=scale,
            thermal_weight_minimum=target.thermal_weight_minimum,
            thermal_weight_maximum=target.thermal_weight_maximum,
            thermal_weight_remap=target.thermal_weight_remap,
        )
        if not result.available:
            raise ValueError(result.reason or "unavailable scalar")


def _path_is_within(path: str, scope_path: str) -> bool:
    """Match a USD path only when it is the scope root or its descendant."""

    normalized_scope = scope_path.rstrip("/")
    return path == normalized_scope or path.startswith(f"{normalized_scope}/")


def _authored_prim_visibility(stage, UsdGeom, path: str) -> str:
    """Return the local authored visibility token for focused evidence."""

    prim = stage.GetPrimAtPath(path)
    if not prim or not prim.IsValid():
        return UsdGeom.Tokens.invisible
    value = UsdGeom.Imageable(prim).GetVisibilityAttr().Get()
    return value or UsdGeom.Tokens.inherited


def _first_imageable_visibility_paths(prim, _UsdGeom) -> tuple[str, ...]:
    """Return the first drawable prims beneath a possibly non-imageable scope."""

    if not prim or not prim.IsValid():
        return ()

    def imageable_paths(candidate) -> tuple[str, ...]:
        if _UsdGeom.Imageable(candidate):
            return (str(candidate.GetPath()),)
        return tuple(
            path for child in candidate.GetChildren() for path in imageable_paths(child)
        )

    return imageable_paths(prim)


def _computed_prim_visibility(stage, UsdGeom, path: str) -> str:
    """Return inherited USD visibility for one resolved stage prim."""

    prim = stage.GetPrimAtPath(path)
    if not prim or not prim.IsValid():
        return UsdGeom.Tokens.invisible
    return UsdGeom.Imageable(prim).ComputeVisibility()


def _heatmap_isolation_enabled_message(target_paths: tuple[str, ...]) -> str:
    """Describe the focused subtrees without duplicating their UI labels."""

    count = len(target_paths)
    noun = "subtree" if count == 1 else "subtrees"
    return f"Heatmap test isolation enabled for {count} focused {noun}."


def _visibility_override_paths(prim, _UsdGeom) -> tuple[str, ...]:
    """Hide the root drawable prims of one sibling subtree."""

    return _first_imageable_visibility_paths(prim, _UsdGeom)


def _thermal_weights(metadata: tuple[object, ...]) -> tuple[float, ...]:
    """Flatten validated authored thermal weights without consulting previews."""

    weights = tuple(
        float(weight)
        for target in metadata
        for weight in (getattr(target, "thermal_weight", None) or ())
    )
    if not weights:
        raise ValueError("missing thermal_weight values")
    return weights


def _calibrate_group_delta_profiles(
    telemetry_config,
    _metric_id: str,
    metadata: tuple[object, ...],
) -> Mapping[str, DeltaProfile]:
    """Return the one approved delta profile for every valid Heatmap target."""

    if not _thermal_weights(metadata):
        raise ValueError("missing thermal_weight values")
    return _uniform_delta_profiles(telemetry_config)


def _provider_profiles(
    telemetry_config,
    metric_ids: tuple[str, ...],
) -> Mapping[str, Mapping[str, tuple[float, float, float, float]]]:
    """Retain provider target/jitter/min/max evidence for each bound metric."""

    return MappingProxyType(
        {
            metric_id: MappingProxyType(
                {
                    workload: resolve_provider_temperature_profile(
                        telemetry_config,
                        metric_id,
                        workload,
                    )
                    for workload in telemetry_config.modes
                }
            )
            for metric_id in metric_ids
        }
    )


def _uniform_delta_profiles(telemetry_config) -> Mapping[str, DeltaProfile]:
    """Use the one source-controlled delta interval across all workloads."""

    return MappingProxyType(
        {workload: DEFAULT_HEATMAP_DELTA_PROFILE for workload in telemetry_config.modes}
    )


def _psu_presentation_temperature_correction(
    semantic: tuple[str | None, str | None],
) -> float:
    """Apply approved radiator-only offsets without changing PSU telemetry bindings."""

    return {
        ("psu_main_radiator", "radiator"): 16.0,
        ("psu_small_radiator", "radiator"): 4.0,
    }.get(semantic, 0.0)


def _motherboard_weight_remap(
    semantic: tuple[str | None, str | None],
) -> str:
    """Select the temporary cold-biased distribution without changing deltas."""

    if semantic in {
        ("mb_nvme", "nvme_heatsink_a"),
        ("mb_nvme", "nvme_heatsink_b"),
        ("mb_pcie_gpu", "pcie_gpu_slot"),
        ("memory", "dimm_slot"),
        ("motherboard_passive", "heatsink"),
        ("motherboard_power", "power_connector"),
        ("vrm_east", "vrm_heatsink"),
        ("vrm_west", "vrm_heatsink"),
    }:
        return THERMAL_WEIGHT_REMAP_COLD_BIASED
    return THERMAL_WEIGHT_REMAP_LINEAR


def _motherboard_calibration_kind(
    _semantic: tuple[str, str],
) -> str:
    """Label the uniform profile in motherboard diagnostic evidence."""

    return "UNIFORM delta=[-10.0, +10.0] C"
