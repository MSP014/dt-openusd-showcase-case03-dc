"""Guided manual proof for the Stage 10.3 full-server Heatmap test."""

from __future__ import annotations

from collections.abc import Callable

from digital_twin_runtime_suite.app.manual_acceptance import GuidedAcceptanceSession
from digital_twin_runtime_suite.app.status_log import format_dtrs_status_block


class HeatmapFullServerAcceptanceWorkflow:
    """Sequence full-server manual verdicts without owning presentation policy."""

    _UNAVAILABLE_CHECK = "UNAVAILABLE_REGIONS"
    _WORKLOAD_CHECKS = (
        ("IDLE_FULL_SERVER_RESPONSE", "Idle"),
        ("SURGE_FULL_SERVER_RESPONSE", "Surge"),
        ("CRITICAL_FULL_SERVER_RESPONSE", "Critical"),
    )
    _RESTORATION_CHECK = "FULL_SERVER_APPEARANCE_RESTORATION"

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
        self._registry_fingerprint = ()
        self._renderable_paths: tuple[str, ...] = ()
        self._scale = None
        self._palette_identity = ""
        self._ownership: tuple[int, int] | None = None

    @property
    def active(self) -> bool:
        """Return whether this workflow exclusively owns Heatmap next actions."""

        return self._session is not None and not self._session.terminal_emitted

    def start(self, result) -> None:
        """Start after full-server preflight, bindings, and presentation succeed."""

        self.cancel()
        preflight = getattr(result, "preflight", None)
        registry = getattr(result, "registry", None)
        state = getattr(result, "full_server", None)
        if not result.success or preflight is None or not preflight.success:
            self._start_failure("Heatmap asset preflight did not pass.")
            return
        if registry is None or not registry.success:
            self._start_failure("Heatmap semantic registry did not pass.")
            return
        if state is None or not state.success or not state.enabled:
            detail = state.message if state else "missing full-server presentation"
            self._start_failure(f"Heatmap full-server preparation failed: {detail}")
            return
        contract = self._controller.heatmap_full_server_contract_snapshot()
        if contract is None:
            self._start_failure("Heatmap full-server coverage contract is unavailable.")
            return
        node_checks = tuple(
            _node_check(item.hardware_identity)
            for item in _ordered_nodes(state.node_evidence)
        )
        self._session = GuidedAcceptanceSession(
            (*node_checks, self._UNAVAILABLE_CHECK, *self._workload_check_ids)
            + (self._RESTORATION_CHECK,)
        )
        self._session.begin()
        self._registry_fingerprint = registry.fingerprint
        self._renderable_paths = tuple(sorted(state.renderable_target_paths))
        self._scale = state.scale_resolution.scale if state.scale_resolution else None
        self._palette_identity = state.palette_identity
        self._ownership = (
            state.material_group_count,
            state.session_binding_count,
        )
        if not self._profiles_are_complete(contract):
            return
        self._report("START", "Full-server Heatmap presentation prepared.")
        scale = state.scale_resolution.scale
        self._report(
            "READY",
            "\n".join(
                (
                    "Full-server Heatmap is ready.",
                    f"thermal_targets={state.total_thermal_targets}",
                    f"renderable_targets={len(state.renderable_target_paths)}",
                    f"rendered_targets={len(state.rendered_target_paths)}",
                    f"unavailable_targets={len(contract.unavailable_target_paths)}",
                    "xray_precedence_targets="
                    f"{len(contract.xray_precedence_target_paths)}",
                    f"semantic_groups={state.semantic_group_count}",
                    f"material_groups={state.material_group_count}",
                    f"session_bindings={state.session_binding_count}",
                    f"scale_celsius=[{scale.minimum:.2f},{scale.maximum:.2f}]",
                    "palette=violet-blue,blue,cyan,green,yellow,orange,red",
                    "delta_profiles=COMPLETE",
                )
            ),
            next_action="Set workload to Nominal.",
        )

    def observe_telemetry_snapshot(self, snapshot) -> None:
        """Wait for the baseline or requested workload before one verdict."""

        session = self._session
        if session is None or self._waiting_check is not None:
            return
        check = session.expected_milestone
        if check is None:
            return
        required_workload = _required_workload(check)
        if (
            required_workload is not None
            and snapshot.operational_state != required_workload
        ):
            return
        if not self._automatic_invariants_hold():
            return
        if check.endswith("_THERMAL_BINDING"):
            self._wait_for_node(check)
        elif check in self._workload_check_ids:
            self._wait_for_workload(check, snapshot.operational_state)

    def record_manual_verdict(self, passed: bool) -> bool:
        """Record one universal operator verdict and continue after manual failure."""

        session = self._session
        check = self._waiting_check
        if session is None or check is None or not session.record(check):
            return False
        self._waiting_check = None
        self._set_manual_verdict_enabled(False)
        if not passed:
            self._manual_failures.append(check)
        self._report(
            "COMPLETE",
            "\n".join(
                (
                    "Manual visual checkpoint recorded.",
                    f"check={check}",
                    f"result={'PASS' if passed else 'FAIL'}",
                )
            ),
            next_action=self._next_action_after(check),
        )
        self._advance_after_verdict(check)
        return True

    def on_test_presentation_disabled(self, result) -> None:
        """Request the final visual verdict only after Session cleanup succeeds."""

        session = self._session
        if session is None or session.expected_milestone != self._RESTORATION_CHECK:
            return
        state = getattr(result, "full_server", None)
        if (
            not result.success
            or state is None
            or not state.success
            or state.enabled
            or state.material_group_count
            or state.session_binding_count
        ):
            detail = state.message if state else result.message
            self._fail(f"Heatmap full-server Session cleanup failed: {detail}")
            return
        self._wait_for_check(
            self._RESTORATION_CHECK,
            "Pre-test full-server appearance is ready for visual inspection.",
            "Confirm that the pre-test full-server appearance is restored, or "
            "declare Failure.",
        )

    def cancel(self) -> None:
        """Release state and make a stale Confirm or Failure callback harmless."""

        self._set_manual_verdict_enabled(False)
        self._session = None
        self._waiting_check = None
        self._manual_failures = []
        self._registry_fingerprint = ()
        self._renderable_paths = ()
        self._scale = None
        self._palette_identity = ""
        self._ownership = None

    @property
    def _workload_check_ids(self) -> tuple[str, ...]:
        return tuple(check for check, _ in self._WORKLOAD_CHECKS)

    def _wait_for_node(self, check: str) -> None:
        identity = _identity_from_node_check(check)
        evidence = next(
            (
                item
                for item in (
                    self._controller.heatmap_full_server_node_evidence_snapshot()
                )
                if item.hardware_identity == identity
            ),
            None,
        )
        if evidence is None:
            self._fail(f"Heatmap node evidence is missing for {identity}.")
            return
        lines = [
            f"{_node_label(identity)} is ready for visual inspection.",
            f"hardware_identity={identity}",
            f"rendered_targets={evidence.rendered_target_count}",
            "semantic_groups=" + ", ".join(evidence.semantic_groups),
            "TELEMETRY:",
        ]
        for metric in evidence.telemetry:
            lines.extend(
                (
                    f"metric={metric.metric_id}",
                    f"value={_format_celsius(metric.value)}",
                    f"quality={metric.quality}",
                    _format_derived_range(metric),
                )
            )
        if evidence.unavailable_target_paths:
            lines.append(
                f"unavailable_targets={len(evidence.unavailable_target_paths)}"
            )
        self._wait_for_check(
            check,
            "\n".join(lines),
            f"Inspect {_node_label(identity)}. Confirm that its Heatmap corresponds "
            "to the listed telemetry channels and authored thermal regions, or "
            "declare Failure.",
        )

    def _wait_for_unavailable(self) -> None:
        contract = self._controller.heatmap_full_server_contract_snapshot()
        registry = self._controller.heatmap_semantic_registry_snapshot()
        if contract is None or registry is None:
            self._fail("Heatmap unavailable-region evidence is unavailable.")
            return
        groups: dict[object, list[str]] = {}
        for path in contract.unavailable_target_paths:
            target = registry.for_prim(path)
            if target is not None:
                groups.setdefault(target.semantic_key, []).append(path)
        lines = ["Unsupported Heatmap regions remain unpainted."]
        for key, paths in sorted(groups.items(), key=lambda item: item[0].label):
            reason = contract.unavailable_reasons[paths[0]]
            lines.extend(
                (
                    key.label,
                    f"targets={len(paths)}",
                    f"reason={reason}",
                )
            )
        self._wait_for_check(
            self._UNAVAILABLE_CHECK,
            "\n".join(lines),
            "Confirm that unsupported thermal regions have not been assigned "
            "fabricated temperatures, or declare Failure.",
        )

    def _wait_for_workload(self, check: str, workload: str) -> None:
        self._wait_for_check(
            check,
            "\n".join(
                (
                    f"{workload} full-server Heatmap response is ready.",
                    "registry_stable=PASS",
                    "semantic_keys_stable=PASS",
                    "metric_ids_stable=PASS",
                    "thermal_weights_stable=PASS",
                    "global_scale_stable=PASS",
                    "palette_stable=PASS",
                    "material_ownership_stable=PASS",
                    "binding_remaps=0",
                )
            ),
            "Confirm that the full-server thermal response changed coherently "
            "while retaining the same absolute scale, or declare Failure.",
        )

    def _wait_for_check(self, check: str, status: str, action: str) -> None:
        self._waiting_check = check
        self._set_manual_verdict_enabled(True)
        self._report("WAITING", f"{status}\ncheck={check}", next_action=action)

    def _advance_after_verdict(self, check: str) -> None:
        session = self._session
        if session is None:
            return
        next_check = session.expected_milestone
        if next_check is None:
            self._complete()
            return
        if next_check.endswith("_THERMAL_BINDING"):
            self._wait_for_node(next_check)
        elif next_check == self._UNAVAILABLE_CHECK:
            self._wait_for_unavailable()

    def _next_action_after(self, check: str) -> str | None:
        actions = {
            self._UNAVAILABLE_CHECK: "Set workload to Idle.",
            "IDLE_FULL_SERVER_RESPONSE": "Set workload to Surge.",
            "SURGE_FULL_SERVER_RESPONSE": "Set workload to Critical.",
            "CRITICAL_FULL_SERVER_RESPONSE": self._restoration_next_action(),
        }
        return actions.get(check)

    def _restoration_next_action(self) -> str:
        label = self._restoration_action_label()
        return (
            f'Press "{label}" to remove the Heatmap test presentation and restore '
            "the prior scene appearance."
        )

    def _automatic_invariants_hold(self) -> bool:
        registry = self._controller.heatmap_semantic_registry_snapshot()
        state = self._controller.heatmap_full_server_snapshot()
        if registry is None or registry.fingerprint != self._registry_fingerprint:
            self._fail("Heatmap semantic registry identity changed during acceptance.")
            return False
        if state is None or not state.success or not state.enabled:
            self._fail("Heatmap full-server presentation is unavailable.")
            return False
        if tuple(sorted(state.renderable_target_paths)) != self._renderable_paths:
            self._fail("Heatmap full-server renderable target set changed.")
            return False
        scale = state.scale_resolution.scale if state.scale_resolution else None
        if scale != self._scale or state.palette_identity != self._palette_identity:
            self._fail("Heatmap global scale or palette changed during acceptance.")
            return False
        if self._ownership != (
            state.material_group_count,
            state.session_binding_count,
        ):
            self._fail("Heatmap material ownership changed during refresh.")
            return False
        if set(state.rendered_target_paths) & set(state.xray_precedence_target_paths):
            self._fail("X-Ray-precedence Heatmap target received ordinary material.")
            return False
        return True

    def _profiles_are_complete(self, contract) -> bool:
        expected = {"Idle", "Nominal", "Surge", "Critical"}
        targets = (*contract.renderable_targets, *contract.xray_precedence_targets)
        complete = all(
            set(target.delta_profiles) == expected
            and all(
                profile.minimum_celsius <= profile.maximum_celsius
                for profile in target.delta_profiles.values()
            )
            for target in targets
        )
        if not complete:
            self._fail("Heatmap full-server delta-profile coverage is incomplete.")
        return complete

    def _start_failure(self, reason: str) -> None:
        self._session = GuidedAcceptanceSession(())
        self._session.begin()
        self._fail(reason)

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
        lines = [f"DTRS HEATMAPS | FULL SERVER ACCEPTANCE | {event}"]
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

    def _complete(self) -> None:
        session = self._session
        if session is None or not session.complete():
            return
        total = len(session.required_milestones)
        passed = total - len(self._manual_failures)
        if self._manual_failures:
            lines = (
                "TEST COMPLETE",
                "FAIL",
                f"manual_checks_passed={passed}/{total}",
                f"manual_checks_failed={len(self._manual_failures)}",
                f"failed_checks={','.join(self._manual_failures)}",
                "No further manual action required.",
            )
        else:
            lines = (
                "TEST COMPLETE",
                "PASS",
                f"manual_checks={total}/{total}",
                "No further manual action required.",
            )
        self._emit("\n".join(lines))


def _ordered_nodes(evidence) -> tuple[object, ...]:
    return tuple(sorted(evidence, key=lambda item: _node_order(item.hardware_identity)))


def _node_order(identity: str) -> tuple[int, str]:
    if identity.startswith("gpu_"):
        return (int(identity.removeprefix("gpu_")), identity)
    return ({"cpu": 4, "nic": 5, "psu": 6}.get(identity, 99), identity)


def _node_check(identity: str) -> str:
    return f"{identity.upper()}_THERMAL_BINDING"


def _identity_from_node_check(check: str) -> str:
    return check.removesuffix("_THERMAL_BINDING").lower()


def _node_label(identity: str) -> str:
    if identity.startswith("gpu_"):
        return f"GPU {identity.removeprefix('gpu_')}"
    return {"cpu": "CPU / CPU cooler", "nic": "ConnectX-7 / NIC", "psu": "PSU"}.get(
        identity,
        identity,
    )


def _required_workload(check: str) -> str | None:
    if check.endswith("_THERMAL_BINDING"):
        return "Nominal"
    return dict(HeatmapFullServerAcceptanceWorkflow._WORKLOAD_CHECKS).get(check)


def _format_celsius(value: float | None) -> str:
    return "unavailable" if value is None else f"{value:.1f} C"


def _format_range(minimum: float | None, maximum: float | None) -> str:
    if minimum is None or maximum is None:
        return "unavailable"
    return f"[{minimum:.1f}, {maximum:.1f}] C"


def _format_derived_range(metric) -> str:
    """Format runtime-derived extrema without widening guided log lines."""

    return "derived_temperature_range=" + _format_range(
        metric.derived_minimum_celsius,
        metric.derived_maximum_celsius,
    )
