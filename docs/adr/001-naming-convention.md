# ADR 001: Naming Convention & Standards

## Status

Accepted

## Context

For an Infrastructure Digital Twin (Data Center), clear distinction between static geometry and dynamic sensor data is critical. We need a standardised grammar to manage zones, racks, and units across composition layers.

## Decision

We will enforce the following naming and operational rules:

### 1. Repository Naming

Format: `dt-omniverse-showreel-case##-[key]`

* **Example:** `dt-openusd-showcase-case03-dc` (this repo)
* **dt**: Digital Twin
* **omniverse**: Platform
* **showreel**: Project type
* **case03**: Sequence ID
* **dc**: Project Key (Data Center)

### 2. File Layers (Snake Case)

* `mesh_*` (Geometry, e.g., `mesh_rack_A01`)
* `mat_*` (Materials / MDL)
* `light_*` (Lighting setups)
* `sim_*` (Simulation caches / thermal data)
* `sensor_*` (Data bindings or logic schemas)

### 3. USD Suffixes

* `.usda`: ASCII (Human-readable, git-friendly). Use for composition arcs and root layers.
* `.usdc`: Binary (Performance). Use for heavy geometry and high-frequency caches. **GITIGNORE this extension.**

### 4. Language Standards

* **Documentation**: All technical documentation and comments MUST be in **British English** (en-GB). Use `s` instead of `z` (e.g., *optimise*, *standardise*).
* **Commit Messages**: British English, imperative mood (e.g., "Add feature", not "Added feature").

### 5. Git Workflow

* **Branches**: `feature/description-of-change` or `fix/issue-id`.
* **Tags**: Use semantic versioning for milestones (e.g., `v1.0.0-gold`).

## Consequences

* **Positive:** Predictable file system, clear separation of binary vs text data, and consistent international documentation code.
* **Negative:** Requires initial setup discipline and cognitive load for suffix management.

### 6. Asset Specific Naming

* **Compute Nodes:** Use the chipset architecture code (e.g., `GB203`) rather than the commercial product name (e.g., `RTX 4500`) to emphasize engineering precision and versatility (Inference/Render/Compute).
  * **Approved:** `Blackwell Rig GB203`
  * **Rejected:** `Blackwell Rig PRO 4500`, `RTX 4500 Ada Rig`
