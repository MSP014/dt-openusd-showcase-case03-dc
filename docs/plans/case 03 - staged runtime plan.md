# Case 03 - Staged Runtime Plan

**Status**: Draft
**Last Updated**: 2026-07-20

This document records the working plan for a staged review/runtime application
around the Case 03 OpenUSD scene.

---

## Current State

Case 03 currently has the authored Houdini/OpenUSD asset pipeline, hydrated
external asset layout, and the first five completed Blackwell Monitoring Suite
slices through the full-server runtime review milestone.

Current decisions already made:

- The public application name is **Blackwell Monitoring Suite**.
- The first build was **Blackwell Monitoring Suite v0.1**.
- The current runtime build is **Blackwell Monitoring Suite v0.3.0**.
- BMS now opens the canonical `Blackwell_Rig_server_assembly.usd` stage by
  default through the `blackwell_rig_gb203` runtime asset entry.
- The shared left sidebar now contains `Telemetry` and `Config` tabs without
  changing the viewport footprint.
- The Stage 3 provider produces config-driven latest-only snapshots at an
  independent runtime cadence for `Idle`, `Nominal`, `Surge`, and `Critical`.
- The Telemetry tab exposes workload mode, refresh cadence, freeze/resume,
  hardware-grouped node metrics, derived power and thermal values, and
  intermittent Critical-mode throttling.
- Packaged telemetry defaults remain read-only; operator tuning is persisted to
  the ignored `telemetry_provider.local.toml` override.
- Stage 4 delivered topology-validated CPU fan motion. Stage 5 extends the
  same runtime contract through 11 explicit config-backed bindings for the CPU
  cooler, three GPU blowers, PSU, motherboard NVMe fan, three front P120 fans,
  and two rear P8 Max fans.
- Stage 5 applies a reversible session-layer `open_chassis` review override
  that hides the top and side cover subtrees for full-server review. It does
  not alter the complete Houdini/USD assembly.
- Heavy USD, texture, VDB, HDRI, and future runtime assets stay outside the
  source package and are hydrated through `assets/_external/`.
- The application source root is `src/blackwell_monitoring_suite/`.
- The first Kit extension id is `msp.bw.monitoring`.
- The app should launch through Kit with a dedicated `.kit` application config.

Jira tracking:

- Runtime epic: `DC-38` - Blackwell Monitoring Suite Runtime.
- Completed planning task: `DC-39` - Develop Case 03 staged runtime plan.
- Completed implementation task: `DC-40` - Stage 1 BMS v0.1 asset preview.
- Completed implementation task: `DC-41` - Stage 2 Look Review Slice.
- Completed implementation task: `DC-42` - Stage 3 Synthetic Telemetry Slice.
- Completed implementation task: `DC-43` - Stage 4 Telemetry Driven Motion
  Slice.
- Completed implementation task: `DC-44` - Stage 5 Full Blackwell Rig server
  review.
- Next implementation task: `DC-45` - Stage 6 Cached Simulation Playback Slice.
- When a delivery stage is completed, update the matching Jira task before
  moving to the next stage: add a concise completion comment, log the actual
  work time, move the task through Review to Done, run Jira sync, and mark the
  next stage task In Progress when work on that stage starts.

The local authoring and tooling environment still uses `case03-env`. Blackwell
Monitoring Suite runtime code, however, runs inside Kit's Python environment
when launched through `kit.exe`. Any Python dependency used by runtime code must
therefore be available to Kit, not only to `case03-env`.

No separate Conda environment is required for the current Blackwell Monitoring
Suite runtime.
If a later stage introduces external service processes, automation, or a web
control surface outside Kit, the project should define that environment
deliberately and update README, ADRs, plans, and tooling references in one pass.

## Next Step

Stage 6 is the next active runtime slice. It should introduce cached simulation
playback or a cached simulation visual layer only when the hydrated asset
package contains a real exported cache or matching visual layer to drive.

Do not expand Stage 6 into Engineering X-Ray, workload-to-cache state binding,
velocity trails, heatmaps, automatic workload cycling, rack/data-hall
navigation, or generated simulation. Those remain separate staged slices after
the cached playback surface is stable.

---

## Runtime Versioning

Blackwell Monitoring Suite uses semantic versioning for public runtime
milestones. A minor `0.x.0` release represents a coherent operator-visible
capability, not an automatic increment for every delivery stage. Patch releases
such as `0.3.1` are reserved for fixes to an already released milestone.

The current runtime is `0.3.0`, released after Stage 5. Future release
milestones are:

| Completed through | Version | Runtime milestone |
| :--- | :--- | :--- |
| Stage 4 | `0.2.0` | Telemetry and CPU fan motion. |
| Stage 5 | `0.3.0` | Full Server Runtime; current release. |
| Stage 8 | `0.4.0` | Cached Simulation Review. |
| Stage 10 | `0.5.0` | Server Visual Analytics. |
| Stage 12 | `0.6.0` | Multi-Scale Runtime Foundation. |
| Stage 14 | `0.7.0` | Multi-Scale Visual Analytics. |
| Stage 16 | `0.8.0` | Operational Runtime. |
| Stage 17 | `1.0.0` | Portfolio-ready release and stable demonstration workflow. |

Versioning rules:

- keep the last released version during intermediate stages within a release
  track;
- use an optional semantic pre-release such as `0.4.0-dev.1` only when an
  intermediate build must be distributed or recorded explicitly;
- increment the patch number for fixes to a released milestone, not for the
  next roadmap stage;
- update package, extension, Kit application, runtime config, tests, and public
  documentation version metadata together when a milestone is released;
- release `1.0.0` only after Stage 17 also passes the end-to-end launch and demo
  smoke path, has current setup documentation, contains no critical known
  defects, and reports consistent version metadata.

Use stable runtime filenames such as
`blackwell_monitoring_suite.kit` and `blackwell_monitoring_suite.toml`. Keep the
semantic version in metadata instead of renaming runtime paths at every minor
release. The current runtime already follows this stable path contract.

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

| Capability | First Stage | Current Status |
| :--- | :--- | :--- |
| Dedicated BMS app launch | Stage 1 | Implemented |
| Runtime TOML config loading | Stage 1 | Implemented |
| Hydrated asset path resolution | Stage 1 | Implemented |
| Noctua CPU cooler USD load | Stage 1 | Implemented |
| Basic load/render/runtime status | Stage 1 | Implemented |
| Review lighting preset | Stage 2 | Implemented |
| Configurable review grid | Stage 2 | Implemented |
| Review camera persistence | Stage 2 | Implemented |
| Synthetic telemetry values | Stage 3 | Implemented |
| Fan motion driven by telemetry | Stage 4 | Implemented |
| Full server / Blackwell Rig stage | Stage 5 | Implemented |
| Cached simulation visual layer | Stage 6 | Future |
| Engineering X-Ray visual mode | Stage 7 | Future |
| Workload-to-cache state binding | Stage 8 | Future |
| Server velocity trail foundation | Stage 9 | Future |
| Server heatmap foundation | Stage 10 | Future |
| Server/rack/data hall navigation | Stage 11 | Future |
| Camera bookmarks | Stage 11 | Future |
| Scene group toggles | Stage 11 | Future |
| Multi-scale telemetry model | Stage 12 | Future |
| Multi-scale velocity trail expansion | Stage 13 | Future |
| Multi-scale heatmap expansion | Stage 14 | Future |
| Telemetry and scale-driven material states | Stage 15 | Future |
| Sequential ignition orchestration | Stage 16 | Future |
| Interaction and UI refinement | Stage 17 | Future |
| Selection-aware context inspector | Stage 17 | Future, optional |
| Viewport-embedded HUD overlay | Stage 17 | Future |
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

## Runtime Implementation Decisions

The first staged build was **Blackwell Monitoring Suite v0.1**. The current
runtime build is **Blackwell Monitoring Suite v0.3.0**.

Fixed names and identifiers:

- Public app title: `Blackwell Monitoring Suite`
- Version: `0.3.0`
- Kit extension id: `msp.bw.monitoring`
- Python package root: `blackwell_monitoring_suite`
- Runtime config: `configs/blackwell_monitoring_suite.toml`
- Application source root: `src/blackwell_monitoring_suite/`

The runtime config uses TOML. This matches Kit's own `.kit` and
`extension.toml` configuration style and allows comments. BMS runtime code
must read it from Kit's Python environment when launched through `kit.exe`;
`case03-env` remains the development/tooling environment, not the runtime
Python environment for the Kit application.

For the current runtime, paths in runtime config are resolved from the
application source root
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

### Runtime Contract

The current runtime contract is still intentionally small. It only needs enough
configuration to launch BMS, resolve the hydrated asset package, load the
configured review stage, configure look-review controls, and connect the
synthetic telemetry and config-backed motion bindings.

The config file is:

```text
configs/blackwell_monitoring_suite.toml
```

Minimum runtime fields:

- `app.name`: `Blackwell Monitoring Suite`
- `app.version`: `0.3.0`
- `paths.app_root`: `src/blackwell_monitoring_suite`
- `paths.asset_root`: `../../assets/_external`
- `assets.default_asset_id`: `blackwell_rig_gb203`
- `assets.entries.noctua_nh_d9_tr5_sp6.label`: `Noctua NH-D9 TR5-SP6`
- `assets.entries.noctua_nh_d9_tr5_sp6.path`: `usd/cpu_fan/cpu_fan.usd`
- `assets.entries.noctua_nh_d9_tr5_sp6.kind`: `usd_stage`
- `assets.entries.blackwell_rig_gb203.label`: `Blackwell Rig GB203`
- `assets.entries.blackwell_rig_gb203.path`:
  `usd/Blackwell_Rig_server_assembly.usd`
- `assets.entries.blackwell_rig_gb203.kind`: `usd_stage`
- `lighting.default_hdri_path`:
  `hdri/kloofendal_48d_partly_cloudy_puresky_4k.exr`
- `lighting.exposure`: default review exposure.
- `lighting.intensity`: default dome light intensity.
- `lighting.rotation`: default XYZ dome rotation in degrees.

Later stages may extend this contract with canonical stage paths, camera config,
scene group config, multiple named lighting presets, telemetry source config,
diagnostics summaries, and optional package manifests. Those fields are not part
of the v0.1 implementation unless a later stage pulls them in.

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

### Completed Runtime Stages

Detailed plans for completed runtime stages are preserved in
[Case 03 - Completed Runtime Stage Plans](case%2003%20-%20completed%20runtime%20stage%20plans.md).

| Stage | Jira | Status | Detailed plan |
| :--- | :--- | :--- | :--- |
| Stage 1 - Asset Preview | `DC-40` | Implemented | [Stage 1 details](case%2003%20-%20completed%20runtime%20stage%20plans.md#stage-1---blackwell-monitoring-suite-v01-asset-preview-slice) |
| Stage 2 - Look Review | `DC-41` | Implemented | [Stage 2 details](case%2003%20-%20completed%20runtime%20stage%20plans.md#stage-2---look-review-slice) |
| Stage 3 - Synthetic Telemetry | `DC-42` | Implemented | [Stage 3 details](case%2003%20-%20completed%20runtime%20stage%20plans.md#stage-3---synthetic-telemetry-slice) |
| Stage 4 - Telemetry Driven Motion | `DC-43` | Implemented | [Stage 4 details](case%2003%20-%20completed%20runtime%20stage%20plans.md#stage-4---telemetry-driven-motion-slice) |
| Stage 5 - Server Review | `DC-44` | Implemented | [Stage 5 details](case%2003%20-%20completed%20runtime%20stage%20plans.md#stage-5---server-review-slice) |

When a runtime stage is completed, move its detailed plan from this document to
the completed-stage archive, update this table with a direct link, and keep only
the active and future stage details here. Cross-stage contracts that still
govern future work remain in this plan.

### Stage 6 - Cached Simulation Playback Slice

Jira: `DC-45`

Release track: `0.4.0` (released on Stage 8 completion).

Introduce cached simulation playback or a cached simulation visual layer only
when the asset package contains a real cache or layer to drive.

Required scope:
- **Cached Playback:** Implement playback and visual mapping of baked Houdini airflow/thermal simulation caches (e.g., OpenVDB or matching visual layers).

Done when the app can enable or play the cached simulation state and report its
load and playback status without pretending to generate the simulation live.

#### Implementation Checkpoint - 2026-07-19 Pit Stop

Status: active investigation; cache playback is not yet visually validated.

Confirmed cache and USD repairs:

- The asset package now contains one intended cache sequence only:
  `assets/_external/vdb/server_airflow_sims/server_airflow_vdb_load_50`, with
  800 VDB frames covering time codes `1001` through `1800`.
- The Houdini USD wrapper at
  `assets/_external/usd/server_airflow_v001/server_airflow_load_50.usda` was
  re-exported with `defaultPrim = /sim`, a `1001-1800` range, and both
  `timeCodesPerSecond` and `framesPerSecond` set to `50`.
- The `density` `OpenVDBAsset` now declares `fieldDataType = "float"`, matching
  the inspected VDB grid (`density`, scalar fog volume, float values).  This
  removes the missing field-type metadata that makes runtime interpretation
  ambiguous.
- Per-frame `filePath` time samples resolve to all 800 local VDB files.
  BMS preflight accepts the wrapper and verifies the range, field, type, and
  file samples before attach.
- A manually specified volume extent was used for the export instead of a full
  frame-range extent scan.  The latter took about two minutes for a single
  frame and is not an acceptable export-time path for this sequence.

Known non-blocking wrapper cleanup:

- Houdini still time-samples constant `fieldName = "density"` and
  `fieldIndex = 0`.  This is redundant animation data, but it does not block
  cache resolution or rendering.  Do not spend further time on it until a
  visible native volume is established.

Runtime work completed so far:

- Added config-backed cache preflight and operator controls for attach, detach,
  play, pause, and reset.  The runtime composes the wrapper through the session
  layer, leaving the authored USD and VDB assets untouched.
- Added the Kit dependency `omni.rtx.index_composite` and installed its release
  extension with the official Kit repository tooling.  The extension loads at
  BMS startup together with `omni.index.usd` and `omni.index.renderer`.
- Replaced the unsupported MDL proxy attempt with the official native NVIDIA
  IndeX composition shape: `nvindex:composite`, `omni:rtx:skip`, native IndeX
  material output, colormap, and compositing settings are authored transiently
  in the BMS session layer.
- Focused Python tests pass locally (`16 passed`) for wrapper preflight and the
  authored session-layer contract.  This is structural validation only, not
  proof that a volume is visible in the GPU viewport.

Rejected paths and observed failures:

- Raw RTX volume rendering produced an opaque red, surface-like mass rather
  than a readable airflow volume.
- The MDL `OmniVolumeDensity` proxy is invalid for this VDB source.  Kit logged
  `volume_density_texture` type `3D` versus VDB type `1D`, then crashed in the
  native rendering path.  This proxy must not be restored.
- The first native IndeX compositing attempt loads its dependencies but still
  produces no visible airflow.  The live BMS viewport also changes its selected
  renderer to `Scientific (IndeX)` rather than staying on the intended RTX
  compositor path.  This is the current blocker, not a solved renderer setup.

Resume point and diagnostic order:

1. Capture and inspect the live BMS session layer immediately after Attach:
   reference, composed `Volume`, `OpenVDBAsset`, material binding, IndeX
   attributes, and current timeline time must be checked in the running Kit
   process rather than inferred from unit tests.
2. Identify which setting or extension action selects `Scientific (IndeX)` and
   keep the viewport on RTX while NVIDIA IndeX compositing is enabled.  Do not
   reintroduce `set_hd_engine("index")` or any MDL VDB proxy.
3. Reproduce the official compositing fixture with one local airflow VDB frame
   in the same Kit release.  Compare its session/stage opinions with the BMS
   authored ones to isolate renderer configuration from wrapper playback.
4. Once one frame is visible, validate native time-sampled `filePath` playback
   over several distant frames before tuning opacity, colour, sampling distance,
   or the BMS presentation.
5. Treat any GPU crash, black proxy, or no-volume result as a renderer-contract
   finding and preserve the relevant Kit log before changing Houdini exports.

#### Implementation Checkpoint - 2026-07-20 Pit Stop

Status: active investigation; native OpenVDB playback is visually established,
but it is not yet fast enough for showreel capture.

Verified runtime result:

- The native RTX / NVIDIA IndeX compositing path can render the original Houdini
  `density` OpenVDB sequence inside the BMS viewport while keeping the server
  geometry visible and the camera interactive. This proves that the repaired
  wrapper and the session-layer composition contract are viable.
- The original cache is not a usable playback payload: its 800 source frames
  average about 33 MiB each. Playback measured about `0.75-1.5 FPS`; pausing a
  frame reached only about `19-20 FPS`. This is below the Stage 6 capture
  target of 25 FPS at 1280x720.

Rejected NanoVDB proxy experiment:

- A 30-frame, 25-FPS test set was made from source frames `1001, 1003, ...,
  1059` using Kit's `omni.volume` converter. It produced about 2.46 GiB of
  `.nvdb` data and therefore was not a storage reduction.
- The current USD `OpenVDBAsset` / RTX-IndeX importer contract requires
  OpenVDB files. Attaching the `.nvdb` wrapper failed with
  `OpenVDB importer (NanoVDB): failed to fetch OpenVDB data` and no volume was
  rendered. Do not repeat this route through `OpenVDBAsset`.

Next controlled test:

1. Keep the original 800-frame `.vdb` cache untouched and restore the local
   BMS override to its original wrapper before the next launch.
2. Use Houdini `VDB Resample` with `mode = voxelsizeonly`, linear filtering,
   and `voxel size = 0.00255` (2x the original `0.001275`) to create a separate
   30-frame `.vdb` proxy from `1001, 1003, ..., 1059`, mapped to runtime frames
   `1001-1030` at 25 FPS.
3. A one-frame proof at this resolution produced a valid `.vdb` of 4.7 MiB,
   versus roughly 33 MiB for the source frame. The next session must first
   validate this 30-frame `.vdb` wrapper in BMS, then record playing and paused
   FPS before deciding whether a stronger resample is necessary.
4. Do not generate a full 400-frame proxy, modify the master cache, use NanoVDB
   through `OpenVDBAsset`, or start another renderer branch until that single
   A/B measurement is captured.

#### Implementation Checkpoint - 2026-07-20 Long Pit Stop

Status: active investigation. Stage 6 is **not delivered**. Cached airflow is
visually playable in BMS, but its current animated volume path is not viable
for showreel capture.

Current measured state:

- The current test cache is the separate Houdini 21 export under
  `assets/_external/vdb/server_airflow_sims/server_airflow_vdb_test`, with 400
  frames mapped to `1001-1400` at 25 FPS. Its wrapper is
  `assets/_external/usd/server_airflows/sim_test.usda` and targets
  `/sim/test/density`.
- The test density grid is a scalar `float` OpenVDB grid. Frame `1001` is
  approximately 4.73 MiB on disk, has a voxel size of `0.00255`, resolution
  `184 x 72 x 213`, and about 11.73 MiB expanded memory.
- Exporting from Houdini 21 removed the prior VDB-format-225 compatibility
  warning. Renaming the sequence to `1001-1400` and correcting the wrapper's
  `fieldDataType` also allowed time-sampled playback to advance. Neither
  change materially improved animated performance.
- The BMS GPU profile measured approximately `328.6 ms` for a frame while the
  volume is playing, or about 3 FPS. With no active airflow cache, the same
  review scene is about 24 FPS. The volume/RTX-IndeX composition path is
  therefore the dominant cost; the source-frame disk size is not sufficient
  evidence that ordinary VDB sequence playback will meet the capture target.
- The current BMS IndeX quality settings are `resolutionScale = 25`,
  `renderingSamples = 1`, `filterMode = trilinear`, and
  `samplingDistance = 0.012`. The sampling distance is about 4.7 test-cache
  voxels. The profiler records a total GPU duration only, so it does not yet
  identify a more granular sub-cost inside the volume renderer.

Findings that must not be re-investigated as primary fixes:

- VDB format `225` was a compatibility defect, but VDB `224` did not remove
  the 2-3 FPS playback limit.
- The wrapper's frame numbering, time-sampled `filePath`, and
  `fieldDataType = float` were necessary for playback correctness, but are not
  the measured performance bottleneck.
- Redundant animated `extent`, `fieldName`, and `fieldIndex` samples are USD
  hygiene issues, not an explanation for the observed render cost. Do not
  spend another Houdini pass on them before a renderer route proves viable.
- The Kit `omni.volume` NanoVDB conversion remains rejected for the current
  `OpenVDBAsset`/IndeX wrapper: it produced a larger `.nvdb` payload and the
  importer failed to load it. Do not retry that route through `OpenVDBAsset`.

Viable routes and hypotheses:

1. **IndeX fast-path A/B.** NVIDIA documents `Nearest` as the faster volume
   filter and identifies sampling distance as a direct quality/performance
   control. One settings-only test can change the filter from `trilinear` to
   `nearest` and increase sampling distance to at least `0.0255` (about ten
   voxels), while retaining the existing 25 percent resolution scale and one
   sample. A further resolution reduction to 12-15 percent is a possible
   second setting, but only after recording the first result. This may reduce
   ray-marching cost; it is not a promise of 25 FPS.
2. **Native RTX Interactive Path Tracing volume route.** NVIDIA documents a
   separate non-uniform VDB path that converts VDB data to GPU-friendly
   NanoVDB internally. Its documented authoring contract is a cube mesh with
   a native VDB material and `/rtx/pathtracing/ptvol/enabled`; fog-like
   volumes can use one scattering bounce, one sample, and denoising. This is
   an alternative authoring proof, not a request to recompute the Houdini
   simulation. It must be implemented only after checking an official Kit API
   example for the animated material path; the earlier generic MDL texture
   experiment was incompatible and crashed.
3. **IndeX cluster rendering** is documented for purpose-built multi-host
   installations. It is not the next experiment and must not be assumed to
   distribute the current workstation's GPUs automatically.

Exact resume order:

1. Before editing BMS or Houdini, obtain an official NVIDIA example or API
   reference for an animated native RTX Interactive Path Tracing VDB material
   on a cube mesh. Do not infer the material graph from the failed generic MDL
   setup.
2. Record the current BMS renderer and Index settings, then run one
   settings-only IndeX fast-path A/B: `nearest`, `samplingDistance = 0.0255`,
   25 percent resolution scale, and one sample. Capture playing FPS, a frame
   profile, and a screenshot for readability. Do not regenerate or resample
   VDB data for this test.
3. If that result remains clearly below a usable showreel threshold, stop
   tuning the current IndeX route. Implement a first-frame native RTX
   Interactive Path Tracing proof using the existing test sequence, then make
   a single short animated A/B before expanding the implementation.
4. Do not perform further Houdini VDB resampling, wrapper exports, extent
   cleanup, NanoVDB conversion, or cluster configuration until either route
   has a measured positive result.

### Stage 7 - Engineering X-Ray Visual Mode Slice

Jira: `DC-48`

Release track: `0.4.0` (released on Stage 8 completion).

Introduce a manually controlled, reversible runtime visual override that lets
the operator inspect internal server components and simulation layers through
otherwise occluding chassis geometry.

Required scope:

- expose an explicit Engineering X-Ray toggle and visible mode status;
- apply runtime or Session Layer overrides without editing authored USD assets
  or MDL sources;
- restore the original presentation after the mode is disabled or the stage is
  reloaded;
- initially target the outer chassis and other documented occluding components,
  including the SilverStone RM44 walls and covers;
- establish a camera-aware chassis fade for server review: the top cover stays
  hidden, while the left and right side panels remain opaque near front/rear
  views and smoothly fade out as the camera moves towards a side view;
- calculate the fade from the camera position in server-local space against a
  configured longitudinal front/rear axis, rather than hard-coding a world
  axis or using camera distance; refine the angular thresholds, interpolation,
  and hysteresis during the Stage 7 plan finalisation;
- author a dedicated runtime-only material override or material binding for
  the side panels. Do not mutate a shared Houdini-authored chassis material;
  validate the chosen Omniverse renderer material path before depending on
  smooth opacity in RTX;
- when a panel reaches zero opacity, permit a visibility override as a final
  render-cost optimisation, while opacity remains the presentation mechanism
  through the transition;
- establish an override boundary that later LED, heatmap, and other material
  states can compose with instead of silently replacing.

Done when Engineering X-Ray can be enabled and disabled reproducibly, reveals
the documented internal review targets, restores the normal presentation, and
does not dirty authored assets.

### Stage 8 - Workload-to-Cache State Binding Slice

Jira: `DC-46`

Release track: `0.4.0` (released on Stage 8 completion).

Connect the existing global `Idle`, `Nominal`, `Surge`, and `Critical` workload
modes to real Houdini-authored simulation caches or matching USD layers made
available through Stage 6. Do not introduce a second set of equivalent `25%`,
`50%`, `75%`, and `96%` controls.

Required scope:

- define which authored cache or layer, if any, corresponds to each supported
  workload mode;
- use the existing workload-state control as the only operator-facing state
  selector;
- select and play only cache states that genuinely exist in the hydrated asset
  package;
- report missing or unsupported state mappings instead of presenting a control
  that changes only its label.

The cache/layer contract, transition behaviour, playback semantics, and missing
state fallback must be refined when the Stage 8 plan is reviewed and finalised
immediately before implementation.

Done when every supported workload mode selects a documented authored cache or
layer, unsupported mappings are reported honestly, and no parallel
workload-state model has been introduced.

### Stage 9 - Server Velocity Trail Foundation Slice

Jira: `DC-49`

Release track: `0.5.0` (released on Stage 10 completion).

Prove the velocity-trail implementation against the full server before adding
rack and data-hall scale. Use an exported server-level vector velocity field from the
Stage 6 simulation package and the cache selected through Stage 8.

Required scope:

- establish a reusable trail renderer and runtime controller rather than a
  throwaway server-only prototype;
- validate vector-field coordinates, units, time mapping, and playback
  synchronisation;
- develop and tune trail seeding, advection, lifetime, density, width, colour,
  and presentation-speed behaviour at `Server` scale;
- validate performance and clean reset across cache changes, reload, and
  shutdown;
- verify that trails remain readable with the Stage 7 Engineering X-Ray mode;
- exclude rack and data-hall trail generation from this stage.

Done when exported server airflow velocity can be displayed as stable, readable
trails through a reusable implementation that survives cache switching and
stage reload.

### Stage 10 - Server Heatmap Foundation Slice

Jira: `DC-50`

Release track: `0.5.0` (released on Stage 10 completion).

Prove the telemetry-driven heatmap implementation against the full server
before adding rack and data-hall scale. Reuse the current server telemetry and
the stable semantic component roots established by the server review stage.

Required scope:

- establish a reusable heatmap renderer, scalar mapping, and runtime controller
  rather than a server-only implementation;
- map documented server telemetry to stable component or region targets;
- define scalar ranges, normalisation, colour mapping, quality handling, and a
  clear missing-data state;
- verify composition with the Stage 7 Engineering X-Ray mode and Stage 9
  velocity trails;
- preserve clean reset across metric changes, stage reload, and shutdown;
- exclude rack and data-hall heatmap generation from this stage.

Done when documented server telemetry can drive a stable, readable heatmap
through a reusable implementation without inventing unavailable measurements.

### Stage 11 - Scale Navigation Foundation Slice

Jira: `DC-47`

Release track: `0.6.0` (released on Stage 12 completion).

Add deliberate navigation between supported scales: server, rack, and data
hall. The exact camera bookmarks and scene group controls are deferred until
this stage because they depend on the final scene structure.

Required scope:

- implement deliberate camera navigation and bookmarks across `Server`, `Rack`,
  and `Data Hall`;
- define stable scene groups and presentation views for each implemented scale;
- keep scale-navigation commands separate from later telemetry, material, and
  scenario behaviour.

Done when the operator can move between implemented scales through clear
commands and each scale has a stable view suitable for repeated review and
screen recording.

### Stage 12 - Multi-Scale Telemetry Model Slice

Jira: `DC-51`

Release track: `0.6.0` (released on Stage 12 completion).

Extend the telemetry provider and runtime state model beyond a single server
node so later scale-aware consumers can address servers, racks, and the data
hall without inventing aggregate state inside UI or rendering code.

Required scope:

- preserve stable site, hall, rack, node, and component identity where the
  synthetic source supports it;
- generate documented server, rack, and data-hall snapshots or aggregates;
- keep PUE at hall/facility scope and use rack-level CEF only where the
  telemetry contract supports it;
- retain explicit `synthetic`, `derived`, `estimated`, or unavailable quality
  instead of presenting generated aggregates as measured data;
- provide the active-scale state required by later material, orchestration, and
  visualisation stages.

The exact synthetic topology, aggregate metric set, update strategy, and
performance limits must be refined before Stage 12 implementation begins.

Done when runtime consumers can request documented telemetry for a known
server, rack, or data-hall context and missing aggregate data remains explicit.

### Stage 13 - Multi-Scale Velocity Trail Expansion Slice

Jira: `DC-52`

Release track: `0.7.0` (released on Stage 14 completion).

Extend the Stage 9 server trail foundation to `Rack` and `Data Hall` after the
scale-navigation and multi-scale runtime context exist. Each supported scale
must use a real implemented vector-field source rather than fabricated flow
data.

Required scope:

- reuse the Stage 9 renderer and controller instead of implementing a parallel
  trail system;
- define real rack and data-hall vector-field sources and their coordinate
  contracts;
- add scale-specific seeding, lifetime, density, width, visibility, and level
  of detail;
- gate trail cost by active scale, camera distance, selection, and documented
  performance budgets;
- allow telemetry to select documented presentation state where useful, but do
  not derive or fabricate velocity vectors from telemetry metrics.

The detailed multi-scale cache contract, performance strategy, UI controls,
and acceptance thresholds must be refined before Stage 13 implementation.

Done when the proven server trail system expands to real rack and data-hall
vector fields with stable scale transitions and bounded runtime cost.

### Stage 14 - Multi-Scale Heatmap Expansion Slice

Jira: `DC-53`

Release track: `0.7.0` (released on Stage 14 completion).

Extend the Stage 10 server heatmap foundation to `Rack` and `Data Hall` after
scale navigation and the multi-scale telemetry model exist. The expansion must
reuse the server renderer, scalar mapping, and quality semantics rather than
introducing a parallel heatmap system.

Required scope:

- map documented rack and data-hall aggregates to stable semantic targets;
- define scale-specific ranges, normalisation, colour mapping, visibility, and
  level of detail;
- keep missing, estimated, derived, and synthetic data visibly honest;
- gate update and rendering cost by active scale, camera distance, selection,
  and documented performance budgets;
- remain composable with Engineering X-Ray and both server and multi-scale
  velocity trails;
- avoid generating scalar values that the Stage 12 telemetry model does not
  expose.

The detailed aggregate mapping, visual composition, controls, and acceptance
thresholds must be refined before Stage 14 implementation.

Done when the Stage 10 heatmap system expands to documented rack and data-hall
telemetry with stable scale transitions and bounded runtime cost.

### Stage 15 - Telemetry and Scale-Driven Material States Slice

Jira: `DC-54`

Release track: `0.8.0` (released on Stage 16 completion).

Drive supported runtime material parameters from both telemetry state and the
active `Server`, `Rack`, or `Data Hall` presentation scale. Use a runtime policy
to resolve those inputs rather than authoring a separate material for every
state-and-scale combination.

Required scope:

- implement telemetry-driven front-panel Power and Status LEDs;
- implement ConnectX-7 Link and Activity LEDs;
- implement motherboard RJ-45 Link and Activity LEDs;
- derive network activity from the corresponding telemetry metrics;
- at `Server` scale, allow the complete supported indicator set;
- at `Rack` scale, retain only indicators that are visible and useful for the
  active or selected rack context;
- at `Data Hall` scale, disable per-port rear-face activity and retain only
  inexpensive aggregate or front-facing status cues;
- define precedence between these runtime material states and the Stage 7
  Engineering X-Ray override and Stage 14 heatmap contract.

The exact metric mapping, update cadence, blink behaviour, shader inputs,
scale policy, and override precedence must be refined when the Stage 15 plan is
reviewed and finalised immediately before implementation.

Done when the front-panel, ConnectX-7, and RJ-45 indicators respond to their
documented telemetry inputs, scale changes apply the documented material-detail
policy, and no combinatorial set of state-specific materials is required.

### Stage 16 - Sequential Ignition Orchestration Slice

Jira: `DC-55`

Release track: `0.8.0` (released on Stage 16 completion).

Add the repeatable "Viral Inference Surge" scenario at `Rack` and `Data Hall`
scales. This is a multi-node orchestration layer, not a single-server visual
mode.

Required scope:

- cascade server activation across the 16 racks with configurable ordering and
  time offsets;
- move addressed nodes from `Idle` towards `Critical` through the existing
  runtime state model rather than creating a second workload vocabulary;
- expose start, reset, cancel, progress, and completion state for repeatable
  review and capture;
- keep scenario timing deterministic enough for repeated footage;
- drive only documented telemetry and runtime consumers available by this
  stage.

Done when the operator can trigger and reset a repeatable rack-to-data-hall
ignition wave, and every affected node remains addressable through the shared
multi-scale state model.

### Stage 17 - Interaction and UI Refinement Slice

Jira: `DC-57`

Release track: `1.0.0` (released after Stage 17 and the `1.0.0` release gate).

After the Stage 1-16 feature set is available, refine the operator workflow and
consolidate the final BMS interface. Stage 11 owns the scale-navigation commands
and stable server, rack, and data-hall views; Stage 17 owns their final UI
placement, interaction design, and presentation polish.

Required scope:

- review and settle the information architecture of the fixed left sidebar,
  starting from the existing `Telemetry` and `Config` tabs;
- place a global, mutually exclusive `Server | Rack | Data Hall` scale control
  outside the contextual sidebar, with the viewport toolbar as the current
  preferred location;
- expose a chassis presentation controller with `Auto fade`, `Open`, and
  `Closed` modes. `Auto fade` uses the Stage 7 camera-aware opacity policy;
  `Open` and `Closed` use reversible session-layer visibility overrides;
  decide then whether the SilverStone RM44 rack ears remain visible when the
  side panels are open;
- keep the active scale visible and consolidate or remove duplicated controls;
- review the remaining camera, scene, lighting, telemetry, status, visual-layer,
  scenario, and runtime controls after their delivery stages are complete;
- implement an interactive viewport HUD overlay using `omni.ui.scene` for
  spatial information, hierarchical scale indication, and quick stress-test
  commands routed through the existing runtime state services.

Selection-aware inspection is optional stretch scope:

- a single viewport selection may open an `Inspect` tab with context for the
  nearest known GPU, component, server node, or rack;
- selection resolution should map a picked leaf prim to a stable semantic root,
  then combine static identity/specification data with available telemetry;
- an explicit drill-down command should enter the selected rack or server, with
  double-click treated as a candidate shortcut only after checking it against
  the stock Kit viewport bindings;
- rack and node summaries must use real implemented aggregate data and must not
  invent telemetry that the current provider does not expose.

Selection-aware inspection does not block Stage 17 completion unless it is
explicitly promoted from optional scope when the Jira task is created.

Done when the final left-sidebar structure and global scale control form a
coherent operator workflow, the current scale is always clear, duplicated
controls have been resolved, and the interface is stable for repeated review
and screen recording.



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
- General runtime asset scanner or repair-oriented USD validator beyond the
  narrow Stage 5 BMS preflight contract.
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

- Which first-run state is most useful for recruiter-facing screen recording?
- Which visual/detail modes belong before the workload preview stage?

### Scene and Content Questions

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
