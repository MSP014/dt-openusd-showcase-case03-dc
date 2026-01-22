# ADR 001: Naming Convention

## Status

Accepted

## Context

Inconsistent naming across files and repositories leads to pipeline friction and "where is that file?" fatigue. For Case 03 (Data Center), understanding which file is geometry and which is a "sensor reading" is critical.

## Decision

We will enforce the following naming rules:

### 1. Repository Naming

Format: `dt-omniverse-showreel-case##-[key]`

* **This Repo:** `dt-omniverse-showreel-case03-dc`
* **dt**: Digital Twin
* **omniverse**: Platform
* **showreel**: Project type
* **case03**: Sequence ID
* **dc**: Project Key (Data Center)

### 2. File Layers (Snake Case)

* `mesh_*` (Geometry - Static Racks/Servers)
* `mat_*` (Materials - MDL shaders)
* `light_*` (Lighting setups)
* `sim_*` (Simulation Data - Heatmap values, Fan curves)
* `sensor_*` (Data bindings or Logic schemas)

### 3. USD Suffixes

* `.usda`: ASCII (Human readable, git-friendly). Use for **logic**, **composition arcs** and **root layers**.
* `.usdc`: Binary (Performance). Use for heavy **geometry** and **caches**. **GITIGNORE this extension.**

### 4. Hierarchy Naming (Specific to Data Center)

* `Zone_[A-Z]` (e.g., `Zone_A`)
* `Rack_[0-99]` (e.g., `Rack_12`)
* `Unit_[0-42]` (e.g., `Unit_10` for standard server units)

## Consequences

* **Positive:** Clear distinction between "dumb" geometry and "smart" data layers.
* **Negative:** Requires strict discipline when generating procedural assets in Houdini to match these names.
