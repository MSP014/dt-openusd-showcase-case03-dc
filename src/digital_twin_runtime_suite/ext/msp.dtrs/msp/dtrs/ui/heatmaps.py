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
        self._heatmap_test_button.enabled = False
        self._heatmap_settings_frame = ui.Frame()
        self._refresh_heatmap_settings_controls()

    def _refresh_heatmap_settings_controls(self) -> None:
        """Repopulate draft models after the ready-stage success barrier."""

        frame = getattr(self, "_heatmap_settings_frame", None)
        if frame is None or self._controller is None:
            return
        catalog = self._controller.heatmap_catalog_snapshot()
        ready = catalog is not None and catalog.ready
        self._set_heatmap_test_button_state(
            self._controller.heatmap_test_active(),
            ready=ready,
        )
        frame.clear()
        with frame:
            if not ready:
                ui.Label(
                    "Heatmap Settings will load after the production stage is ready."
                )
                return
            settings = self._controller.heatmap_applied_settings_snapshot()
            self._build_heatmap_draft_models(settings, catalog)
            self._build_heatmap_settings_editor(catalog)

    def _build_heatmap_draft_models(self, settings, catalog) -> None:
        """Create detached models; their edits cannot call runtime or mutate USD."""

        calibration_settings, _settings = _heatmap_settings_types()
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
                "hex": ui.SimpleStringModel(_heatmap_rgb_to_hex(stop.color)),
            }
            for stop in settings.color_scale.stops
        }
        self._heatmap_global_celsius_scale = (
            self._controller.heatmap_global_celsius_scale_snapshot()
        )
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
                displayed_parents: set[str] = set()
                for selector in catalog.selectors:
                    if selector.parent_id is not None:
                        if selector.parent_id not in displayed_parents:
                            ui.Label(selector.parent_label, height=20)
                            displayed_parents.add(selector.parent_id)
                        self._build_heatmap_isolation_selector(selector, indent=16)
                        continue
                    self._build_heatmap_isolation_selector(selector)

    def _build_heatmap_isolation_selector(self, selector, *, indent: int = 0) -> None:
        """Build one draft-only selector with optional hierarchy indentation."""

        model = self._heatmap_isolation_models[selector.selector_id]
        with ui.HStack(height=20):
            if indent:
                ui.Spacer(width=indent)
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
                with ui.CollapsableFrame("Clamps", collapsed=True, height=0):
                    with ui.VStack(spacing=3, height=0):
                        with ui.HStack(height=20):
                            ui.Label("Minimum Clamp %", width=150)
                            ui.FloatField(model=self._heatmap_minimum_clamp_model)
                        with ui.HStack(height=20):
                            ui.Label("Maximum Clamp %", width=150)
                            ui.FloatField(model=self._heatmap_maximum_clamp_model)
                feedback = self._heatmap_color_scale_draft_feedback()
                feedback_by_stop_id = {item.stop_id: item for item in feedback}
                self._heatmap_color_stop_label_widgets = {}
                self._heatmap_color_preview_widgets = {}
                for stop_id, models in self._heatmap_color_stop_models.items():
                    stop_feedback = feedback_by_stop_id[stop_id]
                    with ui.HStack(height=20, spacing=8):
                        ui.CheckBox(model=models["enabled"], width=24)
                        self._heatmap_color_stop_label_widgets[stop_id] = ui.Label(
                            stop_feedback.temperature_label,
                            width=88,
                        )
                        ui.Label("Position %", width=75)
                        ui.FloatField(model=models["position"], width=90)
                        ui.StringField(model=models["hex"], width=95)
                        self._heatmap_color_preview_widgets[stop_id] = ui.Rectangle(
                            style=_heatmap_preview_style(stop_feedback.preview_color),
                            width=32,
                            height=20,
                        )
                self._install_heatmap_color_scale_draft_callbacks()

    def _install_heatmap_color_scale_draft_callbacks(self) -> None:
        """Refresh draft-only labels and previews without submitting settings."""

        for models in self._heatmap_color_stop_models.values():
            for model in (models["enabled"], models["position"], models["hex"]):
                model.add_value_changed_fn(self._refresh_heatmap_color_scale_draft)
        self._heatmap_minimum_clamp_model.add_value_changed_fn(
            self._refresh_heatmap_color_scale_draft
        )
        self._heatmap_maximum_clamp_model.add_value_changed_fn(
            self._refresh_heatmap_color_scale_draft
        )

    def _refresh_heatmap_color_scale_draft(self, _model) -> None:
        """Update informational widgets only; Apply remains the mutation boundary."""

        feedback = self._heatmap_color_scale_draft_feedback()
        for item in feedback:
            self._heatmap_color_stop_label_widgets[item.stop_id].text = (
                item.temperature_label
            )
            preview = self._heatmap_color_preview_widgets[item.stop_id]
            preview.set_style(_heatmap_preview_style(item.preview_color))

    def _heatmap_color_scale_draft_feedback(self):
        """Read current draft models through the pure Heatmap palette helper."""

        draft_stop, feedback, _settings_from_draft, _rgb_to_hex = (
            _heatmap_color_scale_functions()
        )
        stops = tuple(
            draft_stop(
                stop_id=stop_id,
                enabled=models["enabled"].get_value_as_bool(),
                position_percent=models["position"].get_value_as_float(),
                hex_color=models["hex"].get_value_as_string(),
            )
            for stop_id, models in self._heatmap_color_stop_models.items()
        )
        scale = self._heatmap_global_celsius_scale
        if scale is None:
            return feedback(
                None,
                minimum_clamp_percent=0.0,
                maximum_clamp_percent=100.0,
                stops=stops,
            )
        return feedback(
            _heatmap_celsius_scale(scale),
            minimum_clamp_percent=(
                self._heatmap_minimum_clamp_model.get_value_as_float()
            ),
            maximum_clamp_percent=(
                self._heatmap_maximum_clamp_model.get_value_as_float()
            ),
            stops=stops,
        )

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
        draft_stop, _feedback, settings_from_draft, _rgb_to_hex = (
            _heatmap_color_scale_functions()
        )
        stops = tuple(
            draft_stop(
                stop_id=stop_id,
                enabled=models["enabled"].get_value_as_bool(),
                position_percent=models["position"].get_value_as_float(),
                hex_color=models["hex"].get_value_as_string(),
            )
            for stop_id, models in self._heatmap_color_stop_models.items()
        )
        return settings_type(
            isolation_selectors=selectors,
            calibration=calibration,
            color_scale=settings_from_draft(
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

    def _set_heatmap_test_button_state(
        self,
        active: bool,
        *,
        ready: bool | None = None,
    ) -> None:
        """Synchronize the next action and availability with runtime state."""

        button = getattr(self, "_heatmap_test_button", None)
        if button is None:
            return
        label = heatmap_test_action_label(active)
        button.text = label
        button.tooltip = label
        if ready is not None:
            button.enabled = ready


def _heatmap_preview_style(color: tuple[float, float, float] | None) -> dict:
    """Build one draft preview style without any material or USD operation."""

    return {
        "background_color": _heatmap_rgb_to_omniui_color(
            color if color is not None else (0.2, 0.2, 0.2)
        )
    }


def _heatmap_rgb_to_omniui_color(color: tuple[float, float, float]) -> int:
    red, green, blue = (round(channel * 255) for channel in color)
    return 0xFF000000 | (blue << 16) | (green << 8) | red


def _heatmap_celsius_scale(snapshot):
    """Adapt the runtime read-only snapshot to the palette's existing scale type."""

    from digital_twin_runtime_suite.app.heatmaps.scalar import CelsiusScale

    return CelsiusScale(snapshot.minimum_celsius, snapshot.maximum_celsius)


def _heatmap_rgb_to_hex(color: tuple[float, float, float]) -> str:
    """Import strict Heatmap HEX formatting after the extension source root exists."""

    _draft_stop, _feedback, _settings_from_draft, rgb_to_hex = (
        _heatmap_color_scale_functions()
    )
    return rgb_to_hex(color)


def _heatmap_color_scale_functions():
    """Load pure Color Scale draft helpers without creating a second colour store."""

    from digital_twin_runtime_suite.app.heatmaps.palette import (
        ColorScaleStopDraft,
        color_scale_draft_feedback,
        color_scale_settings_from_draft,
        heatmap_rgb_to_hex,
    )

    return (
        ColorScaleStopDraft,
        color_scale_draft_feedback,
        color_scale_settings_from_draft,
        heatmap_rgb_to_hex,
    )


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
        HeatmapSettings,
    )

    return (
        CalibrationSettings,
        HeatmapSettings,
    )
