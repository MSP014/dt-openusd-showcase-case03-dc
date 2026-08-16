"""Own canonical teardown receipts for the Stage 09 static Streamlines path."""

from __future__ import annotations

from dataclasses import dataclass

STATIC_VELOCITY_SOURCE_ROOT = "/DTRS_HoudiniVelocity"
STREAMLINES_OPERATOR_ROOT = "/DTRS_KitCAE/Streamlines"
STREAMLINES_SEED_ROOT = "/DTRS_KitCAE/StreamlineSeeds"
STREAMLINES_COMPARISON_OPERATOR_ROOT = "/DTRS_KitCAE/StreamlinesComparison"
STREAMLINES_COMPARISON_SEED_ROOT = "/DTRS_KitCAE/StreamlinesComparisonSeeds"

# These are intentionally exact DTRS-owned roots.  Package D must never sweep
# arbitrary scene content merely to make a lifecycle receipt look clean.
STATIC_STREAMLINES_RUNTIME_ROOTS = (
    STATIC_VELOCITY_SOURCE_ROOT,
    STREAMLINES_OPERATOR_ROOT,
    STREAMLINES_SEED_ROOT,
    STREAMLINES_COMPARISON_OPERATOR_ROOT,
    STREAMLINES_COMPARISON_SEED_ROOT,
)


@dataclass(frozen=True)
class StaticStreamlinesCleanupReceipt:
    """Programmatic proof that no static Streamlines runtime state remains."""

    source_present: bool
    operator_present: bool
    seed_present: bool
    runtime_preview_present: bool
    comparison_present: bool
    stale_relationships: int
    remaining_layer_specs: int
    duplicate_prims: int
    pending_tasks: int

    @property
    def clean(self) -> bool:
        """Return whether every owned static-runtime residue is absent."""

        return not any(
            (
                self.source_present,
                self.operator_present,
                self.seed_present,
                self.runtime_preview_present,
                self.comparison_present,
                self.stale_relationships,
                self.remaining_layer_specs,
                self.duplicate_prims,
                self.pending_tasks,
            )
        )


def static_runtime_root_paths(stage) -> tuple[str, ...]:
    """Return owned canonical or suffixed roots currently composed on ``stage``.

    Canonical paths are always included so layer-spec inspection remains useful
    after successful composition cleanup.  A ``_001`` style sibling is evidence
    of a lifecycle violation, never a supported fallback path.
    """

    paths = set(STATIC_STREAMLINES_RUNTIME_ROOTS)
    for prim in _walk_prims(stage.GetPseudoRoot()):
        path = str(prim.GetPath())
        if any(
            path == root or path.startswith(f"{root}_")
            for root in STATIC_STREAMLINES_RUNTIME_ROOTS
        ):
            paths.add(path)
    return tuple(sorted(paths, key=lambda value: (value.count("/"), value)))


def remove_static_runtime_roots_from_layers(stage) -> tuple[str, ...]:
    """Remove only DTRS static roots from session and root layers.

    The VTI importer and the origin compatibility shim author into different
    layers.  Removing both layers is therefore part of the source contract,
    rather than a best-effort viewport cleanup.
    """

    paths = static_runtime_root_paths(stage)
    previous_target = stage.GetEditTarget()
    try:
        for layer in _dtrs_authoring_layers(stage):
            stage.SetEditTarget(layer)
            for path in sorted(paths, key=len, reverse=True):
                if stage.GetPrimAtPath(path).IsValid():
                    stage.RemovePrim(path)
    finally:
        stage.SetEditTarget(previous_target)
    return paths


def inspect_static_runtime_cleanup(
    stage,
    *,
    pending_tasks: int,
) -> StaticStreamlinesCleanupReceipt:
    """Inspect visible, relationship, and layer-spec residue without UI tree use."""

    composed_paths = static_runtime_root_paths(stage)
    source_present = _any_valid(stage, (STATIC_VELOCITY_SOURCE_ROOT,))
    operator_present = _any_valid(stage, (STREAMLINES_OPERATOR_ROOT,))
    seed_present = _any_valid(stage, (STREAMLINES_SEED_ROOT,))
    runtime_preview_present = _any_valid(
        stage,
        (f"{STREAMLINES_OPERATOR_ROOT}/StaticVelocityRuntimePreview",),
    )
    comparison_present = _any_valid(
        stage,
        (
            STREAMLINES_COMPARISON_OPERATOR_ROOT,
            STREAMLINES_COMPARISON_SEED_ROOT,
        ),
    )
    suffixed_paths = tuple(
        path
        for path in composed_paths
        if any(path.startswith(f"{root}_") for root in STATIC_STREAMLINES_RUNTIME_ROOTS)
    )
    return StaticStreamlinesCleanupReceipt(
        source_present=source_present,
        operator_present=operator_present,
        seed_present=seed_present,
        runtime_preview_present=runtime_preview_present,
        comparison_present=comparison_present,
        stale_relationships=_count_stale_relationships(stage),
        remaining_layer_specs=_count_remaining_layer_specs(stage, composed_paths),
        duplicate_prims=len(suffixed_paths),
        pending_tasks=pending_tasks,
    )


def format_static_lifecycle_cleanup_receipt(
    receipt: StaticStreamlinesCleanupReceipt,
) -> str:
    """Format the compact, stable acceptance receipt requested for Package D."""

    result = "CLEAN" if receipt.clean else "DIRTY"
    return "\n".join(
        (
            f"source_present={receipt.source_present}",
            f"operator_present={receipt.operator_present}",
            f"seed_present={receipt.seed_present}",
            f"runtime_preview_present={receipt.runtime_preview_present}",
            f"comparison_present={receipt.comparison_present}",
            f"stale_relationships={receipt.stale_relationships}",
            f"remaining_layer_specs={receipt.remaining_layer_specs}",
            f"duplicate_prims={receipt.duplicate_prims}",
            f"pending_tasks={receipt.pending_tasks}",
            f"result={result}",
        )
    )


def _dtrs_authoring_layers(stage) -> tuple[object, ...]:
    """Return unique layers where DTRS is allowed to remove its own specs."""

    layers = (stage.GetSessionLayer(), stage.GetRootLayer())
    unique_layers = []
    seen_identifiers = set()
    for layer in layers:
        identifier = getattr(layer, "identifier", None) or id(layer)
        if identifier not in seen_identifiers:
            seen_identifiers.add(identifier)
            unique_layers.append(layer)
    return tuple(unique_layers)


def _walk_prims(root_prim):
    """Traverse with ``GetChildren`` for compatibility with installed USD Python."""

    for child in root_prim.GetChildren():
        yield child
        yield from _walk_prims(child)


def _any_valid(stage, paths: tuple[str, ...]) -> bool:
    return any(stage.GetPrimAtPath(path).IsValid() for path in paths)


def _is_static_runtime_target(path: str) -> bool:
    return any(
        path == root or path.startswith(f"{root}/") or path.startswith(f"{root}_")
        for root in STATIC_STREAMLINES_RUNTIME_ROOTS
    )


def _count_stale_relationships(stage) -> int:
    count = 0
    for prim in _walk_prims(stage.GetPseudoRoot()):
        for relationship in prim.GetRelationships():
            if any(
                _is_static_runtime_target(str(target))
                for target in relationship.GetTargets()
            ):
                count += 1
    return count


def _count_remaining_layer_specs(stage, paths: tuple[str, ...]) -> int:
    count = 0
    for layer in _dtrs_authoring_layers(stage):
        for path in paths:
            if _layer_prim_spec(layer, path) is not None:
                count += 1
    return count


def _layer_prim_spec(layer, path: str):
    """Read a layer spec with Kit USD or a dependency-free fake-stage fallback."""

    try:
        from pxr import Sdf
    except ImportError:
        return layer.GetPrimAtPath(path)
    return layer.GetPrimAtPath(Sdf.Path(path))
