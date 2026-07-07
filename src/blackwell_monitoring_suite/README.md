# Blackwell Monitoring Suite

This directory anchors the Blackwell Monitoring Suite source tree for the Case
03 tech pack.

The application layer consumes the USD/VDB asset package and owns the
interactive runtime experience: viewport presentation, status UI, future
telemetry controls, operational state switching, and scene-level review tools.

Use `start_bms.bat` from this directory to launch the current local Kit runtime
when a built Omniverse Kit App Template release is available.

This layer is part of the Case 03 tech pack. The tech pack includes the
documentation, USD contracts, asset packaging rules, validation tools,
development helpers, and the Blackwell Monitoring Suite runtime.

## Boundary

- `docs/` explains the architecture, contracts, and implementation decisions.
- `assets/_external/` contains the heavy hydrated assets outside version
  control.
- `configs/blackwell_monitoring_suite.v0.1.toml` holds the current runtime
  asset and lighting config.
- `tools/mcp/` provides a small NVIDIA Omniverse USD/Kit MCP helper for
  development-time API lookup.
- External NVIDIA repositories such as `kit-usd-agents` remain outside this
  repository and are used as development references/tooling.
- A locally generated NVIDIA Omniverse Kit App Template may be used as a
  read-only implementation reference for app structure, extension layout,
  build/launch workflow, startup/playback/controller patterns, and future
  runtime viewer architecture. No local reference path is part of the public
  runtime contract.

Blackwell Monitoring Suite is the runtime validation layer for the Case 03
content package. Do not treat the local template folder as authored Case 03
content, and do not mix USD/VDB assets, documentation, or project source into
that folder as part of the BMS runtime package.

Heavy USD, VDB, texture, and HDRI payloads remain under `assets/_external/`.
Application modules may reference those files through relative config paths, but
they must not copy those assets into this source tree.

The Stage 2 look-review baseline uses
`assets/_external/hdri/kloofendal_48d_partly_cloudy_puresky_4k.exr` by default
and applies it through a transient `/BMS_Runtime/Lighting` session-layer dome
light.
