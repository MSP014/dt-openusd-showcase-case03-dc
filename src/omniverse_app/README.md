# Case 03 Omniverse App

This directory anchors the future NVIDIA Omniverse Kit application layer for
the Case 03 tech pack.

The application layer will consume the USD/VDB asset package and own the
interactive runtime experience: viewport presentation, HUD overlays, operational
state switching, telemetry controls, and scene-level review tools.

This layer is part of the Case 03 tech pack, not a separate product. The tech
pack includes the documentation, USD contracts, asset packaging rules,
validation tools, development helpers, and the future Kit application runtime.

## Boundary

- `docs/` explains the architecture, contracts, and implementation decisions.
- `assets/_external/` contains the heavy hydrated assets outside version
  control.
- `tools/mcp/` provides a small NVIDIA Omniverse USD/Kit MCP helper for
  development-time API lookup.
- External NVIDIA repositories such as `kit-usd-agents` remain outside this
  repository and are used as development references/tooling.

Implementation files will be added here when the first runtime slice is ready.
