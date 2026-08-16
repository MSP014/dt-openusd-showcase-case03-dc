"""Kit-facing persistent cache build, validation, attachment, and state selection."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, replace
from pathlib import Path
from statistics import median
from typing import Callable

from digital_twin_runtime_suite.app.airflow_dataset import discover_airflow_dataset
from digital_twin_runtime_suite.app.diagnostics import with_dtrs_yerevan_timestamp
from digital_twin_runtime_suite.app.flow.static_source import (
    StaticVelocitySourceDescriptor,
    resolve_static_velocity_sample,
)
from digital_twin_runtime_suite.app.streamlines.cache import (
    CACHE_BUILD_OPERATOR_PATH,
    CACHE_BUILD_SEED_PATH,
    CACHE_PLAYBACK_CURVES_PATH,
    CACHE_PLAYBACK_ROOT_PATH,
    CACHE_SCHEMA_VERSION,
    StreamlinesCacheMetadata,
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
    source_signature_from_values,
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
from digital_twin_runtime_suite.app.streamlines.lifecycle import (
    StreamlinesCleanupReceipt,
)
from digital_twin_runtime_suite.app.streamlines.proof import (
    StreamlinesOperatorRequest,
    build_streamlines_operator_request,
)
from digital_twin_runtime_suite.app.streamlines.temporal import (
    TemporalSampleResolution,
    TemporalSourceSample,
    TemporalVelocitySourceDescriptor,
    resolve_manifest_sample,
)

StatusCallback = Callable[[str], None]


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
        return f'Ready вЂ” Press "{action}".'

    def announce_streamlines_cache_load_ready(self) -> str:
        """Publish cache-load readiness without measuring presentation cadence."""

        action = "Load Streamlines Cache"
        message = (
            "DTRS STREAMLINES | CACHE_LOAD | READY\n" f'NEXT_ACTION | Press "{action}"'
        )
        carb = self._streamlines_carb_logger()
        if carb:
            carb.log_warn(with_dtrs_yerevan_timestamp(message))
        return f'Ready вЂ” Press "{action}".'

    def inspect_existing_streamlines_cache(self) -> StreamlinesCacheValidation:
        """Inspect persisted cache provenance without creating a Kit operator."""

        cache_paths = streamlines_cache_paths(self.config.repo_root)
        if not cache_paths.metadata_path.is_file():
            return StreamlinesCacheValidation(
                False,
                "No completed Streamlines cache metadata was found.",
            )
        if not cache_paths.geometry_path.is_file():
            return StreamlinesCacheValidation(
                False,
                "No completed Streamlines cache geometry was found.",
            )
        try:
            metadata = load_streamlines_cache_metadata(cache_paths.metadata_path)
            expected = self._streamlines_cache_expected_contract(
                stage_time_codes_per_second=metadata.time_codes_per_second,
            )
            return validate_streamlines_cache(
                metadata,
                source_signature=expected["source_signature"],
                settings_signature=expected["settings_signature"],
                workload=expected["workload"],
                dataset_identity=expected["dataset_identity"],
                sample_count=expected["sample_count"],
                geometry_path=cache_paths.geometry_path,
            )
        except Exception as error:
            return StreamlinesCacheValidation(
                False,
                f"Cache inspection failed: {error}",
            )

    async def build_streamlines_cache_in_kit(
        self,
        status_callback: StatusCallback | None = None,
    ) -> StreamlinesCacheBuildResult:
        """Build one complete Nominal cache from real Kit-CAE/UsdRT results.

        The VTI sequence remains authoritative only while this bounded build
        runs. The USDC result is a derived view cache and leaves the accepted
        The explicit recompute fallback remains separate from this cache owner.
        """

        if self._flow_lifecycle_state != "DETACHED":
            return StreamlinesCacheBuildResult(
                False,
                "Cache build is unavailable while airflow Attach is active.",
            )

        started_at = time.monotonic()
        carb = self._streamlines_carb_logger()
        cleanup = None
        cache_paths = streamlines_cache_paths(self.config.repo_root)
        build_mode = streamlines_cache_build_mode(cache_paths)
        self._streamlines_cache_build_active_sample_index = None
        try:
            if carb:
                carb.log_warn(
                    with_dtrs_yerevan_timestamp(
                        "DTRS STREAMLINES | CACHE_BUILD | " f"{build_mode}"
                    )
                )
            if status_callback:
                status_callback("Cache build: preparing manifest temporal source")
            cleanup = await self.clear_streamlines_static_runtime_in_kit()
            if not cleanup.clean:
                raise RuntimeError(
                    "Streamlines cleanup was not clean before cache build."
                )
            source = await self.prepare_streamlines_temporal_velocity_source_in_kit(
                status_callback=status_callback,
            )
            if source.workload != "Nominal":
                raise RuntimeError(
                    "Cache build is scoped to Nominal; "
                    f"current workload={source.workload}."
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
            if status_callback:
                status_callback("Cache build failed; inspect the structured log.")
            return StreamlinesCacheBuildResult(False, message)

        message = self._format_cache_build_success(
            metadata=metadata,
            cache_paths=cache_paths,
            generation_ms=generation_ms,
            total_ms=(time.monotonic() - started_at) * 1000.0,
        )
        if carb:
            carb.log_warn(with_dtrs_yerevan_timestamp(message))
        if status_callback:
            status_callback(
                "Cache build complete. Load Streamlines Cache to inspect it."
            )
        self._streamlines_cache_build_active_sample_index = None
        return StreamlinesCacheBuildResult(True, message, metadata)

    async def _build_cache_geometry_in_kit(
        self,
        source: TemporalVelocitySourceDescriptor,
        *,
        cache_paths: StreamlinesCachePaths,
        status_callback: StatusCallback | None,
    ) -> tuple[StreamlinesCacheMetadata, tuple[float, ...]]:
        """Persist every real manifest sample without creating a RuntimePreview."""

        import carb
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
        cache_curves.CreateDisplayColorPrimvar(UsdGeom.Tokens.constant).Set(
            [(0.1, 0.8, 1.0)]
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
            for index, source_vti in enumerate(source.velocity_paths):
                self._streamlines_cache_build_active_sample_index = index
                sample_started_at = time.monotonic()
                sample = TemporalSourceSample(
                    ordinal=index + 1,
                    total=source.sample_count,
                    sample_index=index,
                    source_vti=source_vti,
                    source_time_seconds=(
                        source.sample_time_codes[index] / source.time_codes_per_second
                    ),
                    time_code=source.sample_time_codes[index],
                )
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
                )
                evidence = execution.evidence
                if not execution.execution_receipt.accepted:
                    raise RuntimeError(
                        "Cache build received an unpaired Kit-CAE execution."
                    )
                if evidence.runtime_curve_bounds is None:
                    raise RuntimeError("Cache build UsdRT geometry has no bounds.")
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
                if status_callback:
                    status_callback(
                        f"Cache build: sample {sample.ordinal}/{sample.total}"
                    )
                if index == 0 or sample.ordinal % 10 == 0:
                    carb.log_warn(
                        with_dtrs_yerevan_timestamp(
                            "DTRS STREAMLINES | CACHE_BUILD | "
                            f"SAMPLE {sample.ordinal}/{sample.total} | PASS | "
                            f"generation_ms={elapsed_ms:.0f}"
                        )
                    )
        finally:
            self._stop_kit_cae_operator_tracking()
            stage.SetEditTarget(previous_target)

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
            source_signature=metadata.source_signature,
            settings_signature=metadata.settings_signature,
            workload=metadata.workload,
            dataset_identity=metadata.dataset_identity,
            sample_count=metadata.sample_count,
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
    ) -> StreamlinesCacheLoadResult:
        """Attach and select a validated persisted cache without cadence tests."""

        import omni.kit.app
        import omni.usd
        from pxr import UsdGeom

        started_at = time.monotonic()
        stage = omni.usd.get_context().get_stage()
        if not stage:
            raise RuntimeError("Cache load requires an open stage.")
        cache_paths = streamlines_cache_paths(self.config.repo_root)
        if not cache_paths.metadata_path.is_file():
            raise RuntimeError("No completed Streamlines cache metadata was found.")
        if not cache_paths.geometry_path.is_file():
            raise RuntimeError("No completed Streamlines cache geometry was found.")

        metadata = load_streamlines_cache_metadata(cache_paths.metadata_path)
        expected = self._streamlines_cache_expected_contract(
            stage_time_codes_per_second=float(stage.GetTimeCodesPerSecond()),
        )
        validation = validate_streamlines_cache(
            metadata,
            source_signature=expected["source_signature"],
            settings_signature=expected["settings_signature"],
            workload=expected["workload"],
            dataset_identity=expected["dataset_identity"],
            sample_count=expected["sample_count"],
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
        self._attach_streamlines_cache_playback_layer(
            stage,
            cache_paths,
        )
        app = omni.kit.app.get_app()
        for _ in range(3):
            await app.next_update_async()
        curves_prim = stage.GetPrimAtPath(CACHE_PLAYBACK_CURVES_PATH)
        if not curves_prim or not curves_prim.IsValid():
            raise RuntimeError("Cache layer did not compose its BasisCurves prim.")
        curves = UsdGeom.BasisCurves(curves_prim)
        actual_time_codes = tuple(
            float(value) for value in curves.GetPointsAttr().GetTimeSamples()
        )
        expected_time_codes = tuple(state.time_code for state in metadata.states)
        if actual_time_codes != expected_time_codes:
            raise RuntimeError("Cache geometry time samples do not match metadata.")
        if stage.GetPrimAtPath(CACHE_BUILD_OPERATOR_PATH).IsValid():
            raise RuntimeError("Cache load retained a Kit-CAE build operator.")
        self._streamlines_loaded_cache_metadata = metadata
        self._streamlines_cache_active_sample_index = None
        resolution = await self.select_streamlines_cache_state_in_kit(0.0)
        if status_callback:
            status_callback(
                "Streamlines cache loaded: exact manifest state "
                f"{resolution.sample.ordinal}/{resolution.sample.total}."
            )
        return StreamlinesCacheLoadResult(
            metadata=metadata,
            active_sample_index=resolution.sample.sample_index,
            load_ms=(time.monotonic() - started_at) * 1000.0,
        )

    async def select_streamlines_cache_state_in_kit(
        self,
        phase_seconds: float,
    ) -> TemporalSampleResolution:
        """Select one exact cached time sample; the same identity is a NO_OP."""

        import omni.kit.app
        import omni.timeline

        metadata = self._streamlines_loaded_cache_metadata
        if not isinstance(metadata, StreamlinesCacheMetadata):
            raise RuntimeError(
                "Load a valid Streamlines cache before selecting a state."
            )
        samples = tuple(
            TemporalSourceSample(
                ordinal=index + 1,
                total=metadata.sample_count,
                sample_index=state.sample_index,
                source_vti=Path(state.source_vti),
                source_time_seconds=state.source_time_seconds,
                time_code=state.time_code,
            )
            for index, state in enumerate(metadata.states)
        )
        resolution = resolve_manifest_sample(
            samples,
            sample_interval_seconds=metadata.sample_interval_seconds,
            phase_seconds=phase_seconds,
            active_sample_index=self._streamlines_cache_active_sample_index,
        )
        if resolution.is_no_op:
            return resolution
        timeline = omni.timeline.get_timeline_interface()
        timeline.pause()
        timeline.set_current_time(resolution.sample.source_time_seconds)
        app = omni.kit.app.get_app()
        await app.next_update_async()
        await app.next_update_async()
        self._streamlines_cache_active_sample_index = resolution.sample.sample_index
        return resolution

    def _streamlines_cache_expected_contract(
        self,
        *,
        stage_time_codes_per_second: float,
    ) -> dict[str, object]:
        """Resolve cache invalidation facts without importing a VTI into Kit."""

        binding = self.resolve_current_workload_airflow_binding()
        sample = resolve_static_velocity_sample(
            self.config.asset_root,
            binding,
            self.config.simulation_cache.velocity_field_name,
            sample_index=0,
        )
        dataset = discover_airflow_dataset(self.config.asset_root, binding.dataset)
        velocity_paths = dataset.velocity_vti_sequence_paths
        interval_seconds = dataset.sample_interval_seconds
        time_codes = tuple(
            index * stage_time_codes_per_second * interval_seconds
            for index in range(len(velocity_paths))
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
        return {
            "workload": binding.workload_mode,
            "dataset_identity": binding.dataset_identity,
            "sample_count": len(velocity_paths),
            "source_signature": source_signature_from_values(
                workload=binding.workload_mode,
                dataset_identity=binding.dataset_identity,
                velocity_paths=velocity_paths,
                sample_time_codes=time_codes,
                time_codes_per_second=stage_time_codes_per_second,
                sample_interval_seconds=interval_seconds,
            ),
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

    def _detach_streamlines_cache_playback_layer(self, stage) -> None:
        """Detach only this cache reference; the persisted cache stays on disk."""

        expected_paths = {
            streamlines_cache_paths(self.config.repo_root)
            .geometry_path.resolve()
            .as_posix()
        }
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
        """Summarise all 80 build states without dumping their raw geometry."""

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
