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
- `E:\omniverse_kit_app` is a read-only local reference copy of NVIDIA
  Omniverse Kit App Template and the generated `msp.case03.blackwell` test
  application. Use it only to inspect app structure, extension layout,
  build/launch workflow, startup/playback/controller patterns, and future
  runtime viewer architecture.

The Omniverse Kit app layer is a future runtime validation layer for the Case 03
content package. Do not treat the local template folder as authored Case 03
content, and do not mix USD/VDB assets, documentation, or project source into
that folder unless explicitly instructed.

Implementation files will be added here when the first runtime slice is ready.
