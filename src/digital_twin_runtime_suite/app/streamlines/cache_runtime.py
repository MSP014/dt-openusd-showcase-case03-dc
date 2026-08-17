"""Kit-facing persistent cache build, validation, attachment, and state selection."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, replace
from pathlib import Path
from statistics import median
from typing import Callable

from digital_twin_runtime_suite.app.diagnostics import with_dtrs_yerevan_timestamp
from digital_twin_runtime_suite.app.flow.static_source import (
    StaticVelocitySourceDescriptor,
    resolve_static_velocity_sample_from_airflow_dataset,
)
from digital_twin_runtime_suite.app.streamlines.cache import (
    CACHE_BUILD_OPERATOR_PATH,
    CACHE_BUILD_SEED_PATH,
    CACHE_PLAYBACK_CURVES_PATH,
    CACHE_PLAYBACK_ROOT_PATH,
    CACHE_SCHEMA_VERSION,
    StreamlinesCacheMetadata,
    StreamlinesCacheOwnership,
    StreamlinesCachePaths,
    StreamlinesCacheSettings,
    StreamlinesCacheState,
    StreamlinesCacheValidation,
    build_streamlines_cache_metadata,
    cache_settings_differences,
    discard_streamlines_cache_staging,
    file_sha256,
)
from digital_twin_runtime_suite.app.streamlines.cache import (
    geometry_signature as cache_geometry_signature,
)
from digital_twin_runtime_suite.app.streamlines.cache import (
    load_streamlines_cache_metadata,
    replace_streamlines_cache_artifacts,
    serialise_streamlines_cache_metadata,
    streamlines_cache_build_mode,
    streamlines_cache_paths,
    streamlines_cache_settings,
    streamlines_settings_signature,
)
from digital_twin_runtime_suite.app.streamlines.cache import (
    topology_signature as cache_topology_signature,
)
from digital_twin_runtime_suite.app.streamlines.cache import (
    validate_streamlines_cache,
    vti_file_identity,
)
from digital_twin_runtime_suite.app.streamlines.cache_discovery import (
    StreamlinesCacheInspection,
    inspect_streamlines_cache,
)
from digital_twin_runtime_suite.app.streamlines.lifecycle import (
    StreamlinesCleanupReceipt,
)
from digital_twin_runtime_suite.app.streamlines.playback import (
    cached_playback_contract_from_validated_cache,
)
from digital_twin_runtime_suite.app.streamlines.proof import (
    StreamlinesOperatorRequest,
    build_streamlines_operator_request,
    clear_streamlines_seed_from_stage,
)
from digital_twin_runtime_suite.app.streamlines.speed import (
    SPEED_PRIMVAR_ATTRIBUTE,
    SPEED_PRIMVAR_NAME,
    validate_persisted_speed_magnitudes,
)
from digital_twin_runtime_suite.app.streamlines.temporal import (
    TemporalVelocitySourceDescriptor,
    manifest_samples,
    temporal_source_from_airflow_dataset,
)

StatusCallback = Callable[[str], None]


def _validate_persisted_speed_primvar(
    attribute,
    *,
    expected_time_codes: tuple[float, ...],
    expected_point_counts: tuple[int, ...],
    Usd,
) -> None:
    """Require raw vertex speed samples aligned to every persisted geometry state."""

    if attribute is None or not attribute.IsValid():
        raise RuntimeError("Cache is missing its raw vertex speed primvar.")
    actual_time_codes = tuple(float(value) for value in attribute.GetTimeSamples())
    if actual_time_codes != expected_time_codes:
        raise RuntimeError(
            "Cache raw speed time samples do not match persisted geometry."
        )
    for time_code, point_count in zip(expected_time_codes, expected_point_counts):
        values = attribute.Get(Usd.TimeCode(time_code))
        try:
            validate_persisted_speed_magnitudes(
                () if values is None else values,
                expected_point_count=point_count,
            )
        except ValueError as error:
            raise RuntimeError(
                f"Cache raw speed primvar is invalid: {error}"
            ) from error


def _author_persisted_speed_sample(
    primvar,
    values,
    *,
    expected_point_count: int,
    time_code,
) -> tuple[float, ...]:
    """Author one vertex-interpolated raw-speed sample after validating it."""

    speeds = validate_persisted_speed_magnitudes(
        values,
        expected_point_count=expected_point_count,
    )
    primvar.Set(list(speeds), time_code)
    return speeds


@dataclass(frozen=True)
class StreamlinesCacheBuildResult:
    """Outcome of one complete derived-cache build."""

    success: bool
    message: str
    metadata: StreamlinesCacheMetadata | None = None


@dataclass(frozen=True)
class StreamlinesCacheLoadResult:
    """Outcome of attaching one validated persisted cache state."""

    metadata: StreamlinesCacheMetadata
    active_sample_index: int
    load_ms: float


@dataclass(frozen=True)
class StreamlinesProductionCacheResult:
    """Validated or newly built cache evidence for one authoritative workload."""

    workload: str
    dataset_identity: str
    reused: bool
    metadata: StreamlinesCacheMetadata
    cache_size_bytes: int
    total_ms: float


@dataclass(frozen=True)
class StreamlinesProductionCacheSetResult:
    """All-or-stop result for one frozen-profile four-workload cache operation."""

    success: bool
    results: tuple[StreamlinesProductionCacheResult, ...]
    failed_workload: str | None = None
    message: str = ""


@dataclass(frozen=True)
class StreamlinesProfilePreviewResult:
    """Representative standard-operator evidence before profile freeze."""

    workload: str
    dataset_identity: str
    curve_count: int
    point_count: int
    generation_ms: float


class StreamlinesCacheRuntimeMixin:
    """Own Kit cache materialisation; never own acceptance benchmarking."""

    def announce_streamlines_cache_build_ready(self) -> str:
        """Publish cache-build readiness without touching an existing artifact."""

        action = "Build Streamlines Cache"
        ready_header = "DTRS STREAMLINES | CACHE_BUILD | READY"
        message = f'{ready_header}\nNEXT_ACTION | Press "{action}"'
        carb = self._streamlines_carb_logger()
        if carb:
            carb.log_warn(with_dtrs_yerevan_timestamp(message))
        return f'Ready — Press "{action}".'

    def announce_streamlines_cache_load_ready(self) -> str:
        """Publish cache-load readiness without measuring presentation cadence."""

        action = "Load Streamlines Cache"
        message = (
            "DTRS STREAMLINES | CACHE_LOAD | READY\n" f'NEXT_ACTION | Press "{action}"'
        )
        carb = self._streamlines_carb_logger()
        if carb:
            carb.log_warn(with_dtrs_yerevan_timestamp(message))
        return f'Ready — Press "{action}".'

    def inspect_existing_streamlines_cache(self) -> StreamlinesCacheValidation:
        """Inspect persisted cache provenance without creating a Kit operator."""

        binding, airflow_dataset = self.resolve_current_airflow_dataset()
        inspection = self._inspect_streamlines_cache_for_target(
            binding,
            airflow_dataset,
        )
        return StreamlinesCacheValidation(inspection.valid, inspection.message)

    def inspect_streamlines_caches(self) -> tuple[StreamlinesCacheInspection, ...]:
        """Classify every configured cache through the shared dataset registry.

        This is deliberately read-only: it resolves authoritative datasets and
        cache receipts but never imports a VTI, creates a Kit operator, or
        rebuilds a missing artifact.
        """

        return tuple(
            self._inspect_streamlines_cache_for_target(target.binding, target.dataset)
            for target in self.resolve_configured_airflow_targets()
        )

    def is_streamlines_production_cache_sanity_ready(self) -> bool:
        """Return whether all expected persisted production caches are ready.

        Read-only discovery is the restart-safe readiness source for the Phase
        3.5 sanity action. It deliberately does not author geometry, import a
        VTI, or rebuild a cache merely to enable the action.
        """

        if not self.is_streamlines_cache_load_allowed():
            return False
        try:
            inspections = self.inspect_streamlines_caches()
        except Exception:
            return False
        return len(inspections) == 4 and all(
            inspection.valid for inspection in inspections
        )

    def _inspect_streamlines_cache_for_target(
        self,
        binding,
        airflow_dataset,
    ) -> StreamlinesCacheInspection:
        """Classify one resolved target without introducing a second registry."""

        ownership = self._streamlines_cache_ownership(binding)
        paths = streamlines_cache_paths(self.config.repo_root, ownership)
        try:
            preliminary = inspect_streamlines_cache(paths, ownership)
        except ValueError:
            preliminary = None
        if preliminary is not None:
            return preliminary
        try:
            metadata = load_streamlines_cache_metadata(paths.metadata_path)
            expected = self._streamlines_cache_expected_contract(
                binding=binding,
                airflow_dataset=airflow_dataset,
                stage_time_codes_per_second=metadata.time_codes_per_second,
            )
        except Exception as error:
            return StreamlinesCacheInspection(
                ownership=ownership,
                paths=paths,
                classification="INCOMPATIBLE",
                message=f"Expected cache contract is unavailable: {error}",
            )
        return inspect_streamlines_cache(
            paths,
            ownership,
            source=expected["source"],
            settings_signature=expected["settings_signature"],
        )

    @staticmethod
    def _streamlines_cache_ownership(binding) -> StreamlinesCacheOwnership:
        """Derive persisted-cache ownership only from the resolved binding."""

        return StreamlinesCacheOwnership(
            workload=binding.workload_mode,
            dataset_identity=binding.dataset_identity,
        )

    @property
    def streamlines_production_profile(self):
        """Return the one session profile used for every production cache."""

        return self._streamlines_profile_state.profile

    def is_streamlines_production_profile_frozen(self) -> bool:
        """Return whether cache promotion is authorised for this session."""

        return self._streamlines_profile_state.frozen

    def mark_streamlines_production_profile_previewed(self) -> None:
        """Record successful representative previews before manual acceptance."""

        self._streamlines_profile_state = (
            self._streamlines_profile_state.mark_previewed()
        )

    def accept_streamlines_production_profile(self):
        """Freeze the previewed geometry contract before any production build."""

        self._streamlines_profile_state = self._streamlines_profile_state.freeze()
        return self._streamlines_profile_state.profile

    async def preview_streamlines_production_profile_in_kit(
        self,
        status_callback: StatusCallback | None = None,
    ) -> tuple[StreamlinesProfilePreviewResult, ...]:
        """Run bounded Idle/Critical previews without writing a cache artifact."""

        if self._flow_lifecycle_state != "DETACHED":
            raise RuntimeError("Production profile preview requires Flow DETACHED.")
        targets = {
            target.binding.workload_mode: target
            for target in self.resolve_configured_airflow_targets()
        }
        required = ("Idle", "Critical")
        if any(workload not in targets for workload in required):
            raise RuntimeError(
                "Production profile preview requires Idle and Critical datasets."
            )
        results = []
        for workload in required:
            target = targets[workload]
            self._report_streamlines_profile(
                event="PROGRESS",
                message=(f"Preparing representative {workload} profile preview."),
                status_callback=status_callback,
            )
            results.append(
                await self._preview_streamlines_profile_target_in_kit(
                    binding=target.binding,
                    airflow_dataset=target.dataset,
                )
            )
        self.mark_streamlines_production_profile_previewed()
        period = self.config.simulation_cache.streamlines_presentation_period_seconds
        self._report_streamlines_profile(
            event="PROGRESS",
            message=(
                "Profile preview cost sanity: cached playback remains configured "
                f"at period_ms={float(period or 0.0) * 1000.0:.0f}; "
                "no persistent cache was built."
            ),
            status_callback=status_callback,
        )
        return tuple(results)

    async def _preview_streamlines_profile_target_in_kit(
        self,
        *,
        binding,
        airflow_dataset,
    ) -> StreamlinesProfilePreviewResult:
        """Show one exact source sample through the profile without persistence."""

        import omni.kit.app
        import omni.timeline
        import omni.usd
        import warp as wp
        from omni.cae.data import usd_utils as cae_usd_utils
        from omni.cae.data.commands import execute_command
        from omni.cae.schema import viz as cae_viz
        from omni.cae.schema import vtk as cae_vtk
        from pxr import Sdf, Usd, UsdGeom
        from usdrt import UsdGeom as UsdGeomRT

        cleanup = await self.clear_streamlines_static_runtime_in_kit()
        if not cleanup.clean:
            raise RuntimeError("Profile preview cleanup was not clean.")
        source = await self.prepare_streamlines_temporal_velocity_source_in_kit(
            binding=binding,
            airflow_dataset=airflow_dataset,
        )
        stage = omni.usd.get_context().get_stage()
        if not stage:
            raise RuntimeError("Production profile preview requires an open stage.")
        descriptor = source.static_descriptor
        dataset_prim = stage.GetPrimAtPath(descriptor.dataset_prim_path)
        field_prim = stage.GetPrimAtPath(descriptor.velocity_field_prim_path)
        if not dataset_prim or not dataset_prim.IsValid():
            raise RuntimeError("Production profile preview dataset is unavailable.")
        if not field_prim or not field_prim.IsValid():
            raise RuntimeError(
                "Production profile preview velocity field is unavailable."
            )
        request = self._build_streamlines_cache_request(descriptor)
        app = omni.kit.app.get_app()
        previous_target = stage.GetEditTarget()
        try:
            stage.SetEditTarget(stage.GetSessionLayer())
            await execute_command(
                "CreateCaeVizMeshPrim",
                prim_type="UnitSphere",
                prim_path=request.seed_path,
                resolution=request.seed_resolution,
            )
            await execute_command(
                "TransformPrimSRT",
                path=request.seed_path,
                new_translation=list(request.seed_center),
                new_scale=[request.seed_radius] * 3,
            )
            await app.next_update_async()
            sample = manifest_samples(source)[0]
            selected_asset = await self._select_temporal_source_in_kit(
                app,
                timeline=omni.timeline.get_timeline_interface(),
                field_prim=field_prim,
                sample=sample,
                cae_vtk=cae_vtk,
                Usd=Usd,
            )
            if selected_asset.resolve() != sample.source_vti.resolve():
                raise RuntimeError("Profile preview selected a non-manifest VTI.")
            self._start_kit_cae_operator_tracking()
            execution = await self._run_fresh_streamlines_operator_in_kit(
                stage,
                app=app,
                request=request,
                descriptor=descriptor,
                dataset_prim=dataset_prim,
                field_prim=field_prim,
                cae_usd_utils=cae_usd_utils,
                cae_viz=cae_viz,
                cae_vtk=cae_vtk,
                UsdGeom=UsdGeom,
                UsdGeomRT=UsdGeomRT,
                wp=wp,
                timeline=omni.timeline.get_timeline_interface(),
                execute_command=execute_command,
                preview_path="/DTRS_KitCAE/Streamlines/ProductionProfilePreview",
                Sdf=Sdf,
            )
        finally:
            self._stop_kit_cae_operator_tracking()
            stage.SetEditTarget(previous_target)
            if not clear_streamlines_seed_from_stage(stage):
                raise RuntimeError(
                    "Production profile preview did not remove its seed."
                )
        return StreamlinesProfilePreviewResult(
            workload=binding.workload_mode,
            dataset_identity=binding.dataset_identity,
            curve_count=execution.evidence.runtime_curve_count,
            point_count=execution.evidence.runtime_point_count,
            generation_ms=execution.rebuild_ms,
        )

    async def build_streamlines_cache_in_kit(
        self,
        status_callback: StatusCallback | None = None,
        *,
        binding=None,
        airflow_dataset=None,
        emit_next_action: bool = True,
    ) -> StreamlinesCacheBuildResult:
        """Build one complete workload-owned cache from real Kit-CAE/UsdRT results.

        The VTI sequence remains authoritative only while this bounded build
        runs. The USDC result is a derived view cache; explicit recompute
        fallback behaviour remains separate from this cache owner.
        """

        if self._flow_lifecycle_state != "DETACHED":
            return StreamlinesCacheBuildResult(
                False,
                "Cache build is unavailable while airflow Attach is active.",
            )
        if not self.is_streamlines_production_profile_frozen():
            return StreamlinesCacheBuildResult(
                False,
                "Accept Production Streamlines Profile before building a cache.",
            )

        started_at = time.monotonic()
        carb = self._streamlines_carb_logger()
        cleanup = None
        if binding is None or airflow_dataset is None:
            binding, airflow_dataset = self.resolve_current_airflow_dataset()
        cache_paths = streamlines_cache_paths(
            self.config.repo_root,
            self._streamlines_cache_ownership(binding),
        )
        build_mode = streamlines_cache_build_mode(cache_paths)
        self._streamlines_cache_build_active_sample_index = None
        try:
            self._report_streamlines_cache_build(
                event="START",
                message=f"Cache build started: mode={build_mode}.",
                status_callback=status_callback,
            )
            self._report_streamlines_cache_build(
                event="PROGRESS",
                message="Cache build: preparing manifest temporal source.",
                status_callback=status_callback,
            )
            cleanup = await self.clear_streamlines_static_runtime_in_kit()
            if not cleanup.clean:
                raise RuntimeError(
                    "Streamlines cleanup was not clean before cache build."
                )
            source = await self.prepare_streamlines_temporal_velocity_source_in_kit(
                status_callback=status_callback,
                binding=binding,
                airflow_dataset=airflow_dataset,
            )
            metadata, generation_ms = await self._build_cache_geometry_in_kit(
                source,
                cache_paths=cache_paths,
                status_callback=status_callback,
            )
            cleanup = await self.clear_streamlines_static_runtime_in_kit()
            if not cleanup.clean:
                raise RuntimeError(
                    "Streamlines cleanup was not clean after cache build."
                )
            replace_streamlines_cache_artifacts(cache_paths)
            if carb:
                carb.log_warn(
                    with_dtrs_yerevan_timestamp(
                        "DTRS STREAMLINES | CACHE_REPLACEMENT | PASS"
                    )
                )
        except asyncio.CancelledError:
            discard_streamlines_cache_staging(cache_paths)
            raise
        except Exception as error:
            discard_streamlines_cache_staging(cache_paths)
            cleanup = await self.clear_streamlines_static_runtime_in_kit()
            message = self._format_cache_build_failure(
                error=error,
                failed_sample_index=self._streamlines_cache_build_active_sample_index,
                cleanup=cleanup,
                total_ms=(time.monotonic() - started_at) * 1000.0,
            )
            if carb:
                carb.log_error(with_dtrs_yerevan_timestamp(message))
            self._report_streamlines_cache_build(
                event="FAIL",
                message="Cache build failed; inspect the detailed failure log.",
                status_callback=status_callback,
            )
            return StreamlinesCacheBuildResult(False, message)

        message = self._format_cache_build_success(
            metadata=metadata,
            cache_paths=cache_paths,
            generation_ms=generation_ms,
            total_ms=(time.monotonic() - started_at) * 1000.0,
        )
        if carb:
            carb.log_warn(with_dtrs_yerevan_timestamp(message))
        self._report_streamlines_cache_build(
            event="COMPLETE",
            message="Cache build complete and atomically persisted.",
            status_callback=status_callback,
        )
        if emit_next_action:
            self._report_streamlines_cache_build(
                event="NEXT_ACTION",
                message='Press "Load Streamlines Cache".',
                status_callback=status_callback,
            )
        self._streamlines_cache_build_active_sample_index = None
        return StreamlinesCacheBuildResult(True, message, metadata)

    async def build_validate_production_cache_set_in_kit(
        self,
        status_callback: StatusCallback | None = None,
    ) -> StreamlinesProductionCacheSetResult:
        """Build only missing/stale workloads after the profile is frozen.

        Every target is independently resolved through the shared dataset
        registry. A failure stops the sequence before any later workload is
        touched, so no unrelated valid cache is rebuilt as collateral work.
        """

        if not self.is_streamlines_production_profile_frozen():
            raise RuntimeError(
                "Accept Production Streamlines Profile before building the cache set."
            )
        if self._flow_lifecycle_state != "DETACHED":
            raise RuntimeError(
                "Production Streamlines cache build requires Flow DETACHED."
            )

        results: list[StreamlinesProductionCacheResult] = []
        for target in self.resolve_configured_airflow_targets():
            binding = target.binding
            dataset = target.dataset
            started_at = time.monotonic()
            inspection = self._inspect_streamlines_cache_for_target(binding, dataset)
            if inspection.valid and inspection.metadata is not None:
                metadata = inspection.metadata
                reused = True
            else:
                result = await self.build_streamlines_cache_in_kit(
                    status_callback=status_callback,
                    binding=binding,
                    airflow_dataset=dataset,
                    emit_next_action=False,
                )
                if not result.success or result.metadata is None:
                    return StreamlinesProductionCacheSetResult(
                        success=False,
                        results=tuple(results),
                        failed_workload=binding.workload_mode,
                        message=result.message,
                    )
                inspection = self._inspect_streamlines_cache_for_target(
                    binding,
                    dataset,
                )
                if not inspection.valid or inspection.metadata is None:
                    return StreamlinesProductionCacheSetResult(
                        success=False,
                        results=tuple(results),
                        failed_workload=binding.workload_mode,
                        message=(
                            "Built Streamlines cache did not pass final validation: "
                            f"{inspection.message}"
                        ),
                    )
                metadata = inspection.metadata
                reused = False
            paths = streamlines_cache_paths(
                self.config.repo_root,
                self._streamlines_cache_ownership(binding),
            )
            results.append(
                StreamlinesProductionCacheResult(
                    workload=binding.workload_mode,
                    dataset_identity=binding.dataset_identity,
                    reused=reused,
                    metadata=metadata,
                    cache_size_bytes=(
                        paths.geometry_path.stat().st_size
                        + paths.metadata_path.stat().st_size
                    ),
                    total_ms=(time.monotonic() - started_at) * 1000.0,
                )
            )
        return StreamlinesProductionCacheSetResult(
            success=True,
            results=tuple(results),
            message="All configured production Streamlines caches are VALID.",
        )

    async def _build_cache_geometry_in_kit(
        self,
        source: TemporalVelocitySourceDescriptor,
        *,
        cache_paths: StreamlinesCachePaths,
        status_callback: StatusCallback | None,
    ) -> tuple[StreamlinesCacheMetadata, tuple[float, ...]]:
        """Persist every real manifest sample without creating a RuntimePreview."""

        import omni.kit.app
        import omni.timeline
        import omni.usd
        import warp as wp
        from omni.cae.data import usd_utils as cae_usd_utils
        from omni.cae.data.commands import execute_command
        from omni.cae.schema import viz as cae_viz
        from omni.cae.schema import vtk as cae_vtk
        from pxr import Sdf, Usd, UsdGeom
        from usdrt import UsdGeom as UsdGeomRT

        app = omni.kit.app.get_app()
        stage = omni.usd.get_context().get_stage()
        if not stage:
            raise RuntimeError("Cache build requires an open stage.")
        descriptor = source.static_descriptor
        dataset_prim = stage.GetPrimAtPath(descriptor.dataset_prim_path)
        field_prim = stage.GetPrimAtPath(descriptor.velocity_field_prim_path)
        if not dataset_prim or not dataset_prim.IsValid():
            raise RuntimeError("Cache build dataset prim is unavailable.")
        if not field_prim or not field_prim.IsValid():
            raise RuntimeError("Cache build velocity field is unavailable.")

        request = self._build_streamlines_cache_request(descriptor)
        cache_paths.directory.mkdir(parents=True, exist_ok=True)
        for partial_path in (
            cache_paths.partial_geometry_path,
            cache_paths.partial_metadata_path,
        ):
            partial_path.unlink(missing_ok=True)
        cache_stage = Usd.Stage.CreateNew(cache_paths.partial_geometry_path.as_posix())
        cache_stage.SetTimeCodesPerSecond(source.time_codes_per_second)
        cache_stage.SetStartTimeCode(source.sample_time_codes[0])
        cache_stage.SetEndTimeCode(source.sample_time_codes[-1])
        cache_root = UsdGeom.Xform.Define(cache_stage, CACHE_PLAYBACK_ROOT_PATH)
        cache_root.GetPrim().SetCustomDataByKey(
            "dtrs:streamlinesCacheSchema",
            CACHE_SCHEMA_VERSION,
        )
        cache_curves = UsdGeom.BasisCurves.Define(
            cache_stage,
            CACHE_PLAYBACK_CURVES_PATH,
        )
        cache_curves.CreateBasisAttr().Set(UsdGeom.Tokens.bspline)
        cache_curves.CreateTypeAttr().Set(UsdGeom.Tokens.cubic)
        cache_curves.CreateWrapAttr().Set(UsdGeom.Tokens.pinned)
        cache_curves.SetWidthsInterpolation(UsdGeom.Tokens.constant)
        UsdGeom.PrimvarsAPI(cache_curves.GetPrim()).CreatePrimvar(
            "widths",
            Sdf.ValueTypeNames.FloatArray,
            UsdGeom.Tokens.constant,
        ).Set([request.width])
        source_time_attribute = cache_curves.GetPrim().CreateAttribute(
            "dtrs:sourceTime",
            Sdf.ValueTypeNames.Double,
            custom=True,
        )
        speed_primvar = UsdGeom.PrimvarsAPI(cache_curves.GetPrim()).CreatePrimvar(
            SPEED_PRIMVAR_NAME,
            Sdf.ValueTypeNames.FloatArray,
            UsdGeom.Tokens.vertex,
        )

        previous_target = stage.GetEditTarget()
        states: list[StreamlinesCacheState] = []
        generation_ms: list[float] = []
        try:
            stage.SetEditTarget(stage.GetSessionLayer())
            await execute_command(
                "CreateCaeVizMeshPrim",
                prim_type="UnitSphere",
                prim_path=request.seed_path,
                resolution=request.seed_resolution,
            )
            await execute_command(
                "TransformPrimSRT",
                path=request.seed_path,
                new_translation=list(request.seed_center),
                new_scale=[request.seed_radius] * 3,
            )
            await app.next_update_async()
            self._start_kit_cae_operator_tracking()
            timeline = omni.timeline.get_timeline_interface()
            for sample in manifest_samples(source):
                index = sample.sample_index
                source_vti = sample.source_vti
                self._streamlines_cache_build_active_sample_index = index
                sample_started_at = time.monotonic()
                selected_asset = await self._select_temporal_source_in_kit(
                    app,
                    timeline=timeline,
                    field_prim=field_prim,
                    sample=sample,
                    cae_vtk=cae_vtk,
                    Usd=Usd,
                )
                if selected_asset.resolve() != source_vti.resolve():
                    raise RuntimeError(
                        "Cache build selected a VTI outside the active manifest."
                    )
                execution = await self._run_fresh_streamlines_operator_in_kit(
                    stage,
                    app=app,
                    request=request,
                    descriptor=descriptor,
                    dataset_prim=dataset_prim,
                    field_prim=field_prim,
                    cae_usd_utils=cae_usd_utils,
                    cae_viz=cae_viz,
                    cae_vtk=cae_vtk,
                    UsdGeom=UsdGeom,
                    UsdGeomRT=UsdGeomRT,
                    wp=wp,
                    timeline=timeline,
                    execute_command=execute_command,
                    preview_path=None,
                    Sdf=Sdf,
                    capture_speed_magnitudes=True,
                    source_time_code=sample.time_code,
                )
                evidence = execution.evidence
                if not execution.execution_receipt.accepted:
                    raise RuntimeError(
                        "Cache build received an unpaired Kit-CAE execution."
                    )
                if evidence.runtime_curve_bounds is None:
                    raise RuntimeError("Cache build UsdRT geometry has no bounds.")
                if execution.speed_magnitudes is None:
                    raise RuntimeError(
                        "Cache build did not capture raw vertex speed values."
                    )
                _author_persisted_speed_sample(
                    speed_primvar,
                    execution.speed_magnitudes,
                    expected_point_count=evidence.runtime_point_count,
                    time_code=Usd.TimeCode(sample.time_code),
                )
                time_code = Usd.TimeCode(sample.time_code)
                cache_curves.GetPointsAttr().Set(
                    list(evidence.runtime_point_positions),
                    time_code,
                )
                cache_curves.GetCurveVertexCountsAttr().Set(
                    list(evidence.runtime_curve_vertex_counts),
                    time_code,
                )
                cache_curves.CreateExtentAttr().Set(
                    list(evidence.runtime_curve_bounds),
                    time_code,
                )
                source_time_attribute.Set(sample.source_time_seconds, time_code)
                elapsed_ms = (time.monotonic() - sample_started_at) * 1000.0
                states.append(
                    StreamlinesCacheState(
                        sample_index=index,
                        source_time_seconds=sample.source_time_seconds,
                        time_code=sample.time_code,
                        source_vti=source_vti.resolve().as_posix(),
                        source_vti_identity=vti_file_identity(source_vti),
                        curve_count=evidence.runtime_curve_count,
                        point_count=evidence.runtime_point_count,
                        topology_signature=cache_topology_signature(
                            evidence.runtime_curve_vertex_counts
                        ),
                        geometry_signature=cache_geometry_signature(
                            curve_count=evidence.runtime_curve_count,
                            point_count=evidence.runtime_point_count,
                            bounds=evidence.runtime_curve_bounds,
                            point_head=evidence.point_head,
                            point_tail=evidence.point_tail,
                        ),
                        generation_ms=elapsed_ms,
                        bounds=evidence.runtime_curve_bounds,
                    )
                )
                generation_ms.append(elapsed_ms)
                progress_stride = max(1, sample.total // 8)
                if (
                    sample.ordinal == 1
                    or sample.ordinal == sample.total
                    or sample.ordinal % progress_stride == 0
                ):
                    self._report_streamlines_cache_build(
                        event="PROGRESS",
                        message=(
                            f"Cache build samples={sample.ordinal}/{sample.total}; "
                            f"generation_ms={elapsed_ms:.0f}."
                        ),
                        status_callback=status_callback,
                    )
        finally:
            self._stop_kit_cae_operator_tracking()
            stage.SetEditTarget(previous_target)

        actual_time_codes = tuple(
            float(value) for value in cache_curves.GetPointsAttr().GetTimeSamples()
        )
        expected_time_codes = tuple(
            sample.time_code for sample in manifest_samples(source)
        )
        if actual_time_codes != expected_time_codes:
            raise RuntimeError(
                "Cache geometry time samples do not match the active manifest."
            )
        source_time_codes = tuple(
            float(value) for value in source_time_attribute.GetTimeSamples()
        )
        if source_time_codes != expected_time_codes:
            raise RuntimeError(
                "Cache source-time attributes do not match the active manifest."
            )
        _validate_persisted_speed_primvar(
            speed_primvar.GetAttr(),
            expected_time_codes=expected_time_codes,
            expected_point_counts=tuple(state.point_count for state in states),
            Usd=Usd,
        )
        cache_stage.GetRootLayer().Save()
        geometry_sha256 = file_sha256(cache_paths.partial_geometry_path)
        metadata = build_streamlines_cache_metadata(
            source,
            request,
            states,
            geometry_file_name=cache_paths.geometry_path.name,
            geometry_sha256=geometry_sha256,
        )
        staged_metadata = replace(
            metadata,
            geometry_file_name=cache_paths.partial_geometry_path.name,
        )
        staged_validation = validate_streamlines_cache(
            staged_metadata,
            source=source,
            settings_signature=metadata.settings_signature,
            geometry_path=cache_paths.partial_geometry_path,
        )
        if not staged_validation.valid:
            raise RuntimeError(
                "Staged Streamlines cache validation failed: "
                f"{staged_validation.message}"
            )
        cache_paths.partial_metadata_path.write_text(
            serialise_streamlines_cache_metadata(metadata),
            encoding="utf-8",
        )
        return metadata, tuple(generation_ms)

    async def load_streamlines_cache_in_kit(
        self,
        status_callback: StatusCallback | None = None,
        *,
        start_playback: bool = True,
    ) -> StreamlinesCacheLoadResult:
        """Attach and select a validated persisted cache without cadence tests.

        ``start_playback`` remains enabled for normal production loading. The
        bounded sanity workflow disables it so its one measured scheduler is
        the only cached-playback start in that workflow.
        """

        if not self.is_streamlines_cache_load_allowed():
            raise RuntimeError("Load Streamlines Cache requires Flow DETACHED.")

        import omni.kit.app
        import omni.usd
        from pxr import Usd, UsdGeom

        started_at = time.monotonic()
        self._report_streamlines_cache_load(
            event="START",
            message="Loading Streamlines cache: checking persisted artifacts.",
            status_callback=status_callback,
        )
        stage = omni.usd.get_context().get_stage()
        if not stage:
            raise RuntimeError("Cache load requires an open stage.")
        await self.stop_streamlines_cached_playback_in_kit()
        self._clear_streamlines_cache_load_state(stage)
        binding, airflow_dataset = self.resolve_current_airflow_dataset()
        cache_paths = streamlines_cache_paths(
            self.config.repo_root,
            self._streamlines_cache_ownership(binding),
        )
        if not cache_paths.metadata_path.is_file():
            raise RuntimeError("No completed Streamlines cache metadata was found.")
        if not cache_paths.geometry_path.is_file():
            raise RuntimeError("No completed Streamlines cache geometry was found.")

        self._report_streamlines_cache_load(
            event="PROGRESS",
            message="Loading Streamlines cache: validating source provenance.",
            status_callback=status_callback,
        )
        metadata = load_streamlines_cache_metadata(cache_paths.metadata_path)
        expected = self._streamlines_cache_expected_contract(
            binding=binding,
            airflow_dataset=airflow_dataset,
            stage_time_codes_per_second=float(stage.GetTimeCodesPerSecond()),
        )
        validation = validate_streamlines_cache(
            metadata,
            source=expected["source"],
            settings_signature=expected["settings_signature"],
            geometry_path=cache_paths.geometry_path,
        )
        if not validation.valid:
            if metadata.settings is None or validation.message.startswith(
                "Cache settings"
            ):
                self._log_streamlines_cache_identity_mismatch(metadata, expected)
            raise RuntimeError(
                "Cache validation failed: "
                f"{validation.message} Explicitly rebuild the cache."
            )
        playback_contract = cached_playback_contract_from_validated_cache(
            metadata,
            expected["source"],
        )
        app = omni.kit.app.get_app()
        try:
            self._report_streamlines_cache_load(
                event="PROGRESS",
                message="Loading Streamlines cache: attaching persisted geometry.",
                status_callback=status_callback,
            )
            self._attach_streamlines_cache_playback_layer(stage, cache_paths)
            return await self._complete_streamlines_cache_load_in_kit(
                stage=stage,
                app=app,
                metadata=metadata,
                playback_contract=playback_contract,
                started_at=started_at,
                status_callback=status_callback,
                start_playback=start_playback,
                Usd=Usd,
                UsdGeom=UsdGeom,
            )
        except BaseException:
            self._clear_streamlines_cache_load_state(stage)
            raise

    async def _complete_streamlines_cache_load_in_kit(
        self,
        *,
        stage,
        app,
        metadata: StreamlinesCacheMetadata,
        playback_contract,
        started_at: float,
        status_callback: StatusCallback | None,
        start_playback: bool,
        Usd,
        UsdGeom,
    ) -> StreamlinesCacheLoadResult:
        """Verify an attached cache before exposing it to cached playback."""

        self._report_streamlines_cache_load(
            event="PROGRESS",
            message="Loading Streamlines cache: composing attached geometry.",
            status_callback=status_callback,
        )
        for _ in range(3):
            await self._await_streamlines_cache_update(
                app,
                status_callback=status_callback,
                started_at=started_at,
            )
        curves_prim = stage.GetPrimAtPath(CACHE_PLAYBACK_CURVES_PATH)
        if not curves_prim or not curves_prim.IsValid():
            raise RuntimeError("Cache layer did not compose its BasisCurves prim.")
        curves = UsdGeom.BasisCurves(curves_prim)
        self._report_streamlines_cache_load(
            event="PROGRESS",
            message="Loading Streamlines cache: verifying manifest time samples.",
            status_callback=status_callback,
        )
        actual_time_codes = tuple(
            float(value) for value in curves.GetPointsAttr().GetTimeSamples()
        )
        expected_time_codes = tuple(state.time_code for state in metadata.states)
        if actual_time_codes != expected_time_codes:
            raise RuntimeError("Cache geometry time samples do not match metadata.")
        source_time_attribute = curves.GetPrim().GetAttribute("dtrs:sourceTime")
        source_time_codes = tuple(
            float(value) for value in source_time_attribute.GetTimeSamples()
        )
        expected_source_times = tuple(
            state.source_time_seconds for state in metadata.states
        )
        actual_source_times = tuple(
            float(source_time_attribute.Get(time_code))
            for time_code in expected_time_codes
        )
        if (
            source_time_codes != expected_time_codes
            or actual_source_times != expected_source_times
        ):
            raise RuntimeError(
                "Cache source-time attributes do not match metadata provenance."
            )
        _validate_persisted_speed_primvar(
            curves.GetPrim().GetAttribute(SPEED_PRIMVAR_ATTRIBUTE),
            expected_time_codes=expected_time_codes,
            expected_point_counts=tuple(state.point_count for state in metadata.states),
            Usd=Usd,
        )
        if stage.GetPrimAtPath(CACHE_BUILD_OPERATOR_PATH).IsValid():
            raise RuntimeError("Cache load retained a Kit-CAE build operator.")
        self._streamlines_loaded_cache_metadata = metadata
        self._streamlines_cache_playback_contract = playback_contract
        self._streamlines_cache_active_sample_index = None
        self._report_streamlines_cache_load(
            event="PROGRESS",
            message="Loading Streamlines cache: selecting manifest state 1.",
            status_callback=status_callback,
        )
        resolution = await self.select_streamlines_cache_state_in_kit(0.0)
        self._report_streamlines_cache_load(
            event="COMPLETE",
            message=(
                "Streamlines cache loaded: exact manifest state "
                f"{resolution.sample.ordinal}/{resolution.sample.total}."
            ),
            status_callback=status_callback,
        )
        if start_playback and (
            self.config.simulation_cache.streamlines_presentation_period_seconds
            is not None
        ):
            await self.start_streamlines_cached_playback_in_kit(
                status_callback=status_callback,
            )
        return StreamlinesCacheLoadResult(
            metadata=metadata,
            active_sample_index=resolution.sample.sample_index,
            load_ms=(time.monotonic() - started_at) * 1000.0,
        )

    def _clear_streamlines_cache_load_state(self, stage) -> None:
        """Detach an unverified cache and clear every playback-facing reference."""

        self._detach_streamlines_cache_playback_layer(stage)
        self._streamlines_loaded_cache_metadata = None
        self._streamlines_loaded_cache_paths = None
        self._streamlines_cache_playback_contract = None
        self._streamlines_cache_active_sample_index = None

    def is_streamlines_cache_load_allowed(self) -> bool:
        """Return whether cache playback can start without contending with Flow."""

        return self._flow_lifecycle_state == "DETACHED"

    def _streamlines_cache_expected_contract(
        self,
        *,
        binding,
        airflow_dataset,
        stage_time_codes_per_second: float,
    ) -> dict[str, object]:
        """Resolve cache invalidation facts without importing a VTI into Kit."""

        sample = resolve_static_velocity_sample_from_airflow_dataset(
            airflow_dataset,
            binding,
            self.config.simulation_cache.velocity_field_name,
            sample_index=0,
        )
        descriptor = StaticVelocitySourceDescriptor(
            workload=sample.workload,
            dataset_identity=sample.dataset_identity,
            sample_index=sample.sample_index,
            vti_path=sample.vti_path,
            dataset_prim_path=self.STATIC_DATASET_PATH,
            velocity_field_prim_path=(
                f"{self.STATIC_IMPORT_ROOT}/PointData/" f"{sample.velocity_field_name}"
            ),
            world_bounds=sample.source_world_bounds,
            dimensions=sample.dimensions,
            spacing=sample.spacing,
            origin=sample.source_origin,
            source_origin=sample.source_origin,
            stage_meters_per_unit=1.0,
        )
        request = self._build_streamlines_cache_request(descriptor)
        source = temporal_source_from_airflow_dataset(
            airflow_dataset,
            workload=binding.workload_mode,
            static_descriptor=descriptor,
            time_codes_per_second=stage_time_codes_per_second,
        )
        return {
            "source": source,
            "settings_signature": streamlines_settings_signature(request),
            "settings": streamlines_cache_settings(request),
        }

    def _build_streamlines_cache_request(
        self,
        descriptor: StaticVelocitySourceDescriptor,
    ) -> StreamlinesOperatorRequest:
        """Derive cache geometry settings from VTI data, not importer floats."""

        minimum = tuple(float(value) for value in descriptor.source_origin)
        maximum = tuple(
            minimum[index]
            + ((descriptor.dimensions[index] - 1) * descriptor.spacing[index])
            for index in range(3)
        )
        canonical_descriptor = replace(
            descriptor,
            world_bounds=(minimum, maximum),
            origin=minimum,
        )
        return replace(
            build_streamlines_operator_request(canonical_descriptor),
            operator_path=CACHE_BUILD_OPERATOR_PATH,
            seed_path=CACHE_BUILD_SEED_PATH,
            operator_type="standard",
        )

    def _log_streamlines_cache_identity_mismatch(
        self,
        metadata: StreamlinesCacheMetadata,
        expected: dict[str, object],
    ) -> None:
        """Log canonical identity evidence without dumping cache geometry details."""

        current = expected.get("settings")
        if metadata.settings is not None and isinstance(
            current, StreamlinesCacheSettings
        ):
            differences = cache_settings_differences(metadata.settings, current)
        elif metadata.settings is None:
            differences = ("canonical settings payload unavailable",)
        else:
            differences = ("current canonical settings payload unavailable",)
        cached_payload = (
            metadata.settings.to_dict() if metadata.settings is not None else None
        )
        current_payload = current.to_dict() if hasattr(current, "to_dict") else None
        carb = self._streamlines_carb_logger()
        if carb:
            message = "\n".join(
                (
                    "DTRS STREAMLINES | CACHE_IDENTITY | MISMATCH",
                    f"cached_settings_signature={metadata.settings_signature}",
                    f"expected_settings_signature="
                    f"{expected.get('settings_signature')}",
                    "cached_canonical_settings_seed="
                    f"{json.dumps(cached_payload, sort_keys=True)}",
                    "current_canonical_settings_seed="
                    f"{json.dumps(current_payload, sort_keys=True)}",
                    f"differing_fields={','.join(differences) or 'none'}",
                )
            )
            carb.log_error(with_dtrs_yerevan_timestamp(message))

    def _report_streamlines_cache_load(
        self,
        *,
        event: str,
        message: str,
        status_callback: StatusCallback | None,
    ) -> None:
        """Expose a cache-load milestone in both OmniUI and the Kit log."""

        if status_callback:
            status_callback(message)
        carb = self._streamlines_carb_logger()
        if carb:
            carb.log_warn(
                with_dtrs_yerevan_timestamp(
                    "DTRS STREAMLINES | CACHE_LOAD | " f"{event}\nstatus={message}"
                )
            )

    def _report_streamlines_cache_build(
        self,
        *,
        event: str,
        message: str,
        status_callback: StatusCallback | None,
    ) -> None:
        """Expose deterministic cache-build progress without tick-level noise."""

        if status_callback:
            status_callback(message)
        carb = self._streamlines_carb_logger()
        if not carb:
            return
        log = carb.log_error if event == "FAIL" else carb.log_warn
        log(
            with_dtrs_yerevan_timestamp(
                f"DTRS STREAMLINES | CACHE_BUILD | {event}\nstatus={message}"
            )
        )

    def _report_streamlines_profile(
        self,
        *,
        event: str,
        message: str,
        status_callback: StatusCallback | None,
    ) -> None:
        """Report bounded profile acceptance stages without cache-build noise."""

        if status_callback:
            status_callback(message)
        carb = self._streamlines_carb_logger()
        if carb:
            carb.log_warn(
                with_dtrs_yerevan_timestamp(
                    f"DTRS STREAMLINES | PRODUCTION_PROFILE | {event}\n"
                    f"status={message}"
                )
            )

    async def _await_streamlines_cache_update(
        self,
        app,
        *,
        status_callback: StatusCallback | None,
        started_at: float,
        heartbeat_seconds: float = 5.0,
    ) -> None:
        """Await one Kit frame while making a stalled composition observable."""

        update = asyncio.ensure_future(app.next_update_async())
        while not update.done():
            try:
                await asyncio.wait_for(
                    asyncio.shield(update),
                    timeout=heartbeat_seconds,
                )
            except TimeoutError:
                elapsed_seconds = time.monotonic() - started_at
                self._report_streamlines_cache_load(
                    event="WAITING",
                    message=(
                        "Loading Streamlines cache: waiting for Kit composition "
                        f"({elapsed_seconds:.0f} s elapsed)."
                    ),
                    status_callback=status_callback,
                )
        await update

    def _attach_streamlines_cache_playback_layer(
        self,
        stage,
        cache_paths: StreamlinesCachePaths,
    ) -> None:
        """Attach one verified cache file only to the transient Session Layer."""

        self._detach_streamlines_cache_playback_layer(stage)
        stage.GetSessionLayer().subLayerPaths.append(
            cache_paths.geometry_path.resolve().as_posix()
        )
        self._streamlines_loaded_cache_paths = cache_paths

    def _detach_streamlines_cache_playback_layer(self, stage) -> None:
        """Detach only this cache reference; the persisted cache stays on disk."""

        expected_paths = set()
        loaded_paths = getattr(self, "_streamlines_loaded_cache_paths", None)
        if loaded_paths is not None:
            expected_paths.add(loaded_paths.geometry_path.resolve().as_posix())
        if hasattr(self, "resolve_configured_airflow_targets"):
            for target in self.resolve_configured_airflow_targets():
                ownership = self._streamlines_cache_ownership(target.binding)
                paths = streamlines_cache_paths(self.config.repo_root, ownership)
                expected_paths.add(paths.geometry_path.resolve().as_posix())
        session_layer = stage.GetSessionLayer()
        for sublayer_path in tuple(session_layer.subLayerPaths):
            try:
                matches_cache = (
                    Path(sublayer_path).resolve().as_posix() in expected_paths
                )
            except OSError:
                matches_cache = sublayer_path.replace("\\", "/") in expected_paths
            if matches_cache:
                session_layer.subLayerPaths.remove(sublayer_path)

    @staticmethod
    def _format_cache_build_success(
        *,
        metadata: StreamlinesCacheMetadata,
        cache_paths: StreamlinesCachePaths,
        generation_ms: tuple[float, ...],
        total_ms: float,
    ) -> str:
        """Summarise all manifest states without dumping raw cache geometry."""

        cache_size = (
            cache_paths.geometry_path.stat().st_size
            + cache_paths.metadata_path.stat().st_size
        )
        first_state = metadata.states[0]
        settings = metadata.settings
        max_steps = settings.max_steps if settings else "unknown"
        return "\n".join(
            (
                "DTRS STREAMLINES | CACHE_BUILD | PASS",
                f"workload={metadata.workload}",
                f"dataset={metadata.dataset_identity}",
                f"sample_count={metadata.sample_count}",
                f"generated_curve_count={first_state.curve_count}",
                f"generated_point_count={first_state.point_count}",
                f"max_steps={max_steps}",
                f"profile={settings.profile_name if settings else 'unknown'}",
                "profile_signature="
                f"{settings.profile_signature if settings else 'unknown'}",
                "persisted_attributes="
                f"{settings.persisted_attributes if settings else 'unknown'}",
                f"source_signature={metadata.source_signature}",
                f"settings_signature={metadata.settings_signature}",
                f"cache_geometry={cache_paths.geometry_path}",
                f"cache_size_bytes={cache_size}",
                f"generation_ms_median={median(generation_ms):.0f}",
                f"generation_ms_max={max(generation_ms):.0f}",
                f"topology_consistent={metadata.topology_consistent}",
                "failed_samples=()",
                "state=VALID",
                'NEXT_ACTION | Press "Load Streamlines Cache" to inspect it.',
                f"total_ms={total_ms:.0f}",
            )
        )

    @staticmethod
    def _format_cache_build_failure(
        *,
        error: Exception,
        failed_sample_index: int | None,
        cleanup: StreamlinesCleanupReceipt,
        total_ms: float,
    ) -> str:
        """Report a broken build without certifying a partial cache artifact."""

        return "\n".join(
            (
                "========================================",
                "DTRS STREAMLINES | CACHE_BUILD | FAIL",
                "========================================",
                f"failed_sample_index={failed_sample_index}",
                f"reason={error}",
                f"rollback={'CLEAN' if cleanup.clean else 'DIRTY'}",
                "cache_replacement=NOT_APPLIED",
                "result=FAIL",
                f"total_ms={total_ms:.0f}",
            )
        )
