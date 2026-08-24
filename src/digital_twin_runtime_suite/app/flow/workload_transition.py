# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""Attached workload-to-airflow transition orchestration."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from digital_twin_runtime_suite.app.airflow_dataset import AirflowDatasetError
from digital_twin_runtime_suite.app.airflow_validation import family as airflow_family
from digital_twin_runtime_suite.app.airflow_validation.cache import (
    build_dataset_validation_signature,
)
from digital_twin_runtime_suite.app.diagnostics import with_dtrs_local_timestamp
from digital_twin_runtime_suite.app.flow import temporal as flow_temporal
from digital_twin_runtime_suite.app.flow import validation as flow_validation
from digital_twin_runtime_suite.app.flow.runtime import SimulationCacheResult
from digital_twin_runtime_suite.app.status_log import format_dtrs_diagnostic_block
from digital_twin_runtime_suite.app.workload_binding import BackgroundValidationError

StatusCallback = Callable[[str], None]
AirflowDatasetFamilyCompatibilityError = (
    airflow_family.AirflowDatasetFamilyCompatibilityError
)
_RUNTIME_RECONCILIATION_PREFIX = "Airflow transition runtime reconciliation required:"


class AttachedWorkloadTransitionMixin:
    """Own Stage 8 in-place selector transition state and proof gates."""

    async def request_attached_workload_transition_in_kit(
        self,
        workload_mode: str,
        status_callback: StatusCallback | None = None,
    ) -> SimulationCacheResult:
        """Execute one transition without allowing async exceptions to strand state."""

        try:
            return await self._request_attached_workload_transition_in_kit(
                workload_mode,
                status_callback=status_callback,
            )
        except Exception as error:
            return await self._reconcile_unexpected_transition_exception(
                workload_mode,
                error,
                status_callback=status_callback,
            )

    async def _request_attached_workload_transition_in_kit(
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

        state_before = self._airflow_state.snapshot
        active_binding = (
            state_before.committed.binding if state_before.committed else None
        )
        if active_binding is None:
            return SimulationCacheResult(
                False, "Attached Flow has no active airflow selector."
            )
        target_binding = self._airflow_state.resolve_binding(workload_mode)
        try:
            target = self._airflow_state.resolve_target(target_binding)
            live_matches = True
            live_source = "not_checked"
            if active_binding == target_binding:
                live_matches, live_source = self._live_flow_consumer_matches_dataset(
                    target.dataset
                )
                if live_matches and state_before.pending is None:
                    return SimulationCacheResult(
                        True,
                        "Attached airflow already matches the requested workload.",
                    )
                if status_callback:
                    status_callback("Airflow active: runtime reconciliation")
            transition = self._airflow_state.begin(
                target,
                force=not live_matches,
            )
        except (AirflowDatasetError, RuntimeError, ValueError) as error:
            return self._finalize_airflow_failure(
                semantic_workload=workload_mode,
                requested_binding=target_binding,
                reason=str(error),
                failure_stage="dataset_discovery",
                logger=carb.log_error,
                status_callback=status_callback,
            )
        if transition is None:
            return SimulationCacheResult(
                True,
                "Attached airflow already matches the requested workload.",
            )
        target_dataset = transition.target.dataset
        transition_id = transition.transition_id
        pending_binding = (
            state_before.pending.target.binding if state_before.pending else None
        )
        if transition.superseded_transition_id is not None:
            carb.log_warn(
                self._format_airflow_transition_log_block(
                    "SUPERSEDED",
                    (
                        ("Transition:", transition.superseded_transition_id),
                        (
                            "Target:",
                            (
                                pending_binding.dataset_identity
                                if pending_binding
                                else "unknown"
                            ),
                        ),
                        ("Superseded by transition:", transition_id),
                        ("New target:", target_binding.dataset_identity),
                        ("Last committed active:", active_binding.dataset_identity),
                        ("Old commit allowed:", False),
                    ),
                )
            )
        if not live_matches:
            carb.log_warn(
                self._format_airflow_transition_log_block(
                    "RECONCILIATION REQUEST",
                    (
                        ("Transition:", transition_id),
                        ("Committed airflow:", active_binding.dataset_identity),
                        ("Requested airflow:", target_binding.dataset_identity),
                        ("Observed live source:", live_source),
                        ("NO_OP allowed:", False),
                    ),
                )
            )
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
            signature = build_dataset_validation_signature(
                target_dataset, self.config.simulation_cache.velocity_field_name
            )
            validation_was_hit = bool(
                self._flow_validation_cache.lookup(signature).preflight
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
                return self._superseded_transition_result(
                    transition_id,
                    target_binding,
                )
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
            family = self.validate_attached_airflow_transition_pair(
                target_dataset=target_dataset,
                target_receipt=receipt,
                target_signature=signature,
            )
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
                    "PAIR COMPATIBILITY",
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
                "PAIR COMPATIBILITY",
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
        if status_callback:
            status_callback("Airflow active: runtime consumption")
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
        if result.message.startswith(_RUNTIME_RECONCILIATION_PREFIX):
            return self._finalize_airflow_reconciliation_failure(
                semantic_workload=workload_mode,
                requested_binding=target_binding,
                reason=result.message.removeprefix(
                    _RUNTIME_RECONCILIATION_PREFIX
                ).strip(),
                logger=carb.log_error,
                status_callback=status_callback,
                transition_id=transition_id,
            )
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
            committed = self._airflow_state.committed
            if committed is None:
                raise ValueError("Shared airflow state has no committed dataset.")
            active_dataset = committed.dataset
            active_resolution, target_resolution = (
                self._airflow_state.resolve_transition_phase_pair(
                    active_dataset,
                    target_dataset,
                )
            )
        except ValueError as error:
            return SimulationCacheResult(
                False, f"Active airflow phase is unavailable: {error}"
            )
        active_source = active_resolution.sample.source_vti
        target_index = target_resolution.sample.sample_index

        time_codes = self._flow_temporal_sample_time_codes
        if len(time_codes) < 2 or len(
            target_dataset.velocity_vti_sequence_paths
        ) != len(time_codes):
            return SimulationCacheResult(
                False,
                "Target airflow sequence cannot preserve the attached temporal phase.",
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
        app = omni.kit.app.get_app()

        async def fail_after_runtime_mutation(reason: str) -> SimulationCacheResult:
            if status_callback:
                status_callback("Airflow active: runtime reconciliation")
            rollback_proven, rollback_reason = (
                await self._rollback_attached_runtime_target_mutation(
                    carb=carb,
                    app=app,
                    timeline=timeline,
                    stage=stage,
                    field_prim=field_prim,
                    emitter_prim=emitter_prim,
                    active_dataset=active_dataset,
                    time_codes=time_codes,
                    velocity_scale_attribute=velocity_scale_attribute,
                    velocity_scale_before=velocity_scale_before,
                    payload_attr=payload_attr,
                    cae_vtk=cae_vtk,
                    Sdf=Sdf,
                    Usd=Usd,
                    transition_id=transition_id,
                    target_binding=target_binding,
                )
            )
            if rollback_proven:
                self._clear_runtime_mutation_context(transition_id)
                return SimulationCacheResult(
                    False,
                    f"{reason} Rollback verified: {rollback_reason}.",
                )
            return SimulationCacheResult(
                False,
                f"{_RUNTIME_RECONCILIATION_PREFIX} {reason} "
                f"Rollback failed: {rollback_reason}.",
            )

        self._flow_runtime_mutation_context = {
            "app": app,
            "timeline": timeline,
            "stage": stage,
            "field_prim": field_prim,
            "emitter_prim": emitter_prim,
            "active_dataset": active_dataset,
            "target_dataset": target_dataset,
            "time_codes": time_codes,
            "velocity_scale_attribute": velocity_scale_attribute,
            "velocity_scale_before": velocity_scale_before,
            "payload_attr": payload_attr,
            "cae_vtk": cae_vtk,
            "Sdf": Sdf,
            "Usd": Usd,
            "transition_id": transition_id,
            "target_binding": target_binding,
        }
        previous_edit_target = stage.GetEditTarget()
        try:
            stage.SetEditTarget(stage.GetSessionLayer())
            try:
                flow_temporal.author_kit_cae_temporal_velocity_samples_except_index(
                    field_prim,
                    target_dataset.velocity_vti_sequence_paths,
                    time_codes,
                    target_index,
                    cae_vtk,
                    Sdf,
                    Usd,
                )
            finally:
                stage.SetEditTarget(previous_edit_target)
            retarget_result = (
                await flow_temporal.retarget_kit_cae_temporal_source_in_place(
                    stage,
                    field_prim,
                    target_source,
                    target_time_code,
                    cae_vtk,
                    Sdf,
                    Usd,
                    refresh=False,
                )
            )
        except (RuntimeError, TypeError, ValueError) as error:
            return await fail_after_runtime_mutation(
                f"Airflow transition target authoring failed: {error}"
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

        consumption_proof = await self._await_runtime_dataset_consumption_proof(
            app=app,
            timeline=timeline,
            stage=stage,
            field_prim=field_prim,
            payload_attr=payload_attr,
            emitter_path=emitter_path,
            expected_paths=target_dataset.velocity_vti_sequence_paths,
            initial_target_source=target_source,
            completions_before=completions_before,
            payload_before_digest=payload_before_digest,
            cae_vtk=cae_vtk,
            Usd=Usd,
            transition_id=transition_id,
            target_binding=target_binding,
        )
        if consumption_proof is None:
            return self._superseded_transition_result(transition_id, target_binding)
        runtime_consumed = bool(consumption_proof["passed"])
        observed_source_name = consumption_proof["last_observed_source"]
        if not runtime_consumed:
            carb.log_error(
                self._format_airflow_transition_log_block(
                    "CONSUMPTION TIMEOUT",
                    (
                        ("Transition:", transition_id),
                        ("Target:", target_binding.dataset_identity),
                        (
                            "Target family observed:",
                            consumption_proof["target_family_observed"],
                        ),
                        (
                            "Exact target sample observed:",
                            consumption_proof["exact_target_sample_observed"],
                        ),
                        (
                            "Operator completion delta:",
                            consumption_proof["operator_completion_delta"],
                        ),
                        (
                            "Payload digest changed:",
                            consumption_proof["payload_digest_changed"],
                        ),
                        (
                            "Last observed source:",
                            observed_source_name,
                        ),
                        (
                            "Target-family sample boundaries:",
                            consumption_proof["target_family_boundaries"],
                        ),
                        (
                            "Foreign-family source observed:",
                            consumption_proof["foreign_family_source_observed"],
                        ),
                        (
                            "Foreign-family sources:",
                            ", ".join(consumption_proof["foreign_family_sources"])
                            or "none",
                        ),
                        ("Forced refresh:", False),
                    ),
                )
            )
            return await fail_after_runtime_mutation(
                "Airflow transition is pending live runtime consumption."
            )

        carb.log_warn(
            self._format_airflow_transition_log_block(
                "CONSUMED",
                (
                    ("Transition:", transition_id),
                    ("Observed source:", observed_source_name),
                    ("Consumption:", "native_temporal_update"),
                    (
                        "Exact target sample observed:",
                        consumption_proof["exact_target_sample_observed"],
                    ),
                    (
                        "Target-family sample boundaries:",
                        consumption_proof["target_family_boundaries"],
                    ),
                    (
                        "Operator completion delta:",
                        consumption_proof["operator_completion_delta"],
                    ),
                    (
                        "Payload digest changed:",
                        consumption_proof["payload_digest_changed"],
                    ),
                ),
            )
        )

        if not self._is_current_airflow_transition(transition_id, target_binding):
            return self._superseded_transition_result(transition_id, target_binding)
        try:
            await flow_temporal.retarget_kit_cae_temporal_source_in_place(
                stage,
                field_prim,
                target_dataset.velocity_vti_sequence_paths[target_index],
                time_codes[target_index],
                cae_vtk,
                Sdf,
                Usd,
                refresh=False,
            )
        except (RuntimeError, TypeError, ValueError) as error:
            return await fail_after_runtime_mutation(
                f"Airflow transition target confirmation failed: {error}"
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
            return await fail_after_runtime_mutation(
                f"Airflow transition target runtime contract failed: {error}"
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
            return await fail_after_runtime_mutation(
                "Airflow transition velocityScale write failed: "
                + (velocity_scale_apply_error or "unknown reason"),
            )

        if not self._is_current_airflow_transition(transition_id, target_binding):
            return self._superseded_transition_result(transition_id, target_binding)

        payload_after = (
            payload_attr.Get() if payload_attr and payload_attr.IsValid() else None
        )
        payload_updated = bool(consumption_proof["payload_digest_changed"])
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
        target_family_observed = bool(consumption_proof["target_family_observed"])
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
            return await fail_after_runtime_mutation(
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
        self._clear_runtime_mutation_context(transition_id)
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
                    ("Runtime source:", observed_source_name),
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

    def _clear_runtime_mutation_context(self, transition_id: str) -> None:
        """Discard one reconciled mutation context without touching a newer one."""

        context = self._flow_runtime_mutation_context
        if context and context.get("transition_id") == transition_id:
            self._flow_runtime_mutation_context = None

    async def _reconcile_unexpected_transition_exception(
        self,
        workload_mode: str,
        error: Exception,
        *,
        status_callback: StatusCallback | None,
    ) -> SimulationCacheResult:
        """Turn an unexpected async error into a safe or explicit terminal state."""

        import carb

        pending = self._airflow_state.pending
        if pending is None or self._flow_lifecycle_state != "ATTACHED":
            return SimulationCacheResult(
                False,
                f"Airflow transition internal error: {type(error).__name__}: {error}",
            )
        transition_id = pending.transition_id
        requested_binding = pending.target.binding
        reason = f"Unexpected {type(error).__name__}: {error}"
        context = self._flow_runtime_mutation_context
        if context and context.get("transition_id") == transition_id:
            if status_callback:
                status_callback("Airflow active: runtime reconciliation")
            rollback_context = dict(context)
            rollback_context.pop("target_dataset", None)
            try:
                rollback_proven, rollback_reason = (
                    await self._rollback_attached_runtime_target_mutation(
                        carb=carb,
                        **rollback_context,
                    )
                )
            except Exception as rollback_error:
                rollback_proven = False
                rollback_reason = (
                    f"rollback raised {type(rollback_error).__name__}: "
                    f"{rollback_error}"
                )
            if rollback_proven:
                self._clear_runtime_mutation_context(transition_id)
                return self._finalize_airflow_failure(
                    semantic_workload=workload_mode,
                    requested_binding=requested_binding,
                    reason=f"{reason}. Rollback verified: {rollback_reason}.",
                    failure_stage="unexpected_runtime_transition",
                    logger=carb.log_error,
                    status_callback=status_callback,
                    transition_id=transition_id,
                )
            return self._finalize_airflow_reconciliation_failure(
                semantic_workload=workload_mode,
                requested_binding=requested_binding,
                reason=f"{reason}. Rollback failed: {rollback_reason}.",
                logger=carb.log_error,
                status_callback=status_callback,
                transition_id=transition_id,
            )
        return self._finalize_airflow_failure(
            semantic_workload=workload_mode,
            requested_binding=requested_binding,
            reason=reason,
            failure_stage="unexpected_transition",
            logger=carb.log_error,
            status_callback=status_callback,
            transition_id=transition_id,
        )

    def _live_flow_consumer_matches_dataset(self, dataset) -> tuple[bool, str]:
        """Read the active FieldArray source before accepting a same-workload NO_OP."""

        try:
            import omni.timeline
            import omni.usd
            from omni.cae.schema import vtk as cae_vtk
            from pxr import Usd

            stage = omni.usd.get_context().get_stage()
            if stage is None:
                return False, "stage unavailable"
            field_prim = stage.GetPrimAtPath(
                "/DTRS_HoudiniVelocity/PointData/"
                f"{self.config.simulation_cache.velocity_field_name}"
            )
            if not field_prim or not field_prim.IsValid():
                return False, "velocity FieldArray unavailable"
            timeline = omni.timeline.get_timeline_interface()
            source = flow_temporal.kit_cae_selected_velocity_asset(
                field_prim,
                float(timeline.get_current_time()) * stage.GetTimeCodesPerSecond(),
                cae_vtk,
                Usd,
            )
        except Exception as error:
            return False, f"live source unverified: {error}"
        if source is None:
            return False, "live source unavailable"
        expected_sources = {
            path.resolve() for path in dataset.velocity_vti_sequence_paths
        }
        return source in expected_sources, source.name

    async def _await_runtime_dataset_consumption_proof(
        self,
        *,
        app,
        timeline,
        stage,
        field_prim,
        payload_attr,
        emitter_path: str,
        expected_paths: tuple[Path, ...],
        initial_target_source: Path,
        completions_before: int,
        payload_before_digest: str,
        cae_vtk,
        Usd,
        transition_id: str,
        target_binding,
    ) -> dict[str, object] | None:
        """Collect target-family evidence without pinning it to one time sample."""

        observed_boundaries: list[Path] = []
        previous_source: Path | None = None
        payload_digest_changed = False
        proof = self._evaluate_runtime_dataset_consumption_proof(
            expected_paths,
            initial_target_source,
            (),
            operator_completion_delta=0,
            payload_digest_changed=False,
        )
        for _ in range(240):
            await app.next_update_async()
            if not self._is_current_airflow_transition(transition_id, target_binding):
                return None
            if not timeline.is_playing():
                continue
            observed_source = flow_temporal.kit_cae_selected_velocity_asset(
                field_prim,
                float(timeline.get_current_time()) * stage.GetTimeCodesPerSecond(),
                cae_vtk,
                Usd,
            )
            if observed_source is not None and observed_source != previous_source:
                observed_boundaries.append(observed_source)
                previous_source = observed_source
            payload = (
                payload_attr.Get() if payload_attr and payload_attr.IsValid() else None
            )
            payload_digest_changed = payload_digest_changed or (
                flow_temporal.kit_cae_payload_digest(
                    payload,
                    len(payload) if payload is not None else 0,
                )
                != payload_before_digest
            )
            proof = self._evaluate_runtime_dataset_consumption_proof(
                expected_paths,
                initial_target_source,
                tuple(observed_boundaries),
                operator_completion_delta=(
                    self._kit_cae_operator_completion_count(emitter_path)
                    - completions_before
                ),
                payload_digest_changed=payload_digest_changed,
            )
            if proof["passed"]:
                return proof
        return proof

    @staticmethod
    def _evaluate_runtime_dataset_consumption_proof(
        expected_paths: tuple[Path, ...],
        initial_target_source: Path,
        observed_boundaries: tuple[Path, ...],
        *,
        operator_completion_delta: int,
        payload_digest_changed: bool,
    ) -> dict[str, object]:
        """Evaluate runtime evidence for one target dataset, not one VTI frame."""

        target_boundaries = tuple(
            source for source in observed_boundaries if source in expected_paths
        )
        foreign_sources = tuple(
            source for source in observed_boundaries if source not in expected_paths
        )
        target_family_observed = bool(target_boundaries)
        exact_target_sample_observed = initial_target_source in observed_boundaries
        completion_delta = max(operator_completion_delta, 0)
        return {
            "target_family_observed": target_family_observed,
            "exact_target_sample_observed": exact_target_sample_observed,
            "operator_completion_delta": completion_delta,
            "payload_digest_changed": payload_digest_changed,
            "last_observed_source": (
                observed_boundaries[-1].name if observed_boundaries else "unavailable"
            ),
            "target_family_boundaries": len(target_boundaries),
            "foreign_family_sources": tuple(source.name for source in foreign_sources),
            "foreign_family_source_observed": bool(foreign_sources),
            "passed": (
                target_family_observed
                and not foreign_sources
                and completion_delta > 0
                and payload_digest_changed
            ),
        }

    async def _rollback_attached_runtime_target_mutation(
        self,
        *,
        carb,
        app,
        timeline,
        stage,
        field_prim,
        emitter_prim,
        active_dataset,
        time_codes: tuple[float, ...],
        velocity_scale_attribute,
        velocity_scale_before,
        payload_attr,
        cae_vtk,
        Sdf,
        Usd,
        transition_id: str,
        target_binding,
    ) -> tuple[bool, str]:
        """Restore and prove the previous dataset before clearing shared pending."""

        if len(active_dataset.velocity_vti_sequence_paths) != len(time_codes):
            return False, "previous dataset cannot restore the temporal sequence"
        if velocity_scale_before is None:
            return False, "previous Flow velocityScale is unavailable"
        try:
            rollback_resolution = self._airflow_state.resolve_phase(active_dataset)
            rollback_index = rollback_resolution.sample.sample_index
            rollback_source = active_dataset.velocity_vti_sequence_paths[rollback_index]
            rollback_time_code = time_codes[rollback_index]
            completions_before = self._kit_cae_operator_completion_count(
                str(emitter_prim.GetPath())
            )
            payload_before = (
                payload_attr.Get() if payload_attr and payload_attr.IsValid() else None
            )
            payload_before_digest = flow_temporal.kit_cae_payload_digest(
                payload_before,
                len(payload_before) if payload_before is not None else 0,
            )
            previous_edit_target = stage.GetEditTarget()
            stage.SetEditTarget(stage.GetSessionLayer())
            try:
                flow_temporal.author_kit_cae_temporal_velocity_samples_except_index(
                    field_prim,
                    active_dataset.velocity_vti_sequence_paths,
                    time_codes,
                    rollback_index,
                    cae_vtk,
                    Sdf,
                    Usd,
                )
                velocity_scale_attribute.Set(velocity_scale_before)
            finally:
                stage.SetEditTarget(previous_edit_target)
            await flow_temporal.retarget_kit_cae_temporal_source_in_place(
                stage,
                field_prim,
                rollback_source,
                rollback_time_code,
                cae_vtk,
                Sdf,
                Usd,
                refresh=False,
            )
        except (RuntimeError, TypeError, ValueError) as error:
            return False, f"previous dataset authoring failed: {error}"

        proof = await self._await_runtime_dataset_consumption_proof(
            app=app,
            timeline=timeline,
            stage=stage,
            field_prim=field_prim,
            payload_attr=payload_attr,
            emitter_path=str(emitter_prim.GetPath()),
            expected_paths=active_dataset.velocity_vti_sequence_paths,
            initial_target_source=rollback_source,
            completions_before=completions_before,
            payload_before_digest=payload_before_digest,
            cae_vtk=cae_vtk,
            Usd=Usd,
            transition_id=transition_id,
            target_binding=target_binding,
        )
        if proof is None:
            return False, "previous dataset rollback was superseded"
        restored_velocity_scale = velocity_scale_attribute.Get()
        velocity_scale_restored = restored_velocity_scale == velocity_scale_before
        payload_after = (
            payload_attr.Get() if payload_attr and payload_attr.IsValid() else None
        )
        couple_rate = emitter_prim.GetAttribute("coupleRateVelocity").Get()
        operator_ready = (
            payload_after is not None
            and len(payload_after) > 0
            and float(couple_rate or 0.0) > 0.0
        )
        rollback_proven = bool(proof["passed"] and velocity_scale_restored)
        rollback_proven = rollback_proven and operator_ready
        carb.log_warn(
            self._format_airflow_transition_log_block(
                "ROLLBACK",
                (
                    ("Transition:", transition_id),
                    ("Previous runtime source:", rollback_source.name),
                    ("Target family observed:", proof["target_family_observed"]),
                    (
                        "Operator completion delta:",
                        proof["operator_completion_delta"],
                    ),
                    ("Payload digest changed:", proof["payload_digest_changed"]),
                    ("VelocityScale restored:", velocity_scale_restored),
                    ("Operator ready:", operator_ready),
                    ("RESULT:", "PASS" if rollback_proven else "FAIL"),
                ),
            )
        )
        if rollback_proven:
            return True, "previous committed dataset restored and verified"
        return False, "previous dataset did not pass runtime rollback proof"

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
        target = self._airflow_state.resolve_target(target_binding)
        return self._airflow_state.commit_target(
            target,
            transition_id=transition_id,
        )

    def _is_current_airflow_transition(
        self, transition_id: str, target_binding
    ) -> bool:
        """Return whether this async path still owns terminal transition state."""

        return (
            self._flow_lifecycle_state == "ATTACHED"
            and self._airflow_state.is_current(transition_id, target_binding)
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

        failure = self._airflow_state.fail(
            transition_id,
            semantic_workload=semantic_workload,
            requested_binding=requested_binding,
            reason=reason,
            failure_stage=failure_stage,
            attached=self._flow_lifecycle_state == "ATTACHED",
        )
        if failure is None:
            return self._superseded_transition_result(
                transition_id or "unknown", requested_binding
            )
        committed = self._airflow_state.committed
        active_binding = committed.binding if committed else None
        pending_cleared = self._airflow_state.pending is None
        attached = (
            self._flow_lifecycle_state == "ATTACHED" and active_binding is not None
        )
        active_selector = active_binding.dataset_identity if attached else "DETACHED"
        requested_selector = (
            requested_binding.dataset_identity
            if requested_binding is not None
            else "unresolved"
        )
        action = failure.action
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

    def _finalize_airflow_reconciliation_failure(
        self,
        *,
        semantic_workload: str,
        requested_binding,
        reason: str,
        logger: Callable[[str], None] | None = None,
        status_callback: StatusCallback | None = None,
        transition_id: str,
    ) -> SimulationCacheResult:
        """Expose an unsafe live consumer instead of falsely retaining a commit."""

        committed = self._airflow_state.committed
        committed_selector = (
            committed.binding.dataset_identity if committed else "unavailable"
        )
        context = self._flow_runtime_mutation_context
        rollback_attempted = bool(
            context and context.get("transition_id") == transition_id
        )
        observed_live_family = self._observed_live_family_from_mutation_context(
            context,
            requested_binding.dataset_identity,
            committed_selector,
        )
        failure = self._airflow_state.fail_unreconciled_runtime(
            transition_id,
            semantic_workload=semantic_workload,
            requested_binding=requested_binding,
            reason=reason,
        )
        if failure is None:
            return self._superseded_transition_result(transition_id, requested_binding)
        self._clear_runtime_mutation_context(transition_id)
        message = (
            "Airflow runtime reconciliation required | "
            f"workload={semantic_workload} | requested="
            f"{requested_binding.dataset_identity} | reason={reason}"
        )
        log_block = self._format_airflow_transition_log_block(
            "RECONCILIATION FAILED",
            (
                ("Semantic workload:", semantic_workload),
                ("Requested airflow:", requested_binding.dataset_identity),
                ("Committed airflow:", committed_selector),
                ("Observed live airflow:", observed_live_family),
                ("Rollback attempted:", rollback_attempted),
                ("Rollback result:", "FAIL"),
                ("Pending cleared:", True),
                ("Reason:", reason),
                ("Action:", failure.action),
                ("RESULT:", "FAIL"),
            ),
        )
        if logger:
            logger(log_block)
        if status_callback:
            status_callback(message)
        return SimulationCacheResult(False, message)

    @staticmethod
    def _observed_live_family_from_mutation_context(
        context: dict[str, object] | None,
        requested_selector: str,
        committed_selector: str,
    ) -> str:
        """Describe the live FieldArray source for an unreconciled error report."""

        if not context:
            return "unverified"
        try:
            timeline = context["timeline"]
            stage = context["stage"]
            field_prim = context["field_prim"]
            cae_vtk = context["cae_vtk"]
            Usd = context["Usd"]
            source = flow_temporal.kit_cae_selected_velocity_asset(
                field_prim,
                float(timeline.get_current_time()) * stage.GetTimeCodesPerSecond(),
                cae_vtk,
                Usd,
            )
            if source is None:
                return "unavailable"
            target_dataset = context["target_dataset"]
            active_dataset = context["active_dataset"]
            if source in target_dataset.velocity_vti_sequence_paths:
                return requested_selector
            if source in active_dataset.velocity_vti_sequence_paths:
                return committed_selector
            return source.name
        except Exception as error:
            return f"unverified: {error}"

    @staticmethod
    def _format_airflow_transition_log_block(
        event: str,
        fields: tuple[tuple[str, object], ...],
    ) -> str:
        """Adapt legacy transition evidence to the shared block formatter."""

        details = {
            label.rstrip(":")
            .lower()
            .replace(" ", "_")
            .replace("-", "_")
            .replace("/", "_"): value
            for label, value in fields
        }
        return format_dtrs_diagnostic_block(
            owner="AIRFLOW TRANSITION",
            process="WORKLOAD",
            state=event,
            details=details,
            append_local_timestamp=with_dtrs_local_timestamp,
        )
