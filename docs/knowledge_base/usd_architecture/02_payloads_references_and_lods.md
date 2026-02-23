# Protocol 02: Payloads, References, and LODs

Managing memory and rendering performance is the most critical challenge when assembling 160 high-density server racks. We solve this using two orthogonal USD mechanics working together: **Composition Arcs** (RAM optimization) and **Purposes** (GPU optimization).

---

## 1. Composition: References vs. Payloads (RAM Optimization)

This dictates *when* a file is loaded into the system's active memory.

### References (Orange Arrow)

* **What it is:** Immediate load.
* **When to use:** Use for lightweight structures, metadata, Xforms, and high-level scene layout.
* **Rule for Case 03:** Server racks as empty container structures can be referenced.

### Payloads (Blue Arrow)

* **What it is:** Deferred load (lazy loading).
* **When to use:** Use for ALL heavy geometry (the 160 GB203 servers, complex cabling meshes).
* **Rule for Case 03:** The actual heavy servers must be saved behind Payloads. When the file is opened, the user sees bounding boxes or empty locators, saving 80GB+ of RAM. They can right-click and "Load Payload" only on the specific row or rack they are actively inspecting.

---

## 2. LODs and Purpose Contract (GPU Optimization)

This dictates *what* the graphics card draws once the asset is actually loaded into RAM.

To avoid chaos between VariantSets and Purposes, Case 03 follows this strict contract (as defined in `00_project_usd_contract.md`):

1. **VariantSet Naming:** You must use a VariantSet named exactly `LOD` (not `lod` or `Lods`).
2. **Variants:** Inside the `LOD` VariantSet, build variants like `LOD0` (highest), `LOD1`, `LOD2`.
3. **Purpose Application:** Within any given LOD variant, attach the Purpose metadata (`proxy`, `render`, `guide`) strictly to the **Geom prims** (the actual meshes), **not** to the root Component Xform.

### The Omniverse Viewport Workflow

Because of this contract, a visualizer can load the payloads for the entire datacenter, but set the Omniverse viewport display filter to **Proxy**. Omniverse will instantly hide millions of polygons and display 160 lightweight proxy boxes.

For final rendering, path-tracers (like Hydra/Iray) evaluate the **Render** purpose, dynamically swapping the geometry at compute time.

---

## ✅ Definition of Done (DoD)

- [ ] Every heavily modeled Component (e.g., GB203 Server) has its main geometry stored as a Payload.
* [ ] The VariantSet for level of detail is universally named `LOD` across the project.
* [ ] Purpose tags (`proxy`, `render`) are applied to Geometry leaf nodes, never to root Xforms.
