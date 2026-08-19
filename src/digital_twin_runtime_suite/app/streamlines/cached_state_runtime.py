"""Explicit cached-state application to one stable renderer-facing prim."""

from __future__ import annotations

import time
from dataclasses import dataclass

from digital_twin_runtime_suite.app.streamlines.cache import (
    CACHE_PLAYBACK_CURVES_PATH,
    CACHE_PLAYBACK_SOURCE_CURVES_PATH,
)
from digital_twin_runtime_suite.app.streamlines.speed import (
    SPEED_PRIMVAR_ATTRIBUTE,
)

SOURCE_TIME_ATTRIBUTE = "dtrs:sourceTime"


@dataclass(frozen=True)
class CachedStreamlinesState:
    """One complete renderer-facing state read at an explicit cache time code."""

    sample_index: int
    time_code: float
    source_time_seconds: float
    points: object
    speeds: object
    extent: object

    @property
    def point_count(self) -> int:
        return len(self.points)


@dataclass(frozen=True)
class CachedStateApplicationReceipt:
    """Evidence that one complete state reached the stable visible prim."""

    sample_index: int
    source_time_seconds: float
    point_count: int
    speed_count: int
    apply_ms: float


def validate_cached_streamlines_state(
    state: CachedStreamlinesState,
    *,
    expected_point_count: int,
) -> None:
    """Reject incomplete source arrays before any visible property is touched."""

    if state.point_count != expected_point_count:
        raise ValueError(
            "Cached Streamlines points do not match fixed topology: "
            f"expected={expected_point_count}; actual={state.point_count}."
        )
    if len(state.speeds) != state.point_count:
        raise ValueError(
            "Cached Streamlines speed count does not match points: "
            f"points={state.point_count}; speed={len(state.speeds)}."
        )
    if state.extent is None or len(state.extent) != 2:
        raise ValueError("Cached Streamlines state has no valid extent.")


class StreamlinesCachedStateRuntimeMixin:
    """Own explicit source reads and transactional visible-property updates."""

    def reset_streamlines_cached_state_runtime_state(self) -> None:
        self._streamlines_cached_state_generation = (
            getattr(self, "_streamlines_cached_state_generation", 0) + 1
        )
        self._streamlines_cached_state_apply_receipts = []

    def invalidate_streamlines_cached_state_updates(self) -> None:
        """Reject completion from an update that outlived its presentation."""

        self._streamlines_cached_state_generation = (
            getattr(self, "_streamlines_cached_state_generation", 0) + 1
        )

    def prepare_streamlines_cached_geometry_in_kit(
        self,
        stage,
        source_curves,
        *,
        UsdGeom,
    ):
        """Create the stable visible BasisCurves and author topology once."""

        previous_target = stage.GetEditTarget()
        stage.SetEditTarget(stage.GetSessionLayer())
        try:
            visible = UsdGeom.BasisCurves.Define(stage, CACHE_PLAYBACK_CURVES_PATH)
            visible.CreateCurveVertexCountsAttr().Set(
                source_curves.GetCurveVertexCountsAttr().Get()
            )
            visible.CreateTypeAttr().Set(source_curves.GetTypeAttr().Get())
            visible.CreateBasisAttr().Set(source_curves.GetBasisAttr().Get())
            visible.CreateWrapAttr().Set(source_curves.GetWrapAttr().Get())
            source_widths = source_curves.GetWidthsAttr()
            widths = source_widths.Get()
            if widths is not None:
                visible_widths = visible.CreateWidthsAttr()
                visible_widths.Set(widths)
                visible.SetWidthsInterpolation(source_curves.GetWidthsInterpolation())
            visible.CreatePointsAttr()
            visible.CreateExtentAttr()
            prim = visible.GetPrim()
            source_prim = source_curves.GetPrim()
            speed_attribute = prim.CreateAttribute(
                SPEED_PRIMVAR_ATTRIBUTE,
                source_prim.GetAttribute(SPEED_PRIMVAR_ATTRIBUTE).GetTypeName(),
            )
            speed_interpolation = source_prim.GetAttribute(
                SPEED_PRIMVAR_ATTRIBUTE
            ).GetMetadata("interpolation")
            speed_attribute.SetMetadata(
                "interpolation", speed_interpolation or "vertex"
            )
            prim.CreateAttribute(
                SOURCE_TIME_ATTRIBUTE,
                source_prim.GetAttribute(SOURCE_TIME_ATTRIBUTE).GetTypeName(),
            )
        finally:
            stage.SetEditTarget(previous_target)
        return visible

    async def apply_streamlines_cached_state_in_kit(
        self,
        sample,
    ) -> CachedStateApplicationReceipt:
        """Copy one explicit source sample to visible defaults, then commit it."""

        import omni.kit.app
        import omni.usd
        from pxr import Sdf, Usd, UsdGeom

        stage = omni.usd.get_context().get_stage()
        if not stage:
            raise RuntimeError("Cached Streamlines state application requires a stage.")
        source_prim = stage.GetPrimAtPath(CACHE_PLAYBACK_SOURCE_CURVES_PATH)
        visible_prim = stage.GetPrimAtPath(CACHE_PLAYBACK_CURVES_PATH)
        if not source_prim or not source_prim.IsValid():
            raise RuntimeError("Cached Streamlines Source geometry is unavailable.")
        if not visible_prim or not visible_prim.IsValid():
            raise RuntimeError(
                "Stable Streamlines presentation Geometry is unavailable."
            )

        metadata = getattr(self, "_streamlines_loaded_cache_metadata", None)
        if metadata is None:
            raise RuntimeError("Cached Streamlines metadata is unavailable.")
        cache_state = next(
            (
                state
                for state in metadata.states
                if state.sample_index == sample.sample_index
            ),
            None,
        )
        if cache_state is None:
            raise RuntimeError(
                f"Cached Streamlines sample {sample.sample_index} is not in metadata."
            )
        time_code = Usd.TimeCode(cache_state.time_code)
        source = UsdGeom.BasisCurves(source_prim)
        state = CachedStreamlinesState(
            sample_index=sample.sample_index,
            time_code=cache_state.time_code,
            source_time_seconds=cache_state.source_time_seconds,
            points=source.GetPointsAttr().Get(time_code),
            speeds=source_prim.GetAttribute(SPEED_PRIMVAR_ATTRIBUTE).Get(time_code),
            extent=source.GetExtentAttr().Get(time_code),
        )
        counts = tuple(source.GetCurveVertexCountsAttr().Get() or ())
        validate_cached_streamlines_state(
            state,
            expected_point_count=sum(int(value) for value in counts),
        )

        generation = getattr(self, "_streamlines_cached_state_generation", 0)
        visible = UsdGeom.BasisCurves(visible_prim)
        attributes = (
            (visible.GetPointsAttr(), state.points),
            (visible_prim.GetAttribute(SPEED_PRIMVAR_ATTRIBUTE), state.speeds),
            (visible.GetExtentAttr(), state.extent),
            (
                visible_prim.GetAttribute(SOURCE_TIME_ATTRIBUTE),
                state.source_time_seconds,
            ),
        )
        previous = tuple(attribute.Get() for attribute, _value in attributes)
        started_at = time.perf_counter()
        previous_target = stage.GetEditTarget()
        stage.SetEditTarget(stage.GetSessionLayer())
        try:
            with Sdf.ChangeBlock():
                for attribute, value in attributes:
                    if not attribute.Set(value):
                        raise RuntimeError(
                            f"Could not author visible {attribute.GetName()}."
                        )
        except BaseException:
            with Sdf.ChangeBlock():
                for (attribute, _value), old_value in zip(attributes, previous):
                    if old_value is None:
                        attribute.Clear()
                    else:
                        attribute.Set(old_value)
            raise
        finally:
            stage.SetEditTarget(previous_target)
        try:
            await omni.kit.app.get_app().next_update_async()
        except BaseException:
            if generation == getattr(self, "_streamlines_cached_state_generation", 0):
                stage.SetEditTarget(stage.GetSessionLayer())
                try:
                    with Sdf.ChangeBlock():
                        for (attribute, _value), old_value in zip(attributes, previous):
                            if old_value is None:
                                attribute.Clear()
                            else:
                                attribute.Set(old_value)
                finally:
                    stage.SetEditTarget(previous_target)
            raise
        if generation != getattr(self, "_streamlines_cached_state_generation", 0):
            raise RuntimeError("Cached Streamlines state update was superseded.")
        if any(attribute.GetTimeSamples() for attribute, _value in attributes):
            raise RuntimeError(
                "Stable Streamlines Geometry accumulated USD time samples."
            )
        self._streamlines_cache_active_sample_index = sample.sample_index
        receipt = CachedStateApplicationReceipt(
            sample_index=sample.sample_index,
            source_time_seconds=state.source_time_seconds,
            point_count=state.point_count,
            speed_count=len(state.speeds),
            apply_ms=(time.perf_counter() - started_at) * 1000.0,
        )
        self._streamlines_cached_state_apply_receipts.append(receipt)
        observer = getattr(
            self,
            "_record_streamlines_explicit_state_application_in_kit",
            None,
        )
        if callable(observer):
            observer(sample, state, visible_prim, receipt)
        return receipt

    def streamlines_cached_state_apply_receipts(
        self,
    ) -> tuple[CachedStateApplicationReceipt, ...]:
        return tuple(getattr(self, "_streamlines_cached_state_apply_receipts", ()))
