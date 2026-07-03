# Runtime Packaging Guardrail

**Status:** Architecture guardrail
**Scope:** Future runtime/viewer packaging for Case 03
**Current priority:** Houdini simulation proof, USD/cache packaging, and README evidence

---

## 1. Purpose

Case 03 is currently a Houdini-first production and simulation project. The
runtime application is not implemented yet: `src/` is still a placeholder, there
is no Docker Compose stack, no frontend, no backend service, and no Omniverse Kit
extension in this repository.

This note defines how future runtime work should be shaped once the exported
USD/simulation package exists. It is a guardrail, not a request to start building
containers immediately.

The practical rule is:

> Build the Houdini and USD outputs so they can be consumed by a reproducible
> runtime later, without turning containerisation into current sprint scope.

---

## 2. Related Source Documents

This note is subordinate to the existing project contracts:

* [ADR 005: Asset Life Cycle & Hydration](../adr/005-asset-hydration.md)
  defines how heavy runtime assets are kept outside Git and hydrated into
  `assets/_external/`.
* [ADR 007: USD Digital Twin Pipeline Architecture](../adr/007-usd-digital-twin-pipeline.md)
  defines the accepted OpenUSD pipeline architecture for Case 03.
* [00. Master USD Contract](./usd_architecture/00_project_usd_contract.md)
  defines the current USD baseline: units, up-axis, LOD naming, payload rules,
  material dependency boundaries, and telemetry primvars.

If this guardrail conflicts with those documents, the accepted ADR/USD contract
wins.

---

## 3. Current Project Reality

The repository already defines several constraints that any future viewer must
respect:

* **Houdini remains the production factory.** `.hip` files and simulation
  authoring workflows stay outside the public runtime package.
* **Heavy assets are externally hydrated.** ADR 005 places USD, textures, HDRI,
  and future cache assets under `assets/_external/`, backed by an external asset
  pack rather than Git.
* **OpenUSD structure is contractual.** ADR 007 and
  `docs/knowledge_base/usd_architecture/` define the required composition,
  payload, LOD, instancing, material, and telemetry rules.
* **Telemetry is authored through primvars.** The v1.0 schema currently requires
  `primvars:telemetry:schemaVersion`, `primvars:server:id`,
  `primvars:telemetry:tempC`, and `primvars:telemetry:powerW`.
* **Simulation data is not live runtime simulation.** Airflow and thermal
  behaviour are expected to be precomputed in Houdini and consumed as exported
  USD/VDB/curve/cache artefacts.
* **Kit app template references are not content.** The local
  `E:\omniverse_kit_app` folder is a read-only reference copy of NVIDIA
  Omniverse Kit App Template and the generated `msp.case03.blackwell` test
  application. It can inform app structure, extension layout, build/launch
  workflow, startup/playback/controller patterns, and future runtime viewer
  architecture, but it is not part of the authored Case 03 content repository.

Therefore the first runtime package should consume existing exports. It should
not require Houdini, raw production scenes, or workstation-specific absolute
paths.

---

## 4. Runtime Boundary

The runtime boundary begins after the production package exists.

```text
Houdini / Solaris / PDG
  -> exported USD composition roots
  -> VDB airflow and thermal caches
  -> BasisCurves / streamline caches
  -> texture and material libraries
  -> cache or asset manifest
  -> runtime viewer package
```

Houdini production files, exploratory caches, raw renders, and workstation-local
paths stay outside the runtime boundary.

---

## 5. Packaging Rule

The future viewer should be **container-ready**, not necessarily
container-implemented from day one.

Container-ready means:

* runtime dependencies are documented;
* launch commands are explicit;
* asset mount points are predictable;
* external assets are not baked into application images;
* environment variables are documented through a safe example file;
* asset paths are relative or configurable;
* the USD/cache package can be inspected without opening Houdini;
* GPU/runtime assumptions are stated when they become known.

This protects the long-term path to Docker Compose, cloud GPU testing, or browser
delivery without forcing those systems into the current production phase.

---

## 6. Deferred Runtime Shape

The current repository does not justify defining hard service boundaries yet.
The likely future runtime can still be described as layers:

1. **Asset package**
   * USD composition root.
   * External USD/VDB/texture/cache directories.
   * Asset or cache manifest.
2. **Viewer runtime**
   * Omniverse Kit extension or lightweight local viewer.
   * State and visual-mode switching.
   * Camera or hierarchy navigation.
3. **Telemetry/data layer**
   * Synthetic demo values first.
   * Same schema shape as future live data.
   * No dependency on a specific monitoring provider.
4. **Optional web or streaming shell**
   * Deferred until the local runtime is stable.
   * Should not be designed before the USD/cache contract is proven.
5. **Optional container wrapper**
   * Mounts the asset package.
   * Runs only the runtime layer.
   * Excludes Houdini source files and raw authoring workflows.

The first implementation may be a local Omniverse runtime rather than a web
application. A web frontend, render-streaming service, or multi-container stack
should be introduced only when there is a concrete viewer to wrap.

Local Kit template inspection is allowed during this phase, but template code,
generated app files, repo tooling, USD/VDB assets, and documentation must not be
mixed between `E:\omniverse_kit_app` and this repository unless a specific
integration task is approved.

---

## 7. First Viewer Contract

Before any container work starts, define a minimal first viewer contract:

* which USD composition root is loaded;
* where hydrated external assets are mounted;
* which visual states are available;
* which VariantSets or primvars the viewer is allowed to touch;
* which cameras or hierarchy targets are exposed;
* which telemetry fields are displayed;
* what counts as a successful launch.

A valid first proof can be modest:

```text
Open one Case 03 USD package
-> load hydrated assets from a documented relative path
-> switch one operational state or visual mode
-> display a small telemetry panel
```

This is enough to prove runtime reproducibility without pulling the project into
a full product stack too early.

---

## 8. Future Package Index

A future runtime will eventually need a small package index: a lightweight text
file that tells the viewer what exported assets exist, where they are mounted,
and which states or modes they support.

This is not a current implementation task. The immediate priority remains the
Houdini simulation proof and clean USD/cache export. The package index becomes
useful after exported assets stabilise, because it prevents future viewer code
from hardcoding paths or guessing which files belong to which state.

When that time comes, the package index should answer:

* package name and version;
* USD composition root path;
* required external directories;
* available LODs;
* available operational states;
* available visual modes;
* cache files per state and scale;
* telemetry schema version;
* expected units and up-axis;
* missing or optional assets.

This index can later be consumed by an Omniverse extension, a local viewer, a
validation script, or a container entrypoint. Until then, it should remain a
design consideration rather than new Jira scope.

---

## 9. Development Order

The correct order for Case 03 remains:

1. Build the Houdini simulation proof at node scale.
2. Export clean USD/VDB/curve/cache artefacts.
3. Validate the outputs against the USD architecture contract.
4. Document the runtime asset/cache contract.
5. Create the smallest local viewer proof.
6. Wrap the viewer in a reproducible runtime package.
7. Containerise only when the local runtime contract is stable.
8. Consider browser streaming or cloud GPU execution only after that.

Containerisation must not compete with the current objective: visible simulation
evidence and a credible USD pipeline.

---

## 10. Out Of Scope For Current Phase

The current phase should not create Jira scope for:

* a React frontend;
* a backend API;
* a render streaming service;
* Kubernetes manifests;
* cloud deployment scripts;
* Docker images containing heavy USD/VDB/textures;
* runtime code that assumes absolute workstation paths;
* a containerised Houdini production environment.

These may become useful later, but only after the Houdini simulation proof,
USD/cache package, and minimal local viewer contract are stable. The point is to
avoid spending production time on a runtime shell before there is a stable
payload for it to run.

---

## 11. Hiring Value

A container-ready runtime path improves the Case 03 story only if it supports the
core evidence:

* Houdini-authored simulation and cache production;
* clean OpenUSD composition;
* externalised heavy assets;
* runtime-readable telemetry and state metadata;
* reproducible viewer launch once the viewer exists.

The recruiter-facing message becomes:

> Case 03 is a digital twin tech pack with authored simulation evidence, a strict
> USD asset contract, and a planned reproducible runtime boundary.

The engineering-facing message becomes:

> The project separates authoring, asset packaging, telemetry schema, and future
> runtime execution instead of relying on one workstation-local scene.

---

## 12. Decision

Case 03 should remain **Houdini-first and USD-contract-first** in the current
phase.

Future viewer work should be designed as **container-ready runtime packaging**,
but actual container implementation should wait until the USD/cache package and
minimal local viewer contract are proven.
