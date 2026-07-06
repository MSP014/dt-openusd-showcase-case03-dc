# 00. Case 03 USD Architecture Baseline

This document defines the current OpenUSD baseline for Case 03 assets and the
long-term target architecture for Blackwell Monitoring Suite.

The baseline applies now. The long-term target applies only when the staged
runtime reaches the server, rack, data hall, telemetry, cache, or scale features
that require it.

## 1. Current Baseline

- **MetersPerUnit:** `1.0`.
- **UpAxis:** `Y`.
- Runtime-facing paths must be relative or explicitly configurable.
- Heavy USD, texture, HDRI, VDB, and future cache assets live under the
  hydrated external asset package, not inside application source.
- Assets should expose readable prim names and stable hierarchy for parts that
  runtime code needs to address.
- Render meshes should be cleaned for Omniverse consumption:
  - no `NaN` or `Inf` UV values;
  - no face-varying primvar count mismatches;
  - final normals recomputed after geometry cleanup;
  - unvalidated LOD variants disabled or deferred until LOD00 is stable.

## 2. Current Runtime Root

Blackwell Monitoring Suite v0.1 uses:

- application source root: `src/blackwell_monitoring_suite/`;
- runtime config: `configs/blackwell_monitoring_suite.v0.1.toml`;
- external asset root from that source root: `../../assets/_external/`;
- first asset id: `noctua_nh_d9_tr5_sp6`;
- first asset path under asset root: `usd/cpu_fan/cpu_fan.usd`.

## 3. Purpose and LOD Guidance

Purpose metadata (`render`, `proxy`, `guide`) is encouraged when it helps
Omniverse review and selection, but current rendered behavior is the authority.

LOD variants are target architecture, not a v0.1 requirement. If authored, they
should use stable naming and must be validated in Omniverse before being
exposed in the runtime.

Recommended future naming:

- VariantSet name: `LOD`;
- variants: `LOD0`, `LOD1`, `LOD2`;
- purpose tags applied to geometry leaf prims, not root component Xforms.

## 4. Payloads, References, and Instancing

Payloads, references, prototypes, and instancing are future-scale tools for
server, rack, and data hall composition. They are not required for the v0.1 CPU
cooler asset preview.

When scale requires them:

- references should describe lightweight layout and composition;
- payloads should contain heavy geometry;
- instances should point at stable prototypes;
- `instanceable = true` should live on instance pointers, not on the shared
  prototype asset itself.

## 5. Materials

Current assets may ship with practical material structure as exported from
Houdini, provided all texture/material paths are portable.

Centralized material libraries remain a future-scale recommendation when the
same material families are shared across many assets.

## 6. Telemetry

Telemetry primvars are future runtime data bindings. They are not required for
v0.1 asset preview.

When telemetry is implemented, use a versioned schema and keep the data
runtime-readable. Candidate keys:

- `primvars:telemetry:schemaVersion`;
- `primvars:server:id`;
- `primvars:telemetry:tempC`;
- `primvars:telemetry:powerW`.

The exact schema becomes mandatory only when the Synthetic Telemetry and later
visualization stages need it.
