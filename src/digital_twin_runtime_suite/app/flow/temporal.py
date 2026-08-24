# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""Temporal VTI sample mapping and loop-proof helpers for DTRS Flow."""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from pathlib import Path

from digital_twin_runtime_suite.app.airflow_dataset import AirflowDataset
from digital_twin_runtime_suite.app.airflow_validation import (
    preflight as airflow_preflight,
)
from digital_twin_runtime_suite.app.flow import smoke as flow_smoke
from digital_twin_runtime_suite.app.flow import validation as flow_validation


def kit_cae_vectors_match(expected, actual, tolerance: float = 1e-6) -> bool:
    """Compare three-component grid values without exposing diagnostic internals."""

    if expected is None or actual is None:
        return False
    try:
        return len(expected) == len(actual) == 3 and all(
            abs(float(expected[index]) - float(actual[index])) <= tolerance
            for index in range(3)
        )
    except (TypeError, ValueError):
        return False


def kit_cae_vti_source_frame(asset: Path) -> str:
    """Extract the Houdini frame suffix for compact temporal evidence."""

    match = re.search(r"(\d+)$", asset.stem)
    return match.group(1) if match else asset.stem


def flow_log_value(value) -> object:
    """Keep compact Flow evidence stable for scalar Kit attribute values."""

    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return value


def kit_cae_temporal_loop_proof_summary(
    records: list[dict[str, object]],
    velocity_paths: tuple[Path, ...],
) -> dict[str, object]:
    """Reduce the fixed Stage 6 loop contract into explicit proof evidence."""

    expected_assets = (*velocity_paths, velocity_paths[0]) if velocity_paths else ()
    expected_names = [asset.name for asset in expected_assets]
    observed_names = [str(record.get("asset", "unavailable")) for record in records]
    frames = [str(record.get("source_frame", "unavailable")) for record in records]
    hashes = {
        str(record["asset_hash"])
        for record in records
        if record.get("asset_hash") is not None
    }
    transitions = [str(record.get("transition", "")) for record in records[1:]]
    forward_transitions = sum(transition == "SWAP" for transition in transitions)
    loop_transitions = sum(transition == "LOOP" for transition in transitions)
    operator_ready_all = all(bool(record.get("operator_ready")) for record in records)
    origin_match_all = all(bool(record.get("origin_match")) for record in records)
    grid_match_all = all(bool(record.get("grid_match")) for record in records)
    timeline_continuous = all(
        bool(record.get("timeline_advancing")) for record in records
    )
    flow_resets = sum(bool(record.get("flow_reset")) for record in records)
    loop_closure = (
        len(records) == len(expected_assets)
        and bool(records)
        and observed_names[-1] == expected_names[0]
        and transitions[-1:] == ["LOOP"]
    )
    mismatch = next(
        (
            (expected_name, observed_name)
            for expected_name, observed_name in zip(expected_names, observed_names)
            if expected_name != observed_name
        ),
        None,
    )
    if mismatch is None and len(observed_names) < len(expected_names):
        mismatch = (expected_names[len(observed_names)], "unavailable")
    passed = (
        len(records) == len(velocity_paths) + 1
        and observed_names == expected_names
        and len(set(observed_names)) == len(velocity_paths)
        and len(hashes) == len(velocity_paths)
        and transitions == ["SWAP"] * (len(velocity_paths) - 1) + ["LOOP"]
        and forward_transitions == len(velocity_paths) - 1
        and loop_transitions == 1
        and loop_closure
        and operator_ready_all
        and origin_match_all
        and grid_match_all
        and timeline_continuous
        and flow_resets == 0
    )
    return {
        "frames": frames,
        "unique_assets": len(set(observed_names)),
        "unique_hashes": len(hashes),
        "forward_transitions": forward_transitions,
        "loop_transitions": loop_transitions,
        "operator_ready_all": operator_ready_all,
        "origin_match_all": origin_match_all,
        "grid_match_all": grid_match_all,
        "timeline_continuous": timeline_continuous,
        "flow_resets": flow_resets,
        "loop_closure": loop_closure,
        "mismatch": mismatch,
        "passed": passed,
    }


def author_kit_cae_temporal_velocity_samples(
    field_prim,
    velocity_paths: tuple[Path, ...],
    time_codes_per_second: float,
    sample_interval_seconds: float,
    cae_vtk,
    Sdf,
    Usd,
) -> tuple[float, ...]:
    """Map discovered VTI samples to USD time codes from manifest timing."""

    file_names_attr = cae_vtk.FieldArray(field_prim).GetFileNamesAttr()
    if not file_names_attr or not file_names_attr.IsValid():
        raise RuntimeError("Kit-CAE velocity field is missing fileNames.")
    if time_codes_per_second <= 0 or sample_interval_seconds <= 0:
        raise RuntimeError(
            "Temporal time-code rate and sample interval must be positive."
        )
    if not velocity_paths:
        raise RuntimeError("Temporal mapping requires at least one VTI sample.")
    time_code_step = float(time_codes_per_second) * float(sample_interval_seconds)
    time_codes = tuple(
        float(index) * time_code_step for index in range(len(velocity_paths))
    )
    for time_code, velocity_path in zip(time_codes, velocity_paths):
        author_kit_cae_temporal_velocity_sample(
            field_prim, velocity_path, time_code, cae_vtk, Sdf, Usd
        )
    return time_codes


async def author_kit_cae_temporal_velocity_samples_in_batches(
    field_prim,
    velocity_paths: tuple[Path, ...],
    time_codes_per_second: float,
    sample_interval_seconds: float,
    cae_vtk,
    Sdf,
    Usd,
    next_update,
    batch_size: int,
    progress_callback=None,
) -> tuple[float, ...]:
    """Author temporal samples in bounded Kit-update batches."""

    file_names_attr = cae_vtk.FieldArray(field_prim).GetFileNamesAttr()
    if not file_names_attr or not file_names_attr.IsValid():
        raise RuntimeError("Kit-CAE velocity field is missing fileNames.")
    if time_codes_per_second <= 0 or sample_interval_seconds <= 0:
        raise RuntimeError(
            "Temporal time-code rate and sample interval must be positive."
        )
    if not velocity_paths:
        raise RuntimeError("Temporal mapping requires at least one VTI sample.")
    if batch_size <= 0:
        raise RuntimeError("Temporal authoring batch size must be positive.")

    time_code_step = float(time_codes_per_second) * float(sample_interval_seconds)
    time_codes = tuple(
        float(index) * time_code_step for index in range(len(velocity_paths))
    )
    for index, (time_code, velocity_path) in enumerate(
        zip(time_codes, velocity_paths),
        start=1,
    ):
        author_kit_cae_temporal_velocity_sample(
            field_prim, velocity_path, time_code, cae_vtk, Sdf, Usd
        )
        if index < len(time_codes) and index % batch_size == 0:
            if progress_callback:
                progress_callback(index, len(time_codes))
            await next_update()
    return time_codes


def author_kit_cae_temporal_velocity_sample(
    field_prim,
    velocity_path: Path,
    time_code: float,
    cae_vtk,
    Sdf,
    Usd,
) -> bool:
    """Author one ``fileNames`` time sample through the Stage 6 mechanism."""

    file_names_attr = cae_vtk.FieldArray(field_prim).GetFileNamesAttr()
    if not file_names_attr or not file_names_attr.IsValid():
        raise RuntimeError("Kit-CAE velocity field is missing fileNames.")
    return bool(
        file_names_attr.Set(
            [Sdf.AssetPath(velocity_path.as_posix())],
            Usd.TimeCode(time_code),
        )
    )


def author_kit_cae_temporal_velocity_samples_except_index(
    field_prim,
    velocity_paths: tuple[Path, ...],
    time_codes: tuple[float, ...],
    preserved_index: int,
    cae_vtk,
    Sdf,
    Usd,
) -> None:
    """Retarget a sequence without changing the source currently being consumed."""

    if len(velocity_paths) != len(time_codes):
        raise RuntimeError(
            "Temporal source paths and time codes must have equal length."
        )
    if not 0 <= preserved_index < len(velocity_paths):
        raise RuntimeError("Temporal preserved sample index is outside the sequence.")
    for index, (velocity_path, time_code) in enumerate(zip(velocity_paths, time_codes)):
        if index != preserved_index:
            author_kit_cae_temporal_velocity_sample(
                field_prim, velocity_path, time_code, cae_vtk, Sdf, Usd
            )


def next_temporal_sample_index(current_index: int, sample_count: int) -> int:
    """Return the next cyclic sample index for a phase-preserving retarget."""

    if not 0 <= current_index < sample_count:
        raise ValueError("Current temporal sample index is outside the sequence.")
    return (current_index + 1) % sample_count


def kit_cae_payload_digest(payload, payload_count: int) -> str:
    """Return bounded, full-payload evidence for one live CAE output."""

    if payload is None:
        return "unavailable"
    try:
        raw = memoryview(payload).tobytes()
    except (TypeError, ValueError):
        raw = b"".join(
            int(value).to_bytes(4, "little", signed=False) for value in payload
        )
    return f"len={payload_count}; sha256={hashlib.sha256(raw).hexdigest()[:16]}"


@dataclass(frozen=True)
class InPlaceTemporalRetargetResult:
    """Evidence returned by one in-place temporal source retarget."""

    target_time_code: float
    requested_source: Path
    resolved_source: Path | None
    authoring_succeeded: bool
    refresh_requested: bool


async def retarget_kit_cae_temporal_source_in_place(
    stage,
    field_prim,
    velocity_path: Path,
    time_code: float,
    cae_vtk,
    Sdf,
    Usd,
    sync_active_controller=None,
    *,
    refresh: bool = True,
) -> InPlaceTemporalRetargetResult:
    """Retarget one FieldArray time sample and optionally refresh CAE.

    The session layer is used because the authored source sequence is an
    immutable asset contract; this adds the smallest runtime override rather
    than changing the Houdini-authored layer.  This helper intentionally
    changes only the existing temporal source opinion. It neither receives nor
    touches Flow, emitter, Attach, Detach, or Reset state.  ``refresh=False``
    is the production transition path: Kit-CAE then consumes the authored
    source through its natural temporal update, avoiding VTK re-entrancy.
    """

    previous_edit_target = stage.GetEditTarget()
    stage.SetEditTarget(stage.GetSessionLayer())
    try:
        authoring_succeeded = author_kit_cae_temporal_velocity_sample(
            field_prim, velocity_path, time_code, cae_vtk, Sdf, Usd
        )
    finally:
        stage.SetEditTarget(previous_edit_target)

    resolved_source = kit_cae_selected_velocity_asset(
        field_prim, time_code, cae_vtk, Usd
    )
    if not authoring_succeeded or resolved_source != velocity_path:
        raise RuntimeError(
            "Kit-CAE temporal source retarget did not resolve to the requested VTI."
        )
    if not refresh:
        return InPlaceTemporalRetargetResult(
            target_time_code=time_code,
            requested_source=velocity_path,
            resolved_source=resolved_source,
            authoring_succeeded=authoring_succeeded,
            refresh_requested=False,
        )
    if sync_active_controller is None:
        from omni.cae.viz.controller import Controller

        sync_active_controller = Controller.sync_active_controller
    refresh_requested = bool(await sync_active_controller())
    return InPlaceTemporalRetargetResult(
        target_time_code=time_code,
        requested_source=velocity_path,
        resolved_source=resolved_source,
        authoring_succeeded=authoring_succeeded,
        refresh_requested=refresh_requested,
    )


def kit_cae_file_names_value_at_time(field_prim, time_code, cae_vtk, Usd):
    """Read the VTK source assets selected at one USD time code."""

    file_names_attr = cae_vtk.FieldArray(field_prim).GetFileNamesAttr()
    return file_names_attr.Get(Usd.TimeCode(time_code))


def kit_cae_file_names_value_repr(value) -> list[str]:
    """Serialize a composed USD asset array for temporal evidence."""

    return [asset.resolvedPath or asset.path or str(asset) for asset in (value or [])]


def kit_cae_file_names_time_samples(field_prim, cae_vtk, Usd) -> list[str]:
    """Format authored VTI source samples for compact time-domain evidence."""

    file_names_attr = cae_vtk.FieldArray(field_prim).GetFileNamesAttr()
    return [
        f"{time_code}:"
        + "|".join(
            kit_cae_file_names_value_repr(
                kit_cae_file_names_value_at_time(
                    field_prim,
                    time_code,
                    cae_vtk,
                    Usd,
                )
            )
        )
        for time_code in file_names_attr.GetTimeSamples()
    ]


def kit_cae_file_names_property_stack(field_prim, cae_vtk) -> list[dict[str, object]]:
    """Expose only composed fileNames opinions needed to debug time samples."""

    file_names_attr = cae_vtk.FieldArray(field_prim).GetFileNamesAttr()
    stack = []
    for spec in file_names_attr.GetPropertyStack():
        try:
            time_samples = spec.GetInfo("timeSamples") or {}
        except Exception:
            time_samples = {}
        stack.append(
            {
                "layer": spec.layer.identifier,
                "time_codes_per_second": spec.layer.timeCodesPerSecond,
                "default": kit_cae_file_names_value_repr(spec.default),
                "authored_time_samples": {
                    str(time_code): kit_cae_file_names_value_repr(value)
                    for time_code, value in time_samples.items()
                },
            }
        )
    return stack


def kit_cae_selected_velocity_asset(field_prim, time_code, cae_vtk, Usd) -> Path | None:
    """Resolve the source VTI selected by the current USD time code."""

    file_names = kit_cae_file_names_value_at_time(
        field_prim,
        time_code,
        cae_vtk,
        Usd,
    )
    if not file_names or len(file_names) != 1:
        return None
    asset_path = file_names[0]
    resolved = asset_path.resolvedPath or asset_path.path
    return Path(resolved).resolve() if resolved else None


class FlowTemporalMixin:
    """Own temporal VTI authoring, playback proof, and evidence logs."""

    def _kit_cae_vti_asset_hash(self, asset: Path) -> str:
        """Return a cached SHA-256 identity for temporal proof evidence."""

        cached = self._flow_temporal_asset_hashes.get(asset)
        if cached:
            return cached
        digest = hashlib.sha256()
        with asset.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        value = digest.hexdigest()
        self._flow_temporal_asset_hashes[asset] = value
        return value

    @staticmethod
    def _kit_cae_vti_source_frame(asset: Path) -> str:
        """Extract the Houdini frame suffix for compact temporal evidence."""

        match = re.search(r"(\d+)$", asset.stem)
        return match.group(1) if match else asset.stem

    @staticmethod
    def _flow_log_value(value) -> object:
        """Keep compact Flow evidence stable for scalar Kit attribute values."""

        try:
            return round(float(value), 3)
        except (TypeError, ValueError):
            return value

    def _log_kit_cae_temporal_frame(
        self,
        carb,
        *,
        sequence_index: int,
        temporal_frames: int,
        asset: Path,
        previous_frame: str | None,
        transition: str,
        operator_ready: bool,
        operator_wait_ms: float,
        nano_vdb_velocities_uint_count: int,
        velocity_scale,
        velocity_scale_matches: bool,
        couple_rate_velocity,
        timeline_time_before: float,
        timeline_time_after: float,
        timeline_advancing: bool,
        flow_reset: bool,
        origin_match: bool,
        grid_match: bool,
        verbose: bool,
    ) -> None:
        """Record one actual source activation without recreating Flow diagnostics."""

        source_frame = self._kit_cae_vti_source_frame(asset)
        asset_hash = self._kit_cae_vti_asset_hash(asset)[:12]
        record = {
            "sequence_index": sequence_index,
            "source_frame": source_frame,
            "asset": asset.name,
            "asset_hash": asset_hash,
            "previous_frame": previous_frame,
            "transition": transition,
            "operator_ready": operator_ready,
            "operator_wait_ms": round(operator_wait_ms),
            "nano_vdb_velocities_uint_count": nano_vdb_velocities_uint_count,
            "velocity_scale": self._flow_log_value(velocity_scale),
            "velocity_scale_matches": velocity_scale_matches,
            "couple_rate_velocity": self._flow_log_value(couple_rate_velocity),
            "timeline_time_before": round(timeline_time_before, 3),
            "timeline_time_after": round(timeline_time_after, 3),
            "timeline_advancing": timeline_advancing,
            "flow_reset": flow_reset,
            "origin_match": origin_match,
            "grid_match": grid_match,
        }
        self._flow_temporal_records.append(record)
        if not verbose:
            return
        carb.log_warn(
            self._format_flow_log_block(
                f"TEMPORAL FRAME {sequence_index + 1}/{temporal_frames}",
                (
                    (
                        "Source",
                        (
                            ("source_frame:", source_frame),
                            ("Asset:", asset.name),
                            ("SHA-256:", asset_hash),
                            ("previous_frame:", previous_frame),
                            ("Transition:", transition),
                        ),
                    ),
                    (
                        "CAE -> Flow",
                        (
                            ("operator_ready:", operator_ready),
                            ("Operator wait:", f"{round(operator_wait_ms)} ms"),
                            ("NanoVDB uint count:", nano_vdb_velocities_uint_count),
                            ("Velocity scale:", record["velocity_scale"]),
                            ("Velocity scale locked:", velocity_scale_matches),
                            ("Couple rate:", record["couple_rate_velocity"]),
                        ),
                    ),
                    (
                        "Timeline",
                        (
                            ("Before:", f"{timeline_time_before:.2f} s"),
                            ("After:", f"{timeline_time_after:.2f} s"),
                            ("Advancing:", timeline_advancing),
                            ("flow_reset:", flow_reset),
                        ),
                    ),
                    (
                        "Invariants",
                        (
                            ("origin_match:", origin_match),
                            ("grid_match:", grid_match),
                        ),
                    ),
                ),
                state="PROGRESS",
            )
        )

    @staticmethod
    def _kit_cae_temporal_loop_proof_summary(
        records: list[dict[str, object]],
        velocity_paths: tuple[Path, ...],
    ) -> dict[str, object]:
        """Reduce the configured temporal loop contract into proof evidence."""

        summary = kit_cae_temporal_loop_proof_summary(
            records,
            velocity_paths,
        )
        velocity_scale_match_all = all(
            bool(record.get("velocity_scale_matches", True)) for record in records
        )
        summary["velocity_scale_match_all"] = velocity_scale_match_all
        summary["passed"] = bool(summary["passed"]) and velocity_scale_match_all
        return summary

    def _log_kit_cae_temporal_proof(
        self,
        carb,
        velocity_paths: tuple[Path, ...],
    ) -> bool:
        """Emit the configured Stage 6 temporal loop proof result."""

        summary = self._kit_cae_temporal_loop_proof_summary(
            self._flow_temporal_records,
            velocity_paths,
        )
        frames = summary["frames"]
        frame_evidence = " -> ".join(frames)
        if not self.config.simulation_cache.temporal_debug_logging and len(frames) > 4:
            frame_evidence = f"{frames[0]} -> ... -> {frames[-2]} -> {frames[-1]}"
        sections = (
            (
                "",
                (
                    ("Frames observed:", frame_evidence or "none"),
                    ("Unique source assets:", summary["unique_assets"]),
                    ("Unique source hashes:", summary["unique_hashes"]),
                    ("Forward transitions:", summary["forward_transitions"]),
                    ("Loop transitions:", summary["loop_transitions"]),
                ),
            ),
            (
                "Invariants",
                (
                    ("operator_ready_all:", summary["operator_ready_all"]),
                    ("origin_match_all:", summary["origin_match_all"]),
                    ("grid_match_all:", summary["grid_match_all"]),
                    (
                        "velocity_scale_match_all:",
                        summary["velocity_scale_match_all"],
                    ),
                    ("timeline_continuous:", summary["timeline_continuous"]),
                    ("Flow resets:", summary["flow_resets"]),
                    (
                        "Loop closure:",
                        "PASS" if summary["loop_closure"] else "FAIL",
                    ),
                ),
            ),
        )
        if not summary["passed"]:
            mismatch = summary["mismatch"]
            failure = self._flow_temporal_failure or {}
            expected_source = (
                mismatch[0]
                if mismatch is not None
                else failure.get("expected_asset", "unavailable")
            )
            resolved_source = (
                failure.get("resolved_asset", "unavailable")
                if mismatch is not None and mismatch[1] == "unavailable"
                else (
                    mismatch[1]
                    if mismatch is not None
                    else failure.get("resolved_asset", "unavailable")
                )
            )
            reason = (
                failure.get("reason", "temporal loop evidence invariant failed")
                if mismatch is not None and mismatch[1] == "unavailable"
                else (
                    "source_asset_match=False"
                    if mismatch is not None
                    else failure.get(
                        "reason", "temporal loop evidence invariant failed"
                    )
                )
            )
            sections += (
                (
                    "Failure",
                    (
                        ("Reason:", reason),
                        ("Expected source:", expected_source),
                        ("Resolved source:", resolved_source),
                    ),
                ),
            )
        sections += (("", (("RESULT:", "PASS" if summary["passed"] else "FAIL"),)),)
        message = self._format_flow_log_block(
            "TEMPORAL LOOP PROOF",
            sections,
            state="PASS" if summary["passed"] else "FAIL",
        )
        if summary["passed"]:
            carb.log_warn(message)
        else:
            carb.log_error(message)
        return bool(summary["passed"])

    @staticmethod
    def _author_kit_cae_temporal_velocity_samples(
        field_prim,
        velocity_paths: tuple[Path, ...],
        time_codes_per_second: float,
        sample_interval_seconds: float,
        cae_vtk,
        Sdf,
        Usd,
    ) -> tuple[float, ...]:
        """Map VTI samples to time codes from manifest-derived cadence."""

        return author_kit_cae_temporal_velocity_samples(
            field_prim,
            velocity_paths,
            time_codes_per_second,
            sample_interval_seconds,
            cae_vtk,
            Sdf,
            Usd,
        )

    def _log_kit_cae_airflow_dataset(
        self,
        carb,
        dataset: AirflowDataset,
    ) -> None:
        """Emit the compact external dataset contract used by this attach."""

        manifest = dataset.manifest
        carb.log_warn(
            self._format_flow_log_block(
                "AIRFLOW DATASET",
                (
                    (
                        "",
                        (
                            ("Scope:", manifest.scope),
                            ("State:", manifest.state),
                            ("Samples:", manifest.sample_count),
                            ("Source FPS:", f"{manifest.source_fps:g}"),
                            ("Source frame step:", manifest.sample_step_frames),
                            ("Runtime sample rate:", f"{manifest.sample_rate_hz:g} Hz"),
                            (
                                "Sample interval:",
                                f"{dataset.sample_interval_seconds:g} s",
                            ),
                            (
                                "Loop duration:",
                                f"{dataset.loop_duration_seconds:g} s",
                            ),
                            (
                                "Grid:",
                                " x ".join(str(value) for value in manifest.grid),
                            ),
                        ),
                    ),
                ),
            )
        )

    @staticmethod
    def _kit_cae_file_names_value_at_time(field_prim, time_code, cae_vtk, Usd):
        """Read the VTK source assets selected at one USD time code."""

        file_names_attr = cae_vtk.FieldArray(field_prim).GetFileNamesAttr()
        return file_names_attr.Get(Usd.TimeCode(time_code))

    @staticmethod
    def _kit_cae_file_names_value_repr(value) -> list[str]:
        """Serialize a composed USD asset array for temporal evidence."""

        return [
            asset.resolvedPath or asset.path or str(asset) for asset in (value or [])
        ]

    @classmethod
    def _kit_cae_file_names_time_samples(cls, field_prim, cae_vtk, Usd) -> list[str]:
        """Format authored VTI source samples for compact time-domain evidence."""

        file_names_attr = cae_vtk.FieldArray(field_prim).GetFileNamesAttr()
        return [
            f"{time_code}:"
            + "|".join(
                cls._kit_cae_file_names_value_repr(
                    cls._kit_cae_file_names_value_at_time(
                        field_prim,
                        time_code,
                        cae_vtk,
                        Usd,
                    )
                )
            )
            for time_code in file_names_attr.GetTimeSamples()
        ]

    @classmethod
    def _kit_cae_file_names_property_stack(
        cls, field_prim, cae_vtk
    ) -> list[dict[str, object]]:
        """Expose only the composed fileNames opinions needed to debug time samples."""

        file_names_attr = cae_vtk.FieldArray(field_prim).GetFileNamesAttr()
        stack = []
        for spec in file_names_attr.GetPropertyStack():
            try:
                time_samples = spec.GetInfo("timeSamples") or {}
            except Exception:
                time_samples = {}
            stack.append(
                {
                    "layer": spec.layer.identifier,
                    "time_codes_per_second": spec.layer.timeCodesPerSecond,
                    "default": cls._kit_cae_file_names_value_repr(spec.default),
                    "authored_time_samples": {
                        str(time_code): cls._kit_cae_file_names_value_repr(value)
                        for time_code, value in time_samples.items()
                    },
                }
            )
        return stack

    @classmethod
    def _log_kit_cae_temporal_time_mapping(
        cls,
        carb,
        *,
        field_prim,
        timeline_time_seconds: float,
        stage_time_codes_per_second: float,
        resolved_stage_time_code: float,
        cae_vtk,
        Usd,
    ) -> None:
        """Log actual composed fileNames values before source-match evaluation."""

        file_names_attr = cae_vtk.FieldArray(field_prim).GetFileNamesAttr()

        def names_at(time_code) -> str:
            values = cls._kit_cae_file_names_value_repr(
                cls._kit_cae_file_names_value_at_time(
                    field_prim,
                    time_code,
                    cae_vtk,
                    Usd,
                )
            )
            return " | ".join(Path(value).name for value in values) or "none"

        property_stack = cls._kit_cae_file_names_property_stack(
            field_prim,
            cae_vtk,
        )
        authoring_layer_tcps = (
            property_stack[0]["time_codes_per_second"]
            if property_stack
            else "unavailable"
        )
        composed_sample_fields = tuple(
            (f"TC {float(time_code):.3f}:", names_at(time_code))
            for time_code in file_names_attr.GetTimeSamples()
        )
        message = cls._format_flow_log_block(
            "TEMPORAL MAPPING",
            (
                (
                    "Field",
                    (
                        ("Prim:", field_prim.GetPath()),
                        ("Attribute:", file_names_attr.GetPath()),
                    ),
                ),
                (
                    "Time domain",
                    (
                        ("Stage TCPS:", stage_time_codes_per_second),
                        ("Authoring layer TCPS:", authoring_layer_tcps),
                        ("Timeline:", f"{timeline_time_seconds:.3f} s"),
                        ("Resolved timeCode:", f"{resolved_stage_time_code:.3f}"),
                    ),
                ),
                ("Composed samples", composed_sample_fields),
                (
                    "Resolved",
                    (
                        (
                            f"TC {resolved_stage_time_code:.3f}:",
                            names_at(resolved_stage_time_code),
                        ),
                    ),
                ),
                ("Property stack", (("Entries:", property_stack),)),
            ),
            state="DEBUG",
        )
        carb.log_warn(message)

    @classmethod
    def _kit_cae_selected_velocity_asset(
        cls, field_prim, time_code, cae_vtk, Usd
    ) -> Path | None:
        """Resolve the source VTI selected by the current USD time code."""

        file_names = cls._kit_cae_file_names_value_at_time(
            field_prim,
            time_code,
            cae_vtk,
            Usd,
        )
        if not file_names or len(file_names) != 1:
            return None
        asset_path = file_names[0]
        resolved = asset_path.resolvedPath or asset_path.path
        return Path(resolved).resolve() if resolved else None

    async def _monitor_kit_cae_temporal_proof(
        self,
        *,
        app,
        carb,
        stage,
        timeline,
        velocity_paths: tuple[Path, ...],
        field_prim,
        dataset_emitter,
        flow_environment_path: str,
        dataset_emitter_path: str,
        origin_match: bool,
        grid_match: bool,
        cae_vtk,
        Usd,
        progress_callback=None,
    ) -> bool:
        """Observe all sparse VTI swaps and the closing loop in one Flow session."""

        if len(velocity_paths) < 2 or not self._flow_temporal_sample_time_codes:
            return self._log_kit_cae_temporal_proof(carb, velocity_paths)

        time_codes_per_second = float(stage.GetTimeCodesPerSecond())
        proof_event_count = len(velocity_paths) + 1

        async def record_transition(
            *,
            sequence_index: int,
            expected_asset: Path,
            previous_frame: str,
            transition: str,
            timeline_time_before: float,
            timeline_time_after: float,
            timeline_advancing: bool,
        ) -> bool:
            resolved_stage_time_code = timeline_time_after * time_codes_per_second
            if self.config.simulation_cache.temporal_debug_logging:
                self._log_kit_cae_temporal_time_mapping(
                    carb,
                    field_prim=field_prim,
                    timeline_time_seconds=timeline_time_after,
                    stage_time_codes_per_second=time_codes_per_second,
                    resolved_stage_time_code=resolved_stage_time_code,
                    cae_vtk=cae_vtk,
                    Usd=Usd,
                )
            active_asset = self._kit_cae_selected_velocity_asset(
                field_prim,
                resolved_stage_time_code,
                cae_vtk,
                Usd,
            )
            source_asset_match = active_asset == expected_asset
            operator_readiness = (
                await flow_validation.wait_for_kit_cae_dataset_emitter_ready(
                    app,
                    dataset_emitter,
                )
            )
            payload_attribute = dataset_emitter.GetAttribute("nanoVdbVelocities")
            payload = (
                payload_attribute.Get()
                if payload_attribute and payload_attribute.IsValid()
                else None
            )
            payload_count = len(payload) if payload is not None else 0
            velocity_scale = dataset_emitter.GetAttribute("velocityScale").Get()
            velocity_scale_matches = self._kit_cae_velocity_scale_matches_expected(
                velocity_scale
            )
            couple_rate_velocity = dataset_emitter.GetAttribute(
                "coupleRateVelocity"
            ).Get()
            flow_simulate = stage.GetPrimAtPath(f"{flow_environment_path}/flowSimulate")
            flow_reset = not (
                self._flow_airflow_simulate_path
                == f"{flow_environment_path}/flowSimulate"
                and flow_simulate
                and flow_simulate.IsValid()
                and dataset_emitter
                and dataset_emitter.IsValid()
                and str(dataset_emitter.GetPath()) == dataset_emitter_path
            )
            frame_evidence_valid = (
                source_asset_match
                and bool(operator_readiness["ready"])
                and not bool(operator_readiness["timed_out"])
                and payload_count > 0
                and float(couple_rate_velocity or 0.0) > 0.0
                and timeline_advancing
                and not flow_reset
                and origin_match
                and grid_match
                and velocity_scale_matches
            )
            self._log_kit_cae_temporal_frame(
                carb,
                sequence_index=sequence_index,
                temporal_frames=proof_event_count,
                asset=active_asset or expected_asset,
                previous_frame=previous_frame,
                transition=transition,
                operator_ready=bool(operator_readiness["ready"]),
                operator_wait_ms=float(operator_readiness["seconds"]) * 1000.0,
                nano_vdb_velocities_uint_count=payload_count,
                velocity_scale=velocity_scale,
                velocity_scale_matches=velocity_scale_matches,
                couple_rate_velocity=couple_rate_velocity,
                timeline_time_before=timeline_time_before,
                timeline_time_after=timeline_time_after,
                timeline_advancing=timeline_advancing,
                flow_reset=flow_reset,
                origin_match=origin_match,
                grid_match=grid_match,
                verbose=self.config.simulation_cache.temporal_debug_logging,
            )
            if frame_evidence_valid:
                if progress_callback:
                    progress_callback(
                        sequence_index + 1,
                        active_asset or expected_asset,
                        False,
                    )
                return True

            self._log_kit_cae_temporal_failure_details(
                carb,
                reason=(
                    "source_asset_match="
                    f"{source_asset_match}, operator_ready="
                    f"{operator_readiness['ready']}, flow_reset={flow_reset}, "
                    f"velocity_scale_matches={velocity_scale_matches}"
                ),
                timeline=timeline,
                field_prim=field_prim,
                dataset_emitter=dataset_emitter,
                cae_vtk=cae_vtk,
                Usd=Usd,
                time_codes_per_second=time_codes_per_second,
                expected_asset=expected_asset,
                flow_reset=flow_reset,
            )
            return False

        for sequence_index, expected_asset in enumerate(velocity_paths[1:], start=1):
            expected_time_code = self._flow_temporal_sample_time_codes[sequence_index]
            deadline = time.monotonic() + 8.0
            timeline_time_before = float(timeline.get_current_time())
            while (
                float(timeline.get_current_time()) * time_codes_per_second
                < expected_time_code
                and time.monotonic() < deadline
            ):
                await app.next_update_async()
            timeline_time_after = float(timeline.get_current_time())
            if timeline_time_after * time_codes_per_second < expected_time_code:
                self._log_kit_cae_temporal_failure_details(
                    carb,
                    reason=f"timeline did not reach source frame {expected_asset.name}",
                    timeline=timeline,
                    field_prim=field_prim,
                    dataset_emitter=dataset_emitter,
                    cae_vtk=cae_vtk,
                    Usd=Usd,
                    time_codes_per_second=time_codes_per_second,
                    expected_asset=expected_asset,
                )
                self._log_kit_cae_temporal_proof(carb, velocity_paths)
                return False
            if not await record_transition(
                sequence_index=sequence_index,
                expected_asset=expected_asset,
                previous_frame=self._kit_cae_vti_source_frame(
                    velocity_paths[sequence_index - 1]
                ),
                transition="SWAP",
                timeline_time_before=timeline_time_before,
                timeline_time_after=timeline_time_after,
                timeline_advancing=timeline_time_after > timeline_time_before,
            ):
                self._log_kit_cae_temporal_proof(carb, velocity_paths)
                return False

        if progress_callback:
            progress_callback(len(velocity_paths), velocity_paths[-1], True)
        loop_deadline = time.monotonic() + 8.0
        previous_time = float(timeline.get_current_time())
        loop_time_before = previous_time
        loop_time_after = previous_time
        loop_observed = False
        while time.monotonic() < loop_deadline:
            await app.next_update_async()
            current_time = float(timeline.get_current_time())
            if current_time + 1e-6 < previous_time:
                loop_time_before = previous_time
                await app.next_update_async()
                loop_time_after = float(timeline.get_current_time())
                loop_observed = True
                break
            previous_time = current_time

        if not loop_observed:
            self._log_kit_cae_temporal_failure_details(
                carb,
                reason="timeline did not close the Stage 6 temporal loop",
                timeline=timeline,
                field_prim=field_prim,
                dataset_emitter=dataset_emitter,
                cae_vtk=cae_vtk,
                Usd=Usd,
                time_codes_per_second=time_codes_per_second,
                expected_asset=velocity_paths[0],
            )
            self._log_kit_cae_temporal_proof(carb, velocity_paths)
            return False

        if not await record_transition(
            sequence_index=len(velocity_paths),
            expected_asset=velocity_paths[0],
            previous_frame=self._kit_cae_vti_source_frame(velocity_paths[-1]),
            transition="LOOP",
            timeline_time_before=loop_time_before,
            timeline_time_after=loop_time_after,
            timeline_advancing=True,
        ):
            self._log_kit_cae_temporal_proof(carb, velocity_paths)
            return False

        return self._log_kit_cae_temporal_proof(carb, velocity_paths)

    def _log_kit_cae_temporal_failure_details(
        self,
        carb,
        *,
        reason: str,
        timeline,
        field_prim,
        dataset_emitter,
        cae_vtk,
        Usd,
        time_codes_per_second: float,
        expected_asset: Path | None = None,
        flow_reset: bool = False,
    ) -> None:
        """Emit expanded evidence only when one temporal proof invariant fails."""

        current_time_code = float(timeline.get_current_time()) * time_codes_per_second
        selected_asset = self._kit_cae_selected_velocity_asset(
            field_prim,
            current_time_code,
            cae_vtk,
            Usd,
        )
        self._flow_temporal_failure = {
            "reason": reason,
            "expected_asset": expected_asset.name if expected_asset else "unavailable",
            "resolved_asset": selected_asset.name if selected_asset else "unavailable",
        }
        payload_attribute = dataset_emitter.GetAttribute("nanoVdbVelocities")
        payload = (
            payload_attribute.Get()
            if payload_attribute and payload_attribute.IsValid()
            else None
        )
        velocity_scale = dataset_emitter.GetAttribute("velocityScale").Get()
        couple_rate_velocity = dataset_emitter.GetAttribute("coupleRateVelocity").Get()
        operator_ready = (
            payload is not None
            and len(payload) > 0
            and float(couple_rate_velocity or 0.0) > 0.0
        )
        carb.log_error(
            self._format_flow_log_block(
                "FAILURE DIAGNOSTICS",
                (
                    (
                        "Failure",
                        (("Reason:", reason),),
                    ),
                    (
                        "Expected",
                        (
                            (
                                "Frame:",
                                (
                                    self._kit_cae_vti_source_frame(expected_asset)
                                    if expected_asset
                                    else "unavailable"
                                ),
                            ),
                            (
                                "Asset:",
                                (
                                    expected_asset.name
                                    if expected_asset
                                    else "unavailable"
                                ),
                            ),
                        ),
                    ),
                    (
                        "Observed",
                        (
                            (
                                "Frame:",
                                (
                                    self._kit_cae_vti_source_frame(selected_asset)
                                    if selected_asset
                                    else "unavailable"
                                ),
                            ),
                            (
                                "Asset:",
                                (
                                    selected_asset.name
                                    if selected_asset
                                    else "unavailable"
                                ),
                            ),
                        ),
                    ),
                    (
                        "Flow state",
                        (
                            ("operator_ready:", operator_ready),
                            (
                                "NanoVDB count:",
                                len(payload) if payload is not None else 0,
                            ),
                            ("Velocity scale:", self._flow_log_value(velocity_scale)),
                            (
                                "Couple rate:",
                                self._flow_log_value(couple_rate_velocity),
                            ),
                            ("flow_reset:", flow_reset),
                        ),
                    ),
                ),
                state="FAIL",
            )
        )

    _read_kit_cae_vti_metadata = staticmethod(
        airflow_preflight.read_kit_cae_vti_metadata
    )
    _wait_for_kit_cae_dataset_emitter_ready = staticmethod(
        flow_validation.wait_for_kit_cae_dataset_emitter_ready
    )
    _trace_kit_cae_dav_velocity_dataset = staticmethod(
        flow_validation.trace_kit_cae_dav_velocity_dataset
    )

    _kit_cae_front_intake_tracer_positions = staticmethod(
        flow_smoke.kit_cae_front_intake_tracer_positions
    )

    _configure_kit_cae_intake_tracer_emitter = staticmethod(
        flow_smoke.configure_kit_cae_intake_tracer_emitter
    )
    _configure_kit_cae_smoke_only_tracer_flow = staticmethod(
        flow_smoke.configure_kit_cae_smoke_only_tracer_flow
    )
    _author_kit_cae_smoke_tuning = staticmethod(flow_smoke.author_kit_cae_smoke_tuning)
    _set_kit_cae_spatial_sanity_wireframes_visibility = staticmethod(
        flow_smoke.set_kit_cae_spatial_sanity_wireframes_visibility
    )
    _hide_kit_cae_intake_tracer_meshes = staticmethod(
        flow_smoke.hide_kit_cae_intake_tracer_meshes
    )
    _clear_kit_cae_server_visibility_session_opinion = staticmethod(
        flow_smoke.clear_kit_cae_server_visibility_session_opinion
    )
    _pulse_kit_cae_flow_clear = staticmethod(flow_smoke.pulse_kit_cae_flow_clear)
