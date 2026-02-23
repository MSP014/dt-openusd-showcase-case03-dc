# Guideline 01: Scale and Axis Setup

## 1. The Core Standard: Houdini Native

In the Case 03 Digital Twin project, the local authoring standard utilizes Houdini's native settings. This ensures the initial procedural generation happens cleanly without continuous conversion math.

The fundamental laws for exported authored assets are:

* **Meters Per Unit**: `1.0` (1 Unit = 1 Meter)
* **Up-Axis**: `Y` (Y-Up)

## 2. Omniverse Auto-Resolution

OpenUSD is a self-describing format. As long as Houdini correctly embeds the layer metadata upon export, compliant platforms (like Omniverse) will read the `upAxis = "Y"` and `metersPerUnit = 1` and automatically apply a `unitsResolve` transform to ensure the assets appear at the mathematically correct scale relative to Z-Up/Centimeter worlds.

## 3. Configuring in Houdini (Solaris)

To ensure compliance, use the `Configure Layer` LOP before writing to disk:

1. Append a **Configure Layer** node before your USD ROP.
2. In the properties, ensure **Up Axis** is set to `Y`.
3. Ensure **Meters Per Unit** is set to `1.0`.

## 4. Pipeline Defense: Ingesting External Assets
>
> [!CAUTION]
> Purchased assets or libraries (e.g., NVIDIA Isaac Sim assets) often default to Z-Up and Centimeters (0.01).
> **Rule:** All external assets must pass through an automated ingestion script that reads their `metersPerUnit` and `upAxis`. The script must either bake the transform or apply a rigid root `Xform` correction before the asset is allowed into the Case 03 master assembly.

---

## ✅ Definition of Done (DoD)

* [ ] Every exported root layer explicitly contains `metersPerUnit=1.0` and `upAxis=Y`.

* [ ] Omniverse import requires **zero** manual rotation or scaling adjustments.
* [ ] An automated pre-flight script reads the root layer metadata and fails the pipeline if external assets conflict without a resolving `Xform`.
