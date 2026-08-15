"""Attached workload-to-airflow transition orchestration."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from digital_twin_runtime_suite.app.airflow_dataset import (
    AirflowDatasetError,
    discover_airflow_dataset,
    discover_airflow_dataset_registry,
)
from digital_twin_runtime_suite.app.airflow_validation import family as airflow_family
from digital_twin_runtime_suite.app.airflow_validation.cache import (
    build_dataset_validation_signature,
)
from digital_twin_runtime_suite.app.diagnostics import with_dtrs_local_timestamp
from digital_twin_runtime_suite.app.flow import temporal as flow_temporal
from digital_twin_runtime_suite.app.flow import validation as flow_validation
from digital_twin_runtime_suite.app.flow.runtime import SimulationCacheResult
from digital_twin_runtime_suite.app.workload_binding import BackgroundValidationError

StatusCallback = Callable[[str], None]
AirflowDatasetFamilyCompatibilityError = (
    airflow_family.AirflowDatasetFamilyCompatibilityError
)


class AttachedWorkloadTransitionMixin:
    """Own Stage 8 in-place selector transition state and proof gates."""

    async def request_attached_workload_transition_in_kit(
        self,
        workload_mode: str,
        status_callback: StatusCallback | None = None,
    ) -> SimulationCacheResult:
        """Request an in-place transition from active to semantic workload airflow.

        Telemetry has already accepted ``workload_mode`` before this consumer
        runs.  Until live Kit-CAE consumption proves the target, the confirmed
        active selector remains visible and the requested selector is pending.
        Transition IDs make every async checkpoint reject a superseded request;
        this method never attaches, detaches, resets, or rebuilds Flow.
        """

        if self._flow_lifecycle_state != "ATTACHED":
            return SimulationCacheResult(
                True, "Flow remains detached; no airflow transition requested."
            )

        import carb

        active_binding = self._flow_session_workload_binding
        target_binding = self.resolve_workload_airflow_binding(workload_mode)
        if active_binding is None:
            return SimulationCacheResult(
                False, "Attached Flow has no active airflow selector."
            )
        pending_binding = self._flow_pending_workload_binding
        if pending_binding is not None:
            if pending_binding.dataset_identity == target_binding.dataset_identity:
                return SimulationCacheResult(
                    True,
                    "Airflow transition already targets the current workload.",
                )
            self._flow_transition_sequence += 1
            transition_id = f"T{self._flow_transition_sequence:04d}"
            superseded_transition_id = self._flow_active_transition_id or "unknown"
            self._flow_active_transition_id = transition_id
            self._flow_pending_workload_binding = target_binding
            carb.log_warn(
                self._format_airflow_transition_log_block(
                    "SUPERSEDED",
                    (
                        ("Transition:", superseded_transition_id),
                        ("Target:", pending_binding.dataset_identity),
                        ("Superseded by transition:", transition_id),
                        ("New target:", target_binding.dataset_identity),
                        ("Last committed active:", active_binding.dataset_identity),
                        ("Old commit allowed:", False),
                    ),
                )
            )
            if target_binding.dataset_identity == active_binding.dataset_identity:
                self._flow_pending_workload_binding = None
                self._flow_active_transition_id = None
                return SimulationCacheResult(
                    True,
                    "Attached airflow already matches the latest workload.",
                )
        if target_binding.dataset_identity == active_binding.dataset_identity:
            self._flow_pending_workload_binding = None
            return SimulationCacheResult(
                True, "Attached airflow already matches workload."
            )

        if pending_binding is None:
            self._flow_transition_sequence += 1
            transition_id = f"T{self._flow_transition_sequence:04d}"
            self._flow_active_transition_id = transition_id
        self._flow_pending_workload_binding = target_binding
        proof_superseded = self._cancel_kit_cae_temporal_proof(
            reason="SUPERSEDED_BY_WORKLOAD_TRANSITION"
        )
        carb.log_warn(
            self._format_airflow_transition_log_block(
                "REQUEST",
                (
                    ("Transition:", transition_id),
                    ("Semantic workload:", workload_mode),
                    ("Active airflow:", active_binding.dataset_identity),
                    ("Target airflow:", target_binding.dataset_identity),
                    ("Pending airflow:", target_binding.dataset_identity),
                    (
                        "Temporal proof state:",
                        "CANCELLED" if proof_superseded else "UNCHANGED",
                    ),
                    (
                        "Temporal proof reason:",
                        "WORKLOAD_TRANSITION" if proof_superseded else "not_running",
                    ),
                ),
            )
        )
        try:
            target_dataset = discover_airflow_dataset(
                self.config.asset_root, target_binding.dataset
            )
            signature = build_dataset_validation_signature(
                target_dataset, self.config.simulation_cache.velocity_field_name
            )
            validation_was_hit = bool(
                self._flow_validation_cache.lookup(signature).preflight
            )
        except AirflowDatasetError as error:
            return self._finalize_airflow_failure(
                semantic_workload=workload_mode,
                requested_binding=target_binding,
                reason=str(error),
                failure_stage="dataset_discovery",
                logger=carb.log_error,
                status_callback=status_callback,
            )
        except RuntimeError as error:
            return self._finalize_airflow_failure(
                semantic_workload=workload_mode,
                requested_binding=target_binding,
                reason=str(error),
                failure_stage="validation_signature",
                logger=carb.log_error,
                status_callback=status_callback,
            )
        try:
            lease = await self.acquire_airflow_validation_for_transition(target_binding)
        except BackgroundValidationError as error:
            if not self._is_current_airflow_transition(transition_id, target_binding):
                return self._superseded_transition_result(transition_id, target_binding)
            return self._finalize_airflow_failure(
                semantic_workload=workload_mode,
                requested_binding=target_binding,
                reason=str(error),
                failure_stage="validation",
                logger=carb.log_error,
                status_callback=status_callback,
                transition_id=transition_id,
            )
        receipt = lease.receipt
        lease.release()
        if not self._is_current_airflow_transition(transition_id, target_binding):
            return self._superseded_transition_result(transition_id, target_binding)
        try:
            family = self.validate_registered_airflow_dataset_family()
            if not family.family_compatible:
                raise AirflowDatasetFamilyCompatibilityError(
                    "Airflow family compatibility mismatch: dataset=family; "
                    "property=family_compatible; expected=True; actual=False."
                )
        except (
            AirflowDatasetError,
            AirflowDatasetFamilyCompatibilityError,
            RuntimeError,
        ) as error:
            carb.log_error(
                self._format_airflow_transition_log_block(
                    "FAMILY COMPATIBILITY",
                    (
                        ("Transition:", transition_id),
                        ("Active:", active_binding.dataset_identity),
                        ("Target:", target_binding.dataset_identity),
                        ("Family compatible:", False),
                        ("Reason:", str(error)),
                    ),
                )
            )
            return self._finalize_airflow_failure(
                semantic_workload=workload_mode,
                requested_binding=target_binding,
                reason=str(error),
                failure_stage="family_compatibility",
                logger=carb.log_error,
                status_callback=status_callback,
                transition_id=transition_id,
            )
        carb.log_warn(
            self._format_airflow_transition_log_block(
                "FAMILY COMPATIBILITY",
                (
                    ("Transition:", transition_id),
                    ("Active:", active_binding.dataset_identity),
                    ("Target:", target_binding.dataset_identity),
                    ("Members:", ", ".join(family.member_selectors)),
                    ("Family compatible:", family.family_compatible),
                    ("Phase mapping:", family.phase_mapping),
                    ("VTI preflight:", "REUSED"),
                    ("RESULT:", "PASS"),
                ),
            )
        )
        carb.log_warn(
            self._format_airflow_transition_log_block(
                "READY",
                (
                    ("Transition:", transition_id),
                    ("Target:", target_binding.dataset_identity),
                    ("Validation:", "REUSED" if validation_was_hit else "PASS"),
                    ("Receipt:", receipt.signature.compact_digest),
                    ("Pending airflow:", target_binding.dataset_identity),
                    ("Waiting for sample boundary:", True),
                ),
            )
        )
        result = await self._retarget_attached_workload_in_kit(
            active_binding,
            target_binding,
            target_dataset,
            status_callback,
            transition_id,
        )
        if result.success:
            return result
        if not self._is_current_airflow_transition(transition_id, target_binding):
            return self._superseded_transition_result(transition_id, target_binding)
        if self._is_current_airflow_transition(transition_id, target_binding):
            return self._finalize_airflow_failure(
                semantic_workload=workload_mode,
                requested_binding=target_binding,
                reason=result.message,
                failure_stage="runtime_transition",
                logger=carb.log_error,
                status_callback=status_callback,
                transition_id=transition_id,
            )
        return result

    async def _retarget_attached_workload_in_kit(
        self,
        active_binding,
        target_binding,
        target_dataset,
        status_callback: StatusCallback | None,
        transition_id: str,
    ) -> SimulationCacheResult:
        """Retarget at a sample boundary and commit only after runtime proof.

        The target sample is selected through normalized phase mapping, then
        authored as a session-layer FieldArray override.  Kit-CAE is allowed to
        consume that change naturally on its next temporal update—forced CAE
        refresh is deliberately avoided here because it can re-enter VTK.  The
        direct-Attach velocity-scale contract is applied and read back before
        the pending selector becomes active.
        """

        import carb
        import omni.kit.app
        import omni.timeline
        import omni.usd
        from omni.cae.schema import vtk as cae_vtk
        from pxr import Sdf, Usd

        if not self._is_current_airflow_transition(transition_id, target_binding):
            return self._superseded_transition_result(transition_id, target_binding)
        cache = self.config.simulation_cache
        stage = omni.usd.get_context().get_stage()
        timeline = omni.timeline.get_timeline_interface()
        field_prim = (
            stage.GetPrimAtPath(
                f"/DTRS_HoudiniVelocity/PointData/{cache.velocity_field_name}"
            )
            if stage
            else None
        )
        emitter_prim = (
            stage.GetPrimAtPath("/DTRS_KitCAE/DataSetEmitter") if stage else None
        )
        if not all(prim and prim.IsValid() for prim in (field_prim, emitter_prim)):
            return SimulationCacheResult(
                False, "Attached airflow runtime objects are unavailable."
            )
        try:
            active_dataset = discover_airflow_dataset(
                self.config.asset_root, active_binding.dataset
            )
            active_time_code = (
                float(timeline.get_current_time()) * stage.GetTimeCodesPerSecond()
            )
            active_source = flow_temporal.kit_cae_selected_velocity_asset(
                field_prim, active_time_code, cae_vtk, Usd
            )
            phase_dataset, active_index = self._resolve_live_airflow_phase_dataset(
                active_dataset,
                active_source,
            )
        except (AirflowDatasetError, ValueError) as error:
            return SimulationCacheResult(
                False, f"Active airflow phase is unavailable: {error}"
            )

        time_codes = self._flow_temporal_sample_time_codes
        if len(time_codes) < 2 or len(
            target_dataset.velocity_vti_sequence_paths
        ) != len(time_codes):
            return SimulationCacheResult(
                False,
                "Target airflow sequence cannot preserve the attached temporal phase.",
            )
        target_index = airflow_family.next_normalized_phase_target_sample_index(
            active_index,
            len(phase_dataset.velocity_vti_sequence_paths),
            len(target_dataset.velocity_vti_sequence_paths),
        )
        target_source = target_dataset.velocity_vti_sequence_paths[target_index]
        target_time_code = time_codes[target_index]

        if not await self._wait_for_attached_airflow_playback(
            timeline,
            omni.kit.app.get_app().next_update_async,
            transition_id,
            target_binding,
        ):
            return self._superseded_transition_result(transition_id, target_binding)

        emitter_path = str(emitter_prim.GetPath())
        velocity_scale_attribute = emitter_prim.GetAttribute("velocityScale")
        velocity_scale_before = (
            velocity_scale_attribute.Get()
            if velocity_scale_attribute and velocity_scale_attribute.IsValid()
            else None
        )
        flow_resets_before = sum(
            bool(record.get("flow_reset")) for record in self._flow_temporal_records
        )
        completions_before = self._kit_cae_operator_completion_count(emitter_path)
        payload_attr = emitter_prim.GetAttribute("nanoVdbVelocities")
        payload_before = (
            payload_attr.Get() if payload_attr and payload_attr.IsValid() else None
        )
        payload_before_digest = flow_temporal.kit_cae_payload_digest(
            payload_before, len(payload_before) if payload_before is not None else 0
        )
        previous_edit_target = stage.GetEditTarget()
        stage.SetEditTarget(stage.GetSessionLayer())
        try:
            flow_temporal.author_kit_cae_temporal_velocity_samples_except_index(
                field_prim,
                target_dataset.velocity_vti_sequence_paths,
                time_codes,
                active_index,
                cae_vtk,
                Sdf,
                Usd,
            )
        finally:
            stage.SetEditTarget(previous_edit_target)
        app = omni.kit.app.get_app()
        retarget_result = await flow_temporal.retarget_kit_cae_temporal_source_in_place(
            stage,
            field_prim,
            target_source,
            target_time_code,
            cae_vtk,
            Sdf,
            Usd,
            refresh=False,
        )
        if not self._is_current_airflow_transition(transition_id, target_binding):
            return self._superseded_transition_result(transition_id, target_binding)
        carb.log_warn(
            self._format_airflow_transition_log_block(
                "RETARGET",
                (
                    ("Transition:", transition_id),
                    ("From source:", active_source.name),
                    ("To source:", target_source.name),
                    ("Sample index:", target_index),
                    ("Phase preserved:", True),
                    ("Retarget readback:", retarget_result.resolved_source.name),
                ),
            )
        )
        carb.log_warn(
            self._format_airflow_transition_log_block(
                "AWAIT CONSUMPTION",
                (
                    ("Transition:", transition_id),
                    ("Target:", target_binding.dataset_identity),
                    ("Forced refresh:", False),
                ),
            )
        )

        runtime_consumed = False
        payload_changed = False
        observed_source = active_source
        observed_sources: set[Path] = set()
        for _ in range(240):
            await app.next_update_async()
            if not self._is_current_airflow_transition(transition_id, target_binding):
                return self._superseded_transition_result(transition_id, target_binding)
            if not timeline.is_playing():
                continue
            observed_source = flow_temporal.kit_cae_selected_velocity_asset(
                field_prim,
                float(timeline.get_current_time()) * stage.GetTimeCodesPerSecond(),
                cae_vtk,
                Usd,
            )
            if observed_source is not None:
                observed_sources.add(observed_source)
            payload = (
                payload_attr.Get() if payload_attr and payload_attr.IsValid() else None
            )
            payload_changed = (
                flow_temporal.kit_cae_payload_digest(
                    payload, len(payload) if payload is not None else 0
                )
                != payload_before_digest
            )
            runtime_consumed = (
                observed_source == target_source
                and self._kit_cae_operator_completion_count(emitter_path)
                > completions_before
                and payload_changed
            )
            if runtime_consumed:
                break
        if not runtime_consumed:
            carb.log_error(
                self._format_airflow_transition_log_block(
                    "CONSUMPTION TIMEOUT",
                    (
                        ("Transition:", transition_id),
                        ("Target:", target_binding.dataset_identity),
                        (
                            "Last observed source:",
                            observed_source.name if observed_source else "unavailable",
                        ),
                        ("Observed sample boundaries:", len(observed_sources)),
                        ("Forced refresh:", False),
                    ),
                )
            )
            return SimulationCacheResult(
                False, "Airflow transition is pending live runtime consumption."
            )

        carb.log_warn(
            self._format_airflow_transition_log_block(
                "CONSUMED",
                (
                    ("Transition:", transition_id),
                    ("Observed source:", observed_source.name),
                    ("Consumption:", "native_temporal_update"),
                    ("Operator update observed:", True),
                    ("Payload changed:", payload_changed),
                ),
            )
        )

        if not self._is_current_airflow_transition(transition_id, target_binding):
            return self._superseded_transition_result(transition_id, target_binding)
        await flow_temporal.retarget_kit_cae_temporal_source_in_place(
            stage,
            field_prim,
            target_dataset.velocity_vti_sequence_paths[active_index],
            time_codes[active_index],
            cae_vtk,
            Sdf,
            Usd,
            refresh=False,
        )
        if not self._is_current_airflow_transition(transition_id, target_binding):
            return self._superseded_transition_result(transition_id, target_binding)

        try:
            resolve_runtime_contract = (
                flow_validation.resolve_live_kit_cae_direct_attach_runtime_contract
            )
            target_runtime_contract = await resolve_runtime_contract(
                emitter_prim,
                Usd,
                self.config.simulation_cache.smoke_tuning.velocity_scale_multiplier,
                Usd.TimeCode(self._flow_temporal_sample_time_codes[0]),
            )
        except RuntimeError as error:
            return SimulationCacheResult(
                False,
                f"Airflow transition target runtime contract failed: {error}",
            )
        if not self._is_current_airflow_transition(transition_id, target_binding):
            return self._superseded_transition_result(transition_id, target_binding)
        target_base_velocity_scale = target_runtime_contract["base_velocity_scale"]
        target_direct_attach_equivalent = target_runtime_contract[
            "effective_velocity_scale"
        ]

        # A dataset-specific transport scale is authored by Kit-CAE during a
        # direct Attach.  Do not guess it from workload names or VTI filenames.
        target_velocity_scale_applied = False
        velocity_scale_apply_error: str | None = None
        velocity_scale_after = velocity_scale_before
        velocity_scale_edit_target = stage.GetEditTarget()
        stage.SetEditTarget(stage.GetSessionLayer())
        try:
            apply_velocity_scale = self._apply_attached_velocity_scale
            velocity_scale_after = apply_velocity_scale(
                emitter_prim,
                base_velocity_scale=target_base_velocity_scale,
                velocity_scale_multiplier=(
                    self.config.simulation_cache.smoke_tuning.velocity_scale_multiplier
                ),
            )
            target_velocity_scale_applied = True
        except RuntimeError as error:
            velocity_scale_apply_error = str(error)
            velocity_scale_after = (
                velocity_scale_attribute.Get()
                if velocity_scale_attribute and velocity_scale_attribute.IsValid()
                else None
            )
        finally:
            stage.SetEditTarget(velocity_scale_edit_target)
        carb.log_warn(
            self._format_airflow_transition_log_block(
                "VELOCITY SCALE APPLY",
                (
                    ("Transition:", transition_id),
                    ("Target selector:", target_binding.dataset_identity),
                    ("Target value:", target_direct_attach_equivalent),
                    (
                        "Write path/function:",
                        "flow_smoke.apply_kit_cae_direct_attach_velocity_scale",
                    ),
                    (
                        "Runtime property/path:",
                        f"{emitter_prim.GetPath()}.velocityScale",
                    ),
                    ("Value before:", velocity_scale_before),
                    ("Write attempted:", True),
                    ("Write succeeded:", target_velocity_scale_applied),
                    ("Value after:", velocity_scale_after),
                    ("Reason:", velocity_scale_apply_error or "none"),
                ),
            )
        )
        if not target_velocity_scale_applied:
            return SimulationCacheResult(
                False,
                "Airflow transition velocityScale write failed: "
                + (velocity_scale_apply_error or "unknown reason"),
            )

        if not self._is_current_airflow_transition(transition_id, target_binding):
            return self._superseded_transition_result(transition_id, target_binding)

        payload_after = (
            payload_attr.Get() if payload_attr and payload_attr.IsValid() else None
        )
        payload_updated = (
            flow_temporal.kit_cae_payload_digest(
                payload_after, len(payload_after) if payload_after is not None else 0
            )
            != payload_before_digest
        )
        couple_rate_attribute = emitter_prim.GetAttribute("coupleRateVelocity")
        couple_rate_velocity = (
            couple_rate_attribute.Get()
            if couple_rate_attribute and couple_rate_attribute.IsValid()
            else None
        )
        operator_ready = (
            payload_after is not None
            and len(payload_after) > 0
            and float(couple_rate_velocity or 0.0) > 0.0
        )
        target_family_observed = (
            observed_source in target_dataset.velocity_vti_sequence_paths
        )
        flow_resets_after = sum(
            bool(record.get("flow_reset")) for record in self._flow_temporal_records
        )
        flow_resets_delta = flow_resets_after - flow_resets_before
        timeline_continuous = timeline.is_playing()
        velocity_scale_matches_target = (
            target_direct_attach_equivalent is not None
            and velocity_scale_after is not None
            and abs(float(velocity_scale_after) - target_direct_attach_equivalent)
            < 1e-6
        )
        runtime_contract_match = (
            runtime_consumed
            and target_family_observed
            and velocity_scale_matches_target
            and operator_ready
            and payload_updated
            and flow_resets_delta == 0
            and timeline_continuous
        )
        carb.log_warn(
            self._format_airflow_transition_log_block(
                "RUNTIME CONTRACT",
                (
                    ("Transition:", transition_id),
                    ("Target selector:", target_binding.dataset_identity),
                    (
                        "Target direct-Attach velocityScale:",
                        (
                            target_direct_attach_equivalent
                            if target_direct_attach_equivalent is not None
                            else "unavailable"
                        ),
                    ),
                    ("Runtime velocityScale before:", velocity_scale_before),
                    ("Applied:", target_velocity_scale_applied),
                    ("Runtime velocityScale after:", velocity_scale_after),
                    ("Effective velocityScale after:", velocity_scale_after),
                    ("Target VTI family observed:", target_family_observed),
                    ("Operator ready:", operator_ready),
                    ("Payload updated:", payload_updated),
                    ("Flow resets delta:", flow_resets_delta),
                    ("Timeline continuous:", timeline_continuous),
                    ("Runtime contract match:", runtime_contract_match),
                ),
            )
        )
        if not runtime_contract_match:
            return SimulationCacheResult(
                False,
                "Airflow transition remains pending: target direct-Attach "
                "runtime contract is not proven.",
            )

        if not self._commit_attached_workload_transition(
            target_binding,
            runtime_consumed,
            runtime_contract_match=True,
            transition_id=transition_id,
        ):
            return self._superseded_transition_result(transition_id, target_binding)
        self._flow_base_velocity_scale = target_base_velocity_scale
        self._flow_temporal_records = []
        self._flow_temporal_failure = None
        carb.log_warn(
            self._format_airflow_transition_log_block(
                "COMMIT",
                (
                    ("Transition:", transition_id),
                    ("Active airflow:", target_binding.dataset_identity),
                    ("Pending airflow:", "None"),
                    ("Runtime source:", observed_source.name),
                    ("Runtime consumed:", runtime_consumed),
                    ("Flow resets delta:", flow_resets_delta),
                    ("Timeline continuous:", timeline_continuous),
                    ("RESULT:", "PASS"),
                ),
            )
        )
        if status_callback:
            status_callback(
                f"Airflow transitioned to {target_binding.dataset_identity}."
            )
        return SimulationCacheResult(
            True, f"Airflow transitioned to {target_binding.dataset_identity}."
        )

    async def _wait_for_attached_airflow_playback(
        self,
        timeline,
        next_update_async,
        transition_id: str,
        target_binding,
    ) -> bool:
        """Wait for the operator's playback intent without changing it."""

        while not timeline.is_playing():
            await next_update_async()
            if not self._is_current_airflow_transition(transition_id, target_binding):
                return False
        return self._is_current_airflow_transition(transition_id, target_binding)

    async def _observe_attached_target_family_proof(
        self,
        app,
        timeline,
        stage,
        field_prim,
        emitter_prim,
        target_dataset,
        target_index: int,
        first_source: Path,
        target_velocity_scale: float,
        cae_vtk,
        Usd,
    ) -> dict[str, object]:
        """Optional development diagnostic; never blocks a runtime transition."""

        expected_paths = target_dataset.velocity_vti_sequence_paths
        observed: list[Path] = [first_source]
        previous_source: Path | None = first_source
        runtime_contract_match = True
        for _ in range(len(expected_paths) * 90):
            if self._flow_lifecycle_state != "ATTACHED" or not timeline.is_playing():
                break
            source = flow_temporal.kit_cae_selected_velocity_asset(
                field_prim,
                float(timeline.get_current_time()) * stage.GetTimeCodesPerSecond(),
                cae_vtk,
                Usd,
            )
            if source is not None and source != previous_source:
                observed.append(source)
                previous_source = source
                velocity_scale = emitter_prim.GetAttribute("velocityScale").Get()
                payload = emitter_prim.GetAttribute("nanoVdbVelocities").Get()
                couple_rate = emitter_prim.GetAttribute("coupleRateVelocity").Get()
                runtime_contract_match = runtime_contract_match and (
                    velocity_scale is not None
                    and abs(float(velocity_scale) - target_velocity_scale) < 1e-6
                    and payload is not None
                    and len(payload) > 0
                    and float(couple_rate or 0.0) > 0.0
                )
                if len(observed) == len(expected_paths):
                    break
            await app.next_update_async()
        return self._evaluate_target_family_proof(
            expected_paths,
            target_index,
            tuple(observed),
            runtime_contract_match,
        )

    @staticmethod
    def _evaluate_target_family_proof(
        expected_paths: tuple[Path, ...],
        start_index: int,
        observed_paths: tuple[Path, ...],
        runtime_contract_match: bool,
    ) -> dict[str, object]:
        """Evaluate target samples without conflating them with old proof state."""

        total = len(expected_paths)
        expected = tuple(
            expected_paths[(start_index + offset) % total] for offset in range(total)
        )
        observed = observed_paths[:total]
        foreign = sum(source not in expected_paths for source in observed)
        ordered = len(observed) == total and observed == expected
        return {
            "samples_observed": f"{len(observed)}/{total}",
            "foreign_family_samples": foreign,
            "forward_transitions": max(len(observed) - 1, 0),
            "loop_closure": "PASS" if ordered else "FAIL",
            "runtime_contract_match": runtime_contract_match,
            "last_source": observed[-1].name if observed else "unavailable",
            "passed": ordered and foreign == 0 and runtime_contract_match,
        }

    def _commit_attached_workload_transition(
        self,
        target_binding,
        runtime_consumed: bool,
        *,
        runtime_contract_match: bool = True,
        transition_id: str | None = None,
    ) -> bool:
        """Commit immediately after the live target runtime contract is proven."""

        if not (runtime_consumed and runtime_contract_match):
            return False
        if transition_id is not None and not self._is_current_airflow_transition(
            transition_id, target_binding
        ):
            return False
        self._flow_session_workload_binding = target_binding
        self._flow_pending_workload_binding = None
        if transition_id is not None:
            self._flow_active_transition_id = None
        self._flow_last_airflow_failure = None
        return True

    def _is_current_airflow_transition(
        self, transition_id: str, target_binding
    ) -> bool:
        """Return whether this async path still owns terminal transition state."""

        return (
            self._flow_lifecycle_state == "ATTACHED"
            and self._flow_active_transition_id == transition_id
            and self._flow_pending_workload_binding == target_binding
        )

    def _resolve_live_airflow_phase_dataset(self, committed_dataset, live_source: Path):
        """Resolve phase from the actual temporal family after a superseded retarget."""

        candidates = (committed_dataset,) + tuple(
            dataset
            for dataset in discover_airflow_dataset_registry(
                self.config.asset_root,
                self.config.simulation_cache.airflow_dataset.root,
            )
            if dataset != committed_dataset
        )
        for dataset in candidates:
            try:
                return dataset, dataset.velocity_vti_sequence_paths.index(live_source)
            except ValueError:
                continue
        raise ValueError(
            "Live temporal source is absent from the registered airflow family: "
            f"{live_source}"
        )

    @staticmethod
    def _superseded_transition_result(
        transition_id: str,
        target_binding,
    ) -> SimulationCacheResult:
        """End a stale async path without treating supersession as failure."""

        return SimulationCacheResult(
            True,
            f"Airflow transition {transition_id} to "
            f"{target_binding.dataset_identity} was superseded.",
        )

    def _finalize_airflow_failure(
        self,
        *,
        semantic_workload: str,
        requested_binding,
        reason: str,
        failure_stage: str,
        logger: Callable[[str], None] | None = None,
        status_callback: StatusCallback | None = None,
        transition_id: str | None = None,
    ) -> SimulationCacheResult:
        """End an unsuccessful airflow operation without changing semantic workload."""

        if transition_id is not None and not self._is_current_airflow_transition(
            transition_id, requested_binding
        ):
            return self._superseded_transition_result(transition_id, requested_binding)

        active_binding = self._flow_session_workload_binding
        self._flow_pending_workload_binding = None
        if transition_id is not None:
            self._flow_active_transition_id = None
        pending_cleared = self._flow_pending_workload_binding is None
        attached = (
            self._flow_lifecycle_state == "ATTACHED" and active_binding is not None
        )
        active_selector = active_binding.dataset_identity if attached else "DETACHED"
        requested_selector = (
            requested_binding.dataset_identity
            if requested_binding is not None
            else "unresolved"
        )
        action = "kept_previous_safe_dataset" if attached else "remained_detached"
        self._flow_last_airflow_failure = {
            "semantic_workload": semantic_workload,
            "requested_airflow_selector": requested_selector,
            "active_airflow_selector": active_selector,
            "reason": reason,
            "failure_stage": failure_stage,
            "action": action,
        }
        message = (
            "Airflow failed | "
            f"workload={semantic_workload} | requested={requested_selector} | "
            f"active={active_selector} | action={action} | reason={reason}"
        )
        log_block = self._format_airflow_transition_log_block(
            "FAILED",
            (
                ("Semantic workload:", semantic_workload),
                ("Requested airflow:", requested_selector),
                ("Active airflow:", active_selector),
                ("Reason:", reason),
                ("Failure stage:", failure_stage),
                ("Action:", action),
                ("Telemetry rolled back:", False),
                ("Pending cleared:", pending_cleared),
                ("Flow reset:", False),
                ("RESULT:", "FAIL"),
            ),
        )
        if logger:
            logger(log_block)
        if status_callback:
            status_callback(message)
        return SimulationCacheResult(False, message)

    @staticmethod
    def _format_airflow_transition_log_block(
        event: str,
        fields: tuple[tuple[str, object], ...],
    ) -> str:
        """Format transition evidence in the same bounded Kit Warning style."""

        rule = "=" * 63
        lines = [f"=== DTRS AIRFLOW TRANSITION / {event} {rule}"]
        lines.extend(f"  {label:<43}{value}" for label, value in fields)
        lines.extend(("", rule))
        return with_dtrs_local_timestamp("\n".join(lines))
