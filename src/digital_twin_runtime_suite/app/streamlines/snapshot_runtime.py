"""Materialise immutable Streamlines cache states as static runtime snapshots."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from digital_twin_runtime_suite.app.streamlines.cache import (
    CACHE_PLAYBACK_CURVES_PATH,
    CACHE_PLAYBACK_ROOT_PATH,
    StreamlinesCacheMetadata,
)
from digital_twin_runtime_suite.app.streamlines.speed import (
    SPEED_PRIMVAR_ATTRIBUTE,
    SPEED_PRIMVAR_NAME,
)

SNAPSHOTS_ROOT_PATH = f"{CACHE_PLAYBACK_ROOT_PATH}/Snapshots"
SOURCE_TIME_ATTRIBUTE = "dtrs:sourceTime"


@dataclass(frozen=True)
class StreamlinesSnapshotStateOwnership:
    """Record one static snapshot and the persisted state it reproduces."""

    sample_index: int
    prim_path: str
    source_time_seconds: float
    curve_count: int
    point_count: int
    points_sha256: str
    persisted_points_sha256: str
    speed_sha256: str

    @property
    def matches_persisted_geometry(self) -> bool:
        """Prove the static runtime copy matches its source cache state."""

        return self.points_sha256 == self.persisted_points_sha256


@dataclass(frozen=True)
class StreamlinesSnapshotSetOwnership:
    """Own one DTRS-authored static snapshot set for a validated cache."""

    root_path: str
    geometry_path: Path
    workload: str
    dataset_identity: str
    profile_id: str
    cache_identity: str
    states: tuple[StreamlinesSnapshotStateOwnership, ...]

    def state_path_for(self, sample_index: int) -> str:
        """Return the exact static snapshot path for one cache sample."""

        for state in self.states:
            if state.sample_index == sample_index:
                return state.prim_path
        raise RuntimeError(f"Static snapshot state {sample_index} is unavailable.")


class StreamlinesSnapshotRuntimeMixin:
    """Own static BasisCurves snapshots without changing normal playback."""

    def reset_streamlines_snapshot_runtime_state(self) -> None:
        """Forget transient snapshot ownership without touching the stage."""

        self._streamlines_snapshot_set_ownership = None
        self._streamlines_snapshot_active_sample_index = None

    def prepare_streamlines_snapshots_in_kit(
        self,
        metadata: StreamlinesCacheMetadata,
        geometry_path: Path,
    ) -> StreamlinesSnapshotSetOwnership:
        """Materialise every validated persisted state as one static prim."""

        from pxr import Usd, UsdGeom

        self._validate_streamlines_snapshot_metadata(metadata)
        stage = self._streamlines_snapshot_stage()
        self.cleanup_streamlines_snapshots_in_kit()
        source_stage = Usd.Stage.Open(str(geometry_path))
        if source_stage is None:
            raise RuntimeError("Persisted Streamlines geometry cannot be opened.")
        source_prim = source_stage.GetPrimAtPath(CACHE_PLAYBACK_CURVES_PATH)
        if not source_prim or not source_prim.IsValid():
            raise RuntimeError("Persisted Streamlines BasisCurves is unavailable.")

        session = stage.GetSessionLayer()
        previous_target = stage.GetEditTarget()
        try:
            stage.SetEditTarget(session)
            UsdGeom.Xform.Define(stage, SNAPSHOTS_ROOT_PATH)
            ownership = tuple(
                self._author_streamlines_snapshot_state(
                    stage,
                    source_prim,
                    state,
                    width=metadata.settings.width,
                )
                for state in metadata.states
            )
        except Exception:
            stage.RemovePrim(SNAPSHOTS_ROOT_PATH)
            self.reset_streamlines_snapshot_runtime_state()
            raise
        finally:
            stage.SetEditTarget(previous_target)

        snapshot_set = StreamlinesSnapshotSetOwnership(
            root_path=SNAPSHOTS_ROOT_PATH,
            geometry_path=geometry_path,
            workload=metadata.workload,
            dataset_identity=metadata.dataset_identity,
            profile_id=metadata.profile_id,
            cache_identity=metadata.geometry_sha256,
            states=ownership,
        )
        self._streamlines_snapshot_set_ownership = snapshot_set
        self._streamlines_snapshot_active_sample_index = None
        return snapshot_set

    def select_streamlines_snapshot_state_in_kit(self, sample_index: int) -> bool:
        """Select one prepared static snapshot by visibility only."""

        ownership = self._streamlines_snapshot_set_ownership
        if ownership is None:
            raise RuntimeError("Static Streamlines snapshots are not prepared.")
        if self._streamlines_snapshot_active_sample_index == sample_index:
            return False

        stage = self._streamlines_snapshot_stage()
        target_path = ownership.state_path_for(sample_index)
        target = stage.GetPrimAtPath(target_path)
        if not target or not target.IsValid():
            raise RuntimeError(
                f"Static Streamlines snapshot state {sample_index} is unavailable."
            )

        previous_index = self._streamlines_snapshot_active_sample_index
        previous = None
        if previous_index is not None:
            previous = stage.GetPrimAtPath(ownership.state_path_for(previous_index))
            if not previous or not previous.IsValid():
                raise RuntimeError("Committed static Streamlines snapshot is missing.")

        previous_target = stage.GetEditTarget()
        try:
            stage.SetEditTarget(stage.GetSessionLayer())
            try:
                if previous is not None:
                    self._set_streamlines_snapshot_visibility(previous, False)
                self._set_streamlines_snapshot_visibility(target, True)
                visible_count = self.streamlines_snapshot_visible_count_in_kit()
                if visible_count != 1:
                    raise RuntimeError(
                        "Static Streamlines snapshot selection requires exactly one "
                        f"visible state; observed={visible_count}."
                    )
            except Exception:
                self._restore_streamlines_snapshot_visibility(previous_index)
                raise
        finally:
            stage.SetEditTarget(previous_target)

        self._streamlines_snapshot_active_sample_index = sample_index
        self._streamlines_cache_active_sample_index = sample_index
        return True

    def streamlines_snapshot_visible_count_in_kit(self) -> int:
        """Count visible static snapshots without changing their selection."""

        from pxr import UsdGeom

        ownership = self._streamlines_snapshot_set_ownership
        if ownership is None:
            return 0
        stage = self._streamlines_snapshot_stage()
        return sum(
            UsdGeom.Imageable(stage.GetPrimAtPath(state.prim_path))
            .GetVisibilityAttr()
            .Get()
            != UsdGeom.Tokens.invisible
            for state in ownership.states
        )

    def streamlines_snapshot_active_state_ownership(self):
        """Return the visible snapshot's persisted-geometry identity."""

        ownership = self._streamlines_snapshot_set_ownership
        index = self._streamlines_snapshot_active_sample_index
        if ownership is None or index is None:
            return None
        for state in ownership.states:
            if state.sample_index == index:
                return state
        raise RuntimeError("Visible static snapshot is outside the owned cache set.")

    def streamlines_snapshot_root_count_in_kit(self) -> int:
        """Detect the active root and any suffixed leftovers from a failed swap."""

        try:
            stage = self._streamlines_snapshot_stage()
        except (ImportError, RuntimeError):
            # Startup acceptance reads evidence before Kit creates its first stage.
            return 0
        parent = stage.GetPrimAtPath(CACHE_PLAYBACK_ROOT_PATH)
        if not parent or not parent.IsValid():
            return 0
        return sum(
            child.GetName().startswith("Snapshots") for child in parent.GetChildren()
        )

    def cleanup_streamlines_snapshots_in_kit(self) -> bool:
        """Remove the DTRS-owned snapshot hierarchy and clear its ownership."""

        try:
            stage = self._streamlines_snapshot_stage()
        except (ImportError, RuntimeError):
            self.reset_streamlines_snapshot_runtime_state()
            return False

        previous_target = stage.GetEditTarget()
        try:
            stage.SetEditTarget(stage.GetSessionLayer())
            present = stage.GetPrimAtPath(SNAPSHOTS_ROOT_PATH)
            was_present = bool(present and present.IsValid())
            stage.RemovePrim(SNAPSHOTS_ROOT_PATH)
            return was_present
        finally:
            stage.SetEditTarget(previous_target)
            self._clear_streamlines_snapshot_active_cache_index()
            self.reset_streamlines_snapshot_runtime_state()

    def _clear_streamlines_snapshot_active_cache_index(self) -> None:
        """Clear the shared active index only when this owner last selected it."""

        snapshot_index = getattr(
            self,
            "_streamlines_snapshot_active_sample_index",
            None,
        )
        if (
            getattr(self, "_streamlines_cache_active_sample_index", None)
            == snapshot_index
        ):
            self._streamlines_cache_active_sample_index = None

    @staticmethod
    def _validate_streamlines_snapshot_metadata(
        metadata: StreamlinesCacheMetadata,
    ) -> None:
        """Reject incomplete cache receipts before allocating runtime geometry."""

        if not metadata.valid:
            raise RuntimeError("Static snapshots require a validated cache receipt.")
        if metadata.sample_count != len(metadata.states):
            raise RuntimeError("Cache metadata sample count does not match its states.")
        expected_indices = tuple(range(metadata.sample_count))
        actual_indices = tuple(state.sample_index for state in metadata.states)
        if actual_indices != expected_indices:
            raise RuntimeError("Cache metadata state ordering is not contiguous.")

    def _author_streamlines_snapshot_state(
        self,
        stage,
        source_prim,
        state,
        *,
        width: float,
    ):
        """Copy one persisted sample into default-valued runtime geometry."""

        from pxr import Sdf, Usd, UsdGeom, Vt

        time_code = Usd.TimeCode(state.time_code)
        source_curves = UsdGeom.BasisCurves(source_prim)
        points = source_curves.GetPointsAttr().Get(time_code)
        counts = source_curves.GetCurveVertexCountsAttr().Get(time_code)
        widths = source_curves.GetWidthsAttr().Get(time_code)
        widths_interpolation = source_curves.GetWidthsInterpolation()
        if widths is None:
            widths = Vt.FloatArray((float(width),))
            widths_interpolation = UsdGeom.Tokens.constant
        extent = source_curves.GetExtentAttr().Get(time_code)
        speed_attribute = source_prim.GetAttribute(SPEED_PRIMVAR_ATTRIBUTE)
        source_time_attribute = source_prim.GetAttribute(SOURCE_TIME_ATTRIBUTE)
        speeds = speed_attribute.Get(time_code) if speed_attribute else None
        source_time = (
            source_time_attribute.Get(time_code) if source_time_attribute else None
        )
        self._validate_streamlines_snapshot_values(
            state,
            points=points,
            counts=counts,
            widths=widths,
            extent=extent,
            speeds=speeds,
            source_time=source_time,
        )

        path = f"{SNAPSHOTS_ROOT_PATH}/State_{state.sample_index:03d}"
        curves = UsdGeom.BasisCurves.Define(stage, path)
        curves.CreateTypeAttr(UsdGeom.Tokens.linear)
        curves.CreateWrapAttr(UsdGeom.Tokens.nonperiodic)
        curves.CreateCurveVertexCountsAttr(counts)
        curves.CreatePointsAttr(points)
        curves.CreateWidthsAttr(widths)
        curves.SetWidthsInterpolation(widths_interpolation)
        curves.CreateExtentAttr(extent)
        curves.GetPrim().CreateAttribute(
            SOURCE_TIME_ATTRIBUTE,
            Sdf.ValueTypeNames.Double,
            custom=True,
        ).Set(source_time)
        speed_primvar = UsdGeom.PrimvarsAPI(curves.GetPrim()).CreatePrimvar(
            SPEED_PRIMVAR_NAME,
            speed_attribute.GetTypeName(),
            speed_attribute.GetMetadata("interpolation") or UsdGeom.Tokens.vertex,
        )
        speed_primvar.Set(speeds)
        curves.CreateVisibilityAttr(UsdGeom.Tokens.invisible)
        persisted_points_sha256 = _streamlines_snapshot_hash(points)
        snapshot_points_sha256 = _streamlines_snapshot_hash(
            curves.GetPointsAttr().Get()
        )
        if snapshot_points_sha256 != persisted_points_sha256:
            raise RuntimeError(
                "Static Streamlines snapshot geometry differs from its cache state."
            )
        return StreamlinesSnapshotStateOwnership(
            sample_index=state.sample_index,
            prim_path=path,
            source_time_seconds=float(source_time),
            curve_count=len(counts),
            point_count=len(points),
            points_sha256=snapshot_points_sha256,
            persisted_points_sha256=persisted_points_sha256,
            speed_sha256=_streamlines_snapshot_hash(speeds),
        )

    @staticmethod
    def _validate_streamlines_snapshot_values(
        state,
        *,
        points,
        counts,
        widths,
        extent,
        speeds,
        source_time,
    ) -> None:
        """Reject incomplete or mismatched persisted arrays before authoring."""

        if (
            points is None
            or counts is None
            or widths is None
            or extent is None
            or speeds is None
        ):
            raise RuntimeError(
                f"Persisted Streamlines state {state.sample_index} is incomplete."
            )
        if len(counts) != state.curve_count or sum(counts) != len(points):
            raise RuntimeError(
                f"Persisted Streamlines state {state.sample_index} has bad topology."
            )
        if len(points) != state.point_count or len(speeds) != len(points):
            raise RuntimeError(
                f"Persisted Streamlines state {state.sample_index} has bad data."
            )
        if source_time is None or float(source_time) != state.source_time_seconds:
            raise RuntimeError(
                f"Persisted Streamlines state {state.sample_index} has bad source time."
            )

    @staticmethod
    def _set_streamlines_snapshot_visibility(prim, visible: bool) -> None:
        """Author only the default visibility opinion for one static snapshot."""

        from pxr import UsdGeom

        value = UsdGeom.Tokens.inherited if visible else UsdGeom.Tokens.invisible
        UsdGeom.Imageable(prim).GetVisibilityAttr().Set(value)

    def _restore_streamlines_snapshot_visibility(
        self,
        previous_index: int | None,
    ) -> None:
        """Restore the previously committed snapshot after a failed selection."""

        ownership = self._streamlines_snapshot_set_ownership
        if ownership is None:
            return
        stage = self._streamlines_snapshot_stage()
        for state in ownership.states:
            self._set_streamlines_snapshot_visibility(
                stage.GetPrimAtPath(state.prim_path),
                state.sample_index == previous_index,
            )

    @staticmethod
    def _streamlines_snapshot_stage():
        """Return the active Kit stage required for DTRS runtime authoring."""

        import omni.usd

        stage = omni.usd.get_context().get_stage()
        if stage is None:
            raise RuntimeError("Static Streamlines snapshots require an open stage.")
        return stage


def _streamlines_snapshot_hash(values) -> str:
    """Return a compact exact-array receipt without retaining duplicate payloads."""

    import numpy as np

    array = np.ascontiguousarray(values, dtype=np.float32)
    return hashlib.sha256(array.tobytes()).hexdigest()
