"""Draft-only OmniUI controls for the generic settings-driven Heatmap harness."""

from __future__ import annotations

import carb
import omni.ui as ui

_HEATMAP_TEST_ENABLE_LABEL = "Test Heatmaps"
_HEATMAP_TEST_RESTORE_LABEL = "Restore Heatmap Test"


def heatmap_test_action_label(enabled: bool) -> str:
    """Return the next explicit action for the one Heatmap harness mode."""

    return _HEATMAP_TEST_RESTORE_LABEL if enabled else _HEATMAP_TEST_ENABLE_LABEL


class HeatmapsUiMixin:
    """Build and retain a UI draft; only Apply delegates a settings mutation."""

    def _build_heatmaps_controls(self) -> None:
        """Build the fixed test action and a stage-populated Settings shell."""

        self._heatmap_test_button = ui.Button(
            heatmap_test_action_label(False),
            height=28,
            clicked_fn=self._toggle_heatmap_test,
        )
        self._heatmap_settings_frame = ui.Frame()
        self._refresh_heatmap_settings_controls()

    def _refresh_heatmap_settings_controls(self) -> None:
        """Repopulate draft models after the ready-stage success barrier."""

        frame = getattr(self, "_heatmap_settings_frame", None)
        if frame is None or self._controller is None:
            return
        catalog = self._controller.heatmap_catalog_snapshot()
        settings = self._controller.heatmap_applied_settings_snapshot()
        self._build_heatmap_draft_models(settings, catalog)
        frame.clear()
        with frame:
            if catalog is None:
                ui.Label("Heatmap Settings will load after the production stage opens.")
                return
            self._build_heatmap_settings_editor(catalog)

    def _build_heatmap_draft_models(self, settings, catalog) -> None:
        """Create detached models; their edits cannot call runtime or mutate USD."""

        calibration_settings, _color_scale_settings, _color_stop_settings, _settings = (
            _heatmap_settings_types()
        )
        selector_ids = catalog.selector_ids if catalog is not None else ()
        selected = frozenset(settings.isolation_selectors)
        self._heatmap_isolation_models = {
            selector_id: ui.SimpleBoolModel(selector_id in selected)
            for selector_id in selector_ids
        }
        descriptors = catalog.calibration if catalog is not None else ()
        self._heatmap_calibration_models = {
            descriptor.calibration_id: {
                "delta": ui.SimpleFloatModel(
                    settings.calibration.get(
                        descriptor.calibration_id,
                        calibration_settings(),
                    ).delta_celsius
                ),
                "offset": ui.SimpleFloatModel(
                    settings.calibration.get(
                        descriptor.calibration_id,
                        calibration_settings(),
                    ).temperature_offset_celsius
                ),
            }
            for descriptor in descriptors
        }
        self._heatmap_color_stop_models = {
            stop.stop_id: {
                "enabled": ui.SimpleBoolModel(stop.enabled),
                "position": ui.SimpleFloatModel(stop.position_percent),
            }
            for stop in settings.color_scale.stops
        }
        self._heatmap_color_stops = settings.color_scale.stops
        self._heatmap_minimum_clamp_model = ui.SimpleFloatModel(
            settings.color_scale.minimum_clamp_percent
        )
        self._heatmap_maximum_clamp_model = ui.SimpleFloatModel(
            settings.color_scale.maximum_clamp_percent
        )

    def _build_heatmap_settings_editor(self, catalog) -> None:
        """Build Isolation, dynamic Calibration, and Color Scale draft frames."""

        with ui.VStack(spacing=6, height=0, content_clipping=True):
            ui.Label("Settings")
            self._build_heatmap_isolation_frame(catalog)
            self._build_heatmap_calibration_frame(catalog)
            self._build_heatmap_color_scale_frame()
            ui.Button(
                "Apply Heatmaps Settings",
                height=28,
                clicked_fn=self._apply_heatmap_settings,
            )

    def _build_heatmap_isolation_frame(self, catalog) -> None:
        with ui.CollapsableFrame("Isolation", collapsed=True, height=0):
            with ui.VStack(spacing=3, height=0):
                for selector in catalog.selectors:
                    model = self._heatmap_isolation_models[selector.selector_id]
                    with ui.HStack(height=20):
                        ui.CheckBox(model=model, width=24)
                        ui.Label(selector.label)

    def _build_heatmap_calibration_frame(self, catalog) -> None:
        with ui.CollapsableFrame("Calibration", collapsed=True, height=0):
            descriptors_by_asset: dict[str, list[object]] = {}
            for descriptor in catalog.calibration:
                descriptors_by_asset.setdefault(
                    descriptor.asset_label,
                    [],
                ).append(descriptor)
            with ui.VStack(spacing=4, height=0):
                for asset_label, descriptors in sorted(descriptors_by_asset.items()):
                    with ui.CollapsableFrame(
                        asset_label,
                        collapsed=True,
                        height=0,
                    ):
                        with ui.VStack(spacing=3, height=0):
                            by_zone: dict[str, list[object]] = {}
                            for descriptor in descriptors:
                                by_zone.setdefault(descriptor.display_zone, []).append(
                                    descriptor
                                )
                            for zone, components in sorted(by_zone.items()):
                                with ui.CollapsableFrame(
                                    zone,
                                    collapsed=True,
                                    height=0,
                                ):
                                    with ui.VStack(spacing=3, height=0):
                                        for descriptor in components:
                                            models = self._heatmap_calibration_models[
                                                descriptor.calibration_id
                                            ]
                                            ui.Label(descriptor.display_component)
                                            with ui.HStack(height=20):
                                                ui.Label("Delta", width=130)
                                                ui.FloatField(model=models["delta"])
                                            with ui.HStack(height=20):
                                                ui.Label(
                                                    "Temperature Offset",
                                                    width=130,
                                                )
                                                ui.FloatField(model=models["offset"])

    def _build_heatmap_color_scale_frame(self) -> None:
        with ui.CollapsableFrame("Color Scale", collapsed=True, height=0):
            with ui.VStack(spacing=3, height=0):
                with ui.HStack(height=20):
                    ui.Label("Minimum Clamp %", width=150)
                    ui.FloatField(model=self._heatmap_minimum_clamp_model)
                with ui.HStack(height=20):
                    ui.Label("Maximum Clamp %", width=150)
                    ui.FloatField(model=self._heatmap_maximum_clamp_model)
                for stop in self._heatmap_color_stops:
                    models = self._heatmap_color_stop_models[stop.stop_id]
                    with ui.HStack(height=20):
                        ui.CheckBox(model=models["enabled"], width=24)
                        ui.Label(stop.stop_id.title(), width=80)
                        ui.Label("Position %", width=75)
                        ui.FloatField(model=models["position"], width=90)
                        ui.Label(_colour_swatch_text(stop.color), width=100)

    def _toggle_heatmap_test(self) -> None:
        """Use persisted settings for Test and exact Session restoration for Restore."""

        restoring = self._controller.heatmap_test_active()
        if restoring:
            result = self._controller.restore_heatmap_test_in_kit()
        else:
            self._refresh_heatmap_telemetry_snapshot()
            result = self._controller.test_heatmaps_in_kit()
        self._set_heatmap_test_button_state(result.enabled)
        self._set_status(result.message)
        self._log_heatmap_action(
            "RESTORE HEATMAP TEST" if restoring else "TEST HEATMAPS",
            "COMPLETE" if result.success else "FAIL",
            {
                "enabled": str(result.enabled).lower(),
                "result": result.message,
            },
        )

    def _apply_heatmap_settings(self) -> None:
        """Submit one complete draft candidate; earlier model edits are inert."""

        previous = self._controller.heatmap_applied_settings_snapshot()
        try:
            candidate = self._heatmap_settings_from_draft()
        except ValueError as error:
            self._set_status(f"Heatmap Settings are invalid: {error}")
            self._log_heatmap_action(
                "APPLY HEATMAP SETTINGS",
                "FAIL",
                {"result": f"validation: {error}"},
            )
            return
        changes = _heatmap_settings_changes(previous, candidate)
        result = self._controller.apply_heatmap_settings_in_kit(candidate)
        self._set_heatmap_test_button_state(result.enabled)
        self._set_status(result.message)
        details = dict(changes)
        if not details:
            details["changes"] = "none"
        details["enabled"] = str(result.enabled).lower()
        details["result"] = result.message
        self._log_heatmap_action(
            "APPLY HEATMAP SETTINGS",
            "COMPLETE" if result.success else "FAIL",
            details,
        )

    def _log_heatmap_action(
        self,
        process: str,
        state: str,
        details: dict[str, str],
    ) -> None:
        """Write one timestamped Heatmap action record through the shared formatter."""

        from digital_twin_runtime_suite.app.status_log import (
            format_dtrs_diagnostic_content,
            format_dtrs_status_block,
        )

        content = format_dtrs_diagnostic_content(
            owner="HEATMAPS",
            process=process,
            state=state,
            details=details,
        )
        carb.log_warn(
            format_dtrs_status_block(
                content,
                append_local_timestamp=_with_dtrs_local_timestamp,
            )
        )

    def _heatmap_settings_from_draft(self):
        """Build a detached immutable candidate from the current UI models."""

        (
            calibration_settings,
            color_scale_settings,
            color_stop_settings,
            settings_type,
        ) = _heatmap_settings_types()
        selectors = tuple(
            selector_id
            for selector_id, model in self._heatmap_isolation_models.items()
            if model.get_value_as_bool()
        )
        calibration = {
            calibration_id: calibration_settings(
                delta_celsius=models["delta"].get_value_as_float(),
                temperature_offset_celsius=models["offset"].get_value_as_float(),
            )
            for calibration_id, models in self._heatmap_calibration_models.items()
        }
        stops = tuple(
            color_stop_settings(
                stop_id=stop.stop_id,
                enabled=models["enabled"].get_value_as_bool(),
                position_percent=models["position"].get_value_as_float(),
                color=stop.color,
            )
            for stop in self._heatmap_color_stops
            for models in (self._heatmap_color_stop_models[stop.stop_id],)
        )
        return settings_type(
            isolation_selectors=selectors,
            calibration=calibration,
            color_scale=color_scale_settings(
                minimum_clamp_percent=(
                    self._heatmap_minimum_clamp_model.get_value_as_float()
                ),
                maximum_clamp_percent=(
                    self._heatmap_maximum_clamp_model.get_value_as_float()
                ),
                stops=stops,
            ),
        )

    def _refresh_heatmap_telemetry_snapshot(self) -> None:
        """Forward provider state through the runtime's public telemetry seam."""

        provider = getattr(self, "_telemetry_provider", None)
        if provider is None:
            return
        self._controller.configure_heatmap_telemetry_config(provider.config)
        self._controller.refresh_heatmap_telemetry_snapshot(provider.latest_snapshot)

    def _set_heatmap_test_button_state(self, enabled: bool) -> None:
        button = getattr(self, "_heatmap_test_button", None)
        if button is None:
            return
        label = heatmap_test_action_label(enabled)
        button.text = label
        button.tooltip = label


def _colour_swatch_text(color: tuple[float, float, float]) -> str:
    """Show a read-only stable RGB swatch label until colour editing is required."""

    return "RGB " + ", ".join(f"{channel:g}" for channel in color)


def _heatmap_settings_changes(previous, candidate) -> tuple[tuple[str, str], ...]:
    """Load the app-owned comparison only after extension source setup is complete."""

    from digital_twin_runtime_suite.app.heatmaps.settings import diff_heatmap_settings

    return diff_heatmap_settings(previous, candidate)


def _with_dtrs_local_timestamp(message: str) -> str:
    """Load shared timestamping only after extension source setup is complete."""

    from digital_twin_runtime_suite.app.diagnostics import (
        with_dtrs_local_timestamp,
    )

    return with_dtrs_local_timestamp(message)


def _heatmap_settings_types():
    """Import app settings only after the extension establishes its source root."""

    from digital_twin_runtime_suite.app.heatmaps.settings import (
        CalibrationSettings,
        ColorScaleSettings,
        ColorStopSettings,
        HeatmapSettings,
    )

    return (
        CalibrationSettings,
        ColorScaleSettings,
        ColorStopSettings,
        HeatmapSettings,
    )
