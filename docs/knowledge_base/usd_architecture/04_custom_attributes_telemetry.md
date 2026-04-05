# Guideline 04: Custom Attributes and Telemetry (v1.0)

To bridge the gap between Houdini's assembly environment, the Hydra render engine, and the FUI (Heads Up Display) in Omniverse, we leverage **Primvars (Primitive Variables)** strictly defined by a formal versioned schema. This operates faster than standard `customData` dictionaries and connects directly to viewport color tinting (e.g., thermal heatmaps).

## 1. The Telemetry Schema Contract (Case 02: v1.0)

We establish the following fixed fields across the Case 02 architecture. By storing this in the `primvars:` namespace, Hydra can read it instantly for shading, and Python can query it for UI/logic.

### Schema Header

* `primvars:telemetry:schemaVersion` = `"1.0"` (String)
  * **What it is:** The global tracker so future automation scripts know which parsing logic to use.

### Specific Sensor Data (Examples)

* `primvars:telemetry:rpm` (Float)
  * **What it is:** The rotations per minute for the Fan, IPC, or HPC shafts. Used to drive rotational blur and FUI dials.
* `primvars:telemetry:egtC` (Float)
  * **What it is:** Exhaust Gas Temperature in Celsius. Used to tint turbine stators and blades (incandescence) at render time.
* `primvars:telemetry:fuelFlow` (Float)
  * **What it is:** The rate of fuel injection.

## 2. Authoring Data in Houdini (The Workflow)

The Digital Twin supervisor should **not** need to manually tag 10,000 engine parts with Python scripts. The geometry must arrive fully self-labeled according to the v1.0 schema.

> [!IMPORTANT]
> **Houdini Implementation:**
> Inject these attributes globally through an **Attribute Wrangle** in SOPs/LOPs before writing out the USD payloads.
> Write them as explicitly varying or constant primvars so they translate natively to OpenUSD.
> Example: `@telemetry:egtC = 1250.0;`
> This creates a robust, API-queryable, and *Shader-readable* data contract.

---

## ✅ Definition of Done (DoD)

* [ ] The `primvars:telemetry:schemaVersion` attribute string returns `"1.0"` upon inspection.
* [ ] Telemetry data (`egtC`, `rpm`) exists directly in the `primvars:` namespace, **not** inside standard user `customData` metadata.
* [ ] Omniverse Python API can query these exact keys algorithmically to drive the FUI dashboards.
