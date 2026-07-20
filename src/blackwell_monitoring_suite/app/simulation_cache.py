"""Preflight checks for the Stage 6 OpenVDB airflow cache."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from blackwell_monitoring_suite.app.config import SimulationCacheConfig


@dataclass(frozen=True)
class SimulationCacheFinding:
    """One cache contract finding."""

    severity: str
    code: str
    message: str
    path: str = ""


@dataclass(frozen=True)
class SimulationCacheContract:
    """Verified cache details used for runtime playback."""

    wrapper_path: Path
    start_time_code: float
    end_time_code: float
    time_codes_per_second: float
    frames_per_second: float
    extent_min: tuple[float, float, float]
    extent_max: tuple[float, float, float]
    field_data_type: str
    file_samples: tuple[tuple[float, str], ...]


@dataclass(frozen=True)
class SimulationCachePreflightResult:
    """Collected cache preflight findings and the verified contract."""

    findings: tuple[SimulationCacheFinding, ...]
    contract: SimulationCacheContract | None = None

    @property
    def error_count(self) -> int:
        return sum(1 for finding in self.findings if finding.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for finding in self.findings if finding.severity == "warning")

    @property
    def success(self) -> bool:
        return self.error_count == 0 and self.contract is not None

    def format_summary(self) -> str:
        if self.error_count:
            return (
                f"airflow cache failed: {self.error_count} error(s), "
                f"{self.warning_count} warning(s)"
            )
        if self.contract:
            frame_count = len(self.contract.file_samples)
            return f"airflow cache ready: {frame_count} VDB frame(s)"
        return "airflow cache is unavailable"


def run_simulation_cache_preflight(
    wrapper_path: Path | str,
    config: SimulationCacheConfig,
) -> SimulationCachePreflightResult:
    """Validate a time-sampled OpenVDB wrapper without opening Kit."""

    from pxr import Sdf, Usd, UsdGeom

    findings: list[SimulationCacheFinding] = []
    resolved_wrapper = Path(wrapper_path).resolve()
    if not resolved_wrapper.exists():
        findings.append(
            SimulationCacheFinding(
                severity="error",
                code="missing_wrapper",
                message=f"Configured cache wrapper is missing: {resolved_wrapper}",
                path=str(resolved_wrapper),
            )
        )
        return SimulationCachePreflightResult(tuple(findings))

    stage = Usd.Stage.Open(resolved_wrapper.as_posix())
    if not stage:
        findings.append(
            SimulationCacheFinding(
                severity="error",
                code="unreadable_wrapper",
                message=f"Could not open cache wrapper: {resolved_wrapper.name}",
                path=str(resolved_wrapper),
            )
        )
        return SimulationCachePreflightResult(tuple(findings))

    root_prim = stage.GetPrimAtPath(config.root_prim_path)
    default_prim = stage.GetDefaultPrim()
    if not root_prim or not root_prim.IsValid():
        findings.append(
            SimulationCacheFinding(
                severity="error",
                code="missing_cache_root",
                message=f"Configured cache root is missing: {config.root_prim_path}",
                path=config.root_prim_path,
            )
        )
    if not default_prim or not default_prim.IsValid():
        findings.append(
            SimulationCacheFinding(
                severity="error",
                code="missing_cache_default_prim",
                message="Cache wrapper has no valid defaultPrim.",
            )
        )
    elif str(default_prim.GetPath()) != config.root_prim_path:
        findings.append(
            SimulationCacheFinding(
                severity="error",
                code="cache_default_prim_mismatch",
                message=(
                    f"Cache defaultPrim is {default_prim.GetPath()}, expected "
                    f"{config.root_prim_path}."
                ),
                path=str(default_prim.GetPath()),
            )
        )

    up_axis = str(UsdGeom.GetStageUpAxis(stage)).upper()
    if up_axis != "Y":
        findings.append(
            SimulationCacheFinding(
                severity="error",
                code="cache_up_axis_mismatch",
                message=f"Cache upAxis is {up_axis}, expected Y.",
            )
        )
    meters_per_unit = float(UsdGeom.GetStageMetersPerUnit(stage))
    if abs(meters_per_unit - 1.0) > 1e-6:
        findings.append(
            SimulationCacheFinding(
                severity="error",
                code="cache_meters_per_unit_mismatch",
                message=f"Cache metersPerUnit is {meters_per_unit:g}, expected 1.",
            )
        )

    volume_prim = stage.GetPrimAtPath(config.volume_prim_path)
    if not volume_prim or not volume_prim.IsValid():
        findings.append(
            SimulationCacheFinding(
                severity="error",
                code="missing_cache_volume",
                message=(
                    "Configured cache volume is missing: " f"{config.volume_prim_path}"
                ),
                path=config.volume_prim_path,
            )
        )
        return SimulationCachePreflightResult(tuple(findings))

    start_time_code = float(stage.GetStartTimeCode())
    end_time_code = float(stage.GetEndTimeCode())
    time_codes_per_second = float(stage.GetTimeCodesPerSecond())
    frames_per_second = float(stage.GetFramesPerSecond())
    extent = _read_extent(volume_prim, start_time_code, findings)
    field_target = volume_prim.GetRelationship(
        f"field:{config.field_name}"
    ).GetTargets()
    if len(field_target) != 1:
        findings.append(
            SimulationCacheFinding(
                severity="error",
                code="missing_density_field",
                message=(
                    "Cache volume must target one "
                    f"field:{config.field_name} relationship."
                ),
                path=config.volume_prim_path,
            )
        )
        return SimulationCachePreflightResult(tuple(findings))

    field_prim = stage.GetPrimAtPath(field_target[0])
    if not field_prim or field_prim.GetTypeName() != "OpenVDBAsset":
        findings.append(
            SimulationCacheFinding(
                severity="error",
                code="invalid_density_field",
                message="Configured cache field is not an OpenVDBAsset prim.",
                path=str(field_target[0]),
            )
        )
        return SimulationCachePreflightResult(tuple(findings))

    field_name = field_prim.GetAttribute("fieldName").Get(start_time_code)
    if str(field_name) != config.field_name:
        findings.append(
            SimulationCacheFinding(
                severity="error",
                code="density_field_name_mismatch",
                message=(
                    f"OpenVDB fieldName is {field_name!r}, expected "
                    f"{config.field_name!r}."
                ),
                path=str(field_prim.GetPath()),
            )
        )

    field_data_type = field_prim.GetAttribute("fieldDataType").Get()
    if str(field_data_type) != "float":
        findings.append(
            SimulationCacheFinding(
                severity="error",
                code="invalid_density_field_data_type",
                message=(
                    "OpenVDB fieldDataType is missing or invalid; expected "
                    "the scalar token 'float'."
                ),
                path=str(field_prim.GetPath()),
            )
        )

    file_path_attr = field_prim.GetAttribute("filePath")
    file_samples = _read_file_samples(Sdf, field_prim, file_path_attr, findings)
    _check_time_metadata(
        start_time_code,
        end_time_code,
        time_codes_per_second,
        frames_per_second,
        file_samples,
        findings,
    )

    if findings or extent is None or not file_samples:
        return SimulationCachePreflightResult(tuple(findings))

    return SimulationCachePreflightResult(
        tuple(findings),
        SimulationCacheContract(
            wrapper_path=resolved_wrapper,
            start_time_code=start_time_code,
            end_time_code=end_time_code,
            time_codes_per_second=time_codes_per_second,
            frames_per_second=frames_per_second,
            extent_min=extent[0],
            extent_max=extent[1],
            field_data_type=str(field_data_type),
            file_samples=tuple(file_samples),
        ),
    )


def _read_extent(
    volume_prim,
    time_code: float,
    findings,
) -> tuple[tuple[float, ...], tuple[float, ...]] | None:
    extent_attr = volume_prim.GetAttribute("extent")
    extent = extent_attr.Get(time_code)
    if not extent or len(extent) != 2:
        findings.append(
            SimulationCacheFinding(
                severity="error",
                code="missing_cache_extent",
                message="Cache volume has no usable extent.",
                path=str(volume_prim.GetPath()),
            )
        )
        return None

    values = tuple(tuple(float(component) for component in point) for point in extent)
    if any(not math.isfinite(component) for point in values for component in point):
        findings.append(
            SimulationCacheFinding(
                severity="error",
                code="invalid_cache_extent",
                message="Cache volume extent contains non-finite values.",
                path=str(volume_prim.GetPath()),
            )
        )
        return None
    return values


def _read_file_samples(
    Sdf, field_prim, file_path_attr, findings
) -> list[tuple[float, str]]:
    time_samples = list(file_path_attr.GetTimeSamples())
    if not time_samples:
        findings.append(
            SimulationCacheFinding(
                severity="error",
                code="missing_vdb_time_samples",
                message="Cache OpenVDBAsset filePath has no time samples.",
                path=str(field_prim.GetPath()),
            )
        )
        return []

    field_layer = field_prim.GetStage().GetRootLayer()
    samples: list[tuple[float, str]] = []
    for time_code in time_samples:
        asset_path = file_path_attr.Get(time_code)
        authored_path = str(getattr(asset_path, "path", asset_path))
        resolved_path = Sdf.ComputeAssetPathRelativeToLayer(field_layer, authored_path)
        if not resolved_path or not Path(resolved_path).exists():
            findings.append(
                SimulationCacheFinding(
                    severity="error",
                    code="missing_vdb_frame",
                    message=(
                        f"VDB frame is unresolved at timeCode {time_code:g}: "
                        f"{authored_path}"
                    ),
                    path=authored_path,
                )
            )
            continue
        samples.append((float(time_code), str(resolved_path)))
    return samples


def _check_time_metadata(
    start_time_code: float,
    end_time_code: float,
    time_codes_per_second: float,
    frames_per_second: float,
    file_samples: list[tuple[float, str]],
    findings,
) -> None:
    if time_codes_per_second <= 0 or frames_per_second <= 0:
        findings.append(
            SimulationCacheFinding(
                severity="error",
                code="invalid_cache_frame_rate",
                message=(
                    "Cache timeCodesPerSecond and framesPerSecond must be positive."
                ),
            )
        )
        return
    if abs(time_codes_per_second - frames_per_second) > 1e-6:
        findings.append(
            SimulationCacheFinding(
                severity="warning",
                code="cache_frame_rate_mismatch",
                message=(
                    "Cache timeCodesPerSecond and framesPerSecond differ; "
                    "playback uses timeCodesPerSecond."
                ),
            )
        )
    expected_count = int(round(end_time_code - start_time_code)) + 1
    sample_times = [time_code for time_code, _ in file_samples]
    if (
        not sample_times
        or sample_times[0] != start_time_code
        or sample_times[-1] != end_time_code
    ):
        findings.append(
            SimulationCacheFinding(
                severity="error",
                code="cache_sample_range_mismatch",
                message=(
                    "Cache VDB samples do not cover the authored stage frame range."
                ),
            )
        )
    elif len(sample_times) != expected_count:
        findings.append(
            SimulationCacheFinding(
                severity="error",
                code="cache_sample_gap",
                message=(
                    "Cache VDB samples are not contiguous across the authored "
                    "frame range."
                ),
            )
        )
