# Guideline 01: Payloads, References, and Assembly

Managing memory (RAM/VRAM) is the primary bottleneck when assembling a Level 1 Digital Twin of a jet engine with 10,000+ individual CAD components. We solve this using careful USD **Composition Arcs**.

---

## 1. References (Immediate Load)

* **What it is:** The asset is loaded into memory the moment the stage opens.
* **When to use:** Use for lightweight structures, organizational `Xforms`, scene layouts, metadata, and proxy objects.
* **Rule for Case 02:** The top-level skeleton of the engine (`/Engine/Fan`, `/Engine/Compressor_HPC`) should be referenced. This allows an engineer to see the structure of the engine instantly without loading the heavy geometry.

## 2. Payloads (Deferred/Lazy Load)

* **What it is:** The asset definition is known, but the heavy data is not loaded into memory until explicitly requested ("Load Payload").
* **When to use:** Use for ALL heavy high-poly CAD/STL geometry (the actual fan blades, turbine discs, complex casing shells) and heavy Houdini simulation caches (VDBs, heavy point clouds).
* **Rule for Case 02:** The actual mechanical parts must be stored behind Payloads. When the file is opened, the user sees a lightweight proxy stand-in. They can right-click and "Load Payload" only on the specific engine module (e.g., the Combustion Chamber) they are actively inspecting, saving massive amounts of RAM.

## 3. Best Practice Assembly Workflow

1. **Asset Structure:** Use references to bring in the organizational `Xform` hierarchy.
2. **Heavy Data:** Place the high-fidelity geometry and heavy `.vdb` caches behind payloads within those referenced assemblies.
3. **Scene Interaction:** The Omniverse stage opens instantly. The engineer selectively loads payloads as needed for analysis.

---

## ✅ Definition of Done (DoD)

* [ ] The master `/Engine` assembly file opens in under 5 seconds because all heavy CAD components are payloaded.
* [ ] The project folder structure separates lightweight assembly files from heavy payload `.usd` files.
