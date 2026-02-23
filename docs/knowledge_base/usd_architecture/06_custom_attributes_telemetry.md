# Guideline 06: Custom Attributes & Telemetry

A critical difference between a 3D visual render and a "Digital Twin" is data.

To bridge the gap between Houdini's assembly environment, the Hydra render engine, and external telemetry software, we leverage **Primvars (Primitive Variables)** strictly defined by a formal versioned schema. This operates faster than standard `customData` dictionaries and connects directly to viewport color tinting (heatmaps).

## 1. The Telemetry Schema Contract (v1.0)

We establish the following fixed fields across the Case 03 architecture. By storing this in the `primvars:` namespace, Hydra can read it instantly for shading, and Python can query it for UI/logic.

If integrating external databases, map them precisely to these keys:

### 1. `primvars:telemetry:schemaVersion` = `"1.0"` (String)

* **What it is:** The global tracker so future automation scripts know which parsing logic to use.

### 2. `primvars:server:id` (String)

* **What it is:** Unique node identifier matching external monitoring logs or CRM.
* **Example:** `"DC01_RACK05_NODE12"`

### 3. `primvars:telemetry:tempC` (Float)

* **What it is:** The real-time temperature telemetry status in Celsius (used by visualizers to tint objects red, orange, or green at render time without unpacking payloads).
* **Example:** `45.5`

### 4. `primvars:telemetry:powerW` (Float)

* **What it is:** The strict wattage drawn by the system for power load simulation and cooling capacity calculations.
* **Example:** `1500.0`

---

## 2. Authoring Data in Houdini (The Workflow)

The Digital Twin consumer (using Omniverse or a custom application) should **not** need to manually tag 160 servers with Python scripts. The geometry must arrive fully self-labeled according to v1.0 schema.

> [!IMPORTANT]
> **Houdini Implementation:**
> Inject these attributes globally through an **Attribute Wrangle** in SOPs/LOPs.
> Write them as explicitly varying or constant primvars so they translate natively to OpenUSD.
> Example: `@server:id = "RACK01_N01"`, `@telemetry:tempC = 40.0;`.
> This creates a robust, API-queryable, and *Shader-readable* data contract.

---

## ✅ Definition of Done (DoD)

* [ ] The `primvars:telemetry:schemaVersion` attribute string returns `"1.0"` upon inspection.

* [ ] Telemetry data (`tempC`, `powerW`) exists directly in the `primvars:` namespace, **not** inside standard user/`customData` metadata.
* [ ] Omniverse Python API can query these 4 exact keys algorithmically.
