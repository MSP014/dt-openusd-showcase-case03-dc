"""Session-owned reusable MDL presentation for Heatmap target groups."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .palette import compact_active_stops


@dataclass(frozen=True)
class HeatmapMaterialTarget:
    """One target's immutable authored weights and current scalar parameters."""

    material_key: str
    prim_path: str
    thermal_weights: tuple[float, ...]
    telemetry_celsius: float
    delta_profile: object
    temperature_offset_celsius: float = 0.0


@dataclass(frozen=True)
class HeatmapMaterialWriteCounts:
    """Aggregate Session writes without retaining per-target diagnostic noise."""

    shader_parameter_writes: int = 0
    skipped_unchanged_parameter_writes: int = 0
    structural_material_writes: int = 0
    material_binding_writes: int = 0
    primvar_st_writes: int = 0
    material_prim_creations: int = 0


@dataclass(frozen=True)
class HeatmapPresentationResult:
    """Report the current Session-owned multi-target material presentation."""

    success: bool
    enabled: bool
    message: str
    target_paths: tuple[str, ...] = ()
    material_creations: int = 0
    parameter_updates: int = 0
    material_group_count: int = 0
    session_binding_count: int = 0
    write_counts: HeatmapMaterialWriteCounts = HeatmapMaterialWriteCounts()


@dataclass
class _TargetPresentation:
    """Exact Session state needed to restore one target's prior appearance."""

    material_key: str
    target_path: str
    binding_snapshot: object | None
    uv_snapshot: object | None
    api_schemas_snapshot: tuple[bool, object | None]


class HeatmapMaterialPresenter:
    """Own grouped Session bindings and restore only its own opinions."""

    MATERIAL_ROOT = "/DTRS_Runtime/Heatmaps"

    def __init__(self, *, material_root: str | None = None) -> None:
        self._material_root = material_root or self.MATERIAL_ROOT
        self._session_layer_id: str | None = None
        self._targets: dict[str, _TargetPresentation] = {}
        self._material_keys: set[str] = set()
        self._created_scope_paths: tuple[str, ...] = ()
        self._created_target_scope_paths: set[str] = set()
        self._material_creations = 0
        self._parameter_updates = 0
        self._shader_parameter_writes = 0
        self._skipped_unchanged_parameter_writes = 0
        self._structural_material_writes = 0
        self._material_binding_writes = 0
        self._primvar_st_writes = 0
        self._material_prim_creations = 0

    @property
    def active(self) -> bool:
        """Return whether any target currently has Heatmap Session presentation."""

        return bool(self._targets or self._material_keys)

    @property
    def material_root(self) -> str:
        """Return the Session scope owned by this presenter instance."""

        return self._material_root

    @property
    def write_counts(self) -> HeatmapMaterialWriteCounts:
        """Expose cumulative owned-write evidence for one active presentation."""

        return HeatmapMaterialWriteCounts(
            shader_parameter_writes=self._shader_parameter_writes,
            skipped_unchanged_parameter_writes=self._skipped_unchanged_parameter_writes,
            structural_material_writes=self._structural_material_writes,
            material_binding_writes=self._material_binding_writes,
            primvar_st_writes=self._primvar_st_writes,
            material_prim_creations=self._material_prim_creations,
        )

    def enable(
        self,
        stage,
        *,
        targets: tuple[HeatmapMaterialTarget, ...],
        scale,
        palette,
    ) -> HeatmapPresentationResult:
        """Synchronize target materials without rebuilding stable bindings."""

        from pxr import Gf, Sdf, UsdGeom, UsdShade, Vt

        self._discard_stale_state(stage)
        paths = tuple(target.prim_path for target in targets)
        if len(paths) != len(set(paths)):
            return self._result(False, "Heatmap material targets must be unique.")
        previous_target = stage.GetEditTarget()
        stage.SetEditTarget(stage.GetSessionLayer())
        try:
            if not self._targets and not self._material_keys:
                self._created_scope_paths = self._capture_created_scope_paths(
                    stage,
                    Sdf,
                )
            desired = {target.prim_path: target for target in targets}
            for path in tuple(self._targets):
                if path not in desired:
                    self._restore_target(stage, self._targets.pop(path), Sdf)
            grouped_targets = _targets_by_material_key(targets)
            for material_key, group_targets in grouped_targets.items():
                existing = material_key in self._material_keys
                material_path = self._material_path(material_key)
                if not existing:
                    self._define_material(stage, material_path, Sdf, UsdShade)
                    self._material_keys.add(material_key)
                    self._material_creations += 1
                    self._material_prim_creations += 1
                    self._structural_material_writes += 1
                self._set_parameters(
                    stage,
                    material_path,
                    group_targets[0],
                    scale,
                    palette,
                    Gf,
                    Sdf,
                    UsdShade,
                    include_static=not existing,
                )
            for target in targets:
                existing = self._targets.get(target.prim_path)
                if existing is None:
                    self._create_target(
                        stage,
                        target,
                        Sdf,
                        UsdGeom,
                        UsdShade,
                        Vt,
                    )
            self._parameter_updates += 1
        except Exception as error:  # noqa: BLE001 - leave no partial presentation.
            self._restore_all(stage, Sdf)
            return self._result(False, f"Heatmap material presentation failed: {error}")
        finally:
            stage.SetEditTarget(previous_target)
        return self._result(True, "Heatmap presentation synchronized.")

    def refresh(
        self,
        stage,
        *,
        targets: tuple[HeatmapMaterialTarget, ...],
        scale,
        palette,
    ) -> HeatmapPresentationResult:
        """Refresh dynamic telemetry parameters and retain target material ownership."""

        return self.enable(stage, targets=targets, scale=scale, palette=palette)

    def update_telemetry(
        self,
        stage,
        telemetry_by_material_key,
    ) -> HeatmapPresentationResult:
        """Write only changed dynamic telemetry inputs for existing materials."""

        from pxr import Sdf, UsdShade

        self._discard_stale_state(stage)
        if not self.active:
            return self._result(True, "Heatmap presentation is inactive.")
        previous_target = stage.GetEditTarget()
        stage.SetEditTarget(stage.GetSessionLayer())
        try:
            for material_key, telemetry_celsius in sorted(
                telemetry_by_material_key.items()
            ):
                if material_key not in self._material_keys:
                    continue
                self._set_dynamic_telemetry(
                    stage,
                    self._material_path(material_key),
                    telemetry_celsius,
                    Sdf,
                    UsdShade,
                )
        except Exception as error:  # noqa: BLE001 - dynamic updates own no topology.
            return self._result(False, f"Heatmap telemetry update failed: {error}")
        finally:
            stage.SetEditTarget(previous_target)
        return self._result(True, "Heatmap telemetry parameters synchronized.")

    def disable(self, stage) -> HeatmapPresentationResult:
        """Remove every Heatmap-owned target opinion and reveal prior presentation."""

        from pxr import Sdf

        self._discard_stale_state(stage)
        if not self.active:
            return self._result(True, "Heatmap presentation is inactive.")
        previous_target = stage.GetEditTarget()
        stage.SetEditTarget(stage.GetSessionLayer())
        try:
            self._restore_all(stage, Sdf)
        except Exception as error:  # noqa: BLE001 - restoration is a hard stop.
            return self._result(False, f"Heatmap material restoration failed: {error}")
        finally:
            stage.SetEditTarget(previous_target)
        return self._result(True, "Heatmap appearance restored.")

    def discard_stale_stage(self, stage) -> None:
        """Forget old Session ownership after a replacement stage becomes current."""

        self._discard_stale_state(stage)

    def _create_target(
        self,
        stage,
        target,
        Sdf,
        UsdGeom,
        UsdShade,
        Vt,
    ) -> None:
        prim = stage.GetPrimAtPath(target.prim_path)
        if not prim or not prim.IsValid():
            raise RuntimeError(f"Heatmap target is unavailable: {target.prim_path}.")
        if not target.thermal_weights:
            raise RuntimeError(f"Heatmap weights are unavailable: {target.prim_path}.")
        binding_path = UsdShade.MaterialBindingAPI(prim).GetDirectBindingRel().GetPath()
        uv_path = Sdf.Path(target.prim_path).AppendProperty("primvars:st")
        self._capture_created_target_scope_paths(stage, target.prim_path, Sdf)
        previous = _TargetPresentation(
            material_key=target.material_key,
            target_path=target.prim_path,
            binding_snapshot=self._capture_property(stage, binding_path, Sdf),
            uv_snapshot=self._capture_property(stage, uv_path, Sdf),
            api_schemas_snapshot=self._capture_api_schemas(stage, prim, Sdf),
        )
        self._targets[target.prim_path] = previous
        material = UsdShade.Material.Get(
            stage,
            self._material_path(target.material_key),
        )
        self._author_weight_uv(prim, target.thermal_weights, Sdf, UsdGeom, Vt)
        self._primvar_st_writes += 1
        UsdShade.MaterialBindingAPI.Apply(prim).Bind(material)
        self._material_binding_writes += 1

    def _restore_all(self, stage, Sdf) -> None:
        for presentation in tuple(self._targets.values()):
            self._restore_target(stage, presentation, Sdf)
        self._targets.clear()
        self._material_keys.clear()
        stage.RemovePrim(self._material_root)
        self._remove_empty_created_target_scopes(stage, Sdf)
        self._remove_empty_created_scopes(stage, Sdf)
        self._created_scope_paths = ()
        self._created_target_scope_paths.clear()
        self._material_creations = 0
        self._parameter_updates = 0
        self._shader_parameter_writes = 0
        self._skipped_unchanged_parameter_writes = 0
        self._structural_material_writes = 0
        self._material_binding_writes = 0
        self._primvar_st_writes = 0
        self._material_prim_creations = 0

    def _restore_target(self, stage, presentation, Sdf) -> None:
        binding_path = Sdf.Path(presentation.target_path).AppendProperty(
            "material:binding"
        )
        uv_path = Sdf.Path(presentation.target_path).AppendProperty("primvars:st")
        self._restore_property(stage, binding_path, presentation.binding_snapshot, Sdf)
        self._restore_property(stage, uv_path, presentation.uv_snapshot, Sdf)
        self._restore_api_schemas(stage, presentation, Sdf)

    @staticmethod
    def _define_material(stage, material_path, Sdf, UsdShade):
        material = UsdShade.Material.Define(stage, material_path)
        shader = UsdShade.Shader.Define(stage, f"{material_path}/Shader")
        shader.CreateImplementationSourceAttr().Set(UsdShade.Tokens.sourceAsset)
        mdl_path = (
            Path(__file__).resolve().parents[2]
            / "ext"
            / "msp.dtrs"
            / "data"
            / "materials"
            / "DTRS_Heatmap.mdl"
        )
        shader.SetSourceAsset(Sdf.AssetPath(str(mdl_path)), "mdl")
        shader.SetSourceAssetSubIdentifier("DTRS_Heatmap", "mdl")
        shader.CreateOutput("out", Sdf.ValueTypeNames.Token).SetRenderType("material")
        material.CreateSurfaceOutput("mdl").ConnectToSource(
            shader.ConnectableAPI(),
            "out",
        )
        return material

    @staticmethod
    def _author_weight_uv(target, thermal_weights, Sdf, UsdGeom, Vt) -> None:
        values = Vt.Vec2fArray([(float(weight), 0.5) for weight in thermal_weights])
        UsdGeom.PrimvarsAPI(target).CreatePrimvar(
            "st",
            Sdf.ValueTypeNames.TexCoord2fArray,
            UsdGeom.Tokens.vertex,
        ).Set(values)

    def _set_parameters(
        self,
        stage,
        material_path,
        target,
        scale,
        palette,
        Gf,
        Sdf,
        UsdShade,
        *,
        include_static: bool,
    ) -> None:
        shader = UsdShade.Shader.Get(stage, f"{material_path}/Shader")
        for name, value in (
            ("telemetry_celsius", target.telemetry_celsius),
            ("delta_minimum_celsius", target.delta_profile.minimum_celsius),
            ("delta_maximum_celsius", target.delta_profile.maximum_celsius),
            ("temperature_offset_celsius", target.temperature_offset_celsius),
        ):
            self._set_shader_input(
                shader,
                name,
                Sdf.ValueTypeNames.Float,
                float(value),
                structural=False,
            )
        if not include_static:
            return
        self._set_shader_input(
            shader,
            "scale_minimum_celsius",
            Sdf.ValueTypeNames.Float,
            float(scale.minimum),
            structural=True,
        )
        self._set_shader_input(
            shader,
            "scale_maximum_celsius",
            Sdf.ValueTypeNames.Float,
            float(scale.maximum),
            structural=True,
        )
        active_stops = compact_active_stops(palette)
        self._set_shader_input(
            shader,
            "minimum_clamp_scalar",
            Sdf.ValueTypeNames.Float,
            float(palette.minimum_clamp_percent / 100.0),
            structural=True,
        )
        self._set_shader_input(
            shader,
            "maximum_clamp_scalar",
            Sdf.ValueTypeNames.Float,
            float(palette.maximum_clamp_percent / 100.0),
            structural=True,
        )
        self._set_shader_input(
            shader,
            "active_stop_count",
            Sdf.ValueTypeNames.Int,
            len(active_stops),
            structural=True,
        )
        padded_stops = (*active_stops, *((active_stops[-1],) * (6 - len(active_stops))))
        for index, stop in enumerate(padded_stops):
            self._set_shader_input(
                shader,
                f"stop_{index}",
                Sdf.ValueTypeNames.Float,
                float(stop.position),
                structural=True,
            )
            self._set_shader_input(
                shader,
                f"color_{index}",
                Sdf.ValueTypeNames.Color3f,
                Gf.Vec3f(*stop.color),
                structural=True,
            )

    def _set_dynamic_telemetry(
        self,
        stage,
        material_path,
        telemetry_celsius,
        Sdf,
        UsdShade,
    ) -> None:
        shader = UsdShade.Shader.Get(stage, f"{material_path}/Shader")
        self._set_shader_input(
            shader,
            "telemetry_celsius",
            Sdf.ValueTypeNames.Float,
            float(telemetry_celsius),
            structural=False,
        )

    def _set_shader_input(
        self,
        shader,
        name,
        value_type,
        value,
        *,
        structural: bool,
    ) -> None:
        input_attr = shader.GetInput(name)
        if input_attr and input_attr.Get() == value:
            self._skipped_unchanged_parameter_writes += 1
            return
        shader.CreateInput(name, value_type).Set(value)
        self._shader_parameter_writes += 1
        if structural:
            self._structural_material_writes += 1

    @staticmethod
    def _capture_property(stage, property_path, Sdf):
        session = stage.GetSessionLayer()
        if session.GetPropertyAtPath(property_path) is None:
            return None
        snapshot = Sdf.Layer.CreateAnonymous("DTRS_HeatmapPresentationSnapshot.usda")
        Sdf.CreatePrimInLayer(snapshot, property_path.GetPrimPath())
        if not Sdf.CopySpec(session, property_path, snapshot, property_path):
            raise RuntimeError(f"Could not snapshot Session property {property_path}.")
        return snapshot

    @staticmethod
    def _restore_property(stage, property_path, snapshot, Sdf) -> None:
        session = stage.GetSessionLayer()
        existing = session.GetPropertyAtPath(property_path)
        if existing is not None:
            prim_spec = session.GetPrimAtPath(property_path.GetPrimPath())
            prim_spec.RemoveProperty(existing)
        if snapshot is not None and not Sdf.CopySpec(
            snapshot,
            property_path,
            session,
            property_path,
        ):
            raise RuntimeError(f"Could not restore Session property {property_path}.")

    @staticmethod
    def _capture_api_schemas(stage, prim, Sdf) -> tuple[bool, object | None]:
        session_prim = stage.GetSessionLayer().GetPrimAtPath(prim.GetPath())
        if session_prim is None or not session_prim.HasInfo("apiSchemas"):
            return (False, None)
        return (True, session_prim.GetInfo("apiSchemas"))

    @staticmethod
    def _restore_api_schemas(stage, presentation, Sdf) -> None:
        session_prim = stage.GetSessionLayer().GetPrimAtPath(
            Sdf.Path(presentation.target_path)
        )
        if session_prim is None:
            return
        present, value = presentation.api_schemas_snapshot
        if present:
            session_prim.SetInfo("apiSchemas", value)
        else:
            session_prim.ClearInfo("apiSchemas")

    def _capture_created_scope_paths(self, stage, Sdf) -> tuple[str, ...]:
        session = stage.GetSessionLayer()
        return tuple(
            path
            for path in (
                "/DTRS_Runtime",
                "/DTRS_Runtime/Heatmaps",
                self._material_root,
            )
            if session.GetPrimAtPath(Sdf.Path(path)) is None
        )

    def _remove_empty_created_scopes(self, stage, Sdf) -> None:
        session = stage.GetSessionLayer()
        for path in reversed(self._created_scope_paths):
            sdf_path = Sdf.Path(path)
            prim_spec = session.GetPrimAtPath(sdf_path)
            if prim_spec is None or prim_spec.nameChildren or prim_spec.properties:
                continue
            parent = session.GetPrimAtPath(sdf_path.GetParentPath())
            if parent is not None:
                del parent.nameChildren[prim_spec.name]

    def _capture_created_target_scope_paths(self, stage, target_path, Sdf) -> None:
        """Remember only target ancestors introduced by this Session presenter."""

        session = stage.GetSessionLayer()
        current = Sdf.Path(target_path)
        while current != Sdf.Path.absoluteRootPath:
            if session.GetPrimAtPath(current) is None:
                self._created_target_scope_paths.add(str(current))
            current = current.GetParentPath()

    def _remove_empty_created_target_scopes(self, stage, Sdf) -> None:
        """Remove empty target overs without touching pre-existing Session state."""

        session = stage.GetSessionLayer()
        for path in sorted(
            self._created_target_scope_paths,
            key=lambda item: item.count("/"),
            reverse=True,
        ):
            sdf_path = Sdf.Path(path)
            prim_spec = session.GetPrimAtPath(sdf_path)
            if prim_spec is None or prim_spec.nameChildren or prim_spec.properties:
                continue
            parent = session.GetPrimAtPath(sdf_path.GetParentPath())
            if parent is not None:
                del parent.nameChildren[prim_spec.name]

    def _discard_stale_state(self, stage) -> None:
        layer_id = stage.GetSessionLayer().identifier
        if self._session_layer_id == layer_id:
            return
        self._session_layer_id = layer_id
        self._targets.clear()
        self._material_keys.clear()
        self._created_scope_paths = ()
        self._created_target_scope_paths.clear()

    def _material_path(self, material_key: str) -> str:
        return f"{self._material_root}/{material_key}"

    def _result(self, success: bool, message: str) -> HeatmapPresentationResult:
        return HeatmapPresentationResult(
            success=success,
            enabled=self.active,
            message=message,
            target_paths=tuple(sorted(self._targets)),
            material_creations=self._material_creations,
            parameter_updates=self._parameter_updates,
            material_group_count=len(self._material_keys),
            session_binding_count=len(self._targets),
            write_counts=self.write_counts,
        )


def _targets_by_material_key(
    targets: tuple[HeatmapMaterialTarget, ...],
) -> dict[str, tuple[HeatmapMaterialTarget, ...]]:
    """Preserve one shared parameter set for each semantic presentation group."""

    grouped: dict[str, list[HeatmapMaterialTarget]] = {}
    for target in targets:
        grouped.setdefault(target.material_key, []).append(target)
    return {
        material_key: tuple(group) for material_key, group in sorted(grouped.items())
    }
