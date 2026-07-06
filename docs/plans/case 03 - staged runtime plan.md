# Case 03 - Staged Runtime Plan

**Status**: Draft
**Last Updated**: 2026-07-06

This document records the working plan for a staged review/runtime application
around the Case 03 OpenUSD scene.

---

## Current State

Case 03 currently has the authored Houdini/OpenUSD asset pipeline, hydrated
external asset layout, planning documents in progress, and the first runnable
Blackwell Monitoring Suite asset-preview slice.

Current decisions already made:

- The public application name is **Blackwell Monitoring Suite**.
- The first build is **Blackwell Monitoring Suite v0.1**.
- v0.1 starts with an asset preview slice, not the full canonical Case 03 stage.
- The first target asset is the Noctua NH-D9 TR5-SP6 CPU cooler.
- Heavy USD, texture, VDB, HDRI, and future runtime assets stay outside the
  source package and are hydrated through `assets/_external/`.
- The application source root is `src/blackwell_monitoring_suite/`.
- The first Kit extension id is `msp.bw.monitoring`.
- The app should launch through Kit with a dedicated `.kit` application config.

Jira tracking:

- Runtime epic: `DC-38` - Blackwell Monitoring Suite Runtime.
- Completed planning task: `DC-39` - Develop Case 03 staged runtime plan.
- Active implementation task: `DC-40` - Stage 1 BMS v0.1 asset preview.
- When a delivery stage is completed, update the matching Jira task before
  moving to the next stage: add a concise completion comment, log the actual
  work time, move the task through Review to Done, run Jira sync, and mark the
  next stage task In Progress when work on that stage starts.

The local authoring and tooling environment still uses `case03-env`. Blackwell
Monitoring Suite runtime code, however, runs inside Kit's Python environment
when launched through `kit.exe`. Any Python dependency used by runtime code must
therefore be available to Kit, not only to `case03-env`.

No separate Conda environment is required for Blackwell Monitoring Suite v0.1.
If a later stage introduces external service processes, automation, or a web
control surface outside Kit, the project should define that environment
deliberately and update README, ADRs, plans, and tooling references in one pass.

## Next Step

Close Stage 1 implementation hygiene, then move to Stage 2 only. Stage 1 now
launches Blackwell Monitoring Suite v0.1, reads runtime config, opens the
configured Noctua NH-D9 TR5-SP6 USD asset, shows it in the Kit RTX viewport,
and reports load status.

Do not implement canonical Case 03 stage loading, camera bookmarks, scene
groups, diagnostics, workload modes, recording tools, or telemetry until the
roadmap reaches the stage that actually needs them.

---

## Product Framing

The viewer is designed around three audience modes: using the application,
evaluating the result, and validating the implementation.

### Primary Audience - Runtime Operator

The primary user is the person who already has the application installed and
uses it directly during review or screen recording. In the first staged build this
is the author, but the application should be designed as if any prepared runtime
operator could drive the same demo.

This user needs to:

- open or reload the configured asset or stage without touching DCC tools;
- move through prepared views from a single server to a rack and then the wider
  data center scene;
- switch visible detail, visual modes, and presentation scale through clear UI
  controls;
- adjust workload or intensity modes for a server, rack, or larger scene group
  when those modes become available;
- control lighting and camera framing without losing the presentation flow;
- see load, render, and runtime status while operating the viewer.

### Secondary Audience - Recruiter or Portfolio Reviewer

The secondary audience is someone who probably will not install the application,
but will evaluate it through still images, edited video, README material, or a
repository scan. This may be an NVIDIA recruiter, a recruiter from another
digital twin or visualization company, or a first-pass technical art reviewer.

This audience needs to understand from the footage that:

- the application is a focused Omniverse/OpenUSD runtime viewer, not just a DCC
  viewport recording;
- the UI is modern, intentional, and legible in video;
- visible controls have obvious purpose even without deep technical context;
- stage loading, prepared views, visual modes, and runtime status form a
  coherent product workflow;
- the Case 03 scene demonstrates authored hardware assets, OpenUSD discipline,
  and runtime presentation quality.

### Tertiary Audience - Technical Reviewer

The tertiary audience is a technically capable reviewer who may install the
project out of interest, due to professional competence, or because they want to
verify that the public documentation matches the actual runtime.

This reviewer needs to confirm that:

- setup and launch documentation match what the application actually does;
- hydrated asset paths, runtime configuration, and launch assumptions are
  explicit;
- the viewer is not secretly dependent on local workstation-only absolute paths;
- documented OpenUSD, Kit, and runtime boundaries are visible in the repository
  structure and application behaviour;
- future scope is labelled honestly and is not presented as already complete;
- the application can serve as a reproducible technical proof, not only as a
  polished video source.

### Audience Outcomes

For the runtime operator, the viewer should provide a controlled demonstration
surface. The operator should be able to launch the app, load the configured
asset or stage for the current delivery slice, move through prepared server,
rack, and data center views when those slices exist, switch visual detail or
workload/intensity modes when those slices exist, and recover from common load
issues without leaving the application.

For the recruiter or portfolio reviewer, the viewer should produce clear visual
evidence. Still images and edited video should make the project legible without a
live install: the reviewer should understand the scale and quality of the Data
Center/Blackwell Rig scene, see that this is a reproducible Omniverse/OpenUSD
runtime rather than a Houdini viewport recording, and recognize that the UI
controls support a coherent presentation workflow.

For the technical reviewer, the viewer should prove implementation honesty. A
local install should confirm that the documented setup, hydrated asset package,
runtime configuration, OpenUSD stage loading, viewer commands, and non-goals
match what actually ships. The reviewer should be able to tell which parts are
implemented behaviour and which parts are explicitly future scope.

### Delivery Mode

Blackwell Monitoring Suite ships and launches as an Omniverse Kit application.

The first screen should be the usable viewer, not a landing page or a generic
project launcher. The operator should immediately see the RTX viewport, review
controls, status, and either the configured v0.1 asset path or a clear empty
state. Later stages may replace the v0.1 asset path with the canonical Case 03
stage path when that stage becomes the active slice.

The main experience is a guided presentation flow through prepared cameras,
scene groups, lighting states, and visual/detail modes as those capabilities
are implemented. The application should support deliberate demonstration rather
than freeform DCC exploration.

Technical details should remain available through compact status messages and,
where useful in later stages, diagnostics or selection information. They should
not interrupt the presentation path or dominate the screen during
recruiter-facing footage.

### Required Staged Capabilities

To deliver the audience outcomes, the staged application should eventually
provide:

- load and reload for configured OpenUSD assets and the canonical Case 03
  stage when that stage becomes the current slice;
- lighting presets or lighting mode controls suitable for review footage;
- a minimal synthetic telemetry source that can drive runtime behaviour without
  relying on a DCC timeline;
- telemetry-driven fan motion for the first hardware slice;
- staged scale progression from a single asset to server, rack, and wider data
  center views;
- manual workload/intensity preview modes only when real USD, material, cache,
  or runtime hooks exist for them;
- status messaging for load, render, and runtime state;
- runtime configuration for asset path, stage path, asset root, and future
  inputs without hidden workstation-only absolute paths.

### Capability By Stage

This table is the compact source of truth for scope. It prevents later sections
from making future capabilities sound like v0.1 requirements.

| Capability | First Stage | v0.1 Status |
| :--- | :--- | :--- |
| Dedicated BMS app launch | Stage 1 | Implemented |
| Runtime TOML config loading | Stage 1 | Implemented |
| Hydrated asset path resolution | Stage 1 | Implemented |
| Noctua CPU cooler USD load | Stage 1 | Implemented |
| Basic load/render/runtime status | Stage 1 | Implemented |
| Review lighting preset | Stage 2 | Future |
| Synthetic telemetry values | Stage 3 | Future |
| Fan motion driven by telemetry | Stage 4 | Future |
| Full server / Blackwell Rig stage | Stage 5 | Future |
| Cached simulation visual layer | Stage 6 | Future |
| Manual workload states | Stage 7 | Future |
| Server/rack/data hall navigation | Stage 8 | Future |
| Camera bookmarks | Stage 8 | Future |
| Scene group toggles | Stage 8 | Future |
| Diagnostics surface | TBD | Future |

---

## Product Intent

The staged application is a presentation and review runtime for the Case 03
Data Center showreel scene.

It should help an operator demonstrate the scene, help a portfolio reviewer
understand the project through footage, and help a technical reviewer verify
that the documented OpenUSD/Kit runtime can actually be reproduced.

The application is not an authoring environment. Modeling, UV, material,
normal, and geometry cleanup remain part of the Houdini/OpenUSD export
pipeline.

## Truth Boundary

This plan is not claiming that the full telemetry-driven digital twin runtime is
already implemented.

The long-term Case 03 architecture may include a state machine, synthetic
telemetry, telemetry-driven visual switching, cached simulation playback, HUD
logic, and workload modes. In this plan those capabilities become real only when
their delivery stages implement working runtime behaviour. Until then, they are
target architecture or future scope, not completed application behaviour.

## v0.1 vs Later Canonical Stage

Blackwell Monitoring Suite v0.1 is an asset preview slice. Its job is to prove
that the standalone Kit application can launch, read config, resolve the
hydrated asset package, open the configured Noctua NH-D9 TR5-SP6 USD asset, and
show reliable runtime status.

The canonical Case 03 stage is a later milestone. Full server, rack, and data
hall loading should not be treated as v0.1 scope. The plan keeps those targets
visible because they define where BMS is going, but they become implementation
requirements only when the staged roadmap reaches them.

## Application Name Decision

The application is named **Blackwell Monitoring Suite**.

This name covers the whole staged path: the first Kit runtime, synthetic
telemetry, future workload/state switching, server/rack/data hall navigation,
optional external control surfaces, and eventual package-ready modules. The
project should not introduce separate public product names for early and late
stages, because that would create documentation drift without adding
engineering value.

## v0.1 Implementation Decisions

The first staged build is **Blackwell Monitoring Suite v0.1**.

Fixed names and identifiers:

- Public app title: `Blackwell Monitoring Suite`
- Version: `0.1`
- Kit extension id: `msp.bw.monitoring`
- Python package root: `blackwell_monitoring_suite`
- Runtime config: `configs/blackwell_monitoring_suite.v0.1.toml`
- Application source root: `src/blackwell_monitoring_suite/`

The runtime config uses TOML. This matches Kit's own `.kit` and
`extension.toml` configuration style and allows comments. v0.1 runtime code
must read it from Kit's Python environment when launched through `kit.exe`;
`case03-env` remains the development/tooling environment, not the runtime
Python environment for the Kit application.

For v0.1, paths in runtime config are resolved from the application source root
unless a later launch contract explicitly overrides that root. Because the
source root is `src/blackwell_monitoring_suite/`, the default hydrated asset
root is expected to resolve to `../../assets/_external/` from that root.

The first asset catalog entry is:

- Asset id: `noctua_nh_d9_tr5_sp6`
- Label: `Noctua NH-D9 TR5-SP6`
- Path under asset root: `usd/cpu_fan/cpu_fan.usd`
- Kind: `usd_stage`

Heavy USD, VDB, texture, and HDRI payloads stay under `assets/_external/`. They
must not be copied into `src/blackwell_monitoring_suite/`. The application code
may keep a lightweight asset catalog, but that catalog only records ids, labels,
relative paths, and metadata.

The v0.1 source tree should not introduce separate `viewport/`, `stage/`, or
`view/` packages. Stage opening and viewport-facing commands can live in
`app/commands.py` until the code proves that a separate module is needed.

The first extension source should live under the application package tree:

```text
src/blackwell_monitoring_suite/ext/msp.bw.monitoring/
```

That folder is treated as a Kit extension folder by pointing Kit at
`src/blackwell_monitoring_suite/ext` as an extension search path. The extension
itself owns its `config/extension.toml`, docs, and Python module files.

A locally generated Kit App Template may remain a local read-only
reference/build workflow example only. Blackwell Monitoring Suite should be
developed as its own standalone application code path, with its own app config,
extension id, runtime config, and launch story.

The dedicated BMS `.kit` application config must add
`src/blackwell_monitoring_suite/ext` as an extension search path and must enable
`msp.bw.monitoring`. If the extension imports shared application modules from
`src/blackwell_monitoring_suite/`, the app config or extension startup code must
make that package importable in Kit's Python environment.

Blackwell Monitoring Suite v0.1 should launch directly through Kit with its own
application `.kit` file:

```text
kit.exe <path-to-blackwell-monitoring-suite-app>.kit
```

`repo.bat launch` may remain useful inside a generated Kit App Template during
development, but the public launch contract should be the standalone BMS app
config passed to `kit.exe`, not a generic template-app selection flow.

---

## Product and Runtime Decision

Case 03 will continue on the Omniverse Kit App Template path.

The team will use a staged viewer-building workflow: first shape a visible Kit
application shell, then add Case 03 runtime features in small, recoverable
slices.

### Adopted from the reference viewer workflow

- Build a visible UI shell first.
- Add runtime features in small recoverable steps.
- Keep loading, recovery, and status states visible.
- Treat the app as a focused studio/review viewer, not as a generic DCC clone.
- Provide file, stage, camera, lighting, and presentation awareness.
- Keep scene semantics separate from viewport helper objects.

---

## UX Contract

### First screen

The first screen should be the usable viewer, not a landing page.

Expected default state:

- A central RTX viewport.
- A compact toolbar for presentation commands.
- A right-side or dockable review panel.
- A visible status area for load/render/runtime state.
- A configured v0.1 asset path or a clear empty state when no asset is loaded.

The application should have a deliberate, production-quality UI. During screen
recording, the viewer should read as a compact review tool with clear controls,
stable status, and no distracting authoring clutter.

### Operator flow

The default operator flow should be:

1. Launch Blackwell Monitoring Suite.
2. Load or confirm the configured v0.1 asset.
3. Inspect the asset in the RTX viewport.
4. Check load/render/runtime status when the flow needs it.

Later stages extend this flow with the canonical Case 03 stage, prepared camera
bookmarks, scene groups, presentation scale, lighting, visual modes, telemetry,
and workload states.

The operator should not need to use a general DCC workflow, browse arbitrary
asset folders, or edit the stage manually to complete the presentation.

### Layout Rule

The UI layout should stay small until the staged build actually needs more
surface area. The initial target is an RTX viewport plus a compact control and
status area. Extra panels should appear only when a stage introduces a real
operator need.

A custom user-facing USD Stage Tree is not part of the plan. If stage tree
inspection remains useful, it belongs in stock Kit tooling or a later technical
diagnostics surface, not in the main operator flow.

### Core commands

- Load configured v0.1 asset.
- Reload current stage.
- Fit all real scene geometry.
- Fit selected prim.
- Switch prepared cameras/bookmarks when that stage exists.
- Toggle important scene groups when that stage exists.
- Switch lighting mode when that stage exists.
- Show load/render/runtime status.
- Show runtime configuration summary.

---

## Technical Direction

### Runtime base

- Omniverse Kit App Template.
- Kit viewport and RTX rendering.
- Native Kit/OmniUI panels and controls for a polished application face.
- OpenUSD stage access through Kit APIs and `pxr` diagnostics where useful.

### UI architecture direction

- The first staged build starts as a native Kit application with OmniUI panels,
  toolbars, and dockable review controls.
- Viewer actions should be implemented behind clear application commands and
  state services instead of being buried directly inside button callbacks.
- This keeps the app ready for a later external React/FastAPI control surface
  that can drive the same load, camera, visibility, lighting, and
  diagnostic operations.
- An embedded browser UI inside the Kit window is not part of the plan.

### Runtime portability direction

- Path-portable first, package-ready later.
- Runtime asset paths should be relative or configurable, never hidden
  workstation-only absolute paths.
- Stage loading, diagnostics, and viewer settings should flow
  through explicit configuration or shared application state.
- Heavy USD assets, textures, HDRIs, and future runtime assets remain outside
  application images and are hydrated through the external asset package.
- Launch steps, runtime assumptions, and required asset mount points should be
  documented as the viewer takes shape.
- The local viewer should have a small smoke check or launch check before any
  future package wrapper, container, streaming, or cloud execution work starts.

### v0.1 Runtime Contract

The v0.1 runtime contract is intentionally small. It only needs enough
configuration to launch BMS, resolve the hydrated asset package, and load the
first asset preview stage.

The config file is:

```text
configs/blackwell_monitoring_suite.v0.1.toml
```

Minimum v0.1 fields:

- `app.name`: `Blackwell Monitoring Suite`
- `app.version`: `0.1`
- `paths.app_root`: `src/blackwell_monitoring_suite`
- `paths.asset_root`: `../../assets/_external`
- `assets.default_asset_id`: `noctua_nh_d9_tr5_sp6`
- `assets.entries.noctua_nh_d9_tr5_sp6.label`: `Noctua NH-D9 TR5-SP6`
- `assets.entries.noctua_nh_d9_tr5_sp6.path`: `usd/cpu_fan/cpu_fan.usd`
- `assets.entries.noctua_nh_d9_tr5_sp6.kind`: `usd_stage`

Later stages may extend this contract with canonical stage paths, camera
config, scene group config, lighting presets, telemetry source config,
diagnostics summaries, and optional package manifests. Those fields are not
part of the v0.1 implementation unless a later stage pulls them in.

### Reference boundary

- A locally generated Kit App Template may be used as a read-only
  implementation reference for generated app structure and workflow.
- No local reference path is part of the public runtime contract.
- Case 03 authored code and documentation remain in the Case 03 repository.
- Existing Omniverse Kit App Template structure remains the implementation
  base.

---

## Staged Delivery Roadmap

The application should be built in small slices that keep Blackwell Monitoring
Suite runnable after each step. Each stage carries its own completion rule; no
separate "first slice acceptance" ceremony is needed.

At the end of each stage, update the linked Jira task before starting the next
stage. The update should record what shipped, any validation performed, and the
actual time spent; then the task should move through the available workflow to
Done. The next stage task should only be moved to In Progress when active work
on that stage begins.

### Stage 1 - Blackwell Monitoring Suite v0.1 Asset Preview Slice

Jira: `DC-40`

Status: implemented locally.

Build the smallest useful app surface: launch Blackwell Monitoring Suite v0.1,
show the RTX viewport, load one configured USD asset from the hydrated asset
package, and show basic load status. The first target asset is the Noctua NH-D9
TR5-SP6 CPU cooler exported at `assets/_external/usd/cpu_fan/cpu_fan.usd`.

Done when the selected asset is visible in the viewport, the load path/result is
visible in status, and the slice does not require a hidden absolute workstation
path.

Implementation notes:

- The app launches through `src/blackwell_monitoring_suite/start_bms.bat` or a
  direct Kit invocation with the BMS `.kit` file.
- The runtime config is `configs/blackwell_monitoring_suite.v0.1.toml`.
- The extension id is `msp.bw.monitoring`.
- The current default asset is `usd/cpu_fan/cpu_fan.usd` under the hydrated
  external asset package.
- Runtime review camera and light helpers are created in the session layer so
  the hydrated asset is not modified.

### Stage 2 - Look Review Slice

Jira: `DC-41`

Add review lighting for the selected asset: one or more HDRI/dome/environment
presets and the minimum exposure controls needed for clear viewport review.

Done when the selected asset can be viewed under the chosen lighting preset and
the operator can see whether the preset loaded successfully.

### Stage 3 - Synthetic Telemetry Slice

Jira: `DC-42`

Add a minimal synthetic telemetry source that runs with the application. This is
not DCC timeline playback; it is runtime data produced or received while the app
is open.

Done when changing telemetry values are visible in the app and are independent
of pressing Play in Houdini or another DCC.

### Stage 4 - Telemetry Driven Motion Slice

Jira: `DC-43`

Connect telemetry to a visible hardware behaviour. The first practical target is
fan rotation on the CPU cooler: when the app runs and telemetry updates, the fan
motion updates from that data.

The current CPU cooler USD exposes a named fan blade mesh at
`/cpu_fan/geo/render/cpu_cooler/cpu_fan/blades/blades`. Stage 4 should use that
existing scene structure if pivot and rotation axis checks confirm it is
suitable for runtime rotation.

Done when the fan rotates from runtime telemetry and the behaviour survives app
reload without requiring manual timeline animation.

### Stage 5 - Server Review Slice

Jira: `DC-44`

Move from the single hardware asset to the full server or Blackwell Rig scene.
Keep the controls minimal: load, focus/navigation, status, and any lighting
control already proven in earlier slices.

Done when the server scene loads reproducibly, remains stable in RTX viewport,
and can be reviewed without returning to Houdini or editing USD manually.

### Stage 6 - Cached Simulation Playback Slice

Jira: `DC-45`

Introduce cached simulation playback or a cached simulation visual layer only
when the asset package contains a real cache or layer to drive.

Done when the app can enable or play the cached simulation state and report its
load/playback status without pretending to generate the simulation live.

### Stage 7 - Manual Workload State Preview Slice

Jira: `DC-46`

Add manual workload states such as `25%`, `50%`, `75%`, and `96%` only after the
USD package, material overrides, cache states, or runtime data hooks exist.
These controls are manual preview states unless a later stage connects live
telemetry.

Done when each workload state changes documented runtime inputs or visual state.
If those hooks do not exist yet, the workload controls remain out of the UI.

### Stage 8 - Scale Navigation Slice

Jira: `DC-47`

Add deliberate navigation between supported scales: server, rack, and data
center. The exact camera bookmarks and scene group controls are deferred until
this stage because they depend on the final scene structure.

Done when the operator can move between implemented scales through clear
controls and each scale has a stable view suitable for screen recording.

---

## Demonstration Scenarios

The staged application should support a small number of repeatable showreel
review scenarios:

1. **Operator walkthrough:** open the Case 03 scene, reach a stable RTX view,
   step through prepared server, rack, Blackwell Rig, and data center cameras,
   and switch one available visual/detail mode.
2. **Recruiter-facing footage:** record a short guided pass externally where the UI makes
   it obvious that this is an Omniverse/OpenUSD runtime viewer with prepared
   presentation controls, not a raw Houdini viewport.
3. **Hardware review:** select or focus one key hardware asset, show compact
   scene/selection information when that stage exists, and toggle nearby groups
   without losing camera framing.
4. **Look review:** compare lighting modes or exposure settings while keeping
   the presentation camera stable.
5. **Technical reviewer smoke path:** launch the app from documented steps, load
   the stage from runtime configuration, confirm hydrated asset paths, and
   verify status without hidden local paths.

---

## Asset Pipeline Assumptions

The viewer assumes assets have already passed a Houdini/OpenUSD export cleanup
pass.

Current cleanup rules under investigation:

- No `NaN` or `Inf` UV values.
- No face-varying UV count mismatches.
- Avoid complex n-gons in render meshes for Omniverse consumption.
- Recompute final vertex normals after geometry cleanup.
- Do not preserve stale normals for zero-normal cases.
- Freeze or disable unvalidated LOD variants until LOD00 is stable.

The viewer should not try to repair asset problems. Any diagnostics beyond basic
runtime status remain TBD until the project defines what is actually worth
showing inside the application.

---

## Non-Goals

- Full Omniverse Create replacement.
- General asset browser for arbitrary projects.
- Houdini export automation.
- Geometry, UV, material, or normal repair.
- Runtime asset scanner or USD preflight engine in the current slices.
- Built-in media recording or export tools.
- External web control surface in the current staged build.
- Embedded web UI inside the Kit window.
- Video recording.
- Offline render queue.
- Web streaming.
- Live physics.
- Multi-user sessions.
- Cloud deployment.
- Docker or container implementation in the current staged build.
- Kubernetes or orchestration manifests.
- Baking heavy USD assets or textures into an application image.
- Containerised Houdini production environment.
- LOD authoring workflow.

---

## Open Questions

### Product Questions

- Should v0.1 open directly into the default CPU cooler asset, or start with a
  project-specific load button?
- When Stage 5 arrives, should BMS open directly into the canonical Case 03
  stage or keep an explicit project load step?
- Which first-run state is most useful for recruiter-facing screen recording?
- Which visual/detail modes belong before the workload preview stage?

### Scene and Content Questions

- What is the canonical Case 03 stage path for staged loading?
- Which camera bookmarks define the first presentation path?
- Which scene groups need first-class visibility toggles?
- Which key hardware assets need explicit focus or selection affordances?

### Runtime and Configuration Questions

- Which additional config fields are needed after the v0.1 asset preview
  contract: canonical stage path, camera config, scene groups, lighting presets,
  telemetry source, diagnostics summary, or package manifest?
- What smoke check proves the viewer can launch against a hydrated asset package
  without hidden workstation-only state?

### UX and Implementation Questions

- What diagnostics, if any, are actually useful inside the application rather
  than in external validation tools?
- If a Stage Tree is needed for technical inspection, should it remain only in
  stock Kit tooling or a later diagnostics surface?
- Which viewer commands and state objects should be kept stable for a later
  external web control surface?

---
