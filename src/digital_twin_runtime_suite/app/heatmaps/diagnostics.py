"""Focused diagnostics for Heatmap semantic binding."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HeatmapBindingDiagnostic:
    """One deterministic identity or binding diagnostic."""

    code: str
    prim_path: str
    message: str


def ambiguous_hardware_identity(
    prim_path: str,
    candidates: tuple[str, ...],
) -> HeatmapBindingDiagnostic:
    """Describe an unsafe repeated-instance ancestry without choosing one."""

    return HeatmapBindingDiagnostic(
        code="AMBIGUOUS_HARDWARE_IDENTITY",
        prim_path=prim_path,
        message="Ambiguous GPU identity in ancestry: " + ", ".join(candidates) + ".",
    )


def unavailable_telemetry_binding(
    prim_path: str,
    reason: str,
) -> HeatmapBindingDiagnostic:
    """Retain a concise truthful reason for an unsupported semantic group."""

    return HeatmapBindingDiagnostic(
        code="UNAVAILABLE_TELEMETRY",
        prim_path=prim_path,
        message=reason,
    )
