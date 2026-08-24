# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""Server-appearance and material-control OmniUI builders."""

from __future__ import annotations

import omni.ui as ui

SERVER_VIEW_LABEL_WIDTH = 150


class AppearanceUiMixin:
    """Own server-appearance models and material-control construction."""

    def _build_material_controls(self, presentation) -> None:
        materials = presentation.materials
        self._build_config_section(
            "X-Ray",
            lambda: self._build_xray_controls(presentation),
            collapsed=True,
        )
        self._build_config_section(
            "Normal Map Scale",
            lambda: self._build_normal_map_scale_controls(materials),
            collapsed=True,
        )

    def _build_xray_controls(self, presentation) -> None:
        """Build transient target selection before persistent Fresnel values.

        The config defines available groups; these Kit models deliberately hold
        no saved selection so every startup and reload begins with X-Ray OFF.
        """

        for group in presentation.xray_target_groups:
            model = self._xray_target_models.setdefault(
                group.group_id,
                # X-Ray bindings are transient Session Layer state. Parameters
                # persist, but a fresh app/config lifecycle always starts OFF.
                ui.SimpleBoolModel(False),
            )
            with ui.HStack(height=24, spacing=6, content_clipping=True):
                ui.Label(
                    group.label,
                    width=SERVER_VIEW_LABEL_WIDTH,
                    elided_text=True,
                    tooltip="Apply or release the production Fresnel material.",
                )
                self._xray_target_checkboxes[group.group_id] = ui.CheckBox(model=model)
        self._build_xray_fresnel_controls(presentation.materials.xray)
        ui.Button(
            "Apply",
            clicked_fn=self._apply_xray_material,
            height=26,
            width=ui.Percent(100),
        )

    def _build_xray_fresnel_controls(self, xray) -> None:
        """Build the single production-owned Fresnel parameter set."""

        from digital_twin_runtime_suite.app.view_controls import rgb_to_hex

        if not hasattr(self, "_xray_fresnel_models"):
            self._xray_fresnel_models = {
                "facing": ui.SimpleStringModel(rgb_to_hex(xray.facing_color)),
                "edge": ui.SimpleStringModel(rgb_to_hex(xray.edge_color)),
                "center": ui.SimpleFloatModel(xray.edge_center),
                "softness": ui.SimpleFloatModel(xray.edge_softness),
                "sharpness": ui.SimpleFloatModel(xray.edge_sharpness),
                "facing_roughness": ui.SimpleFloatModel(xray.facing_roughness),
                "edge_roughness": ui.SimpleFloatModel(xray.edge_roughness),
                "facing_opacity": ui.SimpleFloatModel(xray.facing_opacity),
                "edge_opacity": ui.SimpleFloatModel(xray.edge_opacity),
                "facing_emission": ui.SimpleFloatModel(xray.facing_emission),
                "edge_emission": ui.SimpleFloatModel(xray.edge_emission),
                "emission_scale": ui.SimpleFloatModel(xray.emission_scale),
            }
        for label, key in (("Facing Color", "facing"), ("Edge Color", "edge")):
            with ui.HStack(height=24):
                ui.Label(label, width=SERVER_VIEW_LABEL_WIDTH)
                ui.StringField(
                    model=self._xray_fresnel_models[key], width=ui.Fraction(1)
                )
        for label, key in (
            ("Edge Center", "center"),
            ("Edge Softness", "softness"),
            ("Edge Sharpness", "sharpness"),
            ("Facing Roughness", "facing_roughness"),
            ("Edge Roughness", "edge_roughness"),
            ("Facing Opacity", "facing_opacity"),
            ("Edge Opacity", "edge_opacity"),
            ("Facing Emission", "facing_emission"),
            ("Edge Emission", "edge_emission"),
            ("Emission Scale", "emission_scale"),
        ):
            with ui.HStack(height=24):
                ui.Label(label, width=SERVER_VIEW_LABEL_WIDTH)
                ui.FloatDrag(
                    model=self._xray_fresnel_models[key],
                    width=ui.Fraction(1),
                    precision=3,
                )

    def _build_normal_map_scale_controls(self, materials) -> None:
        if self._normal_map_scale_model is None:
            self._normal_map_scale_model = ui.SimpleFloatModel(
                materials.normal_map_scale
            )
        with ui.HStack(height=24, spacing=6, content_clipping=True):
            ui.Label("Scale", width=SERVER_VIEW_LABEL_WIDTH, elided_text=True)
            ui.FloatDrag(
                model=self._normal_map_scale_model,
                width=ui.Fraction(1),
                precision=2,
            )
        ui.Button(
            "Apply",
            clicked_fn=self._apply_normal_map_scale,
            height=26,
            width=ui.Percent(100),
        )

    def _build_server_view_controls(self, presentation) -> None:
        face_panel = presentation.face_panel
        if not presentation.visibility_groups and not face_panel.enabled:
            ui.Label("No visibility groups configured.", height=34, elided_text=True)
            return

        for group in presentation.visibility_groups:
            model = self._chassis_visibility_models.get(group.group_id)
            if not model:
                model = ui.SimpleBoolModel(group.default_visible)
                self._chassis_visibility_models[group.group_id] = model
            with ui.HStack(height=24, spacing=6, content_clipping=True):
                ui.Label(
                    group.label,
                    width=SERVER_VIEW_LABEL_WIDTH,
                    elided_text=True,
                    tooltip=group.label,
                )
                ui.CheckBox(model=model)
        if face_panel.enabled:
            from digital_twin_runtime_suite.app.view_controls import (
                face_panel_action_label,
            )

            with ui.HStack(height=24, spacing=6, content_clipping=True):
                action_text = face_panel_action_label(self._face_panel_open_state)
                self._face_panel_action_label = ui.Label(
                    action_text,
                    width=SERVER_VIEW_LABEL_WIDTH,
                    elided_text=True,
                    tooltip=action_text,
                )
                ui.CheckBox(model=self._face_panel_open_model)
        ui.Button(
            "Apply",
            clicked_fn=self._schedule_apply_chassis_visibility_controls,
            height=26,
            width=ui.Percent(100),
        )
