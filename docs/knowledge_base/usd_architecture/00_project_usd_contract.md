# 00. Master USD Contract: Case 03

This document serves as the absolute baseline for all USD asset generation, validation, and assembly within the Case 03 Data Center project. It defines the rigid structural naming conventions and hierarchies that downstream tools and visualizers expect.

## 1. Scene Fundamentals

* **MetersPerUnit:** `1.0` (Meters)
* **UpAxis:** `Y`

## 2. LODs and Purpose (Geometry)

* **VariantSet Name:** Exactly `LOD` (not `lod`, `Lods`, etc.)
* **Variant Names:** `LOD0` (highest), `LOD1` (medium), `LOD2` (proxy/lowest).
* **Purpose Application:** Purpose attributes (`render`, `proxy`, `guide`) must be applied exclusively to `Geom` (Mesh/Curve) primitives, **not** to the root `Xform` of the component.

## 3. Instancing and Payload Hierarchy

* **Prototypes:** Must be stored under a designated scope (e.g., `/World/Prototypes/` or `/__Class__`).
* **Payload Location:** The heavy geometry Payload must be loaded *inside* the Prototype.
* **Instance Toggles:** The `instanceable = true` metadata must be set on the leaf pointers (the 160 individual server nodes) that reference the Prototype, never on the Prototype itself.

## 4. Asset Dependencies

* **Libraries:** All shader graphs must be isolated in `.usd`/`.usda` files under `materials/`.
* **Maps:** All bitmap textures must be isolated under `textures/`.
* **Binding:** Material bindings must use relative paths (e.g., `../materials/materials_library.usd`) resolving from the project root.

## 5. Telemetry Schema (v1.0)

All dynamic telemetric data must use the `primvars:` namespace for Hydra compatibility.

* `primvars:telemetry:schemaVersion` = `"1.0"` (String)
* `primvars:server:id` (String)
* `primvars:telemetry:tempC` (Float)
* `primvars:telemetry:powerW` (Float)
