"""Production X-Ray material-override lifecycle for DTRS.

Owns transient Session Layer bindings, chassis and telemetry-LED appearance
arbitration, reversible restoration of composed presentation, and compact
production performance diagnostics.  Material graph authoring and the
isolated Custom MDL Debug Probe live in sibling modules.  This module never
owns Server Enclosure visibility or writes to authored asset layers.

In the tested Case 03/current Kit environment, Fabric Scene Delegate did not
visually roll back a material despite restored USD and Fabric composition.
The application therefore uses the validated OmniHydra configuration; this is
a narrow environment limitation, not a general USD lifecycle contract.
"""

from __future__ import annotations

import time

from digital_twin_runtime_suite.app.config import XRayMaterialConfig
from digital_twin_runtime_suite.app.xray import performance
from digital_twin_runtime_suite.app.xray.material import (
    XRayApplyResult,
    XRayMaterialMixin,
)


class XRayRuntimeMixin(XRayMaterialMixin):
    """Own the reversible production X-Ray binding lifecycle.

    ``RuntimeController`` supplies application-lifetime state and the existing
    telemetry appearance updater.  This mixin owns the temporary X-Ray
    Session Layer opinions and guarantees that static chassis targets release
    those opinions on OFF rather than binding a guessed original material.
    """

    XRAY_CHASSIS_ROOT_PATH = "/blackwell_rig/chassis"
    XRAY_MATERIAL_PATH = "/DTRS_Runtime/Looks/XRayLifecycleControl"
    XRAY_MATERIAL_PERFORMANCE_SAMPLE_INTERVAL_SECONDS = 0.5
    XRAY_MATERIAL_PERFORMANCE_LOG_INTERVAL_SECONDS = 10.0

    def apply_xray_material_in_kit(self, xray: XRayMaterialConfig) -> XRayApplyResult:
        """Apply or release the production control override in the Session Layer.

        ON gives every resolved chassis mesh the production Fresnel material.
        OFF removes only opinions owned by X-Ray, so ordinary geometry naturally
        recomposes to authored USD while LEDs resume their current telemetry
        state through the existing presentation updater.
        """

        import carb
        import omni.usd
        from pxr import Gf, Sdf, Usd, UsdShade

        stage = omni.usd.get_context().get_stage()
        if not stage:
            return XRayApplyResult(False, "X-Ray skipped: no open stage.")

        previous_target = stage.GetEditTarget()
        stage.SetEditTarget(stage.GetSessionLayer())
        try:
            if not xray.chassis_selected:
                removed_count, diagnostics = self._clear_xray_session_overrides(
                    stage, Sdf, Usd, UsdShade
                )
                led_reapplied, led_matches_current_state = (
                    self._reapply_front_panel_indicator_current_state(
                        stage, Gf, Sdf, Usd, UsdShade
                    )
                )
                self._log_xray_lifecycle_diagnostic(
                    carb,
                    action="OFF",
                    formatter=lambda: self._format_xray_lifecycle_diagnostics(
                        "OFF",
                        diagnostics,
                        led_current_state_reapplied=led_reapplied,
                        led_binding_matches_current_state=led_matches_current_state,
                    ),
                )
                return XRayApplyResult(
                    True,
                    "X-Ray removed; original chassis materials restored.",
                    removed_count,
                )
            try:
                target_count, diagnostics = self._apply_xray_session_overrides(
                    stage, xray, Gf, Sdf, Usd, UsdShade
                )
            except RuntimeError as error:
                carb.log_error(
                    self._format_xray_lifecycle_diagnostics(
                        "ON FAILED", self._xray_last_lifecycle_diagnostics
                    )
                    + f"\n  error: {error}"
                )
                carb.log_error(f"DTRS X-Ray apply failed: {error}")
                return XRayApplyResult(False, f"X-Ray apply failed: {error}")
            self._start_xray_material_performance_sampler()
            self._log_xray_lifecycle_diagnostic(
                carb,
                action="ON",
                formatter=lambda: self._format_xray_lifecycle_diagnostics(
                    "ON", diagnostics
                ),
            )
            return XRayApplyResult(
                True,
                "X-Ray Fresnel material applied.",
                target_count,
            )
        finally:
            stage.SetEditTarget(previous_target)

    def sync_xray_fresnel_material_camera_in_kit(self) -> bool:
        """Update production Fresnel camera input from ReviewCamera when active.

        The existing extension update loop owns scheduling. This method owns
        no loop and updates only the active production material instance.
        """

        import omni.usd
        from pxr import Gf, Usd, UsdGeom, UsdShade

        stage = omni.usd.get_context().get_stage()
        if not stage:
            return False
        material = stage.GetPrimAtPath(self.XRAY_MATERIAL_PATH)
        if not material or not material.IsValid():
            return False
        shader = UsdShade.Shader.Get(stage, f"{self.XRAY_MATERIAL_PATH}/Shader")
        if not shader or not shader.GetPrim().IsValid():
            return False
        camera_input = shader.GetInput("camera_position")
        if not camera_input or not camera_input.GetAttr().HasAuthoredValue():
            return False
        current_position = self._xray_review_camera_position(stage, Usd, UsdGeom)
        if current_position is None:
            return False
        authored_position = camera_input.Get()
        if authored_position is None or self._xray_camera_positions_match(
            current_position, authored_position
        ):
            return False
        previous_target = stage.GetEditTarget()
        stage.SetEditTarget(stage.GetSessionLayer())
        try:
            camera_input.Set(Gf.Vec3f(*current_position))
        finally:
            stage.SetEditTarget(previous_target)
        return True

    def advance_xray_material_performance_sampler_in_kit(self) -> bool:
        """Sample production X-Ray only while its transient material is active."""

        import carb
        import omni.usd

        try:
            stage = omni.usd.get_context().get_stage()
            material = stage.GetPrimAtPath(self.XRAY_MATERIAL_PATH) if stage else None
            if not material or not material.IsValid():
                self._stop_xray_material_performance_sampler()
                return False
            self._advance_xray_material_performance_sampler(carb)
            return True
        except Exception as error:  # Diagnostics must not interrupt Kit updates.
            self._log_xray_lifecycle_diagnostic(
                carb,
                action="PERFORMANCE",
                formatter=lambda error=error: (_ for _ in ()).throw(error),
            )
            return False

    def _start_xray_material_performance_sampler(self) -> None:
        """Start a HUD-backed interval for one production X-Ray activation."""

        initial_sample = performance.capture_viewport_performance_sample()
        started_at = initial_sample.captured_at
        self._xray_material_performance_started_at = started_at
        self._xray_material_performance_next_sample_at = (
            started_at + self.XRAY_MATERIAL_PERFORMANCE_SAMPLE_INTERVAL_SECONDS
        )
        self._xray_material_performance_next_log_at = (
            started_at + self.XRAY_MATERIAL_PERFORMANCE_LOG_INTERVAL_SECONDS
        )
        self._xray_material_performance_interval_started_at = started_at
        self._xray_material_performance_samples = [initial_sample]

    def _stop_xray_material_performance_sampler(self) -> None:
        self._xray_material_performance_started_at = None
        self._xray_material_performance_next_sample_at = None
        self._xray_material_performance_next_log_at = None
        self._xray_material_performance_interval_started_at = None
        self._xray_material_performance_samples = []

    def _advance_xray_material_performance_sampler(self, carb) -> None:
        started_at = self._xray_material_performance_started_at
        next_sample_at = self._xray_material_performance_next_sample_at
        next_log_at = self._xray_material_performance_next_log_at
        if started_at is None or next_sample_at is None or next_log_at is None:
            self._start_xray_material_performance_sampler()
            return
        now = time.monotonic()
        if now < next_sample_at:
            return
        try:
            sample = performance.capture_viewport_performance_sample()
        except Exception as error:
            self._xray_material_performance_next_sample_at = (
                now + self.XRAY_MATERIAL_PERFORMANCE_SAMPLE_INTERVAL_SECONDS
            )
            self._log_xray_lifecycle_diagnostic(
                carb,
                action="PERFORMANCE",
                formatter=lambda error=error: (_ for _ in ()).throw(error),
            )
            return
        self._xray_material_performance_samples.append(sample)
        self._xray_material_performance_next_sample_at = (
            now + self.XRAY_MATERIAL_PERFORMANCE_SAMPLE_INTERVAL_SECONDS
        )
        if now < next_log_at:
            return
        interval_started_at = self._xray_material_performance_interval_started_at
        interval_samples = [
            item
            for item in self._xray_material_performance_samples
            if interval_started_at is None or item.captured_at >= interval_started_at
        ]
        self._log_xray_lifecycle_diagnostic(
            carb,
            action="PERFORMANCE",
            formatter=lambda: self._format_xray_material_performance_interval(
                interval_samples
            ),
        )
        self._xray_material_performance_interval_started_at = sample.captured_at
        self._xray_material_performance_next_log_at = (
            now + self.XRAY_MATERIAL_PERFORMANCE_LOG_INTERVAL_SECONDS
        )

    def _format_xray_material_performance_interval(
        self, samples: list[performance.ViewportPerformanceSample]
    ) -> str:
        statistics = performance.viewport_performance_state(samples)
        latest = samples[-1] if samples else None
        started_at = self._xray_material_performance_started_at
        elapsed = (
            latest.captured_at - started_at
            if latest is not None and started_at is not None
            else None
        )
        elapsed_text = f"{elapsed:.1f} s" if elapsed is not None else "<unavailable>"
        return "\n".join(
            (
                "DTRS X-Ray binding lifecycle - PERFORMANCE",
                f"  elapsed={elapsed_text}",
                f"  control_material_path={self.XRAY_MATERIAL_PATH}",
                f"  samples={len(samples)}",
                "  FPS: "
                f"current={statistics['fps_current']}; "
                f"average={statistics['average_fps']}; "
                f"minimum={statistics['minimum_fps']}; "
                f"maximum={statistics['maximum_fps']}",
                "  Frame time: "
                f"current={statistics['frame_time_ms_current']} ms; "
                f"average={statistics['average_frame_time_ms']} ms",
                "  Memory: "
                f"gpu_used_gib={statistics['gpu_used_gib']}; "
                f"process_used_gib={statistics['process_used_gib']}",
            )
        )

    def clear_xray_material_in_kit(self) -> XRayApplyResult:
        """Release runtime X-Ray state during config, stage, or app cleanup."""

        import carb
        import omni.usd
        from pxr import Gf, Sdf, Usd, UsdShade

        stage = omni.usd.get_context().get_stage()
        if not stage:
            return XRayApplyResult(True, "X-Ray is inactive; no open stage.")
        previous_target = stage.GetEditTarget()
        stage.SetEditTarget(stage.GetSessionLayer())
        try:
            removed_count, diagnostics = self._clear_xray_session_overrides(
                stage, Sdf, Usd, UsdShade
            )
            led_reapplied, led_matches_current_state = (
                self._reapply_front_panel_indicator_current_state(
                    stage, Gf, Sdf, Usd, UsdShade
                )
            )
        finally:
            stage.SetEditTarget(previous_target)
        self._log_xray_lifecycle_diagnostic(
            carb,
            action="OFF / cleanup",
            formatter=lambda: self._format_xray_lifecycle_diagnostics(
                "OFF / cleanup",
                diagnostics,
                led_current_state_reapplied=led_reapplied,
                led_binding_matches_current_state=led_matches_current_state,
            ),
        )
        return XRayApplyResult(
            True,
            "X-Ray disabled; original chassis materials restored.",
            removed_count,
        )

    def _clear_xray_session_overrides(self, stage, Sdf, Usd, UsdShade):
        """Remove only X-Ray's binding specs and restore prior Session opinions."""

        self._discard_stale_xray_binding_snapshots(stage)
        removed_count = 0
        diagnostics = []
        root = stage.GetPrimAtPath(self.XRAY_CHASSIS_ROOT_PATH)
        if root and root.IsValid():
            records = []
            for prim in Usd.PrimRange(root):
                if prim.GetTypeName() != "Mesh":
                    continue
                relation = UsdShade.MaterialBindingAPI(prim).GetDirectBindingRel()
                property_path = relation.GetPath()
                if not self._session_binding_is_xray_owned(stage, property_path):
                    continue
                records.append(
                    (
                        prim,
                        relation,
                        property_path,
                        self._xray_binding_lifecycle_snapshot(
                            stage, prim, relation, UsdShade
                        ),
                    )
                )
            with Sdf.ChangeBlock():
                for _prim, _relation, property_path, _before in records:
                    self._remove_xray_session_binding_spec(stage, property_path)
                    prior = self._xray_session_binding_snapshots.pop(
                        str(property_path), None
                    )
                    if prior is not None:
                        self._restore_xray_session_binding_spec(
                            stage, property_path, prior, Sdf
                        )
            cleanup_failures = []
            for prim, relation, property_path, before in records:
                after = self._xray_binding_lifecycle_snapshot(
                    stage, prim, relation, UsdShade
                )
                if after["xray_owned_session_binding_after"]:
                    cleanup_failures.append(str(property_path))
                diagnostics.append(
                    {
                        "before": before,
                        "after": after,
                        "is_led": self._is_xray_led_prim(prim),
                        "baseline_match": (
                            self._xray_baseline_composed_bindings.get(
                                str(property_path)
                            )
                            == after["composed_binding"]
                        ),
                    }
                )
                removed_count += 1
            if cleanup_failures:
                raise RuntimeError(
                    "X-Ray binding cleanup did not remove: "
                    + ", ".join(cleanup_failures)
                )
        self._stop_xray_material_performance_sampler()
        self._xray_session_binding_snapshots.clear()
        self._xray_baseline_composed_bindings.clear()
        self._xray_last_lifecycle_diagnostics = diagnostics
        return removed_count, diagnostics

    def _apply_xray_session_overrides(self, stage, xray, Gf, Sdf, Usd, UsdShade):
        """Bind production Fresnel to every chassis mesh as one reversible transition.

        Static chassis and telemetry LEDs share the temporary binding while
        active.  The latter retain their provider state beneath X-Ray, so the
        application can reapply their *current* appearance when the transition
        is released.
        """

        self._discard_stale_xray_binding_snapshots(stage)
        root = stage.GetPrimAtPath(self.XRAY_CHASSIS_ROOT_PATH)
        if not root or not root.IsValid():
            raise RuntimeError("X-Ray chassis target root is unavailable.")
        from pxr import UsdGeom

        # The operator-owned production X-Ray config is passed directly so
        # Apply updates the material before its settings are persisted.
        fresnel = xray
        values = (
            fresnel.facing_color,
            fresnel.edge_color,
            fresnel.edge_center,
            fresnel.edge_softness,
            fresnel.edge_sharpness,
            fresnel.facing_roughness,
            fresnel.edge_roughness,
            fresnel.facing_opacity,
            fresnel.edge_opacity,
            fresnel.facing_emission,
            fresnel.edge_emission,
            fresnel.emission_scale,
        )
        camera_position = self._xray_review_camera_position(stage, Usd, UsdGeom)
        self._define_xray_fresnel_material(
            stage, self.XRAY_MATERIAL_PATH, Sdf, UsdShade
        )
        self._set_xray_fresnel_material_values(
            stage,
            self.XRAY_MATERIAL_PATH,
            values,
            Gf,
            Sdf,
            UsdShade,
            camera_position=camera_position or (0.0, 0.0, 0.0),
        )
        diagnostics = []
        target_count = 0
        try:
            records = []
            for prim in Usd.PrimRange(root):
                if prim.GetTypeName() != "Mesh":
                    continue
                relation = UsdShade.MaterialBindingAPI(prim).GetDirectBindingRel()
                property_path = relation.GetPath()
                before = self._xray_binding_lifecycle_snapshot(
                    stage, prim, relation, UsdShade
                )
                if not self._session_binding_is_xray_owned(stage, property_path):
                    self._capture_xray_session_binding_spec(stage, property_path, Sdf)
                    self._xray_baseline_composed_bindings.setdefault(
                        str(property_path), before["composed_binding"]
                    )
                records.append((prim, relation, property_path, before))
            # Author every relationship first.  Composed USD queries can be
            # stale inside a ChangeBlock, so validation intentionally follows
            # only after the block closes.
            with Sdf.ChangeBlock():
                for _prim, _relation, property_path, _before in records:
                    self._author_xray_session_binding_spec(stage, property_path, Sdf)
            failures = []
            for prim, relation, property_path, before in records:
                after = self._xray_binding_lifecycle_snapshot(
                    stage, prim, relation, UsdShade
                )
                diagnostics.append(
                    {
                        "before": before,
                        "after": after,
                        "is_led": self._is_xray_led_prim(prim),
                    }
                )
                if not after["xray_owned_session_binding_after"]:
                    failures.append(str(property_path))
                target_count += 1
            if failures:
                mismatch_paths = self._format_xray_mismatch_paths(failures)
                raise RuntimeError(
                    "X-Ray binding mismatch_count="
                    f"{len(failures)}; paths={mismatch_paths}"
                )
        except Exception:
            failed_diagnostics = diagnostics
            self._clear_xray_session_overrides(stage, Sdf, Usd, UsdShade)
            self._reapply_front_panel_indicator_current_state(
                stage, Gf, Sdf, Usd, UsdShade
            )
            self._xray_last_lifecycle_diagnostics = failed_diagnostics
            raise
        self._xray_last_lifecycle_diagnostics = diagnostics
        return target_count, diagnostics

    def _is_xray_led_prim(self, prim) -> bool:
        """Identify telemetry-owned LED geometry within the resolved chassis set."""

        indicators = self.config.chassis_presentation.front_panel_indicators
        target_path = str(prim.GetPath())
        return any(
            path and (target_path == path or target_path.startswith(f"{path}/"))
            for path in (
                indicators.power_path,
                indicators.hdd_path,
                indicators.lan_01_path,
                indicators.lan_02_path,
            )
        )

    def _discard_stale_xray_binding_snapshots(self, stage) -> None:
        """Drop snapshots from a replaced Session Layer without touching a stage."""

        layer_id = stage.GetSessionLayer().identifier
        if self._xray_session_binding_layer_id != layer_id:
            self._xray_session_binding_layer_id = layer_id
            self._xray_session_binding_snapshots.clear()

    def _capture_xray_session_binding_spec(self, stage, property_path, Sdf) -> None:
        """Save one prior Session opinion so OFF restores exact pre-ON ownership."""

        key = str(property_path)
        if key in self._xray_session_binding_snapshots:
            return
        session = stage.GetSessionLayer()
        if session.GetPropertyAtPath(property_path) is None:
            self._xray_session_binding_snapshots[key] = None
            return
        snapshot = Sdf.Layer.CreateAnonymous("DTRS_XRayBindingSnapshot.usda")
        Sdf.CreatePrimInLayer(snapshot, property_path.GetPrimPath())
        if not Sdf.CopySpec(session, property_path, snapshot, property_path):
            raise RuntimeError(f"Could not snapshot Session binding {property_path}.")
        self._xray_session_binding_snapshots[key] = snapshot

    @classmethod
    def _author_xray_session_binding_spec(cls, stage, property_path, Sdf) -> None:
        """Create or retarget exactly one Session Layer material-binding spec."""

        session = stage.GetSessionLayer()
        relationship_spec = session.GetRelationshipAtPath(property_path)
        if relationship_spec is None:
            prim_spec = session.GetPrimAtPath(property_path.GetPrimPath())
            if prim_spec is None:
                prim_spec = Sdf.CreatePrimInLayer(session, property_path.GetPrimPath())
            relationship_spec = Sdf.RelationshipSpec(
                prim_spec,
                property_path.name,
                custom=False,
            )
        relationship_spec.targetPathList.explicitItems = [
            Sdf.Path(cls.XRAY_MATERIAL_PATH)
        ]

    @staticmethod
    def _format_xray_mismatch_paths(paths: list[str]) -> str:
        displayed = paths[:5]
        suffix = f", ... +{len(paths) - len(displayed)} more" if len(paths) > 5 else ""
        return ", ".join(displayed) + suffix

    @staticmethod
    def _remove_xray_session_binding_spec(stage, property_path) -> None:
        """Remove an actual X-Ray-owned property spec rather than rebinding OFF."""

        session = stage.GetSessionLayer()
        property_spec = session.GetPropertyAtPath(property_path)
        if property_spec is None:
            return
        prim_spec = session.GetPrimAtPath(property_path.GetPrimPath())
        if prim_spec is None:
            raise RuntimeError(f"Session binding owner is missing for {property_path}.")
        prim_spec.RemoveProperty(property_spec)
        if session.GetPropertyAtPath(property_path) is not None:
            raise RuntimeError(
                f"Could not remove Session binding spec {property_path}."
            )

    @staticmethod
    def _restore_xray_session_binding_spec(stage, property_path, snapshot, Sdf) -> None:
        """Restore an unrelated prior Session binding captured before X-Ray ON."""

        if not Sdf.CopySpec(
            snapshot, property_path, stage.GetSessionLayer(), property_path
        ):
            raise RuntimeError(f"Could not restore Session binding {property_path}.")

    @classmethod
    def _session_binding_is_xray_owned(cls, stage, property_path) -> bool:
        """Return whether the strongest Session relationship targets X-Ray."""

        spec = stage.GetSessionLayer().GetPropertyAtPath(property_path)
        return bool(
            spec
            and str(cls.XRAY_MATERIAL_PATH)
            in {str(path) for path in spec.targetPathList.explicitItems}
        )

    @classmethod
    def _xray_binding_lifecycle_snapshot(cls, stage, prim, relation, UsdShade):
        """Capture compact per-target state for lifecycle validation diagnostics."""

        session_spec = stage.GetSessionLayer().GetPropertyAtPath(relation.GetPath())
        material, _binding = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial()
        direct_targets = (
            ", ".join(str(path) for path in relation.GetTargets()) or "<none>"
        )
        composed = str(material.GetPath()) if material else "<none>"
        return {
            "target_prim_path": str(prim.GetPath()),
            "control_material_path": str(cls.XRAY_MATERIAL_PATH),
            "binding": direct_targets,
            "session_binding_spec": "present" if session_spec else "absent",
            "composed_binding": composed,
            "control_material_alive": stage.GetPrimAtPath(
                cls.XRAY_MATERIAL_PATH
            ).IsValid(),
            "xray_owned_session_binding_after": cls._session_binding_is_xray_owned(
                stage, relation.GetPath()
            ),
        }

    @staticmethod
    def _format_xray_lifecycle_diagnostics(
        action,
        diagnostics,
        *,
        led_current_state_reapplied=None,
        led_binding_matches_current_state=None,
    ) -> str:
        """Summarise ownership counts and report detailed paths only on mismatch."""

        static = [item for item in diagnostics if not item.get("is_led", False)]
        leds = [item for item in diagnostics if item.get("is_led", False)]
        static_baseline_matches = sum(
            bool(item.get("baseline_match")) for item in static
        )
        static_xray_remaining = sum(
            bool(item["after"]["xray_owned_session_binding_after"]) for item in static
        )
        led_xray_remaining = sum(
            bool(item["after"]["xray_owned_session_binding_after"]) for item in leds
        )
        control_material_alive = any(
            item["after"].get("control_material_alive", False) for item in diagnostics
        )
        led_reapplied_value = (
            led_current_state_reapplied
            if led_current_state_reapplied is not None
            else "<not requested>"
        )
        led_matches_value = (
            led_binding_matches_current_state
            if led_binding_matches_current_state is not None
            else "<not requested>"
        )
        lines = [
            "DTRS X-Ray binding lifecycle",
            f"  action: {action}",
            f"  static_targets_total={len(static)}",
            f"  static_baseline_matches={static_baseline_matches}",
            f"  static_xray_bindings_remaining={static_xray_remaining}",
            f"  led_targets_total={len(leds)}",
            f"  led_xray_bindings_remaining={led_xray_remaining}",
            f"  led_current_state_reapplied={led_reapplied_value}",
            f"  led_binding_matches_current_state={led_matches_value}",
            f"  control_material_alive={control_material_alive}",
        ]
        if action.startswith("OFF") and static:
            if static_baseline_matches == len(static) and static_xray_remaining == 0:
                lines.extend(
                    (
                        "  USD lifecycle: PASS",
                        "  renderer synchronisation: manual visual validation required",
                    )
                )
            else:
                lines.append("  USD lifecycle: FAIL")
        for item in diagnostics:
            after = item["after"]
            mismatch = False
            if action.startswith("ON"):
                mismatch = not after["xray_owned_session_binding_after"]
            elif action.startswith("OFF"):
                mismatch = after["xray_owned_session_binding_after"]
            if action.startswith("OFF") and not item.get("is_led", False):
                mismatch = mismatch or not item.get("baseline_match", False)
            if mismatch:
                lines.append(
                    "  mismatch: "
                    f"target={after['target_prim_path']}; "
                    f"binding={after['binding']}; "
                    f"composed_binding={after['composed_binding']}; "
                    "session_binding_spec="
                    f"{after['session_binding_spec']}"
                )
        return "\n".join(lines)

    @staticmethod
    def _log_xray_lifecycle_diagnostic(carb, *, action: str, formatter) -> None:
        """Keep lifecycle diagnostics non-fatal after a binding mutation succeeds."""

        try:
            carb.log_warn(formatter())
        except Exception as error:
            carb.log_warn(
                "DTRS X-Ray binding lifecycle\n"
                f"  action: {action}\n"
                f"  diagnostic: <inspection failed: {error}>"
            )
