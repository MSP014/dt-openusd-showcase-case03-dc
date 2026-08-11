"""Public DTRS X-Ray application integration boundary.

Only the production runtime mixin is exported here. Material authoring, the
isolated Custom MDL probe, and shared viewport measurements remain internal
sibling implementation modules.
"""

from digital_twin_runtime_suite.app.xray.runtime import XRayRuntimeMixin

__all__ = ("XRayRuntimeMixin",)
