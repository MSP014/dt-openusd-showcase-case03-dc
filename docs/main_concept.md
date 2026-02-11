# Case 03: Data Center (AI Inference Refinery) concept

> **Philosophy:** "Reproducible Tech Pack" — A self-contained, data-driven Digital Twin prototype that demonstrates the complete loop from telemetry to physical simulation.

## 1. High-Level Concept

**Project:** Autonomous NVIDIA Omniverse Kit Application.
**Goal:** Visualise the "Viral Inference Surge" — a dynamic scenario where a sudden spike in AI model requests triggers a sequential ramp-up of cooling and power systems.

Unlike traditional linear animation, this project is a **State Machine**. It does not play a pre-rendered movie; it simulates a system in real-time based on input data (mocked or real).

### Key Features

- **Data Abstraction Layer:** Decoupled logic where visual states are driven by normalised data streams (0.0 - 1.0), not keyframes.
- **Physical Correctness:** Aerodynamic and thermal behaviours are pre-simulated (CFD) but triggered dynamically.
- **Hybrid Visualisation:** Seamless switching between "Photorealistic" (Marketing View) and "Engineering X-Ray" (Technical View).

---

## 2. Interaction Design (UI/UX)

The user interacts via a custom **Control Panel** extension in Omniverse.

### A. Levels of Detail (LODs)

Navigation pivots between three scaling levels:

1. **Node (Micro):** Single Server Blade (SilverStone RM44). Focus on component thermals, fan RPM, and internal airflow.
2. **Rack (Meso):** 42U Cabinet. Focus on rack-level thermodynamics, pressure zones, and blind-mate connectivity.
3. **Room (Macro):** Data Center Hall (16+ Racks). Focus on row-based cooling dynamics and facility telemetry.

### B. Operational States (Simulation Matrix)

The system supports 4 discrete load states. Changing state instantly switches the underlying telemetry generation and visual assets.

| State | Load % | Description | Visual Cues |
| :--- | :--- | :--- | :--- |
| **Idle** | 0% | Standby / Maintenance | Low RPM, Cool ambient lighting, Laminar flow |
| **Nominal** | 25% | Routine Inference | Efficient cooling, steady green/blue status LEDs |
| **Surge** | 50% | High Traffic | Fans ramp up, heat signatures visible on exhaust |
| **Critical** | 85% | Thermal Throttling | Max RPM (Turbulent flow), Warning LEDs, Heat haze |

### C. Visual Modes

1. **Normal Mode:**
    - PBR Materials (Metal, Plastic, Glass).
    - VDB Volumetrics for airflow (Density/Temperature fields).
2. **Flow Vector Diagnostic (X-Ray):**
    - **Geometry:** Holographic/Fresnel shaders (Ghosted geometry).
    - **Airflow:** `BasisCurves` (Streamlines/Volume Trails) instead of VDB.
    - **Purpose:** Analyzing flow recirculation and dead zones without occlusion.

---

## 3. Technical Architecture

### Layer 1: Data Provider (The Brain)

A Python module (`src/data_provider`) that acts as the "Single Source of Truth".

- **Demo Mode:** Generates procedural sine-wave/noise data based on the selected State.
- **Live Mode (Placeholder):** Interface ready for MQTT/Kafka injection.
- **Output:** Normalised floats (e.g., `temp_celsius`, `fan_duty_cycle`, `power_draw_watts`).

### Layer 2: Simulation Core (The Factory)

Pre-calculated assets generated in Houdini (Solaris/PDG).

- **Format:** USD VariantSets.
- **Matrix:** 12 Cached States (3 LODs x 4 Ops).
- **Artifacts:**
  - `.vdb` (Density/Temperature grids)
  - `.usd` (BasisCurves for streamlines)
  - `.bgeo.sc` (Heavy geometry caches if needed)

### Layer 3: Omniverse App (The Frontend)

A Kit-based application that assembles the logic.

- **State Machine:** listents to Data Provider.
- **USD Composition:** Swaps active VariantSets based on State.
- **UI:** Custom window for "Manual Override" of the simulation parameters.

---

## 4. Implementation Strategy

**Objective:** Build a self-contained "Reproducible Tech Pack" demonstrating an L1 Digital Twin of an AI Inference Farm. The system will be data-driven, visualizing 4 distinct operational states across 3 levels of detail.

### Phase 1: Houdini Production (The Factory)

**Goal:** Generate the 12-state asset matrix (3 LODs x 4 Ops) and export optimized USD foundations.

#### 1.1. Base Geometry (Static)

- [ ] **Node (Micro):** Detail the *SilverStone RM44* asset (Blackwell Rig GB203).
  - [ ] Internal components (Mobo, 3x RTX PRO 4500 (GB203) GPUs, Fans) proxy geometry.
  - [ ] Texture baking (Diff/Rough/Norm).
- [ ] **Rack (Meso):** Procedural Layout (HDA).
  - [ ] Loop 40x Nodes.
  - [ ] Add Rack Frame, PDUs, Cabling (simplified).
- [ ] **Room (Macro):** Floorplan Layout (HDA).
  - [ ] Instancer for Racks (4-8 rows).
  - [ ] Facility walls, CRAC units, tiles.

#### 1.2. Simulation Setup (Dynamic)

- [ ] **CFD / Fluid Sim:** Setup generic "Airflow" VDB sim box.
  - [ ] **Input:** Collision geometry from Rack.
  - [ ] **States:**
    - Idle (Laminar, low velocity).
    - Nominal (Steady flow).
    - Surge (Higher velocity, some turbulence).
    - Critical (Turbulent, high velocity heat rejection).
- [ ] **Vector Field Gen:** Convert VDB velocity to `BasisCurves` (Streamlines).
- [ ] **Heatmap Gen:** Create 3D texture/vertex colors for "Thermal" overlay.

#### 1.3. Caching & Export

- [ ] **Batch Process:** ROP setup to iterate through:
    `[Node, Rack, Room] x [Idle, Nominal, Surge, Critical]`
- [ ] **Volume Optimization:** Prune VDBs density threshold.
- [ ] **Curve Optimization:** Resample curves, delete by attribute (visibly insignificant).

### Phase 2: Asset Packaging (The USD Structure)

**Goal:** Assemble the "Switchable" USD assets using VariantSets.

#### 2.1. Material Library

- [ ] **Lookdev:** Create MDLs.
  - [ ] `M_Server_Standard` (PBR).
  - [ ] `M_Server_XRay` (Translucent, additive).
  - [ ] `M_Airflow_Smoke` (Volume shader).
  - [ ] `M_Airflow_Lines` (Curve emission shader).

#### 2.2. Composition (VariantSets)

- [ ] **Master Structure:** `main.usd`
  - [ ] `variantSet: "OperationalState"` -> {`Idle`, `Nominal`, `Surge`, `Critical`}
    - [ ] Payload: Appropriate `.vdb` / `.usd` cache files.
  - [ ] `variantSet: "VisualMode"` -> {`Realistic`, `Engineering`}
    - [ ] Overrides: Material bindings on geometry.

### Phase 3: Omniverse App Logic (The Brain)

**Goal:** Create the interactive runtime environment.

#### 3.1. Data Provider (Python)

- [ ] Create `src/data_provider.py`.
  - [ ] Class `TelemetryGenerator`:
    - `get_data(state_enum)` -> returns dict `{rpm, temp, power}`.
    - Sine wave generators for "alive" feeling.

#### 3.2. Kit Extension

- [ ] Create `exts/omni.ai.refinery/`.
  - [ ] `extension.toml`: Dependency declaration.
  - [ ] `ui.py`: Window with:
    - Dropdown: "LOD" (Camera Jump).
    - Segmented Control: "State" (Idle -> Critical).
    - Toggle: "X-Ray Mode".

#### 3.3. State Machine Wiring

- [ ] **Event Listener:**
  - On UI Change -> Trigger USD Variant selection.
  - Smooth camera transition (optional).

### Phase 4: Polish & Delivery

- [ ] **Lighting:** Bake or real-time setup for "Moody" server room.
- [ ] **Performance Tuning:** Profile FPS.
  - Adjust Point Instancer settings.
  - Reduce curve counts if GPU bound.
- [ ] **Documentation:** `README.md` "How to Run".
