# ADR 006: Omniverse Runtime Boundary and Portability

## Status

Accepted

## Context

Case 03 separates Houdini/OpenUSD asset authoring from the Omniverse runtime
layer.

Houdini produces authored USD assets, textures, material assignments, camera
data, simulation caches, and review-ready scene packages. **Blackwell
Monitoring Suite** consumes those outputs as a staged Omniverse Kit runtime.

The runtime must not become a workstation-bound monolithic scene. It should be
structured around explicit contracts so the project remains reproducible,
inspectable, and portable after the USD asset package is hydrated.

The current direction is native Omniverse Kit and OmniUI first. A future
external web control surface may drive the same viewer commands, but embedded
browser UI, web streaming, cloud GPU execution, and distributed service
splitting are outside the current staged build.

## Decision

The Case 03 Omniverse application must be designed as a contract-driven runtime
layer, not as a local-only scene file.

Blackwell Monitoring Suite v0.1 consumes a deliberately small contract:

- application title and version;
- application source root;
- hydrated external asset root;
- default configured asset id;
- default configured USD asset path;
- load/render/runtime status.

Later stages may extend this contract with:

- canonical Case 03 USD composition root;
- camera and view presets;
- visual mode definitions;
- scene group and visibility definitions;
- lighting and exposure presets;
- telemetry source configuration;
- lightweight diagnostics summaries;
- application commands and shared state for load, reload, camera, visibility,
  lighting, telemetry, and diagnostics;
- performance boundaries for payloads, purposes, LODs, instancing, and render
  mesh cleanliness.

Houdini `.hip` files, raw procedural authoring workflows, geometry cleanup, UV
repair, material repair, exploratory renders, local caches, and
workstation-specific absolute paths remain outside the runtime boundary.

The runtime user interface is implemented with native Kit/OmniUI panels,
toolbars, and dockable controls. Viewer operations should still be exposed
behind clear commands and state services so a later external React/FastAPI
control surface can drive the same runtime without rewriting the viewer core.

An embedded browser UI inside the Kit window is explicitly out of scope.

A locally generated NVIDIA Omniverse Kit App Template may remain a read-only
implementation reference for viewer/controller architecture, extension layout,
app configuration, and build/launch patterns. No local reference path is part
of the public runtime contract. The template is not authored Case 03 content
and must not receive Case 03 USD assets, textures, or documentation files.

The runtime architecture must remain path-portable first and package-ready
later. Container images, browser streaming, cloud GPU execution, and
orchestration are explicitly out of scope until the local Kit runtime and USD
asset package are stable.

## Consequences

- Blackwell Monitoring Suite has a clear boundary: it presents and reviews
  hydrated USD assets, but does not perform Houdini-side asset authoring or
  repair.
- Asset hydration from ADR005 becomes part of the runtime contract.
- The native Kit/OmniUI runtime can move in small staged slices without
  blocking a later external web control surface.
- Future packaging work has a clear direction without expanding the current
  viewer into streaming, cloud, or service orchestration work.
- The app must prove portability through explicit configuration, relative
  paths, documented launch steps, and no hidden local scene state.
- ADR007 and the USD architecture guidelines distinguish current requirements
  from long-term digital twin targets.

## Related Documents

- [ADR 005: Asset Life Cycle & Hydration](005-asset-hydration.md)
- [ADR 007: USD Runtime Asset Pipeline](007-usd-digital-twin-pipeline.md)
- [Case 03 - Staged Runtime Plan](../plans/case%2003%20-%20staged%20runtime%20plan.md)
