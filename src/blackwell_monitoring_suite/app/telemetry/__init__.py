"""Synthetic telemetry boundary for Blackwell Monitoring Suite."""

from .config import TelemetryConfig
from .model import MetricValue, TelemetrySnapshot
from .provider import SnapshotLatch, SyntheticTelemetryProvider

__all__ = [
    "MetricValue",
    "SnapshotLatch",
    "SyntheticTelemetryProvider",
    "TelemetryConfig",
    "TelemetrySnapshot",
]
