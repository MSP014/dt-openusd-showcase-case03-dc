# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""Local operator-override persistence for the DTRS runtime facade."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from digital_twin_runtime_suite.app.config import (
    CameraConfig,
    ChassisPresentationConfig,
    EmitterLayoutConfig,
    GridConfig,
    LightingConfig,
    RuntimeConfig,
    SmokeTuningConfig,
    StreamlinesPresentationConfig,
    ValidationReceiptReuseConfig,
    XRayMaterialConfig,
    chassis_presentation_with_operator_state,
    format_runtime_override,
)


class OperatorSettingsRuntimeMixin:
    """Persist local operator settings while retaining controller-owned config."""

    def project_defaults(self) -> RuntimeConfig:
        """Return the project defaults without local operator overrides."""

        return RuntimeConfig.load(
            self._config_path,
            apply_local_overrides=False,
        )

    def save_runtime_override(
        self,
        lighting: LightingConfig,
        camera: CameraConfig | None = None,
        grid: GridConfig | None = None,
        smoke_tuning: SmokeTuningConfig | None = None,
        emitter_layout: EmitterLayoutConfig | None = None,
        chassis_presentation: ChassisPresentationConfig | None = None,
        streamlines_presentation_period_seconds: float | None = None,
        validation_receipts: ValidationReceiptReuseConfig | None = None,
        streamlines_presentation: StreamlinesPresentationConfig | None = None,
    ) -> Path:
        """Persist local operator settings beside the base config."""

        active_camera = camera or self.config.camera
        active_grid = grid or self.config.grid
        active_smoke_tuning = smoke_tuning or self.config.simulation_cache.smoke_tuning
        active_emitter_layout = (
            emitter_layout or self.config.simulation_cache.emitter_layout
        )
        active_chassis_presentation = (
            chassis_presentation or self.config.chassis_presentation
        )
        active_presentation_period = (
            streamlines_presentation_period_seconds
            if streamlines_presentation_period_seconds is not None
            else self.config.simulation_cache.streamlines_presentation_period_seconds
        )
        active_validation_receipts = (
            validation_receipts or self.config.validation_receipts
        )
        active_streamlines_presentation = (
            streamlines_presentation or self.config.streamlines_presentation
        )
        local_path = RuntimeConfig.local_config_path_for(self._config_path)
        # Replace only a complete file so interrupted UI actions never leave a
        # partially authored local override behind.
        temporary_path = local_path.with_name(f"{local_path.name}.tmp")
        temporary_path.write_text(
            format_runtime_override(
                lighting,
                active_camera,
                active_grid,
                active_smoke_tuning,
                active_emitter_layout,
                active_chassis_presentation,
                active_presentation_period,
                active_validation_receipts,
                active_streamlines_presentation,
            ),
            encoding="utf-8",
        )
        temporary_path.replace(local_path)
        self.config = RuntimeConfig.load(self._config_path)
        return local_path

    def save_validation_receipt_reuse_override(
        self,
        *,
        reuse_verified_vti_receipts: bool,
        reuse_verified_streamlines_cache_receipts: bool,
    ) -> Path:
        """Persist receipt preferences and publish current session evidence."""

        preferences = ValidationReceiptReuseConfig(
            reuse_verified_vti_receipts=reuse_verified_vti_receipts,
            reuse_verified_streamlines_cache_receipts=(
                reuse_verified_streamlines_cache_receipts
            ),
        )
        path = self.save_runtime_override(
            self.config.lighting,
            self.config.camera,
            self.config.grid,
            self.config.simulation_cache.smoke_tuning,
            self.config.simulation_cache.emitter_layout,
            self.config.chassis_presentation,
            self.config.simulation_cache.streamlines_presentation_period_seconds,
            preferences,
        )
        self._flow_validation_cache.configure_persistence(
            persisted_store=self._validation_receipt_store,
            reuse_persisted=reuse_verified_vti_receipts,
        )
        if reuse_verified_vti_receipts:
            self._flow_validation_cache.persist_session_preflight_receipts()
        if reuse_verified_streamlines_cache_receipts:
            self.persist_session_streamlines_cache_validation_receipts()
        return path

    def save_smoke_tuning_override(self, smoke_tuning: SmokeTuningConfig) -> Path:
        """Persist a successfully applied Flow tuning without losing peer overrides."""

        return self.save_runtime_override(
            self.config.lighting,
            self.config.camera,
            self.config.grid,
            smoke_tuning,
        )

    def save_streamlines_presentation_period(self, period_seconds: float) -> Path:
        """Persist an accepted cached-playback period without cache invalidation."""

        if period_seconds <= 0.0:
            raise ValueError("Streamlines presentation period must be positive.")
        return self.save_runtime_override(
            self.config.lighting,
            self.config.camera,
            self.config.grid,
            self.config.simulation_cache.smoke_tuning,
            self.config.simulation_cache.emitter_layout,
            self.config.chassis_presentation,
            period_seconds,
        )

    def save_streamlines_presentation_override(
        self,
        presentation: StreamlinesPresentationConfig,
    ) -> Path:
        """Persist fixed velocity presentation without touching cache identity."""

        return self.save_runtime_override(
            self.config.lighting,
            self.config.camera,
            self.config.grid,
            self.config.simulation_cache.smoke_tuning,
            self.config.simulation_cache.emitter_layout,
            self.config.chassis_presentation,
            self.config.simulation_cache.streamlines_presentation_period_seconds,
            self.config.validation_receipts,
            presentation,
        )

    def save_emitter_layout_override(
        self,
        emitter_layout: EmitterLayoutConfig,
    ) -> Path:
        """Persist a successfully applied tracer layout without losing peers."""

        return self.save_runtime_override(
            self.config.lighting,
            self.config.camera,
            self.config.grid,
            self.config.simulation_cache.smoke_tuning,
            emitter_layout,
        )

    def save_chassis_presentation_override(
        self,
        visibility_by_group: dict[str, bool],
        face_panel_open: bool | None,
    ) -> Path:
        """Persist validated enclosure controls without replacing peer overrides."""

        presentation = chassis_presentation_with_operator_state(
            self.config.chassis_presentation,
            visibility_by_group,
            face_panel_open,
        )
        return self.save_runtime_override(
            self.config.lighting,
            self.config.camera,
            self.config.grid,
            self.config.simulation_cache.smoke_tuning,
            self.config.simulation_cache.emitter_layout,
            presentation,
        )

    def save_normal_map_scale_override(self, normal_map_scale: float) -> Path:
        """Persist the temporary material-tuning value with appearance controls."""

        if not 0.0 <= normal_map_scale <= 4.0:
            raise ValueError("Normal map scale must be between 0 and 4.")
        presentation = replace(
            self.config.chassis_presentation,
            materials=replace(
                self.config.chassis_presentation.materials,
                normal_map_scale=normal_map_scale,
            ),
        )
        return self.save_runtime_override(
            self.config.lighting,
            self.config.camera,
            self.config.grid,
            self.config.simulation_cache.smoke_tuning,
            self.config.simulation_cache.emitter_layout,
            presentation,
        )

    def save_xray_material_override(self, xray: XRayMaterialConfig) -> Path:
        """Persist Fresnel parameters, never runtime target selection."""

        presentation = replace(
            self.config.chassis_presentation,
            materials=replace(
                self.config.chassis_presentation.materials,
                xray=xray,
            ),
        )
        return self.save_runtime_override(
            self.config.lighting,
            self.config.camera,
            self.config.grid,
            self.config.simulation_cache.smoke_tuning,
            self.config.simulation_cache.emitter_layout,
            presentation,
        )

    def save_lighting_override(self, lighting: LightingConfig) -> Path:
        """Persist local operator lighting settings beside the base config."""

        return self.save_runtime_override(
            lighting,
            self.config.camera,
            self.config.grid,
        )

    def clear_camera_override(self, lighting: LightingConfig) -> Path:
        """Persist lighting while removing any local camera override."""

        local_path = RuntimeConfig.local_config_path_for(self._config_path)
        # Match save_runtime_override's atomic replacement contract while
        # intentionally omitting the camera section from the written override.
        temporary_path = local_path.with_name(f"{local_path.name}.tmp")
        temporary_path.write_text(
            format_runtime_override(
                lighting,
                None,
                self.config.grid,
                self.config.simulation_cache.smoke_tuning,
                self.config.simulation_cache.emitter_layout,
                self.config.chassis_presentation,
                self.config.simulation_cache.streamlines_presentation_period_seconds,
                self.config.validation_receipts,
                self.config.streamlines_presentation,
            ),
            encoding="utf-8",
        )
        temporary_path.replace(local_path)
        self.config = RuntimeConfig.load(self._config_path)
        return local_path

    def save_grid_override(self, lighting: LightingConfig, grid: GridConfig) -> Path:
        """Persist local operator grid settings beside the base config."""

        return self.save_runtime_override(
            lighting,
            self.config.camera,
            grid,
        )

    def clear_lighting_override(self) -> RuntimeConfig:
        """Remove local operator lighting settings and reload project defaults."""

        local_path = RuntimeConfig.local_config_path_for(self._config_path)
        preferences = self.config.validation_receipts
        if (
            preferences.reuse_verified_vti_receipts
            or preferences.reuse_verified_streamlines_cache_receipts
        ):
            defaults = self.project_defaults()
            self.save_runtime_override(
                defaults.lighting,
                self.config.camera,
                self.config.grid,
                self.config.simulation_cache.smoke_tuning,
                self.config.simulation_cache.emitter_layout,
                self.config.chassis_presentation,
                self.config.simulation_cache.streamlines_presentation_period_seconds,
                preferences,
            )
            return self.config
        if local_path.exists():
            local_path.unlink()
        self.config = RuntimeConfig.load(self._config_path)
        return self.config
