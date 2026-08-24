# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""Async UI orchestration for Streamlines profile and material actions."""

from __future__ import annotations

import asyncio
from collections.abc import Callable


class StreamlinesWorkflow:
    """Own cancellable Streamlines UI tasks without owning renderer state."""

    def __init__(
        self,
        controller,
        *,
        report_status: Callable[[str], None],
        report_material_status: Callable[[str], None],
        restore_profile_selection: Callable[[object], None],
        log_error: Callable[[str], None],
    ) -> None:
        self._controller = controller
        self._report_status = report_status
        self._report_material_status = report_material_status
        self._restore_profile_selection = restore_profile_selection
        self._log_error = log_error
        self._profile_task = None
        self._material_apply_task = None

    def request_profile(self, profile_id, *, streamlines_active: bool) -> None:
        """Persist an inactive preference or transition an active presentation."""

        self.cancel_material_apply()
        if not streamlines_active:
            self._controller.set_streamlines_profile_preference(profile_id)
            return
        task = self._profile_task
        if task is not None and not task.done():
            task.cancel()
        self._profile_task = asyncio.ensure_future(self._transition_profile(profile_id))

    def apply_material_settings(
        self,
        *,
        opacity: float,
        emission_intensity: float,
        lighting_influence: float,
    ) -> None:
        """Replace an in-flight material application with the latest UI request."""

        self.cancel_material_apply()
        self._material_apply_task = asyncio.ensure_future(
            self._apply_material_settings(
                opacity=opacity,
                emission_intensity=emission_intensity,
                lighting_influence=lighting_influence,
            )
        )

    def cancel_material_apply(self) -> None:
        """Cancel a stale material-only apply task and its completion guard."""

        task = self._material_apply_task
        if task is not None and not task.done():
            task.cancel()
        self._material_apply_task = None
        self._controller.cancel_streamlines_material_apply()

    def cancel(self) -> None:
        """Cancel every workflow-owned Streamlines task during teardown."""

        if self._profile_task is not None:
            self._profile_task.cancel()
        self._profile_task = None
        self.cancel_material_apply()

    async def _transition_profile(self, profile_id) -> None:
        try:
            request_profile_transition = (
                self._controller.request_streamlines_profile_transition_in_kit
            )
            result = await request_profile_transition(
                profile_id,
                status_callback=self._report_status,
            )
            self._report_status(result.message)
            if result.success:
                return
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._report_status(f"Streamlines profile switch failed: {error}")
        finally:
            if self._profile_task is asyncio.current_task():
                self._profile_task = None
        committed = (
            self._controller.streamlines_profile_preference_snapshot().committed_profile
        )
        if committed is not None:
            self._restore_profile_selection(committed)

    async def _apply_material_settings(
        self,
        *,
        opacity: float,
        emission_intensity: float,
        lighting_influence: float,
    ) -> None:
        presentation = None
        receipt = None
        try:
            presentation = self._controller.streamlines_presentation_contract(
                opacity=opacity,
                emission_intensity=emission_intensity,
                lighting_influence=lighting_influence,
            )
            receipt = await self._controller.apply_streamlines_material_settings_in_kit(
                presentation,
                status_callback=self._report_status,
            )
            local_path = self._controller.save_streamlines_material_settings(
                presentation
            )
            message = (
                "Material settings applied and saved locally: bound=True; "
                "cache_build=0; cache_rebuild=0; "
                f"signature={receipt.material.presentation_signature[:12]}; "
                f"config={local_path.name}."
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            message = f"Material settings apply failed: {error}"
            self._log_error(message)
        finally:
            if self._material_apply_task is asyncio.current_task():
                self._material_apply_task = None
        self._report_material_status(message)
