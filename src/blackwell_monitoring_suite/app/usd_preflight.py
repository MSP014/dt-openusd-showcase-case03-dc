"""Static USD preflight checks for runtime asset review."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from blackwell_monitoring_suite.app.config import RuntimeConfig

EXPECTED_ROOT_PATH = "/blackwell_rig"
EXPECTED_METERS_PER_UNIT = 1.0
EXPECTED_UP_AXIS = "Y"
MAX_TIME_SAMPLED_ATTRIBUTES = 8
USD_LAYER_SUFFIXES = {".usd", ".usda", ".usdc", ".usdz"}
VDB_SUFFIX = ".vdb"


@dataclass(frozen=True)
class UsdPreflightFinding:
    """One static preflight finding."""

    severity: str
    code: str
    message: str
    path: str = ""


@dataclass(frozen=True)
class UsdPreflightResult:
    """Collected preflight findings for a loaded USD stage."""

    findings: tuple[UsdPreflightFinding, ...]

    @property
    def error_count(self) -> int:
        """Return the number of blocking findings."""

        return sum(1 for finding in self.findings if finding.severity == "error")

    @property
    def warning_count(self) -> int:
        """Return the number of non-blocking findings."""

        return sum(1 for finding in self.findings if finding.severity == "warning")

    @property
    def has_errors(self) -> bool:
        """Return whether the preflight found blocking issues."""

        return self.error_count > 0

    @property
    def success(self) -> bool:
        """Return whether the stage is ready for runtime review."""

        return not self.has_errors

    def format_summary(self) -> str:
        """Return a compact operator-facing summary."""

        if self.error_count:
            return (
                f"preflight failed: {self.error_count} error(s), "
                f"{self.warning_count} warning(s)"
            )
        if self.warning_count:
            return f"preflight passed with {self.warning_count} warning(s)"
        return "preflight passed"


def run_usd_preflight(stage, config: RuntimeConfig) -> UsdPreflightResult:
    """Validate the loaded runtime USD stage before visual review."""

    from pxr import Sdf, UsdGeom

    findings: list[UsdPreflightFinding] = []
    expected_root_path = _infer_expected_root_path(config) or EXPECTED_ROOT_PATH

    _check_stage_metadata(stage, UsdGeom, expected_root_path, findings)
    _check_configured_prims(stage, config, findings)
    _check_layer_dependencies(stage, Sdf, findings)
    _check_time_sampled_content(stage, findings)

    return UsdPreflightResult(tuple(findings))


def _check_stage_metadata(stage, UsdGeom, root_path: str, findings) -> None:
    root_prim = stage.GetPrimAtPath(root_path)
    if not root_prim or not root_prim.IsValid():
        findings.append(
            UsdPreflightFinding(
                severity="error",
                code="missing_root_prim",
                message=f"Expected root prim is missing: {root_path}",
                path=root_path,
            )
        )

    default_prim = stage.GetDefaultPrim()
    if not default_prim or not default_prim.IsValid():
        findings.append(
            UsdPreflightFinding(
                severity="error",
                code="missing_default_prim",
                message="Stage has no valid defaultPrim.",
            )
        )
    elif str(default_prim.GetPath()) != root_path:
        findings.append(
            UsdPreflightFinding(
                severity="error",
                code="default_prim_mismatch",
                message=(
                    f"defaultPrim points at {default_prim.GetPath()}, "
                    f"expected {root_path}."
                ),
                path=str(default_prim.GetPath()),
            )
        )

    meters_per_unit = float(UsdGeom.GetStageMetersPerUnit(stage))
    if abs(meters_per_unit - EXPECTED_METERS_PER_UNIT) > 1e-6:
        findings.append(
            UsdPreflightFinding(
                severity="error",
                code="meters_per_unit_mismatch",
                message=(
                    f"Stage metersPerUnit is {meters_per_unit:g}, "
                    f"expected {EXPECTED_METERS_PER_UNIT:g}."
                ),
            )
        )

    up_axis = str(UsdGeom.GetStageUpAxis(stage)).upper()
    if up_axis != EXPECTED_UP_AXIS:
        findings.append(
            UsdPreflightFinding(
                severity="error",
                code="up_axis_mismatch",
                message=f"Stage upAxis is {up_axis}, expected {EXPECTED_UP_AXIS}.",
            )
        )


def _check_configured_prims(stage, config: RuntimeConfig, findings) -> None:
    for path in config.chassis_presentation.cover_paths:
        _append_missing_prim_finding(
            stage,
            findings,
            code="missing_chassis_cover",
            message=f"Configured chassis cover prim is missing: {path}",
            path=path,
        )

    for group in getattr(config.chassis_presentation, "visibility_groups", ()):
        for path in group.paths:
            _append_missing_prim_finding(
                stage,
                findings,
                code="missing_chassis_visibility_group",
                message=f"Configured chassis visibility prim is missing: {path}",
                path=path,
            )

    face_panel = getattr(config.chassis_presentation, "face_panel", None)
    if getattr(face_panel, "enabled", False):
        _append_missing_prim_finding(
            stage,
            findings,
            code="missing_chassis_face_panel",
            message=(
                "Configured chassis face panel prim is missing: "
                f"{face_panel.target_path}"
            ),
            path=face_panel.target_path,
        )

    qled = getattr(config.chassis_presentation, "qled_display", None)
    if getattr(qled, "enabled", False):
        for digit_name, segment_paths in (qled.digits or {}).items():
            for segment, path in segment_paths.items():
                _append_missing_prim_finding(
                    stage,
                    findings,
                    code="missing_chassis_qled_segment",
                    message=(
                        "Configured chassis QLED segment is missing: "
                        f"{digit_name}.{segment}: {path}"
                    ),
                    path=path,
                )

    indicators = getattr(config.chassis_presentation, "front_panel_indicators", None)
    if getattr(indicators, "enabled", False):
        for name, path in (
            ("power", indicators.power_path),
            ("hdd", indicators.hdd_path),
            ("lan_01", indicators.lan_01_path),
            ("lan_02", indicators.lan_02_path),
        ):
            _append_missing_prim_finding(
                stage,
                findings,
                code="missing_chassis_front_panel_indicator",
                message=f"Configured front-panel indicator is missing: {name}: {path}",
                path=path,
            )

    for binding in config.fan_motion_bindings:
        _append_missing_prim_finding(
            stage,
            findings,
            code="missing_fan_mesh",
            message=(
                f"Configured fan mesh is missing for {binding.binding_id}: "
                f"{binding.mesh_path}"
            ),
            path=binding.mesh_path,
        )
        _append_missing_prim_finding(
            stage,
            findings,
            code="missing_fan_rotation_target",
            message=(
                f"Configured fan rotation target is missing for {binding.binding_id}: "
                f"{binding.rotation_target_path}"
            ),
            path=binding.rotation_target_path,
        )


def _append_missing_prim_finding(stage, findings, code: str, message: str, path: str):
    prim = stage.GetPrimAtPath(path)
    if prim and prim.IsValid():
        return
    findings.append(
        UsdPreflightFinding(
            severity="error",
            code=code,
            message=message,
            path=path,
        )
    )


def _check_layer_dependencies(stage, Sdf, findings) -> None:
    seen: set[tuple[str, str]] = set()
    for layer in _used_layers(stage):
        layer_id = str(getattr(layer, "identifier", ""))
        for asset_path in _layer_asset_dependencies(layer):
            clean_path = _clean_asset_path(asset_path)
            if not clean_path:
                continue
            key = (layer_id, clean_path)
            if key in seen:
                continue
            seen.add(key)

            if _is_absolute_asset_path(clean_path):
                findings.append(
                    UsdPreflightFinding(
                        severity="error",
                        code="absolute_asset_dependency",
                        message=f"Composition dependency is absolute: {clean_path}",
                        path=layer_id,
                    )
                )

            if _asset_suffix(clean_path) == VDB_SUFFIX:
                findings.append(
                    UsdPreflightFinding(
                        severity="error",
                        code="vdb_asset_dependency",
                        message=(
                            "VDB dependency is outside the static asset contract: "
                            f"{clean_path}"
                        ),
                        path=layer_id,
                    )
                )

            resolved_path = _resolve_asset_path(Sdf, layer, clean_path)
            if (
                _is_filesystem_dependency(resolved_path)
                and not Path(resolved_path).exists()
            ):
                findings.append(
                    UsdPreflightFinding(
                        severity="error",
                        code="missing_asset_dependency",
                        message=f"Composition dependency is unresolved: {clean_path}",
                        path=layer_id,
                    )
                )


def _check_time_sampled_content(stage, findings) -> None:
    sampled_attrs: list[str] = []
    for prim in stage.Traverse():
        for attr in prim.GetAttributes():
            if attr.ValueMightBeTimeVarying():
                sampled_attrs.append(f"{prim.GetPath()}.{attr.GetName()}")
                if len(sampled_attrs) >= MAX_TIME_SAMPLED_ATTRIBUTES:
                    break
        if len(sampled_attrs) >= MAX_TIME_SAMPLED_ATTRIBUTES:
            break

    if sampled_attrs:
        suffix = ""
        if len(sampled_attrs) >= MAX_TIME_SAMPLED_ATTRIBUTES:
            suffix = "; additional attributes may exist"
        findings.append(
            UsdPreflightFinding(
                severity="error",
                code="time_sampled_content",
                message=(
                    "Time-sampled attributes are outside the static review contract: "
                    f"{', '.join(sampled_attrs)}{suffix}"
                ),
            )
        )


def _used_layers(stage):
    try:
        return tuple(stage.GetUsedLayers(True))
    except TypeError:
        return tuple(stage.GetUsedLayers())


def _layer_asset_dependencies(layer) -> tuple[str, ...]:
    dependencies: list[str] = []
    if hasattr(layer, "GetCompositionAssetDependencies"):
        dependencies.extend(
            str(path) for path in layer.GetCompositionAssetDependencies()
        )
    if hasattr(layer, "GetExternalAssetDependencies"):
        dependencies.extend(str(path) for path in layer.GetExternalAssetDependencies())
    return tuple(dependencies)


def _resolve_asset_path(Sdf, layer, asset_path: str) -> str:
    try:
        return str(Sdf.ComputeAssetPathRelativeToLayer(layer, asset_path))
    except Exception:  # noqa: BLE001
        return asset_path


def _infer_expected_root_path(config: RuntimeConfig) -> str | None:
    paths: list[str] = []
    paths.extend(config.chassis_presentation.cover_paths)
    for group in getattr(config.chassis_presentation, "visibility_groups", ()):
        paths.extend(group.paths)
    for binding in config.fan_motion_bindings:
        paths.append(binding.mesh_path)
        paths.append(binding.rotation_target_path)

    roots = {_root_prefix(path) for path in paths}
    roots.discard(None)
    if len(roots) == 1:
        return next(iter(roots))
    return None


def _root_prefix(path: str) -> str | None:
    parts = path.split("/")
    if len(parts) > 1 and parts[1]:
        return f"/{parts[1]}"
    return None


def _clean_asset_path(asset_path: str) -> str:
    return asset_path.strip().strip("@")


def _asset_suffix(asset_path: str) -> str:
    return Path(asset_path.replace("\\", "/")).suffix.lower()


def _is_absolute_asset_path(asset_path: str) -> bool:
    return bool(re.match(r"^[A-Za-z]:[\\/]", asset_path)) or asset_path.startswith(
        ("/", "\\\\")
    )


def _is_filesystem_dependency(asset_path: str) -> bool:
    if not asset_path or "://" in asset_path:
        return False
    return _asset_suffix(asset_path) in USD_LAYER_SUFFIXES | {VDB_SUFFIX}
