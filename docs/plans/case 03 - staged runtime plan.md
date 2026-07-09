# Case 03 - Staged Runtime Plan

**Status**: Draft
**Last Updated**: 2026-07-09

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

Proceed to Stage 5 through `DC-44` when implementation work resumes. Stage 5
loads the full Blackwell Rig server scene into BMS while keeping the controls
minimal: load, focus/navigation, status, and the already proven lighting,
telemetry, and CPU fan motion behaviours.

Do not expand Stage 5 into cached simulation playback, automatic workload
cycling, rack/data-hall navigation, or heatmap authoring. Those remain separate
staged slices after the full server review surface is stable.

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
| Review lighting preset | Stage 2 | Implemented |
| Configurable review grid | Stage 2 | Implemented |
| Review camera persistence | Stage 2 | Implemented |
| Synthetic telemetry values | Stage 3 | Implemented |
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

## Runtime Implementation Decisions

The first staged build was **Blackwell Monitoring Suite v0.1**. The current
runtime build is **Blackwell Monitoring Suite v0.2.0**.

Fixed names and identifiers:

- Public app title: `Blackwell Monitoring Suite`
- Version: `0.2.0`
- Kit extension id: `msp.bw.monitoring`
- Python package root: `blackwell_monitoring_suite`
- Runtime config: `configs/blackwell_monitoring_suite.v0.2.toml`
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
configs/blackwell_monitoring_suite.v0.2.toml
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
- The runtime config is `configs/blackwell_monitoring_suite.v0.2.toml`.
- The extension id is `msp.bw.monitoring`.
- The current default asset is `usd/cpu_fan/cpu_fan.usd` under the hydrated
  external asset package.
- Runtime review camera and light helpers are created in the session layer so
  the hydrated asset is not modified.

### Stage 2 - Look Review Slice

Jira: `DC-41`

Status: implemented locally.

Add review lighting for the selected asset: a Config panel Lighting section,
default Kloofendal HDRI from the hydrated asset package, minimum
exposure/intensity controls, dome XYZ rotation, and clear lighting status.

Done when the selected asset can be viewed under the chosen lighting preset, the
operator can adjust exposure/intensity and dome rotation, and the operator can
see whether the preset loaded successfully.

Implementation notes:

- The Config panel is docked to the left side of the BMS viewport.
- Lighting settings can be applied and saved into the local ignored runtime
  override config.
- The review key light can be enabled or disabled and has its own intensity
  control.
- The review grid can be enabled or disabled, with configurable step and line
  width.
- Camera position can be saved, restored, and reset for repeatable look review.
- HDRI background visibility can be toggled while preserving DomeLight-based
  lighting, using Kit/RTX DomeLight `visibleInPrimaryRay` visibility.
- Operator validation confirmed that the `Show HDRI` control switches the live
  BMS viewport between visible HDRI background and hidden HDRI background while
  keeping the asset lit.

### Stage 3 - Synthetic Telemetry Slice

Jira: `DC-42`

Status: implemented locally.

Add a minimal synthetic telemetry source that runs with the application. This is
not DCC timeline playback; it is runtime data produced or received while the app
is open.

Done when changing telemetry values are visible in the app and are independent
of pressing Play in Houdini or another DCC.

Stage 3 telemetry scope:

- Implement the first-layer node telemetry subset defined in
  `docs/knowledge_base/bms_telemetry_contract.md`.
- Keep the future live-provider superset documented there, but do not implement
  real monitoring feed adapters in Stage 3.
- Group Stage 3 telemetry visually by operator meaning, not by raw sensor
  origin.

Stage 3 UI shell decision:

- Keep a single left-docked BMS sidebar so the viewport is only constrained by
  one stable panel width.
- Convert the current `Config` panel content into a `Config` tab inside that
  sidebar.
- Add a sibling `Telemetry` tab for synthetic Stage 3 runtime values.
- Implement the tabs as an internal OmniUI switcher over content frames, not as
  multiple independent docked windows, unless a later UX pass deliberately
  chooses native Kit dock tabs.
- The selected tab may change, but both tabs should occupy the same sidebar
  footprint and must not cause extra viewport shrinkage.

Left sidebar tab registry:

| Order | Tab | Stage | Purpose |
| :--- | :--- | :--- | :--- |
| 1 | `Telemetry` | Stage 3 | Primary runtime monitoring surface for synthetic telemetry values. |
| 2 | `Config` | Stage 2 / Stage 3 | Operator controls for asset loading, lighting, grid, camera, and local runtime settings. |

Future BMS modules should add their sidebar tabs to this registry before
implementation so the left-slot navigation remains deliberate as the app grows.

Stage 3 runtime snapshot model:

- Use a latest-only in-memory `TelemetrySnapshot` produced by the synthetic
  provider.
- Do not add a database, persistent telemetry store, or historical buffer in
  Stage 3.
- The telemetry UI reads the latest snapshot; future scene behaviours should
  read the same snapshot rather than duplicating generator logic.
- Each snapshot contains the current timestamp, selected operational state,
  refresh interval, and current metric values.
- Each metric value carries its unit and an explicit quality marker. Provider
  source values use `quality = synthetic`; aggregates, balances, utilisation,
  thermal headroom, and other calculated values use `quality = derived`.
  This distinction lets a future live provider replace synthetic sources
  without presenting calculations as measured sensors or forcing UI rewrites.
- Default refresh interval is 1 second. The Telemetry tab may expose a
  `1 / 5 / 10 / 30 s` refresh selector so the operator can reduce update
  frequency if needed.
- Timestamp display is part of the synthetic live-monitoring illusion, but the
  Stage 3 implementation only needs the current snapshot, not stored time
  series data.

Stage 3 data provider boundary:

- Implement the synthetic telemetry provider as a separate application module,
  not as inline UI callback logic.
- Stage 3 keeps the provider in the same Kit application process, but the module
  should be shaped so it can later move behind a process or container boundary.
- UI code should consume provider snapshots through a small provider/state API,
  not by reaching into generator internals.
- The provider should start producing data as soon as BMS starts, before the
  operator manually loads or changes scene content.
- Containerisation, network transport, credentials, service discovery, and live
  provider adapters remain out of Stage 3 scope.

Stage 3 provider lifecycle:

- Start the synthetic telemetry provider during BMS extension startup, not only
  after the operator loads the asset.
- Keep the provider running while the application is open so the `Telemetry`
  tab has data immediately and remains independent from asset reloads.
- Asset loading may subscribe scene behaviour to the latest provider snapshot,
  but it must not be the source of provider lifetime.
- Stop provider update tasks cleanly during extension shutdown so Kit does not
  leave orphaned async tasks, callbacks, or timers.
- Provider shutdown should be idempotent so repeated shutdown or failed startup
  paths do not raise extra errors.

Stage 3 Kit runtime guardrails:

- Do not run the telemetry provider through unmanaged `threading.Thread`
  workers, orphan timers, or callbacks that cannot be cancelled.
- Prefer a Kit-compatible async/update-loop integration with explicit stored
  task/subscription handles owned by the extension or runtime controller.
- Cancel or unsubscribe those handles during extension shutdown and tolerate
  repeated start/stop calls without raising follow-on errors.
- Keep provider configuration path resolution behind a resolver/API boundary
  instead of hardcoding paths relative to the current working directory or Kit
  install layout.
- Treat the provider's packaged base config as read-only; operator changes must
  go to a local override file, not back into the packaged default file.

Stage 3 implementation map:

| Path | Purpose |
| :--- | :--- |
| `src/blackwell_monitoring_suite/app/telemetry/__init__.py` | Public package boundary for telemetry provider code. |
| `src/blackwell_monitoring_suite/app/telemetry/model.py` | `TelemetrySnapshot`, metric value model, workload/health constants, and Stage 3 metric ids. |
| `src/blackwell_monitoring_suite/app/telemetry/config.py` | Load and merge `telemetry_provider.toml` with `telemetry_provider.local.toml`. |
| `src/blackwell_monitoring_suite/app/telemetry/provider.py` | Synthetic provider, fixed provider tick, interpolation, jitter, freeze-independent latest snapshot state. |
| `src/blackwell_monitoring_suite/configs/telemetry_provider.toml` | Packaged read-only base targets, ranges, jitter, default mode, and allowed refresh intervals. |
| `tests/test_telemetry_config.py` | Pure-Python tests for provider config loading, override merge, defaults, and invalid values. |
| `tests/test_telemetry_provider.py` | Pure-Python tests for provider snapshots, cadence semantics, mode changes, freeze/resume display behaviour, deterministic seeded output, and range clamping. |

Stage 3 extension integration:

- `src/blackwell_monitoring_suite/ext/msp.bw.monitoring/msp/bw/monitoring/extension.py`
  remains the Kit extension entry point for this slice.
- Add provider startup/shutdown ownership to `on_startup` and `on_shutdown`,
  storing task/subscription handles as explicit extension fields.
- Convert the current monolithic left panel into a shared sidebar with an
  internal `Telemetry` / `Config` tab switcher.
- Move the current asset, lighting, grid, and camera controls into a
  `_build_config_tab()` helper without changing their runtime behaviour.
- Add `_build_telemetry_tab()` for read-only latest snapshot values, workload
  mode selector, refresh interval selector, and `Freeze` / `Resume`.
- Keep UI refresh separate from provider tick: the Telemetry tab samples the
  latest snapshot at the selected UI refresh interval.
- Keep `src/blackwell_monitoring_suite/app/commands.py` focused on Kit/USD
  runtime commands; do not place synthetic telemetry generator logic there.
- Keep the telemetry provider independent from asset loading. Loading an asset
  may later subscribe scene behaviour to telemetry, but asset load must not own
  provider lifetime.

Stage 3 provider testing:

- Add focused unit tests for the synthetic data provider module as part of
  Stage 3.
- Tests cover the happy path and boundary cases including invalid workload
  mode, unsupported refresh interval, freeze/resume behaviour, timestamp
  monotonicity after resume, metric unit/quality presence, expected metric keys,
  value clamping, deterministic seeded output, GPU ordering and capacity,
  derived metric consistency, node power balance, and intermittent throttling.
- Keep these tests independent of Kit UI so the provider boundary remains
  portable and can later move behind a process or container boundary.

Stage 3 generator behaviour:

- Stage 3 workload mode switching is manual. The operator selects `Idle`,
  `Nominal`, `Surge`, or `Critical`; automatic state cycling is out of scope
  for this slice.
- The selected mode defines target values for each synthetic metric.
- When the selected mode changes, metric values should move smoothly towards the
  new targets instead of jumping instantly.
- The provider may add bounded jitter around the current mode target so the
  telemetry reads as live data without becoming noisy or distracting.
- Provider cadence is driven by Kit runtime/app update time or another
  monotonic runtime clock, not by Houdini or DCC timeline playback.
- Provider state progression should run at its own fixed cadence, initially
  around 1 Hz, so interpolation and jitter remain predictable.
- The UI refresh selector controls how often the Telemetry tab samples the
  latest provider snapshot; it must not slow the provider's internal state
  progression.
- The UI timestamp may use wall-clock time for live-monitoring readability, but
  generator progression must not depend on DCC playback state.
- When `Freeze` is active, the provider should continue running and producing
  latest snapshots, but the UI should keep displaying the frozen snapshot until
  `Resume` is clicked.
- `throttling_active` is generated as a stateful Critical-mode episode rather
  than a static mode flag or per-tick random flicker. Episode probability is
  driven by CPU temperature, maximum GPU hotspot temperature, and PSU load;
  configured active and recovery durations keep the signal intermittent.

Stage 3 telemetry provider config:

- Generated metric baselines and safe ranges are config-driven. Aggregates and
  physically linked values are calculated by provider rules so operator edits
  cannot create contradictory GPU totals, thermal ordering, memory capacity,
  or node power balance.
- Add a separate telemetry provider config file owned by the telemetry/data
  provider module. Do not store telemetry targets in the existing BMS local
  operator override config used for lighting, grid, camera, and look-review
  settings.
- The `Config` tab may expose telemetry provider settings, but persistence must
  go through the provider config path/API, not through the current BMS
  `.local.toml` override.
- Use a read-only packaged base file plus a writable local override, for
  example `telemetry_provider.toml` merged with
  `telemetry_provider.local.toml`.
- The local override should be ignored by git and should contain operator edits
  such as tuned targets or jitter/range changes.
- The provider config file layout should let the telemetry module move later
  into a separate process or container with its own config and without breaking
  the BMS data flow.
- The config should define global telemetry defaults such as default workload
  mode, default refresh interval, and allowed refresh intervals.
- The config should define per-mode targets for `Idle`, `Nominal`, `Surge`, and
  `Critical`, grouped by the Stage 3 telemetry groups.
- Numeric metrics should support `target`, `jitter`, `min`, and `max`.
- String state metrics support direct per-mode values. The Critical-mode
  `throttling_allowed` boolean is a provider gate; the displayed
  `throttling_active` value is calculated by the stateful throttling model.
- Initial values may be rough but plausible; tuning after runtime inspection is
  expected.

Temporary workload mode control:

- Until the BMS shell has a dedicated global mode selector, the first control in
  the `Telemetry` tab should select the global workload mode:
  `Idle`, `Nominal`, `Surge`, or `Critical`.
- This selector is a temporary UI placement decision. The selected mode is still
  global BMS runtime state, not telemetry-tab-local state.
- Stage 3 uses the selected mode to drive synthetic telemetry values.
- Later stages may move the same mode selector into a more global app-level
  control area when scene behaviour, fan motion, overlays, LEDs, or other BMS
  modules need the same state.
- The Telemetry tab should include a `Freeze` toggle. When active, the provider
  keeps the current snapshot visible and pauses displayed updates so the
  operator can capture a stable UI frame. The same control should switch its
  label to `Resume` while frozen and resume normal updates when clicked again.

Stage 3 telemetry UI acceptance:

- The `Telemetry` tab is read-only for displayed telemetry values in Stage 3.
- The first implementation shows current values from the latest
  `TelemetrySnapshot` only.
- Do not add charts, history, sparklines, min/max columns, averages, trend
  buffers, or telemetry persistence in this slice.
- The top of the tab should expose the temporary workload mode selector,
  refresh interval selector, and `Freeze` / `Resume` control.
- Show a timestamp at the top of the telemetry view as `Last update` while
  running and as `Frozen at` while the view is frozen.
- Present metric values by operator meaning and identified hardware: node,
  CPU, each GPU, GPU array summary, power, CPU cooling, front intake, rear
  exhaust, airflow, network, and limits.
- Each visible metric row or compact card should show a human-readable label,
  current value, and unit.
- Metric `quality` is part of the runtime snapshot contract, but does not need
  to be prominent in the first UI. Synthetic source and derived value quality
  may remain hidden until a later detail or diagnostics surface.
- Use health/state colour only for high-level status readability: neutral/OK for
  normal state, amber for warning or degraded state, and red for critical state.
- Surface `throttling_active = true` as a clear warning indicator, row, or badge.

Stage 3 explicit non-goals:

- No charts, sparklines, trend lines, historical tables, or min/max/average
  sensor history.
- No telemetry storage beyond the latest in-memory snapshot needed by the UI and
  future scene consumers.
- No telemetry-driven fan motion or animated hardware behaviour; that starts in
  Stage 4.
- No live monitoring source, external feed adapter, network transport, or
  containerised provider runtime.
- No general alert or rule engine. `health_state` remains a direct mode value;
  the provider only owns the bounded CPU/GPU/PSU pressure model needed to
  generate intermittent `throttling_active` episodes.

Stage 3 manual validation:

- Max can launch BMS and switch the left sidebar to the `Telemetry` tab.
- Telemetry values are visible and update without pressing Play in Houdini, Kit
  timeline, or any other DCC timeline.
- Changing the workload mode changes the telemetry targets and values move
  towards the new mode range.
- `Freeze` stops visible telemetry updates and `Resume` continues them.
- Switching between `Telemetry` and `Config` does not resize, overlap, or damage
  the viewport/sidebar layout.

Operator validation on 2026-07-09 confirmed all Stage 3 manual acceptance
items, including mode transitions, independent runtime updates, freeze/resume,
tab switching, config persistence, intermittent throttling, and clean BMS
restart/shutdown behaviour.

First-layer node telemetry groups:

| Group | Metrics | Purpose |
| :--- | :--- | :--- |
| Node | `timestamp`, `operational_state`, `workload_percent`, `health_state` | Anchors the snapshot in runtime time and shows the selected workload and node health. |
| CPU | `cpu_temp_c`, derived `thermal_headroom_percent`, `cpu_power_w` | Connects CPU workload, package power, temperature, and remaining thermal margin. |
| GPU 1 / 2 / 3 | Per-GPU temperature, memory temperature, hotspot, power, blower RPM, allocated memory, and derived memory utilisation | Represents all three RTX PRO 4500 cards separately with independent jitter and provider-owned positional thermal bias. |
| GPU array | Maximum GPU, memory, and hotspot temperatures; total GPU power; total allocated GPU memory | Derives node-level GPU summaries from the three component values. |
| Power | `pdu_outlet_power_w`, `psu_output_power_estimate_w`, `cpu_power_w`, `gpu_power_w_total`, `platform_residual_power_w`, `psu_conversion_loss_w`, `psu_temp_estimate_c`, `psu_load_percent` | Balances synthetic PDU input, estimated PSU output, measured-class component contributors, platform remainder, conversion loss, thermal estimate, and PSU capacity without claiming unavailable consumer PSU sensors. |
| CPU cooling | `cpu_fan_rpm`, `cpu_fan_duty_percent` | Connects CPU thermal state to the Noctua cooler response. |
| Front intake | Three independent `front_fan_rpm` channels | Represents the three ARCTIC BioniX P120 front-intake fans. |
| Rear exhaust | Two independent `rear_fan_rpm` channels | Represents the two ARCTIC P8 Max rear-exhaust fans. |
| Airflow | `node_airflow_cfm` | Exposes the current node airflow estimate without inventing unsupported intake/exhaust measurements. |
| Network | `link_state`, `link_speed_gbps`, RX/TX throughput, `nic_temp_c`, packet error rate, and active RDMA sessions | Represents the NVIDIA ConnectX-7 link and workload-driven network activity. |
| Limits | `throttling_active` | Shows intermittent Critical-mode throttling episodes driven by CPU, GPU hotspot, and PSU load pressure. |

Deferred rack/facility telemetry fields and the extended live-provider contract
remain in `docs/knowledge_base/bms_telemetry_contract.md`. Stage 3 deliberately
expanded the node slice to cover the installed GPUs, cooling fans, PSU/PDU
balance, and ConnectX-7 NIC, but it does not expose rack or facility telemetry.

The current Case 03 node uses a consumer/workstation PSU. Stage 3 therefore
uses synthetic `pdu_outlet_power_w` as the external input and derives PSU
output, platform residual, conversion loss, load percentage, and estimated
temperature. These estimates remain distinct from direct PSU sensor readings.
Server-class PSU fields are reserved for future live providers that can supply
them through a digital PSU, smart PDU, UPS, branch circuit monitor, BMC,
Redfish, IPMI, or PMBus source.

### Stage 4 - Telemetry Driven Motion Slice

Jira: `DC-43`

Connect the synthetic telemetry snapshot to visible scene behaviour. The first
motion target is the Noctua CPU cooler fan: the sidebar keeps reporting the
realistic `cpu_fan_rpm`, while the viewport rotates the fan blades from the same
live telemetry signal.

Scope:

- create a small generic rotation-motion controller owned by
  `msp.bw.monitoring`;
- update it once per Kit frame from `app.next_update_async()`, not only at the
  slower telemetry UI refresh interval;
- use `SyntheticTelemetryProvider.latest_snapshot.metrics["cpu_fan_rpm"]` as
  the input signal;
- keep the UI Freeze action display-only: frozen telemetry rows must not pause
  the provider or the fan motion.

Runtime motion discovery:

- do not rely on Houdini SOP nulls alone being preserved as usable USD runtime
  controls. The preferred exported contract is a rotating mesh under a stable
  parent `Xform` whose local origin lies on the physical rotation axis;
- the first target mesh is
  `/cpu_fan/geo/render/cpu_cooler/cpu_fan/blades/blades`;
- build edge adjacency from `faceVertexCounts` and `faceVertexIndices`;
- use the mesh bounds only as a coarse search window. A seven-blade impeller is
  not symmetric enough for the bounding-box centre to be a valid pivot;
- find high-valence pole candidates near the hub. Most fan and blower meshes in
  this project originate from 32- or 64-sided cylinders, so centre-pole
  candidates should have at least 32 edge-connected neighbours;
- score candidates by valence, distance from the coarse centre, and neighbour
  distance distribution, then cluster the best candidates into the front/back
  hub centres;
- derive the rotation axis from the front/back hub-centre line and the pivot
  from their midpoint or shared centre line;
- prefer direct rotation on the authored parent `Xform` when the topology
  result validates that the resolved axis passes close to the parent's local
  origin. For a local `Z` axis, the resolved pivot must have near-zero `X` and
  `Y`; the `Z` coordinate may differ because all points on that line share the
  same rotation axis;
- when the authored parent origin is missing or off-axis, fall back to a
  Session Layer pivot stack shaped as
  `translate(pivot) -> rotate(axis) -> translate(-pivot)`;
- cache the resolved pivot and axis per prim path. Recompute only when the
  stage, asset, or prim identity changes.

For the current Noctua fan, the validated mesh-local result is a local Z-axis
with the hub line near `(0.0, 0.0, z)` after the corrected export. Earlier
exports produced the same physical axis with an offset mesh-local pivot; this
remains the fallback case and test fixture. The runtime transform must be
authored as a non-destructive Session Layer override on the existing rotating
prim or its nearest suitable `Xform`, so the referenced USD files and root layer
stay clean.

Scalability and level of detail:

- topology discovery is acceptable for a hero component or a hero server because
  it runs on load or asset reload and then caches the pivot/axis per prim path;
- a full server may animate all meaningful visible rotating parts: CPU fan,
  front intake fans, rear exhaust fans, GPU blowers, and the PSU fan;
- server-level fan and blower assets should follow the BMS motion contract
  documented in `src/blackwell_monitoring_suite/README.md`: stable rotating
  parent `Xform` first, topology-validated axis discovery, Session Layer pivot
  stack only as fallback;
- rack and data-hall views should not animate hidden server internals. At those
  scales, motion should be gated by visibility, selected asset, camera distance,
  and scene detail mode;
- for a full server room, the fallback presentation can animate only
  front-facing fans on nearby or highlighted servers, with distant racks staying
  static or using aggregate visual cues.

Timing:

- measure frame deltas with monotonic time;
- clamp a single frame delta to about `0.1` seconds to avoid a large jump after
  focus loss, reload, or a temporary stall;
- accumulate the angle modulo 360 degrees;
- reset or reacquire stage and prim state on asset reload or stage close.

Display mapping:

The telemetry RPM remains physically plausible for the hardware config: Idle
`650-900`, Nominal `1000-1380`, Surge `1500-1950`, Critical `2050-2300`. The
viewport should not use those RPM values directly, because a seven-blade fan
sampled by an interactive viewport can alias, appear frozen, or reverse. Stage
4 should map telemetry RPM to a labelled presentation speed range that remains
visually readable, responds to jitter and interpolation, and keeps the four
workload modes distinct. This mapping is a display device, not a new telemetry
value. The current first-pass presentation range is `40-360 RPM`: fast enough
to read as an active fan in the viewport, but still below the first seven-blade
stroboscopic stop point at 50 FPS (`~429 RPM`).

Stage 4 deliberately does not lock the whole Kit render loop to 50 FPS. The
simulation/cache cadence belongs to Stage 6: cached playback should map elapsed
seconds to authored time codes, and deterministic capture can request a fixed
capture rate when needed. The fan controller should be robust to variable
interactive frame rate.

Failure behaviour:

- missing stage, missing prim, invalid mesh path, or incompatible xform stack
  must not crash the telemetry loop;
- warnings should be one-shot or rate-limited;
- extension shutdown should stop the controller and remove or neutralise the
  runtime session override when the stage is still available.

Automated checks:

- telemetry RPM to presentation speed mapping, including clamp boundaries;
- angle increment, wraparound, and `dt` clamp;
- controller reset or reacquire behaviour;
- topology-based pivot and axis discovery, including the Noctua 7-blade mesh
  fixture;
- high-valence candidate filtering for 32- and 64-sided cylinder-derived hubs;
- session-layer authoring helper does not target the root layer;
- missing prim or stale stage is handled without repeated errors.

Manual checks:

- load the Noctua NH-D9 TR5-SP6 asset and confirm continuous blade rotation;
- confirm the runtime-resolved pivot matches the known Noctua centre closely
  enough to avoid visible orbiting or wobble;
- switch Idle, Nominal, Surge, and Critical and confirm the visual speed changes
  smoothly with telemetry interpolation;
- click Freeze and confirm the UI rows freeze while fan motion continues;
- reload the asset and confirm rotation resumes without a visible jump;
- confirm the source USD and root layer are not dirtied by runtime motion.

Done when the CPU fan rotates from live telemetry, survives reload and
shutdown, keeps authored USD assets clean, and has focused tests for the
controller logic and edge cases.

### Stage 5 - Server Review Slice

Jira: `DC-44`

Move from the single hardware asset to the full server or Blackwell Rig scene.
Keep the controls minimal: load, focus/navigation, status, and any lighting
control already proven in earlier slices.

When the full server scene arrives, fan motion should reuse the Stage 4 BMS
motion contract rather than invent per-part exceptions: CPU cooler fans, front
intake fans, rear exhaust fans, GPU blowers, and the PSU fan should each expose
a stable rotating parent `Xform` whose local origin lies on the rotation axis,
with topology-validated pivot-stack fallback for older or imperfect exports.

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
