# Case 03: Hardware Specification & Rack Integration

> [!NOTE]
> For rules regarding how this hardware is translated into 3D assets (Scale, Instancing, Kinds, Telemetry), refer to the [USD Architecture Guidelines](./usd_architecture/).

## 📋 High-Level Narrative

The project visualises an **Industrial-Scale AI Inference Farm**, designed to serve flagship Large Language Models (LLMs) like **NVIDIA Nemotron-3**.

Unlike a traditional "batch" render farm, this "Refinery" acts as a live machine that transforms enormous electrical capacity into mass token generation. The showreel focus is on **Dynamic Scaling**: showing how the physical infrastructure responds to a sudden surge in LLM request volumes.

## 🎯 The Scenario: "Viral Inference Surge"

1. **Incoming Load**: A massive spike in user requests hits the data centre.
2. **Sequential Ignition**: The Load Balancer/Scheduler cascades the activation of servers across 16 racks.
3. **Visual Delta**: The room transitions from a "Cold/Idle" state (Blue) to a "Heavy Load/Working" state (Orange-Red Heatmap).
4. **Airflow Reaction**: As nodes activate, cooling fans ramp up, creating visible turbulence (simulated in Houdini) that vibrates the overhead cabling and filters through the front meshes.

## 🖥️ Hardware Specification: Blackwell Rig GB203

To maximise **high-fidelity hardware visualisation for thermal/airflow storytelling**, the project uses a custom-designed **4U Air-Cooled Node** instead of standard rack-mount "fridges".

### Component List

| Component | Model / Detail | Justification |
| :--- | :--- | :--- |
| **Chassis** | **SilverStone RM44** (4U, E-ATX) | Industrial design with maximized front mesh for visible airflow simulation. Supports SSI-EEB boards. |
| **GPU Array** | **3× NVIDIA RTX PRO 4500 (GB203)** (32GB GDDR7) | Reduced from 4x to ensure physical fitment of the ConnectX-7 NIC and improved airflow. Rear power connectors eliminate cable clutter. |
| **CPU** | **AMD Ryzen Threadripper PRO 7975WX** (32C/64T) | High core count for independent task scheduling/preprocessing. |
| **RAM** | **512 GB DDR5-5600 ECC RDIMM** (8×64 GB) | Crucial buffer for large model weights. Optimized for **INT8 Quantization** (Nemotron-3 ~340GB). 8x64GB config maximizes the WRX90's 8-channel architecture without relying on unavailability of 128GB modules. |
| **Cooler** | **Noctua NH-D9 TR5-SP6** (4U) | Premium air-cooling solution that fits within 4U height constraints while providing visual detail for simulation. |
| **Motherboard** | **ASUS Pro WS WRX90E-SAGE SE** (SSI-EEB) | Massive connectivity for 4x GPUs and PCIe 5.0 speeds. |
| **PSU** | **be quiet! Dark Power Pro 13 1600W** (Titanium) | 1600W capacity handles the ~1400W peak load. 200mm length fits easily within the RM44's 255mm limit. |
| **Networking** | **ConnectX-7** (InfiniBand/400GbE) | Occupies the 7th (and final) PCIe slot. Essential for high-bandwidth RDMA in AI clusters. *See Network Constraint note below.* |

> [!NOTE]
> **Historical Config**: For a traditional *Render Farm* role, utilizing all 4 GPUs would be viable as rendering is less dependent on ultra-low latency inter-node communication (onboard 10GbE would suffice). However, the **AI Inference** role mandates the ConnectX-7 for RDMA, necessitating the 3-GPU tradeoff to free up a PCIe slot.
> **Modelling Disclaimer (Asset Provenance & Sim-to-Real Fidelity)**: To build this demonstration without access to original manufacturer CAD data, all server internals were modelled manually based on public photographic references. The focus of this tech pack is the USD pipeline, structural logic, and procedural data interpolation, not millimeter-perfect hardware replication. These assets act as high-fidelity visual proxies representing the mass and airflow impedance of the real hardware.

### 🛠️ Engineering Justification

#### 1. Power Analysis (TDP vs. PSU)

* **CPU Load**: Threadripper 7975WX (350W TDP) can peak at **~500W+** with PBO enabled under heavy inference preprocessing load.
* **Hardware Shift**: Dropping the 4th GPU reduces node power draw to **~1200W**, increasing PSU efficiency headroom to ~75% (sweet spot).
* **Verdict**: The **1600W Titanium PSU** provides ample headroom. The decision to use 3 GPUs + 1 NIC solves the physical "PCIe crowding" issue on the ASUS WRX90, ensuring every component has breathing room.

#### 1a. Power Distribution & Redundancy Boundary

* **Facility-Level Resilience:** The 16-rack layout assumes upstream power protection outside the compute racks: facility/row UPS, generator-backed distribution, overhead busway or power cable trays, and tap boxes feeding each rack.
* **Rack-Level Distribution:** Compute racks have no spare U-space for 1U UPS or rack ATS units. Power enters through rear vertical 0U PDU strips fed from the facility distribution layer, keeping protection and switching hardware outside the occupied 42U envelope.
* **A/B Load Allocation:** Single-cord compute nodes are distributed across the two rear PDU strips in an alternating pattern: Nodes 01/03/05/07/09 connect to Feed A, while Nodes 02/04/06/08/10 connect to Feed B. This balances rack load and limits a single feed or PDU failure to half of the compute nodes rather than the full rack.
* **Switch Power Redundancy:** Each QM9700 leaf or spine switch uses 1+1 redundant, hot-swappable power supplies. PSU 1 connects to Feed A and PSU 2 connects to Feed B, so the network fabric remains powered through a single feed or PDU failure.
* **Node-Level Trade-off:** Each Blackwell Rig GB203 uses a single 1600W PSU, so node-local PSU redundancy is intentionally omitted. A PSU failure removes that node from service; resilience is handled by workload rescheduling across the cluster rather than by hot-swap 1+1 PSUs inside each RM44 chassis.
* **Design Rationale:** This boundary preserves GPU density, airflow clarity, and the cost-optimised "acceptable compute" premise. It should be represented explicitly in HUD/telemetry as a reliability trade-off, not hidden as an enterprise HA claim.

#### 2. Cooling & Airflow

* **Front-to-Back Airflow**: The SilverStone RM44 is selected specifically for its mesh front. The 4U height allows for large, low-RPM intake fans that create a massive volume of air movement.
* **Connectors**: The RTX PRO 4500 (GB203)'s tail-end power connector is crucial. It eliminates the "cable clutter" above the cards typical of consumer GPUs, allowing laminar airflow over the backplates and through the CPU cooler.

#### 3. The 400G Network Constraint (PCIe Bottleneck)

* **The Problem**: A single ConnectX-7 400G (NDR) card requires `~100 GB/s` of bidirectional bandwidth to operate at true Full-Duplex 400G (400Gbps in *both* directions simultaneously). A single PCIe 5.0 x16 slot only provides `~64 GB/s`.
* **The Official Nvidia Solution**: The *Nvidia ConnectX-7 Adapter Cards User Manual* specifies the use of an **Auxiliary Connection Card**, tethered to the main NIC via two internal Cabline CA-II Plus harnesses (black and white cables). This bridges a second PCIe 5.0 x16 slot to double the bandwidth to `128 GB/s`.
* **The Physical Reality**: The ASUS Pro WS WRX90E-SAGE SE has exactly 7 PCIe slots. Three RTX PRO 4500 GPUs (dual-slot) occupy slots 1-6. The main ConnectX-7 card occupies slot 7. **There is no physical space for the Auxiliary Card.**
* **The AI Inference Justification**: This `64 GB/s` bottleneck is acceptable. Unlike a traditional core router requiring massive bidirectional throughput, an LLM Inference node has highly asymmetric traffic (small prompt input, larger token output, internal P2P over PCIe). The single slot's `64 GB/s` is more than enough to saturate the 400G link in a single direction (which requires `~50 GB/s`), making the omission of the Auxiliary Card an acceptable, calculated engineering trade-off for maximum GPU density.

#### 4. Strategic & Economic Positioning

* **"Acceptable Compute" Philosophy**: Designed for scenarios where **H100/B200 clusters are unobtainable** (due to allocation/cost), yet consumer hardware is insufficient.
* **The RAM Reality**: While the GPU/CPU combo is "budget-optimized" compared to DGX, the **512GB ECC RAM** requirement pushes the node price significantly higher due to the 2025-26 memory crisis. This choice acknowledges that for LLM inference, **VRAM is the engine, but System RAM is the fuel tank** — and fuel is expensive right now. This is a deliberate trade-off: spending on capacity where it matters most for model loading.
* **INT8 Optimization**: The 512GB capacity is engineered to perfectly host quantized flagship models (like Nemotron-3 340B INT8 ~340GB) + KV Cache + OS, avoiding the need for exotic and unobtainable 1TB (128GB DIMM) configurations.

#### 5. Financial Justification (TFLOPS per Dollar)

* **The Targeted Scaling Strategy:** The physical constraints of the 4U SilverStone RM44 chassis and the massive 1600W Titanium PSU were deliberately chosen to be **over-provisioned**. This shell acts as a platform capable of handling up to 900W of GPU power, allowing for seamless "drop-in upgrades" to flagship **RTX PRO 5000 (GB202)** cards for clients commanding extreme workloads or Multi-Instance GPU (MIG) support.
* **The Mathematical Reality:** While the platform *can* host the flagship models, the baseline **RTX PRO 4500 (GB203)** was explicitly selected for the foundational deployment due to an unmatched Performance-per-Dollar (FP32 TFLOPS/$) profile:
  * **RTX PRO 4500 (GB203)**: 53.8 TFLOPS @ $2,999 = **17.9 TFLOPS per $1,000**
  * **RTX PRO 5000 72GB (GB202)**: 65.0 TFLOPS @ ~$6,300 = **10.3 TFLOPS per $1,000**
* **The Scale of Savings**: Choosing the high-ROI RTX PRO 4500 saves ~$9,900 per 4U Node compared to the 72GB PRO 5000 setup. When scaled to a standard 16-rack "Inference Refinery" (160 nodes / 480 GPUs), this singular engineering decision yields a **massive saving of over $1.58 Million USD**.
* **Verdict**: The node architecture is built for maximum scalability (up to the RTX PRO 5000 limit), but initialized with the RTX PRO 4500 to guarantee peak economic efficiency for "Acceptable Compute" clusters. *(Note: The absolute top-tier RTX PRO 6000 was dismissed; its 600W TDP per card breaks the 1600W Node envelope, pushing the design out of the consumer-chassis paradigm entirely).*

### 6. Rack Integration Strategy ("The Glass Tube")

The choice of the **SilverStone RM44** (consumer chassis) over a barebone sled is driven by the **"Forced Flow"** containment architecture:

* **Sealed Containment:** The rack features a **hermetic Glass Door** (front) and sealed steel side panels and rear wall. All active exhaust is handled by the servers' and switch's own internal fans — no separate exhaust turbine at the top of the rack.
* **Bottom Feed (Supply-Side Only):** A sealed bottom **intake plenum / air guide interface** occupies the bottom 1U slot. It does not contain the active fan hardware; it captures supply air from the raised-floor tile below and redirects it upward along the glass front door.
* **Forced Trajectory:** The rack acts as a pressurised plenum: cold air streams upward along the glass door and is drawn through the mesh fronts of all 10 servers and the QM9700 switch by their own ~100+ internal fans. Hot exhaust exits through the sealed rear wall into the Hot Aisle and returns to the CRAC via the overhead return duct.
* **No Top Exhaust Turbine:** The combined airflow capacity of the internal fans (3× ARCTIC BioniX P120 + 2× ARCTIC P8 Max + CPU cooler + 3× GPU blowers + 1× PSU fan per server, ×10 servers + 6× QM9700 fans) is sufficient to create the necessary negative pressure at the rear. A red exhaust turbine at the top is architecturally redundant and physically impossible given the fully occupied 42U.

#### Raised-Floor Fan Tile & Bottom Intake Plenum

The rack supply-air concept is based on active raised-floor fan tiles. The reference class is a **JetPanel-style fan-supported raised-floor tile**: a 600×600 mm perforated steel floor tile with integrated EC fans, approximately 39% free surface area, and performance classes around 2700-4000 m3/h per tile. For the full airflow estimate, see the [Rack Airflow Budget](./rack_airflow_budget.md).

For Case 03, the tile is treated as part of the facility floor system, while the rack retains a passive 1U intake interface:

* **Active Floor Layer:** A powered fan tile sits under the cold-side footprint of each compute rack, supplying cold air on demand from the underfloor plenum.
* **Rack Interface Layer:** The bottom 1U plenum seals against the floor tile area and turns the incoming vertical airflow into a front-door pressure zone.
* **Serviceability:** Because the fan module belongs to the raised-floor grid, the rack remains mechanically movable and easier to service.
* **Visual Contract:** Model the active component as a perforated floor tile with a visible EC-fan cassette below the grid, and model the rack component as a blue supply-air guide behind the glass door.

#### Compute Rack U-Space (Final)

| Position | Equipment | U |
| :--- | :--- | :---: |
| 42U (top) | NVIDIA Quantum-2 QM9700 Leaf Switch | 1U |
| 41U – 2U | 10× Blackwell Rig GB203 (4U each) | 40U |
| 1U (bottom) | Bottom Intake Plenum / Air Guide Interface | 1U |
| **Total** | **42U — zero free slots** | **42U** |

#### Central Network Rack U-Space (Final)

| Position | Equipment | U |
| :--- | :--- | :---: |
| 42U – 38U | 5× NVIDIA Quantum-2 QM9700 Spine Switch (C2P, standard orientation) | 5U |
| 37U – 29U | Optical Distribution Frames (ODF) — fibre patch panels | 9U |
| 28U – 24U | Management Ethernet Switches (e.g., 5× SN2201, 1U each) | 5U |
| 23U – 20U | NVIDIA UFM Telemetry Appliances (×2 Primary + Standby) | 4U |
| 19U – 8U | NVMe AI Storage Arrays | 12U |
| 7U – 2U | *(Reserved — future expansion / cable management panels)* | 6U |
| 1U (bottom) | Bottom Intake Plenum / Air Guide Interface | 1U |
| **Total** | **42U — 6U reserved for expansion** | **42U** |

> [!NOTE]
> **Switch Orientation:** All 5 Spine QM9700 switches use the **C2P (Connector-to-Power)** configuration: ports face the Cold Aisle (front) and fan exhausts exit towards the Hot Aisle (rear) — the factory-default orientation, opposite to the P2C Leaf switches in the compute racks.
> [!NOTE]
> **Modelling Reminder — Vertical 0U PDU strips:** Each compute rack requires **2× Vertical PDU strips** (0U, 3-phase, 32–63A), mounted flush against the left and right rear posts. Every server PSU (C19 connector) and the QM9700 plug into these strips. Each strip exits at the top via one thick three-phase cable (`~IEC 60309 32A`) that feeds upward into the dedicated power cable tray running to the room's electrical distribution panel. These are essential for rear-view visual realism and must be included in the compute-rack prototype asset.

## 🕸️ Network Topology & Switch Architecture

To orchestrate the massive RDMA traffic generated by 160 ConnectX-7 NICs, the refinery utilises a two-tier **Non-Blocking Fat-Tree (Leaf-Spine)** topology, built upon the **NVIDIA Quantum-2 QM9700** 400G NDR InfiniBand switches.

### 1. Compute Racks (Leaf / ToR)

* **Configuration**: Each of the 16 compute racks houses 10 Blackwell Nodes and exactly **1× QM9700 Leaf Switch** mounted at the Top-of-Rack (ToR).
* **Airflow Thermodynamics**: The switch utilises the **P2C (Power-to-Connector)** cooling configuration. It is mounted rear-facing, with its 6 fan modules pointing towards the Cold Aisle (front) and its 32 OSFP ports facing the Hot Aisle (rear), maintaining perfectly laminar front-to-back rack thermodynamics.
* **Cable Logistics**: 10 OSFP cables run vertically from the servers' rear ConnectX-7 ports into the switch (Downlinks). To maintain a 1:1 non-blocking oversubscription ratio, **10 OSFP cables** exit the switch vertically ascending into the ceiling cable trays (Uplinks).

### 2. Central Network Rack (Spine / MoR)

* **Configuration**: A single dedicated 42U rack houses the core routing logic of the cluster.
* **Fat-Tree Symmetry**: It contains **5× QM9700 Spine Switches**. To achieve non-blocking routing, the 10 uplinks from *each* of the 16 Leaf switches are divided equally (2 cables per Spine switch). The mathematics guarantee flawless 100% port utilisation: `16 Leaf switches × 2 cables = 32 filled ports per Spine switch`.
* **Visual Density ("Kitbashing")**: To ensure volumetric realism without exhausting modelling resources, the remaining U-space relies on procedural dummy assets (with blinking MDL LED matrices):
  * **8-10U of Optical Distribution Frames (ODF)** cascading fibre bundles.
  * **4-5U of Management Ethernet Switches** (e.g., SN2201) routing OOB IPMI traffic.
  * **4U of NVIDIA UFM Telemetry Appliances** managing the InfiniBand subnet.
  * **10-14U of NVMe AI Storage Arrays** caching local dataset batches.

### 3. VFX & Data Flow Visualisation

* **Intra-Node (P2P)**: High-speed memory sharing between the **3 GPUs** via PCIe 5.0. Visualised as rapid flashes within the server case.
* **Inter-Node (RDMA)**: Distributed memory pooling across the cluster via the Fat-Tree fabric. Visualised as **luminous flows** (Houdini VEX/VOPS) travelling through the overhead yellow cable trays between compute racks and the central Network Rack.
* **Deployment Scale**: 16 Compute Racks (8 vs 8 arrangement) + 1 Central Network Rack. 160 Nodes total (480 Blackwell GPUs). 21× QM9700 switches (16 Leaf + 5 Spine).

## Blackwell Rig Airflow Simulation Preview

Technical viewport preview of the 4U Blackwell Rig GB203 node used as the first airflow layout validation pass.

The current simulation turns the hero server from a static asset into a testable airflow volume: front intake, internal component obstruction, CPU cooler flow, rear exhaust fans, PSU exhaust, and cable-side turbulence are represented as separate flow regions.

These preview frames use Houdini-solved airflow caches as a qualitative validation layer for the hardware layout. They are intended to expose intake paths, component obstruction, recirculation hints, and exhaust directionality, not to claim a validated CFD benchmark.

Video preview: [Blackwell Rig Airflow Simulation Test](https://youtu.be/lDswlLGkTQ8?si=JAtLdAwG9q-KcYMw)

|  |  |
| --- | --- |
| ![Simulation domain / intake view](../img/previews/option.1.A.1150.png) | ![Internal airflow obstruction pass](../img/previews/option.1.B.1150.png) |
| Simulation domain / intake view | Internal airflow obstruction pass |
| ![Rear exhaust and fan interaction](../img/previews/option.1.C.1150.png) | ![Cable-side airflow validation](../img/previews/option.1.D.1150.png) |
| Rear exhaust and fan interaction | Cable-side airflow validation |

The streamline visualisation pass exposes velocity-field behaviour through the server interior and rear cable zone. These frames are used as technical preview material for the airflow look-dev stage before the rack-level simulation is promoted into the Omniverse scene.

|  |  |
| --- | --- |
| ![Velocity field overview](../img/previews/option.0.0051.A.1124.png) | ![CPU cooler and rear fan flow paths](../img/previews/option.0.0051.B.1124.png) |
| Velocity field overview | CPU cooler and rear fan flow paths |
| ![Rear exhaust directionality](../img/previews/option.0.0051.C.1124.png) | ![Cable-side turbulence and intake/exhaust flow](../img/previews/option.0.0051.D.1124.png) |
| Rear exhaust directionality | Cable-side turbulence and intake/exhaust flow |

## 🖼️ Hero Asset Gallery

## RTX PRO 4500 Hero Asset

*Procedural modelling & texturing of the Blackwell GB203 node.*

| | | | |
| :---: | :---: | :---: | :---: |
| ![RTX PRO 4500 Blackwell - 01](../img/rtx_pro_4500/rtx_pro_4500_-_01.png) | ![RTX PRO 4500 Blackwell - 02](../img/rtx_pro_4500/rtx_pro_4500_-_02.png) | ![RTX PRO 4500 Blackwell - 03](../img/rtx_pro_4500/rtx_pro_4500_-_07.png) | ![RTX PRO 4500 Blackwell - 04](../img/rtx_pro_4500/rtx_pro_4500_-_08.png) |
| *RTX PRO 4500 Blackwell - 01* | *RTX PRO 4500 Blackwell - 02* | *RTX PRO 4500 Blackwell - 03* | *RTX PRO 4500 Blackwell - 04* |

## ConnectX-7 Hero Asset

*Procedural modelling & texturing of the 400G NDR network interface card.*

| | | | |
| :---: | :---: | :---: | :---: |
| ![ConnectX-7 - 01](../img/connectx_7/connectx-7_01.png) | ![ConnectX-7 - 02](../img/connectx_7/connectx-7_04.png) | ![ConnectX-7 - 03](../img/connectx_7/connectx-7_07.png) | ![ConnectX-7 - 04](../img/connectx_7/connectx-7_08.png) |
| *ConnectX-7 - 01* | *ConnectX-7 - 02* | *ConnectX-7 - 03* | *ConnectX-7 - 04* |

## ASUS Pro WS WRX90E-SAGE SE Hero Asset

*Procedural modelling & texturing of the WRX90E motherboard.*

| | | | |
| :---: | :---: | :---: | :---: |
| ![ASUS Pro WS WRX90E-SAGE SE - 01](../img/ws_wrx90e/ws_wrx90e_01.png) | ![ASUS Pro WS WRX90E-SAGE SE - 02](../img/ws_wrx90e/ws_wrx90e_03.png) | ![ASUS Pro WS WRX90E-SAGE SE - 03](../img/ws_wrx90e/ws_wrx90e_04.png) | ![ASUS Pro WS WRX90E-SAGE SE - 04](../img/ws_wrx90e/ws_wrx90e_05.png) |
| *ASUS Pro WS WRX90E-SAGE SE - 01* | *ASUS Pro WS WRX90E-SAGE SE - 02* | *ASUS Pro WS WRX90E-SAGE SE - 03* | *ASUS Pro WS WRX90E-SAGE SE - 04* |

## Noctua NH-D9 TR5-SP6 Hero Asset

*Procedural modelling & texturing of the 4U Threadripper CPU cooler.*

| | | | |
| :---: | :---: | :---: | :---: |
| ![Noctua NH-D9 - 01](../img/cpu_fan/cpu_fan_01.png) | ![Noctua NH-D9 - 02](../img/cpu_fan/cpu_fan_03.png) | ![Noctua NH-D9 - 03](../img/cpu_fan/cpu_fan_06.png) | ![Noctua NH-D9 - 04](../img/cpu_fan/cpu_fan_07.png) |
| *Noctua NH-D9 - 01* | *Noctua NH-D9 - 02* | *Noctua NH-D9 - 03* | *Noctua NH-D9 - 04* |

## be quiet! Dark Power Pro 13 1600W Hero Asset

*Procedural modelling & texturing of the Titanium 1600W PSU.*

| | | | |
| :---: | :---: | :---: | :---: |
| ![be quiet! Dark Power Pro 13 - 01](../img/psu/psu_01.png) | ![be quiet! Dark Power Pro 13 - 02](../img/psu/psu_03.png) | ![be quiet! Dark Power Pro 13 - 03](../img/psu/psu_05.png) | ![be quiet! Dark Power Pro 13 - 04](../img/psu/psu_06.png) |
| *be quiet! Dark Power Pro 13 - 01* | *be quiet! Dark Power Pro 13 - 02* | *be quiet! Dark Power Pro 13 - 03* | *be quiet! Dark Power Pro 13 - 04* |

## SilverStone RM44 Chassis Hero Asset

*Procedural modelling & texturing of the 4U industrial server chassis.*

| | | | |
| :---: | :---: | :---: | :---: |
| ![SilverStone RM44 - 01](../img/chassis_rm44/rm44_01.png) | ![SilverStone RM44 - 02](../img/chassis_rm44/rm44_02.png) | ![SilverStone RM44 - 03](../img/chassis_rm44/rm44_03.png) | ![SilverStone RM44 - 04](../img/chassis_rm44/rm44_04.png) |
| *SilverStone RM44 - 01* | *SilverStone RM44 - 02* | *SilverStone RM44 - 03* | *SilverStone RM44 - 04* |
