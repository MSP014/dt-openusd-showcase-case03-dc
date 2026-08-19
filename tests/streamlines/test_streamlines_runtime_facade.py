"""Focused public-facade contracts for Streamlines UI ownership."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

from digital_twin_runtime_suite.app.commands import RuntimeController
from digital_twin_runtime_suite.app.flow.static_source import (
    StaticVelocitySourceDescriptor,
)
from digital_twin_runtime_suite.app.streamlines.operator_runtime import (
    StreamlinesOperatorExecutionReceipt,
)
from digital_twin_runtime_suite.app.streamlines.proof import (
    STREAMLINES_RUNTIME_PREVIEW_PATH,
    STREAMLINES_SEED_ROOT,
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
        "inspect_streamlines_caches",
        "is_streamlines_production_cache_sanity_ready",
        "preview_streamlines_production_profile_in_kit",
        "run_streamlines_profile_preview",
        "set_streamlines_profile_preference",
        "streamlines_profile_preference_snapshot",
        "accept_current_streamlines_profile_candidate",
        "accept_streamlines_production_profile",
        "build_validate_production_cache_set_in_kit",
        "select_streamlines_cache_state_in_kit",
        "start_streamlines_cached_playback_in_kit",
        "stop_streamlines_cached_playback_in_kit",
        "run_streamlines_production_cache_sanity_in_kit",
        "run_streamlines_cadence_characterization_in_kit",
        "run_streamlines_fast_cadence_check_in_kit",
        "run_streamlines_200ms_wrap_recheck_in_kit",
        "run_streamlines_recompute_fallback_in_kit",
        "prepare_streamlines_snapshots_in_kit",
        "select_streamlines_snapshot_state_in_kit",
        "cleanup_streamlines_snapshots_in_kit",
        "announce_streamlines_snapshot_playback_acceptance_ready",
        "start_streamlines_snapshot_playback_acceptance",
        "confirm_streamlines_snapshot_playback_acceptance",
        "reject_streamlines_snapshot_playback_acceptance",
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


def test_recompute_fallback_keeps_preview_after_non_no_op_execution(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = _source(tmp_path)
    descriptor = source.static_descriptor
    stage = _PreviewStage(
        {descriptor.dataset_prim_path, descriptor.velocity_field_prim_path}
    )
    _install_kit_fallback_modules(monkeypatch, stage)
    fallback = _NonNoOpFallbackRuntime(source)

    result = asyncio.run(fallback.run_streamlines_recompute_fallback_in_kit(0.21))

    assert result.resolution.decision == "SELECT"
    assert result.runtime_preview_path == STREAMLINES_RUNTIME_PREVIEW_PATH
    assert result.cleanup_complete is True
    assert STREAMLINES_RUNTIME_PREVIEW_PATH in stage.paths
    assert STREAMLINES_SEED_ROOT not in stage.paths
    assert fallback.selected_sample_index == result.resolution.sample.sample_index


class _FallbackRuntime(StreamlinesRecomputeRuntimeMixin):
    def __init__(self, source: TemporalVelocitySourceDescriptor) -> None:
        self._flow_lifecycle_state = "DETACHED"
        self._streamlines_temporal_source_descriptor = source
        self._streamlines_recompute_active_sample_index = 1


class _PreviewPrim:
    def __init__(self, valid: bool) -> None:
        self._valid = valid

    def IsValid(self) -> bool:
        return self._valid


class _PreviewStage:
    def __init__(self, paths: set[str]) -> None:
        self.paths = set(paths)
        self._session_layer = object()
        self._root_layer = object()
        self._edit_target = self._session_layer

    def GetPrimAtPath(self, path: str) -> _PreviewPrim:
        return _PreviewPrim(
            any(
                candidate == path or candidate.startswith(f"{path}/")
                for candidate in self.paths
            )
        )

    def GetEditTarget(self):
        return self._edit_target

    def SetEditTarget(self, target) -> None:
        self._edit_target = target

    def GetSessionLayer(self):
        return self._session_layer

    def GetRootLayer(self):
        return self._root_layer

    def RemovePrim(self, path: str) -> None:
        self.paths = {
            candidate
            for candidate in self.paths
            if candidate != path and not candidate.startswith(f"{path}/")
        }


class _NonNoOpFallbackRuntime(StreamlinesRecomputeRuntimeMixin):
    def __init__(self, source: TemporalVelocitySourceDescriptor) -> None:
        self._flow_lifecycle_state = "DETACHED"
        self._streamlines_temporal_source_descriptor = source
        self._streamlines_recompute_active_sample_index = None
        self.selected_sample_index: int | None = None

    def _start_kit_cae_operator_tracking(self) -> None:
        pass

    def _stop_kit_cae_operator_tracking(self) -> None:
        pass

    async def _select_temporal_source_in_kit(self, app, **kwargs) -> Path:
        sample = kwargs["sample"]
        self.selected_sample_index = sample.sample_index
        return sample.source_vti

    async def _run_fresh_streamlines_operator_in_kit(self, stage, **kwargs):
        stage.paths.add(kwargs["preview_path"])
        return SimpleNamespace(
            rebuild_ms=23.0,
            execution_receipt=StreamlinesOperatorExecutionReceipt(
                begin_count_before=1,
                begin_count_after=2,
                completion_count_before=1,
                completion_count_after=2,
                completion_begin_count=2,
                completion_success=True,
            ),
        )


def _install_kit_fallback_modules(monkeypatch, stage: _PreviewStage) -> None:
    carb = ModuleType("carb")
    carb.settings = SimpleNamespace(
        get_settings=lambda: SimpleNamespace(get_as_bool=lambda _key: False)
    )
    omni = _package("omni")
    kit = _package("omni.kit")
    app = ModuleType("omni.kit.app")
    app.get_app = lambda: SimpleNamespace(next_update_async=_next_update)
    commands = ModuleType("omni.kit.commands")
    commands.execute = _execute_stage_command(stage)
    usd = ModuleType("omni.usd")
    usd.get_context = lambda: SimpleNamespace(get_stage=lambda: stage)
    cae = _package("omni.cae")
    cae_data = _package("omni.cae.data")
    cae_commands = ModuleType("omni.cae.data.commands")
    cae_commands.execute_command = _execute_stage_command(stage)
    cae_usd_utils = ModuleType("omni.cae.data.usd_utils")
    cae_schema = _package("omni.cae.schema")
    cae_viz = ModuleType("omni.cae.schema.viz")
    cae_vtk = ModuleType("omni.cae.schema.vtk")
    pxr = _package("pxr")
    sdf = ModuleType("pxr.Sdf")
    usd_schema = ModuleType("pxr.Usd")
    usd_geom = ModuleType("pxr.UsdGeom")
    usdrt = ModuleType("usdrt")
    usdrt.UsdGeom = ModuleType("usdrt.UsdGeom")

    omni.kit = kit
    omni.usd = usd
    kit.app = app
    kit.commands = commands
    omni.cae = cae
    cae.data = cae_data
    cae.schema = cae_schema
    cae_data.commands = cae_commands
    cae_data.usd_utils = cae_usd_utils
    cae_schema.viz = cae_viz
    cae_schema.vtk = cae_vtk
    pxr.Sdf = sdf
    pxr.Usd = usd_schema
    pxr.UsdGeom = usd_geom

    for module in (
        carb,
        omni,
        kit,
        app,
        commands,
        usd,
        cae,
        cae_data,
        cae_commands,
        cae_usd_utils,
        cae_schema,
        cae_viz,
        cae_vtk,
        pxr,
        sdf,
        usd_schema,
        usd_geom,
        usdrt,
        usdrt.UsdGeom,
    ):
        monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setitem(sys.modules, "warp", ModuleType("warp"))


def _package(name: str) -> ModuleType:
    package = ModuleType(name)
    package.__path__ = []
    return package


async def _next_update() -> None:
    return None


def _execute_stage_command(stage: _PreviewStage):
    async def execute(command: str, **kwargs) -> None:
        if command == "CreateCaeVizMeshPrim":
            stage.paths.add(kwargs["prim_path"])

    return execute


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
        spacing=(0.1, 0.1, 0.1),
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
