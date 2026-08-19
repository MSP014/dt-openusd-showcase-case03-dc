"""Select prebaked Mesh states without renderer-side geometry conversion."""

from __future__ import annotations

import math
from dataclasses import dataclass

from digital_twin_runtime_suite.app.streamlines.mesh_cache import (
    MESH_CACHE_GEOMETRY_PATH,
)


@dataclass(frozen=True)
class StreamlinesTimelineOwnership:
    """Global timeline state temporarily held by cached Mesh playback."""

    previous_time_seconds: float
    was_playing: bool
    generation: int


class StreamlinesMeshPlaybackRuntimeMixin:
    """Own Mesh time selection; never copy renderer arrays at runtime."""

    def reset_streamlines_mesh_playback_state(self) -> None:
        self._streamlines_mesh_playback_generation = (
            getattr(self, "_streamlines_mesh_playback_generation", 0) + 1
        )
        self._streamlines_timeline_ownership = None
        self._streamlines_runtime_mesh_conversion_count = 0
        self._streamlines_python_point_copy_count = 0

    def invalidate_streamlines_mesh_playback_updates(self) -> None:
        """Prevent an update owned by an older presentation from committing."""

        self._streamlines_mesh_playback_generation = (
            getattr(self, "_streamlines_mesh_playback_generation", 0) + 1
        )

    def acquire_streamlines_timeline_control_in_kit(self) -> None:
        """Pause once before Mesh playback starts and retain prior state."""

        if getattr(self, "_streamlines_timeline_ownership", None) is not None:
            return
        import omni.timeline

        timeline = omni.timeline.get_timeline_interface()
        generation = getattr(self, "_streamlines_mesh_playback_generation", 0)
        ownership = StreamlinesTimelineOwnership(
            previous_time_seconds=float(timeline.get_current_time()),
            was_playing=bool(timeline.is_playing()),
            generation=generation,
        )
        if ownership.was_playing:
            timeline.pause()
        self._streamlines_timeline_ownership = ownership

    async def select_streamlines_mesh_state_in_kit(self, sample) -> None:
        """Select one prebaked Mesh time sample, then commit its identity."""

        import omni.kit.app
        import omni.timeline
        import omni.usd

        stage = omni.usd.get_context().get_stage()
        mesh = stage.GetPrimAtPath(MESH_CACHE_GEOMETRY_PATH) if stage else None
        if not mesh or not mesh.IsValid() or mesh.GetTypeName() != "Mesh":
            raise RuntimeError("Prebaked Streamlines renderer Mesh is unavailable.")
        receipt = getattr(self, "_streamlines_mesh_cache_receipt", None)
        if receipt is None:
            raise RuntimeError("Prebaked Streamlines Mesh receipt is unavailable.")
        state = next(
            (
                item
                for item in receipt.states
                if item.sample_index == sample.sample_index
            ),
            None,
        )
        if state is None:
            raise RuntimeError(
                f"Mesh cache sample {sample.sample_index} is unavailable."
            )
        points_times = getattr(self, "_streamlines_mesh_points_time_codes", ())
        speed_times = getattr(self, "_streamlines_mesh_speed_time_codes", ())
        if state.time_code not in points_times or state.time_code not in speed_times:
            raise RuntimeError(
                f"Mesh cache sample {sample.sample_index} is incomplete."
            )
        ownership = getattr(self, "_streamlines_timeline_ownership", None)
        if not isinstance(ownership, StreamlinesTimelineOwnership):
            raise RuntimeError("Streamlines Mesh playback does not own the timeline.")
        generation = getattr(self, "_streamlines_mesh_playback_generation", 0)
        timeline = omni.timeline.get_timeline_interface()
        timeline.set_current_time(float(state.source_time_seconds))
        await omni.kit.app.get_app().next_update_async()
        if generation != getattr(self, "_streamlines_mesh_playback_generation", 0):
            raise RuntimeError("Streamlines Mesh state selection was superseded.")
        selected = float(timeline.get_current_time())
        if not math.isclose(
            selected,
            state.source_time_seconds,
            rel_tol=0.0,
            abs_tol=1e-6,
        ):
            raise RuntimeError("Streamlines Mesh timeline selection did not apply.")
        self._streamlines_cache_active_sample_index = sample.sample_index
        observer = getattr(self, "_record_streamlines_mesh_selection_in_kit", None)
        if callable(observer):
            observer(sample, state, mesh)

    async def release_streamlines_mesh_timeline_control_in_kit(self) -> None:
        """Restore timeline state after every scheduler has stopped."""

        ownership = getattr(self, "_streamlines_timeline_ownership", None)
        self._streamlines_timeline_ownership = None
        self.invalidate_streamlines_mesh_playback_updates()
        if not isinstance(ownership, StreamlinesTimelineOwnership):
            return
        import omni.timeline

        timeline = omni.timeline.get_timeline_interface()
        timeline.set_current_time(ownership.previous_time_seconds)
        if ownership.was_playing:
            timeline.play()

    def cancel_streamlines_mesh_timeline_control(self) -> None:
        """Synchronously restore timeline state during shutdown/reload."""

        ownership = getattr(self, "_streamlines_timeline_ownership", None)
        self._streamlines_timeline_ownership = None
        self.invalidate_streamlines_mesh_playback_updates()
        if not isinstance(ownership, StreamlinesTimelineOwnership):
            return
        try:
            import omni.timeline
        except ImportError:
            return
        timeline = omni.timeline.get_timeline_interface()
        timeline.set_current_time(ownership.previous_time_seconds)
        if ownership.was_playing:
            timeline.play()

    def streamlines_mesh_runtime_counters(self) -> dict[str, int]:
        """Expose hard zero-work invariants for the prototype gate."""

        return {
            "runtime_mesh_conversion": int(
                self._streamlines_runtime_mesh_conversion_count
            ),
            "python_point_copy": int(self._streamlines_python_point_copy_count),
        }
