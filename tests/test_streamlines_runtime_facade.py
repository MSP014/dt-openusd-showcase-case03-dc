"""Focused public-facade contracts for Streamlines UI ownership."""

from __future__ import annotations

import asyncio
from pathlib import Path

from digital_twin_runtime_suite.app.commands import RuntimeController
from digital_twin_runtime_suite.app.flow.static_source import (
    StaticVelocitySourceDescriptor,
)
from digital_twin_runtime_suite.app.streamlines.operator_runtime import (
    StreamlinesOperatorExecutionReceipt,
)
from digital_twin_runtime_suite.app.streamlines.recompute_runtime import (
    RECOMPUTE_PRESENTATION_PERIOD_SECONDS,
    StreamlinesRecomputeRuntimeMixin,
)
from digital_twin_runtime_suite.app.streamlines.runtime import (
    StreamlinesRuntimeMixin,
)
from digital_twin_runtime_suite.app.streamlines.temporal import (
    TemporalVelocitySourceDescriptor,
)


def test_runtime_controller_retains_ui_facing_streamlines_operations() -> None:
    assert issubclass(RuntimeController, StreamlinesRuntimeMixin)
    for operation in (
        "build_streamlines_cache_in_kit",
        "load_streamlines_cache_in_kit",
        "select_streamlines_cache_state_in_kit",
        "run_streamlines_recompute_fallback_in_kit",
        "clear_streamlines_static_runtime_in_kit",
    ):
        assert callable(getattr(RuntimeController, operation))


def test_recompute_fallback_returns_no_op_for_current_manifest_identity(
    tmp_path: Path,
) -> None:
    fallback = _FallbackRuntime(_source(tmp_path))

    result = asyncio.run(fallback.run_streamlines_recompute_fallback_in_kit(0.21))

    assert RECOMPUTE_PRESENTATION_PERIOD_SECONDS == 2.6
    assert result.resolution.decision == "NO_OP"
    assert result.rebuild_ms is None
    assert result.cleanup_complete is True


def test_operator_receipt_requires_paired_successful_execution() -> None:
    accepted = StreamlinesOperatorExecutionReceipt(
        begin_count_before=1,
        begin_count_after=2,
        completion_count_before=1,
        completion_count_after=2,
        completion_begin_count=2,
        completion_success=True,
    )
    stale = StreamlinesOperatorExecutionReceipt(
        begin_count_before=1,
        begin_count_after=2,
        completion_count_before=1,
        completion_count_after=1,
        completion_begin_count=None,
        completion_success=None,
    )

    assert accepted.accepted is True
    assert stale.accepted is False


class _FallbackRuntime(StreamlinesRecomputeRuntimeMixin):
    def __init__(self, source: TemporalVelocitySourceDescriptor) -> None:
        self._flow_lifecycle_state = "DETACHED"
        self._streamlines_temporal_source_descriptor = source
        self._streamlines_recompute_active_sample_index = 1


def _source(tmp_path: Path) -> TemporalVelocitySourceDescriptor:
    paths = tuple(tmp_path / f"velocity_{index:04d}.vti" for index in range(2))
    for index, path in enumerate(paths):
        path.write_bytes(f"vti-{index}".encode("utf-8"))
    descriptor = StaticVelocitySourceDescriptor(
        workload="Nominal",
        dataset_identity="server/load_normal",
        sample_index=0,
        vti_path=paths[0],
        dataset_prim_path="/DTRS_HoudiniVelocity/VTKImageData",
        velocity_field_prim_path="/DTRS_HoudiniVelocity/PointData/vel",
        world_bounds=((0.0, 0.0, 0.0), (1.0, 1.0, 1.0)),
        dimensions=(2, 2, 2),
        spacing=(1.0, 1.0, 1.0),
        origin=(0.0, 0.0, 0.0),
        source_origin=(0.0, 0.0, 0.0),
        stage_meters_per_unit=1.0,
    )
    return TemporalVelocitySourceDescriptor(
        static_descriptor=descriptor,
        velocity_paths=paths,
        sample_time_codes=(0.0, 12.0),
        time_codes_per_second=60.0,
        sample_interval_seconds=0.2,
    )
