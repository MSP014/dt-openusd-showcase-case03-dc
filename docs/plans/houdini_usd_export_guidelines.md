# Houdini OpenUSD Export Guidelines (Case 03)

This document translates the theoretical rules from the `usd_architecture/` Knowledge Base into concrete Houdini Solaris node workflows.

## 1. Scene Globals ([01_scale_and_axis_protocol.md](../knowledge_base/usd_architecture/01_scale_and_axis_protocol.md))

Before any `usd_rop` or `usdrender_rop` node:

1. Append a **Configure Layer** LOP.
2. **Up Axis**: set explicitly to `Y`.
3. **Meters Per Unit**: set explicitly to `1.0`.
*Failure to do this will cause assets to import into Omniverse lying on their side and 100x too small.*

## 2. Setting Kinds ([03_asset_validator_kinds.md](../knowledge_base/usd_architecture/03_asset_validator_kinds.md))

Do not export untagged geometry. Use the **Configure Primitive** LOP:

* Select your main rack HDA output -> Set **Kind** to `Assembly`.
* Select individual server nodes inside the rack -> Set **Kind** to `Component`.
* Select GPUs/NICs -> Set **Kind** to `Subcomponent`.

## 3. Authoring Telemetry ([06_custom_attributes_telemetry.md](../knowledge_base/usd_architecture/06_custom_attributes_telemetry.md))

Inject data early in the SOP/LOP stream using an **Attribute Wrangle**:

```vex
// SOP Context Example
s@server:id = "RACK01_N" + itoa(@ptnum);
f@telemetry:tempC = fit(rand(@ptnum), 0, 1, 35.0, 85.0);
f@telemetry:powerW = 1200.0;
s@telemetry:schemaVersion = "1.0";
```

Ensure these are promoted to `primvars:` when bridging SOPs to LOPs (using the *SOP Import* node's attribute translation rules).

## 4. Instancing ([04_instancing_for_performance.md](../knowledge_base/usd_architecture/04_instancing_for_performance.md))

When scattering 160 servers into 16 racks:

1. Use the **Instancer** LOP (not standard copy-to-points outputting raw meshes).
2. The prototype input should be the heavily detailed `Component` (Payload references).
3. Ensure the instances output have `instanceable = true` metadata.
4. Pass the custom telemetry attributes (from Step 3) onto the generated instance points so Hydra can read them as Primvar Overrides.

## 5. Material Binding ([05_centralized_materials_library.md](../knowledge_base/usd_architecture/05_centralized_materials_library.md))

1. Use a **Material Library** LOP.
2. In the Save Path settings, do **not** embed materials in the current layer.
3. Export them using a relative path: `../materials/materials_library.usda`.
4. Ensure bindings point to this relative location.
