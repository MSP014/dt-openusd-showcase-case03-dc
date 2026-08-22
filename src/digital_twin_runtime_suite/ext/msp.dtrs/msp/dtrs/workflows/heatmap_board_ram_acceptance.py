"""Guided manual proof for motherboard Heatmap bindings."""

from __future__ import annotations

from collections.abc import Callable

from digital_twin_runtime_suite.app.manual_acceptance import GuidedAcceptanceSession
from digital_twin_runtime_suite.app.status_log import format_dtrs_status_block


class HeatmapMotherboardAcceptanceWorkflow:
    """Own the focused motherboard proof without changing binding policy."""

    _MOTHERBOARD_PATH = "/blackwell_rig/motherboard"
    _CHECKS = (
        "MOTHERBOARD_BASE_BINDING",
        "MOTHERBOARD_CHIPSET_BINDING",
        "MOTHERBOARD_CPU_SOCKET_BINDING",
        "MOTHERBOARD_VRM_EAST_BINDING",
        "MOTHERBOARD_VRM_WEST_BINDING",
        "MOTHERBOARD_NVME_1_BINDING",
        "MOTHERBOARD_NVME_2_BINDING",
        "MOTHERBOARD_COMBINED_PRESENTATION",
        "APPEARANCE_RESTORATION",
    )
    _FOCUSES = {
        "MOTHERBOARD_BASE_BINDING": (
            ("motherboard_temp_c",),
            _MOTHERBOARD_PATH,
            "generic motherboard regions excluding RAM slots",
            572,
        ),
        "MOTHERBOARD_CHIPSET_BINDING": (
            ("chipset_temp_c",),
            _MOTHERBOARD_PATH,
            "cpu / cpu_package",
            1,
        ),
        "MOTHERBOARD_CPU_SOCKET_BINDING": (
            ("cpu_temp_c",),
            _MOTHERBOARD_PATH,
            "cpu / socket",
            7,
        ),
        "MOTHERBOARD_VRM_EAST_BINDING": (
            ("vrm_e_temp_c",),
            _MOTHERBOARD_PATH,
            "authored vrm_east thermal zone",
            2,
        ),
        "MOTHERBOARD_VRM_WEST_BINDING": (
            ("vrm_w_temp_c",),
            _MOTHERBOARD_PATH,
            "authored vrm_west thermal zone",
            2,
        ),
        "MOTHERBOARD_NVME_1_BINDING": (
            ("nvme_1_temp_c",),
            _MOTHERBOARD_PATH,
            "NVMe_A",
            2,
        ),
        "MOTHERBOARD_NVME_2_BINDING": (
            ("nvme_2_temp_c",),
            _MOTHERBOARD_PATH,
            "NVMe_B",
            3,
        ),
        "MOTHERBOARD_COMBINED_PRESENTATION": (
            (
                "motherboard_temp_c",
                "chipset_temp_c",
                "cpu_temp_c",
                "vrm_e_temp_c",
                "vrm_w_temp_c",
                "nvme_1_temp_c",
                "nvme_2_temp_c",
            ),
            _MOTHERBOARD_PATH,
            "complete motherboard thermal presentation",
            597,
        ),
    }

    def __init__(
        self,
        controller,
        *,
        log_warning: Callable[[str], None],
        append_local_timestamp: Callable[[str], str],
        set_manual_verdict_enabled: Callable[[bool], None],
        set_test_enabled: Callable[[bool], None],
        restoration_action_label: Callable[[], str],
    ) -> None:
        self._controller = controller
        self._log_warning = log_warning
        self._append_local_timestamp = append_local_timestamp
        self._set_manual_verdict_enabled = set_manual_verdict_enabled
        self._set_test_enabled = set_test_enabled
        self._restoration_action_label = restoration_action_label
        self._session: GuidedAcceptanceSession | None = None
        self._waiting_check: str | None = None
        self._manual_failures: list[str] = []

    @property
    def active(self) -> bool:
        """Return whether this workflow exclusively owns Heatmap verdict controls."""

        return self._session is not None and not self._session.terminal_emitted

    def start(self, result) -> None:
        """Begin with the isolated normal-material baseline at stable Nominal."""

        self.cancel()
        self._session = GuidedAcceptanceSession(self._CHECKS)
        self._session.begin()
        if not result.success:
            self._fail(result.message)
            return
        state = result.full_server
        self._report(
            "START",
            "Motherboard Heatmap binding calibration started.",
        )
        self._report(
            "READY",
            "Motherboard Heatmap binding calibration is prepared.\n"
            "workload=" + (state.workload if state else "<unknown>"),
            next_action="Set workload to Nominal.",
        )
        calibration = self._controller.heatmap_motherboard_delta_calibration_snapshot()
        if calibration:
            self._report(
                "PROGRESS",
                _format_motherboard_delta_calibration(calibration),
            )
        if state is not None and state.workload == "Nominal":
            self._show_next_focus()

    def observe_telemetry_snapshot(self, snapshot) -> None:
        """Start the stable-Nominal proof only after the real provider reaches it."""

        if self.active and self._waiting_check is None:
            if snapshot.operational_state == "Nominal":
                self._show_next_focus()

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
        next_action = self._next_action(check)
        self._report(
            "COMPLETE",
            "Manual visual checkpoint recorded.\n"
            f"check={check}\nresult={'PASS' if passed else 'FAIL'}",
            next_action=next_action,
        )
        if check == "APPEARANCE_RESTORATION":
            self._finish()
        elif check != "MOTHERBOARD_COMBINED_PRESENTATION":
            self._show_next_focus()
        return True

    def on_test_presentation_disabled(self, result) -> None:
        """Offer restoration verdict only after filter and Session cleanup succeed."""

        session = self._session
        if session is None:
            return
        if session.expected_milestone != "APPEARANCE_RESTORATION":
            self.cancel()
            return
        if (
            not result.success
            or self._controller.heatmap_binding_calibration_test_active()
            or self._controller.heatmap_binding_calibration_filter_active()
        ):
            self._fail("Heatmap binding calibration cleanup did not complete.")
            return
        self._wait_for_check(
            "APPEARANCE_RESTORATION",
            "Original scene appearance is ready for visual inspection.",
            "Confirm that the prior scene appearance is restored, or declare "
            "Failure.",
        )

    def cancel(self) -> None:
        """Make stale Confirm/Failure callbacks harmless without changing runtime."""

        self._set_manual_verdict_enabled(False)
        self._session = None
        self._waiting_check = None
        self._manual_failures = []

    def _show_next_focus(self) -> None:
        session = self._session
        check = session.expected_milestone if session is not None else None
        if check is None or check not in self._FOCUSES:
            return
        metric_ids, isolation_path, expected_zone, expected_count = self._FOCUSES[check]
        if check == "MOTHERBOARD_COMBINED_PRESENTATION":
            focus = self._controller.set_heatmap_binding_calibration_full_scope_in_kit(
                isolation_path
            )
        else:
            focus = self._controller.set_heatmap_binding_calibration_focus_in_kit(
                metric_ids,
                isolation_path,
            )
        if not focus.success:
            self._fail(f"{check}: {focus.message}")
            return
        if len(focus.expected_target_paths) != expected_count:
            self._fail(
                f"{check}: expected {expected_count} binding targets, found "
                f"{len(focus.expected_target_paths)}."
            )
            return
        value, quality = self._focus_metric_value(focus.expected_target_paths[0])
        status = "\n".join(
            (
                "Heatmap telemetry focus is ready for visual inspection.",
                "telemetry_focus="
                f"{','.join(metric_ids) if metric_ids else 'full_provider_snapshot'}",
                f"value={value}",
                f"quality={quality}",
                f"expected_thermal_zone={expected_zone}",
                f"expected_target_count={expected_count}",
                "actual_bound_target_count=" f"{len(focus.expected_target_paths)}",
                "actual_heatmap_presented_target_count="
                f"{len(focus.rendered_target_paths)}",
                "foreign_target_count=" f"{len(focus.foreign_rendered_target_paths)}",
            )
        )
        action = _motherboard_visual_action(check, expected_zone)
        self._wait_for_check(check, status, action)

    def _focus_metric_value(self, prim_path: str) -> tuple[str, str]:
        telemetry = self._controller.heatmap_telemetry_binding_snapshot()
        value = telemetry.for_prim(prim_path) if telemetry is not None else None
        if value is None or value.value is None:
            return ("<unavailable>", "unavailable")
        return (f"{float(value.value):.1f} C", value.quality)

    def _wait_for_check(self, check: str, status: str, action: str) -> None:
        self._waiting_check = check
        self._set_manual_verdict_enabled(True)
        self._report("WAITING", f"{status}\ncheck={check}", next_action=action)

    def _next_action(self, check: str) -> str | None:
        session = self._session
        next_check = session.expected_milestone if session is not None else None
        if check == "MOTHERBOARD_COMBINED_PRESENTATION":
            return (
                f'Press "{self._restoration_action_label()}" to restore the '
                "prior scene appearance."
            )
        if next_check in self._FOCUSES:
            return "Inspect the next Heatmap telemetry binding checkpoint."
        return None

    def _fail(self, reason: str) -> None:
        session = self._session
        if session is None or session.terminal_emitted:
            return
        session.mark_failed()
        self._waiting_check = None
        self._set_manual_verdict_enabled(False)
        self._controller.set_heatmap_binding_calibration_test_in_kit(False)
        self._set_test_enabled(False)
        self._report("FAIL", reason)
        session.terminal_emitted = True
        self._emit("TEST COMPLETE\nFAIL\nNo further manual action required.")

    def _finish(self) -> None:
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

    def _report(
        self,
        event: str,
        status: str,
        *,
        next_action: str | None = None,
    ) -> None:
        lines = [
            f"DTRS HEATMAPS | MOTHERBOARD BINDING ACCEPTANCE | {event}",
            f"status={status}",
        ]
        if next_action is not None:
            lines.append(f"NEXT_ACTION | {next_action}")
        self._emit("\n".join(lines))

    def _emit(self, content: str) -> None:
        self._log_warning(
            format_dtrs_status_block(
                content,
                append_local_timestamp=self._append_local_timestamp,
            )
        )


def _motherboard_visual_action(check: str, expected_zone: str) -> str:
    """Keep the combined visual contract explicit without feature policy in UI."""

    if check != "MOTHERBOARD_COMBINED_PRESENTATION":
        return (
            f"Inspect {expected_zone}. Confirm its Heatmap binding, or declare "
            "Failure."
        )
    return (
        "Confirm binding, readable large-component gradients, restrained small-"
        "component variation, comparable NVMe and VRM envelopes, and one global "
        "Celsius scale; or declare Failure."
    )


def _format_motherboard_delta_calibration(calibration) -> str:
    """Render the complete runtime-owned calibration matrix for Houdini review."""

    lines = ["MOTHERBOARD_DELTA_CALIBRATION"]
    for row in calibration:
        lines.extend(
            (
                "",
                f"{row.thermal_zone} / {row.thermal_component}",
                f"metric={row.metric_id}",
                f"targets={row.target_count}",
                "weights=" f"[{row.weight_minimum:.3f}, {row.weight_maximum:.3f}]",
                f"classification={row.calibration_kind}",
            )
        )
        for profile in row.profiles:
            lines.append(
                f"{profile.workload}: delta=[{profile.delta_minimum_celsius:.3f}, "
                f"{profile.delta_maximum_celsius:.3f}] display=["
                f"{profile.display_minimum_celsius:.3f}, "
                f"{profile.display_maximum_celsius:.3f}] effective_span="
                f"{profile.effective_span_celsius:.3f}"
            )
    return "\n".join(lines)
