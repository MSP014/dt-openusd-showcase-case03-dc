# Runtime Packaging Guardrail

**Status:** Architecture guardrail
**Scope:** Future runtime/viewer packaging for Case 03
**Current priority:** path-portable local Kit runtime and hydrated OpenUSD assets

---

## 1. Purpose

Case 03 is currently an OpenUSD asset and viewer project. Houdini remains the
authoring and cleanup environment. The Omniverse Kit application is the runtime
layer that consumes hydrated USD assets and presents them as an interactive
review and demonstration viewer.

This note defines how future runtime packaging should be shaped once the local
Kit runtime is stable. It is a guardrail, not a request to start building
Docker images, streaming services, or cloud deployment scripts now.

The practical rule is:

> Build the Kit runtime and USD asset package so they are path-portable first
> and package-ready later, without turning containerisation into current scope.

---

## 2. Related Source Documents

This guardrail follows the current runtime boundary:

- [ADR 005: Asset Life Cycle & Hydration](../adr/005-asset-hydration.md)
  defines how heavy runtime assets are kept outside Git and hydrated into
  `assets/_external/`.
- [ADR 006: Omniverse Runtime Boundary and Portability](../adr/006-omniverse-runtime-boundary.md)
  defines the Omniverse viewer as a contract-driven runtime layer, not a
  workstation-local scene file.
- [Case 03 - Staged Runtime Plan](../plans/case%2003%20-%20staged%20runtime%20plan.md)
  defines the staged runtime direction: native Kit/OmniUI, Kit RTX viewport,
  explicit viewer commands, and a future-ready boundary for an external web
  control surface.

ADR 007 and the files under `docs/knowledge_base/usd_architecture/` remain
useful historical and target-architecture material, but their wording is under
review. They must not turn long-term digital twin goals into accidental current
runtime requirements.

---

## 3. Current Project Reality

The repository already defines several constraints that any runtime package must
respect:

- **Houdini remains the asset factory.** `.hip` files, procedural authoring,
  geometry cleanup, UV repair, material repair, and exploratory renders stay
  outside the public runtime package.
- **Heavy assets are externally hydrated.** ADR 005 places USD, textures, HDRI,
  and related runtime assets under `assets/_external/`, backed by an external
  asset pack rather than Git.
- **The first runtime is a Kit Viewer.** The first staged build is a native Omniverse Kit
  application with OmniUI panels, toolbars, dockable controls, and a Kit RTX
  viewport.
- **Viewer commands must be explicit.** Load, reload, camera, visibility,
  lighting, telemetry, and diagnostic operations should live behind application
  commands and shared state instead of being buried directly in UI callbacks.
- **A later external web control surface is allowed.** React/FastAPI can become
  a future control layer that drives the same viewer commands, but it is not
  part of the current staged build.
- **Embedded browser UI is out of scope.** The plan is native Kit/OmniUI first,
  not a web page embedded inside the Kit window.
- **Kit template references are not content.** A locally generated NVIDIA
  Omniverse Kit App Template may be used as a read-only implementation
  reference for app structure, extension layout, build/launch workflow, and
  controller patterns, but no local reference path is part of the public runtime
  contract.

Therefore the first runtime package should consume existing exports. It should
not require Houdini, raw production scenes, local absolute paths, or a second UI
runtime.

---

## 4. Runtime Boundary

The runtime boundary begins after the authored asset package exists.

```text
Houdini / OpenUSD authoring
  -> cleaned USD assets, textures, cameras, and material assignments
  -> hydrated asset package under assets/_external/
  -> Omniverse Kit Viewer runtime
  -> optional external control surface or package wrapper later
```

Houdini production files, exploratory caches, raw renders, and workstation-local
paths stay outside the runtime boundary.

The viewer may report asset-side issues through diagnostics, but it must not
become a geometry, UV, material, or normal repair tool.

---

## 5. Packaging Rule

The future viewer should be **path-portable first, package-ready later**, not
container-implemented from day one.

Path-portable first means:

- runtime dependencies are documented;
- launch commands are explicit;
- asset mount points are predictable;
- external assets are not baked into application images;
- secrets and local credentials are not committed;
- environment variables are documented through safe examples when needed;
- asset paths are relative or configurable;
- the hydrated USD package can be inspected without opening Houdini;
- GPU/runtime assumptions are stated when they become known;
- viewer commands and shared state are clean enough to be driven by a future
  external control surface;
- there is a small smoke test or launch check for the local viewer package.

This protects the long-term path to Docker Compose, cloud GPU testing, browser
delivery, or remote review without forcing those systems into the current
runtime scope.

---

## 6. Deferred Runtime Shape

The likely future runtime can be described as layers:

1. **Asset package**
   - USD composition root.
   - External USD/texture/HDRI directories.
   - Optional package manifest.
2. **Kit Viewer runtime**
   - Omniverse Kit App Template based application.
   - Native OmniUI controls.
   - Kit RTX viewport.
   - Stage loading, camera, visibility, lighting, telemetry, and diagnostics.
3. **Viewer command/state layer**
   - Stable commands for core viewer operations.
   - Shared state that is not tied directly to UI widgets.
   - The integration point for future automation or web control.
4. **Optional external web control surface**
   - Deferred until the native Kit Viewer is stable.
   - May use React/FastAPI or another web stack.
   - Must drive the existing viewer commands rather than replacing the viewer
     core.
5. **Optional container wrapper**
   - Mounts the hydrated asset package.
   - Runs only the runtime layer.
   - Excludes Houdini source files and raw authoring workflows.
6. **Optional streaming or cloud execution**
   - Deferred until local viewer packaging is proven.
   - Not a requirement for the current staged build.

Local Kit template inspection is allowed during this phase, but template code,
generated app files, USD assets, textures, and documentation must not be mixed
between the local template reference and this repository unless a specific
integration task is approved.

---

## 7. First Viewer Contract

Before any container work starts, define a minimal local viewer contract:

- which USD composition root is loaded;
- where hydrated external assets are mounted;
- what counts as a successful launch;
- which cameras or bookmarks are exposed;
- which scene groups receive first-class visibility toggles;
- which lighting presets are available;
- which diagnostics are shown in the current staged build;
- which viewer commands and state objects must stay stable for future control
  layers.

A valid first proof can be modest:

```text
Open one Case 03 USD package
-> load hydrated assets from a documented relative path
-> reach a stable Kit RTX view
-> switch one prepared camera
-> toggle one meaningful scene group
-> report load and runtime status
```

This is enough to prove runtime reproducibility without pulling the project into
a full product stack too early.

---

## 8. Future Package Index

A future runtime may need a small package index: a lightweight text file that
tells the viewer what exported assets exist, where they are mounted, and which
viewer modes they support.

This is not a current implementation task. The package index becomes useful
after exported assets and the local viewer contract stabilise, because it
prevents future viewer code from hardcoding paths or guessing which files belong
to which scene state.

When that time comes, the package index should answer:

- package name and version;
- USD composition root path;
- required external directories;
- available camera bookmarks;
- available scene groups;
- available visual or lighting modes;
- expected units and up-axis;
- asset validation status;
- missing or optional assets.

This index can later be consumed by the Kit Viewer, an external web control
surface, a validation script, or a container entrypoint. Until then, it should
remain a design consideration rather than new implementation scope.

---

## 9. Development Order

The correct order for Case 03 is:

1. Finish and accept the staged runtime plan.
2. Stabilise the Houdini-to-OpenUSD asset export rules needed by Omniverse.
3. Define the canonical Case 03 USD stage path and hydrated asset layout.
4. Build the smallest local Kit Viewer proof.
5. Add viewer commands and shared state for core operations.
6. Add native OmniUI panels for presentation, lighting, telemetry, and diagnostics.
7. Prove reproducible local launch and asset loading.
8. Consider an external web control surface only after the local viewer works.
9. Wrap the viewer in a reproducible package only after the runtime contract is
   stable.
10. Consider containerisation, streaming, or cloud GPU execution only after that.

Containerisation must not compete with the current objective: a stable,
presentable Kit runtime consuming clean Case 03 OpenUSD assets.

---

## 10. Out Of Scope For Current Phase

The current phase should not create implementation scope for:

- a React frontend;
- a backend API;
- an embedded browser UI inside Kit;
- a render streaming service;
- Kubernetes manifests;
- cloud deployment scripts;
- Docker images containing heavy USD or textures;
- runtime code that assumes absolute workstation paths;
- a containerised Houdini production environment;
- geometry, UV, material, or normal repair inside the viewer.

These may become useful later, but only after the Kit runtime, hydrated asset
package, and minimal local runtime contract are stable.

---

## 11. Hiring Value

A future package-ready runtime path improves the Case 03 story only if it
supports the core evidence:

- Houdini-authored hard-surface assets and cleanup workflow;
- clean OpenUSD composition suitable for Omniverse;
- externalised heavy assets;
- a focused Kit Viewer with a polished native UI;
- reproducible viewer launch;
- a runtime boundary that can later support packaging or external control.

The recruiter-facing message becomes:

> Case 03 is an OpenUSD/Omniverse tech pack with authored hardware assets,
> externalised runtime assets, and a planned reproducible Kit Viewer boundary.

The engineering-facing message becomes:

> The project separates authoring, asset packaging, viewer runtime, and future
> packaging instead of relying on one workstation-local scene.

---

## 12. Decision

Case 03 should remain **Houdini/OpenUSD-first and Kit Viewer-first** in the
current phase.

Future viewer work should be designed as **path-portable first and
package-ready later**, but actual container implementation should wait until the
Kit runtime, hydrated asset package, and local runtime contract are proven.
