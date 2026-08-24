# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""Plain X-Ray target-selection state shared by manual and temporary owners."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class XRayTargetSnapshot:
    """Manual selection plus an optional temporary effective-target override."""

    manual_target_ids: frozenset[str]
    override_owner: str | None
    override_target_ids: frozenset[str]
    override_excluded_paths: frozenset[str] = frozenset()

    @property
    def effective_target_ids(self) -> frozenset[str]:
        """Return the override targets when one owner temporarily has priority."""

        return (
            self.override_target_ids
            if self.override_owner is not None
            else self.manual_target_ids
        )


class XRayTargetState:
    """Own target selection only; material values remain config/runtime state."""

    def __init__(self) -> None:
        self._manual_target_ids: frozenset[str] = frozenset()
        self._override_owner: str | None = None
        self._override_target_ids: frozenset[str] = frozenset()
        self._override_excluded_paths: frozenset[str] = frozenset()

    @property
    def snapshot(self) -> XRayTargetSnapshot:
        """Return selection state without exposing mutable owner fields."""

        return XRayTargetSnapshot(
            self._manual_target_ids,
            self._override_owner,
            self._override_target_ids,
            self._override_excluded_paths,
        )

    def set_manual_target_ids(self, target_ids: frozenset[str]) -> None:
        """Update operator intent without disturbing an active temporary override."""

        self._manual_target_ids = frozenset(target_ids)

    def activate_override(
        self,
        owner: str,
        target_ids: frozenset[str],
        excluded_paths: frozenset[str] = frozenset(),
    ) -> bool:
        """Give one named presentation owner temporary effective-target priority."""

        if self._override_owner not in (None, owner):
            return False
        self._override_owner = owner
        self._override_target_ids = frozenset(target_ids)
        self._override_excluded_paths = frozenset(excluded_paths)
        return True

    def release_override(self, owner: str) -> bool:
        """Return effective target ownership to the preserved manual selection."""

        if self._override_owner != owner:
            return False
        self._override_owner = None
        self._override_target_ids = frozenset()
        self._override_excluded_paths = frozenset()
        return True

    def restore(self, snapshot: XRayTargetSnapshot) -> None:
        """Restore a failed transactional target-selection change exactly."""

        self._manual_target_ids = snapshot.manual_target_ids
        self._override_owner = snapshot.override_owner
        self._override_target_ids = snapshot.override_target_ids
        self._override_excluded_paths = snapshot.override_excluded_paths
