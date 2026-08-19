"""Streamlines and validation-receipt OmniUI controls."""

from __future__ import annotations

import carb
import omni.ui as ui

COMPACT_TEXT_LENGTH = 44
SERVER_VIEW_LABEL_WIDTH = 150


def _compact_text(value: str, max_length: int = COMPACT_TEXT_LENGTH) -> str:
    text = str(value)
    if len(text) <= max_length:
        return text
    return f"{text[: max_length - 3]}..."


def _with_dtrs_local_timestamp(message: str) -> str:
    """Use the shared formatter after the composition root configures imports."""

    from digital_twin_runtime_suite.app.diagnostics import (
        with_dtrs_local_timestamp,
    )

    return with_dtrs_local_timestamp(message)


class StreamlinesUiMixin:
    """Build Streamlines controls and forward UI intent to existing workflows."""

    def _build_validation_receipt_controls(self) -> None:
        """Build developer-only validation and geometry-preview controls."""

        with ui.VStack(spacing=6, content_clipping=True):
            with ui.HStack(height=24, spacing=6, content_clipping=True):
                ui.Label(
                    "Reuse verified VTI receipts",
                    width=ui.Fraction(1),
                )
                ui.CheckBox(model=self._reuse_vti_receipts_model, width=24)
            with ui.HStack(height=24, spacing=6, content_clipping=True):
                ui.Label(
                    "Reuse verified Streamlines cache receipts",
                    width=ui.Fraction(1),
                )
                ui.CheckBox(
                    model=self._reuse_streamlines_receipts_model,
                    width=24,
                )
            self._validation_receipt_status_label = ui.Label(
                "Receipt reuse is opt-in and identity checked.",
                height=32,
                word_wrap=True,
            )

    def _build_streamlines_profile_controls(self) -> None:
        """Build production profile preference and shared material tuning."""

        from digital_twin_runtime_suite.app.streamlines.profile import (
            STREAMLINES_PROFILE_LABELS,
            StreamlinesProfileId,
        )

        with ui.VStack(spacing=6, content_clipping=True):
            profiles = tuple(StreamlinesProfileId)
            snapshot = self._controller.streamlines_profile_preference_snapshot()
            preferred = snapshot.preferred_profile
            with ui.HStack(height=24, spacing=6, content_clipping=True):
                ui.Label("Profile", width=SERVER_VIEW_LABEL_WIDTH)
            self._streamlines_profile_combo = ui.ComboBox(
                profiles.index(preferred),
                *(STREAMLINES_PROFILE_LABELS[item] for item in profiles),
                width=ui.Fraction(1),
            )
            self._streamlines_final_acceptance_frame = ui.Frame(visible=False)
            with self._streamlines_final_acceptance_frame:
                with ui.VStack(spacing=6, content_clipping=True):
                    ui.Label("Final acceptance failure reason", height=18)
                    self._streamlines_final_acceptance_failure_reason = ui.StringField()
                    self._streamlines_final_acceptance_confirm_button = ui.Button(
                        "Confirm Clean Playback",
                        height=28,
                        clicked_fn=self._confirm_streamlines_final_acceptance,
                    )
                    self._streamlines_final_acceptance_failure_button = ui.Button(
                        "Report Clean Playback Failure",
                        height=28,
                        clicked_fn=self._reject_streamlines_final_acceptance,
                    )
            ui.Label("Material Tuning", height=18)
            self._streamlines_material_tuning_combos = {
                "opacity": self._build_streamlines_tuning_combo(
                    "Opacity", 3, (0.40, 0.55, 0.70, 0.85, 1.00)
                ),
                "emission": self._build_streamlines_tuning_combo(
                    "Emission", 2, (0.5, 1.0, 1.5, 2.0, 3.0)
                ),
                "lighting": self._build_streamlines_tuning_combo(
                    "Lighting Influence", 2, (0.0, 0.1, 0.2, 0.35, 0.5)
                ),
            }
            ui.Button(
                "Apply Material Preview",
                height=28,
                clicked_fn=self._apply_streamlines_material_preview,
            )
            ui.Button(
                "Accept Material Candidate",
                height=28,
                clicked_fn=self._accept_streamlines_material_candidate,
            )
            self._streamlines_material_status_label = ui.Label(
                "Material preview changes no cache, workload, profile, or scheduler.",
                height=32,
                word_wrap=True,
            )
        profile_model = self._combo_index_model(self._streamlines_profile_combo)
        if profile_model:
            profile_model.add_value_changed_fn(
                self._on_streamlines_profile_preference_changed
            )

    def _build_streamlines_tuning_combo(
        self,
        label: str,
        default_index: int,
        values,
    ):
        with ui.HStack(height=24, spacing=6, content_clipping=True):
            ui.Label(label, width=SERVER_VIEW_LABEL_WIDTH)
            return ui.ComboBox(
                default_index,
                *(str(value) for value in values),
                width=ui.Fraction(1),
            )

    def _on_streamlines_profile_preference_changed(self, model) -> None:
        from digital_twin_runtime_suite.app.streamlines.profile import (
            StreamlinesProfileId,
        )

        if self._updating_streamlines_profile_combo:
            return
        self._cancel_streamlines_material_preview()
        profiles = tuple(StreamlinesProfileId)
        index = self._model_int(model)
        if not 0 <= index < len(profiles):
            return
        profile_id = profiles[index]
        visualization = self._controller.visualization_snapshot()
        self._streamlines_workflow.request_profile(
            profile_id,
            streamlines_active=visualization.committed.value == "Streamlines",
        )

    def _apply_streamlines_material_preview(self) -> None:
        """Schedule one cancellable material-only preview and performance gate."""

        options = {
            "opacity": (0.40, 0.55, 0.70, 0.85, 1.00),
            "emission": (0.5, 1.0, 1.5, 2.0, 3.0),
            "lighting": (0.0, 0.1, 0.2, 0.35, 0.5),
        }
        selected = {
            name: values[
                self._model_int(
                    self._combo_index_model(
                        self._streamlines_material_tuning_combos[name]
                    )
                )
            ]
            for name, values in options.items()
        }
        self._streamlines_workflow.preview_material(
            opacity=selected["opacity"],
            emission_intensity=selected["emission"],
            lighting_influence=selected["lighting"],
        )

    def _accept_streamlines_material_candidate(self) -> None:
        """Accept the last applied immutable session presentation snapshot."""

        self._streamlines_workflow.accept_material_candidate()

    def _cancel_streamlines_material_preview(self) -> None:
        """Cancel delayed material evidence after profile/workload supersession."""

        if self._streamlines_workflow:
            self._streamlines_workflow.cancel_material_preview()

    def _restore_streamlines_profile_selection(self, committed) -> None:
        """Restore the ComboBox after a rejected profile transition."""

        if self._streamlines_profile_combo is None:
            return
        profiles = tuple(type(committed))
        self._updating_streamlines_profile_combo = True
        try:
            model = self._combo_index_model(self._streamlines_profile_combo)
            if model is not None:
                model.set_value(profiles.index(committed))
        finally:
            self._updating_streamlines_profile_combo = False

    def _set_streamlines_material_status(self, message: str) -> None:
        """Show a workflow result in the material-only UI status label."""

        if self._streamlines_material_status_label is not None:
            self._streamlines_material_status_label.text = message

    def _on_validation_receipt_reuse_changed(self, _model) -> None:
        """Persist preferences immediately; validation remains background-owned."""

        if not self._controller:
            return
        reuse_vti = bool(self._reuse_vti_receipts_model.as_bool)
        reuse_streamlines = bool(self._reuse_streamlines_receipts_model.as_bool)
        try:
            path = self._validation_workflow.save_reuse_settings(
                reuse_vti=reuse_vti,
                reuse_streamlines=reuse_streamlines,
            )
        except Exception as error:
            message = f"Validation receipt settings were not saved: {error}"
            if self._validation_receipt_status_label:
                self._validation_receipt_status_label.text = _compact_text(message)
                self._validation_receipt_status_label.tooltip = message
            carb.log_error(_with_dtrs_local_timestamp(message))
            return
        message = f"Receipt reuse settings saved to {path.name}."
        if self._validation_receipt_status_label:
            self._validation_receipt_status_label.text = _compact_text(message)
            self._validation_receipt_status_label.tooltip = message
