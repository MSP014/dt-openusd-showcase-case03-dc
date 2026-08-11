"""DTRS X-Ray subsystem boundary.

The package separates production material-binding lifecycle, material
construction, and the isolated Custom MDL probe into sibling modules.  The
application command facade imports only the mixin required for its current
integration boundary.
"""

from digital_twin_runtime_suite.app.xray.material import (
    XRayApplyResult,
    XRayMaterialMixin,
)
from digital_twin_runtime_suite.app.xray.probe import XRayProbeMixin
from digital_twin_runtime_suite.app.xray.runtime import XRayRuntimeMixin

__all__ = (
    "XRayApplyResult",
    "XRayMaterialMixin",
    "XRayProbeMixin",
    "XRayRuntimeMixin",
)
