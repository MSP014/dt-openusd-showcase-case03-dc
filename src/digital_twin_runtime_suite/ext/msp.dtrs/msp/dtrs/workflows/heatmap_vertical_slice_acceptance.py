"""Guided manual review for the three-GPU internal Heatmap demo."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable

from digital_twin_runtime_suite.app.heatmaps.scalar import effective_delta_range
from digital_twin_runtime_suite.app.manual_acceptance import GuidedAcceptanceSession
from digital_twin_runtime_suite.app.status_log import format_dtrs_status_block


class HeatmapVerticalSliceAcceptanceWorkflow:
    """Own one three-GPU visual verdict and exact Session restoration proof."""

    _CHECKS = ("GPU_INTERNALS_PCB_PRESENTATION", "APPEARANCE_RESTORATION")
    _CHANNEL_COUNTS = {
        "gpu_1_hotspot_temp_c": 1,
        "gpu_1_memory_temp_c": 8,
        "gpu_1_temp_c": 51,
        "gpu_2_hotspot_temp_c": 1,
        "gpu_2_memory_temp_c": 8,
        "gpu_2_temp_c": 51,
        "gpu_3_hotspot_temp_c": 1,
        "gpu_3_memory_temp_c": 8,
        "gpu_3_temp_c": 51,
    }

    def __init__(
        self,
        controller,
        *,
        log_warning: Callable[[str], None],
        append_local_timestamp: Callable[[str], str],
        set_manual_verdict_enabled: Callable[[bool], None],
        restoration_action_label: Callable[[], str],
    ) -> None:
        self._controller = controller
        self._log_warning = log_warning
        self._append_local_timestamp = append_local_timestamp
        self._set_manual_verdict_enabled = set_manual_verdict_enabled
        self._restoration_action_label = restoration_action_label
        self._session: GuidedAcceptanceSession | None = None
        self._waiting_check: str | None = None
        self._manual_failures: list[str] = []
        self._target_paths: tuple[str, ...] = ()
        self._registry_fingerprint = ()
        self._gradient_audit = ()

    @property
    def active(self) -> bool:
        """Return whether this workflow exclusively owns Heatmap verdict controls."""

        return self._session is not None and not self._session.terminal_emitted

    def start(self, result) -> None:
        """Prepare the isolated three-GPU audit without early presentation."""

        self.cancel()
        self._session = GuidedAcceptanceSession(self._CHECKS)
        self._session.begin()
        preflight = getattr(result, "preflight", None)
        registry = getattr(result, "registry", None)
        state = getattr(result, "vertical_slice", None)
        if not result.success or preflight is None or not preflight.success:
            self._fail("GPU internal isolation or Heatmap preflight did not pass.")
            return
        if registry is None or not registry.success:
            self._fail("Heatmap semantic registry did not pass.")
            return
        if state is None or not state.success:
            detail = state.message if state else "missing GPU internal scalar contract"
            self._fail(f"GPU internal contract preparation failed: {detail}")
            return
        contract = self._controller.heatmap_vertical_slice_contract_snapshot()
        if contract is None or not self._channel_contract_is_valid(contract):
            return
        self._target_paths = tuple(target.prim_path for target in contract.targets)
        self._registry_fingerprint = registry.fingerprint
        self._gradient_audit = self._controller.heatmap_gpu03_gradient_audit_snapshot()
        if not self._gradient_audit:
            self._fail("GPU internal authored thermal-weight audit is unavailable.")
            return
        scale = contract.scale_resolution.scale
        self._report("START", "GPU 1/2/3 internal Heatmap demo prepared.")
        self._report(
            "READY",
            "\n".join(
                (
                    "Complete GPU 1/2/3 internal Heatmap scope is isolated.",
                    f"targets={len(contract.targets)}",
                    "channels=hotspot,memory,general",
                    f"scale_celsius=[{scale.minimum:.2f},{scale.maximum:.2f}]",
                    "smoothing=2 Hz / 2.0 s",
                    _format_gradient_audit(self._gradient_audit),
                    _format_gpu_pcb_display_ranges(contract),
                )
            ),
            next_action="Set workload to Nominal.",
        )

    def observe_telemetry_snapshot(self, snapshot) -> None:
        """Apply all GPU03 channels together only at the requested baseline."""

        session = self._session
        if (
            session is None
            or self._waiting_check is not None
            or session.expected_milestone != "GPU_INTERNALS_PCB_PRESENTATION"
            or snapshot.operational_state != "Nominal"
        ):
            return
        if not self._automatic_invariants_hold():
            return
        state = self._controller.enable_heatmap_vertical_slice_in_kit()
        if not state.success or not state.enabled:
            self._fail(f"GPU internal Heatmap material enable failed: {state.message}")
            return
        if state.target_paths != self._target_paths:
            self._fail("GPU internal Heatmap target coverage is incomplete.")
            return
        self._wait_for_check(
            "GPU_INTERNALS_PCB_PRESENTATION",
            "\n".join(
                (
                    "Nominal GPU 1/2/3 Heatmap presentation is ready for review.",
                    _format_gradient_audit(self._gradient_audit),
                    _format_gpu_pcb_display_ranges(
                        self._controller.heatmap_vertical_slice_contract_snapshot()
                    ),
                )
            ),
            "Inspect GPU 1/2/3 side-by-side: confirm each PCB is cooler than "
            "its VRAM/die at the listed maximum offset; non-PCB behaviour is "
            "unchanged; and all three internals remain readable; or declare Failure.",
        )

    def record_manual_verdict(self, passed: bool) -> bool:
        """Record one universal verdict; manual failure remains non-terminal."""

        session = self._session
        check = self._waiting_check
        if session is None or check is None or not session.record(check):
            return False
        self._waiting_check = None
        self._set_manual_verdict_enabled(False)
        if not passed:
            self._manual_failures.append(check)
        next_action = None
        if check == "GPU_INTERNALS_PCB_PRESENTATION":
            next_action = self._restoration_next_action()
        self._report(
            "COMPLETE",
            "\n".join(
                (
                    "Manual visual checkpoint recorded.",
                    f"check={check}",
                    f"result={'PASS' if passed else 'FAIL'}",
                )
            ),
            next_action=next_action,
        )
        if check == "APPEARANCE_RESTORATION":
            self._complete_after_restoration()
        return True

    def on_test_presentation_disabled(self, result) -> None:
        """Request restoration review only after GPU03 Session cleanup succeeds."""

        session = self._session
        if session is None or session.expected_milestone != "APPEARANCE_RESTORATION":
            return
        presentation = getattr(result, "vertical_slice", None)
        if not result.success or presentation is None or not presentation.success:
            detail = presentation.message if presentation else result.message
            self._fail(f"GPU internal Heatmap Session cleanup failed: {detail}")
            return
        self._wait_for_check(
            "APPEARANCE_RESTORATION",
            "Original GPU/server appearance is ready for visual inspection.",
            "Confirm the prior scene appearance is restored, or declare Failure.",
        )

    def cancel(self) -> None:
        """Release workflow state and make stale Confirm/Failure callbacks harmless."""

        self._set_manual_verdict_enabled(False)
        self._session = None
        self._waiting_check = None
        self._manual_failures = []
        self._target_paths = ()
        self._registry_fingerprint = ()
        self._gradient_audit = ()

    def _channel_contract_is_valid(self, contract) -> bool:
        counts = Counter(target.metric_id for target in contract.targets)
        if dict(counts) != self._CHANNEL_COUNTS:
            self._fail(
                "GPU internal thermal channels do not match three 1/8/51 splits."
            )
            return False
        if any(
            profile.minimum_celsius > profile.maximum_celsius
            for target in contract.targets
            for profile in target.delta_profiles.values()
        ):
            self._fail("GPU internal Heatmap delta profile ordering is reversed.")
            return False
        return True

    def _automatic_invariants_hold(self) -> bool:
        registry = self._controller.heatmap_semantic_registry_snapshot()
        if registry is None or registry.fingerprint != self._registry_fingerprint:
            self._fail("Heatmap semantic registry identity changed during review.")
            return False
        contract = self._controller.heatmap_vertical_slice_contract_snapshot()
        if contract is None:
            self._fail("GPU internal Heatmap contract is unavailable during review.")
            return False
        target_paths = tuple(target.prim_path for target in contract.targets)
        if target_paths != self._target_paths:
            self._fail("GPU internal Heatmap target set changed during review.")
            return False
        values = self._controller.heatmap_telemetry_binding_snapshot()
        if values is None:
            self._fail("GPU internal Heatmap telemetry is unavailable.")
            return False
        for target in contract.targets:
            current = values.for_prim(target.prim_path)
            if (
                current is None
                or not current.available
                or current.metric_id != target.metric_id
            ):
                self._fail("GPU internal telemetry binding changed or is unavailable.")
                return False
        return True

    def _wait_for_check(self, check: str, status: str, action: str) -> None:
        self._waiting_check = check
        self._set_manual_verdict_enabled(True)
        self._report("WAITING", f"{status}\ncheck={check}", next_action=action)

    def _restoration_next_action(self) -> str:
        """Describe the visible action that removes the focused presentation."""

        return (
            f'Press "{self._restoration_action_label()}" to restore the prior ' "scene."
        )

    def _fail(self, reason: str) -> None:
        session = self._session
        if session is None or session.terminal_emitted:
            return
        session.mark_failed()
        self._waiting_check = None
        self._set_manual_verdict_enabled(False)
        self._report("FAIL", reason)
        session.terminal_emitted = True
        self._emit("TEST COMPLETE\nFAIL\nNo further manual action required.")

    def _report(
        self,
        event: str,
        status: str,
        *,
        next_action: str | None = None,
    ) -> None:
        lines = [f"DTRS HEATMAPS | GPU INTERNAL DEMO | {event}"]
        lines.append(f"status={status}")
        if next_action:
            lines.append(f"NEXT_ACTION | {next_action}")
        self._emit("\n".join(lines))

    def _emit(self, content: str) -> None:
        self._log_warning(
            format_dtrs_status_block(
                content,
                append_local_timestamp=self._append_local_timestamp,
            )
        )

    def _complete_after_restoration(self) -> None:
        session = self._session
        if session is None or not session.complete():
            return
        passed = len(self._CHECKS) - len(self._manual_failures)
        lines = ["TEST COMPLETE", "PASS" if not self._manual_failures else "FAIL"]
        if self._manual_failures:
            lines.extend(
                (
                    f"manual_checks_passed={passed}/{len(self._CHECKS)}",
                    f"manual_checks_failed={len(self._manual_failures)}",
                    f"failed_checks={','.join(self._manual_failures)}",
                )
            )
        else:
            lines.append(f"manual_checks={len(self._CHECKS)}/{len(self._CHECKS)}")
        lines.append("No further manual action required.")
        self._emit("\n".join(lines))


def _format_gradient_audit(audit) -> str:
    """Render semantic gradient evidence required for the focused review."""

    lines = ["GPU_INTERNALS_GRADIENT_AUDIT | workload=Nominal"]
    for item in audit:
        lines.extend(
            (
                f"{item.thermal_zone} / {item.thermal_component}",
                f"metric={item.metric_id}",
                f"targets={item.target_count}",
                f"weights=[{item.weight_minimum:.3f},{item.weight_maximum:.3f}]",
                "delta_minimum="
                f"[{item.delta_minimum_celsius[0]:.3f},"
                f"{item.delta_minimum_celsius[1]:.3f}]",
                "delta_maximum="
                f"[{item.delta_maximum_celsius[0]:.3f},"
                f"{item.delta_maximum_celsius[1]:.3f}]",
                f"effective_display_span={item.effective_display_span_celsius:.3f} C",
                f"variation={item.variation}",
            )
        )
    return "\n".join(lines)


def _format_gpu_pcb_display_ranges(contract) -> str:
    """Render per-GPU PCB display bounds for every provider workload."""

    groups: dict[int, list[object]] = {}
    for target in contract.targets:
        semantic = (
            target.semantic_key.thermal_zone,
            target.semantic_key.thermal_component,
        )
        instance = target.semantic_key.hardware.instance
        if semantic == ("board", "pcb") and instance in {1, 2, 3}:
            groups.setdefault(instance, []).append(target)
    if set(groups) != {1, 2, 3}:
        return "GPU_PCB_DISPLAY_RANGES\nstatus=unavailable"
    lines = ["GPU_PCB_DISPLAY_RANGES"]
    for instance in (1, 2, 3):
        pcb_targets = groups[instance]
        weights = tuple(
            weight for target in pcb_targets for weight in target.thermal_weights
        )
        lines.append(f"GPU {instance}")
        for workload in ("Idle", "Nominal", "Surge", "Critical"):
            profile = pcb_targets[0].delta_profiles[workload]
            delta_minimum, delta_maximum = effective_delta_range(
                profile,
                weight_minimum=min(weights),
                weight_maximum=max(weights),
            )
            metric_id = f"gpu_{instance}_temp_c"
            provider_target = contract.provider_profiles[metric_id][workload][0]
            lines.extend(
                (
                    workload,
                    f"{metric_id}_target={provider_target:.3f} C",
                    f"pcb_display_min={provider_target + delta_minimum:.3f} C",
                    f"pcb_display_max={provider_target + delta_maximum:.3f} C",
                )
            )
    return "\n".join(lines)
