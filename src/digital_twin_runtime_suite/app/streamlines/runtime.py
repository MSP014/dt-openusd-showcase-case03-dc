"""Thin public Streamlines runtime facade composed from focused owners."""

from __future__ import annotations

from typing import Callable

from digital_twin_runtime_suite.app.diagnostics import with_dtrs_yerevan_timestamp
from digital_twin_runtime_suite.app.flow.static_source import (
    StaticVelocitySourceDescriptor,
    clear_static_velocity_source_from_stage,
)
from digital_twin_runtime_suite.app.streamlines.cache_runtime import (
    StreamlinesCacheBuildResult,
    StreamlinesCacheRuntimeMixin,
)
from digital_twin_runtime_suite.app.streamlines.lifecycle import (
    STATIC_VELOCITY_SOURCE_ROOT,
    StreamlinesCleanupReceipt,
    inspect_streamlines_runtime_cleanup,
    remove_streamlines_runtime_roots_from_layers,
)
from digital_twin_runtime_suite.app.streamlines.operator_runtime import (
    StreamlinesOperatorExecutionReceipt,
    StreamlinesOperatorRuntimeMixin,
)
from digital_twin_runtime_suite.app.streamlines.proof import (
    clear_streamlines_operator_from_stage,
)
from digital_twin_runtime_suite.app.streamlines.recompute_runtime import (
    StreamlinesRecomputeRuntimeMixin,
)
from digital_twin_runtime_suite.app.streamlines.source_runtime import (
    StreamlinesSourceRuntimeMixin,
)

StatusCallback = Callable[[str], None]
ErrorLogger = Callable[[str], None]

__all__ = (
    "StreamlinesCacheBuildResult",
    "StreamlinesOperatorExecutionReceipt",
    "StreamlinesRuntimeMixin",
    "report_streamlines_task_failure",
)


def _emit_streamlines_task_error(error_logger: ErrorLogger, message: str) -> None:
    """Contain a secondary logging failure at the UI-task error boundary."""

    try:
        error_logger(message)
    except Exception:
        return


def _set_streamlines_task_error_status(
    status_callback: StatusCallback,
    message: str,
) -> None:
    """Contain a secondary status-label failure at the UI-task boundary."""

    try:
        status_callback(message)
    except Exception:
        return


def report_streamlines_task_failure(
    error: Exception,
    *,
    area: str,
    display_name: str,
    status_callback: StatusCallback,
    error_logger: ErrorLogger,
) -> None:
    """Turn an unexpected detached UI-task failure into a retryable DTRS event."""

    reason = " ".join(str(error).splitlines()) or type(error).__name__
    message = f"{display_name} failed: {reason}"
    _emit_streamlines_task_error(
        error_logger,
        with_dtrs_yerevan_timestamp(
            f"DTRS STREAMLINES | {area} | FAIL | "
            "boundary=UI_TASK | "
            f"error_type={type(error).__name__} | reason={reason}"
        ),
    )
    _set_streamlines_task_error_status(status_callback, message)


class StreamlinesRuntimeMixin(
    StreamlinesCacheRuntimeMixin,
    StreamlinesRecomputeRuntimeMixin,
    StreamlinesSourceRuntimeMixin,
    StreamlinesOperatorRuntimeMixin,
):
    """Public facade used by ``RuntimeController`` and OmniUI."""

    STATIC_IMPORT_ROOT = STATIC_VELOCITY_SOURCE_ROOT
    STATIC_DATASET_PATH = f"{STATIC_IMPORT_ROOT}/VTKImageData"
    STREAMLINES_OPERATOR_TIMEOUT_SECONDS = 15.0

    def streamlines_static_source_descriptor(
        self,
    ) -> StaticVelocitySourceDescriptor | None:
        """Return the current validated static source without mutating Kit."""

        return self._streamlines_static_source_descriptor

    def streamlines_static_source_diagnostics_failure(self) -> str | None:
        """Return a non-fatal diagnostic formatter or logger failure, if any."""

        return self._streamlines_static_source_diagnostics_failure

    def clear_streamlines_static_runtime_from_open_stage(
        self,
    ) -> StreamlinesCleanupReceipt:
        """Remove all DTRS-owned Streamlines artifacts from the open stage."""

        self._stop_kit_cae_operator_tracking()
        self._streamlines_static_source_descriptor = None
        self._streamlines_static_source_diagnostics_failure = None
        self._streamlines_temporal_source_descriptor = None
        self._streamlines_loaded_cache_metadata = None
        self._streamlines_cache_active_sample_index = None
        self._streamlines_recompute_active_sample_index = None
        pending_tasks = self._streamlines_pending_runtime_task_count()
        try:
            import omni.usd
        except ImportError:
            return self._empty_static_cleanup_receipt(pending_tasks)

        stage = omni.usd.get_context().get_stage()
        if not stage:
            return self._empty_static_cleanup_receipt(pending_tasks)
        self._detach_streamlines_cache_playback_layer(stage)
        clear_static_velocity_source_from_stage(stage, self.STATIC_IMPORT_ROOT)
        clear_streamlines_operator_from_stage(stage)
        remove_streamlines_runtime_roots_from_layers(stage)
        return inspect_streamlines_runtime_cleanup(stage, pending_tasks=pending_tasks)

    async def clear_streamlines_static_runtime_in_kit(
        self,
    ) -> StreamlinesCleanupReceipt:
        """Clear Streamlines and wait one Kit update before checking cleanliness."""

        receipt = self.clear_streamlines_static_runtime_from_open_stage()
        try:
            import omni.kit.app
            import omni.usd
        except ImportError:
            return receipt
        await omni.kit.app.get_app().next_update_async()
        stage = omni.usd.get_context().get_stage()
        if not stage:
            return receipt
        return inspect_streamlines_runtime_cleanup(
            stage,
            pending_tasks=self._streamlines_pending_runtime_task_count(),
        )

    def reset_streamlines_runtime_state(self) -> None:
        """Reset transient Streamlines ownership on startup or config reload."""

        self._streamlines_static_source_descriptor = None
        self._streamlines_static_source_diagnostics_failure = None
        self._streamlines_temporal_source_descriptor = None
        self._streamlines_cache_build_active_sample_index = None
        self._streamlines_loaded_cache_metadata = None
        self._streamlines_cache_active_sample_index = None
        self._streamlines_recompute_active_sample_index = None

    def _streamlines_pending_runtime_task_count(self) -> int:
        """Count DTRS-owned CAE subscriptions and active operators after teardown."""

        return len(self._flow_kit_cae_operator_subscriptions) + len(
            self._flow_kit_cae_active_operator_paths
        )

    @staticmethod
    def _empty_static_cleanup_receipt(
        pending_tasks: int,
    ) -> StreamlinesCleanupReceipt:
        """Treat a no-stage shutdown as clean after observer ownership is released."""

        return StreamlinesCleanupReceipt(
            source_present=False,
            operator_present=False,
            seed_present=False,
            runtime_preview_present=False,
            stale_relationships=0,
            remaining_layer_specs=0,
            duplicate_prims=0,
            pending_tasks=pending_tasks,
        )

    @staticmethod
    def _streamlines_carb_logger():
        """Return Kit logging without making logger availability a requirement."""

        try:
            import carb
        except ImportError:
            return None
        return carb
