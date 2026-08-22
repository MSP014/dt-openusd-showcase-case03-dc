"""Task ownership for Streamlines cache maintenance actions."""

from __future__ import annotations

import asyncio

import carb


def _with_dtrs_local_timestamp(message: str) -> str:
    """Use the shared formatter after the extension source root is available."""

    from digital_twin_runtime_suite.app.diagnostics import (
        with_dtrs_local_timestamp,
    )

    return with_dtrs_local_timestamp(message)


class StreamlinesCacheWorkflowMixin:
    """Own cancellable cache-build tasks without changing cache semantics."""

    def _schedule_build_validate_production_cache_set(self) -> None:
        """Build only non-valid production targets in one cancellable task."""

        if self._airflow_task and not self._airflow_task.done():
            self._set_streamlines_status("Airflow operation is already in progress.")
            return
        self._set_streamlines_cache_buttons_enabled(False)
        self._airflow_task = asyncio.ensure_future(
            self._build_validate_production_cache_set()
        )

    async def _build_validate_production_cache_set(self) -> None:
        """Run the sole production cache-set builder behind the UI boundary."""

        try:
            build_cache_set = (
                self._controller.build_validate_production_cache_set_in_kit
            )
            result = await build_cache_set(
                status_callback=self._set_streamlines_status,
            )
            if not result.success:
                raise RuntimeError(result.message)
            if any(not entry.reused for entry in getattr(result, "results", ())):
                invalidate_receipts = getattr(
                    self._validation_workflow,
                    "invalidate_streamlines_receipts_after_cache_rebuild",
                )
                invalidate_receipts()
            ready_entries = (
                self._controller.streamlines_production_speed_readiness_snapshot()
            )
            proposal = await self._controller.collect_streamlines_speed_scale_proposal(
                status_callback=self._set_streamlines_status,
                ready_entries=ready_entries,
            )
            message = (
                f"{result.message} Shared speed scale saved locally: "
                f"{proposal.scale.minimum:.6g}..{proposal.scale.maximum:.6g} "
                f"{proposal.scale.units}."
            )
            self._set_streamlines_status(message)
            self._set_streamlines_material_status(message)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            message = f"Production Streamlines cache-set build failed: {error}"
            self._set_streamlines_status(message)
            self._set_streamlines_material_status(message)
            carb.log_error(_with_dtrs_local_timestamp(message))
        finally:
            self._set_streamlines_cache_buttons_enabled(True)

    def _schedule_build_constant_topology_prototype(self) -> None:
        """Launch only the Volume Coverage / Nominal prototype build."""

        if self._airflow_task and not self._airflow_task.done():
            self._set_streamlines_status("Airflow operation is already in progress.")
            return
        self._set_streamlines_cache_buttons_enabled(False)
        self._airflow_task = asyncio.ensure_future(
            self._build_constant_topology_prototype()
        )

    async def _build_constant_topology_prototype(self) -> None:
        """Contain one prototype build without touching the other seven caches."""

        try:
            build_prototype = getattr(
                self._controller,
                "build_validate_constant_topology_prototype_in_kit",
            )
            result = await build_prototype(
                status_callback=self._set_streamlines_status,
            )
            if not result.success:
                raise RuntimeError(result.message)
            message = result.message
            self._set_streamlines_status(message)
            if self._streamlines_material_status_label is not None:
                self._streamlines_material_status_label.text = message
            self._update_visualization_controls()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            message = f"Constant-topology prototype build failed: {error}"
            self._set_streamlines_status(message)
            carb.log_error(_with_dtrs_local_timestamp(message))
        finally:
            self._set_streamlines_cache_buttons_enabled(True)

    def _schedule_build_streamlines_cache(self) -> None:
        """Build a persistent cache while no other airflow operation is active."""

        if self._airflow_task and not self._airflow_task.done():
            self._set_streamlines_status("Airflow operation is already in progress.")
            return
        self._set_streamlines_cache_buttons_enabled(False)
        self._airflow_task = asyncio.ensure_future(self._build_streamlines_cache())

    async def _build_streamlines_cache(self) -> None:
        """Contain production cache-build failures at the OmniUI task boundary."""

        try:
            result = await self._controller.build_streamlines_cache_in_kit(
                status_callback=self._set_streamlines_status,
            )
            self._set_streamlines_status(result.message)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            import carb

            from digital_twin_runtime_suite.app.streamlines.runtime import (
                report_streamlines_task_failure,
            )

            report_streamlines_task_failure(
                error,
                area="CACHE_BUILD",
                display_name="Streamlines cache build",
                status_callback=self._set_streamlines_status,
                error_logger=carb.log_error,
            )
        finally:
            self._set_streamlines_cache_buttons_enabled(True)
