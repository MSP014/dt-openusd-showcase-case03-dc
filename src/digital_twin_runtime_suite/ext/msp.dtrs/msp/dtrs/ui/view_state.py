"""Read-only View-state rendering and transient UI values."""

from __future__ import annotations

import omni.ui as ui

COMPACT_TEXT_LENGTH = 44
ROW_LABEL_WIDTH = 104


def _compact_text(value: str, max_length: int = COMPACT_TEXT_LENGTH) -> str:
    text = str(value)
    if len(text) <= max_length:
        return text
    return f"{text[: max_length - 3]}..."


class ViewStateUiMixin:
    """Render controller snapshots and collect View-side transient UI values."""

    def _update_visualization_controls(self) -> None:
        """Refresh mode/readiness labels from controller-owned read-only state."""

        if not self._controller:
            return
        from digital_twin_runtime_suite.app.visualization_mode import (
            VisualizationMode,
        )

        try:
            readiness = self._controller.visualization_readiness()
        except Exception as error:
            readiness = None
            message = f"Current workload readiness unavailable: {error}"
        if readiness is not None:
            for entry in readiness.entries:
                label = self._visualization_readiness_labels.get(entry.mode)
                if label:
                    text = f"{entry.state}: {entry.message}"
                    label.text = _compact_text(text)
                    label.tooltip = text
        else:
            for label in self._visualization_readiness_labels.values():
                label.text = _compact_text(message)
                label.tooltip = message
        snapshot = self._controller.visualization_snapshot()
        combo_model = self._combo_index_model(self._visualization_combo)
        if combo_model:
            displayed_mode = snapshot.committed
            if snapshot.pending is not None:
                displayed_mode = snapshot.pending.target
            self._updating_visualization_mode = True
            try:
                combo_model.set_value(tuple(VisualizationMode).index(displayed_mode))
            finally:
                self._updating_visualization_mode = False
        self._sync_xray_target_controls()

    def _sync_xray_target_controls(self) -> None:
        """Synchronize temporary X-Ray ownership without discarding a draft."""

        if not self._controller:
            return
        from digital_twin_runtime_suite.app.view_controls import (
            bool_model_value,
            xray_target_draft_requires_snapshot_sync,
        )

        snapshot = self._controller.xray_target_snapshot()
        effective = snapshot.effective_target_ids
        override_active = snapshot.override_owner is not None
        previous_override_owner = getattr(
            self,
            "_xray_target_controls_override_owner",
            None,
        )
        initialized = getattr(self, "_xray_target_controls_initialized", False)
        sync_draft = xray_target_draft_requires_snapshot_sync(
            initialized=initialized,
            previous_override_owner=previous_override_owner,
            current_override_owner=snapshot.override_owner,
        )
        for group_id, model in self._xray_target_models.items():
            expected = group_id in effective
            if sync_draft and bool_model_value(model) != expected:
                model.set_value(expected)
            checkbox = self._xray_target_checkboxes.get(group_id)
            if checkbox:
                checkbox.enabled = not override_active
        self._xray_target_controls_initialized = True
        self._xray_target_controls_override_owner = snapshot.override_owner

    @staticmethod
    def _health_colour(health: str) -> int:
        if health == "Critical":
            return 0xFF5C5CE6
        if health == "Warning":
            return 0xFF5CC5E6
        return 0xFF72B88A

    @staticmethod
    def _format_metric(value, unit: str) -> str:
        if isinstance(value, bool):
            return "Active" if value else "Inactive"
        if isinstance(value, str):
            return value
        precision = 0 if unit in {"RPM", "W", "CFM", "sessions"} else 1
        formatted = f"{float(value):.{precision}f}"
        return f"{formatted} {unit}".strip()

    def _build_float_row(
        self,
        label: str,
        model,
        enabled: bool = True,
        precision: int = 2,
    ) -> None:
        with ui.HStack(height=24, spacing=6, content_clipping=True):
            ui.Label(label, width=ROW_LABEL_WIDTH, elided_text=True)
            ui.FloatDrag(
                model=model,
                width=ui.Fraction(1),
                precision=precision,
                enabled=enabled,
            )
