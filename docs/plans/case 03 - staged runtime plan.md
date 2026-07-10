# Case 03 - Staged Runtime Plan

**Status**: Draft
**Last Updated**: 2026-07-10

This document records the working plan for a staged review/runtime application
around the Case 03 OpenUSD scene.

---

## Current State

Case 03 currently has the authored Houdini/OpenUSD asset pipeline, hydrated
external asset layout, and the first four runnable Blackwell Monitoring Suite
slices: asset preview, look review, synthetic runtime telemetry, and
telemetry-driven CPU fan motion.

Current decisions already made:

- The public application name is **Blackwell Monitoring Suite**.
- The first build was **Blackwell Monitoring Suite v0.1**.
- The current runtime build is **Blackwell Monitoring Suite v0.2.0**.
- The app still starts with a component review slice, not the full canonical
  Case 03 stage.
- The first target asset is the Noctua NH-D9 TR5-SP6 CPU cooler.
- The shared left sidebar now contains `Telemetry` and `Config` tabs without
  changing the viewport footprint.
- The Stage 3 provider produces config-driven latest-only snapshots at an
  independent runtime cadence for `Idle`, `Nominal`, `Surge`, and `Critical`.
- The Telemetry tab exposes workload mode, refresh cadence, freeze/resume,
  hardware-grouped node metrics, derived power and thermal values, and
  intermittent Critical-mode throttling.
- Packaged telemetry defaults remain read-only; operator tuning is persisted to
  the ignored `telemetry_provider.local.toml` override.
- Stage 4 motion drives the Noctua CPU fan from telemetry through a
  topology-validated USD rotation controller.
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
- When a delivery stage is completed, update the matching Jira task before
  moving to the next stage: add a concise completion comment, log the actual
  work time, move the task through Review to Done, run Jira sync, and mark the
  next stage task In Progress when work on that stage starts.

The local authoring and tooling environment still uses `case03-env`. Blackwell
Monitoring Suite runtime code, however, runs inside Kit's Python environment
when launched through `kit.exe`. Any Python dependency used by runtime code must
therefore be available to Kit, not only to `case03-env`.

No separate Conda environment is required for Blackwell Monitoring Suite v0.2.0.
If a later stage introduces external service processes, automation, or a web
control surface outside Kit, the project should define that environment
deliberately and update README, ADRs, plans, and tooling references in one pass.

## Next Step

Stage 5 planning is active through `DC-44`. Implementation begins after the
required server components reach `Composition ready`. BMS then opens the
configured canonical full-server stage by default while retaining load/reload,
focus/navigation, status, and the already proven lighting, telemetry, and fan
motion behaviours.

Until the readiness gate passes, topology correction and re-export remain
Houdini-side work.

Do not expand Stage 5 into cached simulation playback, automatic workload
cycling, rack/data-hall navigation, or heatmap authoring. Those remain separate
staged slices after the full server review surface is stable.

---

## Runtime Versioning

Blackwell Monitoring Suite uses semantic versioning for public runtime
milestones. A minor `0.x.0` release represents a coherent operator-visible
capability, not an automatic increment for every delivery stage. Patch releases
such as `0.3.1` are reserved for fixes to an already released milestone.

The current runtime is `0.2.0`, released after Stage 4. Future release
milestones are:

| Completed through | Version | Runtime milestone |
| :--- | :--- | :--- |
| Stage 4 | `0.2.0` | Telemetry and CPU fan motion; current release. |
| Stage 5 | `0.3.0` | Full Server Runtime. |
| Stage 8 | `0.4.0` | Cached Simulation Review. |
| Stage 10 | `0.5.0` | Server Visual Analytics. |
| Stage 12 | `0.6.0` | Multi-Scale Runtime Foundation. |
| Stage 14 | `0.7.0` | Multi-Scale Visual Analytics. |
| Stage 16 | `0.8.0` | Operational Runtime. |
| Stage 17 | `0.9.0` | Feature-complete runtime with RDMA flow visualisation. |
| Stage 18 | `1.0.0` | Portfolio-ready release and stable demonstration workflow. |

Versioning rules:

- keep the last released version during intermediate stages within a release
  track;
- use an optional semantic pre-release such as `0.4.0-dev.1` only when an
  intermediate build must be distributed or recorded explicitly;
- increment the patch number for fixes to a released milestone, not for the
  next roadmap stage;
- update package, extension, Kit application, runtime config, tests, and public
  documentation version metadata together when a milestone is released;
- release `1.0.0` only after Stage 18 also passes the end-to-end launch and demo
  smoke path, has current setup documentation, contains no critical known
  defects, and reports consistent version metadata.

Use stable runtime filenames such as
`blackwell_monitoring_suite.kit` and `blackwell_monitoring_suite.toml`. Keep the
semantic version in metadata instead of renaming runtime paths at every minor
release. The current `0.2.0` runtime already follows this stable path contract.

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
| Full server / Blackwell Rig stage | Stage 5 | Future |
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
| Rack and data-hall RDMA flow visualisation | Stage 17 | Future |
| Interaction and UI refinement | Stage 18 | Future |
| Selection-aware context inspector | Stage 18 | Future, optional |
| Viewport-embedded HUD overlay | Stage 18 | Future |
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
runtime build is **Blackwell Monitoring Suite v0.2.0**.

Fixed names and identifiers:

- Public app title: `Blackwell Monitoring Suite`
- Version: `0.2.0`
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
configuration to launch BMS, resolve the hydrated asset package, load the first
asset preview stage, configure look-review controls, and connect the synthetic
telemetry and first motion slice.

The config file is:

```text
configs/blackwell_monitoring_suite.toml
```

Minimum runtime fields:

- `app.name`: `Blackwell Monitoring Suite`
- `app.version`: `0.2.0`
- `paths.app_root`: `src/blackwell_monitoring_suite`
- `paths.asset_root`: `../../assets/_external`
- `assets.default_asset_id`: `noctua_nh_d9_tr5_sp6`
- `assets.entries.noctua_nh_d9_tr5_sp6.label`: `Noctua NH-D9 TR5-SP6`
- `assets.entries.noctua_nh_d9_tr5_sp6.path`: `usd/cpu_fan/cpu_fan.usd`
- `assets.entries.noctua_nh_d9_tr5_sp6.kind`: `usd_stage`
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

When a runtime stage is completed, move its detailed plan from this document to
the completed-stage archive, update this table with a direct link, and keep only
the active and future stage details here. Cross-stage contracts that still
govern future work remain in this plan.

### Stage 5 - Server Review Slice

Jira: `DC-44`

Release track: `0.3.0` (released on Stage 5 completion).

Move from the single hardware asset to the full server or Blackwell Rig scene.
Keep the controls minimal: load, focus/navigation, status, and any lighting
control already proven in earlier slices.

Stage 5 has an asset-readiness gate. Each server component must progress through
the same states in order:

`Topology fixed` -> `USD exported` -> `Static preflight passed` ->
`RTX passed` -> `Runtime contract passed` -> `Composition ready`.

| Asset | Current state | Note |
| :--- | :--- | :--- |
| `cpu_fan` | Topology fixed | Corrected; the remaining common checks still apply. |
| `ws_wrx90e` | Topology fixed | Corrected; the remaining common checks still apply. |
| `rm44` | Awaiting topology fix | Re-export and validate after correction. |
| `rtx_pro_4500` | Awaiting topology fix | Re-export and validate after correction. |
| `connectx7` | Awaiting topology fix | Re-export and validate after correction. |
| `psu` | Awaiting topology fix | Re-export and validate after correction. |
| `ram` | Awaiting topology fix | Re-export and validate after correction. |
| `bionix_p120` | Topology fixed | Corrected; the remaining common checks still apply. |
| `p8_max` | Topology fixed | Corrected; the remaining common checks still apply. |
| `cables` | Awaiting topology fix | Re-export and validate after correction. |

No component is `Composition ready` until it passes the same static, RTX, and
runtime-contract checks as every other component in the server assembly.

Canonical server-stage contract:

- Houdini/Solaris exports a static server composition with the root
  `/blackwell_rig_gb203` `Xform` at the world origin and set as `defaultPrim`.
- The stable path under the hydrated asset root is
  `usd/blackwell_rig_gb203/blackwell_rig_gb203.usd`.
- The stage preserves the Houdini-exported `metersPerUnit = 1.0` and
  `upAxis = "Y"`; BMS does not convert or repair units or orientation.
- Existing Houdini references compose the component entry points, and Stage 5
  loads the complete server assembly eagerly. Payload-based selective loading
  is outside Stage 5 and remains a later rack/data-hall decision.
- Component and texture dependencies use relative paths only.
- The static composition excludes VDB layers, workload-specific visual state,
  and authored timeline animation.

Static preflight contract:

- Run the standard OpenUSD `usdchecker` against each corrected component export
  and the canonical server stage before RTX review.
- Keep any Case 03-specific preflight supplement deliberately small. It should
  check unresolved component and texture dependencies, absolute paths,
  `defaultPrim`, `metersPerUnit`, `upAxis`, discoverable `blades` fan meshes,
  and accidental VDB or authored time-sample content.
- Do not build a separate general-purpose validation framework for Stage 5.
- A static preflight pass proves structural USD readiness only. It does not
  prove that holes, complex polygons, normals, or materials render correctly in
  Omniverse; the RTX visual pass remains the topology and rendering authority.

When the full server scene arrives, fan motion should reuse the
[Stage 4 BMS motion contract](case%2003%20-%20completed%20runtime%20stage%20plans.md#stage-4---telemetry-driven-motion-slice)
rather than invent per-part exceptions: CPU cooler fans, front
intake fans, rear exhaust fans, GPU blowers, and the PSU fan should each expose
a stable rotating parent `Xform` whose local origin lies on the rotation axis,
with topology-validated pivot-stack fallback for older or imperfect exports.
BMS should discover candidate fan meshes beneath stable component roots by the
`blades` name or name substring, validate each candidate through the Stage 4
topology contract, and require an explicit config override only when discovery
is ambiguous.

Done when the server scene loads reproducibly, remains stable in the RTX
viewport, all supported fan motion matches telemetry speed, and the scene can
be reviewed without manual USD edits.

### Stage 6 - Cached Simulation Playback Slice

Jira: `DC-45`

Release track: `0.4.0` (released on Stage 8 completion).

Introduce cached simulation playback or a cached simulation visual layer only
when the asset package contains a real cache or layer to drive.

Required scope:
- **Cached Playback:** Implement playback and visual mapping of baked Houdini airflow/thermal simulation caches (e.g., OpenVDB or matching visual layers).

Done when the app can enable or play the cached simulation state and report its
load and playback status without pretending to generate the simulation live.

### Stage 7 - Engineering X-Ray Visual Mode Slice

Jira: no dedicated task exists yet.

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
- defer the exact opacity, material-replacement, or visibility policy until the
  Stage 7 implementation plan is finalised;
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

Jira: no dedicated task exists yet.

Release track: `0.5.0` (released on Stage 10 completion).

Prove the velocity-trail implementation against the full server before adding
rack and data-hall scale. Use a real server-level vector velocity field from the
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

Done when real server airflow velocity can be displayed as stable, readable
trails through a reusable implementation that survives cache switching and
stage reload.

### Stage 10 - Server Heatmap Foundation Slice

Jira: no dedicated task exists yet.

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

Jira: no dedicated task exists yet.

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

Jira: no dedicated task exists yet.

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

Jira: no dedicated task exists yet.

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

Jira: no dedicated task exists yet.

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

Jira: no dedicated task exists yet.

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

### Stage 17 - Rack and Data Hall RDMA Flow Visualisation Slice

Jira: no dedicated task exists yet.

Release track: `0.9.0` (released on Stage 17 completion).

Add an inter-node network-flow layer for `Rack` and `Data Hall` views only.
Visualise workload-driven RDMA traffic through the yellow overhead cable trays
between compute racks and the central Network Rack.

The implementation must use documented network topology and telemetry inputs,
remain legible over the heatmap and velocity-trail layers, and must not add a
single-server data-flow effect. The detailed route contract, rendering
approach, flow timing, performance strategy, controls, and acceptance criteria
remain to be developed before Stage 17 implementation begins.

### Stage 18 - Interaction and UI Refinement Slice

Jira: no dedicated task exists yet. Create an ordinary task under `DC-38`
before implementation or any future detailed planning, validation, or
finalisation of this stage begins.

Release track: `1.0.0` (released after Stage 18 and the `1.0.0` release gate).

After the Stage 1-17 feature set is available, refine the operator workflow and
consolidate the final BMS interface. Stage 11 owns the scale-navigation commands
and stable server, rack, and data-hall views; Stage 18 owns their final UI
placement, interaction design, and presentation polish.

Required scope:

- review and settle the information architecture of the fixed left sidebar,
  starting from the existing `Telemetry` and `Config` tabs;
- place a global, mutually exclusive `Server | Rack | Data Hall` scale control
  outside the contextual sidebar, with the viewport toolbar as the current
  preferred location;
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

Selection-aware inspection does not block Stage 18 completion unless it is
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
