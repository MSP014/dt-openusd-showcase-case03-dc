"""Digital Twin Runtime Suite Kit extension."""

from __future__ import annotations

import asyncio
import contextlib
import re
import sys
import time
from dataclasses import replace
from pathlib import Path

import carb
import carb.settings
import carb.tokens
import carb.windowing
import omni.appwindow
import omni.ext
import omni.ui as ui

EXTENSION_SETTINGS = "/exts/msp.dtrs"
PANEL_WIDTH = 340
ROW_LABEL_WIDTH = 104
SERVER_VIEW_LABEL_WIDTH = 150
TELEMETRY_VALUE_RIGHT_PADDING = 8
COMPACT_TEXT_LENGTH = 44

# Stage 09 closure restores the registry, workload-mapping, and background
# validation logs. They make shared Flow state observable without changing
# production lifecycle ownership or suppressing errors.
STAGE09_SUPPRESS_AIRFLOW_DIAGNOSTICS = False


def _compact_text(value: str, max_length: int = COMPACT_TEXT_LENGTH) -> str:
    text = str(value)
    if len(text) <= max_length:
        return text
    return f"{text[: max_length - 3]}..."


def _resolve_token_path(value: str) -> Path:
    tokens = carb.tokens.get_tokens_interface()
    return Path(tokens.resolve(value)).resolve()


def _fallback_source_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if parent.name == "digital_twin_runtime_suite":
            return parent
    raise RuntimeError("Unable to locate Digital Twin Runtime Suite source root.")


def _ensure_source_root(source_root: Path) -> None:
    src_root = source_root.parent
    src_root_text = str(src_root)
    if src_root_text not in sys.path:
        sys.path.insert(0, src_root_text)


def _with_dtrs_local_timestamp(message: str) -> str:
    """Load the shared formatter only after the extension source root exists."""

    from digital_twin_runtime_suite.app.diagnostics import (
        with_dtrs_local_timestamp,
    )

    return with_dtrs_local_timestamp(message)


class DigitalTwinRuntimeSuiteExtension(omni.ext.IExt):
    """Runtime controls for the current Digital Twin Runtime Suite slice."""

    def on_startup(self, ext_id: str) -> None:
        self._ext_id = ext_id
        self._window = None
        self._controller = None
        self._status_label = None
        self._lighting_status_label = None
        self._asset_label = None
        self._load_task = None
        self._reload_task = None
        self._airflow_task = None
        self._visualization_task = None
        self._scheduled_visualization_mode = None
        self._airflow_transition_task = None
        self._airflow_detach_requested = False
        self._airflow_cache_selector_label = None
        self._streamlines_status_label = None
        self._streamlines_cache_build_button = None
        self._streamlines_cache_load_button = None
        self._airflow_background_validation_task = None
        self._streamlines_cache_validation_task = None
        self._streamlines_cache_validation_workload = None
        self._streamlines_receipt_sweep_task = None
        self._validation_receipt_summary_task = None
        self._validation_receipt_acceptance_task = None
        self._validation_receipt_acceptance = None
        self._validation_receipt_checkpoint = None
        self._validation_receipt_acceptance_owns_actions = False
        self._validation_receipt_acceptance_user_mode = None
        self._reuse_vti_receipts_model = None
        self._reuse_streamlines_receipts_model = None
        self._validation_receipt_status_label = None
        self._streamlines_preview_button = None
        self._streamlines_accept_candidate_button = None
        self._streamlines_preview_status_label = None
        self._streamlines_preview_task = None
        self._streamlines_profile_combo = None
        self._streamlines_profile_task = None
        self._streamlines_speed_distribution_task = None
        self._updating_streamlines_profile_combo = False
        self._streamlines_global_tuning_combos = {}
        self._streamlines_volume_tuning_combos = {}
        self._streamlines_global_tuning_frame = None
        self._streamlines_volume_tuning_frame = None
        self._streamlines_material_tuning_combos = {}
        self._streamlines_material_status_label = None
        self._streamlines_material_preview_task = None
        self._streamlines_xform_probe_task = None
        self._streamlines_xform_probe_button = None
        self._streamlines_xform_probe_ready_emitted = False
        self._streamlines_real_curve_ab_probe_task = None
        self._streamlines_real_curve_ab_probe_button = None
        self._streamlines_real_curve_ab_probe_ready_emitted = False
        self._streamlines_real_curve_ab_probe_active = False
        self._streamlines_full_state_ab_probe_task = None
        self._streamlines_full_state_ab_probe_button = None
        self._streamlines_full_state_ab_probe_ready_emitted = False
        self._view_task = None
        self._auxiliary_windows_task = None
        self._smoke_tuning_combos = {}
        self._flow_voxel_resolution_combo = None
        self._show_flow_debug_overlays_model = None
        self._flow_camera_bookmarks = {}
        self._lighting_task = None
        self._camera_sync_task = None
        self._telemetry_task = None
        self._motion_controller = None
        self._suspend_camera_sync_until = 0.0
        self._updating_camera_controls = False
        self._telemetry_provider = None
        self._telemetry_latch = None
        self._telemetry_frame = None
        self._view_frame = None
        self._config_frame = None
        self._telemetry_tab_button = None
        self._view_tab_button = None
        self._config_tab_button = None
        self._chassis_visibility_models = {}
        self._normal_map_scale_model = None
        self._xray_target_models = {}
        self._xray_target_checkboxes = {}
        self._visualization_combo = None
        self._visualization_readiness_labels = {}
        self._updating_visualization_mode = False
        self._visualization_acceptance = None
        self._phase43_flow_attach_baseline = 0
        self._face_panel_open_model = None
        self._face_panel_action_label = None
        self._face_panel_open_state = False
        self._workload_combo = None
        self._refresh_combo = None
        self._freeze_button = None
        self._telemetry_timestamp_label = None
        self._telemetry_state_label = None
        self._telemetry_metric_labels = {}
        self._workload_modes = ()
        self._refresh_intervals = ()
        self._telemetry_config_path = None
        self._telemetry_config_status_label = None
        self._telemetry_config_status_clear_at = 0.0
        self._provider_default_mode_combo = None
        self._provider_default_refresh_combo = None
        self._provider_tuning_mode_combo = None
        self._provider_metric_combo = None
        self._provider_tick_model = None
        self._provider_interpolation_model = None
        self._provider_target_model = None
        self._provider_jitter_model = None
        self._provider_minimum_model = None
        self._provider_maximum_model = None
        self._provider_numeric_metrics = ()
        self._provider_component_tuning_groups = {}
        self._next_telemetry_ui_update = 0.0
        self._hdri_model = None
        self._exposure_model = None
        self._intensity_model = None
        self._show_hdri_background_model = None
        self._review_key_model = None
        self._review_key_intensity_model = None
        self._rotation_x_model = None
        self._rotation_y_model = None
        self._rotation_z_model = None
        self._grid_enabled_model = None
        self._grid_step_model = None
        self._grid_width_model = None
        self._camera_position_x_model = None
        self._camera_position_y_model = None
        self._camera_position_z_model = None
        self._camera_rotation_x_model = None
        self._camera_rotation_y_model = None
        self._camera_rotation_z_model = None
        self._camera_rotation_order = "YXZ"

        self._settings = carb.settings.get_settings()
        carb.log_info(
            "DTRS renderer delegate\n"
            "/app/useFabricSceneDelegate = "
            f"{self._settings.get_as_bool('/app/useFabricSceneDelegate')}"
        )
        self._build_controller()
        self._validation_receipt_checkpoint = (
            self._controller.load_validation_receipt_acceptance_checkpoint()
        )
        self._build_window()
        self._initialize_validation_receipt_acceptance()
        if self._validation_receipt_checkpoint is None:
            self._start_validation_receipt_background_work()
        asyncio.ensure_future(self._dock_left())
        self._auxiliary_windows_task = asyncio.ensure_future(
            self._hide_auxiliary_kit_windows()
        )
        self._camera_sync_task = asyncio.ensure_future(self._sync_camera_panel())
        self._telemetry_task = asyncio.ensure_future(self._run_telemetry())

        if self._settings.get_as_bool(f"{EXTENSION_SETTINGS}/autoLoad"):
            self._schedule_load()

    def on_shutdown(self) -> None:
        if self._controller:
            self._controller.stop_background_airflow_validation()
            self._controller.cancel_visualization_transition()
            cancel_preview = getattr(
                self._controller,
                "cancel_streamlines_profile_preview_measurement",
                None,
            )
            if cancel_preview:
                cancel_preview()
            cancel_material = getattr(
                self._controller,
                "cancel_streamlines_material_preview_measurement",
                None,
            )
            if cancel_material:
                cancel_material()
        for task_name in (
            "_load_task",
            "_reload_task",
            "_lighting_task",
            "_airflow_task",
            "_visualization_task",
            "_airflow_transition_task",
            "_airflow_background_validation_task",
            "_streamlines_cache_validation_task",
            "_streamlines_receipt_sweep_task",
            "_validation_receipt_summary_task",
            "_validation_receipt_acceptance_task",
            "_streamlines_preview_task",
            "_streamlines_profile_task",
            "_streamlines_speed_distribution_task",
            "_streamlines_material_preview_task",
            "_streamlines_xform_probe_task",
            "_streamlines_real_curve_ab_probe_task",
            "_streamlines_full_state_ab_probe_task",
            "_view_task",
            "_auxiliary_windows_task",
        ):
            task = getattr(self, task_name, None)
            if task:
                task.cancel()
            setattr(self, task_name, None)
        if self._camera_sync_task:
            self._camera_sync_task.cancel()
            self._camera_sync_task = None
        if self._telemetry_task:
            self._telemetry_task.cancel()
            self._telemetry_task = None
        if self._controller:
            try:
                from digital_twin_runtime_suite.app.streamlines import (
                    real_curve_ab_probe,
                )

                real_curve_ab_probe.cleanup_real_curve_ab_probe_in_kit()
            except Exception as error:  # noqa: BLE001 - shutdown must continue.
                carb.log_error(f"DTRS real-curve A/B cleanup failed: {error}")
            try:
                from digital_twin_runtime_suite.app.streamlines import (
                    full_state_ab_probe,
                )

                full_state_ab_probe.cleanup_full_state_ab_probe_in_kit()
            except Exception as error:  # noqa: BLE001 - shutdown must continue.
                carb.log_error(f"DTRS full-state A/B cleanup failed: {error}")
            try:
                receipt = (
                    self._controller.clear_streamlines_static_runtime_from_open_stage()
                )
                if not receipt.clean:
                    carb.log_error(
                        "DTRS STREAMLINES | SHUTDOWN_CLEANUP | FAIL\n" "result=DIRTY"
                    )
            except Exception as error:  # noqa: BLE001 - shutdown must continue.
                carb.log_error(f"DTRS Streamlines shutdown cleanup failed: {error}")
            try:
                self._controller.clear_xray_material_in_kit()
            except RuntimeError as error:
                carb.log_error(f"DTRS X-Ray shutdown cleanup failed: {error}")
            self._controller.stop_flow_runtime_callbacks()
            self._controller.clear_flow_validation_cache()
        if self._motion_controller:
            self._motion_controller.reset()
        self._motion_controller = None
        self._telemetry_provider = None
        self._telemetry_latch = None
        self._controller = None
        if self._window:
            self._window.visible = False
            self._window = None

    def _start_background_airflow_validation(self) -> None:
        """Start one detached plain-data VTI validator for this DTRS session."""

        if not self._controller:
            return
        try:
            self._controller.start_background_airflow_validation()
        except Exception as error:  # Startup diagnostics must not block DTRS.
            carb.log_error(
                _with_dtrs_local_timestamp(
                    f"DTRS AIRFLOW BACKGROUND VALIDATION | START FAILED | {error}"
                )
            )
            return
        self._airflow_background_validation_task = asyncio.ensure_future(
            self._run_background_airflow_validation()
        )

    async def _run_background_airflow_validation(self) -> None:
        """Forward concise coordinator diagnostics without touching Flow state."""

        def log(message: str) -> None:
            carb.log_warn(_with_dtrs_local_timestamp(message))

        try:
            await self._controller.run_background_airflow_validation(log)
        except asyncio.CancelledError:
            raise
        except Exception as error:  # Preserve startup even if registry assets change.
            carb.log_error(
                _with_dtrs_local_timestamp(
                    f"DTRS AIRFLOW BACKGROUND VALIDATION | ABORTED | {error}"
                )
            )

    def _schedule_current_streamlines_cache_validation(self) -> None:
        """Request one owner-managed cache receipt when workload identity changes."""

        if not self._controller or not self._telemetry_provider:
            return
        workload = self._telemetry_provider.mode
        task = self._streamlines_cache_validation_task
        if (
            workload == self._streamlines_cache_validation_workload
            and task is not None
            and not task.done()
        ):
            return
        self._streamlines_cache_validation_workload = workload
        self._streamlines_cache_validation_task = asyncio.ensure_future(
            self._run_current_streamlines_cache_validation()
        )

    async def _run_current_streamlines_cache_validation(self) -> None:
        """Publish one background receipt without blocking Kit or the UI loop."""

        try:
            ensure_validation = getattr(
                self._controller,
                "ensure_current_streamlines_cache_validation_in_background",
            )
            await ensure_validation()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            carb.log_warn(
                _with_dtrs_local_timestamp(
                    "DTRS STREAMLINES | CACHE_VALIDATION | FAILED " f"| {error}"
                )
            )

    def _start_validation_receipt_background_work(self) -> None:
        """Start bounded validation work; never create a permanent polling loop."""

        if not STAGE09_SUPPRESS_AIRFLOW_DIAGNOSTICS:
            task = self._airflow_background_validation_task
            if task is None or task.done():
                self._start_background_airflow_validation()
        task = self._streamlines_receipt_sweep_task
        if task is None or task.done():
            self._streamlines_receipt_sweep_task = asyncio.ensure_future(
                self._run_streamlines_receipt_sweep()
            )
        summary = self._validation_receipt_summary_task
        if summary is None or summary.done():
            self._validation_receipt_summary_task = asyncio.ensure_future(
                self._report_validation_receipt_startup_summary()
            )

    async def _run_streamlines_receipt_sweep(self):
        """Validate or reuse all configured caches through the existing owner."""

        def status(message: str) -> None:
            carb.log_warn(
                _with_dtrs_local_timestamp(
                    "DTRS VALIDATION RECEIPTS | PROGRESS | " + message
                )
            )

        try:
            ensure_validations = getattr(
                self._controller,
                "ensure_configured_streamlines_cache_validations_in_background",
            )
            return await ensure_validations(status_callback=status)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            carb.log_error(
                _with_dtrs_local_timestamp(
                    "DTRS VALIDATION RECEIPTS | STREAMLINES | FAIL | " f"reason={error}"
                )
            )
            return ()

    async def _report_validation_receipt_startup_summary(self) -> None:
        """Emit one compact source summary after bounded startup work settles."""

        tasks = tuple(
            task
            for task in (
                self._airflow_background_validation_task,
                self._streamlines_receipt_sweep_task,
                self._streamlines_cache_validation_task,
            )
            if task is not None
        )
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        metrics = self._controller.validation_receipt_metrics_snapshot()
        message = "\n".join(
            (
                "DTRS VALIDATION RECEIPTS | STARTUP SUMMARY",
                "VTI:",
                f"  persisted_reused={metrics.vti.persisted_reused}",
                f"  session_reused={metrics.vti.session_reused}",
                f"  fresh_validated={metrics.vti.fresh_validated}",
                f"  invalidated={metrics.vti.invalidated}",
                "Streamlines:",
                "  persisted_reused=" f"{metrics.streamlines.persisted_reused}",
                f"  session_reused={metrics.streamlines.session_reused}",
                f"  fresh_validated={metrics.streamlines.fresh_validated}",
                f"  invalidated={metrics.streamlines.invalidated}",
            )
        )
        carb.log_warn(_with_dtrs_local_timestamp(message))

    def _initialize_validation_receipt_acceptance(self) -> None:
        """Start the appropriate generic guided session after UI construction."""

        if self._validation_receipt_checkpoint is not None:
            self._validation_receipt_acceptance_owns_actions = True
            self._validation_receipt_acceptance_task = asyncio.ensure_future(
                self._run_validation_receipt_acceptance_session2()
            )
            return
        from digital_twin_runtime_suite.app.manual_acceptance import (
            GuidedAcceptanceSession,
        )

        self._validation_receipt_acceptance = GuidedAcceptanceSession(("SESSION_1",))
        self._validation_receipt_acceptance.begin()
        preferences = self._controller.config.validation_receipts
        if (
            preferences.reuse_verified_vti_receipts
            and preferences.reuse_verified_streamlines_cache_receipts
        ):
            return
        self._validation_receipt_acceptance_owns_actions = True
        self._report_validation_receipt_acceptance(
            "READY",
            "View validation-reuse settings are available.",
            next_action=(
                'Enable "Reuse verified VTI receipts" and '
                '"Reuse verified Streamlines cache receipts".'
            ),
        )

    def _begin_validation_receipt_acceptance_session1(self) -> None:
        """Establish all persisted evidence after both settings are saved."""

        task = self._validation_receipt_acceptance_task
        if task is not None and not task.done():
            return
        self._validation_receipt_acceptance_owns_actions = True
        self._report_validation_receipt_acceptance(
            "START",
            "Establishing persisted validation receipts for VTI datasets and "
            "Streamlines caches.",
        )
        self._start_validation_receipt_background_work()
        self._validation_receipt_acceptance_task = asyncio.ensure_future(
            self._run_validation_receipt_acceptance_session1()
        )

    async def _run_validation_receipt_acceptance_session1(self) -> None:
        """Persist four VTI and four Streamlines receipts, then request restart."""

        if not await self._wait_for_validation_receipt_tasks("SESSION_1"):
            return
        try:
            identities = await asyncio.to_thread(
                self._controller.validation_receipt_identity_snapshot
            )
            coverage = self._controller.validation_receipt_coverage_snapshot(identities)
        except Exception as error:
            self._fail_validation_receipt_acceptance(str(error))
            return
        preferences = self._controller.config.validation_receipts
        if not (
            preferences.reuse_verified_vti_receipts
            and preferences.reuse_verified_streamlines_cache_receipts
        ):
            self._fail_validation_receipt_acceptance(
                "Receipt reuse settings were not persisted."
            )
            return
        if coverage["vti_total"] != 4 or coverage["vti_valid"] != 4:
            self._fail_validation_receipt_acceptance(
                "Not all configured VTI preflight receipts were persisted."
            )
            return
        if coverage["streamlines_total"] != 4 or coverage["streamlines_valid"] != 4:
            self._fail_validation_receipt_acceptance(
                "Not all configured Streamlines VALID receipts were persisted."
            )
            return
        self._controller.write_validation_receipt_acceptance_checkpoint(
            {
                "phase": "AWAITING_RESTART",
                "baseline_identities": identities,
            }
        )
        session = getattr(self, "_validation_receipt_acceptance", None)
        if session is None or not session.record("SESSION_1"):
            return
        self._report_validation_receipt_acceptance(
            "COMPLETE",
            "Persisted validation baseline established. "
            f"VTI persisted_receipts={coverage['vti_valid']}/"
            f"{coverage['vti_total']}; Streamlines persisted_receipts="
            f"{coverage['streamlines_valid']}/{coverage['streamlines_total']}; "
            "settings_persisted=True.",
            next_action=(
                "Restart DTRS without changing VTI datasets, Streamlines caches, "
                "or validation settings."
            ),
        )

    async def _run_validation_receipt_acceptance_session2(self) -> None:
        """Prove cheap reuse, then wait for explicit production UI actions."""

        from digital_twin_runtime_suite.app.manual_acceptance import (
            GuidedAcceptanceSession,
        )

        self._validation_receipt_acceptance = GuidedAcceptanceSession(
            ("RESTORED", "Smoke", "Normal")
        )
        self._validation_receipt_acceptance.begin()
        try:
            identities = await asyncio.to_thread(
                self._controller.validation_receipt_identity_snapshot
            )
        except Exception as error:
            self._fail_validation_receipt_acceptance(str(error))
            return
        baseline = self._validation_receipt_checkpoint.get("baseline_identities")
        if identities != baseline:
            self._fail_validation_receipt_acceptance(
                "Acceptance input changed between sessions; persisted-reuse "
                "proof is no longer a controlled comparison."
            )
            return
        preferences = self._controller.config.validation_receipts
        if not (
            preferences.reuse_verified_vti_receipts
            and preferences.reuse_verified_streamlines_cache_receipts
        ):
            self._fail_validation_receipt_acceptance(
                "Receipt reuse settings did not survive restart."
            )
            return
        coverage_before = self._controller.validation_receipt_coverage_snapshot(
            identities
        )
        if (
            coverage_before["vti_total"] != 4
            or coverage_before["vti_valid"] != 4
            or coverage_before["streamlines_total"] != 4
            or coverage_before["streamlines_valid"] != 4
        ):
            self._fail_validation_receipt_acceptance(
                "Persisted receipt store does not cover the four controlled VTI "
                "datasets and Streamlines caches."
            )
            return
        startup_failures = self._validation_receipt_normal_failures()
        if startup_failures:
            self._fail_validation_receipt_acceptance(
                "Session 2 did not start in clean Normal state: "
                + "; ".join(startup_failures)
                + "."
            )
            return
        self._report_validation_receipt_acceptance(
            "READY",
            "Persisted receipt store and controlled resource identities match.",
            next_action="Wait for persisted receipt reuse verification.",
        )
        self._report_validation_receipt_acceptance(
            "START",
            "Verifying persisted receipt reuse without expensive validators.",
        )
        self._start_validation_receipt_background_work()
        if not await self._wait_for_validation_receipt_tasks("SESSION_2"):
            return
        coverage = self._controller.validation_receipt_coverage_snapshot(identities)
        metrics = self._controller.validation_receipt_metrics_snapshot()
        failures = []
        if coverage["vti_valid"] != 4 or metrics.vti.persisted_reused != 4:
            failures.append("VTI persisted reuse was not 4/4")
        if metrics.vti.fresh_validated or metrics.vti.expensive_validation_calls:
            failures.append("an expensive VTI preflight ran unexpectedly")
        if (
            coverage["streamlines_valid"] != 4
            or metrics.streamlines.persisted_reused != 4
        ):
            failures.append("Streamlines persisted reuse was not 4/4")
        if (
            metrics.streamlines.fresh_validated
            or metrics.streamlines.expensive_validation_calls
            or metrics.streamlines.geometry_sha256_recomputed
        ):
            failures.append("Streamlines strong validation ran unexpectedly")
        if metrics.vti.invalidated or metrics.streamlines.invalidated:
            failures.append("a controlled resource identity was invalidated")
        if failures:
            self._fail_validation_receipt_acceptance("; ".join(failures) + ".")
            return
        session = self._validation_receipt_acceptance
        if session is None or not session.record("RESTORED"):
            return
        self._report_validation_receipt_acceptance(
            "COMPLETE",
            "Persisted receipts restored through the cheap path. "
            "VTI persisted_reused=4/4; "
            "fresh_validated=0; invalidated=0; expensive_preflight_calls=0; "
            "Streamlines persisted_reused=4/4; fresh_validated=0; "
            "invalidated=0; geometry_sha256_recomputed=0; "
            "strong_validation_calls=0.",
            next_action=(
                'Select "Smoke" in "Visualization" to verify the persisted VTI '
                "receipt through the production Flow consumer."
            ),
        )

    def _begin_validation_receipt_consumer_action(self, mode) -> None:
        """Observe only explicit Visualization selector actions in Session 2."""

        session = getattr(self, "_validation_receipt_acceptance", None)
        if (
            session is None
            or session.failed
            or session.terminal_emitted
            or session.expected_milestone not in {"Smoke", "Normal"}
        ):
            return
        if session.expected_milestone != mode.value:
            self._fail_validation_receipt_acceptance(
                "Unexpected Visualization selection: expected "
                f"{session.expected_milestone}, got {mode.value}."
            )
            return
        self._validation_receipt_acceptance_user_mode = mode
        status = (
            "Verifying persisted VTI receipt through the production Flow consumer."
            if mode.value == "Smoke"
            else "Verifying return to clean Normal visualization state."
        )
        self._report_validation_receipt_acceptance("START", status)

    def _complete_validation_receipt_consumer_action(self, mode, result) -> None:
        """Validate one explicitly selected Session 2 production transition."""

        if self._validation_receipt_acceptance_user_mode is not mode:
            return
        self._validation_receipt_acceptance_user_mode = None
        session = self._validation_receipt_acceptance
        if session is None or session.failed or session.terminal_emitted:
            return
        if mode.value == "Smoke":
            failures = self._validation_receipt_smoke_failures(result)
            completion = (
                "Persisted VTI receipt accepted by the production Flow consumer. "
                "persisted_receipt_consumer_check=PASS; KitCAE_grid_contract=PASS."
            )
            next_action = 'Select "Normal" in "Visualization".'
        else:
            failures = self._validation_receipt_normal_failures(result)
            completion = (
                "Production visualization returned to Normal; Flow and "
                "Streamlines are clean."
            )
            next_action = None
        if failures:
            self._fail_validation_receipt_acceptance("; ".join(failures) + ".")
            return
        if not session.record(mode.value):
            self._fail_validation_receipt_acceptance(
                "Receipt acceptance action could not be recorded in order."
            )
            return
        self._report_validation_receipt_acceptance(
            "COMPLETE",
            completion,
            next_action=next_action,
        )
        if next_action is not None or not session.complete():
            return
        from digital_twin_runtime_suite.app.manual_acceptance import (
            format_manual_acceptance_test_complete,
        )

        carb.log_warn(
            _with_dtrs_local_timestamp(
                format_manual_acceptance_test_complete(
                    "Persisted VTI and Streamlines validation receipt reuse passed."
                )
            )
        )
        self._controller.clear_validation_receipt_acceptance_checkpoint()
        self._validation_receipt_checkpoint = None
        self._validation_receipt_acceptance_owns_actions = False

    def _validation_receipt_smoke_failures(self, result) -> list[str]:
        """Return exact production-consumer failures without rerunning preflight."""

        consumer = self._controller.vti_receipt_consumer_check_snapshot()
        metrics = self._controller.validation_receipt_metrics_snapshot()
        snapshot = self._controller.visualization_snapshot()
        failures = []
        if not result.success:
            failures.append(f"real Smoke Attach failed: {result.message}")
        if snapshot.committed.value != "Smoke" or snapshot.pending is not None:
            failures.append("Smoke was not committed cleanly")
        if consumer.receipt_source != "PERSISTED":
            failures.append("Nominal Flow consumer did not use PERSISTED evidence")
        if consumer.selector != "server/load_normal":
            failures.append("consumer check did not attach the Nominal VTI dataset")
        if not consumer.kit_cae_grid_contract_passed:
            failures.append("Kit-CAE imported grid contract failed")
        if not consumer.flow_initial_readiness_passed:
            failures.append("Flow initial readiness failed")
        if metrics.vti.expensive_validation_calls:
            failures.append("consumer check unexpectedly ran expensive VTI preflight")
        return failures

    def _validation_receipt_normal_failures(self, result=None) -> list[str]:
        """Verify that acceptance leaves the ordinary startup presentation state."""

        from digital_twin_runtime_suite.app.visualization_mode import (
            VisualizationMode,
        )

        snapshot = self._controller.visualization_snapshot()
        presentation = (
            self._controller.primary_visualization_presentation_snapshot_in_kit()
        )
        xray = self._controller.xray_target_snapshot()
        combo_model = self._combo_index_model(self._visualization_combo)
        combo_is_normal = combo_model is not None and self._model_int(combo_model) == 0
        failures = []
        if result is not None and not result.success:
            failures.append(f"Normal transition failed: {result.message}")
        if snapshot.committed is not VisualizationMode.NORMAL or snapshot.pending:
            failures.append("Normal was not committed cleanly")
        if self._controller._flow_lifecycle_state != "DETACHED":
            failures.append("Flow lifecycle is not detached")
        if presentation.flow_source_prepared:
            failures.append("Flow source remains prepared")
        if presentation.smoke_presentation_visible:
            failures.append("Smoke renderer remains active")
        if presentation.streamlines_presentation_visible:
            failures.append("Streamlines presentation remains active")
        if presentation.streamlines_scheduler_tasks:
            failures.append("Streamlines scheduler remains active")
        if xray.override_owner is not None:
            failures.append("a visualization-owned X-Ray override remains active")
        if not combo_is_normal:
            failures.append("Visualization ComboBox does not display Normal")
        return failures

    async def _wait_for_validation_receipt_tasks(self, session_name: str) -> bool:
        """Wait with bounded five-second diagnostics only during active work."""

        started_at = time.monotonic()
        next_waiting_at = started_at + 5.0
        while True:
            tasks = tuple(
                task
                for task in (
                    self._airflow_background_validation_task,
                    self._streamlines_receipt_sweep_task,
                )
                if task is not None and not task.done()
            )
            if not tasks:
                return True
            now = time.monotonic()
            if now >= next_waiting_at:
                self._report_validation_receipt_acceptance(
                    "WAITING",
                    f"{session_name} validation remains active; "
                    f"elapsed_s={now - started_at:.1f}.",
                )
                next_waiting_at = now + 5.0
            await asyncio.sleep(0.1)

    def _fail_validation_receipt_acceptance(self, reason: str) -> None:
        """Stop the current guided session with one exact failure reason."""

        session = self._validation_receipt_acceptance
        if session is not None:
            session.mark_failed()
        self._report_validation_receipt_acceptance("FAIL", reason)
        self._validation_receipt_acceptance_owns_actions = False

    @staticmethod
    def _report_validation_receipt_acceptance(
        event: str,
        status: str,
        next_action: str | None = None,
    ) -> None:
        """Use the generic manual-acceptance formatter for receipt verification."""

        from digital_twin_runtime_suite.app.manual_acceptance import (
            format_manual_acceptance_event,
        )

        carb.log_warn(
            _with_dtrs_local_timestamp(
                format_manual_acceptance_event(
                    area="VALIDATION RECEIPTS | ACCEPTANCE",
                    event=event,
                    status=status,
                    next_action=next_action,
                )
            )
        )

    def _build_controller(self) -> None:
        source_root_setting = self._settings.get_as_string(
            f"{EXTENSION_SETTINGS}/sourceRoot"
        )
        if source_root_setting:
            source_root = _resolve_token_path(source_root_setting)
        else:
            source_root = _fallback_source_root()

        _ensure_source_root(source_root)

        config_path_setting = self._settings.get_as_string(
            f"{EXTENSION_SETTINGS}/configPath"
        )
        if config_path_setting:
            config_path = _resolve_token_path(config_path_setting)
        else:
            config_path = (
                source_root.parent.parent
                / "configs"
                / "digital_twin_runtime_suite.toml"
            ).resolve()

        # isort: off
        from digital_twin_runtime_suite.app.commands import RuntimeController
        from digital_twin_runtime_suite.app.airflow_dataset import (
            AirflowDatasetError,
            format_airflow_dataset_registry,
        )
        from digital_twin_runtime_suite.app.motion import (
            MultiRotationMotionController,
        )
        from digital_twin_runtime_suite.app.telemetry import SnapshotLatch
        from digital_twin_runtime_suite.app.telemetry import (
            SyntheticTelemetryProvider,
        )
        from digital_twin_runtime_suite.app.telemetry import TelemetryConfig

        # isort: on

        self._controller = RuntimeController(config_path)
        try:
            registry_log = format_airflow_dataset_registry(
                self._controller.airflow_dataset_registry()
            )
        except AirflowDatasetError as error:
            carb.log_error(
                _with_dtrs_local_timestamp(
                    f"DTRS AIRFLOW DATASET REGISTRY | Discovery failed: {error}"
                )
            )
        else:
            if not STAGE09_SUPPRESS_AIRFLOW_DIAGNOSTICS:
                carb.log_warn(_with_dtrs_local_timestamp(registry_log))
        self._set_application_title_version(self._controller.config)
        telemetry_config_path = (
            config_path.parent / "telemetry_provider.toml"
        ).resolve()
        self._telemetry_config_path = telemetry_config_path
        telemetry_config = TelemetryConfig.load(telemetry_config_path)
        self._telemetry_provider = SyntheticTelemetryProvider(telemetry_config)
        self._controller.set_workload_source(lambda: self._telemetry_provider.mode)
        self._telemetry_latch = SnapshotLatch()
        self._motion_controller = MultiRotationMotionController(
            self._controller.config.fan_motion_bindings
        )
        self._workload_modes = tuple(telemetry_config.modes)
        self._refresh_intervals = telemetry_config.allowed_refresh_intervals_s
        self._log_workload_cache_mapping(telemetry_config.default_mode)

    @staticmethod
    def _set_application_title_version(config) -> None:
        """Apply the derived display version without subscribing to USD titles."""

        app_window = (
            omni.appwindow.acquire_app_window_factory_interface().get_default_window()
        )
        if app_window is None or app_window.get_window() is None:
            carb.log_warn("DTRS could not access the native application window.")
            return
        carb.windowing.acquire_windowing_interface().set_window_title(
            app_window.get_window(),
            f"{config.app_name} {config.display_version}",
        )

    def _build_window(self) -> None:
        config = self._controller.config
        display_version = config.display_version
        default_asset = config.default_asset.label
        lighting = config.lighting

        self._hdri_model = ui.SimpleStringModel(lighting.hdri_path)
        self._exposure_model = ui.SimpleFloatModel(lighting.exposure)
        self._intensity_model = ui.SimpleFloatModel(lighting.intensity)
        self._show_hdri_background_model = ui.SimpleBoolModel(
            lighting.show_hdri_background
        )
        self._review_key_model = ui.SimpleBoolModel(lighting.review_key_light_enabled)
        self._review_key_intensity_model = ui.SimpleFloatModel(
            lighting.review_key_light_intensity
        )
        self._rotation_x_model = ui.SimpleFloatModel(lighting.rotation.x)
        self._rotation_y_model = ui.SimpleFloatModel(lighting.rotation.y)
        self._rotation_z_model = ui.SimpleFloatModel(lighting.rotation.z)
        self._grid_enabled_model = ui.SimpleBoolModel(config.grid.enabled)
        self._show_flow_debug_overlays_model = ui.SimpleBoolModel(False)
        self._show_flow_debug_overlays_model.add_value_changed_fn(
            lambda _model: self._schedule_apply_flow_debug_overlays()
        )
        self._grid_step_model = ui.SimpleFloatModel(config.grid.step)
        self._grid_width_model = ui.SimpleFloatModel(config.grid.width)
        receipt_preferences = config.validation_receipts
        self._reuse_vti_receipts_model = ui.SimpleBoolModel(
            receipt_preferences.reuse_verified_vti_receipts
        )
        self._reuse_streamlines_receipts_model = ui.SimpleBoolModel(
            receipt_preferences.reuse_verified_streamlines_cache_receipts
        )
        self._reuse_vti_receipts_model.add_value_changed_fn(
            self._on_validation_receipt_reuse_changed
        )
        self._reuse_streamlines_receipts_model.add_value_changed_fn(
            self._on_validation_receipt_reuse_changed
        )
        self._camera_position_x_model = ui.SimpleFloatModel(0.0)
        self._camera_position_y_model = ui.SimpleFloatModel(0.0)
        self._camera_position_z_model = ui.SimpleFloatModel(0.0)
        self._camera_rotation_x_model = ui.SimpleFloatModel(0.0)
        self._camera_rotation_y_model = ui.SimpleFloatModel(0.0)
        self._camera_rotation_z_model = ui.SimpleFloatModel(0.0)
        self._chassis_visibility_models = {
            group.group_id: ui.SimpleBoolModel(group.default_visible)
            for group in config.chassis_presentation.visibility_groups
        }
        self._face_panel_open_model = ui.SimpleBoolModel(
            config.chassis_presentation.face_panel.default_open
        )
        self._face_panel_open_state = (
            config.chassis_presentation.face_panel.default_open
        )
        if config.camera:
            self._set_camera_controls(config.camera)
        self._install_camera_edit_callbacks()

        self._window = ui.Window(
            f"{config.app_name} {display_version}",
            width=PANEL_WIDTH,
            height=620,
        )
        with self._window.frame:
            with ui.VStack(spacing=6, content_clipping=True):
                ui.Label(
                    f"{config.app_name} {display_version}",
                    height=20,
                    elided_text=True,
                    tooltip=f"{config.app_name} {display_version}",
                )
                with ui.HStack(height=28, spacing=4):
                    self._telemetry_tab_button = ui.Button(
                        "Telemetry",
                        clicked_fn=lambda: self._select_sidebar_tab("Telemetry"),
                        width=ui.Fraction(1),
                        height=28,
                    )
                    self._view_tab_button = ui.Button(
                        "View",
                        clicked_fn=lambda: self._select_sidebar_tab("View"),
                        width=ui.Fraction(1),
                        height=28,
                    )
                    self._config_tab_button = ui.Button(
                        "Config",
                        clicked_fn=lambda: self._select_sidebar_tab("Config"),
                        width=ui.Fraction(1),
                        height=28,
                    )

                self._telemetry_frame = ui.Frame(visible=True)
                with self._telemetry_frame:
                    self._build_telemetry_tab()

                self._view_frame = ui.Frame(visible=False)
                with self._view_frame:
                    self._build_view_tab(config)

                self._config_frame = ui.Frame(visible=False)
                with self._config_frame:
                    self._build_config_tab(config, default_asset)

        self._select_sidebar_tab("Telemetry")

    def _build_config_tab(self, config, default_asset: str) -> None:
        with ui.ScrollingFrame(
            horizontal_scrollbar_policy=ui.ScrollBarPolicy.SCROLLBAR_ALWAYS_OFF,
            vertical_scrollbar_policy=ui.ScrollBarPolicy.SCROLLBAR_ALWAYS_ON,
        ):
            with ui.VStack(spacing=6, content_clipping=True):
                self._build_config_section(
                    "Asset",
                    lambda: self._build_asset_config_controls(default_asset),
                )
                self._build_config_section(
                    "Lighting",
                    lambda: self._build_lighting_config_controls(config),
                    collapsed=True,
                )
                self._build_config_section(
                    "Grid",
                    self._build_grid_config_controls,
                    collapsed=True,
                )
                self._build_config_section(
                    "Camera",
                    self._build_camera_config_controls,
                    collapsed=True,
                )
                self._build_config_section(
                    "Telemetry provider",
                    self._build_telemetry_config_section,
                )

    def _build_view_tab(self, config) -> None:
        with ui.ScrollingFrame(
            horizontal_scrollbar_policy=ui.ScrollBarPolicy.SCROLLBAR_ALWAYS_OFF,
            vertical_scrollbar_policy=ui.ScrollBarPolicy.SCROLLBAR_ALWAYS_ON,
        ):
            with ui.VStack(spacing=6, content_clipping=True):
                self._build_config_section(
                    "Server Appearance",
                    lambda: self._build_server_appearance_controls(
                        config.chassis_presentation
                    ),
                )
                self._build_config_section(
                    "Visualization",
                    self._build_visualization_controls,
                )
                self._build_config_section(
                    "Streamlines",
                    self._build_streamlines_profile_controls,
                )
                self._build_config_section(
                    "Development validation",
                    self._build_validation_receipt_controls,
                    collapsed=True,
                )
                self._build_config_section(
                    "Airflow cache",
                    self._build_airflow_cache_controls,
                )

    def _build_server_appearance_controls(self, presentation) -> None:
        with ui.VStack(spacing=6, content_clipping=True):
            self._build_config_section(
                "Server enclosure",
                lambda: self._build_server_view_controls(presentation),
            )
            self._build_config_section(
                "Materials",
                lambda: self._build_material_controls(presentation),
            )

    def _build_validation_receipt_controls(self) -> None:
        """Build developer-only validation and geometry-preview controls."""

        with ui.VStack(spacing=6, content_clipping=True):
            with ui.HStack(height=24, spacing=6, content_clipping=True):
                ui.Label(
                    "Reuse verified VTI receipts",
                    width=ui.Fraction(1),
                )
                ui.CheckBox(model=self._reuse_vti_receipts_model, width=24)
            with ui.HStack(height=24, spacing=6, content_clipping=True):
                ui.Label(
                    "Reuse verified Streamlines cache receipts",
                    width=ui.Fraction(1),
                )
                ui.CheckBox(
                    model=self._reuse_streamlines_receipts_model,
                    width=24,
                )
            self._validation_receipt_status_label = ui.Label(
                "Receipt reuse is opt-in and identity checked.",
                height=32,
                word_wrap=True,
            )
            ui.Button(
                "Run RTX Mesh Time-Sample Probe",
                height=28,
                clicked_fn=self._run_rtx_mesh_time_sample_probe,
            )

    @staticmethod
    def _run_rtx_mesh_time_sample_probe() -> None:
        """Run the isolated renderer probe from one explicit user action."""

        from digital_twin_runtime_suite.app.renderer_diagnostic import (
            run_time_sampled_mesh_probe_in_kit,
        )

        run_time_sampled_mesh_probe_in_kit()

    def _build_streamlines_profile_controls(self) -> None:
        """Build production profile preference and shared material tuning."""

        from digital_twin_runtime_suite.app.streamlines.profile import (
            STREAMLINES_PROFILE_LABELS,
            StreamlinesProfileId,
        )

        with ui.VStack(spacing=6, content_clipping=True):
            profiles = tuple(StreamlinesProfileId)
            snapshot = self._controller.streamlines_profile_preference_snapshot()
            preferred = snapshot.preferred_profile
            with ui.HStack(height=24, spacing=6, content_clipping=True):
                ui.Label("Profile", width=SERVER_VIEW_LABEL_WIDTH)
                self._streamlines_profile_combo = ui.ComboBox(
                    profiles.index(preferred),
                    *(STREAMLINES_PROFILE_LABELS[item] for item in profiles),
                    width=ui.Fraction(1),
                )
            ui.Button(
                "Confirm Mesh Playback",
                height=28,
                clicked_fn=self._confirm_streamlines_mesh_playback,
            )
            ui.Button(
                "Report Mesh Playback Failure",
                height=28,
                clicked_fn=self._reject_streamlines_mesh_playback,
            )
            self._streamlines_xform_probe_button = ui.Button(
                "Run Streamlines Xform Probe",
                height=28,
                clicked_fn=self._schedule_streamlines_xform_probe,
            )
            self._streamlines_real_curve_ab_probe_button = ui.Button(
                "Run Real Curve A/B Probe",
                height=28,
                clicked_fn=self._schedule_real_curve_ab_probe,
            )
            self._streamlines_real_curve_ab_probe_button.enabled = False
            self._streamlines_full_state_ab_probe_button = ui.Button(
                "Run Full 80-State Streamlines Probe",
                height=28,
                clicked_fn=self._schedule_full_state_ab_probe,
            )
            self._streamlines_full_state_ab_probe_button.enabled = False
            ui.Button(
                "Analyze Fixed Speed Scale",
                height=28,
                clicked_fn=self._schedule_streamlines_speed_distribution,
            )
            ui.Button(
                "Accept Proposed Speed Scale",
                height=28,
                clicked_fn=self._accept_streamlines_speed_scale,
            )
            self._streamlines_global_tuning_frame = None
            self._streamlines_volume_tuning_frame = None
            self._streamlines_preview_button = None
            self._streamlines_accept_candidate_button = None
            ui.Label("Material Tuning", height=18)
            self._streamlines_material_tuning_combos = {
                "opacity": self._build_streamlines_tuning_combo(
                    "Opacity", 3, (0.40, 0.55, 0.70, 0.85, 1.00)
                ),
                "emission": self._build_streamlines_tuning_combo(
                    "Emission", 2, (0.5, 1.0, 1.5, 2.0, 3.0)
                ),
                "lighting": self._build_streamlines_tuning_combo(
                    "Lighting Influence", 2, (0.0, 0.1, 0.2, 0.35, 0.5)
                ),
            }
            ui.Button(
                "Apply Material Preview",
                height=28,
                clicked_fn=self._apply_streamlines_material_preview,
            )
            ui.Button(
                "Accept Material Candidate",
                height=28,
                clicked_fn=self._accept_streamlines_material_candidate,
            )
            self._streamlines_material_status_label = ui.Label(
                "Material preview changes no cache, workload, profile, or scheduler.",
                height=32,
                word_wrap=True,
            )
        profile_model = self._combo_index_model(self._streamlines_profile_combo)
        if profile_model:
            profile_model.add_value_changed_fn(
                self._on_streamlines_profile_preference_changed
            )

    def _build_streamlines_tuning_combo(
        self,
        label: str,
        default_index: int,
        values,
    ):
        with ui.HStack(height=24, spacing=6, content_clipping=True):
            ui.Label(label, width=SERVER_VIEW_LABEL_WIDTH)
            return ui.ComboBox(
                default_index,
                *(str(value) for value in values),
                width=ui.Fraction(1),
            )

    def _on_streamlines_profile_preference_changed(self, model) -> None:
        from digital_twin_runtime_suite.app.streamlines.profile import (
            StreamlinesProfileId,
        )

        if self._updating_streamlines_profile_combo:
            return
        self._cancel_streamlines_material_preview()
        profiles = tuple(StreamlinesProfileId)
        index = self._model_int(model)
        if not 0 <= index < len(profiles):
            return
        profile_id = profiles[index]
        visualization = self._controller.visualization_snapshot()
        if visualization.committed.value != "Streamlines":
            self._controller.set_streamlines_profile_preference(profile_id)
            return
        start_acceptance = getattr(
            self._controller,
            "phase44b_cache_playback_start_profile",
            None,
        )
        if start_acceptance:
            start_acceptance(profile_id)
        task = self._streamlines_profile_task
        if task is not None and not task.done():
            task.cancel()
        self._streamlines_profile_task = asyncio.ensure_future(
            self._run_streamlines_profile_transition(profile_id)
        )

    async def _run_streamlines_profile_transition(self, profile_id) -> None:
        """Contain one production cached-profile transaction at the UI edge."""

        try:
            result = (
                await self._controller.request_streamlines_profile_transition_in_kit(
                    profile_id,
                    status_callback=self._set_streamlines_status,
                )
            )
            self._set_streamlines_status(result.message)
            observe_acceptance = getattr(
                self._controller,
                "phase44b_cache_playback_observe_profile_result",
                None,
            )
            if observe_acceptance:
                observe_acceptance(profile_id, result)
            if result.success:
                return
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._set_streamlines_status(f"Streamlines profile switch failed: {error}")
        finally:
            if self._streamlines_profile_task is asyncio.current_task():
                self._streamlines_profile_task = None
        committed = (
            self._controller.streamlines_profile_preference_snapshot().committed_profile
        )
        if committed is None or self._streamlines_profile_combo is None:
            return
        profiles = tuple(type(committed))
        self._updating_streamlines_profile_combo = True
        try:
            model = self._combo_index_model(self._streamlines_profile_combo)
            if model is not None:
                model.set_value(profiles.index(committed))
        finally:
            self._updating_streamlines_profile_combo = False

    def _apply_streamlines_material_preview(self) -> None:
        """Schedule one cancellable material-only preview and performance gate."""

        task = self._streamlines_material_preview_task
        if task is not None and not task.done():
            task.cancel()
            self._controller.cancel_streamlines_material_preview_measurement()
        self._streamlines_material_preview_task = asyncio.ensure_future(
            self._run_streamlines_material_preview()
        )

    async def _run_streamlines_material_preview(self) -> None:
        """Read current presets once, then await stabilized material evidence."""

        options = {
            "opacity": (0.40, 0.55, 0.70, 0.85, 1.00),
            "emission": (0.5, 1.0, 1.5, 2.0, 3.0),
            "lighting": (0.0, 0.1, 0.2, 0.35, 0.5),
        }
        selected = {
            name: values[
                self._model_int(
                    self._combo_index_model(
                        self._streamlines_material_tuning_combos[name]
                    )
                )
            ]
            for name, values in options.items()
        }
        try:
            presentation = self._controller.streamlines_presentation_contract(
                opacity=selected["opacity"],
                emission_intensity=selected["emission"],
                lighting_influence=selected["lighting"],
            )
            receipt = await self._controller.apply_streamlines_material_preview_in_kit(
                presentation,
                status_callback=self._set_streamlines_status,
            )
            message = (
                "Material preview complete: bound=True; cache_build=0; "
                "cache_rebuild=0; "
                f"fps_avg={receipt.viewport_fps_average}; "
                f"signature={receipt.material.presentation_signature[:12]}."
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            message = f"Material preview failed: {error}"
            carb.log_error(_with_dtrs_local_timestamp(message))
        finally:
            if self._streamlines_material_preview_task is asyncio.current_task():
                self._streamlines_material_preview_task = None
        if self._streamlines_material_status_label is not None:
            self._streamlines_material_status_label.text = message

    def _schedule_build_constant_topology_prototype(self) -> None:
        """Launch only the Volume Coverage / Nominal prototype build."""

        if self._airflow_task and not self._airflow_task.done():
            self._set_streamlines_status("Airflow operation is already in progress.")
            return
        self._set_streamlines_cache_buttons_enabled(False)
        self._airflow_task = asyncio.ensure_future(
            self._build_constant_topology_prototype()
        )

    def _schedule_streamlines_speed_distribution(self) -> None:
        task = self._streamlines_speed_distribution_task
        if task is not None and not task.done():
            return
        self._streamlines_speed_distribution_task = asyncio.ensure_future(
            self._collect_streamlines_speed_distribution()
        )

    async def _collect_streamlines_speed_distribution(self) -> None:
        try:
            proposal = await self._controller.collect_streamlines_speed_scale_proposal(
                status_callback=self._set_streamlines_status,
            )
            message = (
                "Fixed speed scale proposed: 0.."
                f"{proposal.scale.maximum:.6g} {proposal.scale.units}."
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            message = f"Speed distribution failed: {error}"
            carb.log_error(_with_dtrs_local_timestamp(message))
        finally:
            self._streamlines_speed_distribution_task = None
        if self._streamlines_material_status_label is not None:
            self._streamlines_material_status_label.text = message

    def _accept_streamlines_speed_scale(self) -> None:
        try:
            scale = self._controller.accept_streamlines_speed_scale_proposal()
            message = f"Fixed speed scale accepted: 0..{scale.maximum:.6g}."
        except Exception as error:
            message = f"Speed scale acceptance failed: {error}"
            carb.log_error(_with_dtrs_local_timestamp(message))
        if self._streamlines_material_status_label is not None:
            self._streamlines_material_status_label.text = message

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

    def _accept_streamlines_material_candidate(self) -> None:
        """Accept the last applied immutable session presentation snapshot."""

        try:
            candidate = self._controller.accept_streamlines_material_candidate()
            message = (
                "Material candidate accepted for this session: "
                f"signature={candidate.signature[:12]}."
            )
        except Exception as error:
            message = f"Material candidate acceptance failed: {error}"
            carb.log_error(_with_dtrs_local_timestamp(message))
        if self._streamlines_material_status_label is not None:
            self._streamlines_material_status_label.text = message

    def _schedule_streamlines_phase44a_preview(
        self,
    ) -> None:
        """Read current production workload and launch one disposable preview."""

        task = getattr(self, "_streamlines_preview_task", None)
        if task is not None and not task.done():
            self._cancel_streamlines_profile_preview()

        workload_model = self._combo_index_model(self._workload_combo)
        profile_id, tuning = self._selected_streamlines_profile_tuning()
        workload_index = self._model_int(workload_model)
        if not 0 <= workload_index < len(self._workload_modes):
            raise ValueError("Telemetry workload selection is out of range.")
        workload = self._workload_modes[workload_index]
        if self._streamlines_preview_button is not None:
            self._streamlines_preview_button.enabled = False
        accept_button = getattr(self, "_streamlines_accept_candidate_button", None)
        if accept_button is not None:
            accept_button.enabled = False
        self._streamlines_preview_task = asyncio.ensure_future(
            self._run_streamlines_phase44a_preview(
                workload,
                profile_id,
                tuning,
            )
        )

    def _selected_streamlines_profile_tuning(self):
        """Translate visible developer controls without geometry calculations."""

        from digital_twin_runtime_suite.app.streamlines.profile import (
            StreamlinesProfileId,
        )
        from digital_twin_runtime_suite.app.streamlines.tuning import (
            global_tuning_from_indices,
            volume_tuning_from_indices,
        )

        profiles = tuple(StreamlinesProfileId)
        profile_index = self._model_int(
            self._combo_index_model(self._streamlines_profile_combo)
        )
        profile_id = profiles[profile_index]
        if profile_id is StreamlinesProfileId.GLOBAL_FLOW_PATH:
            models = self._streamlines_global_tuning_combos
            selection = global_tuning_from_indices(
                self._model_int(self._combo_index_model(models["seed_count"])),
                self._model_int(self._combo_index_model(models["max_steps"])),
                self._model_int(self._combo_index_model(models["step_scale"])),
            )
        else:
            models = self._streamlines_volume_tuning_combos
            selection = volume_tuning_from_indices(
                self._model_int(self._combo_index_model(models["section_count"])),
                self._model_int(self._combo_index_model(models["seeds_per_section"])),
                self._model_int(self._combo_index_model(models["max_steps"])),
                self._model_int(self._combo_index_model(models["step_scale"])),
            )
        return profile_id, selection

    async def _run_streamlines_phase44a_preview(
        self,
        workload: str,
        profile_id,
        tuning,
    ) -> None:
        """Keep preview execution and UI recovery inside one task boundary."""

        self._set_streamlines_preview_status(
            f"Preparing {profile_id.value} / {workload} preview: "
            f"max_steps={tuning.max_steps}; "
            f"step_scale={tuning.step_scale_label}."
        )
        from digital_twin_runtime_suite.app.streamlines.tuning import (
            StreamlinesPreviewSelectionMismatchError,
            StreamlinesPreviewWorkloadMismatchError,
        )

        completed = False
        try:
            results = await self._controller.run_streamlines_profile_preview(
                status_callback=self._set_streamlines_preview_status,
                profile_id=profile_id,
                workload=workload,
                tuning_selection=tuning,
            )
            result = results[0]
            self._set_streamlines_preview_status(
                f"{workload} preview ready: "
                f"curves={result.curve_count}; points={result.point_count}."
            )
            completed = True
        except asyncio.CancelledError:
            raise
        except (
            StreamlinesPreviewSelectionMismatchError,
            StreamlinesPreviewWorkloadMismatchError,
        ) as error:
            message = str(error)
            self._set_streamlines_preview_status(message)
            carb.log_error(_with_dtrs_local_timestamp(message))
        except Exception as error:
            message = f"{workload} Streamlines preview failed: {error}"
            self._set_streamlines_preview_status(message)
            carb.log_error(_with_dtrs_local_timestamp(message))
        finally:
            current_task = asyncio.current_task()
            owner_task = getattr(self, "_streamlines_preview_task", None)
            if owner_task is None or owner_task is current_task:
                self._streamlines_preview_task = None
                if self._streamlines_preview_button is not None:
                    self._streamlines_preview_button.enabled = True
                accept_button = getattr(
                    self,
                    "_streamlines_accept_candidate_button",
                    None,
                )
                if accept_button is not None:
                    accept_button.enabled = completed

    def _cancel_streamlines_profile_preview(self) -> None:
        """Cancel the one authoritative preview and its delayed measurement."""

        task = getattr(self, "_streamlines_preview_task", None)
        if task is not None and not task.done():
            task.cancel()
        self._streamlines_preview_task = None
        controller = getattr(self, "_controller", None)
        if controller:
            cancel_preview = getattr(
                controller,
                "cancel_streamlines_profile_preview_measurement",
                None,
            )
            if cancel_preview:
                cancel_preview()
        preview_button = getattr(self, "_streamlines_preview_button", None)
        if preview_button is not None:
            preview_button.enabled = True
        accept_button = getattr(self, "_streamlines_accept_candidate_button", None)
        if accept_button is not None:
            accept_button.enabled = False

    def _cancel_streamlines_material_preview(self) -> None:
        """Cancel delayed material evidence after profile/workload supersession."""

        task = getattr(self, "_streamlines_material_preview_task", None)
        if task is not None and not task.done():
            task.cancel()
        self._streamlines_material_preview_task = None
        controller = getattr(self, "_controller", None)
        if controller:
            controller.cancel_streamlines_material_preview_measurement()

    def _accept_current_streamlines_candidate(self) -> None:
        accepted = self._controller.accept_current_streamlines_profile_candidate()
        message = (
            "Current profile candidate accepted for this session."
            if accepted
            else "Run the expected profile preview before accepting it."
        )
        self._set_streamlines_preview_status(message)

    def _set_streamlines_preview_status(self, message: str) -> None:
        """Publish bounded preview progress without changing primary mode."""

        label = self._streamlines_preview_status_label
        if label is None:
            return
        label.text = _compact_text(message)
        label.tooltip = message

    def _on_validation_receipt_reuse_changed(self, _model) -> None:
        """Persist preferences immediately; validation remains background-owned."""

        if not self._controller:
            return
        reuse_vti = bool(self._reuse_vti_receipts_model.as_bool)
        reuse_streamlines = bool(self._reuse_streamlines_receipts_model.as_bool)
        try:
            path = self._controller.save_validation_receipt_reuse_override(
                reuse_verified_vti_receipts=reuse_vti,
                reuse_verified_streamlines_cache_receipts=reuse_streamlines,
            )
        except Exception as error:
            message = f"Validation receipt settings were not saved: {error}"
            if self._validation_receipt_status_label:
                self._validation_receipt_status_label.text = _compact_text(message)
                self._validation_receipt_status_label.tooltip = message
            carb.log_error(_with_dtrs_local_timestamp(message))
            return
        message = f"Receipt reuse settings saved to {path.name}."
        if self._validation_receipt_status_label:
            self._validation_receipt_status_label.text = _compact_text(message)
            self._validation_receipt_status_label.tooltip = message
        if reuse_vti and reuse_streamlines:
            self._begin_validation_receipt_acceptance_session1()
        elif reuse_streamlines:
            self._start_validation_receipt_background_work()

    def _build_material_controls(self, presentation) -> None:
        materials = presentation.materials
        self._build_config_section(
            "X-Ray",
            lambda: self._build_xray_controls(presentation),
            collapsed=True,
        )
        self._build_config_section(
            "Normal Map Scale",
            lambda: self._build_normal_map_scale_controls(materials),
            collapsed=True,
        )

    def _build_xray_controls(self, presentation) -> None:
        """Build transient target selection before persistent Fresnel values.

        The config defines available groups; these Kit models deliberately hold
        no saved selection so every startup and reload begins with X-Ray OFF.
        """

        for group in presentation.xray_target_groups:
            model = self._xray_target_models.setdefault(
                group.group_id,
                # X-Ray bindings are transient Session Layer state. Parameters
                # persist, but a fresh app/config lifecycle always starts OFF.
                ui.SimpleBoolModel(False),
            )
            with ui.HStack(height=24, spacing=6, content_clipping=True):
                ui.Label(
                    group.label,
                    width=SERVER_VIEW_LABEL_WIDTH,
                    elided_text=True,
                    tooltip="Apply or release the production Fresnel material.",
                )
                self._xray_target_checkboxes[group.group_id] = ui.CheckBox(model=model)
        self._build_xray_fresnel_controls(presentation.materials.xray)
        ui.Button(
            "Apply",
            clicked_fn=self._apply_xray_material,
            height=26,
            width=ui.Percent(100),
        )

    def _build_xray_fresnel_controls(self, xray) -> None:
        """Build the single production-owned Fresnel parameter set."""

        from digital_twin_runtime_suite.app.view_controls import rgb_to_hex

        if not hasattr(self, "_xray_fresnel_models"):
            self._xray_fresnel_models = {
                "facing": ui.SimpleStringModel(rgb_to_hex(xray.facing_color)),
                "edge": ui.SimpleStringModel(rgb_to_hex(xray.edge_color)),
                "center": ui.SimpleFloatModel(xray.edge_center),
                "softness": ui.SimpleFloatModel(xray.edge_softness),
                "sharpness": ui.SimpleFloatModel(xray.edge_sharpness),
                "facing_roughness": ui.SimpleFloatModel(xray.facing_roughness),
                "edge_roughness": ui.SimpleFloatModel(xray.edge_roughness),
                "facing_opacity": ui.SimpleFloatModel(xray.facing_opacity),
                "edge_opacity": ui.SimpleFloatModel(xray.edge_opacity),
                "facing_emission": ui.SimpleFloatModel(xray.facing_emission),
                "edge_emission": ui.SimpleFloatModel(xray.edge_emission),
                "emission_scale": ui.SimpleFloatModel(xray.emission_scale),
            }
        for label, key in (("Facing Color", "facing"), ("Edge Color", "edge")):
            with ui.HStack(height=24):
                ui.Label(label, width=SERVER_VIEW_LABEL_WIDTH)
                ui.StringField(
                    model=self._xray_fresnel_models[key], width=ui.Fraction(1)
                )
        for label, key in (
            ("Edge Center", "center"),
            ("Edge Softness", "softness"),
            ("Edge Sharpness", "sharpness"),
            ("Facing Roughness", "facing_roughness"),
            ("Edge Roughness", "edge_roughness"),
            ("Facing Opacity", "facing_opacity"),
            ("Edge Opacity", "edge_opacity"),
            ("Facing Emission", "facing_emission"),
            ("Edge Emission", "edge_emission"),
            ("Emission Scale", "emission_scale"),
        ):
            with ui.HStack(height=24):
                ui.Label(label, width=SERVER_VIEW_LABEL_WIDTH)
                ui.FloatDrag(
                    model=self._xray_fresnel_models[key],
                    width=ui.Fraction(1),
                    precision=3,
                )

    def _build_normal_map_scale_controls(self, materials) -> None:
        if self._normal_map_scale_model is None:
            self._normal_map_scale_model = ui.SimpleFloatModel(
                materials.normal_map_scale
            )
        with ui.HStack(height=24, spacing=6, content_clipping=True):
            ui.Label("Scale", width=SERVER_VIEW_LABEL_WIDTH, elided_text=True)
            ui.FloatDrag(
                model=self._normal_map_scale_model,
                width=ui.Fraction(1),
                precision=2,
            )
        ui.Button(
            "Apply",
            clicked_fn=self._apply_normal_map_scale,
            height=26,
            width=ui.Percent(100),
        )

    def _build_server_view_controls(self, presentation) -> None:
        face_panel = presentation.face_panel
        if not presentation.visibility_groups and not face_panel.enabled:
            ui.Label("No visibility groups configured.", height=34, elided_text=True)
            return

        for group in presentation.visibility_groups:
            model = self._chassis_visibility_models.get(group.group_id)
            if not model:
                model = ui.SimpleBoolModel(group.default_visible)
                self._chassis_visibility_models[group.group_id] = model
            with ui.HStack(height=24, spacing=6, content_clipping=True):
                ui.Label(
                    group.label,
                    width=SERVER_VIEW_LABEL_WIDTH,
                    elided_text=True,
                    tooltip=group.label,
                )
                ui.CheckBox(model=model)
        if face_panel.enabled:
            from digital_twin_runtime_suite.app.view_controls import (
                face_panel_action_label,
            )

            with ui.HStack(height=24, spacing=6, content_clipping=True):
                action_text = face_panel_action_label(self._face_panel_open_state)
                self._face_panel_action_label = ui.Label(
                    action_text,
                    width=SERVER_VIEW_LABEL_WIDTH,
                    elided_text=True,
                    tooltip=action_text,
                )
                ui.CheckBox(model=self._face_panel_open_model)
        ui.Button(
            "Apply",
            clicked_fn=self._schedule_apply_chassis_visibility_controls,
            height=26,
            width=ui.Percent(100),
        )

    def _build_config_section(self, title, build_fn, collapsed: bool = False) -> None:
        with ui.CollapsableFrame(
            title,
            collapsed=collapsed,
            height=0,
            build_header_fn=self._build_telemetry_group_header,
            style={
                "CollapsableFrame": {
                    "background_color": 0xFF3A3A3A,
                    "secondary_color": 0xFF464646,
                    "border_color": 0xFF5A5A5A,
                    "border_width": 1,
                    "border_radius": 2,
                }
            },
        ):
            with ui.VStack(spacing=6, height=0, content_clipping=True):
                ui.Spacer(height=2)
                build_fn()
                ui.Spacer(height=2)

    def _build_asset_config_controls(self, default_asset: str) -> None:
        ui.Label("Loaded asset", height=18)
        self._asset_label = ui.Label(
            _compact_text(default_asset),
            height=18,
            elided_text=True,
            tooltip=default_asset,
        )
        ui.Button(
            "Load",
            clicked_fn=self._schedule_load,
            height=26,
            width=ui.Percent(100),
        )
        ui.Button(
            "Reload Config",
            clicked_fn=self._reload_config,
            height=26,
            width=ui.Percent(100),
        )
        self._status_label = ui.Label("Ready", height=34, elided_text=True)

    def _build_smoke_tuning_row(
        self,
        label: str,
        field_name: str,
        value: float,
    ) -> None:
        from digital_twin_runtime_suite.app.config import (
            SMOKE_TUNING_VALUE_OPTIONS,
        )
        from digital_twin_runtime_suite.app.view_controls import (
            smoke_tuning_option_index,
        )

        choices = SMOKE_TUNING_VALUE_OPTIONS[field_name]
        with ui.HStack(height=24, spacing=6, content_clipping=True):
            ui.Label(label, width=SERVER_VIEW_LABEL_WIDTH)
            self._smoke_tuning_combos[field_name] = ui.ComboBox(
                smoke_tuning_option_index(field_name, value),
                *(f"{choice:g}" for choice in choices),
                width=ui.Fraction(1),
            )

    def _build_smoke_color_controls(
        self,
        base_color: tuple[float, float, float],
    ) -> None:
        from digital_twin_runtime_suite.app.view_controls import (
            rgb_to_hex,
            rgb_to_hsv,
        )

        hue, saturation, value = rgb_to_hsv(base_color)
        self._updating_smoke_color_controls = False
        self._smoke_color_input_source = "hex"
        self._smoke_color_hex_model = ui.SimpleStringModel(rgb_to_hex(base_color))
        self._smoke_color_hue_model = ui.SimpleFloatModel(hue)
        self._smoke_color_saturation_model = ui.SimpleFloatModel(saturation)
        self._smoke_color_value_model = ui.SimpleFloatModel(value)
        with ui.HStack(height=24, spacing=6, content_clipping=True):
            ui.Label("Color", width=SERVER_VIEW_LABEL_WIDTH)
            ui.StringField(
                model=self._smoke_color_hex_model,
                width=ui.Fraction(1),
            )
            self._smoke_color_preview_frame = ui.Frame(width=32, height=20)
        with ui.HStack(height=24, spacing=6, content_clipping=True):
            ui.Label("HSV", width=SERVER_VIEW_LABEL_WIDTH)
            ui.Label("H", width=12)
            ui.FloatField(model=self._smoke_color_hue_model, width=ui.Fraction(1))
            ui.Label("S", width=12)
            ui.FloatField(
                model=self._smoke_color_saturation_model,
                width=ui.Fraction(1),
            )
            ui.Label("V", width=12)
            ui.FloatField(model=self._smoke_color_value_model, width=ui.Fraction(1))
        self._smoke_color_hex_model.add_value_changed_fn(
            self._on_smoke_color_hex_changed
        )
        for model in (
            self._smoke_color_hue_model,
            self._smoke_color_saturation_model,
            self._smoke_color_value_model,
        ):
            model.add_value_changed_fn(self._on_smoke_color_hsv_changed)
        self._set_pending_smoke_color(base_color)

    def _set_pending_smoke_color(
        self,
        base_color: tuple[float, float, float],
    ) -> None:
        from digital_twin_runtime_suite.app.view_controls import (
            rgb_to_hex,
            rgb_to_hsv,
        )

        self._updating_smoke_color_controls = True
        try:
            hue, saturation, value = rgb_to_hsv(base_color)
            self._smoke_color_hex_model.set_value(rgb_to_hex(base_color))
            self._smoke_color_hue_model.set_value(hue)
            self._smoke_color_saturation_model.set_value(saturation)
            self._smoke_color_value_model.set_value(value)
        finally:
            self._updating_smoke_color_controls = False
        self._refresh_smoke_color_preview(base_color)

    def _refresh_smoke_color_preview(
        self,
        base_color: tuple[float, float, float],
    ) -> None:
        from digital_twin_runtime_suite.app.view_controls import (
            rgb_to_omniui_color,
        )

        with self._smoke_color_preview_frame:
            ui.Rectangle(
                style={"background_color": rgb_to_omniui_color(base_color)},
                width=ui.Percent(100),
                height=ui.Percent(100),
            )

    def _on_smoke_color_hex_changed(self, _model) -> None:
        if self._updating_smoke_color_controls:
            return
        from digital_twin_runtime_suite.app.view_controls import (
            hex_to_rgb,
            string_model_value,
        )

        self._smoke_color_input_source = "hex"
        try:
            color = hex_to_rgb(string_model_value(self._smoke_color_hex_model))
        except ValueError:
            return
        self._set_pending_smoke_color(color)

    def _on_smoke_color_hsv_changed(self, _model) -> None:
        if self._updating_smoke_color_controls:
            return
        from digital_twin_runtime_suite.app.view_controls import (
            build_smoke_base_color_from_models,
        )

        self._smoke_color_input_source = "hsv"
        try:
            color = build_smoke_base_color_from_models(
                source="hsv",
                hex_model=self._smoke_color_hex_model,
                hue_model=self._smoke_color_hue_model,
                saturation_model=self._smoke_color_saturation_model,
                value_model=self._smoke_color_value_model,
            )
        except ValueError:
            return
        self._set_pending_smoke_color(color)

    def _build_emitter_layout_row(
        self,
        label: str,
        field_name: str,
        value: float | int,
    ) -> None:
        from digital_twin_runtime_suite.app.config import (
            EMITTER_LAYOUT_VALUE_OPTIONS,
        )
        from digital_twin_runtime_suite.app.view_controls import (
            emitter_layout_option_index,
        )

        choices = EMITTER_LAYOUT_VALUE_OPTIONS[field_name]
        labels = (
            (
                ("Minimum" if choice == 0 else f"{choice:.0%}")
                if field_name == "size"
                else (
                    f"{choice:.0%}"
                    if field_name in {"depth", "horizontal_margin", "vertical_margin"}
                    else f"{choice:g}"
                )
            )
            for choice in choices
        )
        with ui.HStack(height=24, spacing=6, content_clipping=True):
            ui.Label(label, width=SERVER_VIEW_LABEL_WIDTH)
            self._emitter_layout_combos[field_name] = ui.ComboBox(
                emitter_layout_option_index(field_name, value),
                *labels,
                width=ui.Fraction(1),
            )

    def _build_airflow_cache_controls(self) -> None:
        cache = self._controller.config.simulation_cache
        wrapper_name = self._airflow_cache_selector_text()
        self._airflow_cache_selector_label = ui.Label(
            _compact_text(wrapper_name),
            height=18,
            elided_text=True,
            tooltip=wrapper_name,
        )
        with ui.HStack(height=26, spacing=6, content_clipping=True):
            ui.Button(
                "Attach",
                clicked_fn=self._schedule_attach_airflow,
                width=ui.Fraction(1),
            )
            ui.Button(
                "Detach",
                clicked_fn=self._schedule_detach_airflow,
                width=ui.Fraction(1),
            )
        with ui.HStack(height=26, spacing=6, content_clipping=True):
            ui.Button(
                "Play",
                clicked_fn=self._play_airflow,
                width=ui.Fraction(1),
            )
            ui.Button(
                "Pause",
                clicked_fn=self._pause_airflow,
                width=ui.Fraction(1),
            )
            ui.Button(
                "Reset",
                clicked_fn=self._reset_airflow,
                width=ui.Fraction(1),
            )
        with ui.HStack(height=24, spacing=6, content_clipping=True):
            ui.Button(
                "Set Overview",
                clicked_fn=lambda: self._capture_flow_camera_bookmark("Overview"),
                width=ui.Fraction(1),
            )
            ui.Button(
                "Set Close-up",
                clicked_fn=lambda: self._capture_flow_camera_bookmark("Close-up"),
                width=ui.Fraction(1),
            )

        with ui.HStack(height=24, spacing=6, content_clipping=True):
            ui.Button(
                "Overview",
                clicked_fn=lambda: self._schedule_apply_flow_camera_bookmark(
                    "Overview"
                ),
                width=ui.Fraction(1),
            )
            ui.Button(
                "Close-up",
                clicked_fn=lambda: self._schedule_apply_flow_camera_bookmark(
                    "Close-up"
                ),
                width=ui.Fraction(1),
            )
        with ui.HStack(height=24, spacing=6, content_clipping=True):
            ui.Label("Show debug overlays", width=SERVER_VIEW_LABEL_WIDTH)
            ui.CheckBox(model=self._show_flow_debug_overlays_model)
        self._smoke_tuning_combos = {}
        smoke_tuning = cache.smoke_tuning
        ui.Label("Smoke Tuning", height=22)
        ui.Label("Appearance", height=18)
        self._build_smoke_tuning_row("Density", "density", smoke_tuning.density)
        self._build_smoke_tuning_row(
            "Brightness",
            "brightness",
            smoke_tuning.brightness,
        )
        self._build_smoke_tuning_row("Ambient", "ambient", smoke_tuning.ambient)
        self._build_smoke_tuning_row(
            "Shadow density",
            "shadow_density",
            smoke_tuning.shadow_density,
        )
        self._build_smoke_color_controls(smoke_tuning.base_color)
        ui.Label("Dynamics", height=18)
        self._build_smoke_tuning_row("Damping", "damping", smoke_tuning.damping)
        self._build_smoke_tuning_row("Fade", "fade", smoke_tuning.fade)
        self._build_smoke_tuning_row("Sharpness", "sharpness", smoke_tuning.sharpness)
        self._build_smoke_tuning_row(
            "Vorticity",
            "vorticity",
            smoke_tuning.vorticity,
        )
        self._build_smoke_tuning_row(
            "Velocity scale ×",
            "velocity_scale_multiplier",
            smoke_tuning.velocity_scale_multiplier,
        )
        self._build_smoke_tuning_row(
            "Time scale",
            "time_scale",
            smoke_tuning.time_scale,
        )
        ui.Label("Quality", height=18)
        self._build_smoke_tuning_row(
            "Raymarch quality",
            "raymarch_quality",
            smoke_tuning.raymarch_quality,
        )
        from digital_twin_runtime_suite.app.flow.quality import (
            KIT_CAE_FLOW_VOXEL_RESOLUTION_OPTIONS,
        )

        with ui.HStack(height=24, spacing=6, content_clipping=True):
            ui.Label("Flow voxel resolution", width=SERVER_VIEW_LABEL_WIDTH)
            self._flow_voxel_resolution_combo = ui.ComboBox(
                0,
                *(str(value) for value in KIT_CAE_FLOW_VOXEL_RESOLUTION_OPTIONS),
                width=ui.Fraction(1),
            )
        ui.Button(
            "Apply Smoke Settings",
            clicked_fn=self._schedule_apply_smoke_tuning,
            height=26,
            width=ui.Percent(100),
        )
        ui.Button(
            "Apply & Restart Flow",
            clicked_fn=self._schedule_apply_flow_voxel_resolution,
            height=26,
            width=ui.Percent(100),
        )
        self._emitter_layout_combos = {}
        emitter_layout = cache.emitter_layout
        ui.Label("Emitter Layout", height=22)
        self._build_emitter_layout_row(
            "Emitters per row",
            "emitters_per_row",
            emitter_layout.emitters_per_row,
        )
        self._build_emitter_layout_row(
            "Emitter rows",
            "rows",
            emitter_layout.rows,
        )
        self._build_emitter_layout_row(
            "Depth position",
            "depth",
            emitter_layout.depth,
        )
        self._build_emitter_layout_row(
            "Emitter size",
            "size",
            emitter_layout.size,
        )
        self._build_emitter_layout_row(
            "Horizontal margin",
            "horizontal_margin",
            emitter_layout.horizontal_margin,
        )
        self._build_emitter_layout_row(
            "Vertical margin",
            "vertical_margin",
            emitter_layout.vertical_margin,
        )
        ui.Button(
            "Apply Emitter Layout",
            clicked_fn=self._schedule_apply_emitter_layout,
            height=26,
            width=ui.Percent(100),
        )

    def _build_lighting_config_controls(self, config) -> None:
        self._lighting_status_label = ui.Label(
            _compact_text(f"HDRI: {config.default_hdri_path.name}"),
            height=34,
            elided_text=True,
            tooltip=f"HDRI: {config.default_hdri_path.name}",
        )
        ui.Label("HDRI file", height=18)
        ui.StringField(
            model=self._hdri_model,
            height=24,
            width=ui.Percent(100),
        )
        self._build_float_row("Exposure", self._exposure_model)
        self._build_float_row("HDRI intensity", self._intensity_model)
        with ui.HStack(height=24, spacing=6, content_clipping=True):
            ui.Label("Show HDRI", width=ROW_LABEL_WIDTH)
            ui.CheckBox(model=self._show_hdri_background_model)
        with ui.HStack(height=24, spacing=6, content_clipping=True):
            ui.Label("Key", width=ROW_LABEL_WIDTH)
            ui.CheckBox(model=self._review_key_model)
        self._build_float_row("Key intensity", self._review_key_intensity_model)
        ui.Label("Dome rotation", height=18)
        self._build_float_row("Rotate X", self._rotation_x_model)
        self._build_float_row("Rotate Y", self._rotation_y_model)
        self._build_float_row("Rotate Z", self._rotation_z_model)
        ui.Button(
            "Apply",
            clicked_fn=self._schedule_apply_lighting,
            height=26,
            width=ui.Percent(100),
        )
        ui.Button(
            "Use Default",
            clicked_fn=self._reset_lighting_controls,
            height=26,
            width=ui.Percent(100),
        )
        ui.Button(
            "Save Settings",
            clicked_fn=self._save_current_runtime_override,
            height=26,
            width=ui.Percent(100),
        )

    def _build_grid_config_controls(self) -> None:
        with ui.HStack(height=24, spacing=6, content_clipping=True):
            ui.Label("Show grid", width=ROW_LABEL_WIDTH)
            ui.CheckBox(model=self._grid_enabled_model)
        self._build_float_row("Grid step", self._grid_step_model, precision=3)
        self._build_float_row("Line width", self._grid_width_model, precision=5)
        ui.Button(
            "Apply Grid",
            clicked_fn=self._schedule_apply_grid,
            height=26,
            width=ui.Percent(100),
        )

    def _build_camera_config_controls(self) -> None:
        ui.Label("Position", height=18)
        self._build_float_row("Camera X", self._camera_position_x_model)
        self._build_float_row("Camera Y", self._camera_position_y_model)
        self._build_float_row("Camera Z", self._camera_position_z_model)
        ui.Label("Rotation", height=18)
        self._build_float_row("Camera RX", self._camera_rotation_x_model)
        self._build_float_row("Camera RY", self._camera_rotation_y_model)
        self._build_float_row("Camera RZ", self._camera_rotation_z_model)
        ui.Button(
            "Apply Camera",
            clicked_fn=self._schedule_apply_camera,
            height=26,
            width=ui.Percent(100),
        )
        ui.Button(
            "Save Camera Pos",
            clicked_fn=self._save_camera_position,
            height=26,
            width=ui.Percent(100),
        )
        ui.Button(
            "Reset Camera",
            clicked_fn=self._schedule_reset_camera,
            height=26,
            width=ui.Percent(100),
        )

    def _build_telemetry_config_section(self) -> None:
        # isort: off
        from digital_twin_runtime_suite.app.telemetry.config import (
            COMPONENT_TUNING_GROUPS,
            TUNING_METRIC_LABELS,
            TUNING_METRICS,
        )
        from digital_twin_runtime_suite.app.telemetry.model import (
            METRIC_LABELS,
        )

        # isort: on

        config = self._telemetry_provider.config
        self._provider_numeric_metrics = tuple(sorted(TUNING_METRICS))
        self._provider_component_tuning_groups = COMPONENT_TUNING_GROUPS
        default_mode_index = self._workload_modes.index(config.default_mode)
        default_refresh_index = self._refresh_intervals.index(
            config.default_refresh_interval_s
        )
        self._provider_tick_model = ui.SimpleFloatModel(config.provider_tick_seconds)
        self._provider_interpolation_model = ui.SimpleFloatModel(
            config.interpolation_factor
        )
        self._provider_target_model = ui.SimpleFloatModel(0.0)
        self._provider_jitter_model = ui.SimpleFloatModel(0.0)
        self._provider_minimum_model = ui.SimpleFloatModel(0.0)
        self._provider_maximum_model = ui.SimpleFloatModel(0.0)

        with ui.HStack(height=24, spacing=6):
            ui.Label("Default mode", width=ROW_LABEL_WIDTH)
            self._provider_default_mode_combo = ui.ComboBox(
                default_mode_index,
                *self._workload_modes,
                width=ui.Fraction(1),
            )
        with ui.HStack(height=24, spacing=6):
            ui.Label("Default refresh", width=ROW_LABEL_WIDTH)
            refresh_labels = tuple(f"{value} s" for value in self._refresh_intervals)
            self._provider_default_refresh_combo = ui.ComboBox(
                default_refresh_index,
                *refresh_labels,
                width=ui.Fraction(1),
            )
        self._build_float_row("Provider tick", self._provider_tick_model)
        self._build_float_row(
            "Interpolation",
            self._provider_interpolation_model,
            precision=3,
        )

        ui.Label("Mode tuning", height=18)
        with ui.HStack(height=24, spacing=6):
            ui.Label("Mode", width=ROW_LABEL_WIDTH)
            self._provider_tuning_mode_combo = ui.ComboBox(
                default_mode_index,
                *self._workload_modes,
                width=ui.Fraction(1),
            )
        with ui.HStack(height=24, spacing=6):
            ui.Label("Metric", width=ROW_LABEL_WIDTH)
            metric_labels = tuple(
                (
                    TUNING_METRIC_LABELS[metric_id]
                    if metric_id in TUNING_METRIC_LABELS
                    else METRIC_LABELS[metric_id]
                )
                for metric_id in self._provider_numeric_metrics
            )
            self._provider_metric_combo = ui.ComboBox(
                0,
                *metric_labels,
                width=ui.Fraction(1),
            )
        self._build_float_row("Target", self._provider_target_model)
        self._build_float_row("Jitter", self._provider_jitter_model)
        self._build_float_row("Minimum", self._provider_minimum_model)
        self._build_float_row("Maximum", self._provider_maximum_model)
        ui.Button(
            "Save Telemetry Config",
            clicked_fn=self._save_telemetry_config,
            height=26,
            width=ui.Percent(100),
        )
        self._telemetry_config_status_label = ui.Label(
            "Packaged config with local override",
            height=34,
            elided_text=True,
        )

        for combo in (
            self._provider_tuning_mode_combo,
            self._provider_metric_combo,
        ):
            model = self._combo_index_model(combo)
            if model:
                model.add_value_changed_fn(
                    lambda _model: self._load_selected_metric_controls()
                )
        self._load_selected_metric_controls()

    def _selected_provider_mode_and_metric(self) -> tuple[str, str]:
        mode_index = self._model_int(
            self._combo_index_model(self._provider_tuning_mode_combo)
        )
        metric_index = self._model_int(
            self._combo_index_model(self._provider_metric_combo)
        )
        return (
            self._workload_modes[mode_index],
            self._provider_numeric_metrics[metric_index],
        )

    def _load_selected_metric_controls(self) -> None:
        if not self._telemetry_provider:
            return
        mode_name, metric_id = self._selected_provider_mode_and_metric()
        metric_ids = self._provider_component_tuning_groups.get(
            metric_id,
            (metric_id,),
        )
        source_metric_id = metric_ids[len(metric_ids) // 2]
        metric = self._telemetry_provider.config.modes[mode_name].numeric[
            source_metric_id
        ]
        self._provider_target_model.set_value(metric.target)
        self._provider_jitter_model.set_value(metric.jitter)
        self._provider_minimum_model.set_value(metric.minimum)
        self._provider_maximum_model.set_value(metric.maximum)

    def _save_telemetry_config(self) -> None:
        if not self._telemetry_provider or not self._telemetry_config_path:
            return

        try:
            # isort: off
            from digital_twin_runtime_suite.app.telemetry import (
                SyntheticTelemetryProvider,
                TelemetryConfig,
            )
            from digital_twin_runtime_suite.app.telemetry.config import (
                NumericMetricConfig,
            )

            # isort: on

            config = self._telemetry_provider.config
            mode_name, metric_id = self._selected_provider_mode_and_metric()
            default_mode_index = self._model_int(
                self._combo_index_model(self._provider_default_mode_combo)
            )
            default_refresh_index = self._model_int(
                self._combo_index_model(self._provider_default_refresh_combo)
            )
            tick_seconds = float(self._provider_tick_model.as_float)
            interpolation = float(self._provider_interpolation_model.as_float)
            target = float(self._provider_target_model.as_float)
            jitter = float(self._provider_jitter_model.as_float)
            minimum = float(self._provider_minimum_model.as_float)
            maximum = float(self._provider_maximum_model.as_float)

            if tick_seconds <= 0:
                raise ValueError("Provider tick must be greater than zero.")
            if not 0 < interpolation <= 1:
                raise ValueError("Interpolation must be in the range (0, 1].")
            if minimum > maximum:
                raise ValueError("Minimum must not exceed maximum.")
            if not minimum <= target <= maximum:
                raise ValueError("Target must remain inside the safe range.")
            if jitter < 0:
                raise ValueError("Jitter must not be negative.")

            current_mode = config.modes[mode_name]
            numeric = dict(current_mode.numeric)
            metric_ids = self._provider_component_tuning_groups.get(
                metric_id,
                (metric_id,),
            )
            for resolved_metric_id in metric_ids:
                numeric[resolved_metric_id] = NumericMetricConfig(
                    target=target,
                    jitter=jitter,
                    minimum=minimum,
                    maximum=maximum,
                )
            modes = dict(config.modes)
            modes[mode_name] = replace(current_mode, numeric=numeric)
            updated = replace(
                config,
                default_mode=self._workload_modes[default_mode_index],
                provider_tick_seconds=tick_seconds,
                default_refresh_interval_s=self._refresh_intervals[
                    default_refresh_index
                ],
                interpolation_factor=interpolation,
                modes=modes,
            )
            updated.save_local_override()
            reloaded = TelemetryConfig.load(self._telemetry_config_path)

            runtime_mode = self._telemetry_provider.mode
            runtime_refresh = (
                self._telemetry_provider.latest_snapshot.refresh_interval_s
            )
            self._telemetry_provider = SyntheticTelemetryProvider(reloaded)
            self._telemetry_provider.set_mode(runtime_mode)
            if runtime_refresh in reloaded.allowed_refresh_intervals_s:
                self._telemetry_provider.set_refresh_interval(runtime_refresh)
            self._next_telemetry_ui_update = 0.0
            self._set_telemetry_config_status("Telemetry config saved and applied.")
        except Exception as exc:  # noqa: BLE001
            self._provider_tick_model.set_value(
                self._telemetry_provider.config.provider_tick_seconds
            )
            self._provider_interpolation_model.set_value(
                self._telemetry_provider.config.interpolation_factor
            )
            self._load_selected_metric_controls()
            self._set_telemetry_config_status(
                f"Telemetry config error: {exc}",
                clear_after_s=8.0,
            )

    def _set_telemetry_config_status(
        self,
        message: str,
        clear_after_s: float | None = None,
    ) -> None:
        if self._telemetry_config_status_label:
            self._telemetry_config_status_label.text = _compact_text(message)
            self._telemetry_config_status_label.tooltip = message
            self._telemetry_config_status_clear_at = (
                time.monotonic() + clear_after_s if clear_after_s else 0.0
            )

    def _build_telemetry_tab(self) -> None:
        # isort: off
        from digital_twin_runtime_suite.app.telemetry.model import (
            METRIC_LABELS,
        )
        from digital_twin_runtime_suite.app.telemetry.model import (
            TELEMETRY_GROUPS,
        )

        # isort: on

        snapshot = self._telemetry_provider.latest_snapshot
        mode_index = self._workload_modes.index(snapshot.operational_state)
        refresh_index = self._refresh_intervals.index(snapshot.refresh_interval_s)

        with ui.ScrollingFrame(
            horizontal_scrollbar_policy=ui.ScrollBarPolicy.SCROLLBAR_ALWAYS_OFF,
            vertical_scrollbar_policy=ui.ScrollBarPolicy.SCROLLBAR_ALWAYS_ON,
        ):
            with ui.VStack(spacing=6, content_clipping=True):
                ui.Label("Node telemetry", height=20)
                with ui.HStack(height=24, spacing=6):
                    ui.Label("Workload", width=ROW_LABEL_WIDTH)
                    self._workload_combo = ui.ComboBox(
                        mode_index,
                        *self._workload_modes,
                        width=ui.Fraction(1),
                    )
                with ui.HStack(height=24, spacing=6):
                    ui.Label("Refresh", width=ROW_LABEL_WIDTH)
                    refresh_labels = tuple(
                        f"{value} s" for value in self._refresh_intervals
                    )
                    self._refresh_combo = ui.ComboBox(
                        refresh_index,
                        *refresh_labels,
                        width=ui.Fraction(1),
                    )
                self._freeze_button = ui.Button(
                    "Freeze",
                    clicked_fn=self._toggle_telemetry_freeze,
                    height=26,
                    width=ui.Percent(100),
                )
                self._telemetry_timestamp_label = ui.Label(
                    "Last update",
                    height=20,
                    elided_text=True,
                )
                self._telemetry_state_label = ui.Label(
                    snapshot.operational_state,
                    height=22,
                )

                for group_name, metric_ids in TELEMETRY_GROUPS.items():
                    ui.Spacer(height=3)
                    collapsed = group_name.startswith(("GPU 1 ", "GPU 2 ", "GPU 3 "))
                    with ui.CollapsableFrame(
                        group_name,
                        collapsed=collapsed,
                        height=0,
                        build_header_fn=self._build_telemetry_group_header,
                        style={
                            "CollapsableFrame": {
                                "background_color": 0xFF3A3A3A,
                                "secondary_color": 0xFF464646,
                                "border_color": 0xFF5A5A5A,
                                "border_width": 1,
                                "border_radius": 2,
                            }
                        },
                    ):
                        with ui.VStack(spacing=2, height=0):
                            ui.Spacer(height=2)
                            for metric_id in metric_ids:
                                with ui.HStack(
                                    height=22,
                                    spacing=6,
                                    content_clipping=True,
                                ):
                                    ui.Label(
                                        METRIC_LABELS[metric_id],
                                        width=ui.Fraction(1),
                                        elided_text=True,
                                    )
                                    value_label = ui.Label(
                                        "",
                                        width=112,
                                        alignment=ui.Alignment.RIGHT_CENTER,
                                    )
                                    ui.Spacer(width=TELEMETRY_VALUE_RIGHT_PADDING)
                                    self._telemetry_metric_labels.setdefault(
                                        metric_id,
                                        [],
                                    ).append(value_label)
                            ui.Spacer(height=2)

        self._install_telemetry_callbacks()
        self._update_telemetry_labels(snapshot)

    @staticmethod
    def _build_telemetry_group_header(collapsed: bool, title: str) -> None:
        with ui.ZStack(height=26):
            ui.Rectangle(style={"background_color": 0xFF383838})
            with ui.HStack(height=26, spacing=4):
                ui.Label(
                    ">" if collapsed else "v",
                    width=16,
                    alignment=ui.Alignment.CENTER,
                    style={
                        "color": 0xFFB8B8B8,
                        "font": "${fonts}/OpenSans-SemiBold.ttf",
                    },
                )
                ui.Label(
                    title,
                    alignment=ui.Alignment.LEFT_CENTER,
                    elided_text=True,
                    tooltip=title,
                    style={
                        "color": 0xFFE6E6E6,
                        "font": "${fonts}/OpenSans-SemiBold.ttf",
                        "font_size": 14,
                    },
                )

    def _select_sidebar_tab(self, tab_name: str) -> None:
        telemetry_selected = tab_name == "Telemetry"
        view_selected = tab_name == "View"
        config_selected = tab_name == "Config"
        if self._telemetry_frame:
            self._telemetry_frame.visible = telemetry_selected
        if self._view_frame:
            self._view_frame.visible = view_selected
        if self._config_frame:
            self._config_frame.visible = config_selected
        if self._telemetry_tab_button:
            self._telemetry_tab_button.checked = telemetry_selected
        if self._view_tab_button:
            self._view_tab_button.checked = view_selected
        if self._config_tab_button:
            self._config_tab_button.checked = config_selected

    def _install_telemetry_callbacks(self) -> None:
        workload_model = self._combo_index_model(self._workload_combo)
        refresh_model = self._combo_index_model(self._refresh_combo)
        if workload_model:
            workload_model.add_value_changed_fn(self._on_workload_mode_changed)
        if refresh_model:
            refresh_model.add_value_changed_fn(self._on_refresh_interval_changed)

    @staticmethod
    def _combo_index_model(combo):
        if not combo or not combo.model:
            return None
        return combo.model.get_item_value_model(None)

    @staticmethod
    def _model_int(model) -> int:
        if hasattr(model, "as_int"):
            return int(model.as_int)
        return int(model.get_value_as_int())

    def _on_workload_mode_changed(self, model) -> None:
        self._cancel_streamlines_profile_preview()
        self._cancel_streamlines_material_preview()
        if not self._telemetry_provider:
            return
        index = self._model_int(model)
        if 0 <= index < len(self._workload_modes):
            workload_mode = self._workload_modes[index]
            self._telemetry_provider.set_mode(workload_mode)
            self._log_workload_cache_mapping(workload_mode)
            self._schedule_current_streamlines_cache_validation()
            self._refresh_airflow_cache_selector_label()
            self._schedule_workload_transition(workload_mode)
            self._next_telemetry_ui_update = 0.0

    def _airflow_cache_selector_text(self) -> str:
        """Return the next or current Flow selector without changing runtime state."""

        if not self._controller:
            return "Not configured"
        cache = self._controller.config.simulation_cache
        if cache.runtime_mode != "kit_cae":
            return (
                Path(cache.wrapper_path).name
                if cache.wrapper_path
                else "Not configured"
            )
        try:
            return self._controller.airflow_cache_selector_identity()
        except (RuntimeError, ValueError):
            return "Not configured"

    def _refresh_airflow_cache_selector_label(self) -> None:
        if not self._airflow_cache_selector_label:
            return
        selector_text = self._airflow_cache_selector_text()
        self._airflow_cache_selector_label.text = _compact_text(selector_text)
        self._airflow_cache_selector_label.tooltip = selector_text

    def _log_workload_cache_mapping(self, workload_mode: str) -> None:
        """Report mapping resolution without changing the Flow lifecycle."""

        if STAGE09_SUPPRESS_AIRFLOW_DIAGNOSTICS or not self._controller:
            return
        mapping_log = self._controller.resolve_workload_airflow_binding(
            workload_mode
        ).format_mapping_log()
        carb.log_warn(mapping_log)

    def _on_refresh_interval_changed(self, model) -> None:
        if not self._telemetry_provider:
            return
        index = self._model_int(model)
        if 0 <= index < len(self._refresh_intervals):
            self._telemetry_provider.set_refresh_interval(
                self._refresh_intervals[index]
            )
            self._next_telemetry_ui_update = 0.0

    def _toggle_telemetry_freeze(self) -> None:
        if not self._telemetry_provider or not self._telemetry_latch:
            return
        if self._telemetry_latch.is_frozen:
            self._telemetry_latch.resume()
            if self._freeze_button:
                self._freeze_button.text = "Freeze"
        else:
            self._telemetry_latch.freeze(self._telemetry_provider.latest_snapshot)
            if self._freeze_button:
                self._freeze_button.text = "Resume"
        self._next_telemetry_ui_update = 0.0

    async def _run_telemetry(self) -> None:
        try:
            import omni.kit.app
            import omni.usd

            app = omni.kit.app.get_app()
            usd_context = omni.usd.get_context()
            provider_tick_seconds = (
                self._telemetry_provider.config.provider_tick_seconds
            )
            next_provider_tick = time.monotonic() + provider_tick_seconds
            self._next_telemetry_ui_update = 0.0

            while self._telemetry_provider and self._window:
                await app.next_update_async()
                now = time.monotonic()

                if (
                    self._telemetry_config_status_clear_at
                    and now >= self._telemetry_config_status_clear_at
                ):
                    self._set_telemetry_config_status("")

                if now >= next_provider_tick:
                    self._telemetry_provider.tick()
                    next_provider_tick = (
                        now + self._telemetry_provider.config.provider_tick_seconds
                    )

                if self._motion_controller:
                    self._motion_controller.update(
                        usd_context.get_stage(),
                        self._telemetry_provider.latest_snapshot,
                        now,
                    )

                if self._controller:
                    self._controller.sync_simulation_cache_frame_in_kit()

                latest = self._telemetry_provider.latest_snapshot
                displayed = self._telemetry_latch.displayed(latest)
                if self._controller:
                    self._controller.apply_front_panel_indicators_snapshot_in_kit(
                        displayed,
                        now,
                    )

                if now >= self._next_telemetry_ui_update:
                    self._update_telemetry_labels(displayed)
                    self._update_airflow_temporal_validation_status()
                    self._update_visualization_controls()
                    if self._controller:
                        self._controller.apply_qled_display_snapshot_in_kit(displayed)
                    self._next_telemetry_ui_update = now + latest.refresh_interval_s
        except asyncio.CancelledError:
            return
        except Exception as exc:  # noqa: BLE001
            self._set_status(f"Telemetry stopped: {exc}")

    def _update_telemetry_labels(self, snapshot) -> None:
        if self._telemetry_timestamp_label:
            prefix = (
                "Frozen at"
                if self._telemetry_latch and self._telemetry_latch.is_frozen
                else "Last update"
            )
            timestamp = snapshot.timestamp.astimezone().strftime("%Y-%m-%d %H:%M:%S")
            self._telemetry_timestamp_label.text = f"{prefix}: {timestamp}"

        if self._telemetry_state_label:
            health = snapshot.metrics["health_state"].value
            self._telemetry_state_label.text = (
                f"{snapshot.operational_state} / {health}"
            )
            self._telemetry_state_label.style = {
                "color": self._health_colour(str(health))
            }

        for metric_id, labels in self._telemetry_metric_labels.items():
            metric = snapshot.metrics.get(metric_id)
            if metric:
                for label in labels:
                    label.text = self._format_metric(metric.value, metric.unit)
                    if metric_id == "throttling_active":
                        label.style = {
                            "color": (0xFF5C5CE6 if bool(metric.value) else 0xFF72B88A)
                        }

    def _update_visualization_controls(self) -> None:
        """Refresh mode/readiness labels from controller-owned read-only state."""

        if not self._controller:
            return
        from digital_twin_runtime_suite.app.visualization_mode import (
            VisualizationMode,
        )

        try:
            readiness = self._controller.visualization_readiness()
        except Exception as error:
            readiness = None
            message = f"Current workload readiness unavailable: {error}"
        if readiness is not None:
            for entry in readiness.entries:
                label = self._visualization_readiness_labels.get(entry.mode)
                if label:
                    text = f"{entry.state}: {entry.message}"
                    label.text = _compact_text(text)
                    label.tooltip = text
            self._announce_visualization_acceptance_when_ready(readiness)
            self._announce_streamlines_xform_probe_when_ready()
            self._sync_real_curve_ab_probe_action()
            self._sync_full_state_ab_probe_action()
        else:
            for label in self._visualization_readiness_labels.values():
                label.text = _compact_text(message)
                label.tooltip = message
        snapshot = self._controller.visualization_snapshot()
        combo_model = self._combo_index_model(self._visualization_combo)
        if combo_model:
            self._updating_visualization_mode = True
            try:
                combo_model.set_value(
                    tuple(VisualizationMode).index(snapshot.committed)
                )
            finally:
                self._updating_visualization_mode = False
        self._sync_xray_target_controls()

    def _sync_xray_target_controls(self) -> None:
        """Reflect X-Ray's effective target owner without simulating UI callbacks."""

        if not self._controller:
            return
        from digital_twin_runtime_suite.app.view_controls import bool_model_value

        snapshot = self._controller.xray_target_snapshot()
        effective = snapshot.effective_target_ids
        override_active = snapshot.override_owner is not None
        for group_id, model in self._xray_target_models.items():
            expected = group_id in effective
            if bool_model_value(model) != expected:
                model.set_value(expected)
            checkbox = self._xray_target_checkboxes.get(group_id)
            if checkbox:
                checkbox.enabled = not override_active

    def _announce_visualization_acceptance_when_ready(self, readiness) -> None:
        """Offer only the prebaked Mesh prototype playback action."""

        if getattr(self, "_validation_receipt_acceptance_owns_actions", False):
            return
        announce = getattr(
            self._controller,
            "announce_streamlines_phase44b_mesh_playback_when_ready",
            None,
        )
        if announce:
            announce()

    def _confirm_streamlines_mesh_playback(self) -> None:
        """Forward explicit Mesh viewport approval to the guided owner."""

        confirm = getattr(
            self._controller,
            "confirm_streamlines_mesh_playback",
            None,
        )
        if not confirm or not confirm():
            self._set_streamlines_status(
                "Complete the Mesh playback technical loop before confirming."
            )

    def _announce_streamlines_xform_probe_when_ready(self) -> None:
        """Offer the one-shot probe only after its existing Mesh is visible."""

        if self._streamlines_xform_probe_ready_emitted:
            return
        if not self._controller.streamlines_cached_presentation_is_visible_in_kit():
            return
        carb.log_warn(
            "DTRS STREAMLINES | XFORM_PROBE | READY\n"
            'NEXT_ACTION | Press "Run Streamlines Xform Probe".'
        )
        self._streamlines_xform_probe_ready_emitted = True

    def _schedule_streamlines_xform_probe(self) -> None:
        """Schedule at most one temporary Session Layer Xform probe."""

        full_task = self._streamlines_full_state_ab_probe_task
        if full_task and not full_task.done():
            return
        task = self._streamlines_xform_probe_task
        if task and not task.done():
            return
        from digital_twin_runtime_suite.app.streamlines.xform_probe import (
            run_streamlines_xform_probe_in_kit,
        )

        self._streamlines_xform_probe_task = asyncio.ensure_future(
            run_streamlines_xform_probe_in_kit(self._controller)
        )

    def _sync_real_curve_ab_probe_action(self) -> None:
        """Enable the static switch while Streamlines is visible."""

        from digital_twin_runtime_suite.app.streamlines.real_curve_ab_probe import (
            real_curve_ab_probe_ready_in_kit,
        )

        available = real_curve_ab_probe_ready_in_kit()
        full_task = self._streamlines_full_state_ab_probe_task
        full_running = bool(full_task and not full_task.done())
        if self._streamlines_real_curve_ab_probe_button:
            self._streamlines_real_curve_ab_probe_button.enabled = (
                available and not full_running
            )
        if not available or self._streamlines_real_curve_ab_probe_ready_emitted:
            return
        carb.log_warn(
            "DTRS STREAMLINES | REAL_CURVE_STATIC_SWITCH | READY\n"
            'NEXT_ACTION | Press "Run Real Curve A/B Probe" to start; '
            "press it again to stop."
        )
        self._streamlines_real_curve_ab_probe_ready_emitted = True

    def _schedule_real_curve_ab_probe(self) -> None:
        """Start or stop the sole repeating real-curve comparison."""

        task = self._streamlines_real_curve_ab_probe_task
        full_task = self._streamlines_full_state_ab_probe_task
        if full_task and not full_task.done():
            return
        if task and not task.done():
            from digital_twin_runtime_suite.app.streamlines.real_curve_ab_probe import (
                request_stop_real_curve_ab_probe,
            )

            if request_stop_real_curve_ab_probe():
                self._streamlines_real_curve_ab_probe_button.enabled = False
            return
        self._streamlines_real_curve_ab_probe_task = asyncio.ensure_future(
            self._run_real_curve_ab_probe()
        )

    async def _run_real_curve_ab_probe(self) -> None:
        from digital_twin_runtime_suite.app.streamlines.real_curve_ab_probe import (
            run_real_curve_ab_probe_in_kit,
        )

        result = await run_real_curve_ab_probe_in_kit(self._controller)
        self._streamlines_real_curve_ab_probe_active = result == "ACTIVE"
        self._sync_real_curve_ab_probe_action()

    def _sync_full_state_ab_probe_action(self) -> None:
        """Enable the full-density switch while Streamlines is visible."""

        from digital_twin_runtime_suite.app.streamlines.full_state_ab_probe import (
            full_state_ab_probe_ready_in_kit,
        )

        task = self._streamlines_full_state_ab_probe_task
        running = bool(task and not task.done())
        available = full_state_ab_probe_ready_in_kit()
        if self._streamlines_full_state_ab_probe_button:
            self._streamlines_full_state_ab_probe_button.enabled = (
                available and not running
            )
        if not available or self._streamlines_full_state_ab_probe_ready_emitted:
            return
        carb.log_warn(
            "DTRS STREAMLINES | FULL_80_STATE_PROBE | READY\n"
            'NEXT_ACTION | Press "Run Full 80-State Streamlines Probe".'
        )
        self._streamlines_full_state_ab_probe_ready_emitted = True

    def _schedule_full_state_ab_probe(self) -> None:
        """Schedule the sole bounded full-density 80-state comparison."""

        task = self._streamlines_full_state_ab_probe_task
        if task and not task.done():
            return
        self._streamlines_full_state_ab_probe_button.enabled = False
        self._streamlines_full_state_ab_probe_task = asyncio.ensure_future(
            self._run_full_state_ab_probe()
        )

    async def _run_full_state_ab_probe(self) -> None:
        reset_mesh_acceptance = getattr(
            self._controller,
            "reset_streamlines_mesh_playback_acceptance_state",
            None,
        )
        if reset_mesh_acceptance:
            reset_mesh_acceptance()
        xform_task = self._streamlines_xform_probe_task
        if xform_task and not xform_task.done():
            xform_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await xform_task
        self._streamlines_xform_probe_task = None
        if self._streamlines_xform_probe_button:
            self._streamlines_xform_probe_button.enabled = False
        if self._streamlines_real_curve_ab_probe_button:
            self._streamlines_real_curve_ab_probe_button.enabled = False
        real_curve_task = self._streamlines_real_curve_ab_probe_task
        if real_curve_task and not real_curve_task.done():
            from digital_twin_runtime_suite.app.streamlines.real_curve_ab_probe import (
                request_stop_real_curve_ab_probe,
            )

            request_stop_real_curve_ab_probe()
            await real_curve_task
        from digital_twin_runtime_suite.app.streamlines.real_curve_ab_probe import (
            cleanup_real_curve_ab_probe_in_kit,
        )

        cleanup_real_curve_ab_probe_in_kit()
        self._streamlines_real_curve_ab_probe_active = False
        from digital_twin_runtime_suite.app.streamlines.full_state_ab_probe import (
            run_full_state_ab_probe_in_kit,
        )

        await run_full_state_ab_probe_in_kit(self._controller)
        self._sync_full_state_ab_probe_action()

    def _reject_streamlines_mesh_playback(self) -> None:
        """Forward a manual Mesh visual/performance defect as terminal."""

        reject = getattr(
            self._controller,
            "reject_streamlines_mesh_playback",
            None,
        )
        if reject and reject():
            self._set_streamlines_status("Mesh playback visual check failed.")

    def _report_visualization_acceptance_start(self, mode) -> None:
        """Record the Phase 4.3 baseline or final visualization selection."""

        try:
            self._announce_visualization_acceptance_when_ready(
                self._controller.visualization_readiness()
            )
        except Exception:
            # Manual guidance must never block a production mode request.
            return
        session = self._visualization_acceptance
        if session is None or session.failed or session.terminal_emitted:
            return
        if session.expected_milestone != mode.value:
            session.mark_failed()
            self._report_visualization_acceptance_event(
                "FAIL",
                "Unexpected selector action: "
                f"expected {session.expected_milestone}, got {mode.value}.",
            )
            return
        self._report_visualization_acceptance_event(
            "START",
            f"Requested production visualization mode: {mode.value}.",
        )
        self._report_visualization_acceptance_event(
            "PROGRESS",
            f"Preparing production visualization mode: {mode.value}.",
        )

    def _report_visualization_acceptance_waiting_once(
        self,
        mode,
        elapsed_seconds: int,
    ) -> None:
        """Emit one waiting record when a manual transition remains active."""

        session = self._visualization_acceptance
        if session is None or session.failed or session.terminal_emitted:
            return
        milestone = mode.value if hasattr(mode, "value") else str(mode)
        if session.expected_milestone != milestone:
            return
        self._report_visualization_acceptance_event(
            "WAITING",
            "Production visualization transition remains active: "
            f"{milestone}; elapsed={elapsed_seconds} s.",
        )

    def _report_visualization_acceptance_result(self, mode, result) -> None:
        """Advance Phase 4.3 visualization milestones after backend proof."""

        session = self._visualization_acceptance
        if session is None or session.failed or session.terminal_emitted:
            return
        reason = self._visualization_acceptance_failure_reason(mode, result)
        if reason is not None:
            session.mark_failed()
            self._report_visualization_acceptance_event("FAIL", reason)
            return
        if not session.record(mode.value):
            session.mark_failed()
            self._report_visualization_acceptance_event(
                "FAIL",
                "Manual acceptance transition could not be recorded in order.",
            )
            return
        next_mode = session.expected_milestone
        evidence = self._visualization_acceptance_evidence(mode)
        completion = f"Committed={mode.value}; {result.message}; {evidence}"
        if next_mode is None:
            self._report_visualization_acceptance_event(
                "COMPLETE",
                completion,
            )
            if session.complete():
                from digital_twin_runtime_suite.app.manual_acceptance import (
                    format_manual_acceptance_test_complete,
                )

                carb.log_warn(
                    _with_dtrs_local_timestamp(
                        format_manual_acceptance_test_complete(
                            "Phase 4.3 workload-aware Streamlines runtime passed."
                        )
                    )
                )
            return
        self._report_visualization_acceptance_event(
            "COMPLETE",
            completion,
            next_action=f'Select "{next_mode}" in "Visualization".',
        )

    def _visualization_acceptance_evidence(self, mode) -> str:
        """Format backend liveness facts already required before COMPLETE."""

        presentation = (
            self._controller.primary_visualization_presentation_snapshot_in_kit()
        )
        if mode.value == "Streamlines":
            proof = self._controller.streamlines_cached_playback_advance_proof_in_kit()
            composition = self._controller.streamlines_presentation_reference_snapshot()
            attach_calls = (
                self._controller.visualization_flow_attach_call_count()
                - self._phase43_flow_attach_baseline
            )
            airflow = self._controller._airflow_state.snapshot
            committed = airflow.committed
            return (
                f"committed_workload={committed.workload_mode}; "
                f"dataset={committed.binding.dataset_identity}; "
                f"smoke_renderer_visible={presentation.smoke_presentation_visible}; "
                "streamlines_visible="
                f"{presentation.streamlines_presentation_visible}; "
                f"scheduler_tasks={presentation.streamlines_scheduler_tasks}; "
                f"initial_sample={proof.initial_sample_identity}; "
                f"advanced_sample={proof.advanced_sample_identity}; "
                f"sample_advanced={proof.sample_advanced}; "
                f"Flow={self._controller._flow_lifecycle_state}; "
                "streamlines_reference_swap="
                f"{'PASS' if composition.reference_swap_passed else 'FAIL'}; "
                "session_sublayers_unchanged="
                f"{composition.session_sublayers_unchanged}; "
                "root_sublayers_unchanged="
                f"{composition.root_sublayers_unchanged}; "
                "server_scene_composition_mutations="
                f"{composition.server_scene_composition_mutations}; "
                f"flow_attach_calls={attach_calls}; cache_build=0; KitCAE=0; "
                "RuntimePreview=0; VTI_import=0; rebuild=0"
            )
        return (
            "smoke_renderer_visible="
            f"{presentation.smoke_presentation_visible}; "
            "streamlines_visible="
            f"{presentation.streamlines_presentation_visible}; "
            f"scheduler_tasks={presentation.streamlines_scheduler_tasks}"
        )

    def _visualization_acceptance_failure_reason(self, mode, result) -> str | None:
        """Verify peer-mode activation and exclusive primary presentation truth."""

        if not result.success:
            return result.message
        snapshot = self._controller.visualization_snapshot()
        if snapshot.committed is not mode or snapshot.pending is not None:
            return "Visualization transaction did not commit the requested mode."
        presentation = (
            self._controller.primary_visualization_presentation_snapshot_in_kit()
        )
        if mode.value == "Streamlines":
            streamlines_proof = (
                self._controller.streamlines_cached_playback_advance_proof_in_kit()
            )
            composition = self._controller.streamlines_presentation_reference_snapshot()
            if (
                presentation.streamlines_scheduler_tasks != 1
                or not presentation.streamlines_presentation_visible
                or presentation.smoke_presentation_visible
                or not self._controller.streamlines_cached_playback_advanced_in_kit()
                or streamlines_proof is None
                or not streamlines_proof.sample_advanced
                or composition is None
                or not composition.reference_swap_passed
            ):
                return "Streamlines committed without its exclusive prepared playback."
            airflow = self._controller._airflow_state.snapshot
            committed = airflow.committed
            attach_calls = (
                self._controller.visualization_flow_attach_call_count()
                - self._phase43_flow_attach_baseline
            )
            if (
                self._controller._flow_lifecycle_state != "DETACHED"
                or presentation.flow_source_prepared
                or attach_calls != 0
                or committed is None
                or committed.workload_mode != "Nominal"
                or committed.binding.dataset_identity != "server/load_normal"
                or airflow.pending is not None
            ):
                return "Nominal Streamlines baseline did not satisfy Phase 4.3."
        if mode.value == "Normal" and (
            self._controller._flow_lifecycle_state != "DETACHED"
            or presentation.flow_source_prepared
            or presentation.smoke_presentation_visible
            or presentation.streamlines_scheduler_tasks != 0
            or presentation.streamlines_presentation_visible
            or self._controller.streamlines_controls_timeline_in_kit()
            or self._controller._airflow_state.pending is not None
        ):
            return (
                "Normal committed with a primary presentation still active: "
                f"flow_source_prepared={presentation.flow_source_prepared}; "
                f"smoke_visible={presentation.smoke_presentation_visible}; "
                "streamlines_visible="
                f"{presentation.streamlines_presentation_visible}; "
                "streamlines_scheduler_tasks="
                f"{presentation.streamlines_scheduler_tasks}."
            )
        return None

    def _report_visualization_acceptance_event(
        self,
        event: str,
        status: str,
        next_action: str | None = None,
    ) -> None:
        """Use the generic formatter without creating a gate-specific framework."""

        from digital_twin_runtime_suite.app.manual_acceptance import (
            format_manual_acceptance_event,
        )

        carb.log_warn(
            _with_dtrs_local_timestamp(
                format_manual_acceptance_event(
                    area="STREAMLINES | PHASE_4_3",
                    event=event,
                    status=status,
                    next_action=next_action,
                )
            )
        )

    @staticmethod
    def _health_colour(health: str) -> int:
        if health == "Critical":
            return 0xFF5C5CE6
        if health == "Warning":
            return 0xFF5CC5E6
        return 0xFF72B88A

    @staticmethod
    def _format_metric(value, unit: str) -> str:
        if isinstance(value, bool):
            return "Active" if value else "Inactive"
        if isinstance(value, str):
            return value
        precision = 0 if unit in {"RPM", "W", "CFM", "sessions"} else 1
        formatted = f"{float(value):.{precision}f}"
        return f"{formatted} {unit}".strip()

    def _build_float_row(
        self,
        label: str,
        model,
        enabled: bool = True,
        precision: int = 2,
    ) -> None:
        with ui.HStack(height=24, spacing=6, content_clipping=True):
            ui.Label(label, width=ROW_LABEL_WIDTH, elided_text=True)
            ui.FloatDrag(
                model=model,
                width=ui.Fraction(1),
                precision=precision,
                enabled=enabled,
            )

    async def _dock_left(self) -> None:
        try:
            import omni.kit.app

            app = omni.kit.app.get_app()
            for _ in range(3):
                await app.next_update_async()

            viewport = ui.Workspace.get_window("Viewport")
            if viewport and self._window:
                self._window.dock_in(viewport, ui.DockPosition.LEFT, 0.15)
                await app.next_update_async()
                if self._window.dock_id:
                    ui.Workspace.set_dock_id_width(
                        self._window.dock_id,
                        PANEL_WIDTH,
                    )
        except Exception:  # noqa: BLE001
            return

    async def _hide_auxiliary_kit_windows(self) -> None:
        """Keep the focused DTRS shell clear of IndeX dependency windows."""

        try:
            import omni.kit.app

            app = omni.kit.app.get_app()
            for _ in range(6):
                await app.next_update_async()

            for name in ("Property", "Content", "Render Settings"):
                window = ui.Workspace.get_window(name)
                if window:
                    window.visible = False
        except Exception:  # noqa: BLE001
            return

    def _reload_config(self) -> None:
        if self._reload_task and not self._reload_task.done():
            self._set_status("Configuration reload is already running.")
            return
        self._reload_task = asyncio.ensure_future(self._reload_config_and_stage())

    async def _reload_config_and_stage(self) -> None:
        self._cancel_streamlines_profile_preview()
        try:
            cleanup = self._controller.clear_xray_material_in_kit()
        except RuntimeError as error:
            self._set_status(f"X-Ray cleanup before Reload Config failed: {error}")
            return
        if not cleanup.success:
            self._set_status(cleanup.message)
            return
        try:
            streamlines_cleanup = (
                self._controller.clear_streamlines_static_runtime_from_open_stage()
            )
        except Exception as error:  # noqa: BLE001 - keep Reload Config usable.
            self._set_status(
                f"Streamlines cleanup before Reload Config failed: {error}"
            )
            return
        if not streamlines_cleanup.clean:
            self._set_status(
                "Streamlines cleanup before Reload Config left runtime state."
            )
            return
        try:
            config = self._controller.reload_config()
        except RuntimeError:
            self._set_status("Detach airflow before reloading config")
            return
        if self._motion_controller:
            self._motion_controller.reset()
        # Motion bindings are config-backed. Rebuild after a runtime config reload.
        from digital_twin_runtime_suite.app.motion import (
            MultiRotationMotionController,
        )

        self._motion_controller = MultiRotationMotionController(
            config.fan_motion_bindings
        )
        if self._asset_label:
            asset_text = config.default_asset.label
            self._asset_label.text = _compact_text(asset_text)
            self._asset_label.tooltip = asset_text
        self._set_lighting_controls(config.lighting)
        self._set_grid_controls(config.grid)
        self._set_chassis_visibility_controls(config.chassis_presentation)
        if config.camera:
            self._set_camera_controls(config.camera)
        if self._lighting_status_label:
            lighting_text = f"HDRI: {config.default_hdri_path.name}"
            self._lighting_status_label.text = _compact_text(lighting_text)
            self._lighting_status_label.tooltip = lighting_text
        self._set_airflow_status("Not attached")
        result = await self._load_default_asset("Reload Config (stage open)")
        if result.success:
            self._set_status("Configuration reloaded and stage reopened.")

    def _set_status(self, message: str) -> None:
        if self._status_label:
            self._status_label.text = _compact_text(message)
            self._status_label.tooltip = message

    def _set_lighting_status(self, message: str) -> None:
        if self._lighting_status_label:
            self._lighting_status_label.text = _compact_text(message)
            self._lighting_status_label.tooltip = message

    def _update_airflow_temporal_validation_status(self) -> None:
        """Render the DTRS-owned proof snapshot without reading Kit-CAE internals."""

        if not self._controller:
            return
        progress = self._controller.temporal_proof_progress()
        state = progress.state.value
        if state == "IDLE":
            return
        if state == "RUNNING":
            message = (
                "Airflow active: validation "
                f"{progress.validated_sample_count}/{progress.total_sample_count}; "
                f"{progress.percentage or 0}%"
            )
        elif state == "CHECKING_LOOP_CLOSURE":
            message = "Airflow active: checking loop"
        elif state == "PASSED":
            message = (
                "Airflow active: validation reused"
                if progress.result_source.value == "SESSION_CACHE"
                else "Airflow active: validation passed"
            )
        elif state == "CANCELLED":
            message = "Airflow detached"
        else:
            message = "Airflow active: validation failed"
        detail = (
            "Background temporal validation: "
            f"{progress.validated_sample_count} of {progress.total_sample_count} "
            f"samples passed. Current source: "
            f"{progress.current_asset_name or 'unavailable'}."
        )
        self._set_airflow_status(message, tooltip=detail)

    def _set_airflow_status(self, message: str, tooltip: str | None = None) -> None:
        """Publish compact DTRS airflow state to Kit's shared lower status bar."""

        import omni.kit.app

        compact_message = " ".join(str(message).splitlines()).strip()
        match = re.search(
            r"(?:VTI|USD|Validation) (\d+)/(\d+).*?(\d+)%",
            compact_message,
        )
        progress = -1.0
        if match:
            completed, total, _percentage = (int(value) for value in match.groups())
            progress = completed / total if total else -1.0

        # This bar is shared with Kit-CAE. DTRS reports only its own logical
        # preparation/proof progress and never reads or mutates Kit-CAE's internal
        # ProgressContext stack behind the separate "Fetching array" activity.
        omni.kit.app.queue_event(
            "omni.kit.window.status_bar@activity",
            payload={"text": compact_message},
        )
        omni.kit.app.queue_event(
            "omni.kit.window.status_bar@progress",
            payload={"progress": progress},
        )

    def _set_streamlines_status(self, message: str) -> None:
        """Publish the independent static-source state in its collapsed UI section."""

        if self._streamlines_status_label:
            text = f"Status: {message}"
            self._streamlines_status_label.text = _compact_text(text)
            self._streamlines_status_label.tooltip = text

    def _set_streamlines_cache_buttons_enabled(self, enabled: bool) -> None:
        """Keep production cache actions available without a restart gate."""

        if self._streamlines_cache_build_button:
            self._streamlines_cache_build_button.enabled = enabled
        if self._streamlines_cache_load_button:
            self._streamlines_cache_load_button.enabled = enabled

    @staticmethod
    def _asset_loaded_status(message: str) -> str:
        if "viewport framed" in message:
            return "Asset loaded; viewport framed."
        return "Asset loaded."

    @staticmethod
    def _lighting_status_from_load(message: str) -> str:
        for marker in ("Lighting loaded:", "Missing HDRI:"):
            marker_index = message.find(marker)
            if marker_index >= 0:
                return message[marker_index:]
        return "Lighting status unavailable."

    def _schedule_load(self) -> None:
        self._load_task = asyncio.ensure_future(self._load_default_asset())

    def _schedule_apply_lighting(self) -> None:
        self._lighting_task = asyncio.ensure_future(self._apply_lighting())

    def _schedule_attach_airflow(self) -> None:
        """Keep the legacy Attach control on the primary Smoke request path."""

        from digital_twin_runtime_suite.app.visualization_mode import (
            VisualizationMode,
        )

        self._schedule_visualization_mode_request(VisualizationMode.SMOKE)

    def _schedule_visualization_mode_request(self, mode) -> None:
        """Own one task per pending presentation request from the selector."""

        task = self._visualization_task
        pending = (
            self._controller.visualization_snapshot().pending
            if self._controller
            else None
        )
        scheduled_mode = getattr(self, "_scheduled_visualization_mode", None)
        if (
            task
            and not task.done()
            and (scheduled_mode is mode or (pending and pending.target is mode))
        ):
            return

        self._scheduled_visualization_mode = mode
        self._visualization_task = asyncio.ensure_future(
            self._request_visualization_mode(mode)
        )

    async def _request_visualization_mode(self, mode) -> None:
        """Contain one production mode transition at the OmniUI task boundary."""

        start_acceptance = getattr(
            self._controller,
            "phase44b_mesh_playback_start_visualization",
            None,
        )
        if start_acceptance:
            start_acceptance(mode)
        self._report_visualization_acceptance_start(mode)
        waiting_task = self._start_visualization_acceptance_waiting(mode)
        try:
            result = await self._controller.request_visualization_mode_in_kit(
                mode,
                status_callback=self._report_visualization_mode_progress,
            )
        finally:
            if waiting_task is not None:
                waiting_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await waiting_task
            if self._scheduled_visualization_mode is mode:
                self._scheduled_visualization_mode = None
        self._refresh_airflow_cache_selector_label()
        self._set_airflow_status(result.message)
        self._update_visualization_controls()
        self._complete_validation_receipt_consumer_action(mode, result)
        self._report_visualization_acceptance_result(mode, result)
        observe_acceptance = getattr(
            self._controller,
            "phase44b_mesh_playback_observe_visualization_result",
            None,
        )
        if observe_acceptance:
            await observe_acceptance(
                mode,
                result,
                status_callback=self._set_streamlines_status,
            )

    def _report_visualization_mode_progress(self, message: str) -> None:
        """Mirror bounded runtime milestones into the active generic scenario."""

        self._set_airflow_status(message)
        session = self._visualization_acceptance
        if session is None or session.failed or session.terminal_emitted:
            return
        self._report_visualization_acceptance_event("PROGRESS", message)

    def _start_visualization_acceptance_waiting(self, mode):
        """Emit sparse waiting evidence only for an active manual scenario."""

        session = self._visualization_acceptance
        if session is None or session.failed or session.terminal_emitted:
            return None
        return asyncio.ensure_future(
            self._report_visualization_acceptance_waiting(mode, time.monotonic())
        )

    async def _report_visualization_acceptance_waiting(self, mode, started_at: float):
        """Report genuine long transitions at a human-readable five-second rate."""

        while True:
            await asyncio.sleep(5.0)
            elapsed_seconds = int(time.monotonic() - started_at)
            self._report_visualization_acceptance_waiting_once(mode, elapsed_seconds)

    def _schedule_build_streamlines_cache(self) -> None:
        """Build a persistent cache while no other airflow operation is active."""

        if self._airflow_task and not self._airflow_task.done():
            self._set_streamlines_status("Airflow operation is already in progress.")
            return
        self._set_streamlines_cache_buttons_enabled(False)
        self._airflow_task = asyncio.ensure_future(self._build_streamlines_cache())

    def _schedule_load_streamlines_cache(self) -> None:
        """Load a cache only when no task or attached Flow can contend for time."""

        if self._airflow_task and not self._airflow_task.done():
            self._set_streamlines_status("Airflow operation is already in progress.")
            return
        if (
            not self._controller
            or not self._controller.is_streamlines_cache_load_allowed()
        ):
            self._set_streamlines_status(
                "Load Streamlines Cache requires Flow DETACHED."
            )
            return
        self._set_streamlines_status("Loading Streamlines cache: preparing load task.")
        self._set_streamlines_cache_buttons_enabled(False)
        self._airflow_task = asyncio.ensure_future(self._load_streamlines_cache())

    def _schedule_workload_transition(self, workload_mode: str) -> None:
        """Forward one semantic request through the product controller path."""

        if not self._controller:
            return
        task = self._airflow_transition_task
        if task and not task.done():
            # The controller owns generation-based supersession.  Do not drop a
            # newer workload request merely because an older transition awaits.
            self._airflow_transition_task = asyncio.ensure_future(
                self._run_workload_transition(workload_mode)
            )
            return
        self._airflow_transition_task = asyncio.ensure_future(
            self._run_workload_transition(workload_mode)
        )

    async def _run_workload_transition(self, workload_mode: str) -> None:
        """Contain one workload transition and its guided evidence at the UI edge."""

        def report_progress(message: str) -> None:
            self._set_airflow_status(message)
            self._report_phase43_workload_progress(workload_mode, message)

        start_acceptance = getattr(
            self._controller,
            "phase44b_cache_playback_start_workload",
            None,
        )
        if start_acceptance:
            start_acceptance(workload_mode)
        self._report_phase43_workload_start(workload_mode)
        waiting_task = self._start_visualization_acceptance_waiting(workload_mode)
        try:
            result = await self._controller.request_workload_transition_in_kit(
                workload_mode,
                status_callback=report_progress,
            )
        finally:
            if waiting_task is not None:
                waiting_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await waiting_task
        self._set_airflow_status(result.message)
        self._refresh_airflow_cache_selector_label()
        self._update_visualization_controls()
        self._report_phase43_workload_result(workload_mode, result)
        observe_acceptance = getattr(
            self._controller,
            "phase44b_cache_playback_observe_workload_result",
            None,
        )
        if observe_acceptance:
            observe_acceptance(workload_mode, result)

    def _report_phase43_workload_start(self, workload_mode: str) -> None:
        """Emit START immediately after the expected production selection."""

        session = self._visualization_acceptance
        if session is None or session.failed or session.terminal_emitted:
            return
        if session.expected_milestone != workload_mode:
            session.mark_failed()
            self._report_visualization_acceptance_event(
                "FAIL",
                "Unexpected workload selection: "
                f"expected {session.expected_milestone}, got {workload_mode}.",
            )
            return
        self._report_visualization_acceptance_event(
            "START",
            f"Requested Streamlines workload: {workload_mode}.",
        )

    def _report_phase43_workload_progress(
        self,
        workload_mode: str,
        message: str,
    ) -> None:
        """Forward bounded owner milestones into the active Phase 4.3 session."""

        session = self._visualization_acceptance
        if (
            session is None
            or session.failed
            or session.terminal_emitted
            or session.expected_milestone != workload_mode
        ):
            return
        self._report_visualization_acceptance_event("PROGRESS", message)

    def _report_phase43_workload_result(self, workload_mode: str, result) -> None:
        """Advance workload guidance only after identity and liveness proof."""

        session = self._visualization_acceptance
        if session is None or session.failed or session.terminal_emitted:
            return
        reason = self._phase43_workload_failure_reason(workload_mode, result)
        if reason is not None:
            session.mark_failed()
            self._report_visualization_acceptance_event("FAIL", reason)
            return
        if not session.record(workload_mode):
            session.mark_failed()
            self._report_visualization_acceptance_event(
                "FAIL",
                "Phase 4.3 workload milestone could not be recorded in order.",
            )
            return
        evidence = self._controller.streamlines_workload_transition_evidence()
        next_milestone = session.expected_milestone
        status = (
            f"requested_workload={workload_mode}; "
            f"previous_committed={evidence.previous_workload}; "
            f"target_dataset={evidence.target_dataset}; "
            f"target_cache={evidence.target_cache}; "
            f"selected_sample={evidence.selected_sample_identity}; "
            f"initial_sample={evidence.initial_sample_identity}; "
            f"advanced_sample={evidence.advanced_sample_identity}; "
            f"committed_workload={evidence.committed_workload}; pending=None; "
            f"loaded_cache_workload={evidence.committed_workload}; "
            f"loaded_cache_dataset={evidence.target_dataset}; "
            f"streamlines_visible={evidence.streamlines_visible}; "
            f"scheduler_tasks={evidence.scheduler_tasks}; "
            f"sample_advanced={evidence.sample_advanced}; "
            "streamlines_reference_swap="
            f"{'PASS' if evidence.streamlines_reference_swap else 'FAIL'}; "
            "session_sublayers_unchanged="
            f"{evidence.session_sublayers_unchanged}; "
            "root_sublayers_unchanged="
            f"{evidence.root_sublayers_unchanged}; "
            "server_scene_composition_mutations="
            f"{evidence.server_scene_composition_mutations}; cache_build=0; "
            "recompute=0; KitCAE=0; VTI_import=0; "
            f"Flow_attach_due_to_transition={evidence.flow_attach_calls}"
        )
        self._report_visualization_acceptance_event(
            "COMPLETE",
            status,
            next_action=(
                'Select "Normal" in "Visualization".'
                if next_milestone == "Normal"
                else f'Select "{next_milestone}" in "Workload".'
            ),
        )

    def _phase43_workload_failure_reason(
        self,
        workload_mode: str,
        result,
    ) -> str | None:
        """Require current shared, cache, and presentation truth to agree."""

        if not result.success:
            return result.message
        session = self._visualization_acceptance
        if session is None or session.expected_milestone != workload_mode:
            return "Phase 4.3 workload result arrived outside its expected step."
        evidence = self._controller.streamlines_workload_transition_evidence()
        airflow = self._controller._airflow_state.snapshot
        visualization = self._controller.visualization_snapshot()
        presentation = (
            self._controller.primary_visualization_presentation_snapshot_in_kit()
        )
        contract = self._controller._streamlines_cache_playback_contract
        if evidence is None or evidence.requested_workload != workload_mode:
            return "Streamlines workload transition published no target evidence."
        if (
            airflow.committed is None
            or airflow.committed.workload_mode != workload_mode
            or airflow.pending is not None
            or visualization.committed.value != "Streamlines"
            or visualization.pending is not None
            or getattr(contract, "workload", None) != workload_mode
            or getattr(contract, "dataset_identity", None) != evidence.target_dataset
            or not presentation.streamlines_presentation_visible
            or presentation.streamlines_scheduler_tasks != 1
            or not evidence.sample_advanced
            or evidence.flow_attach_calls != 0
            or not evidence.streamlines_reference_swap
            or not evidence.session_sublayers_unchanged
            or not evidence.root_sublayers_unchanged
            or evidence.server_scene_composition_mutations != 0
        ):
            return (
                "Streamlines workload target did not satisfy shared identity "
                "and playback liveness proof."
            )
        return None

    def _build_visualization_controls(self) -> None:
        """Build the one primary-presentation selector and read-only readiness."""

        from digital_twin_runtime_suite.app.visualization_mode import (
            VisualizationMode,
        )

        modes = tuple(VisualizationMode)
        snapshot = self._controller.visualization_snapshot()
        active_index = modes.index(snapshot.committed)
        with ui.HStack(height=24, spacing=6, content_clipping=True):
            ui.Label("Mode", width=SERVER_VIEW_LABEL_WIDTH)
            self._visualization_combo = ui.ComboBox(
                active_index,
                *(mode.value for mode in modes),
                width=ui.Fraction(1),
            )
        for mode in modes:
            with ui.HStack(height=22, spacing=6, content_clipping=True):
                ui.Label(mode.value, width=SERVER_VIEW_LABEL_WIDTH, elided_text=True)
                self._visualization_readiness_labels[mode] = ui.Label(
                    "Checking current workload readiness…",
                    width=ui.Fraction(1),
                    elided_text=True,
                )
        model = self._combo_index_model(self._visualization_combo)
        if model:
            model.add_value_changed_fn(self._on_visualization_mode_changed)
        self._update_visualization_controls()

    def _on_visualization_mode_changed(self, model) -> None:
        """Route the selector through RuntimeController's single mode request path."""

        if self._updating_visualization_mode:
            return
        from digital_twin_runtime_suite.app.visualization_mode import (
            VisualizationMode,
        )

        index = self._model_int(model)
        modes = tuple(VisualizationMode)
        if 0 <= index < len(modes):
            mode = modes[index]
            readiness = self._controller.visualization_readiness().for_mode(mode)
            if not readiness.activation_available:
                self._set_airflow_status(
                    f"{mode.value} unavailable: {readiness.message}"
                )
                self._update_visualization_controls()
                return
            self._begin_validation_receipt_consumer_action(mode)
            self._schedule_visualization_mode_request(mode)

    def _schedule_detach_airflow(self) -> None:
        """Keep the legacy Detach control on the primary Normal request path."""

        from digital_twin_runtime_suite.app.visualization_mode import (
            VisualizationMode,
        )

        self._schedule_visualization_mode_request(VisualizationMode.NORMAL)
        return

    def _schedule_legacy_detach_airflow(self) -> None:
        """Retain the established cancellation implementation for internal callers."""

        transition_task = self._airflow_transition_task
        if transition_task and not transition_task.done():
            transition_task.cancel()
        if self._airflow_task and not self._airflow_task.done():
            if self._airflow_detach_requested:
                self._set_airflow_status("Cancelling airflow preparation…")
                return
            if self._controller.request_flow_attach_cancellation():
                active_attach_task = self._airflow_task
                self._airflow_detach_requested = True
                self._set_airflow_status("Cancelling airflow preparation…")
                self._airflow_task = asyncio.ensure_future(
                    self._cancel_attach_then_detach(active_attach_task)
                )
                return
            self._set_airflow_status("Airflow operation is already in progress.")
            return
        self._airflow_task = asyncio.ensure_future(self._detach_airflow())

    def _schedule_apply_smoke_tuning(self) -> None:
        if self._airflow_task and not self._airflow_task.done():
            self._set_airflow_status("Airflow operation is already in progress.")
            return
        self._airflow_task = asyncio.ensure_future(self._apply_smoke_tuning())

    def _schedule_apply_flow_voxel_resolution(self) -> None:
        if self._airflow_task and not self._airflow_task.done():
            self._set_airflow_status("Airflow operation is already in progress.")
            return
        self._airflow_task = asyncio.ensure_future(self._apply_flow_voxel_resolution())

    def _schedule_apply_emitter_layout(self) -> None:
        if self._airflow_task and not self._airflow_task.done():
            self._set_airflow_status("Airflow operation is already in progress.")
            return
        self._airflow_task = asyncio.ensure_future(self._apply_emitter_layout())

    def _schedule_apply_flow_debug_overlays(self) -> None:
        if self._airflow_task and not self._airflow_task.done():
            self._set_airflow_status("Airflow operation is already in progress.")
            return
        self._airflow_task = asyncio.ensure_future(self._apply_flow_debug_overlays())

    def _capture_flow_camera_bookmark(self, name: str) -> None:
        camera = self._controller.capture_review_camera_config()
        if not camera:
            self._set_airflow_status(f"{name} camera bookmark capture failed.")
            return
        self._flow_camera_bookmarks[name] = camera
        self._set_airflow_status(f"{name} camera bookmark captured for this session.")

    def _schedule_apply_flow_camera_bookmark(self, name: str) -> None:
        if self._airflow_task and not self._airflow_task.done():
            self._set_airflow_status("Airflow operation is already in progress.")
            return
        self._airflow_task = asyncio.ensure_future(
            self._apply_flow_camera_bookmark(name)
        )

    def _apply_normal_map_scale(self) -> None:
        from digital_twin_runtime_suite.app.view_controls import (
            normal_map_scale_from_model,
        )

        if not self._normal_map_scale_model:
            self._set_status("Normal Map Scale control is unavailable.")
            return
        try:
            scale = normal_map_scale_from_model(self._normal_map_scale_model)
        except ValueError as error:
            self._set_status(f"Normal Map Scale is invalid: {error}")
            return
        result = self._controller.apply_normal_map_scale_in_kit(scale)
        if not result.success:
            self._set_status(result.message)
            return
        try:
            self._controller.save_normal_map_scale_override(scale)
        except OSError as error:
            self._set_status(f"Normal Map Scale was applied but not saved: {error}")
            return
        self._set_status(f"{result.message} Saved to local config.")

    def _apply_xray_material(self) -> None:
        try:
            xray = self._xray_config_from_controls()
        except ValueError as error:
            self._set_status(f"X-Ray settings are invalid: {error}")
            return
        result = self._controller.apply_manual_xray_material_in_kit(
            xray, self._selected_xray_target_ids()
        )
        try:
            self._controller.save_xray_material_override(xray)
        except OSError as error:
            self._set_status(f"X-Ray settings were not saved: {error}")
            return
        if not result.success:
            self._set_status(result.message)
            return
        self._sync_xray_target_controls()
        self._set_status(f"{result.message} Saved to local config.")

    def _xray_config_from_controls(self):
        from digital_twin_runtime_suite.app.config import XRayMaterialConfig

        values = self._xray_fresnel_values()
        return XRayMaterialConfig(
            facing_color=values[0],
            edge_color=values[1],
            edge_center=values[2],
            edge_softness=values[3],
            edge_sharpness=values[4],
            facing_roughness=values[5],
            edge_roughness=values[6],
            facing_opacity=values[7],
            edge_opacity=values[8],
            facing_emission=values[9],
            edge_emission=values[10],
            emission_scale=values[11],
        )

    def _selected_xray_target_ids(self) -> frozenset[str]:
        """Return the UI-owned target selection without persisting it to config."""

        from digital_twin_runtime_suite.app.view_controls import (
            bool_model_value,
        )

        return frozenset(
            group_id
            for group_id, model in self._xray_target_models.items()
            if bool_model_value(model)
        )

    def _xray_fresnel_values(self):
        """Read the production-owned Fresnel parameter set from X-Ray controls."""

        from digital_twin_runtime_suite.app.view_controls import (
            hex_to_rgb,
            string_model_value,
        )

        models = self._xray_fresnel_models
        center = models["center"].get_value_as_float()
        softness = models["softness"].get_value_as_float()
        sharpness = models["sharpness"].get_value_as_float()
        facing_roughness = models["facing_roughness"].get_value_as_float()
        edge_roughness = models["edge_roughness"].get_value_as_float()
        facing_opacity = models["facing_opacity"].get_value_as_float()
        edge_opacity = models["edge_opacity"].get_value_as_float()
        facing_emission = models["facing_emission"].get_value_as_float()
        edge_emission = models["edge_emission"].get_value_as_float()
        emission_scale = models["emission_scale"].get_value_as_float()
        if (
            not 0.0 <= center <= 1.0
            or not 0.001 <= softness <= 1.0
            or not 0.1 <= sharpness <= 8.0
            or not 0.0 <= facing_roughness <= 1.0
            or not 0.0 <= edge_roughness <= 1.0
            or not 0.0 <= facing_opacity <= 1.0
            or not 0.0 <= edge_opacity <= 1.0
            or facing_emission < 0.0
            or edge_emission < 0.0
            or emission_scale < 0.0
        ):
            raise ValueError("X-Ray Fresnel values are outside their allowed range.")
        return (
            hex_to_rgb(string_model_value(models["facing"])),
            hex_to_rgb(string_model_value(models["edge"])),
            center,
            softness,
            sharpness,
            facing_roughness,
            edge_roughness,
            facing_opacity,
            edge_opacity,
            facing_emission,
            edge_emission,
            emission_scale,
        )

    def _schedule_apply_chassis_visibility_controls(self) -> None:
        self._view_task = asyncio.ensure_future(
            self._apply_chassis_visibility_controls()
        )

    def _play_airflow(self) -> None:
        result = self._controller.play_simulation_cache_in_kit()
        self._set_airflow_status(result.message)

    def _pause_airflow(self) -> None:
        result = self._controller.pause_simulation_cache_in_kit()
        self._set_airflow_status(result.message)

    def _reset_airflow(self) -> None:
        if self._airflow_task and not self._airflow_task.done():
            self._set_airflow_status("Airflow operation is already in progress.")
            return
        result = self._controller.reset_simulation_cache_in_kit()
        self._set_airflow_status(result.message)

    def _schedule_apply_camera(self) -> None:
        self._lighting_task = asyncio.ensure_future(self._apply_camera())

    def _schedule_apply_grid(self) -> None:
        self._lighting_task = asyncio.ensure_future(self._apply_grid())

    def _schedule_reset_camera(self) -> None:
        self._lighting_task = asyncio.ensure_future(self._reset_camera())

    def _reset_lighting_controls(self) -> None:
        config = self._controller.clear_lighting_override()
        self._set_lighting_controls(config.lighting)
        self._set_lighting_status("Lighting controls reset to project defaults.")

    def _set_lighting_controls(self, lighting) -> None:
        if self._hdri_model:
            self._hdri_model.set_value(lighting.hdri_path)
        if self._exposure_model:
            self._exposure_model.set_value(lighting.exposure)
        if self._intensity_model:
            self._intensity_model.set_value(lighting.intensity)
        if self._show_hdri_background_model:
            self._show_hdri_background_model.set_value(lighting.show_hdri_background)
        if self._review_key_model:
            self._review_key_model.set_value(lighting.review_key_light_enabled)
        if self._review_key_intensity_model:
            self._review_key_intensity_model.set_value(
                lighting.review_key_light_intensity
            )
        if self._rotation_x_model:
            self._rotation_x_model.set_value(lighting.rotation.x)
        if self._rotation_y_model:
            self._rotation_y_model.set_value(lighting.rotation.y)
        if self._rotation_z_model:
            self._rotation_z_model.set_value(lighting.rotation.z)

    def _set_grid_controls(self, grid) -> None:
        if self._grid_enabled_model:
            self._grid_enabled_model.set_value(grid.enabled)
        if self._grid_step_model:
            self._grid_step_model.set_value(grid.step)
        if self._grid_width_model:
            self._grid_width_model.set_value(grid.width)

    def _set_chassis_visibility_controls(self, presentation) -> None:
        for group in presentation.visibility_groups:
            model = self._chassis_visibility_models.get(group.group_id)
            if model:
                model.set_value(group.default_visible)
        if self._face_panel_open_model:
            self._face_panel_open_model.set_value(presentation.face_panel.default_open)
        if self._normal_map_scale_model:
            self._normal_map_scale_model.set_value(
                presentation.materials.normal_map_scale
            )
        xray = presentation.materials.xray
        # Material values reload from config, while target selection is runtime
        # state and must never silently re-author Session Layer bindings.
        for model in self._xray_target_models.values():
            model.set_value(False)
        if hasattr(self, "_xray_fresnel_models"):
            from digital_twin_runtime_suite.app.view_controls import rgb_to_hex

            models = self._xray_fresnel_models
            models["facing"].set_value(rgb_to_hex(xray.facing_color))
            models["edge"].set_value(rgb_to_hex(xray.edge_color))
            for key, value in (
                ("center", xray.edge_center),
                ("softness", xray.edge_softness),
                ("sharpness", xray.edge_sharpness),
                ("facing_roughness", xray.facing_roughness),
                ("edge_roughness", xray.edge_roughness),
                ("facing_opacity", xray.facing_opacity),
                ("edge_opacity", xray.edge_opacity),
                ("facing_emission", xray.facing_emission),
                ("edge_emission", xray.edge_emission),
                ("emission_scale", xray.emission_scale),
            ):
                models[key].set_value(value)
        self._face_panel_open_state = presentation.face_panel.default_open
        self._set_face_panel_action_label(self._face_panel_open_state)

    def _set_face_panel_action_label(self, is_open: bool) -> None:
        if not self._face_panel_action_label:
            return
        from digital_twin_runtime_suite.app.view_controls import (
            face_panel_action_label,
        )

        action_text = face_panel_action_label(is_open)
        self._face_panel_action_label.text = action_text
        self._face_panel_action_label.tooltip = action_text

    def _set_camera_controls(self, camera) -> None:
        self._updating_camera_controls = True
        try:
            if self._camera_position_x_model:
                self._camera_position_x_model.set_value(camera.position.x)
            if self._camera_position_y_model:
                self._camera_position_y_model.set_value(camera.position.y)
            if self._camera_position_z_model:
                self._camera_position_z_model.set_value(camera.position.z)
            if self._camera_rotation_x_model:
                self._camera_rotation_x_model.set_value(camera.rotation.x)
            if self._camera_rotation_y_model:
                self._camera_rotation_y_model.set_value(camera.rotation.y)
            if self._camera_rotation_z_model:
                self._camera_rotation_z_model.set_value(camera.rotation.z)
            self._camera_rotation_order = camera.rotation_order
        finally:
            self._updating_camera_controls = False

    def _install_camera_edit_callbacks(self) -> None:
        for model in (
            self._camera_position_x_model,
            self._camera_position_y_model,
            self._camera_position_z_model,
            self._camera_rotation_x_model,
            self._camera_rotation_y_model,
            self._camera_rotation_z_model,
        ):
            if hasattr(model, "add_value_changed_fn"):
                model.add_value_changed_fn(lambda _model: self._pause_camera_sync())

    def _pause_camera_sync(self) -> None:
        if self._updating_camera_controls:
            return
        self._suspend_camera_sync_until = time.monotonic() + 5.0

    def _build_lighting_config_from_controls(self):
        # isort: off
        from digital_twin_runtime_suite.app.config import (
            LightingConfig,
            RotationConfig,
        )

        # isort: on

        review_key_intensity = float(self._review_key_intensity_model.as_float)
        return LightingConfig(
            hdri_path=self._hdri_model.as_string.strip(),
            exposure=float(self._exposure_model.as_float),
            intensity=float(self._intensity_model.as_float),
            show_hdri_background=bool(self._show_hdri_background_model.as_bool),
            review_key_light_enabled=bool(self._review_key_model.as_bool),
            review_key_light_intensity=review_key_intensity,
            rotation=RotationConfig(
                x=float(self._rotation_x_model.as_float),
                y=float(self._rotation_y_model.as_float),
                z=float(self._rotation_z_model.as_float),
            ),
        )

    def _build_camera_config_from_controls(self):
        # isort: off
        from digital_twin_runtime_suite.app.config import (
            CameraConfig,
            RotationConfig,
        )

        # isort: on

        return CameraConfig(
            position=RotationConfig(
                x=float(self._camera_position_x_model.as_float),
                y=float(self._camera_position_y_model.as_float),
                z=float(self._camera_position_z_model.as_float),
            ),
            rotation=RotationConfig(
                x=float(self._camera_rotation_x_model.as_float),
                y=float(self._camera_rotation_y_model.as_float),
                z=float(self._camera_rotation_z_model.as_float),
            ),
            rotation_order=self._camera_rotation_order,
        )

    def _build_grid_config_from_controls(self):
        from digital_twin_runtime_suite.app.config import GridConfig

        return GridConfig(
            enabled=bool(self._grid_enabled_model.as_bool),
            step=float(self._grid_step_model.as_float),
            width=float(self._grid_width_model.as_float),
        )

    def _save_current_runtime_override(self) -> None:
        if not self._controller or not self._hdri_model:
            return

        try:
            lighting = self._build_lighting_config_from_controls()
            camera = self._controller.capture_review_camera_config()
            grid = self._build_grid_config_from_controls()
            self._controller.save_runtime_override(lighting, camera, grid)
            self._set_status("Settings saved.")
        except Exception:  # noqa: BLE001
            return

    def _save_camera_position(self) -> None:
        if not self._controller:
            return

        camera = self._controller.capture_review_camera_config()
        if not camera:
            self._set_status("Camera save skipped: no review camera.")
            return

        try:
            lighting = self._build_lighting_config_from_controls()
            grid = self._build_grid_config_from_controls()
            self._controller.save_runtime_override(lighting, camera, grid)
            self._set_camera_controls(camera)
            self._suspend_camera_sync_until = 0.0
            self._set_status("Camera position saved.")
        except Exception:  # noqa: BLE001
            self._set_status("Camera save failed.")

    async def _sync_camera_panel(self) -> None:
        try:
            import omni.kit.app

            app = omni.kit.app.get_app()
            panel_counter = 0
            while self._controller and self._window:
                await app.next_update_async()
                self._controller.sync_xray_fresnel_material_camera_in_kit()
                self._controller.advance_xray_material_performance_sampler_in_kit()
                panel_counter += 1
                if panel_counter < 15:
                    continue
                panel_counter = 0
                if time.monotonic() < self._suspend_camera_sync_until:
                    continue
                camera = self._controller.capture_review_camera_config()
                if camera:
                    self._set_camera_controls(camera)
        except asyncio.CancelledError:
            return
        except Exception:  # noqa: BLE001
            return

    async def _load_default_asset(self, event_label: str = "Load"):
        result = await self._controller.open_default_asset_in_kit(
            status_callback=self._set_status,
        )
        self._set_status(
            self._asset_loaded_status(result.message)
            if result.success
            else result.message
        )
        if result.success:
            self._set_lighting_status(self._lighting_status_from_load(result.message))
        return result

    async def _attach_airflow(self) -> None:
        def update_status(message: str) -> None:
            self._refresh_airflow_cache_selector_label()
            self._set_airflow_status(message)

        result = await self._controller.attach_simulation_cache_in_kit(
            status_callback=update_status,
        )
        self._refresh_airflow_cache_selector_label()
        self._set_airflow_status(result.message)

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

    async def _load_streamlines_cache(self) -> None:
        """Contain production cache-load failures at the OmniUI task boundary."""

        try:
            result = await self._controller.load_streamlines_cache_in_kit(
                status_callback=self._set_streamlines_status,
            )
            self._set_streamlines_status(
                "Streamlines cache loaded: exact manifest state "
                f"{result.active_sample_index + 1}/{result.metadata.sample_count}."
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            import carb

            from digital_twin_runtime_suite.app.streamlines.runtime import (
                report_streamlines_task_failure,
            )

            report_streamlines_task_failure(
                error,
                area="CACHE_LOAD",
                display_name="Streamlines cache load",
                status_callback=self._set_streamlines_status,
                error_logger=carb.log_error,
            )
        finally:
            self._set_streamlines_cache_buttons_enabled(True)

    async def _cancel_attach_then_detach(self, attach_task) -> None:
        """Serialize Detach behind the cooperative preflight cancellation result."""

        try:
            await attach_task
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001
            import carb

            carb.log_error(f"DTRS airflow Attach cancellation task failed: {error}")
        finally:
            self._airflow_detach_requested = False
        await self._detach_airflow()

    async def _detach_airflow(self) -> None:
        try:
            result = await self._controller.detach_simulation_cache_in_kit()
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001
            carb.log_error(f"DTRS airflow detach task failed: {error}")
            self._set_airflow_status(f"Airflow cache detach failed: {error}")
            return
        self._refresh_airflow_cache_selector_label()
        self._set_airflow_status(result.message)

    async def _apply_smoke_tuning(self) -> None:
        from digital_twin_runtime_suite.app.view_controls import (
            build_smoke_base_color_from_models,
            build_smoke_tuning_from_models,
        )

        index_models = {
            field_name: self._combo_index_model(combo)
            for field_name, combo in self._smoke_tuning_combos.items()
        }
        if any(model is None for model in index_models.values()):
            self._set_airflow_status("Smoke Tuning controls are unavailable.")
            return
        try:
            base_color = build_smoke_base_color_from_models(
                source=self._smoke_color_input_source,
                hex_model=self._smoke_color_hex_model,
                hue_model=self._smoke_color_hue_model,
                saturation_model=self._smoke_color_saturation_model,
                value_model=self._smoke_color_value_model,
            )
            tuning = build_smoke_tuning_from_models(
                index_models,
                base_color=base_color,
            )
        except ValueError as error:
            self._set_airflow_status(f"Smoke Tuning selection is invalid: {error}")
            return
        result = self._controller.apply_kit_cae_smoke_tuning_in_kit(tuning)
        self._set_airflow_status(result.message)

    async def _apply_flow_voxel_resolution(self) -> None:
        from digital_twin_runtime_suite.app.flow.quality import (
            kit_cae_flow_voxel_resolution_from_index,
        )

        model = self._combo_index_model(self._flow_voxel_resolution_combo)
        if model is None:
            self._set_airflow_status("Flow resolution control is unavailable.")
            return
        try:
            max_resolution = kit_cae_flow_voxel_resolution_from_index(model)
        except ValueError as error:
            self._set_airflow_status(f"Flow resolution selection is invalid: {error}")
            return
        result = await self._controller.apply_kit_cae_voxel_resolution_in_kit(
            max_resolution
        )
        self._set_airflow_status(result.message)

    async def _apply_emitter_layout(self) -> None:
        from digital_twin_runtime_suite.app.view_controls import (
            build_emitter_layout_from_models,
        )

        index_models = {
            field_name: self._combo_index_model(combo)
            for field_name, combo in self._emitter_layout_combos.items()
        }
        if any(model is None for model in index_models.values()):
            self._set_airflow_status("Emitter Layout controls are unavailable.")
            return
        try:
            layout = build_emitter_layout_from_models(index_models)
        except ValueError as error:
            self._set_airflow_status(f"Emitter Layout selection is invalid: {error}")
            return
        result = await self._controller.apply_kit_cae_emitter_layout_in_kit(layout)
        self._set_airflow_status(result.message)

    async def _apply_flow_debug_overlays(self) -> None:
        if not self._show_flow_debug_overlays_model:
            self._set_airflow_status("Flow debug overlay control is unavailable.")
            return
        result = self._controller.set_kit_cae_debug_overlays_visible_in_kit(
            self._show_flow_debug_overlays_model.get_value_as_bool()
        )
        self._set_airflow_status(result.message)

    async def _apply_flow_camera_bookmark(self, name: str) -> None:
        camera = self._flow_camera_bookmarks.get(name)
        if not camera:
            self._set_airflow_status(f"Capture the {name} camera bookmark first.")
            return
        applied = await self._controller.apply_camera_in_kit(
            camera,
            status_callback=self._set_airflow_status,
        )
        if applied:
            self._controller.set_flow_performance_camera_bookmark(name)
            self._set_airflow_status(f"{name} camera bookmark applied.")

    async def _apply_chassis_visibility_controls(self) -> None:
        from digital_twin_runtime_suite.app.config import (
            chassis_presentation_with_operator_state,
        )
        from digital_twin_runtime_suite.app.view_controls import (
            build_face_panel_state,
            build_visibility_state,
        )

        group_ids = tuple(
            group.group_id
            for group in self._controller.config.chassis_presentation.visibility_groups
        )
        visibility_by_group = build_visibility_state(
            self._chassis_visibility_models,
            group_ids,
        )
        face_panel_state = build_face_panel_state(self._face_panel_open_model)
        try:
            chassis_presentation_with_operator_state(
                self._controller.config.chassis_presentation,
                visibility_by_group,
                face_panel_state,
            )
        except ValueError as error:
            self._set_status(f"Server enclosure settings are invalid: {error}")
            return

        visibility_applied = True
        if group_ids:
            visibility_applied = (
                await self._controller.apply_chassis_visibility_state_in_kit(
                    visibility_by_group,
                    status_callback=self._set_status,
                )
            )
        face_panel_applied = True
        if face_panel_state is not None:
            face_panel_applied = await self._controller.apply_face_panel_state_in_kit(
                face_panel_state,
                status_callback=self._set_status,
            )
        if not visibility_applied or not face_panel_applied:
            self._set_status("Server enclosure changes were not saved.")
            return
        try:
            self._controller.save_chassis_presentation_override(
                visibility_by_group,
                face_panel_state,
            )
        except (OSError, ValueError) as error:
            self._set_status(
                f"Server enclosure applied but could not be saved: {error}"
            )
            return
        if face_panel_state is not None:
            self._face_panel_open_state = face_panel_state
            self._set_face_panel_action_label(face_panel_state)
        self._set_status("Server enclosure settings applied and saved.")

    async def _apply_lighting(self) -> None:
        lighting = self._build_lighting_config_from_controls()
        result = await self._controller.apply_lighting_in_kit(
            lighting=lighting,
            status_callback=self._set_lighting_status,
        )
        if result.success:
            self._controller.save_lighting_override(lighting)
        self._set_lighting_status(result.message)

    async def _apply_grid(self) -> None:
        grid = self._build_grid_config_from_controls()
        result = await self._controller.apply_grid_in_kit(
            grid,
            status_callback=self._set_status,
        )
        if result:
            lighting = self._build_lighting_config_from_controls()
            self._controller.save_grid_override(lighting, grid)

    async def _apply_camera(self) -> None:
        try:
            camera = self._controller.config.camera
            if not camera:
                self._set_status("Camera apply skipped: no saved camera.")
                return
            applied = await self._controller.apply_camera_in_kit(
                camera,
                status_callback=self._set_status,
            )
            if applied:
                self._set_camera_controls(camera)
                self._suspend_camera_sync_until = 0.0
        except Exception as exc:  # noqa: BLE001
            self._set_status(f"Camera apply failed: {exc}")

    async def _reset_camera(self) -> None:
        lighting = self._build_lighting_config_from_controls()
        self._controller.clear_camera_override(lighting)
        self._set_status("Camera reset to auto-framed default.")
        await self._load_default_asset()
