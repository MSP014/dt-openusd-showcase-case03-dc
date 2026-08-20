"""Telemetry-panel construction and UI-side state synchronisation."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import carb
import omni.ui as ui

ROW_LABEL_WIDTH = 104
SERVER_VIEW_LABEL_WIDTH = 150
TELEMETRY_VALUE_RIGHT_PADDING = 8
COMPACT_TEXT_LENGTH = 44


def _compact_text(value: str, max_length: int = COMPACT_TEXT_LENGTH) -> str:
    text = str(value)
    if len(text) <= max_length:
        return text
    return f"{text[: max_length - 3]}..."


class TelemetryUiMixin:
    """Build and synchronise the DTRS telemetry panel and its controls."""

    def _build_telemetry_config_section(self) -> None:
        # isort: off
        from digital_twin_runtime_suite.app.telemetry.config import (
            COMPONENT_TUNING_GROUPS,
            TUNING_METRIC_LABELS,
            TUNING_METRICS,
        )
        from digital_twin_runtime_suite.app.telemetry.model import (
            METRIC_LABELS,
        )

        # isort: on

        config = self._telemetry_provider.config
        self._provider_numeric_metrics = tuple(sorted(TUNING_METRICS))
        self._provider_component_tuning_groups = COMPONENT_TUNING_GROUPS
        default_mode_index = self._workload_modes.index(config.default_mode)
        default_refresh_index = self._refresh_intervals.index(
            config.default_refresh_interval_s
        )
        self._provider_tick_model = ui.SimpleFloatModel(config.provider_tick_seconds)
        self._provider_interpolation_model = ui.SimpleFloatModel(
            config.interpolation_factor
        )
        self._provider_target_model = ui.SimpleFloatModel(0.0)
        self._provider_jitter_model = ui.SimpleFloatModel(0.0)
        self._provider_minimum_model = ui.SimpleFloatModel(0.0)
        self._provider_maximum_model = ui.SimpleFloatModel(0.0)

        with ui.HStack(height=24, spacing=6):
            ui.Label("Default mode", width=ROW_LABEL_WIDTH)
            self._provider_default_mode_combo = ui.ComboBox(
                default_mode_index,
                *self._workload_modes,
                width=ui.Fraction(1),
            )
        with ui.HStack(height=24, spacing=6):
            ui.Label("Default refresh", width=ROW_LABEL_WIDTH)
            refresh_labels = tuple(f"{value} s" for value in self._refresh_intervals)
            self._provider_default_refresh_combo = ui.ComboBox(
                default_refresh_index,
                *refresh_labels,
                width=ui.Fraction(1),
            )
        self._build_float_row("Provider tick", self._provider_tick_model)
        self._build_float_row(
            "Interpolation",
            self._provider_interpolation_model,
            precision=3,
        )

        ui.Label("Mode tuning", height=18)
        with ui.HStack(height=24, spacing=6):
            ui.Label("Mode", width=ROW_LABEL_WIDTH)
            self._provider_tuning_mode_combo = ui.ComboBox(
                default_mode_index,
                *self._workload_modes,
                width=ui.Fraction(1),
            )
        with ui.HStack(height=24, spacing=6):
            ui.Label("Metric", width=ROW_LABEL_WIDTH)
            metric_labels = tuple(
                (
                    TUNING_METRIC_LABELS[metric_id]
                    if metric_id in TUNING_METRIC_LABELS
                    else METRIC_LABELS[metric_id]
                )
                for metric_id in self._provider_numeric_metrics
            )
            self._provider_metric_combo = ui.ComboBox(
                0,
                *metric_labels,
                width=ui.Fraction(1),
            )
        self._build_float_row("Target", self._provider_target_model)
        self._build_float_row("Jitter", self._provider_jitter_model)
        self._build_float_row("Minimum", self._provider_minimum_model)
        self._build_float_row("Maximum", self._provider_maximum_model)
        ui.Button(
            "Save Telemetry Config",
            clicked_fn=self._save_telemetry_config,
            height=26,
            width=ui.Percent(100),
        )
        self._telemetry_config_status_label = ui.Label(
            "Packaged config with local override",
            height=34,
            elided_text=True,
        )

        for combo in (
            self._provider_tuning_mode_combo,
            self._provider_metric_combo,
        ):
            model = self._combo_index_model(combo)
            if model:
                model.add_value_changed_fn(
                    lambda _model: self._load_selected_metric_controls()
                )
        self._load_selected_metric_controls()

    def _selected_provider_mode_and_metric(self) -> tuple[str, str]:
        mode_index = self._model_int(
            self._combo_index_model(self._provider_tuning_mode_combo)
        )
        metric_index = self._model_int(
            self._combo_index_model(self._provider_metric_combo)
        )
        return (
            self._workload_modes[mode_index],
            self._provider_numeric_metrics[metric_index],
        )

    def _load_selected_metric_controls(self) -> None:
        if not self._telemetry_provider:
            return
        mode_name, metric_id = self._selected_provider_mode_and_metric()
        metric_ids = self._provider_component_tuning_groups.get(
            metric_id,
            (metric_id,),
        )
        source_metric_id = metric_ids[len(metric_ids) // 2]
        metric = self._telemetry_provider.config.modes[mode_name].numeric[
            source_metric_id
        ]
        self._provider_target_model.set_value(metric.target)
        self._provider_jitter_model.set_value(metric.jitter)
        self._provider_minimum_model.set_value(metric.minimum)
        self._provider_maximum_model.set_value(metric.maximum)

    def _save_telemetry_config(self) -> None:
        if not self._telemetry_provider or not self._telemetry_config_path:
            return

        try:
            from msp.dtrs.workflows.telemetry_config import TelemetryConfigEdit

            mode_name, metric_id = self._selected_provider_mode_and_metric()
            default_mode_index = self._model_int(
                self._combo_index_model(self._provider_default_mode_combo)
            )
            default_refresh_index = self._model_int(
                self._combo_index_model(self._provider_default_refresh_combo)
            )
            tick_seconds = float(self._provider_tick_model.as_float)
            interpolation = float(self._provider_interpolation_model.as_float)
            target = float(self._provider_target_model.as_float)
            jitter = float(self._provider_jitter_model.as_float)
            minimum = float(self._provider_minimum_model.as_float)
            maximum = float(self._provider_maximum_model.as_float)
            metric_ids = self._provider_component_tuning_groups.get(
                metric_id,
                (metric_id,),
            )
            edit = TelemetryConfigEdit(
                default_mode=self._workload_modes[default_mode_index],
                default_refresh_interval_s=self._refresh_intervals[
                    default_refresh_index
                ],
                provider_tick_seconds=tick_seconds,
                interpolation_factor=interpolation,
                mode_name=mode_name,
                metric_ids=tuple(metric_ids),
                target=target,
                jitter=jitter,
                minimum=minimum,
                maximum=maximum,
            )
            self._telemetry_provider = self._telemetry_config_workflow.save(
                self._telemetry_provider,
                edit,
            )
            self._next_telemetry_ui_update = 0.0
            self._set_telemetry_config_status("Telemetry config saved and applied.")
        except Exception as exc:  # noqa: BLE001
            self._provider_tick_model.set_value(
                self._telemetry_provider.config.provider_tick_seconds
            )
            self._provider_interpolation_model.set_value(
                self._telemetry_provider.config.interpolation_factor
            )
            self._load_selected_metric_controls()
            self._set_telemetry_config_status(
                f"Telemetry config error: {exc}",
                clear_after_s=8.0,
            )

    def _set_telemetry_config_status(
        self,
        message: str,
        clear_after_s: float | None = None,
    ) -> None:
        if self._telemetry_config_status_label:
            self._telemetry_config_status_label.text = _compact_text(message)
            self._telemetry_config_status_label.tooltip = message
            self._telemetry_config_status_clear_at = (
                time.monotonic() + clear_after_s if clear_after_s else 0.0
            )

    def _build_telemetry_tab(self) -> None:
        # isort: off
        from digital_twin_runtime_suite.app.telemetry.model import (
            METRIC_LABELS,
        )
        from digital_twin_runtime_suite.app.telemetry.model import (
            TELEMETRY_GROUPS,
        )

        # isort: on

        snapshot = self._telemetry_provider.latest_snapshot
        mode_index = self._workload_modes.index(snapshot.operational_state)
        refresh_index = self._refresh_intervals.index(snapshot.refresh_interval_s)

        with ui.ScrollingFrame(
            horizontal_scrollbar_policy=ui.ScrollBarPolicy.SCROLLBAR_ALWAYS_OFF,
            vertical_scrollbar_policy=ui.ScrollBarPolicy.SCROLLBAR_ALWAYS_ON,
        ):
            with ui.VStack(spacing=6, content_clipping=True):
                ui.Label("Node telemetry", height=20)
                with ui.HStack(height=24, spacing=6):
                    ui.Label("Workload", width=ROW_LABEL_WIDTH)
                    self._workload_combo = ui.ComboBox(
                        mode_index,
                        *self._workload_modes,
                        width=ui.Fraction(1),
                    )
                with ui.HStack(height=24, spacing=6):
                    ui.Label("Refresh", width=ROW_LABEL_WIDTH)
                    refresh_labels = tuple(
                        f"{value} s" for value in self._refresh_intervals
                    )
                    self._refresh_combo = ui.ComboBox(
                        refresh_index,
                        *refresh_labels,
                        width=ui.Fraction(1),
                    )
                self._freeze_button = ui.Button(
                    "Freeze",
                    clicked_fn=self._toggle_telemetry_freeze,
                    height=26,
                    width=ui.Percent(100),
                )
                self._telemetry_timestamp_label = ui.Label(
                    "Last update",
                    height=20,
                    elided_text=True,
                )
                self._telemetry_state_label = ui.Label(
                    snapshot.operational_state,
                    height=22,
                )

                for group_name, metric_ids in TELEMETRY_GROUPS.items():
                    ui.Spacer(height=3)
                    collapsed = group_name.startswith(("GPU 1 ", "GPU 2 ", "GPU 3 "))
                    with ui.CollapsableFrame(
                        group_name,
                        collapsed=collapsed,
                        height=0,
                        build_header_fn=self._build_telemetry_group_header,
                        style={
                            "CollapsableFrame": {
                                "background_color": 0xFF3A3A3A,
                                "secondary_color": 0xFF464646,
                                "border_color": 0xFF5A5A5A,
                                "border_width": 1,
                                "border_radius": 2,
                            }
                        },
                    ):
                        with ui.VStack(spacing=2, height=0):
                            ui.Spacer(height=2)
                            for metric_id in metric_ids:
                                with ui.HStack(
                                    height=22,
                                    spacing=6,
                                    content_clipping=True,
                                ):
                                    ui.Label(
                                        METRIC_LABELS[metric_id],
                                        width=ui.Fraction(1),
                                        elided_text=True,
                                    )
                                    value_label = ui.Label(
                                        "",
                                        width=112,
                                        alignment=ui.Alignment.RIGHT_CENTER,
                                    )
                                    ui.Spacer(width=TELEMETRY_VALUE_RIGHT_PADDING)
                                    self._telemetry_metric_labels.setdefault(
                                        metric_id,
                                        [],
                                    ).append(value_label)
                            ui.Spacer(height=2)

        self._install_telemetry_callbacks()
        self._update_telemetry_labels(snapshot)

    @staticmethod
    def _build_telemetry_group_header(collapsed: bool, title: str) -> None:
        with ui.ZStack(height=26):
            ui.Rectangle(style={"background_color": 0xFF383838})
            with ui.HStack(height=26, spacing=4):
                ui.Label(
                    ">" if collapsed else "v",
                    width=16,
                    alignment=ui.Alignment.CENTER,
                    style={
                        "color": 0xFFB8B8B8,
                        "font": "${fonts}/OpenSans-SemiBold.ttf",
                    },
                )
                ui.Label(
                    title,
                    alignment=ui.Alignment.LEFT_CENTER,
                    elided_text=True,
                    tooltip=title,
                    style={
                        "color": 0xFFE6E6E6,
                        "font": "${fonts}/OpenSans-SemiBold.ttf",
                        "font_size": 14,
                    },
                )

    def _select_sidebar_tab(self, tab_name: str) -> None:
        telemetry_selected = tab_name == "Telemetry"
        view_selected = tab_name == "View"
        config_selected = tab_name == "Config"
        if self._telemetry_frame:
            self._telemetry_frame.visible = telemetry_selected
        if self._view_frame:
            self._view_frame.visible = view_selected
        if self._config_frame:
            self._config_frame.visible = config_selected
        if self._telemetry_tab_button:
            self._telemetry_tab_button.checked = telemetry_selected
        if self._view_tab_button:
            self._view_tab_button.checked = view_selected
        if self._config_tab_button:
            self._config_tab_button.checked = config_selected

    def _install_telemetry_callbacks(self) -> None:
        workload_model = self._combo_index_model(self._workload_combo)
        refresh_model = self._combo_index_model(self._refresh_combo)
        if workload_model:
            workload_model.add_value_changed_fn(self._on_workload_mode_changed)
        if refresh_model:
            refresh_model.add_value_changed_fn(self._on_refresh_interval_changed)

    @staticmethod
    def _combo_index_model(combo):
        if not combo or not combo.model:
            return None
        return combo.model.get_item_value_model(None)

    @staticmethod
    def _model_int(model) -> int:
        if hasattr(model, "as_int"):
            return int(model.as_int)
        return int(model.get_value_as_int())

    def _visualization_combo_is_normal(self) -> bool:
        """Return the UI's current Normal selection for receipt acceptance."""

        model = self._combo_index_model(self._visualization_combo)
        return model is not None and self._model_int(model) == 0

    def _on_workload_mode_changed(self, model) -> None:
        self._cancel_streamlines_material_apply()
        if not self._telemetry_provider:
            return
        index = self._model_int(model)
        if 0 <= index < len(self._workload_modes):
            workload_mode = self._workload_modes[index]
            self._telemetry_provider.set_mode(workload_mode)
            self._log_workload_cache_mapping(workload_mode)
            self._validation_workflow.schedule_current_streamlines_cache_validation()
            self._refresh_airflow_cache_selector_label()
            self._schedule_workload_transition(workload_mode)
            self._next_telemetry_ui_update = 0.0

    def _airflow_cache_selector_text(self) -> str:
        """Return the next or current Flow selector without changing runtime state."""

        if not self._controller:
            return "Not configured"
        cache = self._controller.config.simulation_cache
        if cache.runtime_mode != "kit_cae":
            return (
                Path(cache.wrapper_path).name
                if cache.wrapper_path
                else "Not configured"
            )
        try:
            return self._controller.airflow_cache_selector_identity()
        except (RuntimeError, ValueError):
            return "Not configured"

    def _refresh_airflow_cache_selector_label(self) -> None:
        if not self._airflow_cache_selector_label:
            return
        selector_text = self._airflow_cache_selector_text()
        self._airflow_cache_selector_label.text = _compact_text(selector_text)
        self._airflow_cache_selector_label.tooltip = selector_text

    def _log_workload_cache_mapping(self, workload_mode: str) -> None:
        """Report mapping resolution without changing the Flow lifecycle."""

        if not self._controller:
            return
        mapping_log = self._controller.resolve_workload_airflow_binding(
            workload_mode
        ).format_mapping_log()
        carb.log_warn(mapping_log)

    def _on_refresh_interval_changed(self, model) -> None:
        if not self._telemetry_provider:
            return
        index = self._model_int(model)
        if 0 <= index < len(self._refresh_intervals):
            self._telemetry_provider.set_refresh_interval(
                self._refresh_intervals[index]
            )
            self._next_telemetry_ui_update = 0.0

    def _toggle_telemetry_freeze(self) -> None:
        if not self._telemetry_provider or not self._telemetry_latch:
            return
        if self._telemetry_latch.is_frozen:
            self._telemetry_latch.resume()
            if self._freeze_button:
                self._freeze_button.text = "Freeze"
        else:
            self._telemetry_latch.freeze(self._telemetry_provider.latest_snapshot)
            if self._freeze_button:
                self._freeze_button.text = "Resume"
        self._next_telemetry_ui_update = 0.0

    async def _run_telemetry(self) -> None:
        try:
            import omni.kit.app
            import omni.usd

            app = omni.kit.app.get_app()
            usd_context = omni.usd.get_context()
            provider_tick_seconds = (
                self._telemetry_provider.config.provider_tick_seconds
            )
            next_provider_tick = time.monotonic() + provider_tick_seconds
            self._next_telemetry_ui_update = 0.0

            while self._telemetry_provider and self._window:
                await app.next_update_async()
                now = time.monotonic()

                if (
                    self._telemetry_config_status_clear_at
                    and now >= self._telemetry_config_status_clear_at
                ):
                    self._set_telemetry_config_status("")

                if now >= next_provider_tick:
                    self._telemetry_provider.tick()
                    next_provider_tick = (
                        now + self._telemetry_provider.config.provider_tick_seconds
                    )

                if self._motion_controller:
                    self._motion_controller.update(
                        usd_context.get_stage(),
                        self._telemetry_provider.latest_snapshot,
                        now,
                    )

                if self._controller:
                    self._controller.sync_simulation_cache_frame_in_kit()

                latest = self._telemetry_provider.latest_snapshot
                displayed = self._telemetry_latch.displayed(latest)
                if self._controller:
                    self._controller.apply_front_panel_indicators_snapshot_in_kit(
                        displayed,
                        now,
                    )

                if now >= self._next_telemetry_ui_update:
                    self._update_telemetry_labels(displayed)
                    self._update_airflow_temporal_validation_status()
                    self._update_visualization_controls()
                    if self._controller:
                        self._controller.apply_qled_display_snapshot_in_kit(displayed)
                    self._next_telemetry_ui_update = now + latest.refresh_interval_s
        except asyncio.CancelledError:
            return
        except Exception as exc:  # noqa: BLE001
            self._set_status(f"Telemetry stopped: {exc}")

    def _update_telemetry_labels(self, snapshot) -> None:
        if self._telemetry_timestamp_label:
            prefix = (
                "Frozen at"
                if self._telemetry_latch and self._telemetry_latch.is_frozen
                else "Last update"
            )
            timestamp = snapshot.timestamp.astimezone().strftime("%Y-%m-%d %H:%M:%S")
            self._telemetry_timestamp_label.text = f"{prefix}: {timestamp}"

        if self._telemetry_state_label:
            health = snapshot.metrics["health_state"].value
            self._telemetry_state_label.text = (
                f"{snapshot.operational_state} / {health}"
            )
            self._telemetry_state_label.style = {
                "color": self._health_colour(str(health))
            }

        for metric_id, labels in self._telemetry_metric_labels.items():
            metric = snapshot.metrics.get(metric_id)
            if metric:
                for label in labels:
                    label.text = self._format_metric(metric.value, metric.unit)
                    if metric_id == "throttling_active":
                        label.style = {
                            "color": (0xFF5C5CE6 if bool(metric.value) else 0xFF72B88A)
                        }
