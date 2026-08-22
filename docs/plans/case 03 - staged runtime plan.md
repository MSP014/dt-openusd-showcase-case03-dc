# Case 03 - Staged Runtime Plan

**Status**: Active roadmap; Stages 1–9 complete; Stage 10 next
**Last Updated**: 2026-08-20

This document records the working plan for a staged review/runtime application
around the Case 03 OpenUSD scene.

---

## Application integration invariant

All subsequent Case 03 work must preserve the repository-level Kit extension
boundaries defined in
[Application Boundaries](../architecture/application_boundaries.md).

`extension.py` remains a thin lifecycle/composition root; new feature
orchestration, acceptance workflows, and domain/runtime logic must not
accumulate there.

---

## Current State

Case 03 currently has the authored Houdini/OpenUSD asset pipeline, hydrated
external asset layout, and the first nine completed Digital Twin Runtime Suite
slices through cached Streamlines velocity presentation and Streamlines + X-Ray.

Current decisions already made:

- The public application name is **Digital Twin Runtime Suite**.
- The first build was **Digital Twin Runtime Suite v0.1**.
- The current runtime build is **Digital Twin Runtime Suite v0.4.0**, released
  with Stage 7. Stages 8 and 9 have no separate release bump; the next feature
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
- Stage 9 delivers server-scale cached Streamlines velocity presentation,
  workload/profile switching, velocity material settings, and independent
  Streamlines + X-Ray composition without runtime Streamlines recompute. Its
  completed contract and evidence are preserved in the [Stage 9 archive](case%2003%20-%20completed%20runtime%20stage%20plans.md#stage-9---server-velocity-trail-foundation-slice).
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
- Completed implementation task: `DC-49` - Stage 9 Server Velocity Trail
  Foundation Slice.
- Next planned implementation task: `DC-50` - Stage 10 Server Heatmap
  Foundation Slice.
- When a delivery stage is completed, update the matching Jira task before
  moving to the next stage: add a concise completion comment, log the actual
  work time, move the task through Review to Done, run Jira sync, and mark the
  next stage task In Progress when work on that stage starts.

## Next Step

Stage 10, Server Heatmap Foundation, is the next planned implementation slice
(`DC-50` remains To Do). Stage 9, Server Velocity Trail Foundation, is complete
and archived with its evidence in the completed runtime-stage plans. Before
starting Stage 10, create the clean Stage 9 Git checkpoint required by the
Stage 10 preflight. Stage 10 must preserve the accepted Stage 6 Flow, Stage 7
X-Ray, Stage 8 workload-to-cache, and Stage 9 cached Streamlines contracts.

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
| Server velocity trail foundation | Stage 9 | Implemented |
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
| Stage 9 - Server Velocity Trail Foundation | `DC-49` | ✅ Complete | [Stage 9 details](case%2003%20-%20completed%20runtime%20stage%20plans.md#stage-9---server-velocity-trail-foundation-slice) |

When a runtime stage is completed, move its detailed plan from this document to
the completed-stage archive, update this table with a direct link, and keep only
the active and future stage details here. Cross-stage contracts that still
govern future work remain in this plan.



### Stage 10 - Server Heatmap Slice

Checkpoint preflight: before implementation, verify that Stage 9 ends at a
clean Git checkpoint commit. If it does not, create that checkpoint first.

Jira: `DC-50`

Release track: `0.5.0` (released on Stage 10 completion).


Prove a reusable telemetry-driven Heatmap against the full server at
single-server detail level before adding rack or data-hall scale.

Preparatory package structure has already been created to reserve the Heatmap
subsystem boundary before implementation begins.

Prepared runtime package:

`src/digital_twin_runtime_suite/app/heatmaps/`

- `__init__.py`
- `bindings.py`
- `diagnostics.py`
- `discovery.py`
- `material.py`
- `runtime.py`
- `scalar.py`

Prepared test package:

`tests/heatmaps/`

- `test_heatmap_bindings.py`
- `test_heatmap_discovery.py`
- `test_heatmap_runtime.py`
- `test_heatmap_scalar.py`

These files currently contain package/module placeholders and responsibility
descriptions only. They do not constitute Stage 10 implementation and may be
refined as the runtime architecture is proven. `__init__.py` is intentionally
left without a predefined public API.


#### Thermal contract

Use the thermal metadata already authored in Houdini and transported through
USD:

- `thermal_zone` - semantic thermal region;
- `thermal_component` - component role inside that region;
- `primvars:thermal_weight` - dimensionless authored spatial distribution from
  relatively colder to hotter areas;
- `primvars:temperature_preview` - optional Houdini authoring/debug data only.

`thermal_weight` is not temperature and must never be interpreted as degrees
Celsius. Runtime thermal values come from the existing DTRS telemetry
provider. Heatmap combines documented telemetry with the authored
`thermal_weight` distribution to produce the visual result.

Only documented telemetry may drive Heatmap regions. Missing measurements must
remain unavailable rather than being invented. Preserve the existing telemetry
quality semantics (`measured`, `estimated`, `derived`, `synthetic`, `stale`,
`unavailable`).

Stage 10 uses one documented absolute temperature scale in degrees Celsius for
the complete server. The same temperature must always map to the same colour,
regardless of workload, component family, or thermal zone. Do not apply
per-workload, per-component, or per-region normalization to this Celsius
scalar.

Heatmap temperatures are a derived spatial interpolation, not a claim that
each rendered vertex has a physical temperature sensor. Runtime normalises the
observed authored weights across each discovered asset/zone/component group to
`[0, 1]`; it then calculates:

```text
delta_min_celsius = -Delta
delta_max_celsius = +Delta

display_temperature_celsius = component_telemetry_celsius
    + TemperatureOffset
    + lerp(
        delta_min_celsius,
        delta_max_celsius,
        normalized_thermal_weight
      )
```

`component_telemetry_celsius` is the source temperature for the exact telemetry
identity, such as GPU 1. Delta and Temperature Offset are persisted by
asset/zone/component and are independent of workload. A normalized weight of
`0` resolves to the lower delta endpoint; `1` resolves to the upper endpoint.
The derived display temperature then uses the one server-wide Celsius scale
above. `scalar.py` owns this Celsius calculation; `palette.py` owns clamping,
active stops, and colour interpolation.

The input telemetry quality remains visible. The resulting field must be
described in the UI, legend, and diagnostics as a derived spatial
interpolation from component telemetry and Houdini-authored thermal metadata,
never as direct per-part measurement.

Phase 10.3 provides one settings-driven Heatmap harness, initially OFF. Its
Test/Restore controls own only Heatmap Session opinions. Reload returns the
normal scene and repopulates persisted Heatmap settings; production lifecycle
composition and X-Ray precedence remain deliberately deferred to Phase 10.4.

Rack and data-hall Heatmap behavior is outside Stage 10.


### Implementation sequence

#### Phase 10.0 - Asset preflight ✅

- inspect the production server USD used by DTRS;
- verify `thermal_zone`, `thermal_component`, `thermal_weight`, and optional
  `temperature_preview`;
- verify `thermal_weight` range and usable USD interpolation;
- identify dual-purpose X-Ray/Heatmap geometry.

Gate: production USD proves the expected thermal metadata contract.

result=PASS
thermal_targets=1148
valid_targets=1148
malformed_targets=0
review_targets=0
thermal_weight_range=[0, 1]
xray_overlaps=42


#### Phase 10.1 - Discovery and telemetry binding ✅

- create a reusable semantic registry of Heatmap-capable primitives;
- discover targets from thermal metadata rather than hard-coded mesh paths
  where semantic discovery is sufficient;
- preserve deterministic identity for repeated hardware such as GPU 1/2/3;
- map documented telemetry metrics to compatible thermal zones/components;
- mark regions without truthful telemetry as unavailable;
- keep presentation policy separate from Heatmap capability.

Gate: DTRS can deterministically resolve:

`primitive -> thermal semantics -> telemetry binding/unavailable ->
presentation policy`

without rendering yet.


#### Phase 10.2 - Scalar mapping foundation ✅

- implement the one fixed documented server-wide Celsius scale, clamping,
  colour mapping, quality handling, and missing-data behavior;
- preserve the same-temperature-to-same-colour Celsius-scalar contract without
  per-workload, per-component, or per-region scalar normalization;
- implement the telemetry-anchored derived spatial interpolation defined in
  the thermal contract; do not claim measured temperature at every surface
  point;
- keep `temperature_preview` outside the runtime calculation;
- cover the mapping logic with focused tests;
- implement the reusable Heatmap renderer and prove the complete path on a
  representative non-uniform target:

`TelemetrySnapshot -> semantic binding -> scalar mapping ->
thermal_weight -> visible Heatmap`

- apply runtime presentation without modifying authored asset layers;
- prove clean enable/disable and appearance restoration.

Gate: one production target works end-to-end in Kit before expanding coverage.


#### Phase 10.3 - Generic settings-driven Heatmaps ✅

- persist Isolation, Calibration, and Color Scale in
  `configs/heatmap_settings.toml` without changing telemetry provider config;
- build a stage-driven catalog for the generic Isolation union and dynamic
  calibration controls; all enabled selectors are the full-server case;
- support independent GPU Internals and Housing selectors plus arbitrary
  combinations, exact Session restoration, and generic presentation plans;
- apply candidate settings transactionally while Heatmaps are active, with an
  explicit previous-presentation rollback result on failure;
- retain the 2 Hz presentation cadence, 2.0-second smoothing, and one global
  absolute Celsius scale;
- configure a 2-to-6-stop palette with post-scalar clamp in `palette.py`;
- keep Test/Restore as a development harness, initially OFF after startup or
  reload. No Heatmap lifecycle or X-Ray composition is added in this phase.

Gate: the generic settings path works from one selected target through all
selectors against the production server, without a Vertical Slice or FullServer
runtime mode.


#### Phase 10.4 - Composition and lifecycle

- require every Heatmap activation to apply the Engineering X-Ray presentation;
- do not implement a standalone non-X-Ray Heatmap mode;
- enforce single-server X-Ray precedence on dual-purpose geometry, especially
  the GPU enclosure/shroud;
- ensure suppression affects presentation only and does not remove thermal
  capability or metadata;
- add only the necessary runtime controls, legend, quality/missing-data state,
  and diagnostics;
- verify clean behavior across metric changes, workload changes,
  enable/disable, stage reload, and shutdown;
- remove only Heatmap-owned runtime state and restore the correct authored or
  higher-priority presentation.

Gate: Heatmap always owns its X-Ray presentation, and Heatmap/Streamlines
transitions leave exactly one healthy primary presentation without stale or
corrupted state.


#### Phase 10.5 - Acceptance and release

- run focused Heatmap tests and the full DTRS test suite;
- perform Kit-side acceptance against the production server stage;
- document the thermal metadata contract, telemetry binding, scalar mapping,
  X-Ray precedence, and rack/data-hall boundary;
- record acceptance evidence;
- close `DC-50`;
- create the Stage 10 checkpoint;
- release DTRS `0.5.0`.


### Stage 10 Acceptance

Stage 10 is complete when:

1. Production USD thermal metadata is discovered and validated correctly.

2. `thermal_weight` remains an authored `[0, 1]` spatial distribution and
   `temperature_preview` remains authoring/debug data only.

3. Documented DTRS telemetry drives the correct thermal regions through the
   defined derived spatial interpolation and one deterministic server-wide
   Celsius mapping. Delta and Temperature Offset are persisted calibration,
   while normalized authored weight supplies the spatial distribution.

4. Telemetry quality, stale state, and missing data are represented truthfully;
   unavailable component temperatures are not invented.

5. Repeated hardware resolves to the correct telemetry identity.

6. Workload changes alter runtime thermal presentation without changing the
   authored thermal distribution.

7. Isolation, calibration, and palette settings persist independently of the
   telemetry provider; Test uses applied settings rather than an unsaved draft.

8. Test/Restore leave authored layers and exact prior Session opinions intact.
   Reload returns Heatmaps to OFF and reloads persisted settings. Production
   lifecycle composition and X-Ray precedence remain Phase 10.4 work.

9. Enable/disable and metric changes leave no stale Heatmap harness state and
   do not modify production asset layers.

10. The implementation is reusable and subsystem-owned, with rack/data-hall
    Heatmap behavior explicitly left outside Stage 10.


Done when the full server can present a stable, readable telemetry-driven
Heatmap over Houdini-authored thermal distributions without inventing
measurements or implying validated thermal simulation.


### Post-Stage 10 Enhancement - Thermal-Aware Flow Smoke

This enhancement begins only after Stage 10 Heatmap is complete and its
thermal metadata, telemetry binding, scalar mapping, palette, lifecycle, and
acceptance contracts are stable.

It is not a replacement for the Heatmap and does not introduce another primary
Visualization mode.

The purpose is to connect two already-proven visual systems:

`telemetry-driven component thermal state`
`-> authored Heatmap distribution`
`-> thermal influence injected into the existing Flow simulation`
`-> temperature-aware smoke colour`

The result should make airflow and thermal state read as parts of one system:
cold intake smoke enters the server, passes thermal sources, acquires thermal
colour, and is advected by the existing Houdini-authored velocity field.

This remains an engineering visualisation. The Flow temperature channel is a
temperature-derived presentation scalar seeded from component telemetry; it
must not be presented as a measured or validated per-voxel air-temperature
field.


#### Architecture contract

Do not create:

- a second Flow simulation;
- another telemetry binding system inside `smoke`;
- a second Heatmap scalar/palette implementation;
- RGB values authored independently for Heatmap and Flow;
- workload-specific thermal-smoke logic;
- high-density emitters corresponding to every thermal-weight vertex.

Reuse:

- the existing Flow velocity simulation and smoke tracers;
- the Stage 10 semantic thermal registry and telemetry bindings;
- the Stage 10 fixed scalar ranges and normalization;
- the Stage 10 thermal colour palette;
- the existing Flow lifecycle and performance instrumentation.

Thermal Smoke is a secondary Smoke presentation option:

`Smoke colour = Neutral | Thermal`

It must not become a new primary `VisualizationMode`.


#### Stage 10 compatibility requirements

Stage 10 should leave the following reusable boundaries so this enhancement
does not require a Heatmap refactor.

`heatmaps/scalar.py`

- remains dependency-light and independent from Kit/material code;
- owns the canonical fixed thermal scalar mapping;
- exposes the normalized thermal display scalar used by presentation systems;
- contains no USD material or Flow-specific logic.

`heatmaps/palette.py`

- owns colour-stop validation, clamp, active-stop handling, and interpolation;
- maps the scalar from `scalar.py` to the shared Heatmap colour policy;
- contains no USD material or Flow-specific logic.

`heatmaps/bindings.py`

- remains the single owner of semantic thermal-region -> telemetry binding;
- preserves repeated hardware identity;
- preserves telemetry quality and unavailable state;
- contains no Flow-specific bindings.

`heatmaps/discovery.py`

- remains the owner of the authored thermal metadata contract;
- preserves deterministic prim identity, `thermal_zone`,
  `thermal_component`, and `thermal_weight` information needed for bounded
  spatial sampling;
- must not add Flow-specific presentation policy.

`heatmaps/runtime.py`

- exposes a small immutable/plain-data thermal-state snapshot sufficient for
  other presentation consumers;
- the snapshot should expose resolved component identity, telemetry binding,
  normalized thermal state, quality/availability, and target identity without
  exposing Heatmap material internals;
- other systems must not inspect Heatmap private runtime state.

`heatmaps/material.py`

- remains surface presentation only;
- Thermal Smoke must not import or reuse Heatmap material-binding code.

This establishes:

`heatmaps scalar/binding state`
`-> reusable thermal presentation contract`

rather than:

`smoke`
`-> Heatmap material implementation`.


#### Smoke implementation ownership

Add:

`src/digital_twin_runtime_suite/app/smoke/thermal.py`

This module owns the translation from the reusable Stage 10 thermal state into
a bounded Flow thermal-source description.

Responsibilities:

- consume the public Stage 10 thermal-state snapshot;
- select thermal source regions supported at single-server detail level;
- generate a sparse, bounded set of source samples from authored thermal
  distributions;
- preserve repeated component identity;
- convert canonical normalized thermal scalars into Flow temperature source
  values;
- enforce a configurable maximum sample/source count;
- exclude unavailable regions instead of fabricating temperatures;
- avoid using presentation-proxy geometry such as the single-server GPU shroud
  as an additional thermal source when that would double-count internal GPU
  sources.

It contains no direct telemetry-provider queries and no Flow lifecycle
orchestration.


`smoke/flow.py`

Extend the existing low-level Flow authoring helpers.

Responsibilities:

- create/update DTRS-owned sparse temperature Point Emitter data;
- author temperature and temperature coupling only;
- keep smoke, fuel, burn, divergence, and self-velocity contribution disabled
  for these thermal sources;
- apply the shared thermal palette to the native Flow temperature colormap;
- validate that authored Flow state retained the requested values;
- remove only DTRS-owned thermal-source/colormap runtime opinions during
  cleanup.

Existing passive smoke tracers remain unchanged.


`smoke/runtime.py`

Extend `SmokeRuntimeMixin` with Thermal Smoke presentation lifecycle.

Responsibilities:

- expose `Neutral` and `Thermal` smoke-colour modes;
- enable Thermal only against an already prepared/attached Flow source;
- request the current public thermal-state snapshot from the Heatmap subsystem;
- build/update sparse thermal sources through `smoke/thermal.py`;
- apply them through `smoke/flow.py`;
- refresh source values when telemetry/workload changes without rebuilding the
  Flow simulation;
- restore neutral smoke presentation cleanly;
- rollback to the last valid Neutral state if Thermal activation fails;
- prevent duplicate thermal emitters/tasks after repeated Apply or rapid mode
  changes;
- clean thermal state on Flow detach, stage reload, Normal/Streamlines
  transition, and shutdown.

Thermal Smoke activation must not perform Flow Attach, VTI import, Streamlines
cache work, or Flow reconstruction unless the existing Smoke transition already
requires that operation.


#### Renderer proof before full implementation

Before expanding across the server, perform one bounded Kit-side proof.

Use:

- one existing attached Flow simulation;
- the existing passive smoke tracer;
- one representative thermal source;
- one simple low/high temperature change;
- the Stage 10 palette.

Prove that the installed Kit/Flow renderer can visibly map the advected
temperature channel through the required colormap while preserving the current
smoke-density presentation.

Do not build full-server source generation until this proof succeeds.

Gate:

`existing smoke + one thermal source -> visibly advected temperature colour`

must work without a second Flow simulation or runtime Flow reset.


#### Full-server implementation

After the renderer proof:

- create sparse thermal sources only for supported Stage 10 thermal regions;
- begin with GPU, CPU, and PSU sources;
- expand to other components only when they have truthful Stage 10 bindings and
  visible value;
- reuse the same fixed scalar mapping and palette used by Heatmap;
- keep source density bounded; do not mirror every authored
  `thermal_weight` point into Flow;
- workload changes update source scalar values through the existing telemetry
  path;
- the Houdini velocity field remains the sole airflow velocity source.

The goal is readable thermal transport, not reconstructing CFD heat transfer.


#### Automated tests

Extend existing Heatmap tests where the shared contract is involved:

`tests/heatmaps/test_heatmap_scalar.py`

- canonical normalization remains deterministic;
- identical normalized scalar produces the canonical palette result;
- scalar/palette behavior is workload-independent.

`tests/heatmaps/test_heatmap_runtime.py`

- public thermal-state snapshot exposes supported component state without
  exposing material/runtime internals;
- quality and unavailable state survive the snapshot unchanged.

Add focused Smoke tests, preferably under `tests/smoke/`:

`test_thermal_smoke_sources.py`

- sparse source generation from thermal-state snapshots;
- repeated hardware identity;
- bounded source count;
- unavailable-region exclusion;
- correct normalized temperature values;
- no duplicated source identities.

`test_thermal_smoke_flow.py`

- thermal emitters author temperature coupling only;
- smoke/fuel/burn/self-velocity coupling stays disabled;
- canonical palette is translated to the Flow colormap correctly;
- cleanup removes only Thermal-Smoke-owned opinions.

`test_thermal_smoke_runtime.py`

- Neutral -> Thermal -> Neutral Happy Path;
- telemetry/workload refresh updates thermal sources without Flow reset;
- repeated Apply is idempotent;
- failure rolls back to valid Neutral smoke;
- detach/reload/shutdown leaves no thermal-source state behind.

Extend visualization-mode tests to prove that Thermal Smoke remains a secondary
Smoke setting and does not become another primary visualization mode.


#### Required boundary cases

In addition to the Happy Path, automated tests must cover at least these
boundary cases:

1. **No truthful thermal source**
   - all candidate regions are unavailable;
   - Thermal activation must not invent source temperatures;
   - report unavailable or remain Neutral according to the Stage 10
     missing-data policy.

2. **Mixed valid and unavailable regions**
   - valid components continue to contribute;
   - unavailable components are skipped;
   - no whole-server failure is caused by one optional missing binding.

3. **Invalid/stale/out-of-range telemetry**
   - use the exact Stage 10 scalar/quality policy;
   - do not silently promote stale data or create NaN/invalid Flow values;
   - clamping, rejection, or suppression must match the canonical thermal
     contract.

4. **Rapid supersession**
   - workload or Neutral/Thermal mode changes while a previous update is
     pending;
   - the latest committed request wins;
   - no duplicate emitters, tasks, or stale source values remain.

5. **Presentation/lifecycle exit**
   - transition from Thermal Smoke to Normal or Streamlines, Flow Detach, stage
     reload, and shutdown;
   - thermal emitters and colormap overrides are cleaned while unrelated Flow,
     Heatmap, X-Ray, and Streamlines state remains owned by their respective
     subsystems.

Additional Case 03 guard:

- the GPU shroud may remain Heatmap-capable for future rack/hall use, but at
  single-server level it must not become an extra Thermal Smoke source if the
  internal GPU thermal regions already represent that device.


#### Performance acceptance

Use the existing Flow viewport-performance sampler; do not introduce a second
profiling system.

Run a fixed-camera A/B comparison using the same:

- workload;
- airflow dataset;
- voxel resolution;
- raymarch quality;
- smoke tuning;
- camera;
- measurement duration.

Compare:

A. `Neutral Smoke`
B. `Thermal Smoke`

Record at minimum:

- average FPS;
- minimum FPS;
- average frame time;
- GPU memory use.

Initial performance guardrail:

- Thermal Smoke should remain within approximately 10% of the Neutral Smoke
  average-FPS baseline at the accepted fixed camera/settings;
- a larger regression requires source-density or renderer tuning before the
  feature is accepted;
- no performance claim is made until measured on the production RTX 3080
  configuration.

If source count materially changes active Flow allocation, characterize that
separately instead of attributing the entire regression to colour mapping.


#### Guided Kit acceptance

Use the existing reusable `GuidedAcceptanceSession` /
`format_manual_acceptance_event()` mechanism.

The guided workflow belongs in a focused extension workflow, not in
`smoke/runtime.py`, `heatmaps/runtime.py`, or `extension.py`.

Suggested workflow:

`thermal_smoke_acceptance.py`

Automatic preflight before READY must verify:

- Stage 10 thermal contract is available;
- production server stage is loaded;
- current workload has at least one valid thermal source;
- no conflicting visualization transition is pending;
- Flow/Smoke can be selected normally;
- fixed performance camera/bookmark is available.

Only then emit:

`READY`

followed by:

`NEXT_ACTION | Select "Smoke" in "Visualization".`

After Smoke is visibly prepared and stable:

`NEXT_ACTION | Set "Smoke colour" to "Thermal" and press "Apply".`

The workflow then automatically verifies:

- one existing Flow simulation remains in use;
- no Flow reset/re-Attach occurred;
- thermal source prims exist exactly once;
- valid source values match the Stage 10 thermal snapshot;
- Flow temperature presentation is active;
- the canonical thermal palette is installed;
- playback continues;
- performance sampling is live.

Then emit:

`NEXT_ACTION | Change workload to "Critical".`

After the workload transition, automatically verify:

- telemetry identity changed to the committed workload state;
- thermal source values changed through the shared Stage 10 mapping;
- source geometry/identity was not rebuilt unnecessarily;
- Flow playback remained live;
- no duplicate source prims appeared.

Then emit:

`NEXT_ACTION | Set "Smoke colour" to "Neutral" and press "Apply".`

Automatically verify:

- thermal source influence is disabled/removed;
- neutral smoke colour is restored;
- the original Flow source remains valid;
- no stale thermal presentation remains.

Then emit:

`NEXT_ACTION | Select "Normal" in "Visualization".`

Automatically verify final cleanup and emit exactly one terminal result:

`TEST COMPLETE | PASS`

or:

`TEST COMPLETE | FAIL`

After `TEST COMPLETE`, emit no further manual action.


#### Thermal Smoke Enhancement Acceptance

This enhancement is complete when:

1. Thermal Smoke reuses the accepted Stage 10 thermal scalar and palette
   contract rather than implementing a second mapping.

2. Thermal Smoke uses the existing Flow simulation and existing Houdini
   velocity field.

3. Sparse Flow temperature sources are driven only by truthful Stage 10 thermal
   state.

4. The existing passive smoke emitters remain smoke-only and are not converted
   into fake thermal sensors.

5. Thermal colour visibly advects through the server airflow rather than merely
   recolouring the entire volume uniformly.

6. Neutral/Thermal switching does not rebuild or re-Attach Flow.

7. Workload changes update thermal influence through the existing telemetry
   path.

8. Missing, stale, or unavailable data follows the Stage 10 quality policy and
   never fabricates a valid-looking thermal result.

9. Neutral Smoke, Thermal Smoke, Heatmap, X-Ray, Streamlines, reload, detach,
   and shutdown retain clean subsystem ownership and cleanup.

10. Fixed-camera performance evidence shows the measured Thermal Smoke cost
    relative to the accepted Neutral Smoke baseline.

Done when DTRS can use the same telemetry-derived thermal language for both
surface Heatmap presentation and Flow smoke colouring, while keeping thermal
transport explicitly a presentation layer rather than claiming validated
per-voxel air-temperature simulation.


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


**Deferred visual-layer refinement — seamless Streamlines workload handoff
(optional):**

Stage 9 keeps the server/rack scene continuously composed during Streamlines
workload changes by swapping only the DTRS-owned Streamlines cache reference.
The Streamlines geometry itself may still disappear briefly while the replacement
cache composes.

If this remains visually objectionable with the final production Streamlines
presentation, consider an A/B presentation-slot handoff:

- keep the currently proven Streamlines cache visible;
- prepare the target workload cache in a second candidate slot;
- resolve and prove the required cached state before presentation handoff;
- switch visibility only after the candidate is ready;
- release the previous slot after the handoff;
- preserve existing workload commit, rollback and supersession semantics;
- keep exactly one authoritative playback scheduler after completion;
- measure the additional CPU/GPU memory cost before accepting the refinement.

This is presentation polish only. It was not required for Stage 9 / Phase 4
correctness or acceptance and remains deferred.


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
