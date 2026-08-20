"""Kit-facing VTI import and exact temporal-source selection for Streamlines."""

from __future__ import annotations

import time
from typing import Callable

from digital_twin_runtime_suite.app.airflow_dataset import AirflowDataset
from digital_twin_runtime_suite.app.diagnostics import with_dtrs_local_timestamp
from digital_twin_runtime_suite.app.flow import temporal as flow_temporal
from digital_twin_runtime_suite.app.flow.static_source import (
    StaticVelocitySourceDescriptor,
    clear_static_velocity_source_from_stage,
    describe_imported_static_velocity_source,
    resolve_static_velocity_sample_from_airflow_dataset,
)
from digital_twin_runtime_suite.app.status_log import (
    format_dtrs_diagnostic_block,
    format_dtrs_status_block,
)
from digital_twin_runtime_suite.app.streamlines.diagnostics import (
    format_static_source_acceptance,
    inspect_static_source_runtime,
    require_clean_static_source_runtime,
)
from digital_twin_runtime_suite.app.streamlines.temporal import (
    TemporalSourceSample,
    TemporalVelocitySourceDescriptor,
    temporal_source_from_airflow_dataset,
)
from digital_twin_runtime_suite.app.workload_binding.runtime import (
    WorkloadAirflowBinding,
)

StatusCallback = Callable[[str], None]


class StreamlinesSourceRuntimeMixin:
    """Own Kit VTI import and exact manifest-source selection."""

    async def prepare_streamlines_temporal_velocity_source_in_kit(
        self,
        *,
        status_callback: StatusCallback | None = None,
        binding: WorkloadAirflowBinding | None = None,
        airflow_dataset: AirflowDataset | None = None,
        emit_runtime_diagnostics: bool = True,
    ) -> TemporalVelocitySourceDescriptor:
        """Author the shared ``vel.fileNames`` time-sample source for Streamlines.

        The first VTI is imported once through the spatial-validation seam. All
        remaining real VTI files are selected by USD time codes on that same
        imported ``vel`` field, matching the accepted DTRS temporal mechanism.
        """

        if binding is None:
            binding, resolved_dataset = self.resolve_current_airflow_dataset()
            airflow_dataset = airflow_dataset or resolved_dataset
        if airflow_dataset is None:
            airflow_dataset = self.resolve_airflow_dataset_for_binding(binding)
        descriptor = await self.prepare_static_velocity_sample_in_kit(
            sample_index=0,
            status_callback=status_callback,
            binding=binding,
            airflow_dataset=airflow_dataset,
            emit_runtime_diagnostics=emit_runtime_diagnostics,
        )
        if (
            descriptor.workload != binding.workload_mode
            or descriptor.dataset_identity != binding.dataset_identity
        ):
            raise RuntimeError(
                "Telemetry workload changed while the temporal Streamlines source was "
                "being prepared; retry from a stable workload."
            )
        velocity_paths = airflow_dataset.velocity_vti_sequence_paths

        import omni.kit.app
        import omni.usd
        from omni.cae.schema import vtk as cae_vtk
        from pxr import Sdf, Usd

        app = omni.kit.app.get_app()
        stage = omni.usd.get_context().get_stage()
        if not stage:
            raise RuntimeError("Temporal Streamlines source requires an open stage.")
        field_prim = stage.GetPrimAtPath(descriptor.velocity_field_prim_path)
        if not field_prim or not field_prim.IsValid():
            raise RuntimeError(
                "Accepted static velocity field is unavailable for temporal authoring."
            )
        if status_callback:
            status_callback(
                f"Authoring temporal source: {len(velocity_paths)} manifest samples"
            )
        previous_target = stage.GetEditTarget()
        try:
            session_layer = stage.GetSessionLayer()
            session_layer.timeCodesPerSecond = float(stage.GetTimeCodesPerSecond())
            stage.SetEditTarget(session_layer)
            author_samples = (
                flow_temporal.author_kit_cae_temporal_velocity_samples_in_batches
            )
            time_codes = await author_samples(
                field_prim,
                velocity_paths,
                float(stage.GetTimeCodesPerSecond()),
                airflow_dataset.sample_interval_seconds,
                cae_vtk,
                Sdf,
                Usd,
                app.next_update_async,
                self.TEMPORAL_AUTHORING_BATCH_SIZE,
            )
        finally:
            stage.SetEditTarget(previous_target)
        await app.next_update_async()
        expected_source = temporal_source_from_airflow_dataset(
            airflow_dataset,
            workload=binding.workload_mode,
            static_descriptor=descriptor,
            time_codes_per_second=float(stage.GetTimeCodesPerSecond()),
        )
        if time_codes != expected_source.sample_time_codes:
            raise RuntimeError(
                "Kit temporal source time codes do not match the active manifest."
            )
        source = expected_source
        if (
            len(
                flow_temporal.kit_cae_file_names_time_samples(
                    field_prim,
                    cae_vtk,
                    Usd,
                )
            )
            != source.sample_count
        ):
            raise RuntimeError(
                "Temporal Streamlines field did not retain every manifest time sample."
            )
        self._streamlines_temporal_source_descriptor = source
        return source

    @staticmethod
    async def _select_temporal_source_in_kit(
        app,
        *,
        field_prim,
        sample: TemporalSourceSample,
        cae_vtk,
        Usd,
    ):
        """Select and verify one real manifest VTI before touching its consumer."""

        # The persisted manifest is read at its explicit source time code; this
        # source helper never owns Kit's global timeline.
        await app.next_update_async()
        await app.next_update_async()
        selected_asset = flow_temporal.kit_cae_selected_velocity_asset(
            field_prim,
            sample.time_code,
            cae_vtk,
            Usd,
        )
        expected_asset = sample.source_vti.resolve()
        if selected_asset is None or selected_asset.resolve() != expected_asset:
            raise RuntimeError(
                "Temporal field selected a different source VTI: "
                f"expected={expected_asset}, actual={selected_asset}."
            )
        return selected_asset

    async def prepare_static_velocity_sample_in_kit(
        self,
        sample_index: int = 0,
        status_callback: StatusCallback | None = None,
        *,
        force_failure_after_import: bool = False,
        binding: WorkloadAirflowBinding | None = None,
        airflow_dataset: AirflowDataset | None = None,
        emit_runtime_diagnostics: bool = True,
    ) -> StaticVelocitySourceDescriptor:
        """Resolve, import, and spatially validate one manifest-backed VTI sample.

        This is source preparation rather than a partial Flow Attach. It reuses
        the accepted Stage 6 origin compatibility shim because the current VTK
        importer does not retain the Houdini ImageData origin by itself.
        """

        if binding is None:
            binding, resolved_dataset = self.resolve_current_airflow_dataset()
            airflow_dataset = airflow_dataset or resolved_dataset
        if airflow_dataset is None:
            airflow_dataset = self.resolve_airflow_dataset_for_binding(binding)
        cache = self.config.simulation_cache
        sample = resolve_static_velocity_sample_from_airflow_dataset(
            airflow_dataset,
            binding,
            cache.velocity_field_name,
            sample_index,
        )
        if status_callback:
            status_callback(
                f"Preparing Streamlines source: {sample.dataset_identity}; "
                f"VTI {sample.sample_index}"
            )

        import carb
        import omni.kit.app
        import omni.usd
        from omni.cae.importer.vtk import import_to_stage
        from omni.cae.schema import cae
        from omni.cae.schema import vtk as cae_vtk
        from pxr import Gf, UsdGeom

        app = omni.kit.app.get_app()
        extension_manager = app.get_extension_manager()
        required_extensions = (
            "omni.cae.delegate.vtk",
            "omni.cae.importer.vtk",
        )
        disabled_extensions = [
            extension_id
            for extension_id in required_extensions
            if not extension_manager.is_extension_enabled(extension_id)
        ]
        if disabled_extensions:
            raise RuntimeError(
                "Kit-CAE static VTI import is unavailable; start DTRS through "
                "start_dtrs.bat with these extensions enabled: "
                f"{', '.join(disabled_extensions)}."
            )

        stage = omni.usd.get_context().get_stage()
        if not stage:
            raise RuntimeError("Static source preparation requires an open stage.")
        velocity_field_name = sample.velocity_field_name
        field_path = f"{self.STATIC_IMPORT_ROOT}/PointData/{velocity_field_name}"
        cleanup = clear_static_velocity_source_from_stage(
            stage, self.STATIC_IMPORT_ROOT
        )
        if not cleanup.success:
            raise RuntimeError(
                "Previous static source cleanup did not remove its runtime prim."
            )
        await app.next_update_async()
        self._streamlines_static_source_descriptor = None
        self._streamlines_static_source_diagnostics_failure = None
        import_started_at = time.monotonic()
        try:
            await import_to_stage(str(sample.vti_path), self.STATIC_IMPORT_ROOT)
            await app.next_update_async()
            if emit_runtime_diagnostics:
                import_duration_ms = (time.monotonic() - import_started_at) * 1000.0
                carb.log_warn(
                    format_dtrs_diagnostic_block(
                        owner="STREAMLINES",
                        process="VTI IMPORT",
                        state="PASS",
                        details={"duration_ms": f"{import_duration_ms:.0f}"},
                        append_local_timestamp=with_dtrs_local_timestamp,
                    )
                )

            dataset_prim = stage.GetPrimAtPath(self.STATIC_DATASET_PATH)
            field_prim = stage.GetPrimAtPath(field_path)
            spatial_started_at = time.monotonic()
            previous_target = stage.GetEditTarget()
            stage.SetEditTarget(stage.GetSessionLayer())
            try:
                self._author_kit_cae_vti_origin_session_opinion(
                    dataset_prim,
                    sample.source_origin,
                    cae_vtk,
                    Gf,
                )
            finally:
                stage.SetEditTarget(previous_target)
            await app.next_update_async()
            imported_grid = self._validate_kit_cae_velocity_field(
                dataset_prim,
                field_prim,
                {
                    "dimensions": sample.dimensions,
                    "spacing": sample.spacing,
                },
                cae,
                cae_vtk,
            )
            descriptor = describe_imported_static_velocity_source(
                sample,
                dataset_prim_path=self.STATIC_DATASET_PATH,
                velocity_field_prim_path=field_path,
                imported_grid=imported_grid,
                stage_meters_per_unit=float(UsdGeom.GetStageMetersPerUnit(stage)),
            )
            if emit_runtime_diagnostics:
                spatial_duration_ms = (time.monotonic() - spatial_started_at) * 1000.0
                carb.log_warn(
                    format_dtrs_diagnostic_block(
                        owner="STREAMLINES",
                        process="SPATIAL VALIDATION",
                        state="PASS",
                        details={"duration_ms": f"{spatial_duration_ms:.0f}"},
                        append_local_timestamp=with_dtrs_local_timestamp,
                    )
                )
            evidence = inspect_static_source_runtime(
                stage,
                import_root_path=self.STATIC_IMPORT_ROOT,
                field_prim=field_prim,
                cae_vtk=cae_vtk,
            )
            require_clean_static_source_runtime(evidence)
            if emit_runtime_diagnostics:
                try:
                    carb.log_warn(
                        format_dtrs_status_block(
                            format_static_source_acceptance(
                                descriptor,
                                cleanup,
                                evidence,
                            ),
                            append_local_timestamp=with_dtrs_local_timestamp,
                        )
                    )
                except Exception as error:
                    # Evidence is required for acceptance, but a diagnostic failure
                    # must not discard the already validated reusable source.
                    diagnostic_reason = (
                        " ".join(str(error).splitlines()) or type(error).__name__
                    )
                    self._streamlines_static_source_diagnostics_failure = (
                        diagnostic_reason
                    )
                    try:
                        carb.log_error(
                            format_dtrs_diagnostic_block(
                                owner="STREAMLINES",
                                process="SOURCE DIAGNOSTICS",
                                state="FAIL",
                                details={"reason": diagnostic_reason},
                                append_local_timestamp=with_dtrs_local_timestamp,
                            )
                        )
                    except Exception:
                        # A failed secondary log sink must not discard the source
                        # descriptor already validated above.
                        self._streamlines_static_source_diagnostics_failure = (
                            diagnostic_reason
                        )
            self._streamlines_static_source_descriptor = descriptor
            if force_failure_after_import:
                raise RuntimeError("Forced velocity-source failure after import.")
        except Exception:
            self._streamlines_static_source_descriptor = None
            clear_static_velocity_source_from_stage(stage, self.STATIC_IMPORT_ROOT)
            raise

        if status_callback:
            status_callback(
                f"Static source ready: {descriptor.dataset_identity}; "
                f"VTI {descriptor.sample_index}"
            )
        return descriptor
