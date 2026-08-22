"""Session-layer visibility isolation owned exclusively by the Heatmap harness."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HeatmapIsolationResult:
    """Outcome of one generic isolation or exact restoration operation."""

    success: bool
    enabled: bool
    message: str
    target_paths: tuple[str, ...] = ()
    owned_visibility_paths: tuple[str, ...] = ()


class HeatmapIsolation:
    """Own minimal Session visibility opinions and restore their exact prior specs."""

    def __init__(self, *, root_path: str = "/blackwell_rig") -> None:
        self._root_path = root_path
        self._session_layer_id: str | None = None
        self._visibility_snapshots: dict[str, object | None] = {}
        self._created_scope_paths: set[str] = set()
        self._target_paths: tuple[str, ...] = ()

    @property
    def active(self) -> bool:
        """Return whether this owner currently has a visibility presentation."""

        return bool(self._visibility_snapshots)

    @property
    def target_paths(self) -> tuple[str, ...]:
        """Return the active generic selection without exposing mutable state."""

        return self._target_paths

    def apply(self, stage, target_paths: tuple[str, ...]) -> HeatmapIsolationResult:
        """Isolate any validated target union with no asset-specific resolver."""

        from pxr import Sdf, UsdGeom

        self._discard_stale_state(stage)
        paths = tuple(sorted(set(target_paths)))
        if not paths:
            return self.restore(stage)
        if self.active:
            return HeatmapIsolationResult(
                True,
                True,
                "Heatmap isolation is already active; restore before replacement.",
                self._target_paths,
                self.owned_visibility_paths,
            )
        try:
            visibility_plan = _visibility_plan(
                stage,
                UsdGeom,
                root_path=self._root_path,
                target_paths=paths,
            )
        except RuntimeError as error:
            return HeatmapIsolationResult(False, False, str(error), paths)
        previous_target = stage.GetEditTarget()
        stage.SetEditTarget(stage.GetSessionLayer())
        try:
            with Sdf.ChangeBlock():
                for path, visibility in visibility_plan.items():
                    self._capture_visibility_spec(stage, path, Sdf)
                    prim = stage.GetPrimAtPath(path)
                    UsdGeom.Imageable(prim).CreateVisibilityAttr().Set(visibility)
            self._target_paths = paths
        except Exception as error:  # noqa: BLE001 - exact rollback is the contract.
            self._restore_owned_specs(stage, Sdf)
            return HeatmapIsolationResult(
                False,
                False,
                f"Heatmap isolation failed: {error}",
                paths,
            )
        finally:
            stage.SetEditTarget(previous_target)
        return HeatmapIsolationResult(
            True,
            True,
            "Heatmap isolation applied.",
            paths,
            self.owned_visibility_paths,
        )

    def restore(self, stage) -> HeatmapIsolationResult:
        """Restore exact Session visibility without changing persisted settings."""

        from pxr import Sdf

        self._discard_stale_state(stage)
        if not self.active:
            return HeatmapIsolationResult(
                True,
                False,
                "Heatmap isolation is already restored.",
            )
        previous_target = stage.GetEditTarget()
        stage.SetEditTarget(stage.GetSessionLayer())
        try:
            self._restore_owned_specs(stage, Sdf)
        except Exception as error:  # noqa: BLE001 - keep state for caller recovery.
            return HeatmapIsolationResult(
                False,
                True,
                f"Heatmap isolation restore failed: {error}",
                self._target_paths,
                self.owned_visibility_paths,
            )
        finally:
            stage.SetEditTarget(previous_target)
        return HeatmapIsolationResult(
            True,
            False,
            "Heatmap isolation restored the prior scene presentation.",
        )

    @property
    def owned_visibility_paths(self) -> tuple[str, ...]:
        """Return precisely the Session properties this owner may restore."""

        return tuple(sorted(self._visibility_snapshots))

    def discard_stale_stage(self, stage) -> None:
        """Forget stale ownership after a stage replacement without mutating USD."""

        self._discard_stale_state(stage)

    def _discard_stale_state(self, stage) -> None:
        layer_id = stage.GetSessionLayer().identifier
        if self._session_layer_id == layer_id:
            return
        self._session_layer_id = layer_id
        self._visibility_snapshots.clear()
        self._created_scope_paths.clear()
        self._target_paths = ()

    def _capture_visibility_spec(self, stage, path: str, Sdf) -> None:
        property_path = Sdf.Path(path).AppendProperty("visibility")
        key = str(property_path)
        if key in self._visibility_snapshots:
            return
        session = stage.GetSessionLayer()
        self._capture_created_scope_paths(session, property_path.GetPrimPath(), Sdf)
        if session.GetPropertyAtPath(property_path) is None:
            self._visibility_snapshots[key] = None
            return
        snapshot = Sdf.Layer.CreateAnonymous("DTRS_HeatmapIsolationSnapshot.usda")
        Sdf.CreatePrimInLayer(snapshot, property_path.GetPrimPath())
        if not Sdf.CopySpec(session, property_path, snapshot, property_path):
            raise RuntimeError(
                f"Could not snapshot Session visibility {property_path}."
            )
        self._visibility_snapshots[key] = snapshot

    def _restore_owned_specs(self, stage, Sdf) -> None:
        with Sdf.ChangeBlock():
            for key, snapshot in self._visibility_snapshots.items():
                property_path = Sdf.Path(key)
                _remove_visibility_spec(stage, property_path)
                if snapshot is not None and not Sdf.CopySpec(
                    snapshot,
                    property_path,
                    stage.GetSessionLayer(),
                    property_path,
                ):
                    raise RuntimeError(
                        f"Could not restore Session visibility {property_path}."
                    )
        self._remove_empty_created_scopes(stage, Sdf)
        self._visibility_snapshots.clear()
        self._created_scope_paths.clear()
        self._target_paths = ()

    def _capture_created_scope_paths(self, session, prim_path, Sdf) -> None:
        current = prim_path
        while current != Sdf.Path.absoluteRootPath:
            if session.GetPrimAtPath(current) is None:
                self._created_scope_paths.add(str(current))
            current = current.GetParentPath()

    def _remove_empty_created_scopes(self, stage, Sdf) -> None:
        session = stage.GetSessionLayer()
        for path in sorted(
            self._created_scope_paths,
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


def _visibility_plan(
    stage,
    UsdGeom,
    *,
    root_path: str,
    target_paths: tuple[str, ...],
) -> dict[str, str]:
    """Return minimal parent/sibling opinions for the requested target union."""

    root = stage.GetPrimAtPath(root_path)
    if not root or not root.IsValid():
        raise RuntimeError(f"Heatmap isolation root is unavailable: {root_path}.")
    chains: list[tuple[object, ...]] = []
    for target_path in target_paths:
        target = stage.GetPrimAtPath(target_path)
        if not target or not target.IsValid():
            raise RuntimeError(
                f"Heatmap isolation target is unavailable: {target_path}."
            )
        chain = [target]
        current = target
        while str(current.GetPath()) != root_path:
            current = current.GetParent()
            if not current or not current.IsValid():
                raise RuntimeError(
                    "Heatmap isolation target is not beneath server root: "
                    f"{target_path}."
                )
            chain.append(current)
        chains.append(tuple(reversed(chain)))
    preserved = {str(prim.GetPath()) for chain in chains for prim in chain}
    plan: dict[str, str] = {}
    for chain in chains:
        for prim in chain[1:]:
            plan[str(prim.GetPath())] = UsdGeom.Tokens.inherited
        for parent in chain[:-1]:
            for sibling in parent.GetChildren():
                if str(sibling.GetPath()) in preserved:
                    continue
                for path in _visibility_override_paths(sibling, UsdGeom):
                    plan[path] = UsdGeom.Tokens.invisible
    return plan


def _visibility_override_paths(prim, UsdGeom) -> tuple[str, ...]:
    paths = _first_imageable_visibility_paths(prim, UsdGeom)
    return paths or (str(prim.GetPath()),)


def _first_imageable_visibility_paths(prim, UsdGeom) -> tuple[str, ...]:
    if not prim or not prim.IsValid():
        return ()
    if prim.IsA(UsdGeom.Gprim):
        return (str(prim.GetPath()),)
    paths: list[str] = []
    for child in prim.GetChildren():
        paths.extend(_first_imageable_visibility_paths(child, UsdGeom))
    return tuple(paths)


def _remove_visibility_spec(stage, property_path) -> None:
    session = stage.GetSessionLayer()
    property_spec = session.GetPropertyAtPath(property_path)
    if property_spec is None:
        return
    prim_spec = session.GetPrimAtPath(property_path.GetPrimPath())
    if prim_spec is None:
        raise RuntimeError(f"Session visibility owner is missing for {property_path}.")
    prim_spec.RemoveProperty(property_spec)
