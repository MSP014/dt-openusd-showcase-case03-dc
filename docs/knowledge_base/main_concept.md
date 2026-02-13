# Case 03: Data Center (AI Inference Refinery) concept

> **Philosophy:** "Reproducible Tech Pack" — A self-contained, data-driven Digital Twin prototype that demonstrates the complete loop from telemetry to physical simulation.

## 1. High-Level Concept: The "Forced-Flow" Inference Refinery

**Project:** Autonomous NVIDIA Omniverse Kit Application.
**Mission:** Visualise the "Viral Inference Surge" — a dynamic scenario where a sudden spike in AI model requests triggers a sequential ramp-up of cooling and power systems.
**Engineering Logic:** A unified "Air-Energy" design where the entire facility acts as a single machine, not just a room of isolated servers.

### The Ecosystem (Three Scales)

#### 1. Level Node (Micro): Blackwell Rig GB203

* **Base Unit:** Custom 4U Node (SilverStone RM44 chassis).
* **Configuration:** AMD Threadripper PRO 7975WX + 3x NVIDIA RTX PRO 4500 (GB203).
* **Dynamics:** Internal fans (Arctic P12/P8) act as *flow accelerators*, not primary pumps. The node maintains positive pressure to prevent dust ingress and dead zones.
* **Thermodynamics:** The 1600W PSU is treated as an active heat source (~84W waste heat), ensuring correct thermal signatures in X-Ray mode.

### Key Features

* **Data Abstraction Layer:** Decoupled logic where visual states are driven by normalised data streams (0.0 - 1.0), not keyframes.
* **Physical Correctness:** Aerodynamic and thermal behaviours are pre-simulated (**Fluid Dynamics**) but triggered dynamically.
* **Hybrid Visualisation:** Seamless switching between "Photorealistic" (Marketing View) and "Engineering X-Ray" (Technical View).

#### 2. Level Rack (Meso): The Containment System

* **Blue Zone (Intake):** Blowers force cold air into the plenum, "feeding" the nodes.
* **Red Zone (Exhaust):** Active extraction removes waste heat (~15-16 kW/rack).
* **Metric:** **Cooling Efficiency Factor (CEF)** measures the effort required to cool the rack. It acts as a bridge between raw Node power and Global PUE.

#### 3. Level Hall (Macro): Infrastructure

* **Circuit:** Closed-loop system (Plenum -> Racks -> Exhaust -> CRAH/Chiller -> Recirculation).
* **Scale:** 16 Racks (160 Nodes) handling ~0.3 MW total load.
* **Key Metric:** **PUE (Power Usage Effectiveness)**.

---

## 2. Interaction Design (UI/UX)

The user controls the "Viral Surge" scenario via a custom Omniverse Extension.

### A. Operational States (Simulation Matrix)

Transitions between states are handled via a **5-frame Cross-Dissolve** on the **Pyro Shader layer** (Fade-Out Old / Fade-In New) to ensure smooth visual continuity without affecting static geometry.

| State | Load | Description | Visual Cues |
| :--- | :--- | :--- | :--- |
| **Idle** | 0% | Standby / Maintenance | Min RPM, Laminar Flow, Cool Lighting. |
| **Nominal** | 25% | Routine Inference | Efficient cooling, steady LED status. |
| **Surge** | 50% | High Traffic | Fans ramp up, balanced power/thermal profile (incl. PSU heat). |
| **Critical** | 85% | **"Inference Surge"** | Max RPM (Turbulent Flow), Heat Haze (GPU+PSU), Warning LEDs. |

### B. Visual Modes

* **Normal Mode:** Photorealistic PBR (Metal, Plastic, Glass).
* **Engineering X-Ray:**
  * **Geometry:** Ghosted/Holographic.
  * **Airflow:** Vector Lines / Streamlines (Pyro Velocity).
  * **Purpose:** Visualizing the invisible (airflow paths, dead zones, turbulence).

### C. Unified Dashboard (Real-time Telemetry)

| Level | Power ($P$) | Airflow ($V$) | Thermal ($T$) |
| :--- | :--- | :--- | :--- |
| **Node** | $P_{node}$ (W), $\eta_{PSU}$ | $RPM_{internal}$ | $T_{die}$ (CPU/GPU), $T_{psu}$ (~84W) |
| **Rack** | $P_{rack}$ (kW), $CEF$ (Cooling Effort) | $\Delta P_{plenum}$ (Pa) | $T_{exhaust\_avg}$ |
| **Hall** | $P_{total}$ (MW), PUE | $V_{total}$ ($m^3/h$) | $T_{coolant}$ (In/Out) |

---

## 3. Technical Architecture

### Layer 1: Data Provider (The Brain)

A Python module (`src/data_provider`) that acts as the "Single Source of Truth".

* **Demo Mode:** Generates procedural sine-wave/noise data based on the selected State.
* **Live Mode (Placeholder):** Interface ready for MQTT/Kafka injection.
* **Output:** Normalised floats (e.g., `temp_celsius`, `fan_duty_cycle`, `power_draw_watts`).

### Layer 2: Simulation Core (The Factory)

Pre-calculated assets generated in Houdini (Solaris/PDG).

* **Format:** USD VariantSets.
* **Matrix:** 12 Cached States (3 LODs x 4 Ops).
* **Artifacts:**
  * `.vdb` (Density/Temperature grids)
  * `.usd` (BasisCurves for streamlines)
  * `.bgeo.sc` (Heavy geometry caches if needed)

### Layer 3: Omniverse App (The Frontend)

A Kit-based application that assembles the logic.

* **State Machine:** listents to Data Provider.
* **USD Composition:** Swaps active VariantSets based on State.
* **UI:** Custom window for "Manual Override" of the simulation parameters.

---

## 4. Implementation Strategy

**Objective:** Build a self-contained "Reproducible Tech Pack" demonstrating an L1 Digital Twin of an AI Inference Farm. The system will be data-driven, visualizing 4 distinct operational states across 3 levels of detail.

### Phase 1: Houdini Production (The Factory)

**Goal:** Generate the 12-state asset matrix (3 LODs x 4 Ops) and export optimized USD foundations.

#### 1.1. Base Geometry (Static)

* [ ] **Node (Micro):** Detail the *SilverStone RM44* asset (Blackwell Rig GB203). (See [Hardware Spec](./hardware_specification.md))
  * [ ] Internal components (Mobo, 3x RTX PRO 4500 (GB203) GPUs, Fans) proxy geometry.
  * [ ] Texture baking (Diff/Rough/Norm).
* [ ] **Rack (Meso):** Procedural Layout (HDA).
  * [ ] Loop 40x Nodes.
  * [ ] Add Rack Frame, PDUs, Cabling (simplified).
* [ ] **Room (Macro):** Floorplan Layout (HDA).
  * [ ] Instancer for Racks (4-8 rows).
  * [ ] Facility walls, CRAC units, tiles.

#### 1.2. Simulation Setup (Dynamic)

* [ ] **CFD / Fluid Sim:** Setup generic "Airflow" VDB sim box.
  * [ ] **Input:** Collision geometry from Rack.
  * [ ] **States:**
    * Idle (Laminar, low velocity).
    * Nominal (Steady flow).
    * Surge (Higher velocity, some turbulence).
    * Critical (Turbulent, high velocity heat rejection).
* [ ] **Vector Field Gen:** Convert VDB velocity to `BasisCurves` (Streamlines).
* [ ] **Heatmap Gen:** Create 3D texture/vertex colors for "Thermal" overlay.

#### 1.3. Caching & Export

* [ ] **Batch Process:** ROP setup to iterate through:
    `[Node, Rack, Room] x [Idle, Nominal, Surge, Critical]`
* [ ] **Volume Optimization:** Prune VDBs density threshold.
* [ ] **Curve Optimization:** Resample curves, delete by attribute (visibly insignificant).

### Phase 2: Asset Packaging (The USD Structure)

**Goal:** Assemble the "Switchable" USD assets using VariantSets.

#### 2.1. Material Library

* [ ] **Lookdev:** Create MDLs.
  * [ ] `M_Server_Standard` (PBR).
  * [ ] `M_Server_XRay` (Translucent, additive).
  * [ ] `M_Airflow_Smoke` (Volume shader).
  * [ ] `M_Airflow_Lines` (Curve emission shader).

#### 2.2. Composition (VariantSets)

* [ ] **Master Structure:** `main.usd`
  * [ ] `variantSet: "OperationalState"` -> {`Idle`, `Nominal`, `Surge`, `Critical`}
    * [ ] Payload: Appropriate `.vdb` / `.usd` cache files.
  * [ ] `variantSet: "VisualMode"` -> {`Realistic`, `Engineering`}
    * [ ] Overrides: Material bindings on geometry.

### Phase 3: Omniverse App Logic (The Brain)

**Goal:** Create the interactive runtime environment.

#### 3.1. Data Provider (Python)

* [ ] Create `src/data_provider.py`.
  * [ ] Class `TelemetryGenerator`:
    * `get_data(state_enum)` -> returns dict `{rpm, temp, power}`.
    * Sine wave generators for "alive" feeling.

#### 3.2. Kit Extension

* [ ] Create `exts/omni.ai.refinery/`.
  * [ ] `extension.toml`: Dependency declaration.
  * [ ] `ui.py`: Window with:
    * Dropdown: "LOD" (Camera Jump).
    * Segmented Control: "State" (Idle -> Critical).
    * Toggle: "X-Ray Mode".

#### 3.3. State Machine Wiring

* [ ] **Event Listener:**
  * On UI Change -> Trigger USD Variant selection.
  * Smooth camera transition (optional).

### Phase 4: Polish & Delivery

* [ ] **Lighting:** Bake or real-time setup for "Moody" server room.
* [ ] **Performance Tuning:** Profile FPS.
  * Adjust Point Instancer settings.
  * Reduce curve counts if GPU bound.
* [ ] **Documentation:** `README.md` "How to Run".
