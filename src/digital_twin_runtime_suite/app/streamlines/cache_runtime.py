"""Kit-facing persistent centerline-cache build, validation, and preparation."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, replace
from pathlib import Path
from statistics import median
from types import SimpleNamespace
from typing import Callable

from digital_twin_runtime_suite.app.airflow_validation.cache import (
    build_dataset_validation_signature,
)
from digital_twin_runtime_suite.app.diagnostics import (
    with_dtrs_local_timestamp,
    with_dtrs_yerevan_timestamp,
)
from digital_twin_runtime_suite.app.flow.static_source import (
    StaticVelocitySourceDescriptor,
    resolve_static_velocity_sample_from_airflow_dataset,
)
from digital_twin_runtime_suite.app.status_log import format_dtrs_diagnostic_block
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
    StreamlinesCacheSpeedEvidence,
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
    source_signature_from_temporal_source,
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
    StreamlinesCacheValidationReceipt,
    inspect_streamlines_cache,
    streamlines_cache_resource_fingerprint,
)
from digital_twin_runtime_suite.app.streamlines.constant_topology import (
    SOURCE_CURVE_VERTEX_COUNTS_ATTRIBUTE,
    pad_streamlines_sample_for_renderer,
    renderer_topology_for_profile,
    terminal_padding_is_exact,
    validate_persisted_constant_topology_cache,
)
from digital_twin_runtime_suite.app.streamlines.lifecycle import (
    StreamlinesCleanupReceipt,
)
from digital_twin_runtime_suite.app.streamlines.playback import (
    cached_playback_contract_from_validated_cache,
    resolve_cached_playback_state,
)
from digital_twin_runtime_suite.app.streamlines.profile import (
    DEFAULT_STREAMLINES_PROFILE,
    StreamlinesProfileId,
    final_geometry_contract,
    geometry_contract_signature,
)
from digital_twin_runtime_suite.app.streamlines.proof import (
    StreamlinesOperatorRequest,
    build_streamlines_seeded_operator_request,
)
from digital_twin_runtime_suite.app.streamlines.seed_layout import (
    derive_global_flow_path_layout,
    derive_volume_coverage_layout,
)
from digital_twin_runtime_suite.app.streamlines.seed_runtime import (
    author_streamlines_seed_mesh_in_kit,
)
from digital_twin_runtime_suite.app.streamlines.speed import (
    SPEED_PRIMVAR_ATTRIBUTE,
    SPEED_PRIMVAR_NAME,
    validate_persisted_speed_magnitudes,
)
from digital_twin_runtime_suite.app.streamlines.speed_distribution import (
    SpeedDistributionAccumulator,
    build_streamlines_cache_speed_evidence,
    persisted_speed_chunks,
    validate_persisted_speed_cache,
)
from digital_twin_runtime_suite.app.streamlines.temporal import (
    TemporalVelocitySourceDescriptor,
    manifest_samples,
    temporal_source_from_airflow_dataset,
)
from digital_twin_runtime_suite.app.streamlines.temporal_liveness import (
    PersistedTemporalGeometryEvidence,
    inspect_persisted_streamlines_temporal_geometry,
)

StatusCallback = Callable[[str], None]
STREAMLINES_VALIDATION_CONTRACT_VERSION = "streamlines-cache-validation-v1"


def _float_tuple(values, count: int) -> tuple[float, ...]:
    """Restore one fixed-size numeric tuple from JSON evidence."""

    result = tuple(float(value) for value in values)
    if len(result) != count:
        raise ValueError(f"expected {count} numeric values")
    return result


def _int_tuple(values, count: int) -> tuple[int, ...]:
    """Restore one fixed-size integer tuple from JSON evidence."""

    result = tuple(int(value) for value in values)
    if len(result) != count:
        raise ValueError(f"expected {count} integer values")
    return result


def _float_tuple_pair(values) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """Restore two three-dimensional bounds from JSON evidence."""

    result = tuple(_float_tuple(item, 3) for item in values)
    if len(result) != 2:
        raise ValueError("expected minimum and maximum bounds")
    return result


class StreamlinesPresentationCancelled(RuntimeError):
    """Stop a stale presentation candidate before it can attach or start work."""


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


def _validate_composed_constant_topology_cache(curves, metadata, *, Usd) -> None:
    """Require renderer topology and source provenance on the attached prim."""

    topology = renderer_topology_for_profile(metadata.profile_id)
    renderer_counts_attr = curves.GetCurveVertexCountsAttr()
    if renderer_counts_attr.GetTimeSamples():
        raise RuntimeError("Composed renderer topology is time sampled.")
    if tuple(renderer_counts_attr.Get() or ()) != topology.curve_vertex_counts:
        raise RuntimeError("Composed renderer topology differs from the profile.")
    source_counts_attr = curves.GetPrim().GetAttribute(
        SOURCE_CURVE_VERTEX_COUNTS_ATTRIBUTE
    )
    if not source_counts_attr or not source_counts_attr.IsValid():
        raise RuntimeError("Cache source curve topology is missing.")
    expected_times = tuple(state.time_code for state in metadata.states)
    actual_times = tuple(float(value) for value in source_counts_attr.GetTimeSamples())
    if actual_times != expected_times:
        raise RuntimeError("Cache source topology samples are incomplete.")
    points_attr = curves.GetPointsAttr()
    speed_attr = curves.GetPrim().GetAttribute(SPEED_PRIMVAR_ATTRIBUTE)
    for state in metadata.states:
        time_code = Usd.TimeCode(state.time_code)
        points = tuple(points_attr.Get(time_code) or ())
        speeds = tuple(speed_attr.Get(time_code) or ())
        source_counts = tuple(source_counts_attr.Get(time_code) or ())
        if (
            len(points) != topology.point_count
            or len(speeds) != topology.point_count
            or len(source_counts) != topology.curve_count
            or sum(source_counts) != state.source_point_count
        ):
            raise RuntimeError("Composed constant-topology arrays are misaligned.")
        if not terminal_padding_is_exact(
            points,
            source_counts,
            vertices_per_curve=topology.vertices_per_curve,
        ) or not terminal_padding_is_exact(
            speeds,
            source_counts,
            vertices_per_curve=topology.vertices_per_curve,
        ):
            raise RuntimeError("Composed terminal padding is not an exact repeat.")


@dataclass(frozen=True)
class StreamlinesCacheBuildResult:
    """Outcome of one complete derived-cache build."""

    success: bool
    message: str
    metadata: StreamlinesCacheMetadata | None = None


@dataclass(frozen=True)
class StreamlinesConstantTopologyPrototypeResult:
    """One Volume/Nominal cache build and representative offline proof."""

    success: bool
    message: str
    metadata: StreamlinesCacheMetadata | None = None
    sample_proofs: tuple[object, ...] = ()


@dataclass(frozen=True)
class StreamlinesProductionCacheResult:
    """Validated or newly built cache evidence for one authoritative workload."""

    workload: str
    dataset_identity: str
    profile_id: str
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
class StreamlinesProductionCacheMatrixEntry:
    """Read-only readiness for one required workload/profile cache."""

    workload: str
    dataset_identity: str
    profile_id: str
    classification: str
    message: str

    @property
    def valid(self) -> bool:
        """Return whether this entry can be reused by the matrix build."""

        return self.classification == "VALID"


@dataclass(frozen=True)
class StreamlinesProductionSpeedEntry:
    """Cheap persisted raw-speed availability evidence for one production cache."""

    entry: StreamlinesProductionCacheMatrixEntry
    speed_header_available: bool
    geometry_path: Path | None = None
    metadata: StreamlinesCacheMetadata | None = None
    speed_evidence: StreamlinesCacheSpeedEvidence | None = None

    @property
    def valid(self) -> bool:
        """Require both structural cache readiness and its speed time samples."""

        return self.entry.valid and self.speed_header_available


@dataclass(frozen=True)
class StreamlinesProductionCacheTemporalEntry:
    """Structural and authentic-geometry readiness for one matrix cache."""

    entry: StreamlinesProductionCacheMatrixEntry
    temporal_geometry: PersistedTemporalGeometryEvidence | None
    diagnostic_error: str | None = None

    @property
    def valid(self) -> bool:
        """Allow matrix reuse only after structural and temporal validation."""

        return bool(
            self.entry.valid
            and self.temporal_geometry is not None
            and self.temporal_geometry.passed
        )


class StreamlinesCacheRuntimeMixin:
    """Own Kit cache materialisation; never own acceptance benchmarking."""

    def reset_streamlines_cache_validation_receipts(self) -> None:
        """Forget background cache receipts at an application lifecycle boundary."""

        self._streamlines_cache_validation_receipts = {}
        self._streamlines_cache_validation_tasks = {}

    def announce_streamlines_phase44b_cache_build_when_ready(self) -> bool:
        """Keep the completed cache-build scenario permanently retired."""

        return False

    def streamlines_cache_readiness_snapshot(self) -> StreamlinesCacheInspection:
        """Return the current receipt state without touching cache resources."""

        binding, airflow_dataset = self.resolve_current_airflow_dataset()
        return self._streamlines_cache_receipt_snapshot(binding, airflow_dataset)

    def configured_streamlines_cache_readiness_snapshot(
        self,
    ) -> tuple[StreamlinesCacheInspection, ...]:
        """Return cheap receipt projections for every configured workload."""

        return tuple(
            self._streamlines_cache_receipt_snapshot(
                target.binding,
                target.dataset,
            )
            for target in self.resolve_configured_airflow_targets()
        )

    def streamlines_production_cache_matrix_readiness_snapshot(
        self,
    ) -> tuple[StreamlinesProductionCacheMatrixEntry, ...]:
        """Project all eight frozen cache identities without starting validation."""

        entries = []
        for target in self.resolve_configured_airflow_targets():
            for profile_id in StreamlinesProfileId:
                inspection = self._inspect_streamlines_cache_for_target(
                    target.binding,
                    target.dataset,
                    profile_id=profile_id,
                )
                entries.append(
                    StreamlinesProductionCacheMatrixEntry(
                        workload=target.binding.workload_mode,
                        dataset_identity=target.binding.dataset_identity,
                        profile_id=profile_id.value,
                        classification=inspection.classification,
                        message=inspection.message,
                    )
                )
        return tuple(entries)

    def streamlines_production_cache_matrix_temporal_readiness_snapshot(
        self,
    ) -> tuple[StreamlinesProductionCacheTemporalEntry, ...]:
        """Inspect every persisted matrix cache before accepting playback reuse."""

        entries = []
        for target in self.resolve_configured_airflow_targets():
            for profile_id in StreamlinesProfileId:
                inspection = self._inspect_streamlines_cache_for_target(
                    target.binding,
                    target.dataset,
                    profile_id=profile_id,
                )
                entry = StreamlinesProductionCacheMatrixEntry(
                    workload=target.binding.workload_mode,
                    dataset_identity=target.binding.dataset_identity,
                    profile_id=profile_id.value,
                    classification=inspection.classification,
                    message=inspection.message,
                )
                evidence = None
                error = None
                if inspection.valid and inspection.metadata is not None:
                    try:
                        evidence = inspect_persisted_streamlines_temporal_geometry(
                            inspection.paths.geometry_path,
                            inspection.metadata,
                        )
                    except (
                        ImportError,
                        OSError,
                        RuntimeError,
                        TypeError,
                        ValueError,
                    ) as exception:
                        error = " ".join(str(exception).splitlines())
                entries.append(
                    StreamlinesProductionCacheTemporalEntry(
                        entry=entry,
                        temporal_geometry=evidence,
                        diagnostic_error=error,
                    )
                )
        return tuple(entries)

    def streamlines_production_speed_readiness_snapshot(
        self,
    ) -> tuple[StreamlinesProductionSpeedEntry, ...]:
        """Check eight cache headers without rebuilding or scanning vertex payloads."""

        from digital_twin_runtime_suite.app.streamlines.speed_distribution import (
            persisted_speed_header_available,
        )

        entries = []
        for target in self.resolve_configured_airflow_targets():
            for profile_id in StreamlinesProfileId:
                inspection = self._inspect_streamlines_cache_for_target(
                    target.binding,
                    target.dataset,
                    profile_id=profile_id,
                )
                entry = StreamlinesProductionCacheMatrixEntry(
                    workload=target.binding.workload_mode,
                    dataset_identity=target.binding.dataset_identity,
                    profile_id=profile_id.value,
                    classification=inspection.classification,
                    message=inspection.message,
                )
                speed_available = bool(
                    inspection.valid
                    and inspection.metadata is not None
                    and persisted_speed_header_available(
                        inspection.paths.geometry_path,
                        inspection.metadata,
                    )
                )
                entries.append(
                    StreamlinesProductionSpeedEntry(
                        entry,
                        speed_available,
                        inspection.paths.geometry_path if inspection.valid else None,
                        inspection.metadata if inspection.valid else None,
                        (
                            inspection.metadata.speed_evidence
                            if inspection.valid and inspection.metadata is not None
                            else None
                        ),
                    )
                )
        return tuple(entries)

    async def ensure_current_streamlines_cache_validation_in_background(
        self,
    ) -> StreamlinesCacheValidationReceipt:
        """Strongly validate the current cache once, outside the Kit/UI thread."""

        binding, airflow_dataset = self.resolve_current_airflow_dataset()
        return await self.ensure_streamlines_cache_validation_in_background(
            binding,
            airflow_dataset,
        )

    async def ensure_configured_streamlines_cache_validations_in_background(
        self,
        status_callback: StatusCallback | None = None,
    ) -> tuple[StreamlinesCacheValidationReceipt, ...]:
        """Validate all final workload/profile caches off the Kit thread."""

        receipts = []
        for target in self.resolve_configured_airflow_targets():
            for profile_id in StreamlinesProfileId:
                if status_callback:
                    status_callback(
                        "Streamlines receipt: "
                        f"workload={target.binding.workload_mode}; "
                        f"profile={profile_id.value}; status=CHECKING"
                    )
                receipt = await self.ensure_streamlines_cache_validation_in_background(
                    target.binding,
                    target.dataset,
                    profile_id=profile_id,
                    emit_diagnostic=status_callback is None,
                )
                receipts.append(receipt)
                if status_callback:
                    status_callback(
                        "Streamlines receipt: "
                        f"workload={target.binding.workload_mode}; "
                        f"profile={profile_id.value}; "
                        f"status={receipt.inspection.classification}; "
                        f"receipt_source={receipt.receipt_source}"
                    )
        return tuple(receipts)

    def final_streamlines_cache_readiness_snapshot(self):
        """Return eight plain receipt projections without filesystem access."""

        snapshots = []
        receipts = getattr(self, "_streamlines_cache_validation_receipts", {})
        tasks = getattr(self, "_streamlines_cache_validation_tasks", {})
        for target in self.resolve_configured_airflow_targets():
            for profile_id in StreamlinesProfileId:
                key = self._streamlines_cache_receipt_key(
                    target.binding,
                    profile_id,
                )
                task = tasks.get(key)
                receipt = receipts.get(key)
                inspection = (
                    receipt.inspection
                    if receipt is not None
                    else SimpleNamespace(
                        classification=(
                            "CHECKING"
                            if task is not None and not task.done()
                            else "UNKNOWN"
                        ),
                        metadata=None,
                    )
                )
                snapshots.append(
                    SimpleNamespace(
                        workload=target.binding.workload_mode,
                        dataset_identity=target.binding.dataset_identity,
                        profile_id=profile_id,
                        inspection=inspection,
                    )
                )
        return tuple(snapshots)

    def streamlines_validation_identity_snapshot(self) -> dict[str, object]:
        """Compute only small metadata/stat identities for restart acceptance."""

        identities = {}
        for target in self.resolve_configured_airflow_targets():
            for profile_id in StreamlinesProfileId:
                ownership = self._streamlines_cache_ownership(
                    target.binding,
                    profile_id,
                )
                paths = streamlines_cache_paths(self.config.repo_root, ownership)
                metadata = load_streamlines_cache_metadata(paths.metadata_path)
                key = self._persisted_streamlines_receipt_key(
                    target.binding,
                    profile_id,
                )
                identities[key] = {
                    "resource_fingerprint": list(
                        streamlines_cache_resource_fingerprint(paths)
                    ),
                    "dependency_identity": list(
                        self._streamlines_cache_dependency_identity(
                            target.binding,
                            target.dataset,
                        )
                    ),
                    "classification": "VALID",
                    "metadata_geometry_sha256": metadata.geometry_sha256,
                }
        return identities

    async def ensure_streamlines_cache_validation_in_background(
        self,
        binding,
        airflow_dataset,
        *,
        profile_id: StreamlinesProfileId | None = None,
        emit_diagnostic: bool = True,
    ) -> StreamlinesCacheValidationReceipt:
        """Deduplicate one target's strong validation and publish its receipt."""

        profile_id = self._resolved_streamlines_profile_id(profile_id)
        key = self._streamlines_cache_receipt_key(binding, profile_id)
        tasks = getattr(self, "_streamlines_cache_validation_tasks", None)
        if tasks is None:
            self.reset_streamlines_cache_validation_receipts()
            tasks = self._streamlines_cache_validation_tasks
        task = tasks.get(key)
        if task is None or task.done():
            previous = self._streamlines_cache_validation_receipts.get(key)
            task = asyncio.create_task(
                asyncio.to_thread(
                    self._validate_streamlines_cache_receipt,
                    binding,
                    airflow_dataset,
                    previous,
                    profile_id,
                )
            )
            tasks[key] = task
        try:
            receipt = await asyncio.shield(task)
        except asyncio.CancelledError:
            raise
        finally:
            if task.done() and tasks.get(key) is task:
                tasks.pop(key, None)
        self._streamlines_cache_validation_receipts[key] = receipt
        if emit_diagnostic:
            self._log_streamlines_cache_validation_receipt(receipt)
        return receipt

    def _streamlines_cache_receipt_snapshot(
        self,
        binding,
        airflow_dataset,
    ) -> StreamlinesCacheInspection:
        """Project one receipt as CHECKING until its async validation completes."""

        del airflow_dataset
        ownership = self._streamlines_cache_ownership(binding)
        paths = streamlines_cache_paths(self.config.repo_root, ownership)
        key = self._streamlines_cache_receipt_key(
            binding,
            self._resolved_streamlines_profile_id(),
        )
        task = getattr(self, "_streamlines_cache_validation_tasks", {}).get(key)
        if task is not None and not task.done():
            return StreamlinesCacheInspection(
                ownership=ownership,
                paths=paths,
                classification="CHECKING",
                message="Cache provenance validation is running.",
            )
        receipt = getattr(
            self,
            "_streamlines_cache_validation_receipts",
            {},
        ).get(key)
        if receipt is not None:
            return receipt.inspection
        return StreamlinesCacheInspection(
            ownership=ownership,
            paths=paths,
            classification="CHECKING",
            message="Cache provenance validation has not started.",
        )

    def _validate_streamlines_cache_receipt(
        self,
        binding,
        airflow_dataset,
        previous: StreamlinesCacheValidationReceipt | None,
        profile_id: StreamlinesProfileId,
    ) -> StreamlinesCacheValidationReceipt:
        """Perform source, metadata, and geometry validation in a worker thread."""

        ownership = self._streamlines_cache_ownership(binding, profile_id)
        paths = streamlines_cache_paths(self.config.repo_root, ownership)
        fingerprint = streamlines_cache_resource_fingerprint(paths)
        try:
            metadata = load_streamlines_cache_metadata(paths.metadata_path)
            dependency = self._streamlines_cache_dependency_identity(
                binding,
                airflow_dataset,
                profile_id,
            )
        except Exception:
            metadata = None
            dependency = ("unavailable", "unavailable")

        if (
            previous is not None
            and previous.resource_fingerprint == fingerprint
            and previous.dependency_identity == dependency
        ):
            store = getattr(self, "_validation_receipt_store", None)
            if store:
                store.record_reuse(
                    "streamlines",
                    previous.receipt_source,
                    self._persisted_streamlines_receipt_key(binding, profile_id),
                )
            return replace(
                previous,
                cache_location="SESSION",
                validation_executed=False,
                geometry_sha256_recomputed=False,
            )

        persisted = self._reuse_persisted_streamlines_receipt(
            binding=binding,
            airflow_dataset=airflow_dataset,
            profile_id=profile_id,
            metadata=metadata,
            paths=paths,
            fingerprint=fingerprint,
            dependency=dependency,
        )
        if persisted is not None:
            return persisted

        store = getattr(self, "_validation_receipt_store", None)
        if store:
            store.record_expensive_validation("streamlines")
        try:
            if metadata is None:
                raise ValueError("Cache metadata is unavailable.")
            expected = self._streamlines_cache_expected_contract(
                binding=binding,
                airflow_dataset=airflow_dataset,
                stage_time_codes_per_second=metadata.time_codes_per_second,
                profile_id=profile_id,
            )
            source = expected["source"]
            settings_signature = expected["settings_signature"]
            compatibility = (
                CACHE_SCHEMA_VERSION,
                source_signature_from_temporal_source(source),
                settings_signature,
            )
        except Exception:
            source = None
            compatibility = (CACHE_SCHEMA_VERSION, "unavailable", "unavailable")

        if source is None:
            try:
                inspection = inspect_streamlines_cache(paths, ownership)
            except ValueError as error:
                inspection = StreamlinesCacheInspection(
                    ownership=ownership,
                    paths=paths,
                    classification="INCOMPATIBLE",
                    message=f"Expected cache contract is unavailable: {error}",
                )
        else:
            inspection = inspect_streamlines_cache(
                paths,
                ownership,
                source=source,
                settings_signature=settings_signature,
            )
        if inspection.valid and inspection.metadata is not None:
            try:
                validate_persisted_constant_topology_cache(
                    paths.geometry_path,
                    inspection.metadata,
                )
                for _chunk in persisted_speed_chunks(
                    paths.geometry_path,
                    inspection.metadata,
                ):
                    pass
            except ImportError:
                pass
            except (OSError, RuntimeError, TypeError, ValueError) as error:
                inspection = replace(
                    inspection,
                    classification="INCOMPATIBLE",
                    message=f"Cache raw speed contract is invalid: {error}",
                )
        receipt = StreamlinesCacheValidationReceipt(
            inspection=inspection,
            resource_fingerprint=fingerprint,
            compatibility_identity=compatibility,
            source=source,
            dependency_identity=dependency,
            receipt_source="FRESH",
            validation_executed=True,
            geometry_sha256_recomputed=(inspection.geometry_sha256_recomputed),
        )
        if store and inspection.geometry_sha256_recomputed:
            store.record_geometry_sha256_recomputed()
        if store:
            store.record_reuse(
                "streamlines",
                "FRESH",
                self._persisted_streamlines_receipt_key(binding, profile_id),
            )
        if inspection.valid and self._reuse_streamlines_receipts_enabled():
            self._persist_streamlines_cache_validation_receipt(
                binding,
                receipt,
                profile_id=profile_id,
            )
        return receipt

    @staticmethod
    def _streamlines_cache_receipt_key(
        binding,
        profile_id: StreamlinesProfileId,
    ) -> tuple[str, str, str]:
        """Keep receipts isolated by their authoritative workload cache owner."""

        return (
            binding.workload_mode,
            binding.dataset_identity,
            profile_id.value,
        )

    @staticmethod
    def _persisted_streamlines_receipt_key(
        binding,
        profile_id: StreamlinesProfileId,
    ) -> str:
        """Format one JSON-safe workload and dataset cache owner."""

        return f"{binding.workload_mode}|{binding.dataset_identity}|{profile_id.value}"

    def _streamlines_cache_dependency_identity(
        self,
        binding,
        airflow_dataset,
        profile_id: StreamlinesProfileId | None = None,
    ) -> tuple[str, str]:
        """Fingerprint VTI inputs and profile without reading VTI payloads."""

        try:
            vti_signature = build_dataset_validation_signature(
                airflow_dataset,
                self.config.simulation_cache.velocity_field_name,
            ).digest
        except (AttributeError, OSError, TypeError, ValueError):
            sources = getattr(self, "_sources", {})
            source = sources.get(binding.workload_mode)
            vti_signature = (
                source_signature_from_temporal_source(source)
                if source is not None
                else "unavailable"
            )
        profile_signature = geometry_contract_signature(
            final_geometry_contract(self._resolved_streamlines_profile_id(profile_id))
        )
        profile_signature += str(getattr(self, "settings_suffix", ""))
        validation_identity = (
            f"{STREAMLINES_VALIDATION_CONTRACT_VERSION}:{profile_signature}"
        )
        return (vti_signature, validation_identity)

    def _reuse_streamlines_receipts_enabled(self) -> bool:
        """Read the opt-in preference without performing receipt work."""

        preferences = getattr(self.config, "validation_receipts", None)
        return bool(
            preferences and preferences.reuse_verified_streamlines_cache_receipts
        )

    def _reuse_persisted_streamlines_receipt(
        self,
        *,
        binding,
        airflow_dataset,
        profile_id: StreamlinesProfileId,
        metadata: StreamlinesCacheMetadata | None,
        paths: StreamlinesCachePaths,
        fingerprint: tuple[str, str],
        dependency: tuple[str, str],
    ) -> StreamlinesCacheValidationReceipt | None:
        """Restore VALID evidence after cheap resource and dependency checks."""

        store = getattr(self, "_validation_receipt_store", None)
        if not self._reuse_streamlines_receipts_enabled() or store is None:
            return None
        if metadata is None:
            return None
        key = self._persisted_streamlines_receipt_key(binding, profile_id)
        lookup = store.lookup_streamlines(
            key=key,
            resource_fingerprint=fingerprint,
            dependency_identity=dependency,
        )
        if lookup.status != "HIT" or lookup.payload is None:
            return None
        try:
            if (
                lookup.payload.get("validation_contract_version")
                != STREAMLINES_VALIDATION_CONTRACT_VERSION
            ):
                store.record_invalidation("streamlines", key)
                return None
            compatibility = tuple(lookup.payload["compatibility_identity"])
            if compatibility != (
                CACHE_SCHEMA_VERSION,
                metadata.source_signature,
                metadata.settings_signature,
            ):
                store.record_invalidation("streamlines", key)
                return None
            source = self._streamlines_source_from_persisted_payload(
                binding,
                airflow_dataset,
                metadata,
                lookup.payload,
            )
            if (
                source_signature_from_temporal_source(source)
                != metadata.source_signature
            ):
                store.record_invalidation("streamlines", key)
                return None
        except (KeyError, TypeError, ValueError) as error:
            store.record_invalidation("streamlines", key)
            carb = self._streamlines_carb_logger()
            if carb:
                carb.log_warn(
                    "DTRS STREAMLINES CACHE VALIDATION | "
                    f"persisted receipt rejected | reason={error}"
                )
            return None
        store.record_reuse("streamlines", "PERSISTED", key)
        return StreamlinesCacheValidationReceipt(
            inspection=StreamlinesCacheInspection(
                ownership=self._streamlines_cache_ownership(binding, profile_id),
                paths=paths,
                classification="VALID",
                message="Persisted strong validation receipt matches resources.",
                metadata=metadata,
            ),
            resource_fingerprint=fingerprint,
            compatibility_identity=(
                int(compatibility[0]),
                str(compatibility[1]),
                str(compatibility[2]),
            ),
            source=source,
            dependency_identity=dependency,
            receipt_source="PERSISTED",
            validation_executed=False,
            geometry_sha256_recomputed=False,
        )

    def _streamlines_source_from_persisted_payload(
        self,
        binding,
        airflow_dataset,
        metadata: StreamlinesCacheMetadata,
        payload: dict[str, object],
    ) -> TemporalVelocitySourceDescriptor:
        """Rebuild plain temporal identity from prior spatial preflight facts."""

        static = payload["static_source"]
        if not isinstance(static, dict):
            raise ValueError("persisted static source is malformed")
        velocity_paths = airflow_dataset.velocity_vti_sequence_paths
        descriptor = StaticVelocitySourceDescriptor(
            workload=binding.workload_mode,
            dataset_identity=binding.dataset_identity,
            sample_index=0,
            vti_path=velocity_paths[0],
            dataset_prim_path=self.STATIC_DATASET_PATH,
            velocity_field_prim_path=(
                f"{self.STATIC_IMPORT_ROOT}/PointData/"
                f"{self.config.simulation_cache.velocity_field_name}"
            ),
            world_bounds=_float_tuple_pair(static["world_bounds"]),
            dimensions=_int_tuple(static["dimensions"], 3),
            spacing=_float_tuple(static["spacing"], 3),
            origin=_float_tuple(static["origin"], 3),
            source_origin=_float_tuple(static["source_origin"], 3),
            stage_meters_per_unit=float(static["stage_meters_per_unit"]),
        )
        return temporal_source_from_airflow_dataset(
            airflow_dataset,
            workload=binding.workload_mode,
            static_descriptor=descriptor,
            time_codes_per_second=metadata.time_codes_per_second,
        )

    def _persist_streamlines_cache_validation_receipt(
        self,
        binding,
        receipt: StreamlinesCacheValidationReceipt,
        *,
        profile_id: StreamlinesProfileId,
    ) -> None:
        """Persist only a fully VALID receipt and its plain reconstruction facts."""

        store = getattr(self, "_validation_receipt_store", None)
        metadata = receipt.inspection.metadata
        source = receipt.source
        if store is None or metadata is None or source is None:
            return
        static = source.static_descriptor
        payload = {
            "validation_contract_version": STREAMLINES_VALIDATION_CONTRACT_VERSION,
            "workload": binding.workload_mode,
            "dataset_identity": binding.dataset_identity,
            "profile_id": profile_id.value,
            "classification": "VALID",
            "resource_fingerprint": list(receipt.resource_fingerprint),
            "dependency_identity": list(receipt.dependency_identity),
            "compatibility_identity": list(receipt.compatibility_identity),
            "geometry_sha256": metadata.geometry_sha256,
            "static_source": {
                "world_bounds": static.world_bounds,
                "dimensions": static.dimensions,
                "spacing": static.spacing,
                "origin": static.origin,
                "source_origin": static.source_origin,
                "stage_meters_per_unit": static.stage_meters_per_unit,
            },
        }
        try:
            store.store_streamlines(
                key=self._persisted_streamlines_receipt_key(binding, profile_id),
                payload=payload,
            )
        except (OSError, TypeError, ValueError) as error:
            carb = self._streamlines_carb_logger()
            if carb:
                carb.log_warn(
                    "DTRS STREAMLINES CACHE VALIDATION | receipt persist failed "
                    f"| workload={binding.workload_mode} | reason={error}"
                )

    def persist_session_streamlines_cache_validation_receipts(self) -> None:
        """Persist only current-session receipts matching current cache resources."""

        if not self._reuse_streamlines_receipts_enabled():
            return
        if getattr(self, "_airflow_dataset_registry_error", None) is not None:
            return
        receipts = getattr(self, "_streamlines_cache_validation_receipts", {})
        for target in self.resolve_configured_airflow_targets():
            for profile_id in StreamlinesProfileId:
                key = self._streamlines_cache_receipt_key(
                    target.binding,
                    profile_id,
                )
                receipt = receipts.get(key)
                if receipt is None or not receipt.inspection.valid:
                    continue
                paths = streamlines_cache_paths(
                    self.config.repo_root,
                    self._streamlines_cache_ownership(target.binding, profile_id),
                )
                resource_fingerprint = streamlines_cache_resource_fingerprint(paths)
                dependency_identity = self._streamlines_cache_dependency_identity(
                    target.binding,
                    target.dataset,
                    profile_id,
                )
                if (
                    receipt.resource_fingerprint != resource_fingerprint
                    or receipt.dependency_identity != dependency_identity
                ):
                    continue
                self._persist_streamlines_cache_validation_receipt(
                    target.binding,
                    receipt,
                    profile_id=profile_id,
                )

    def _log_streamlines_cache_validation_receipt(
        self,
        receipt: StreamlinesCacheValidationReceipt,
    ) -> None:
        """Log whether strong geometry evidence was fresh or reused."""

        carb = self._streamlines_carb_logger()
        if not carb:
            return
        ownership = receipt.inspection.ownership
        event = "REUSED" if not receipt.validation_executed else "VALIDATED"
        getattr(carb, "log_info", carb.log_warn)(
            format_dtrs_diagnostic_block(
                owner="STREAMLINES",
                process="CACHE VALIDATION",
                state=event,
                details={
                    "workload": ownership.workload,
                    "dataset": ownership.dataset_identity,
                    "classification": receipt.inspection.classification,
                    "receipt_source": receipt.receipt_source,
                    "validation_executed": receipt.validation_executed,
                    "geometry_sha256_recomputed": (receipt.geometry_sha256_recomputed),
                },
                append_local_timestamp=with_dtrs_local_timestamp,
            )
        )

    def announce_streamlines_cache_build_ready(self) -> str:
        """Publish cache-build readiness without touching an existing artifact."""

        action = "Build Streamlines Cache"
        ready_header = "DTRS STREAMLINES | CACHE_BUILD | READY"
        message = f'{ready_header}\nNEXT_ACTION | Press "{action}"'
        carb = self._streamlines_carb_logger()
        if carb:
            getattr(carb, "log_info", carb.log_warn)(
                with_dtrs_yerevan_timestamp(message)
            )
        return f'Ready — Press "{action}".'

    def inspect_existing_streamlines_cache(self) -> StreamlinesCacheValidation:
        """Inspect persisted cache provenance without creating a Kit operator."""

        inspection = self.inspect_current_streamlines_cache()
        return StreamlinesCacheValidation(inspection.valid, inspection.message)

    def inspect_current_streamlines_cache(self) -> StreamlinesCacheInspection:
        """Classify the current workload cache without triggering any runtime work."""

        binding, airflow_dataset = self.resolve_current_airflow_dataset()
        return self._inspect_streamlines_cache_for_target(binding, airflow_dataset)

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

        if self._flow_lifecycle_state != "DETACHED":
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
        *,
        profile_id: StreamlinesProfileId | None = None,
    ) -> StreamlinesCacheInspection:
        """Classify one resolved target without introducing a second registry."""

        profile_id = self._resolved_streamlines_profile_id(profile_id)
        ownership = self._streamlines_cache_ownership(binding, profile_id)
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
                profile_id=profile_id,
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

    def _streamlines_cache_ownership(
        self,
        binding,
        profile_id: StreamlinesProfileId | None = None,
    ) -> StreamlinesCacheOwnership:
        """Derive persisted-cache ownership only from the resolved binding."""

        return StreamlinesCacheOwnership(
            workload=binding.workload_mode,
            dataset_identity=binding.dataset_identity,
            profile_id=self._resolved_streamlines_profile_id(profile_id).value,
        )

    def _resolved_streamlines_profile_id(
        self,
        profile_id: StreamlinesProfileId | None = None,
    ) -> StreamlinesProfileId:
        """Resolve an explicit profile or the production-facing preference."""

        if profile_id is not None:
            return StreamlinesProfileId(profile_id)
        preference = getattr(self, "_streamlines_profile_preference", None)
        if preference is None:
            return StreamlinesProfileId.GLOBAL_FLOW_PATH
        return preference.snapshot.preferred_profile

    async def build_streamlines_cache_in_kit(
        self,
        status_callback: StatusCallback | None = None,
        *,
        binding=None,
        airflow_dataset=None,
        profile_id: StreamlinesProfileId | None = None,
        emit_next_action: bool = True,
        emit_runtime_diagnostics: bool = True,
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
        started_at = time.monotonic()
        carb = self._streamlines_carb_logger()
        cleanup = None
        if binding is None or airflow_dataset is None:
            binding, airflow_dataset = self.resolve_current_airflow_dataset()
        profile_id = self._resolved_streamlines_profile_id(profile_id)
        cache_paths = streamlines_cache_paths(
            self.config.repo_root,
            self._streamlines_cache_ownership(binding, profile_id),
        )
        build_mode = streamlines_cache_build_mode(cache_paths)
        self._streamlines_cache_build_active_sample_index = None
        try:
            self._report_streamlines_cache_build(
                event="START",
                message=f"Cache build started: mode={build_mode}.",
                status_callback=status_callback,
                emit_runtime_diagnostics=emit_runtime_diagnostics,
            )
            self._report_streamlines_cache_build(
                event="PROGRESS",
                message="Cache build: preparing manifest temporal source.",
                status_callback=status_callback,
                emit_runtime_diagnostics=emit_runtime_diagnostics,
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
                emit_runtime_diagnostics=emit_runtime_diagnostics,
            )
            metadata, generation_ms = await self._build_cache_geometry_in_kit(
                source,
                cache_paths=cache_paths,
                status_callback=status_callback,
                profile_id=profile_id,
                emit_runtime_diagnostics=emit_runtime_diagnostics,
            )
            cleanup = await self.clear_streamlines_static_runtime_in_kit()
            if not cleanup.clean:
                raise RuntimeError(
                    "Streamlines cleanup was not clean after cache build."
                )
            replace_streamlines_cache_artifacts(cache_paths)
            receipt_key = self._streamlines_cache_receipt_key(binding, profile_id)
            getattr(self, "_streamlines_cache_validation_receipts", {}).pop(
                receipt_key,
                None,
            )
            if carb and emit_runtime_diagnostics:
                getattr(carb, "log_info", carb.log_warn)(
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
            if carb and emit_runtime_diagnostics:
                carb.log_error(with_dtrs_yerevan_timestamp(message))
            self._report_streamlines_cache_build(
                event="FAIL",
                message="Cache build failed; inspect the detailed failure log.",
                status_callback=status_callback,
                emit_runtime_diagnostics=emit_runtime_diagnostics,
            )
            return StreamlinesCacheBuildResult(False, message)

        message = self._format_cache_build_success(
            metadata=metadata,
            cache_paths=cache_paths,
            generation_ms=generation_ms,
            total_ms=(time.monotonic() - started_at) * 1000.0,
        )
        if carb and emit_runtime_diagnostics:
            getattr(carb, "log_info", carb.log_warn)(
                with_dtrs_yerevan_timestamp(message)
            )
        self._report_streamlines_cache_build(
            event="COMPLETE",
            message="Cache build complete and atomically persisted.",
            status_callback=status_callback,
            emit_runtime_diagnostics=emit_runtime_diagnostics,
        )
        self._streamlines_cache_build_active_sample_index = None
        return StreamlinesCacheBuildResult(True, message, metadata)

    async def build_validate_production_cache_set_in_kit(
        self,
        status_callback: StatusCallback | None = None,
        *,
        emit_runtime_diagnostics: bool = True,
    ) -> StreamlinesProductionCacheSetResult:
        """Build only missing/stale workloads after the profile is frozen.

        Every target is independently resolved through the shared dataset
        registry. A failure stops the sequence before any later workload is
        touched, so no unrelated valid cache is rebuilt as collateral work.
        """

        if self._flow_lifecycle_state != "DETACHED":
            raise RuntimeError(
                "Production Streamlines cache build requires Flow DETACHED."
            )

        results: list[StreamlinesProductionCacheResult] = []
        total_targets = len(self.resolve_configured_airflow_targets()) * len(
            tuple(StreamlinesProfileId)
        )
        for target in self.resolve_configured_airflow_targets():
            for profile_id in StreamlinesProfileId:
                binding = target.binding
                dataset = target.dataset
                self._report_phase44b_cache_build(
                    "PROGRESS",
                    f"cache={len(results) + 1}/{total_targets}; "
                    f"workload={binding.workload_mode}; profile={profile_id.value}",
                    status_callback,
                    emit_runtime_diagnostics=emit_runtime_diagnostics,
                )
                started_at = time.monotonic()
                inspection = self._inspect_streamlines_cache_for_target(
                    binding,
                    dataset,
                    profile_id=profile_id,
                )
                temporal_evidence = None
                reused = False
                if inspection.valid and inspection.metadata is not None:
                    metadata = inspection.metadata
                    needs_volume_speed_evidence = (
                        profile_id is StreamlinesProfileId.VOLUME_COVERAGE
                        and isinstance(metadata, StreamlinesCacheMetadata)
                        and getattr(metadata, "speed_evidence", None) is None
                    )
                    paths = streamlines_cache_paths(
                        self.config.repo_root,
                        self._streamlines_cache_ownership(binding, profile_id),
                    )
                    if not needs_volume_speed_evidence:
                        try:
                            temporal_evidence = await asyncio.to_thread(
                                self._inspect_persisted_cache_temporal_geometry,
                                paths.geometry_path,
                                metadata,
                            )
                        except (
                            ImportError,
                            OSError,
                            RuntimeError,
                            TypeError,
                            ValueError,
                        ) as error:
                            return StreamlinesProductionCacheSetResult(
                                success=False,
                                results=tuple(results),
                                failed_workload=binding.workload_mode,
                                message=(
                                    "Persisted Streamlines temporal diagnosis failed: "
                                    f"{error}"
                                ),
                            )
                        reused = temporal_evidence.passed
                if not reused:
                    result = await self.build_streamlines_cache_in_kit(
                        status_callback=status_callback,
                        binding=binding,
                        airflow_dataset=dataset,
                        profile_id=profile_id,
                        emit_next_action=False,
                        emit_runtime_diagnostics=emit_runtime_diagnostics,
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
                        profile_id=profile_id,
                    )
                    if not inspection.valid or inspection.metadata is None:
                        return StreamlinesProductionCacheSetResult(
                            success=False,
                            results=tuple(results),
                            failed_workload=binding.workload_mode,
                            message=(
                                "Built Streamlines cache did not pass final "
                                "validation: "
                                f"{inspection.message}"
                            ),
                        )
                    metadata = inspection.metadata
                    if (
                        profile_id is StreamlinesProfileId.VOLUME_COVERAGE
                        and isinstance(metadata, StreamlinesCacheMetadata)
                        and getattr(metadata, "speed_evidence", None) is None
                    ):
                        return StreamlinesProductionCacheSetResult(
                            success=False,
                            results=tuple(results),
                            failed_workload=binding.workload_mode,
                            message=(
                                "Built Volume Coverage cache is missing speed "
                                "presentation evidence."
                            ),
                        )
                    reused = False
                    temporal_evidence = None
                paths = streamlines_cache_paths(
                    self.config.repo_root,
                    self._streamlines_cache_ownership(binding, profile_id),
                )
                try:
                    if temporal_evidence is None:
                        temporal_evidence = await asyncio.to_thread(
                            self._inspect_persisted_cache_temporal_geometry,
                            paths.geometry_path,
                            metadata,
                        )
                    if not temporal_evidence.passed:
                        raise RuntimeError(
                            "Persisted cache contains no authentic temporal geometry "
                            "changes."
                        )
                    await asyncio.to_thread(
                        validate_persisted_constant_topology_cache,
                        paths.geometry_path,
                        metadata,
                    )
                    await asyncio.to_thread(
                        validate_persisted_speed_cache,
                        paths.geometry_path,
                        metadata,
                    )
                except ImportError:
                    # Pure unit environments do not ship USD; real Kit builds do.
                    pass
                except (OSError, RuntimeError, TypeError, ValueError) as error:
                    return StreamlinesProductionCacheSetResult(
                        success=False,
                        results=tuple(results),
                        failed_workload=binding.workload_mode,
                        message=(
                            "Final Streamlines raw-speed validation failed: " f"{error}"
                        ),
                    )
                results.append(
                    StreamlinesProductionCacheResult(
                        workload=binding.workload_mode,
                        dataset_identity=binding.dataset_identity,
                        profile_id=profile_id.value,
                        reused=reused,
                        metadata=metadata,
                        cache_size_bytes=(
                            paths.geometry_path.stat().st_size
                            + paths.metadata_path.stat().st_size
                        ),
                        total_ms=(time.monotonic() - started_at) * 1000.0,
                    )
                )
        result = StreamlinesProductionCacheSetResult(
            success=True,
            results=tuple(results),
            message="All configured production Streamlines caches are VALID.",
        )
        self._report_phase44b_cache_build(
            "COMPLETE",
            f"{len(results)}/{total_targets} final Streamlines caches are VALID.\n"
            "dtrs:speed=PASS; metadata_profile_identity=PASS.",
            status_callback,
            emit_runtime_diagnostics=emit_runtime_diagnostics,
        )
        return result

    @staticmethod
    def _inspect_persisted_cache_temporal_geometry(
        geometry_path: Path,
        metadata: StreamlinesCacheMetadata,
    ) -> PersistedTemporalGeometryEvidence:
        """Keep matrix liveness separate from generic structural classification."""

        return inspect_persisted_streamlines_temporal_geometry(
            geometry_path,
            metadata,
        )

    async def build_validate_constant_topology_prototype_in_kit(
        self,
        status_callback: StatusCallback | None = None,
    ) -> StreamlinesConstantTopologyPrototypeResult:
        """Build only the Volume Coverage / Nominal renderer-safe prototype."""

        target = next(
            (
                item
                for item in self.resolve_configured_airflow_targets()
                if item.binding.workload_mode == "Nominal"
            ),
            None,
        )
        if target is None:
            return StreamlinesConstantTopologyPrototypeResult(
                False,
                "Nominal authoritative airflow target is unavailable.",
            )
        profile_id = StreamlinesProfileId.VOLUME_COVERAGE
        result = await self.build_streamlines_cache_in_kit(
            status_callback=status_callback,
            binding=target.binding,
            airflow_dataset=target.dataset,
            profile_id=profile_id,
            emit_next_action=False,
        )
        if not result.success or result.metadata is None:
            return StreamlinesConstantTopologyPrototypeResult(
                False,
                result.message,
            )
        receipt = await self.ensure_streamlines_cache_validation_in_background(
            target.binding,
            target.dataset,
            profile_id=profile_id,
        )
        if not receipt.inspection.valid or receipt.inspection.metadata is None:
            return StreamlinesConstantTopologyPrototypeResult(
                False,
                "Constant-topology prototype did not pass strong validation.",
            )
        metadata = receipt.inspection.metadata
        paths = streamlines_cache_paths(
            self.config.repo_root,
            self._streamlines_cache_ownership(target.binding, profile_id),
        )
        proofs = await asyncio.to_thread(
            validate_persisted_constant_topology_cache,
            paths.geometry_path,
            metadata,
            sample_indices=(0, 1, 2, 79),
        )
        if len(proofs) != 4 or not all(proof.passed for proof in proofs):
            return StreamlinesConstantTopologyPrototypeResult(
                False,
                "Representative constant-topology offline proof failed.",
                metadata,
                proofs,
            )
        self._streamlines_constant_topology_prototype_proofs = proofs
        message = (
            "Volume Coverage / Nominal constant-topology cache is VALID; "
            "samples=0,1,2,79; curves=6144; points=122880; "
            "topology_consistent=True."
        )
        return StreamlinesConstantTopologyPrototypeResult(
            True,
            message,
            metadata,
            proofs,
        )

    def _report_phase44b_cache_build(
        self,
        event: str,
        message: str,
        status_callback: StatusCallback | None,
        *,
        emit_runtime_diagnostics: bool = True,
    ) -> None:
        """Emit only bounded profile/workload cache-build acceptance milestones."""

        if status_callback:
            status_callback(message)
        if not emit_runtime_diagnostics or event == "PROGRESS":
            return
        logger = getattr(self, "_streamlines_carb_logger", None)
        if logger is None:
            try:
                import carb
            except ImportError:
                carb = None
        else:
            carb = logger()
        if carb:
            log = (
                carb.log_error
                if event == "FAIL"
                else getattr(carb, "log_info", carb.log_warn)
            )
            log(
                with_dtrs_yerevan_timestamp(
                    f"DTRS STREAMLINES | CACHE_BUILD | {event}\n" f"status={message}"
                )
            )

    async def _build_cache_geometry_in_kit(
        self,
        source: TemporalVelocitySourceDescriptor,
        *,
        cache_paths: StreamlinesCachePaths,
        status_callback: StatusCallback | None,
        profile_id: StreamlinesProfileId,
        emit_runtime_diagnostics: bool,
    ) -> tuple[StreamlinesCacheMetadata, tuple[float, ...]]:
        """Persist every real manifest sample without creating a RuntimePreview."""

        import omni.kit.app
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

        layout = self._streamlines_cache_seed_layout(descriptor, profile_id)
        request = self._build_streamlines_cache_request(
            descriptor,
            profile_id=profile_id,
            layout=layout,
        )
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
        source_counts_attribute = cache_curves.GetPrim().CreateAttribute(
            SOURCE_CURVE_VERTEX_COUNTS_ATTRIBUTE,
            Sdf.ValueTypeNames.IntArray,
            custom=True,
        )
        renderer_topology = renderer_topology_for_profile(profile_id)
        cache_curves.GetCurveVertexCountsAttr().Set(
            list(renderer_topology.curve_vertex_counts)
        )

        previous_target = stage.GetEditTarget()
        states: list[StreamlinesCacheState] = []
        generation_ms: list[float] = []
        volume_speed_accumulator = (
            SpeedDistributionAccumulator()
            if profile_id is StreamlinesProfileId.VOLUME_COVERAGE
            else None
        )
        try:
            stage.SetEditTarget(stage.GetSessionLayer())
            author_streamlines_seed_mesh_in_kit(
                stage,
                layout=layout,
                UsdGeom=UsdGeom,
                seed_path=request.seed_path,
            )
            await app.next_update_async()
            self._start_kit_cae_operator_tracking()
            for sample in manifest_samples(source):
                index = sample.sample_index
                source_vti = sample.source_vti
                self._streamlines_cache_build_active_sample_index = index
                sample_started_at = time.monotonic()
                selected_asset = await self._select_temporal_source_in_kit(
                    app,
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
                if execution.prepared.locked_source_time_code != sample.time_code:
                    raise RuntimeError(
                        "Cache build operator did not lock the manifest source state."
                    )
                if evidence.runtime_curve_bounds is None:
                    raise RuntimeError("Cache build UsdRT geometry has no bounds.")
                if execution.speed_magnitudes is None:
                    raise RuntimeError(
                        "Cache build did not capture raw vertex speed values."
                    )
                if volume_speed_accumulator is not None:
                    volume_speed_accumulator.add(execution.speed_magnitudes)
                padded = pad_streamlines_sample_for_renderer(
                    profile_id=profile_id,
                    points=evidence.runtime_point_positions,
                    curve_vertex_counts=evidence.runtime_curve_vertex_counts,
                    speeds=execution.speed_magnitudes,
                )
                _author_persisted_speed_sample(
                    speed_primvar,
                    padded.speeds,
                    expected_point_count=renderer_topology.point_count,
                    time_code=Usd.TimeCode(sample.time_code),
                )
                time_code = Usd.TimeCode(sample.time_code)
                cache_curves.GetPointsAttr().Set(
                    list(padded.points),
                    time_code,
                )
                source_counts_attribute.Set(
                    list(padded.source_curve_vertex_counts),
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
                        curve_count=renderer_topology.curve_count,
                        point_count=renderer_topology.point_count,
                        topology_signature=cache_topology_signature(
                            renderer_topology.curve_vertex_counts
                        ),
                        geometry_signature=cache_geometry_signature(
                            curve_count=renderer_topology.curve_count,
                            point_count=renderer_topology.point_count,
                            bounds=evidence.runtime_curve_bounds,
                            point_head=padded.points[:8],
                            point_tail=padded.points[-8:],
                        ),
                        generation_ms=elapsed_ms,
                        bounds=evidence.runtime_curve_bounds,
                        source_point_count=evidence.runtime_point_count,
                        source_topology_signature=cache_topology_signature(
                            evidence.runtime_curve_vertex_counts
                        ),
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
                        emit_runtime_diagnostics=emit_runtime_diagnostics,
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
        source_count_time_codes = tuple(
            float(value) for value in source_counts_attribute.GetTimeSamples()
        )
        if source_count_time_codes != expected_time_codes:
            raise RuntimeError(
                "Cache source topology samples do not match the active manifest."
            )
        if cache_curves.GetCurveVertexCountsAttr().GetTimeSamples():
            raise RuntimeError("Renderer curve topology must not be time sampled.")
        if tuple(cache_curves.GetCurveVertexCountsAttr().Get()) != (
            renderer_topology.curve_vertex_counts
        ):
            raise RuntimeError("Renderer curve topology does not match the profile.")
        _validate_persisted_speed_primvar(
            speed_primvar.GetAttr(),
            expected_time_codes=expected_time_codes,
            expected_point_counts=tuple(state.point_count for state in states),
            Usd=Usd,
        )
        cache_stage.GetRootLayer().Save()
        geometry_sha256 = file_sha256(cache_paths.partial_geometry_path)
        speed_evidence = None
        if volume_speed_accumulator is not None:
            speed_evidence = build_streamlines_cache_speed_evidence(
                volume_speed_accumulator
            )
        metadata = build_streamlines_cache_metadata(
            source,
            request,
            states,
            geometry_file_name=cache_paths.geometry_path.name,
            geometry_sha256=geometry_sha256,
            speed_evidence=speed_evidence,
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
        validate_persisted_constant_topology_cache(
            cache_paths.partial_geometry_path,
            staged_metadata,
        )
        temporal_evidence = inspect_persisted_streamlines_temporal_geometry(
            cache_paths.partial_geometry_path,
            metadata,
        )
        if not temporal_evidence.passed:
            raise RuntimeError(
                "Built Streamlines cache contains no authentic temporal geometry "
                "changes."
            )
        cache_paths.partial_metadata_path.write_text(
            serialise_streamlines_cache_metadata(metadata),
            encoding="utf-8",
        )
        return metadata, tuple(generation_ms)

    async def prepare_streamlines_cached_presentation_in_kit(
        self,
        context,
        *,
        status_callback: StatusCallback | None = None,
        cancellation_requested: Callable[[], bool] | None = None,
    ):
        """Prepare the current shared-airflow target through the explicit seam."""

        binding, airflow_dataset = self.resolve_current_airflow_dataset()
        return await self.prepare_streamlines_cached_target_in_kit(
            binding,
            airflow_dataset,
            context.logical_phase_seconds,
            expected_sample_index=context.source_sample_index,
            expected_source_vti=context.source_vti,
            status_callback=status_callback,
            cancellation_requested=cancellation_requested,
        )

    async def prepare_streamlines_cached_target_in_kit(
        self,
        binding,
        airflow_dataset,
        phase_seconds: float,
        *,
        expected_sample_index: int | None = None,
        expected_source_vti: Path | None = None,
        validated_receipt: StreamlinesCacheValidationReceipt | None = None,
        status_callback: StatusCallback | None = None,
        cancellation_requested: Callable[[], bool] | None = None,
    ):
        """Prepare one target's static snapshots at an exact validated phase.

        This is the normal Visualization -> Streamlines preparation seam.  It
        reads only the validated centerline receipt and its persisted USDC; it
        never requires the temporary Mesh prototype, imports VTI, runs Kit-CAE,
        or rebuilds the cache.
        """

        self._raise_if_streamlines_presentation_cancelled(cancellation_requested)
        receipt = validated_receipt
        if receipt is None:
            receipt = await self.ensure_streamlines_cache_validation_in_background(
                binding,
                airflow_dataset,
            )
        self._raise_if_streamlines_presentation_cancelled(cancellation_requested)
        inspection = receipt.inspection
        if inspection.classification != "VALID":
            raise RuntimeError(
                "Streamlines cache is "
                f"{inspection.classification}: {inspection.message}"
            )
        metadata = inspection.metadata
        if metadata is None:
            raise RuntimeError("Validated Streamlines cache receipt lacks metadata.")
        if receipt.source is None:
            raise RuntimeError("Validated Streamlines cache receipt lacks a source.")
        cache_paths = inspection.paths
        if not cache_paths.geometry_path.is_file():
            raise RuntimeError("Validated Streamlines centerline geometry is missing.")
        contract = cached_playback_contract_from_validated_cache(
            metadata,
            receipt.source,
        )
        if (
            contract.workload != binding.workload_mode
            or contract.dataset_identity != binding.dataset_identity
            or contract.profile_id != metadata.profile_id
        ):
            raise RuntimeError("Prepared Streamlines cache target identity drifted.")
        resolution = resolve_cached_playback_state(
            contract,
            phase_seconds,
            active_sample_index=None,
        )
        sample_index_matches = (
            expected_sample_index is None
            or resolution.sample.sample_index == expected_sample_index
        )
        source_vti_matches = (
            expected_source_vti is None
            or resolution.sample.source_vti.resolve() == expected_source_vti.resolve()
        )
        if not sample_index_matches or not source_vti_matches:
            raise RuntimeError(
                "Prepared Streamlines sample does not match the requested "
                "target phase identity."
            )
        if status_callback:
            status_callback(
                "Valid persisted centerline cache accepted; preparing "
                "production snapshots."
            )

        import omni.usd

        stage = omni.usd.get_context().get_stage()
        if stage is None:
            raise RuntimeError(
                "Streamlines snapshot preparation requires an open stage."
            )
        await self.stop_streamlines_cached_playback_in_kit()
        self._clear_streamlines_cache_load_state(stage)
        try:
            self._streamlines_loaded_cache_metadata = metadata
            self._streamlines_loaded_cache_paths = cache_paths
            self._streamlines_cache_playback_contract = contract
            self._streamlines_cache_active_sample_index = None
            self._raise_if_streamlines_presentation_cancelled(cancellation_requested)
            self.prepare_streamlines_snapshots_in_kit(
                metadata,
                cache_paths.geometry_path,
            )
            self._raise_if_streamlines_presentation_cancelled(cancellation_requested)
            self._require_streamlines_snapshot_contract_ownership(contract)
            material = self.apply_streamlines_presentation_in_kit()
            if material.snapshot_count != contract.sample_count:
                raise RuntimeError(
                    "Static snapshot material did not bind every cache state."
                )
            if not self.set_streamlines_cached_presentation_visible_in_kit(False):
                raise RuntimeError(
                    "Prepared snapshot presentation could not be hidden."
                )
            self.select_streamlines_snapshot_state_in_kit(
                resolution.sample.sample_index
            )
            if self.streamlines_snapshot_visible_count_in_kit() != 1:
                raise RuntimeError("Prepared snapshots did not select one real state.")
            self._raise_if_streamlines_presentation_cancelled(cancellation_requested)
            return resolution
        except BaseException:
            self._clear_streamlines_cache_load_state(stage)
            raise

    async def cleanup_streamlines_cached_presentation_in_kit(self) -> None:
        """Stop one scheduler and remove the DTRS-owned snapshot presentation."""

        import omni.kit.app
        import omni.usd

        await self.stop_streamlines_cached_playback_in_kit()
        stage = omni.usd.get_context().get_stage()
        if stage:
            self._clear_streamlines_cache_load_state(stage)
            await omni.kit.app.get_app().next_update_async()
        self._streamlines_cached_presentation_visible = False

    def cancel_streamlines_cached_presentation_in_kit(self) -> None:
        """Synchronously cancel scheduler and cache ownership during shutdown."""

        import omni.usd

        self.cancel_streamlines_cached_playback()
        stage = omni.usd.get_context().get_stage()
        if stage:
            self._clear_streamlines_cache_load_state(stage)
        self._streamlines_cached_presentation_visible = False

    def set_streamlines_cached_presentation_visible_in_kit(self, visible: bool) -> bool:
        """Show or hide the snapshot hierarchy without changing selected state."""

        import omni.usd
        from pxr import UsdGeom

        stage = omni.usd.get_context().get_stage()
        from digital_twin_runtime_suite.app.streamlines.snapshot_runtime import (
            SNAPSHOTS_ROOT_PATH,
        )

        root = stage.GetPrimAtPath(SNAPSHOTS_ROOT_PATH) if stage else None
        if (
            not root
            or not root.IsValid()
            or getattr(self, "_streamlines_snapshot_set_ownership", None) is None
        ):
            return False
        previous_target = stage.GetEditTarget()
        stage.SetEditTarget(stage.GetSessionLayer())
        try:
            UsdGeom.Imageable(root).CreateVisibilityAttr().Set(
                UsdGeom.Tokens.inherited if visible else UsdGeom.Tokens.invisible
            )
        finally:
            stage.SetEditTarget(previous_target)
        self._streamlines_cached_presentation_visible = visible
        return True

    def streamlines_cached_presentation_is_visible_in_kit(self) -> bool:
        """Report root visibility only when one static snapshot remains selected."""

        import omni.usd
        from pxr import UsdGeom

        stage = omni.usd.get_context().get_stage()
        from digital_twin_runtime_suite.app.streamlines.snapshot_runtime import (
            SNAPSHOTS_ROOT_PATH,
        )

        root = stage.GetPrimAtPath(SNAPSHOTS_ROOT_PATH) if stage else None
        if not root or not root.IsValid():
            return False
        return (
            UsdGeom.Imageable(root).ComputeVisibility() != UsdGeom.Tokens.invisible
            and self.streamlines_snapshot_visible_count_in_kit() == 1
        )

    def streamlines_cached_presentation_is_prepared_in_kit(self) -> bool:
        """Report a valid snapshot set even when the presentation root is hidden."""

        import omni.usd

        stage = omni.usd.get_context().get_stage()
        from digital_twin_runtime_suite.app.streamlines.snapshot_runtime import (
            SNAPSHOTS_ROOT_PATH,
        )

        root = stage.GetPrimAtPath(SNAPSHOTS_ROOT_PATH) if stage else None
        return bool(
            root
            and root.IsValid()
            and getattr(self, "_streamlines_snapshot_set_ownership", None) is not None
        )

    def _clear_streamlines_cache_load_state(self, stage) -> None:
        """Remove snapshots before clearing every playback-facing reference."""

        cleanup_snapshots = getattr(
            self,
            "cleanup_streamlines_snapshots_in_kit",
            None,
        )
        if callable(cleanup_snapshots):
            cleanup_snapshots()
        self._streamlines_loaded_cache_metadata = None
        self._streamlines_loaded_cache_paths = None
        self._streamlines_cache_playback_contract = None
        self._streamlines_cache_active_sample_index = None

    def _streamlines_cache_expected_contract(
        self,
        *,
        binding,
        airflow_dataset,
        stage_time_codes_per_second: float,
        profile_id: StreamlinesProfileId | None = None,
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
        profile_id = self._resolved_streamlines_profile_id(profile_id)
        request = self._build_streamlines_cache_request(
            descriptor,
            profile_id=profile_id,
        )
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
        *,
        profile_id: StreamlinesProfileId | None = None,
        layout=None,
    ) -> StreamlinesOperatorRequest:
        """Derive one frozen profile request from VTI data, not UI state."""

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
        profile_id = (
            DEFAULT_STREAMLINES_PROFILE
            if self is None and profile_id is None
            else (
                StreamlinesProfileId(profile_id or DEFAULT_STREAMLINES_PROFILE)
                if self is None
                else self._resolved_streamlines_profile_id(profile_id)
            )
        )
        if layout is None:
            layout = StreamlinesCacheRuntimeMixin._streamlines_cache_seed_layout(
                canonical_descriptor,
                profile_id,
            )
        geometry = final_geometry_contract(profile_id)
        return replace(
            build_streamlines_seeded_operator_request(
                canonical_descriptor,
                layout,
                geometry_contract=geometry,
            ),
            operator_path=CACHE_BUILD_OPERATOR_PATH,
            seed_path=CACHE_BUILD_SEED_PATH,
            operator_type="standard",
        )

    @staticmethod
    def _streamlines_cache_seed_layout(
        descriptor: StaticVelocitySourceDescriptor,
        profile_id: StreamlinesProfileId,
    ):
        """Derive the frozen deterministic point-grid for one cache profile."""

        minimum = tuple(float(value) for value in descriptor.source_origin)
        maximum = tuple(
            minimum[index]
            + ((descriptor.dimensions[index] - 1) * descriptor.spacing[index])
            for index in range(3)
        )
        contract = final_geometry_contract(profile_id)
        bounds = (minimum, maximum)
        if profile_id is StreamlinesProfileId.VOLUME_COVERAGE:
            return derive_volume_coverage_layout(
                bounds,
                section_count=contract.section_count,
                seeds_per_section=contract.seed_count,
            )
        return derive_global_flow_path_layout(
            bounds,
            front_intake_z=maximum[2],
            max_cell_spacing=max(descriptor.spacing),
            seed_count=contract.seed_count,
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

    def _report_streamlines_cache_build(
        self,
        *,
        event: str,
        message: str,
        status_callback: StatusCallback | None,
        emit_runtime_diagnostics: bool = True,
    ) -> None:
        """Expose deterministic cache-build progress without tick-level noise."""

        if status_callback:
            status_callback(message)
        if not emit_runtime_diagnostics or event == "PROGRESS":
            return
        carb = self._streamlines_carb_logger()
        if not carb:
            return
        log = (
            carb.log_error
            if event == "FAIL"
            else getattr(carb, "log_info", carb.log_warn)
        )
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
            log = (
                carb.log_error
                if event == "FAIL"
                else getattr(carb, "log_info", carb.log_warn)
            )
            log(
                with_dtrs_yerevan_timestamp(
                    f"DTRS STREAMLINES | PRODUCTION_PROFILE | {event}\n"
                    f"status={message}"
                )
            )

    @staticmethod
    def _raise_if_streamlines_presentation_cancelled(
        cancellation_requested: Callable[[], bool] | None,
    ) -> None:
        """Reject stale candidate work before it can mutate presentation state."""

        if cancellation_requested and cancellation_requested():
            raise StreamlinesPresentationCancelled(
                "Streamlines presentation request was superseded or cancelled."
            )

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
                "Persisted centerline cache validation passed.",
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
