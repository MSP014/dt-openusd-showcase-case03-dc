"""Temporary Stage 10 Heatmap test control."""

from __future__ import annotations

import carb
import omni.ui as ui

_HEATMAP_TEST_ENABLE_LABEL = "Test Heatmaps"
_HEATMAP_TEST_RESTORE_LABEL = "Restore Heatmap Test"


def heatmap_test_action_label(enabled: bool) -> str:
    """Return the visible action for the temporary Heatmap test control."""

    return _HEATMAP_TEST_RESTORE_LABEL if enabled else _HEATMAP_TEST_ENABLE_LABEL


def _with_dtrs_local_timestamp(message: str) -> str:
    """Load shared timestamping after the extension establishes source imports."""

    from digital_twin_runtime_suite.app.diagnostics import (
        with_dtrs_local_timestamp,
    )

    return with_dtrs_local_timestamp(message)


class HeatmapsUiMixin:
    """Build the temporary test controls and forward intent to the runtime facade."""

    def _build_heatmaps_controls(self) -> None:
        """Build Stage 10 Heatmap test controls without USD work in UI."""

        with ui.VStack(spacing=6, content_clipping=True):
            self._heatmap_test_isolation_button = ui.Button(
                heatmap_test_action_label(False),
                height=28,
                clicked_fn=self._toggle_heatmap_test_isolation,
            )
            with ui.HStack(height=28, spacing=6):
                self._heatmap_confirm_button = ui.Button(
                    "Confirm",
                    enabled=False,
                    clicked_fn=lambda: self._submit_heatmap_manual_verdict(True),
                )
                self._heatmap_failure_button = ui.Button(
                    "Failure",
                    enabled=False,
                    clicked_fn=lambda: self._submit_heatmap_manual_verdict(False),
                )

    def _toggle_heatmap_test_isolation(self) -> None:
        """Toggle the temporary motherboard-and-eight-RAM Heatmap scope."""

        enabled = not self._controller.heatmap_test_isolation_active()
        if enabled:
            self._refresh_heatmap_telemetry_snapshot()
            self._report_heatmap_test_start()
            self._report_heatmap_asset_preflight_start()
        result = self._controller.set_heatmap_test_isolation_in_kit(enabled)
        preflight = getattr(result, "preflight", None)
        if enabled and preflight is not None:
            self._report_heatmap_asset_preflight_result(preflight)
        self._set_heatmap_test_isolation_button_state(result.enabled)
        self._log_heatmap_motherboard_ram_isolation(result, enabled)
        if enabled:
            binding_workflow = getattr(self, "_heatmap_binding_workflow", None)
            if binding_workflow is not None:
                binding_workflow.cancel()
            workflow = getattr(self, "_heatmap_vertical_slice_workflow", None)
            if workflow is not None:
                workflow.cancel()
            workflow = getattr(self, "_heatmap_full_server_workflow", None)
            if workflow is not None:
                workflow.cancel()
            workflow = getattr(self, "_heatmap_motherboard_workflow", None)
            if workflow is not None:
                workflow.cancel()
            self._set_heatmap_manual_verdict_enabled(False)

    def _refresh_heatmap_telemetry_snapshot(self) -> None:
        """Provide the current provider snapshot through the runtime's public seam."""

        provider = getattr(self, "_telemetry_provider", None)
        configure = getattr(
            self._controller,
            "configure_heatmap_telemetry_config",
            None,
        )
        refresh = getattr(
            self._controller,
            "refresh_heatmap_telemetry_snapshot",
            None,
        )
        if provider is not None:
            if configure is not None:
                configure(provider.config)
            if refresh is not None:
                refresh(provider.latest_snapshot)

    def _reset_heatmap_test_isolation_control(self) -> None:
        """Reflect reload cleanup without asking the UI to manage runtime state."""

        self._set_heatmap_test_isolation_button_state(False)
        self._set_heatmap_manual_verdict_enabled(False)

    def _set_heatmap_test_isolation_button_state(self, enabled: bool) -> None:
        """Keep the one control explicit about whether its next click restores."""

        if not self._heatmap_test_isolation_button:
            return
        label = heatmap_test_action_label(enabled)
        self._heatmap_test_isolation_button.text = label
        self._heatmap_test_isolation_button.tooltip = label

    def _set_heatmap_manual_verdict_enabled(self, enabled: bool) -> None:
        """Expose workflow waiting state without putting checkpoint policy in UI."""

        for button_name in (
            "_heatmap_confirm_button",
            "_heatmap_failure_button",
        ):
            button = getattr(self, button_name, None)
            if button is not None:
                button.enabled = enabled

    def _submit_heatmap_manual_verdict(self, passed: bool) -> None:
        """Route one generic operator verdict and immediately block double clicks."""

        self._set_heatmap_manual_verdict_enabled(False)
        workflow = getattr(self, "_heatmap_motherboard_workflow", None)
        if workflow is None or not workflow.active:
            workflow = getattr(self, "_heatmap_full_server_workflow", None)
        if workflow is None or not workflow.active:
            workflow = getattr(self, "_heatmap_vertical_slice_workflow", None)
        if workflow is not None:
            workflow.record_manual_verdict(passed)

    def _log_heatmap_motherboard_ram_isolation(
        self,
        result,
        requested_enabled: bool,
    ) -> None:
        """Log the proven focused server scope without implementation detail."""

        from digital_twin_runtime_suite.app.observability import EventKind

        presentation = getattr(result, "full_server", None)
        presentation_ready = bool(
            presentation and presentation.success and presentation.enabled
        )
        if result.success and requested_enabled and presentation_ready:
            kind = EventKind.COMPLETE
            status = (
                "Motherboard, eight RAM modules, CPU cooler, GPU internals and "
                "plugs, ConnectX-7, and PSU thermal internals are isolated with "
                "Heatmap presentation."
            )
        elif result.success and requested_enabled:
            kind = EventKind.COMPLETE
            status = (
                "Motherboard, eight RAM modules, CPU cooler, GPU internals and "
                "plugs, ConnectX-7, and PSU thermal internals are isolated; "
                "Heatmap presentation is "
                "unavailable."
            )
        elif result.success:
            kind = EventKind.COMPLETE
            status = (
                "Motherboard, RAM, CPU cooler, GPU internals and plugs, and "
                "ConnectX-7, and PSU thermal internals isolation restored the "
                "prior scene."
            )
        else:
            kind = EventKind.FAIL
            status = (
                "Motherboard, RAM, CPU cooler, GPU internals and plugs, and "
                "ConnectX-7, and PSU thermal internals isolation could not be "
                "started."
            )
        evidence = getattr(result, "focus_evidence", None)
        metadata = {
            "root": "/blackwell_rig",
            "result": result.message,
        }
        if requested_enabled:
            metadata["heatmap_presentation"] = _pass_fail(presentation_ready)
            metadata["heatmap_presented_targets"] = len(
                presentation.rendered_target_paths if presentation else ()
            )
        if evidence is not None:
            metadata.update(
                {
                    "motherboard_visible": _pass_fail(evidence.motherboard_visible),
                    "ram_modules": len(evidence.ram_module_paths),
                    "ram_instances": ",".join(
                        path.rsplit("/", maxsplit=1)[-1]
                        for path in evidence.ram_module_paths
                    ),
                    "ram_visible": _pass_fail(
                        evidence.visible_ram_module_paths == evidence.ram_module_paths
                    ),
                    "cpu_cooler_render_paths": len(evidence.cpu_cooler_render_paths),
                    "cpu_cooler_visible": _pass_fail(
                        evidence.visible_cpu_cooler_render_paths
                        == evidence.cpu_cooler_render_paths
                    ),
                    "cpu_cooler_fan_hidden": _pass_fail(evidence.cpu_cooler_fan_hidden),
                    "gpu_internals": len(evidence.gpu_internal_paths),
                    "gpu_internals_visible": _pass_fail(
                        evidence.visible_gpu_internal_paths
                        == evidence.gpu_internal_paths
                    ),
                    "gpu_plug_targets": len(evidence.gpu_plug_paths),
                    "gpu_plugs_visible": _pass_fail(
                        evidence.visible_gpu_plug_paths == evidence.gpu_plug_paths
                    ),
                    "connectx_7_visible": _pass_fail(evidence.nic_visible),
                    "unrelated_server_hardware_hidden": _pass_fail(
                        evidence.unrelated_server_hardware_hidden
                    ),
                    "outside_server_untouched": _pass_fail(
                        evidence.outside_server_visibility_untouched
                    ),
                }
            )
        self._emit_heatmap_event(
            kind,
            "MOTHERBOARD + RAM + CPU COOLER + GPU + NIC + PSU ISOLATION",
            status,
            metadata,
        )

    def _report_heatmap_test_start(self) -> None:
        """Record the button request before preflight or Session Layer work begins."""

        from digital_twin_runtime_suite.app.observability import EventKind

        self._emit_heatmap_event(
            EventKind.START,
            "TEST",
            "Heatmap test started.",
            {"root": "/blackwell_rig"},
        )

    def _report_heatmap_asset_preflight_start(self) -> None:
        """Record the full-server preflight before entering the PCB test sandbox."""

        from digital_twin_runtime_suite.app.observability import EventKind

        self._emit_heatmap_event(
            EventKind.START,
            "ASSET PREFLIGHT",
            "Heatmap asset preflight started.",
            {"root": "/blackwell_rig"},
        )

    def _report_heatmap_asset_preflight_result(self, preflight) -> None:
        """Record complete authoring evidence without listing valid geometry."""

        from digital_twin_runtime_suite.app.observability import EventKind

        self._emit_heatmap_event(
            EventKind.COMPLETE,
            "ASSET PREFLIGHT",
            _preflight_report(preflight),
            {},
        )

    def _emit_heatmap_event(self, kind, operation: str, status: str, metadata) -> None:
        """Use the shared durable-event path, with a standalone Kit fallback."""

        from digital_twin_runtime_suite.app.status_log import format_dtrs_status_block

        reporter = getattr(self, "_observability_reporter", None)
        if reporter:
            reporter.event(kind, f"HEATMAPS | {operation}", status, metadata=metadata)
            return
        content = "\n".join(
            (
                f"DTRS HEATMAPS | {operation} | {kind.value}",
                f"status={status}",
                *(f"{name}={value}" for name, value in metadata.items()),
            )
        )
        carb.log_info(
            format_dtrs_status_block(
                content,
                append_local_timestamp=_with_dtrs_local_timestamp,
            )
        )


def _weight_range(preflight) -> str:
    if preflight.observed_weight_min is None:
        return "<none>"
    return f"[{preflight.observed_weight_min:g}, {preflight.observed_weight_max:g}]"


def _pass_fail(value: bool) -> str:
    """Keep concise isolation evidence legible in the wrapped DTRS record."""

    return "PASS" if value else "FAIL"


def _preflight_report(preflight) -> str:
    """Build the ordered authoring checklist carried by the terminal log event."""

    lines = [
        "Heatmap asset preflight completed.",
        f"root={preflight.root_path}",
        f"result={preflight.status}",
        f"thermal_targets={preflight.thermal_target_count}",
        f"valid_targets={preflight.valid_target_count}",
        f"malformed_targets={preflight.malformed_target_count}",
        f"review_targets={preflight.review_target_count}",
        f"thermal_weight_range={_weight_range(preflight)}",
        f"xray_overlaps={len(preflight.xray_overlap_targets)}",
    ]
    if preflight.diagnostics:
        lines.extend(
            ("", "FAILED_ASSETS_TO_FIX:", _failure_report(preflight.diagnostics))
        )
    if preflight.review_targets:
        lines.extend(
            ("", "ASSETS_TO_REVIEW:", _review_report(preflight.review_targets))
        )
    return "\n".join(lines)


def _failure_report(diagnostics) -> str:
    """Group every definite contract failure by production asset."""

    groups: dict[str, list[tuple[str, tuple[str, ...]]]] = {}
    for diagnostic in diagnostics:
        asset, relative_path = _asset_and_relative_path(diagnostic.prim_path)
        groups.setdefault(asset, []).append(
            (relative_path, _failure_details(diagnostic))
        )

    lines: list[str] = []
    for asset, failures in sorted(groups.items()):
        lines.extend((asset, f"failed={len(failures)}"))
        for relative_path, details in failures:
            lines.append(f"- {relative_path}")
            lines.extend(f"  {detail}" for detail in details)
        lines.append("")
    return "\n".join(lines).rstrip()


def _review_report(review_targets) -> str:
    """Group every unannotated prim that shares an asset with valid Heatmaps."""

    groups: dict[str, list[str]] = {}
    for prim_path in review_targets:
        asset, relative_path = _asset_and_relative_path(prim_path)
        groups.setdefault(asset, []).append(relative_path)

    lines: list[str] = []
    for asset, paths in sorted(groups.items()):
        lines.extend((asset, f"review={len(paths)}"))
        for relative_path in paths:
            lines.extend((f"- {relative_path}", "  heatmap attributes: none"))
        lines.append("")
    return "\n".join(lines).rstrip()


def _asset_and_relative_path(prim_path: str) -> tuple[str, str]:
    """Remove server/render scaffolding while retaining the production asset."""

    if prim_path == "/blackwell_rig":
        return "server root", "."
    relative_parts = prim_path.removeprefix("/blackwell_rig/").split("/")
    asset_parts = relative_parts[:1]
    if relative_parts[0] == "compute":
        asset_parts = relative_parts[:2]
    asset = "/".join(asset_parts)
    remaining_parts = relative_parts[len(asset_parts) :]
    if remaining_parts[:2] == ["geo", "render"] and len(remaining_parts) > 2:
        remaining_parts = remaining_parts[3:]
    return asset, "/".join(remaining_parts) or "."


def _failure_details(diagnostic) -> tuple[str, ...]:
    """Show partial-contract presence separately from invalid complete values."""

    present = getattr(diagnostic, "core_attributes_present", ())
    missing = getattr(diagnostic, "core_attributes_missing", ())
    if missing:
        return (
            f"present: {', '.join(present)}",
            f"missing: {', '.join(missing)}",
        )
    return _format_failure_reason(diagnostic.reason)


def _format_failure_reason(reason: str) -> tuple[str, ...]:
    """Separate missing fields from invalid values in compatibility diagnostics."""

    missing = [
        detail.removeprefix("missing ")
        for detail in reason.split("; ")
        if detail.startswith("missing ")
    ]
    invalid = [
        detail for detail in reason.split("; ") if not detail.startswith("missing ")
    ]
    details: list[str] = []
    if missing:
        details.append(f"missing: {', '.join(missing)}")
    if invalid:
        details.append(f"invalid: {'; '.join(invalid)}")
    return tuple(details)
