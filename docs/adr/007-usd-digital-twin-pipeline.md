# ADR 007: USD Digital Twin Pipeline Architecture

**Date:** 2026-02-23
**Status:** Accepted

## Context

Case 03 (Data Center) requires assembling a massive Digital Twin comprising 160 high-density server nodes (GB203). To maintain reliable framerates, eliminate memory bloat, and ensure dynamic telemetry (heatmaps, power draw) functions correctly in Omniverse, we required a hardened, engineering-grade OpenUSD project structure.

## Decision

We have established a rigid "Case 03 Protocol Pack v0.1" for all OpenUSD authoring and assembly.
This pipeline is not a recommendation; it is a strict engineering contract.

The architecture is governed by the following atomic protocols located in `docs/knowledge_base/usd_architecture/`:

* **`00_project_usd_contract.md`**: The Master USD Contract defining variant names, geometry-level purposes, and schema versions.
* **`01_scale_and_axis_protocol.md`**: Enforces a strict Y-Up, Meters local authoring standard (Houdini Native).
* **`02_payloads_references_and_lods.md`**: Mandates Payloads for heavy geometry and explicitly separated LOD VariantSets for Proxy/Render purposes.
* **`03_asset_validator_kinds.md`**: Defines project UX rules enforcing `Assembly` -> `Component` -> `Subcomponent` hierarchies.
* **`04_instancing_for_performance.md`**: Mandates Point Instancing for server racks, utilizing Primvars for unique thermal overrides.
* **`05_centralized_materials_library.md`**: Establishes a single source of truth for all materials (`materials/materials_library.usda`) to decouple Lookdev from Asset generation.
* **`06_custom_attributes_telemetry.md`**: Formats the physical data contract allowing Omniverse Hydra renderers and Python APIs to query standard keys (`primvars:telemetry:tempC`, etc.) out of the box.

## Consequences

* **Positive:** Omniverse scenes will open faster, navigate smoothly via Proxies, render correctly with high-fidelity variants, and connect instantly to real-world data simulations without custom translation scripts.
* **Negative:** TD pipeline strictness is high. External assets (like those purchased or imported from Isaac Sim) MUST be scrubbed and converted to match the contract (e.g., baking Z-Up to Y-Up) before ingestion.
