# Case 03 - Staged Runtime Plan

**Status**: Active roadmap; Stages 1–8 complete; Stage 9 active
**Last Updated**: 2026-08-15

This document records the working plan for a staged review/runtime application
around the Case 03 OpenUSD scene.

---

## Current State

Case 03 currently has the authored Houdini/OpenUSD asset pipeline, hydrated
external asset layout, and the first eight completed Digital Twin Runtime Suite
slices through Engineering X-Ray visual mode.

Current decisions already made:

- The public application name is **Digital Twin Runtime Suite**.
- The first build was **Digital Twin Runtime Suite v0.1**.
- The current runtime build is **Digital Twin Runtime Suite v0.4.0**, released
  with Stage 7. Stage 8 has no separate release bump; the next feature
  milestone remains `0.5.0` after Stage 10.
- DTRS now opens the canonical `Blackwell_Rig_server_assembly.usd` stage by
  default through the `blackwell_rig_gb203` runtime asset entry.
- The shared left sidebar now contains `Telemetry`, `View`, and `Config` tabs
  without changing the viewport footprint.
- The Stage 3 provider produces config-driven latest-only snapshots at an
  independent runtime cadence for `Idle`, `Nominal`, `Surge`, and `Critical`.
- The Telemetry tab exposes workload mode, refresh cadence, freeze/resume,
  hardware-grouped node metrics, derived power and thermal values, and
  intermittent Critical-mode throttling.
- Telemetry defaults remain read-only in `configs/telemetry_provider.toml`;
  operator tuning is persisted to the ignored sibling
  `configs/telemetry_provider.local.toml` override.
- Stage 4 delivered topology-validated CPU fan motion. Stage 5 extends the
  same runtime contract through 11 explicit config-backed bindings for the CPU
  cooler, three GPU blowers, PSU, motherboard NVMe fan, three front P120 fans,
  and two rear P8 Max fans.
- Stage 5 introduced reversible session-layer chassis presentation overrides
  without altering the complete Houdini/USD assembly. Stage 6 persists the
  operator-selected enclosure visibility groups and front-panel state.
- Stage 6 delivers the cached airflow playback route from a Houdini velocity
  field through manifest-driven VTI discovery, Kit-CAE, the CAE/NanoVDB bridge,
  and one NVIDIA Flow simulation to a real-time volumetric smoke tracer.
- The accepted `server / load_normal` dataset contains 80 VTI samples at 5 Hz.
  Its 0.2 second cadence and 16 second loop are derived from the manifest,
  rather than from hardcoded sample paths or sequence counts.
- The tracer stays `SMOKE_ONLY`: imported VTI remains the sole velocity source;
  fuel, temperature, burn, combustion, buoyancy, and collision behaviour remain
  disabled.
- The View tab provides persistent Apply-based smoke tuning, transport scale,
  time scale, smoke colour, and parameterised emitter layout controls. They
  preserve the dataset route and do not mutate Flow until an Apply succeeds.
- The generic temporal proof validates all discovered samples, source hashes,
  temporal continuity, origin/grid invariants, loop closure, and zero Flow
  resets. The accepted 80-sample dataset yields 79 forward transitions and one
  loop transition.
- Fixed-camera performance comparison and the final Kit regression pass
  covered Attach, Play, tuning/layout Apply, Pause/Play, Detach, re-Attach, and
  restart persistence on the RTX 3080.
- Vorticity strength remains operator-configurable. Its masks remain an
  internal implementation detail because further mask tuning had no remaining
  FPS budget.
- The completed Stage 6 runtime contract and validation evidence are preserved
  in the [Stage 6 archive](case%2003%20-%20completed%20runtime%20stage%20plans.md#stage-6---cached-simulation-playback-slice).
- Stage 7 delivers the production Custom MDL Fresnel X-Ray material with
  config-driven multi-target selection, Session Layer-only reversible
  bindings, live ReviewCamera response, and telemetry LED ownership that
  resumes from current telemetry state after X-Ray is removed.
- X-Ray target selections are runtime-only and start OFF after startup or
  configuration reload; approved Fresnel parameters persist as project
  defaults and may be locally overridden without auto-applying X-Ray.
- In the tested Case 03/current Kit environment, Fabric Scene Delegate did not
  visually roll back restored bindings. The validated OmniHydra launch
  workaround is therefore retained; this is a narrow tested runtime limitation,
  not a general USD lifecycle failure.
- Combined X-Ray and RTX Flow validation passed on the RTX 3080, including
  typical X-Ray at approximately 25–27 FPS and all configured X-Ray targets at
  approximately 20–25+ FPS.
- The completed Stage 7 runtime contract and validation evidence are preserved
  in the [Stage 7 archive](case%2003%20-%20completed%20runtime%20stage%20plans.md#stage-7---engineering-x-ray-visual-mode-slice).
- Stage 8 binds the shared semantic workload state to manifest-backed Houdini
  temporal airflow datasets through cached validation and phase-preserving Flow
  switching. Its completed evidence is preserved in the [Stage 8 archive](case%2003%20-%20completed%20runtime%20stage%20plans.md#stage-8---workload-to-cache-state-binding-slice).
- Heavy USD, texture, HDRI, temporal VTI, and future runtime assets stay
  outside the source package and are hydrated through `assets/_external/`.
- The application source root is `src/digital_twin_runtime_suite/`.
- The first Kit extension id is `msp.dtrs`.
- The app should launch through Kit with a dedicated `.kit` application config.

The local authoring and tooling environment still uses `case03-env`. Digital Twin Runtime Suite runtime code, however, runs inside Kit's Python environment
when launched through `kit.exe`. Any Python dependency used by runtime code must
therefore be available to Kit, not only to `case03-env`.

No separate Conda environment is required for the current Digital Twin Runtime Suite runtime.
If a later stage introduces external service processes, automation, or a web
control surface outside Kit, the project should define that environment
deliberately and update README, ADRs, plans, and tooling references in one pass.

## Jira Tracking

- Runtime epic: `DC-38` - Digital Twin Runtime Suite Runtime.
- Completed planning task: `DC-39` - Develop Case 03 staged runtime plan.
- Completed implementation task: `DC-40` - Stage 1 DTRS v0.1 asset preview.
- Completed implementation task: `DC-41` - Stage 2 Look Review Slice.
- Completed implementation task: `DC-42` - Stage 3 Synthetic Telemetry Slice.
- Completed implementation task: `DC-43` - Stage 4 Telemetry Driven Motion
  Slice.
- Completed implementation task: `DC-44` - Stage 5 Full Blackwell Rig server
  review.
- Completed implementation task: `DC-45` - Stage 6 Cached Simulation Playback Slice.
- Completed implementation task: `DC-48` - Stage 7 Engineering X-Ray Visual
  Mode Slice.
- Completed implementation task: `DC-46` - Stage 8 Workload-to-Cache State
  Binding Slice.
- Next planned implementation task: `DC-49` - Stage 9 Server Velocity Trail
  Foundation Slice.
- When a delivery stage is completed, update the matching Jira task before
  moving to the next stage: add a concise completion comment, log the actual
  work time, move the task through Review to Done, run Jira sync, and mark the
  next stage task In Progress when work on that stage starts.

## Next Step

Stage 9, Server Velocity Trail Foundation, is the next active implementation
slice. Stage 8, Workload-to-Cache Binding, is complete and archived with its
evidence in the completed runtime-stage plans. Stage 9 must preserve the
accepted Stage 6 Flow, Stage 7 X-Ray, and Stage 8 workload-to-cache contracts.

---

## Runtime Versioning

Digital Twin Runtime Suite uses a canonical three-component semantic version
(`x.y.z`) for public runtime milestones. A minor `0.x.0` release represents a
coherent operator-visible capability, not an automatic increment for every
delivery stage. Patch releases such as `0.4.1` are reserved for fixes to an
already released milestone.

The canonical version is the sole source of truth for runtime configuration,
code and package metadata, release history, Git tags, and internal version
comparisons. The current Stage 7 release is `0.4.0`; subsequent hotfixes use
`0.4.1`, `0.4.2`, and so on. Stage 8 has no separate release bump. The next
feature release, containing Velocity Trails and Thermal Map, is `0.5.0` after
Stage 10.

Human-facing application UI derives a display version from the canonical value
by showing only `x.y`: `0.4.0`, `0.4.1`, and `0.4.2` display as `0.4`, while
`0.5.0` displays as `0.5`. Display version is never stored independently.

Release milestones are:

| Completed through | Version | Runtime milestone |
| :--- | :--- | :--- |
| Stage 4 | `0.2.0` | Telemetry and CPU fan motion. |
| Stage 5 | `0.3.0` | Full Server Runtime; last completed release. |
| Stage 7 | `0.4.0` | Engineering X-Ray; current release. |
| Stage 10 | `0.5.0` | Velocity Trails and Thermal Map. |
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
- derive every human-facing display version from the canonical major and minor
  components; never introduce an independently stored UI version;
- update package, extension, Kit application, runtime config, tests, and public
  documentation version metadata together when a milestone is released;
- release `1.0.0` only after Stage 17 also passes the end-to-end launch and demo
  smoke path, has current setup documentation, contains no critical known
  defects, and reports consistent version metadata.

Use stable runtime filenames such as
`digital_twin_runtime_suite.kit` and `digital_twin_runtime_suite.toml`. Keep the
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

Digital Twin Runtime Suite ships and launches as an Omniverse Kit application.

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
| Dedicated DTRS app launch | Stage 1 | Implemented |
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
| Cached simulation visual layer | Stage 6 | Implemented |
| Engineering X-Ray visual mode | Stage 7 | Implemented |
| Workload-to-cache state binding | Stage 8 | Implemented |
| Server velocity trail foundation | Stage 9 | Future |
| Server heatmap foundation | Stage 10 | Future |
| Server/rack/data hall navigation | Stage 11 | Future |
| Cross-scale camera bookmarks | Stage 11 | Future |
| Cross-scale scene group toggles | Stage 11 | Future |
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

Digital Twin Runtime Suite v0.1 is an asset preview slice. Its job is to prove
that the standalone Kit application can launch, read config, resolve the
hydrated asset package, open the configured Noctua NH-D9 TR5-SP6 USD asset, and
show reliable runtime status.

The canonical Case 03 stage is a later milestone. Full server, rack, and data
hall loading should not be treated as v0.1 scope. The plan keeps those targets
visible because they define where DTRS is going, but they become implementation
requirements only when the staged roadmap reaches them.

## Application Name Decision

The application is named **Digital Twin Runtime Suite**.

This name covers the whole staged path: the first Kit runtime, synthetic
telemetry, future workload/state switching, server/rack/data hall navigation,
optional external control surfaces, and eventual package-ready modules. The
project should not introduce separate public product names for early and late
stages, because that would create documentation drift without adding
engineering value.

## Runtime Implementation Decisions

The first staged build was **Digital Twin Runtime Suite v0.1**. The current
runtime build is **Digital Twin Runtime Suite v0.4.0**.

Fixed names and identifiers:

- Public app title: `Digital Twin Runtime Suite`
- Version: `0.4.0`
- Kit extension id: `msp.dtrs`
- Python package root: `digital_twin_runtime_suite`
- Runtime config: `configs/digital_twin_runtime_suite.toml`
- Application source root: `src/digital_twin_runtime_suite/`

The runtime config uses TOML. This matches Kit's own `.kit` and
`extension.toml` configuration style and allows comments. DTRS runtime code
must read it from Kit's Python environment when launched through `kit.exe`;
`case03-env` remains the development/tooling environment, not the runtime
Python environment for the Kit application.

For the current runtime, paths in runtime config are resolved from the
application source root
unless a later launch contract explicitly overrides that root. Because the
source root is `src/digital_twin_runtime_suite/`, the default hydrated asset
root is expected to resolve to `../../assets/_external/` from that root.

The first asset catalog entry is:

- Asset id: `noctua_nh_d9_tr5_sp6`
- Label: `Noctua NH-D9 TR5-SP6`
- Path under asset root: `usd/cpu_fan/cpu_fan.usd`
- Kind: `usd_stage`

Heavy USD, texture, HDRI, and temporal VTI payloads stay under
`assets/_external/`. They must not be copied into
`src/digital_twin_runtime_suite/`. The application code may keep a lightweight
asset catalog, but that catalog only records ids, labels, relative paths, and
metadata.

The v0.1 source tree should not introduce separate `viewport/`, `stage/`, or
`view/` packages. Stage opening and viewport-facing commands can live in
`app/commands.py` until the code proves that a separate module is needed.

The first extension source should live under the application package tree:

```text
src/digital_twin_runtime_suite/ext/msp.dtrs/
```

That folder is treated as a Kit extension folder by pointing Kit at
`src/digital_twin_runtime_suite/ext` as an extension search path. The extension
itself owns its `config/extension.toml`, docs, and Python module files.

A locally generated Kit App Template may remain a local read-only
reference/build workflow example only. Digital Twin Runtime Suite should be
developed as its own standalone application code path, with its own app config,
extension id, runtime config, and launch story.

The dedicated DTRS `.kit` application config must add
`src/digital_twin_runtime_suite/ext` as an extension search path and must enable
`msp.dtrs`. If the extension imports shared application modules from
`src/digital_twin_runtime_suite/`, the app config or extension startup code must
make that package importable in Kit's Python environment.

Digital Twin Runtime Suite v0.1 should launch directly through Kit with its own
application `.kit` file:

```text
kit.exe <path-to-digital-twin-runtime-suite-app>.kit
```

`repo.bat launch` may remain useful inside a generated Kit App Template during
development, but the public launch contract should be the standalone DTRS app
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

1. Launch Digital Twin Runtime Suite.
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
configuration to launch DTRS, resolve the hydrated asset package, load the
configured review stage, configure look-review controls, and connect the
synthetic telemetry and config-backed motion bindings.

The config file is:

```text
configs/digital_twin_runtime_suite.toml
```

Minimum runtime fields:

- `app.name`: `Digital Twin Runtime Suite`
- `app.version`: `0.4.0`
- `paths.app_root`: `src/digital_twin_runtime_suite`
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

The application should be built in small slices that keep Digital Twin Runtime Suite runnable after each step. Each stage carries its own completion rule; no
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
| Stage 1 - Asset Preview | `DC-40` | ✅ Complete | [Stage 1 details](case%2003%20-%20completed%20runtime%20stage%20plans.md#stage-1---digital-twin-runtime-suite-v01-asset-preview-slice) |
| Stage 2 - Look Review | `DC-41` | ✅ Complete | [Stage 2 details](case%2003%20-%20completed%20runtime%20stage%20plans.md#stage-2---look-review-slice) |
| Stage 3 - Synthetic Telemetry | `DC-42` | ✅ Complete | [Stage 3 details](case%2003%20-%20completed%20runtime%20stage%20plans.md#stage-3---synthetic-telemetry-slice) |
| Stage 4 - Telemetry Driven Motion | `DC-43` | ✅ Complete | [Stage 4 details](case%2003%20-%20completed%20runtime%20stage%20plans.md#stage-4---telemetry-driven-motion-slice) |
| Stage 5 - Server Review | `DC-44` | ✅ Complete | [Stage 5 details](case%2003%20-%20completed%20runtime%20stage%20plans.md#stage-5---server-review-slice) |
| Stage 6 - Cached Simulation Playback | `DC-45` | ✅ Complete | [Stage 6 details](case%2003%20-%20completed%20runtime%20stage%20plans.md#stage-6---cached-simulation-playback-slice) |
| Stage 7 - Engineering X-Ray | `DC-48` | ✅ Complete | [Stage 7 details](case%2003%20-%20completed%20runtime%20stage%20plans.md#stage-7---engineering-x-ray-visual-mode-slice) |
| Stage 8 - Workload-to-Cache State Binding | `DC-46` | ✅ Complete | [Stage 8 details](case%2003%20-%20completed%20runtime%20stage%20plans.md#stage-8---workload-to-cache-state-binding-slice) |

When a runtime stage is completed, move its detailed plan from this document to
the completed-stage archive, update this table with a direct link, and keep only
the active and future stage details here. Cross-stage contracts that still
govern future work remain in this plan.


### Stage 9 - Server Velocity Trail Foundation Slice

Checkpoint preflight: before implementation, verify the preceding stage ends
at a Git checkpoint commit. If it does not, create that checkpoint before
starting this stage.

Jira: `DC-49`

Target release milestone: `0.5.0` (not released; assigned after Stage 10 completion).

Deliver a reusable Kit-CAE Streamlines subsystem at `Server` scale. It must
consume the same manifest-backed Houdini airflow datasets as Stages 6--8,
without duplicating VTI discovery, spatial registration, or workload identity.
The result is an engineering visualisation of the active velocity field, not a
second smoke implementation and not a custom streamline integrator.

The first proof must run from a clean DTRS startup state and must not require
the existing full airflow Attach workflow. Attach currently imports and authors
the complete temporal sequence before creating Flow objects; that remains the
right workflow for smoke, but it is intentionally too large for the initial
Streamlines proof.

#### Scope and semantic boundary

- Streamlines are **instantaneous streamlines derived from the active
  Houdini-authored velocity field**. They are not particles or pathlines moving
  through a transient simulation.
- An optional animated-streak material may improve directional readability over
  already-generated `BasisCurves`; it must never be presented as a particle
  simulation or as interpolated vector data.
- Do not write a custom streamline integrator. Use the Kit-CAE Streamlines
  operator after the VTI source and spatial contract have been validated.
- Preserve the current Stage 6 Flow Attach behaviour while extracting shared
  source preparation. Do not migrate the working Flow path merely to introduce
  Streamlines.
- Rack and Data Hall streamlines, a user-facing timeline/frame selector, and
  artificial intermediate velocity fields are out of scope.

#### Code-readability checkpoints

New Streamlines code must follow the established `app/flow` readability
pattern: document module responsibility, public runtime entry points,
plain-data contracts, lifecycle/state transitions, and non-obvious Kit-CAE
constraints at the point of implementation. Comments explain engineering
intent and invariants, not obvious Python syntax.

Apply the project code-readability review at these checkpoints:

1. **Every runtime change set:** before adding or refactoring implementation
   code, apply the review to identify its owner, public contract, and lifecycle
   boundary.
2. **Every contract or lifecycle seam:** when changing airflow-source data,
   asynchronous state, Kit-CAE authoring, cleanup, or a visualization-mode
   invariant, apply the review and document the non-obvious reason locally.
3. **Each phase gate:** before accepting the Phase 1 static proof, Phase 2
   temporal feasibility result, Phase 2.5 cache decision, Phase 2.75 runtime
   decomposition, Phase 3 shared-source refactor, or Phase 4 production mode,
   apply the review by rereading the changed surface as a first-time technical
   reader and filling only real explanatory gaps.

The runtime source contract remains:

```text
telemetry workload
    -> Stage 8 workload-to-dataset binding
    -> manifest-backed server/load_* dataset
    -> Houdini VTI velocity field
    -> /DTRS_HoudiniVelocity/VTKImageData
    -> /DTRS_HoudiniVelocity/PointData/<configured velocity field; currently vel>
```

The implementation must use the API provided by the selected DTRS Kit-CAE
build:

```python
from omni.cae.data.commands import execute_command
from omni.cae.schema import viz as cae_viz
```

`CreateCaeVizStreamlines` receives the imported dataset path and creates the
operator at a DTRS-owned path. A DTRS-owned UnitSphere seed source is then
created and related to the operator; creating the operator alone is not a
valid visual proof.

#### Phase 1 - Static source and operator proof

1. ✅ Add only the responsibilities that are immediately needed under
   `app/streamlines/`: runtime ownership and Kit-CAE authoring. Do not create
   empty diagnostics, validation, or performance modules before they have an
   owner. Add the `StreamlinesRuntimeMixin` to `RuntimeController` alongside
   the existing runtime mixins.
2. ✅ Add a collapsed `Streamlines` section in the Airflow Cache UI with one
   initial diagnostic action, `Run Static Test`, and a clear status. The action
   is available only from a clean, non-attached airflow state; if Flow Attach
   is active it is disabled or explains why it cannot run.
3. ✅ Extract a narrow source helper beside the existing Flow code, for example
   `prepare_static_velocity_sample_in_kit(sample_index=0)`. It resolves the
   current telemetry workload through the Stage 8 binding, validates the
   manifest-selected VTI, imports exactly that one sample, applies the proven
   origin correction, and returns a plain descriptor containing workload,
   dataset identity, sample index, VTI path, dataset path, velocity-field path,
   bounds, dimensions, spacing, and origin. This is source preparation, not a
   partial Flow attach.
4. ✅ Sample `0` is the deterministic initial test input. Re-running the test for
   the same workload must select the same VTI; changing workload selects the
   corresponding dataset's sample `0`.
5. ✅ Reuse the existing VTI checks before authoring Streamlines: configured
   velocity field (currently `vel`), dimensions, spacing, VTI origin, imported
   origin, world bounds, and stage units. Reuse the accepted session-layer VTI
   origin compatibility shim; upstream investigation of importer origin loss
   remains separate technical debt. The first phase gate is that the imported
   VTI is a correct spatial velocity source while no Flow environment, emitter,
   injector, or temporal loop exists.
6. ✅ Create one Streamlines operator beneath `/DTRS_KitCAE/Streamlines` through
   `CreateCaeVizStreamlines`, and a small diagnostic UnitSphere beneath
   `/DTRS_KitCAE/StreamlineSeeds`. Bind the configured vector-valued velocity
   field (currently `vel`) directly, set a known direction, and verify generated
   `BasisCurves` both visually and through diagnostics. The line must be in the
   expected region and direction, remain inside the credible airflow domain,
   and show no axis or scale error. Stage 7 documents that
   `/app/useFabricSceneDelegate=true` breaks Engineering X-Ray viewport rollback,
   so FSD remains disabled. For this Package B human gate, hide the command's
   authored four-point fallback and author a short-lived DTRS-owned
   `RuntimePreview` `BasisCurves` snapshot from the accepted UsdRT points and
   curve counts. It is a diagnostic presentation bridge for the normal USD
   viewport, not a second operator, custom integrator, or new airflow source;
   proof cleanup removes it with the Streamlines runtime roots.
7. ✅ Run a controlled `standard` versus `nanovdb` comparison using the identical
   VTI, seed, and integration settings. Record creation/rebuild duration,
   curve and point count, viewport FPS, visual quality, stability, and memory
   pressure. Choose one production type; do not support both without an
   evidenced reason.

   Package C procedure: retain the accepted Package B setup exactly
   (`Nominal`, sample `0`, `server_airflow_velocity_normal_1001.vti`, `vel`,
   seed transform, direction, integration settings, width, camera/viewport,
   FSD=false, and the RuntimePreview bridge), changing only `operator_type`.
   Run one warm-up plus three measured executions per type; use medians for
   rebuild, preview-mirror, total-visible-update, FPS, and available Kit/RTX
   memory evidence. Each warm-up and measured execution must have its own
   causally matched Kit-CAE begin/end completion receipt; real UsdRT geometry
   is necessary evidence but is not a substitute for that receipt. Log NanoVDB
   voxelization time only if it is separately observable. NanoVDB's effective
   uniform voxel size must be no coarser than the imported VTI spacing; log its
   effective dimensions and voxel size rather than only the requested setting.
   Do not tune a separate ROI or lower-fidelity resolution merely to make it
   win. Recreate and clean the disposable comparison operator for the warm-up
   and for each measured run; never perturb the shared VTI, seed, velocity
   field, integration settings, or NanoVDB fidelity simply to make Kit dirty.
   Treat steady FPS as a post-operation recovery/sanity metric rather than the
   primary `standard`/`nanovdb` discriminator: under FSD=false both paths are
   displayed through equivalent RuntimePreview geometry. After each final
   visible preview becomes stable, wait 5 seconds, then reuse the Flow
   performance snapshot source for 5 snapshots at 5-second intervals. Log
   `fps_snapshots`, FPS median/min/max, GPU-memory snapshots, and process-memory
   snapshots; never derive evidence from repeated adjacent `next_update()`
   frame-time reads. Leave either measured preview selectable under the unchanged viewport
   for visual review.

   **Package C decision — accepted:** `standard` is the sole production
   Streamlines operator. Under the fixed Package B setup, standard rebuilt in
   median **63 ms** versus NanoVDB **94 ms**; steady viewport FPS medians were
   **49.8** versus **48.9**; GPU memory was **4.0 GiB** versus **4.1 GiB**.
   Both produced **256 curves / 51,200 points**, and human review found no
   material NanoVDB visual-quality, stability, or artifact advantage. NanoVDB
   remains only in the Package C comparison/integration harness as regression
   evidence; no production runtime path may retain it.
8. ✅ Make the static action idempotent. Before a new run, clean the preceding
   Streamlines operator, seed source, and static imported dataset from every
   layer to which the importer or command authored them. The same cleanup must
   run on reload, stage reopen, and shutdown.

   **Package D acceptance — passed:** canonical cleanup passed on rerun and
   after a deterministic post-import failure rollback; the recovery run, Reload
   Config path, stage reopen path, and pre-shutdown cleanup all passed. A full
   DTRS restart then passed clean-startup verification, a new static run and
   cleanup, and a second idempotent cleanup. Every receipt reported
   `stale_relationships=0`, `remaining_layer_specs=0`, `duplicate_prims=0`,
   and `pending_tasks=0`. The production operator decision remains
   `standard`; NanoVDB is retained only in the regression comparison harness.

**Code-readability checkpoint -- ✅ passed before the Phase 1 gate:** Reviewed
the new `app/streamlines/` ownership boundary, static-source descriptor,
Kit-CAE authoring path, and cleanup behaviour. A first-time reader can follow
why this proof neither creates nor requires Flow, why cleanup spans session and
root layers, and why the post-restart handoff uses a persistent Kit setting.

**Phase 1 gate — ✅ passed:** From clean startup, one validated Houdini VTI
produces correctly placed Kit-CAE Streamlines, with no Flow objects and no
duplicate runtime prims after repeated run/cleanup cycles. The Package D
in-process lifecycle matrix and full post-restart check also verified clean
rollback, reload, stage reopen, shutdown, and second-cleanup idempotence.

#### Phase 2 - Temporal feasibility

1. ✅ Extend the static helper into a minimal no-Flow temporal probe path. It must
   prepare the real manifest-selected VTI source and use the same temporal
   field-relation/timecode mechanism intended for DTRS, but it creates neither
   a Flow environment nor emitters and does not move Stage 8 transition
   ownership. Minimal means minimal consumer and state ownership, not an
   artificial VTI or an unrelated reimport path.
2. ✅ Add `Run Temporal Probe` only after this narrow helper exists. For the active
   workload it derives a representative deterministic sequence from that
   dataset's manifest-defined sample count and cadence: first sample, early
   samples, approximately 25% and 50% phase, final sample, then the first
   sample again. Deduplicate indices for short sequences. Wait for the
   DTRS-owned Kit-CAE operator tracker and record selected VTI, sample index,
   operator start/end, rebuild duration, geometry replacement, curve/point
   count, and a viewport-recovery observation. Package E does not interpret
   FPS or rebuild timings as a cadence result; that measurement belongs to
   Package F.

   **Package E evidence — accepted:** the manifest temporal source passed with
   the deterministic sequence `0 → 1 → 2 → 20 → 40 → 79 → 0`. Exact VTI
   selection passed for all 7 samples; all 7/7 standard Streamlines consumer
   recreations produced fresh successful Kit-CAE executions and confirmed UsdRT
   geometry replacements. The final-to-first boundary passed and the returned
   first-sample geometry was consistent with the initial result. Flow,
   emitters, and smoke remained absent; canonical cleanup was clean. The
   installed consumer therefore refreshes explicitly at each selected source
   boundary. Per-sample rebuild timings are retained as Package F evidence only;
   they do not yet support a cadence conclusion. Production operator remains
   `standard`.
3. ✅ Treat the selected Kit-CAE Streamlines operator as non-temporal until an
   installed-build experiment proves otherwise. Measure its cost at real source
   boundaries, repeated samples, and the intended 5 Hz source cadence. Do not
   promise 5 Hz production updates, build production UI, or add synthetic
   intermediate vectors before this measurement.

   **Package F evidence — accepted measurement, classification B:** the source
   cadence is 5 Hz / 200 ms. On the frozen Package E path, sequential boundaries
   measured median `source_transition=31 ms`, `operator_rebuild=1204 ms`,
   `UsdRT_ready=1437 ms`, `RuntimePreview_update=1125 ms`, and
   `total_visible_update=2547 ms`. Repeating one sample measured a median
   `total_visible_update=1562 ms`. The 5 Hz burst processed all 10/10 requested
   samples correctly, but missed all 10 deadlines, reached queue depth 8, and
   accumulated median/max completion lateness of `8044/18512 ms`. The final to
   first boundary, geometry correctness, and canonical cleanup all passed.
   Baseline/during/recovery FPS medians were `48.4/7.0/41.7`; recovery did not
   reach 90% of baseline in the observed window. Therefore temporal Streamlines
   are functionally stable, but 5 Hz visible presentation is not viable with
   explicit consumer rebuild plus the FSD-safe RuntimePreview bridge. No
   optimisation or cadence reduction was applied in Package F; `standard`
   remains the production operator and Package G owns the time-based
   presentation decision.
4. ✅ Define the maximum practical time-based presentation cadence from the evidence.
   Treat source cadence and Streamlines presentation cadence as separate clocks:
   each workload dataset retains its own manifest-defined sample count and source
   cadence, while Streamlines presentation is scheduled by a runtime presentation
   period in seconds against the shared 16-second loop phase.

   If every source boundary is viable, retain the dataset cadence. Otherwise,
   measure and select the minimum practical `presentation_period_seconds`
   independently of dataset sample count. At each presentation tick, resolve the
   latest real manifest sample whose source time is at or before the current loop
   phase, preserving the exact selected sample index, source time, timecode, and
   VTI identity. Do not interpolate, average, or synthesize intermediate velocity
   vectors.

   If a presentation tick resolves to the same source sample that is already
   presented, treat it as a no-op rather than rebuilding the Streamlines consumer.
   Validate the selected period across loop wrap and demonstrate that it does not
   accumulate queue depth or timing drift during sustained operation.

   If no credible time-based presentation period is viable, stop before the
   shared-source refactor and reassess Stage 09 scope.

   **Package G evidence — accepted:**

   ```text
   decision=TIME_BASED_PRESENTATION_VIABLE
   presentation_period_seconds=2.6
   presentation_cadence_hz=0.384615
   loop_duration_seconds=16

   source_cadence=manifest-defined per workload
   source_resolution=latest sample at or before loop phase
   same_source_sample=NO_OP
   interpolation=NONE

   sustained_confirmation:
     measured_ticks=12
     rebuilt_ticks=11
     no_op_ticks=1
     missed_deadlines=0
     max_pending_requests=0
     visible_update_ms_median_max=(1906, 2031)
     headroom_ms_median_min=(694, 569)
     loop_wrap=PASS
     exact_mapping=PASS
     cleanup=CLEAN

   fps:
     baseline=50.9
     sustained=14.6
     recovered=53.0
     recovery_to_90_percent_seconds=5
   ```

**Code-readability checkpoint — ✅ passed before the Phase 2 gate:** Reviewed
the temporal source-time resolver, explicit consumer-rebuild boundary,
same-source no-op decision, bounded scheduler, candidate state transitions,
and cleanup ownership. The fixed 16-second loop and the separation of
manifest-defined source time from time-based presentation are explicit at the
relevant runtime boundaries.

**Phase 2 gate — ✅ passed:** DTRS has measured the real server Streamlines
behaviour on RTX 3080. The source clock remains manifest-defined per workload;
the selected, defensible presentation clock is 2.6 seconds (0.384615 Hz)
against the fixed 16-second loop. Exact mapping, loop wrap, no-op handling,
sustained scheduling headroom, recovery, and cleanup are proven before any
change to Flow or Stage 8 ownership.

#### Phase 2.5 - Precomputed Streamlines cache feasibility — ✅ passed

Purpose: determine whether deterministic Kit-CAE Streamlines geometry can be
precomputed once from the manifest-defined temporal VTI dataset, persisted as a
derived visualization cache, and replayed substantially faster than runtime
Streamlines recomputation. This is a bounded feasibility experiment; Phase 2
runtime recomputation remains the proven fallback while cache production
parameters are refined later.

1. ✅ Establish the cache contract. Treat the VTI dataset as the authoritative
   simulation source and the Streamlines cache as a derived artifact. Preserve
   workload/dataset identity, manifest sample index, source time, USD timecode,
   source VTI identity, Streamlines settings/seed configuration identity, and
   generated curve topology/points for every cached state. Do not interpolate,
   average, synthesize velocity data, or invent source samples.

   Cache invalidation must at minimum distinguish changes to the source dataset
   or manifest, source VTI identity, Streamlines seed/settings, and cache
   schema/version.

2. ✅ Build one complete representative cache from the existing Nominal 80-sample
   dataset and the already-proven diagnostic Streamlines configuration. For each
   real manifest sample run `VTI sample -> Kit-CAE Streamlines -> confirmed
   UsdRT curves -> persistent cache`. Do not involve Flow, Smoke, Stage 8
   workload switching, or RuntimePreview unless it is required solely for
   validation. Record total build time, per-sample generation time, cache size
   on disk, topology consistency, and failed or non-deterministic samples. The
   cache is a build artifact and must not be recomputed during normal DTRS
   startup.

3. ✅ Prove restart persistence. Close and restart DTRS, then load the existing
   Streamlines cache without executing the Kit-CAE Streamlines operator for
   playback. Prove that every cached state resolves back to its exact manifest
   sample identity.

4. ✅ Prove temporal cached playback with the existing 16-second loop and the
   manifest source clock. For the current Nominal dataset this means the exact
   `80 samples / 16 s = 5 Hz` source sequence. At every source boundary display
   the corresponding precomputed state, preserving sample order, loop wrap, and
   phase semantics. Do not interpolate or execute runtime Streamlines
   recomputation. Measure cached-state visible latency, sustained FPS, deadline
   misses, timing drift, RAM, GPU/process memory, startup/load cost, and loop
   consistency.

5. ✅ Compare against the proven Phase 2 baseline:
   `presentation_period_seconds=2.6`. Cache feasibility succeeds only if
   playback is materially cheaper and sustains the current 5 Hz source cadence
   without backlog or timing drift. Record whether measured cache-state latency
   leaves credible headroom for a future 10-12 Hz source cadence; do not create
   higher-cadence VTI datasets during this phase.

6. ✅ Make an explicit Phase 2.5 decision before Phase 3 begins:

   - `CACHE_PLAYBACK_VIABLE`: retain the Phase 2 runtime-recompute path as the
     proven fallback; select precomputed Streamlines cache as the preferred
     production direction; update Phase 3 architecture before implementing the
     shared airflow source; and defer production seed/layout tuning plus full
     four-workload cache generation to the appropriate later phase.
   - `CACHE_PLAYBACK_NOT_VIABLE`: means that exact cached playback at the full
     5 Hz source cadence is not viable. Preserve the Phase 2 2.6-second
     runtime-recompute contract as proven fallback, retain the precomputed
     cache architecture as the preferred production direction, and stop
     density-reduction R&D in this phase.

**Phase 2.5 conclusion — accepted:** `CACHE_PLAYBACK_NOT_VIABLE` rejects the
full manifest source-boundary playback hypothesis on the current RTX 3080 path;
it does not reject the precomputed Streamlines cache architecture.

- The 256-curve cache measured cached switch-latency median `891 ms`.
- The 128-curve diagnostic cache measured cached switch-latency median
  `469 ms`. Geometry-density scaling was strong and approximately
  proportional, but 5 Hz / 200 ms playback remained `NOT_VIABLE`.
- The 128-curve probe preserved exact manifest mapping, loop wrap, persistent
  cache playback after restart, zero runtime Kit-CAE Streamlines executions,
  and zero RuntimePreview rebuilds.
- Further density reduction is rejected: the predicted density required for
  credible 5 Hz playback would materially compromise diagnostic Streamlines
  readability without credible worst-case 5 Hz headroom.
- The precomputed cache remains the preferred production direction because it
  removes repeated Kit-CAE Streamlines computation from runtime and makes
  geometry updates substantially cheaper than the accepted 2.6-second
  runtime-recompute path. Phase 2 recomputation remains fallback evidence only.
- Do not freeze 128 curves or a cached presentation period as production
  values. They are Phase 2.5 evidence, not the final production configuration.

**Code-readability checkpoint — ✅ passed before the Phase 2.5 gate:** Review
the cache identity and invalidation contract, the authoritative-versus-derived
data boundary, persistent cache ownership, restart lifecycle, and the guarantee
that playback never silently recomputes Streamlines.

**Phase 2.5 gate — ✅ passed:** the full 5 Hz cached source-boundary playback
hypothesis is rejected; the precomputed cache architecture is retained as the
preferred production direction, and runtime Streamlines recomputation remains
the Phase 2 fallback. Do not perform further density-reduction R&D in Phase
2.5.

#### Phase 2.75 - Streamlines runtime decomposition — ✅ passed

Purpose: refactor the now-large `app/streamlines/runtime.py` only after Phase
2.5 establishes which production architecture survives. Drive the decomposition
from that decision rather than speculative module boundaries.

1. ✅ Begin only after Phase 2.5 records an explicit cache-playback decision, and
   preserve every accepted Phase 1/2 contract and evidence. Preserve the proven
   2.6-second runtime-recompute path as fallback unless Phase 2.5 evidence
   explicitly makes it unnecessary.
2. ✅ Use the retained precomputed-cache architecture when defining production and
   cache ownership boundaries. Keep the rejected full-5-Hz acceptance harness
   distinct from production cache behaviour, and retain Phase 2 runtime
   recomputation as fallback evidence.
3. ✅ Keep `StreamlinesRuntimeMixin` and `RuntimeController` public behaviour
   stable unless evidence requires a contract change. Do not combine the
   refactor with visual features, seed tuning, AnimatedStreaks, workload-mode
   implementation, or Phase 3 shared-source work.
4. ✅ Prefer modules based on responsibilities actually discovered by Phase 2.5;
   do not prescribe empty modules in advance. Preserve lifecycle cleanup,
   Kit-CAE execution receipts, time/source mapping, logging semantics, and
   focused tests.
5. ✅ Run the Code Readability review after the decomposition.

**Phase 2.75 gate — ✅ passed:** A first-time technical reader can distinguish
the production Streamlines runtime; cache build/playback ownership if accepted;
the runtime-recompute fallback; diagnostic/acceptance harnesses; and
lifecycle/cleanup ownership without tracing a monolithic ~5k-line runtime
module. All focused tests must remain green, and the accepted Phase 2.5 path
must still pass its relevant Kit acceptance after the refactor.

Do not begin Phase 3 until Phase 2.75 closes.

#### Phase 3 - Shared airflow source architecture

1. Only after Phase 2.75 closes, separate the airflow source lifecycle from the
   Flow consumer. The consumer-neutral source layer owns
   manifest discovery,
   validation, VTI import, temporal sample authoring, origin/grid validation,
   source identity, normalized phase mapping, pending target, source-commit
   verification, supersession, and failure rollback.
2. Flow, smoke, and Streamlines become consumers of the prepared source. The
   intended Streamlines production route is `Houdini-authored temporal VTI ->
   offline/precomputed Kit-CAE Streamlines cache -> runtime cached geometry
   playback`, rather than per-presentation Kit-CAE recomputation. Keep the
   current Stage 6 Attach workflow visually and functionally unchanged, with
   focused regression tests for that guarantee.
3. Move the generic parts of the Stage 8 workload transition contract into the
   shared source layer. Replace Flow-specific `Field + DataSetEmitter required`
   proof with `source transition committed -> active consumer validates result`.
   Do not count Flow `DataSetEmitter` consumption as evidence that Streamlines
   consumed a new source.
4. Establish concise consumer proofs for both paths: the Flow consumer retains
   its current behaviour, while the Streamlines consumer reports selected VTI,
   operator completion, generated geometry, and confirmed workload identity.

**Code-readability checkpoint -- apply before the Phase 3 gate:** Review the
consumer-neutral source contract, commit/rollback and supersession rules, and
the explicit ownership boundary between the shared source, Flow, and
Streamlines. A reader must be able to see why the existing Attach path remains
unchanged.

**Phase 3 gate:** Workload switching is owned by the shared airflow source,
not by Flow, and both Flow and Streamlines prove consumption without a
regression to the existing Attach workflow. Phase 3 determines practical cache
parameters: cached Streamlines presentation cadence, production geometry
density, seed/layout/integration settings, workload-aware cache behaviour, and
interaction with the shared airflow-source architecture; it does not inherit
128 curves or a specific cached presentation period as a frozen value.

#### Phase 4 - Production modes and acceptance

1. Introduce the DTRS-owned Airflow Visualization Mode state: `Smoke`,
   `Streamlines`, and, if necessary internally, `Off`. Enforce the product
   invariant in the runtime controller, not only in the UI: smoke and
   Streamlines must never be active together.
2. Preserve the familiar Attach workflow: it prepares the temporal dataset and
   activates Smoke by default. A mode switch is not Attach/Detach and must
   preserve `/DTRS_HoudiniVelocity`. Implement both switch directions with
   Flow quiescence, source preservation, stale-presentation cleanup, and
   completed-operator confirmation.
3. Build one deterministic, configuration-backed `Front Intake` seed preset
   before considering additional semantic groups. Tune in this order: seed
   placement, direction, integration step sizes, maximum steps/length, seed
   density, then width. Add GPU, CPU, PSU, or interior seed groups only when
   the primary preset cannot explain the server airflow clearly.
4. After real operator properties have been measured, add
   `StreamlinesConfig` and `[simulation_cache.streamlines]`. Its production
   contract includes operator type, direction, integration limits, width, seed
   preset, colour domain/mode, and optional animated-streak setting. Values are
   evidence-derived, not speculative defaults.
5. Colour production streamlines from the imported velocity data with one fixed
   cross-workload domain. Explicitly prevent the operator's automatic rescale
   path from redefining that domain during rebuild. The same colour must retain
   the same physical meaning across Idle, Nominal, Surge, and Critical.
6. Verify all four workload transitions in Streamlines mode without a new
   Attach or whole-dataset reimport. Each transition must prove: target accepted,
   selected VTI committed, Streamlines operator completed, new geometry exists,
   consumer state names the new workload, and Smoke remains inactive. On failure
   keep the last confirmed visualisation understandable and report the reason.
7. Replace temporary static/probe controls with production controls only after
   the preceding gates pass. The final Airflow UI exposes the selected mode and
   only the measured Streamlines settings; retain diagnostic actions only when
   they remain useful and clearly labelled as diagnostics.
8. Consider `AnimatedStreaks` only after static geometry, temporal cadence, and
   mode switching are accepted. Confirm that its material and timeline behaviour
   does not cause a geometry rebuild on render ticks. If that isolation is not
   achieved, Stage 09 ships `ScalarColor` Streamlines; no custom animation
   system is introduced to compensate.
9. Run the full lifecycle matrix: startup/static test/cleanup, Attach/Smoke,
   both mode-switch directions, workload switch while Streamlines are active,
   play/pause/reset, Detach/re-Attach, config reload, stage reopen, shutdown,
   and DTRS restart. Verify no duplicate operators or seeds, stale curves or
   smoke, invalid source relations, surviving runtime prims, or leaked tasks.
10. Validate Streamlines alone and with the Stage 7 Engineering X-Ray modes:
    chassis, GPU shrouds, and relevant group combinations. Assess readability,
    depth/occlusion, width, colour competition, flicker/ghosting, and FPS.
11. Record RTX 3080 evidence at fixed camera conditions for server baseline,
    Smoke, Streamlines ScalarColor, accepted AnimatedStreaks if any, X-Ray, and
    X-Ray plus Streamlines. Record viewport FPS, Streamlines rebuild duration,
    workload-switch visual latency, curve/point count, and visible artifacts.
12. Add focused automated tests for DTRS-owned logic: config parsing and
    validation, static/temporal source requests, sample-index checks,
    deterministic seeds, mode-state transitions and XOR enforcement,
    duplicate-create prevention, cleanup idempotence, workload commit/failure,
    fixed colour-domain policy, and reload/shutdown reset. Kit-CAE geometry
    remains a DTRS/Kit integration acceptance check.
13. Update public documentation with the correct physical claim:
   "DTRS visualizes instantaneous streamlines derived from the active
   Houdini-authored temporal velocity field, with workload-aware dataset
   switching and optional animated-streak presentation for directional
   readability."
14. Before closing Stage 09 / `DC-49`, set
    `STAGE09_SUPPRESS_AIRFLOW_DIAGNOSTICS = False` and restore exactly these
    temporarily suppressed Airflow diagnostics: successful
    `DTRS AIRFLOW DATASET REGISTRY` startup output,
    `DTRS WORKLOAD CACHE MAPPING` output, and the
    `DTRS AIRFLOW BACKGROUND VALIDATION` startup task with its normal log
    output. Error reporting remains enabled throughout Stage 09. Verify that
    the restored diagnostics do not interfere with the accepted Streamlines
    lifecycle or diagnostic evidence, and record the restoration in the Stage
    09 acceptance evidence. This is a closure condition, not optional cleanup.

**Code-readability checkpoint -- apply before Stage 09 acceptance:** Review
the visualization-mode state machine and its Smoke XOR Streamlines invariant,
the mode-switch teardown/preservation paths, workload-transition reporting,
and the UI-facing presentation contract. Confirm that success, failure, and
shutdown can be understood without unstated runtime knowledge.

Done when DTRS can prepare and validate Houdini-authored server airflow
velocity data independently of NVIDIA Flow, visualise the active field through
a reusable Kit-CAE Streamlines subsystem, and reuse the same manifest-backed
temporal dataset across mutually exclusive Smoke and Streamlines modes. The
accepted implementation preserves correct spatial and source-time mapping,
recomputes through Stage 8 workload transitions at its measured presentation
cadence, uses reproducible server-scale seeding and fixed physical colour
meaning, composes with Engineering X-Ray, and survives mode switching, detach,
reload, and shutdown within the accepted RTX 3080 runtime budget. Stage 09
cannot close while `STAGE09_SUPPRESS_AIRFLOW_DIAGNOSTICS` remains enabled.

### Stage 10 - Server Heatmap Foundation Slice

Checkpoint preflight: before implementation, verify the preceding stage ends
at a Git checkpoint commit. If it does not, create that checkpoint before
starting this stage.

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

Checkpoint preflight: before implementation, verify the preceding stage ends
at a Git checkpoint commit. If it does not, create that checkpoint before
starting this stage.

Jira: `DC-47`

Release track: `0.6.0` (released on Stage 12 completion).

Add deliberate navigation between supported scales: server, rack, and data
hall. The exact cross-scale camera bookmarks and scene group controls are deferred until
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

Checkpoint preflight: before implementation, verify the preceding stage ends
at a Git checkpoint commit. If it does not, create that checkpoint before
starting this stage.

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

Checkpoint preflight: before implementation, verify the preceding stage ends
at a Git checkpoint commit. If it does not, create that checkpoint before
starting this stage.

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

Checkpoint preflight: before implementation, verify the preceding stage ends
at a Git checkpoint commit. If it does not, create that checkpoint before
starting this stage.

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

Checkpoint preflight: before implementation, verify the preceding stage ends
at a Git checkpoint commit. If it does not, create that checkpoint before
starting this stage.

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

Checkpoint preflight: before implementation, verify the preceding stage ends
at a Git checkpoint commit. If it does not, create that checkpoint before
starting this stage.

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

Checkpoint preflight: before implementation, verify the preceding stage ends
at a Git checkpoint commit. If it does not, create that checkpoint before
starting this stage.

Jira: `DC-57`

Release track: `1.0.0` (released after Stage 17 and the `1.0.0` release gate).

After the Stage 1-16 feature set is available, refine the operator workflow and
consolidate the final DTRS interface. Stage 11 owns the scale-navigation commands
and stable server, rack, and data-hall views; Stage 17 owns their final UI
placement, interaction design, and presentation polish.

Required scope:

- review and settle the information architecture of the fixed left sidebar,
  starting from the existing `Telemetry`, `View`, and `Config` tabs;
- place a global, mutually exclusive `Server | Rack | Data Hall` scale control
  outside the contextual sidebar, with the viewport toolbar as the current
  preferred location;
- expose a chassis presentation controller with `Open` and `Closed` modes
  using reversible session-layer visibility overrides;
  decide then whether the SilverStone RM44 rack ears remain visible when the
  side panels are open;
- keep the active scale visible and consolidate or remove duplicated controls;
- review the remaining camera, scene, lighting, telemetry, status, visual-layer,
  scenario, and runtime controls after their delivery stages are complete;
- design and implement a user-facing runtime feedback pattern for asynchronous
  commands that can fail, beginning with airflow attach: distinguish progress,
  actionable error, recoverable warning, and success without requiring an
  operator to inspect a Python traceback or Kit log; decide the final visual
  form, placement, and persistence during the Stage 17 UI design pass;
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
  narrow Stage 5 DTRS preflight contract.
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

- Which cross-scale camera bookmarks define the first presentation path?
- Which cross-scale scene groups need first-class visibility toggles?
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
