# ADR 007: USD Runtime Asset Pipeline

**Date:** 2026-02-23
**Status:** Accepted, revised 2026-07-06

## Context

Case 03 is moving toward **Blackwell Monitoring Suite**, a staged Omniverse Kit
runtime that consumes hydrated OpenUSD assets from `assets/_external/`.

The earlier architecture described the final digital-twin target as a strict
160-node data center with payloads, LOD variants, instancing, material
centralization, telemetry primvars, and state-driven visual modes. That target
is still useful, but it must not be confused with the current implementation
state.

The current work starts smaller:

- Blackwell Monitoring Suite v0.1 loads one configured USD asset, the Noctua
  NH-D9 TR5-SP6 CPU cooler.
- Later stages add lighting, synthetic telemetry, telemetry-driven fan motion,
  full server loading, cached simulation playback, workload preview states, and
  server/rack/data hall navigation.
- Houdini remains the authoring and cleanup environment.
- The Kit runtime is a consumer and presentation surface, not a geometry, UV,
  material, or normal repair tool.

## Decision

Case 03 keeps a USD architecture knowledge base, but the guidance is split into
two levels:

1. **Current accepted baseline**
   Rules that exported assets and the staged runtime should follow now.

2. **Long-term target architecture**
   Rules that become mandatory only when the relevant staged runtime slice or
   full-scale scene requires them.

The files under `docs/knowledge_base/usd_architecture/` are therefore
engineering guidance, not proof that every listed feature is already
implemented.

## Current Accepted Baseline

The current baseline is:

- Root layers must declare `metersPerUnit = 1.0` and `upAxis = "Y"` unless a
  specific ingest rule documents a conversion.
- Heavy USD assets, textures, HDRIs, VDBs, and future runtime assets stay under
  the hydrated external asset package, not inside application source.
- Runtime-facing paths must be relative or explicitly configurable.
- OpenUSD assets should expose readable prim names and stable hierarchy where
  runtime code needs to address a part, such as the CPU cooler fan blades.
- Render meshes should be cleaned for Omniverse consumption: no NaN/Inf UVs,
  no face-varying primvar count mismatches, no known-invalid LOD variants, and
  final normals should be recomputed after geometry cleanup.
- `render`, `proxy`, and `guide` purpose usage is encouraged, but current asset
  behavior in Omniverse is the authority. LOD variants should remain disabled
  or deferred until LOD00 is stable.
- The runtime may report asset-side issues, but asset repair stays in
  Houdini/OpenUSD export tooling.

## Long-Term Target Architecture

The following remain valid targets for later server, rack, and data hall
stages:

- payloads for heavy scene components;
- references for lightweight layout and composition;
- stable component and subcomponent hierarchy for selection and review;
- centralized or shared material libraries where they reduce duplication;
- instancing or point instancing for repeated servers/racks when scale demands
  it;
- semantic scene groups and camera/bookmark definitions;
- telemetry primvars or equivalent runtime data bindings for visual state;
- cached simulation layers for airflow, heat, streamlines, or other qualitative
  engineering visualization;
- manual workload preview states such as `25%`, `50%`, `75%`, and `96%` once
  the USD package, material overrides, cache states, or runtime hooks exist.

These targets are not v0.1 requirements.

## Consequences

- ADR007 no longer overclaims that the full 160-node digital twin pipeline is
  already implemented.
- The staged runtime plan becomes the source of truth for what Blackwell
  Monitoring Suite must implement next.
- USD architecture documents remain useful, but each one must distinguish
  current requirements from future-scale recommendations.
- Technical reviewers can see a clear boundary between authored assets,
  hydrated runtime packages, Kit runtime behavior, and future digital-twin
  expansion.
- Houdini-to-USD cleanup remains the correct place to fix geometry, UV,
  material, normal, LOD, and cache export problems.

## Related Documents

- [ADR 005: Asset Life Cycle & Hydration](005-asset-hydration.md)
- [ADR 006: Omniverse Runtime Boundary and Portability](006-omniverse-runtime-boundary.md)
- [Case 03 - Staged Runtime Plan](../plans/case%2003%20-%20staged%20runtime%20plan.md)
- `docs/knowledge_base/usd_architecture/`
