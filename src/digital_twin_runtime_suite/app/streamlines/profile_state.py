# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""Own the preferred Streamlines profile independently from OmniUI."""

from __future__ import annotations

from dataclasses import dataclass

from digital_twin_runtime_suite.app.streamlines.profile import (
    DEFAULT_STREAMLINES_PROFILE,
    StreamlinesProfileId,
)


@dataclass(frozen=True)
class StreamlinesProfileSnapshot:
    """Expose preference now and reserve transactional production fields."""

    preferred_profile: StreamlinesProfileId
    committed_profile: StreamlinesProfileId | None = None
    pending_profile: StreamlinesProfileId | None = None
    generation: int = 0


@dataclass(frozen=True)
class StreamlinesProfileTransition:
    transition_id: int
    previous_profile: StreamlinesProfileId | None
    target_profile: StreamlinesProfileId


class StreamlinesProfileState:
    """Keep profile preference plain and free of presentation side effects."""

    def __init__(
        self,
        preferred_profile: StreamlinesProfileId = DEFAULT_STREAMLINES_PROFILE,
    ) -> None:
        self._preferred_profile = preferred_profile
        self._committed_profile: StreamlinesProfileId | None = None
        self._pending: StreamlinesProfileTransition | None = None
        self._generation = 0

    @property
    def snapshot(self) -> StreamlinesProfileSnapshot:
        return StreamlinesProfileSnapshot(
            preferred_profile=self._preferred_profile,
            committed_profile=self._committed_profile,
            pending_profile=(self._pending.target_profile if self._pending else None),
            generation=self._generation,
        )

    def set_preference(
        self,
        profile_id: StreamlinesProfileId,
    ) -> StreamlinesProfileSnapshot:
        self._preferred_profile = StreamlinesProfileId(profile_id)
        return self.snapshot

    def mark_loaded(
        self, profile_id: StreamlinesProfileId
    ) -> StreamlinesProfileSnapshot:
        """Publish the profile proven by a completed cache load."""

        profile_id = StreamlinesProfileId(profile_id)
        self._preferred_profile = profile_id
        self._committed_profile = profile_id
        self._pending = None
        return self.snapshot

    def begin(
        self, profile_id: StreamlinesProfileId
    ) -> StreamlinesProfileTransition | None:
        """Supersede older profile work while retaining committed truth."""

        profile_id = StreamlinesProfileId(profile_id)
        self._generation += 1
        if profile_id == self._committed_profile:
            self._pending = None
            self._preferred_profile = profile_id
            return None
        transition = StreamlinesProfileTransition(
            self._generation,
            self._committed_profile,
            profile_id,
        )
        self._pending = transition
        return transition

    def is_current(self, transition: StreamlinesProfileTransition) -> bool:
        return self._pending == transition

    def commit(self, transition: StreamlinesProfileTransition) -> bool:
        if not self.is_current(transition):
            return False
        self._committed_profile = transition.target_profile
        self._preferred_profile = transition.target_profile
        self._pending = None
        return True

    def fail(self, transition: StreamlinesProfileTransition) -> bool:
        if not self.is_current(transition):
            return False
        self._pending = None
        return True
