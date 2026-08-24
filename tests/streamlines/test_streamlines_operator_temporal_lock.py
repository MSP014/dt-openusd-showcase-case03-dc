# SPDX-FileCopyrightText: 2026 Maksim Pospelkov
# SPDX-License-Identifier: MIT
"""Focused temporal-context contracts for disposable cache operators."""

from digital_twin_runtime_suite.app.streamlines.operator_runtime import (
    StreamlinesOperatorRuntimeMixin,
)


def test_cache_operator_locks_its_exact_manifest_time_code():
    operator_prim = object()
    cae_viz = _CaeViz()

    locked = StreamlinesOperatorRuntimeMixin._lock_streamlines_operator_to_source_time(
        operator_prim,
        source_time_code=12.5,
        cae_viz=cae_viz,
    )

    temporal_api = cae_viz.temporal_apis[operator_prim]
    assert locked == 12.5
    assert temporal_api.use_locked_time.value is True
    assert temporal_api.locked_time.value == 12.5


def test_preview_operator_keeps_its_unlocked_current_source_contract():
    cae_viz = _CaeViz()

    locked = StreamlinesOperatorRuntimeMixin._lock_streamlines_operator_to_source_time(
        object(),
        source_time_code=None,
        cae_viz=cae_viz,
    )

    assert locked is None
    assert cae_viz.temporal_apis == {}


class _Attribute:
    def __init__(self, value=None) -> None:
        self.value = value

    def Set(self, value) -> None:
        self.value = value

    def Get(self):
        return self.value


class _TemporalApi:
    def __init__(self) -> None:
        self.use_locked_time = _Attribute(False)
        self.locked_time = _Attribute(0.0)

    def GetUseLockedTimeAttr(self):
        return self.use_locked_time

    def GetLockedTimeAttr(self):
        return self.locked_time


class _OperatorTemporalApi:
    def __init__(self, owner) -> None:
        self._owner = owner

    def Apply(self, operator_prim) -> None:
        self._owner.temporal_apis.setdefault(operator_prim, _TemporalApi())

    def __call__(self, operator_prim):
        return self._owner.temporal_apis[operator_prim]


class _CaeViz:
    def __init__(self) -> None:
        self.temporal_apis = {}
        self.OperatorTemporalAPI = _OperatorTemporalApi(self)
