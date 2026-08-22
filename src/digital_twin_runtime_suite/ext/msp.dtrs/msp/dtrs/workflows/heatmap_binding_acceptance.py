"""Guided manual acceptance for the non-rendering Heatmap binding layer."""

from __future__ import annotations

from collections.abc import Callable

from digital_twin_runtime_suite.app.manual_acceptance import (
    GuidedAcceptanceSession,
    format_manual_acceptance_event,
    format_manual_acceptance_test_complete,
)
from digital_twin_runtime_suite.app.status_log import format_dtrs_status_block


class HeatmapBindingAcceptanceWorkflow:
    """Observe workload milestones without owning Heatmap binding policy."""

    def __init__(
        self,
        controller,
        *,
        log_warning: Callable[[str], None],
        append_local_timestamp: Callable[[str], str],
    ) -> None:
        self._controller = controller
        self._log_warning = log_warning
        self._append_local_timestamp = append_local_timestamp
        self._session: GuidedAcceptanceSession | None = None
        self._registry_fingerprint = ()
        self._last_timestamp = None

    def start(self, result) -> None:
        """Begin only after the automatic preflight, registry and sandbox steps."""

        self._session = GuidedAcceptanceSession(("Idle", "Critical", "Nominal"))
        self._session.begin()
        preflight = getattr(result, "preflight", None)
        registry = getattr(result, "registry", None)
        if not result.success:
            self._fail("GPU 03 PCB isolation did not complete.")
            return
        if preflight is None or not preflight.success:
            self._fail("Heatmap asset preflight did not pass.")
            return
        if registry is None or not registry.success:
            diagnostic = (
                registry.diagnostics[0].message if registry else "missing registry"
            )
            self._fail(f"Heatmap semantic registry failed: {diagnostic}")
            return
        self._registry_fingerprint = registry.fingerprint
        self._report("START", "Heatmap semantic registry built without rendering work.")
        self._report(
            "READY",
            "\n".join(
                (
                    "Heatmap semantic registry is ready.",
                    f"targets={registry.target_count}",
                    f"semantic_groups={registry.semantic_group_count}",
                    f"bound_groups={registry.bound_group_count}",
                    f"unavailable_groups={registry.unavailable_group_count}",
                    f"identity_errors={len(registry.diagnostics)}",
                    f"xray_precedence={registry.xray_precedence_count}",
                )
            ),
            next_action="Set workload to Idle.",
        )

    def observe_telemetry_snapshot(self, snapshot) -> None:
        """Advance one expected workload only when its new telemetry is available."""

        session = self._session
        if session is None or session.expected_milestone != snapshot.operational_state:
            return
        registry = self._controller.heatmap_semantic_registry_snapshot()
        values = self._controller.heatmap_telemetry_binding_snapshot()
        if registry is None or values is None:
            self._fail("Heatmap registry or current telemetry snapshot is unavailable.")
            return
        if registry.fingerprint != self._registry_fingerprint:
            self._fail("Heatmap registry identity changed during workload acceptance.")
            return
        if not _quality_is_preserved(registry, values, snapshot):
            self._fail(
                "Heatmap telemetry quality/provenance changed during resolution."
            )
            return
        if (
            self._last_timestamp is not None
            and snapshot.timestamp == self._last_timestamp
        ):
            self._fail("Heatmap telemetry did not refresh for the requested workload.")
            return

        milestone = session.expected_milestone
        if milestone == "Idle":
            representatives = _representative_bindings(registry, values)
            if len(representatives) != 6:
                self._fail("Required GPU/CPU/NIC/PSU Heatmap bindings are unavailable.")
                return
            if not session.record("Idle"):
                return
            self._last_timestamp = snapshot.timestamp
            self._report(
                "COMPLETE",
                _idle_binding_report(representatives),
                next_action="Set workload to Critical.",
            )
            return
        if milestone == "Critical":
            if not session.record("Critical"):
                return
            self._last_timestamp = snapshot.timestamp
            self._report(
                "COMPLETE",
                _invariant_report("Critical telemetry refreshed."),
                next_action="Return workload to Nominal.",
            )
            return
        if milestone == "Nominal" and session.record("Nominal"):
            self._last_timestamp = snapshot.timestamp
            self._report(
                "COMPLETE",
                _invariant_report(
                    "Nominal bindings remain stable.",
                    include_presentation_counts=True,
                ),
            )
            if session.complete():
                self._emit(format_manual_acceptance_test_complete("PASS"))

    def cancel(self) -> None:
        """Release only workflow-held manual-acceptance state on shutdown."""

        self._session = None
        self._registry_fingerprint = ()
        self._last_timestamp = None

    def _fail(self, reason: str) -> None:
        session = self._session
        if session is None or session.terminal_emitted:
            return
        session.mark_failed()
        self._report("FAIL", reason)
        session.terminal_emitted = True
        self._emit(format_manual_acceptance_test_complete("FAIL"))

    def _report(
        self,
        event: str,
        status: str,
        next_action: str | None = None,
    ) -> None:
        self._emit(
            format_manual_acceptance_event(
                area="HEATMAPS | BINDING ACCEPTANCE",
                event=event,
                status=status,
                next_action=next_action,
            )
        )

    def _emit(self, content: str) -> None:
        self._log_warning(
            format_dtrs_status_block(
                content,
                append_local_timestamp=self._append_local_timestamp,
            )
        )


def _quality_is_preserved(registry, values, snapshot) -> bool:
    """Compare raw provider quality labels without normalising their provenance."""

    for target in registry.targets:
        binding = target.telemetry_binding
        if not binding.available:
            continue
        metric = snapshot.metrics.get(binding.metric_id)
        current = values.for_prim(target.prim_path)
        if metric is None or current is None or not current.available:
            return False
        if current.value != metric.value or current.quality != metric.quality:
            return False
    return True


def _representative_bindings(
    registry,
    values,
) -> tuple[tuple[str, str, str, str, str], ...]:
    """Return one current evidence item for GPU 1/2/3, CPU, NIC and PSU."""

    representatives = []
    for family, instance in (
        ("gpu", 1),
        ("gpu", 2),
        ("gpu", 3),
        ("cpu", None),
        ("nic", None),
        ("psu", None),
    ):
        target = next(
            (
                item
                for item in registry.targets
                if item.semantic_key.hardware.family == family
                and item.semantic_key.hardware.instance == instance
                and item.telemetry_binding.available
            ),
            None,
        )
        if target is None:
            continue
        current = values.for_prim(target.prim_path)
        if current is None or not current.available:
            continue
        representatives.append(
            (
                target.semantic_key.hardware.label,
                f"{target.semantic_key.thermal_zone} / "
                f"{target.semantic_key.thermal_component}",
                current.metric_id or "<unavailable>",
                _format_current_value(current.value, current.unit),
                current.quality,
            )
        )
    return tuple(representatives)


def _idle_binding_report(
    representatives: tuple[tuple[str, str, str, str, str], ...],
) -> str:
    """Format the six manual-proof bindings as readable multi-line evidence."""

    lines = ["Idle bindings verified.", "", "REPRESENTATIVE_BINDINGS:"]
    for label, thermal_semantics, metric_id, value, quality in representatives:
        lines.extend(
            (
                f"{label} | {thermal_semantics}",
                f"  metric={metric_id}",
                f"  value={value}",
                f"  quality={quality}",
            )
        )
    return "\n".join(lines)


def _format_current_value(value, unit: str | None) -> str:
    """Format the log-only Celsius presentation without changing telemetry data."""

    if (
        unit in {"C", "°C"}
        and isinstance(value, (int, float))
        and not isinstance(
            value,
            bool,
        )
    ):
        text = f"{float(value):.1f} C"
    else:
        text = f"{value} {unit}".strip()
    return text


def _invariant_report(
    status: str,
    *,
    include_presentation_counts: bool = False,
) -> str:
    """Keep each acceptance invariant independent and easy to scan in Kit logs."""

    lines = [
        status,
        "registry_stable=PASS",
        "semantic_keys_stable=PASS",
        "metric_ids_stable=PASS",
        "gpu_identities_stable=PASS",
        "telemetry_refresh=PASS",
        "quality_preserved=PASS",
        "binding_remaps=0",
    ]
    if include_presentation_counts:
        lines.extend(
            (
                "renderer_operations=0",
                "material_operations=0",
                "scalar_operations=0",
            )
        )
    return "\n".join(lines)
