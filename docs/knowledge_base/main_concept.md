# Case 03: Data Center (AI Inference Refinery) concept

> **Philosophy:** "Reproducible Tech Pack" — A self-contained, data-driven Digital Twin prototype that demonstrates the complete loop from telemetry to physical simulation.

## 1. High-Level Concept: The "Forced-Flow" Inference Refinery

**Project:** Autonomous NVIDIA Omniverse Kit Application.
**Mission:** Visualise the "Viral Inference Surge" — a dynamic scenario where a sudden spike in AI model requests triggers a sequential ramp-up of cooling and power systems.
**Engineering Logic:** A unified "Air-Energy" design where the entire facility acts as a single machine, not just a room of isolated servers.

### The Ecosystem (Three Scales)

#### 1. Level Node (Micro): Blackwell Rig GB203

* **Base Unit:** Custom 4U Node (SilverStone RM44 chassis).
* **Configuration:** AMD Threadripper PRO 7975WX + 3x NVIDIA RTX PRO 4500 (GB203). **Note (Targeted Scaling):** While the RTX PRO 4500 was explicitly chosen for its unmatched ROI—saving over **$1.58 Million USD** across a 16-rack cluster—the node's underlying architecture (1600W PSU / High-Airflow 4U) is intentionally **over-provisioned**. This allows for a zero-hassle "drop-in upgrade" to the flagship RTX PRO 5000 72GB for clients demanding MIG capability entirely within the same thermal envelope.
* **Dynamics:** Internal fans (Arctic P12/P8) act as *flow accelerators*, not primary pumps. The node maintains positive pressure to prevent dust ingress and dead zones.
* **Thermodynamics:** The 1600W PSU is treated as an active heat source (~84W waste heat), ensuring correct thermal signatures in X-Ray mode.

## RTX PRO 4500 Hero Asset

*Procedural modeling & texturing of the Blackwell GB203 node.*

| | | | |
| :---: | :---: | :---: | :---: |
| ![RTX PRO 4500 Blackwell - 01](../img/rtx_pro_4500/rtx_pro_4500_-_01.png) | ![RTX PRO 4500 Blackwell - 02](../img/rtx_pro_4500/rtx_pro_4500_-_02.png) | ![RTX PRO 4500 Blackwell - 03](../img/rtx_pro_4500/rtx_pro_4500_-_07.png) | ![RTX PRO 4500 Blackwell - 04](../img/rtx_pro_4500/rtx_pro_4500_-_08.png) |
| *RTX PRO 4500 Blackwell - 01* | *RTX PRO 4500 Blackwell - 02* | *RTX PRO 4500 Blackwell - 03* | *RTX PRO 4500 Blackwell - 04* |

### Key Features

* **Data Abstraction Layer (Procedural Telemetry Interpolation):** A core pipeline feature of the Digital Twin is transforming sparse, generic telemetry (e.g., standard HWiNFO or Grafana outputs like "Average GPU Temp" or "GPU Hotspot Temp") into highly granular, visually complex "per-component" data.
  * **The Algorithm:** The Python Data Provider takes the generic temperature value and uses a combination of proximity gradients and procedural noise to distribute hypothetical temperatures across the micro-components of the PCB. Components physically closer to the GB203 die (the hotspot) render hotter, while VRAM chips, inductors, and capacitors closer to the cooling turbine or further along the exhaust path render cooler.
  * **LED Traffic Simulation:** This exact same procedural noise engine—which calculates the thermal distribution during X-Ray mode—is repurposed when X-Ray is *inactive* (Normal Mode). It generates chaotic, erratic signals that drive the blinking of the network LEDs on the OSFP (ConnectX-7) and RJ-45 management ports, perfectly simulating heavy network traffic without the overhead of simulating actual data packets.
* **Physical Correctness:** Aerodynamic and thermal behaviours are pre-simulated (**Fluid Dynamics**) but triggered dynamically.
* **Hybrid Visualisation:** Seamless switching between "Photorealistic" (Marketing View) and "Engineering X-Ray" (Technical View), controlled directly via the HUD.

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

### B. Visual Modes & HUD-Driven Level of Detail (LOD)

The visualization scale and detail are controlled manually via a HUD toggle, *not* by dynamic camera tracking. This simple, robust approach ensures predictable presentation quality while navigating the scene.

#### HUD Navigation: Hierarchical Drill-Down

The user navigates between scales using a cascading HUD selector (conceptually similar to breadcrumbs):

1. **Hall Level (default):** All 16 racks are visible. User is at the top of the hierarchy.
2. **Rack Level:** User selects a specific rack (e.g., `Rack 03`) from the HUD dropdown. The scene focuses on that rack and its 10 nodes become individually distinguishable.
3. **Server Level:** User selects a specific node (e.g., `Rack 03 / Node 07`) from a secondary HUD dropdown. The scene isolates that server, removes the top cover, and loads the appropriate detailed state (Pyro smoke, HUD overlays, etc.).

Navigating *up* (e.g., from Server back to Rack or Hall) simply deselects the current entity and restores the parent view. This approach is far simpler to implement in Omniverse Kit than distance-based automatic LOD (which would require raycasts and frustum calculations) and gives the presenter full narrative control.

#### 1. Level Node (Micro - Server Scale)

* **Normal Mode:** Displays a specific server (e.g., pulled from a rack) with the top cover removed. Omniverse renders the pre-cached Pyro-simulation showing exactly how air moves through the chassis. **HUD overlays** pop up to display precise metrics: temperatures inside the GPUs, CPU, and PSU, alongside specific RPM values for the front chassis fans, rear exhaust fans, the PSU's internal fan, and the CPU cooler.
* **X-Ray Thermal Mode:** The Pyro smoke is hidden. A highly detailed **Thermal Heatmap** is projected directly onto the intricate internal geometry (extrapolated via the noise/gradient algorithm). To prevent visual clutter, the complex floating HUD numbers are disabled, replaced by a simple, clean temperature color scale (e.g., Blue = 30°C, Red = 95°C).
* **Velocity Vectors (Streamlines):** A dedicated toggle independent of the mapping. The node's solid geometry transitions into a semi-transparent 'hologram' (utilizing a Fresnel shader or wireframe mesh). Through these translucent guts, the user sees constantly evolving vector lines depicting the airflow. **Color-coding by Velocity:** These lines are colored based on airspeed magnitude—areas where the flow is calm appear Blue or Green (matching the lowest temps on the thermal scale), but as the flow is sucked through the front chassis fans, GPU turbines, CPU coolers, or PSU fans, the lines sharply transition to Red to visualize rapid acceleration.

#### 2. Level Rack (Meso - Rack Scale)

* **Normal Mode:** Closed rack view. Focuses on macro containment airflow. We no longer see internal server flow, but rather the holistic path: cold air rising from the raised floor, passing completely through the 4U nodes, and exhausting up into the ventilation channel above the rack.
* **X-Ray Thermal Mode:** The rack boundaries become semi-transparent holograms. Detail is aggregated: the Thermal Heatmap no longer highlights individual capacitors, but rather displays the averaged temperature of major sub-assemblies within each of the 10 servers (e.g., the entire block of GPU 2, GPU 3, the CPU block, or the PSU block).
* **Velocity Vectors:** Toggles on the streamline bundles flowing through the entire rack structure, allowing the user to trace the pressure zones from the floor to the ceiling exhaust, again color-coded by airspeed (Blue for ambient drift, Red for high-velocity extraction).

#### 3. Level Hall (Macro - Data Center Scale)

* **Normal Mode / X-Ray Thermal Mode:** The highest abstraction level. The minimal visible entity is now a complete server or network switch. The Thermal Heatmap averages the temperature of all internal guts into a single color for the entire 4U chassis. This allows an instant visual read of the holistic data center health, spotting over-taxed nodes or localized cooling failures across rows of racks.
* **Velocity Vectors:** Lines visualize the massive, room-scale air rivers circulating between the hot and cold aisles and the facility-level CRAH units.

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

* **Demo Mode:** Generates procedural sine-wave/noise data based on the selected Operational State. This is the default mode for the showreel and tech-pack demonstration.
* **Live Mode (Placeholder — upgrade path to a true Digital Twin):** The Data Provider exposes a clearly defined interface (`get_telemetry() -> dict`) that accepts the same normalized float payload from any external source. To connect real hardware monitoring, replace the Demo Mode generator with any standard data feed — HWiNFO64 (via its HTTP server plugin), Prometheus/Grafana (via API), or a streaming broker (MQTT, Kafka). **Zero changes required to the visualization layer.** This is the designed upgrade path for anyone who wants to adapt this Tech Pack into a genuine, production-grade Digital Twin of their own data center.
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

* **State Machine:** Listens to Data Provider.
* **USD Composition:** Swaps active VariantSets / attributes based on State.
* **UI:** Viewport-embedded HUD panel (`omni.ui.scene` overlay) for state control and telemetry readout.

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

> [!NOTE]
> **Architecture Contract:** All USD assembly, instancing, and telemetry formatting must strictly adhere to the engineering guidelines defined in [ADR 007: USD Digital Twin Pipeline Architecture](../adr/007-usd-digital-twin-pipeline.md) and the `usd_architecture` knowledge base.

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
  * [ ] `ui.py`: Viewport-embedded HUD (`omni.ui.scene` overlay):
    * **State Switcher**: segmented control `[IDLE] [NOMINAL] [SURGE] [CRITICAL]`.
    * **Demo Mode toggle**: ON → Data Provider generates synthetic data; OFF → awaits real data stream (MQTT/Kafka placeholder).
    * **Telemetry readout**: live display of `temp_celsius`, `fan_duty_cycle`, `power_draw_watts`.
    * **LOD / Camera Jump**: dropdown for viewport navigation.

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

---

## Implementation Notes (for future me)

> This section collects the **"how we fake it"** decisions so the concept sections above stay focused on *what we show*. Nothing here changes the vision; it's purely mechanics.
> [!NOTE]
> **Why synthetic data?** We have no access to a live data center or real server telemetry. The entire telemetry pipeline — from GPU temperatures to fan RPMs — is procedurally generated by the Data Provider module. The goal is to demonstrate a Digital Twin *concept* and prove technical artist competency: the ability to design and implement a convincing, data-driven, procedurally animated real-time visualization without relying on actual hardware. The system is intentionally architected so that real telemetry (HWiNFO, Grafana, MQTT, Kafka) can be hot-swapped in at any time with zero changes to the visualization layer.

### 1. Pyro: State Caches + Trigger Logic

* All airflow simulations are **pre-baked in Houdini** (Solaris/PDG) into a 12-state matrix: `[Node, Rack, Hall] × [Idle, Nominal, Surge, Critical]`.
* Cached as USD VariantSets (`.vdb` volumes + `BasisCurves` streamlines) — no live sim at runtime.
* State transitions use a **5-frame Cross-Dissolve** on the Pyro Shader layer (Fade-Out old / Fade-In new), applied only to the visual layer; static geometry is never touched.
* The Omniverse Kit State Machine listens to the Data Provider and triggers the appropriate VariantSet swap.

### 2. Telemetry → Heat: Gradient / Noise Mapping

* The Data Provider receives **two values per GPU**: `avg_core_temp` and `hotspot_temp` (same format as HWiNFO / Grafana output).
* A visualizer module takes these values and builds a per-component thermal map using:
  1. **Proximity Gradient**: Each micro-component (VRAM die, VRM inductor, capacitor) is assigned a weight based on its physical distance from the GB203 die (hottest) and the exhaust/turbine (coolest). The gradient maps `hotspot_temp` → `avg_exhaust_temp` across this distance.
  2. **Procedural Noise Offset**: A noise field adds ±N°C variation to each component so the result looks organic and non-uniform, not like a flat ramp.
* The same algorithm runs at each LOD scale, simply changing what "components" are addressed:
  * **Micro:** Individual VRAM chips, VRMs, inductors, caps.
  * **Meso:** Whole GPU block, CPU block, PSU block per server.
  * **Macro:** Entire 4U chassis → single averaged color.

### 3. LEDs: Reuse the Same Noise Field

* When X-Ray is **inactive** (Normal Mode), the same procedural noise field generated by the telemetry mapper is redirected to drive the `emission_intensity` Primvar on the LED meshes of the OSFP (ConnectX-7) and RJ-45 ports.
* This produces chaotic, realistic, non-synchronized blinking across all visible ports with zero extra computation — the noise was already being generated for the heatmap.
* LED blink frequency range scales with operational state (sluggish in Idle, aggressive strobing in Critical).

### 4. UI: HUD Drill-Down + Toggles

* **LOD Selector (breadcrumb):** `[Hall] → [Rack XX] → [Rack XX / Node YY]`. Switching level triggers a USD VariantSet swap + optional camera jump to the selected entity.
* **Operational State Switcher:** Segmented control `[IDLE] [NOMINAL] [SURGE] [CRITICAL]` — triggers both the VariantSet swap and the Data Provider state enum.
* **Per-LOD visualization toggles** (available at each scale):
  * `Normal Mode` / `X-Ray Thermal` — mutually exclusive; swapping hides Pyro, enables heatmap Primvars.
  * `Velocity Vectors` — independent toggle; activates streamline curves and switches geometry to `M_Server_Ghost` (Fresnel / wireframe) material.
* **X-Ray HUD simplification:** At Micro level, when X-Ray is active the dense metric overlays (RPM readouts, exact °C values) are hidden to avoid visual clutter; only the temperature color-scale legend is shown.

### 5. Perf: LOD / Payload Strategy

* Heavy geometry (full PCB detail with micro-components) is loaded as a **USD Payload** — only pulled in when Micro/Node level is selected.
* Rack and Hall levels use **Point Instancers** over simplified proxy meshes; no full-res geometry in memory.
* Streamline curves are aggressively resampled in Houdini before export; insignificant curves culled by length/velocity attribute.
* Target: stable 30+ FPS in Hall view; 24+ FPS in isolated Node view with Pyro active.
