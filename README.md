# Case 03: The "Forced-Flow" Inference Refinery

> [!WARNING]
> **Work in Progress:** This project is currently under active development. Some links and assets may be placeholders.

---

## 📋 Project Overview

A **Reproducible Tech Pack** demonstrating a High-Fidelity **L1 Digital Twin** of an AI Inference Farm.
Built strictly on the **Sim-to-Real** methodology, this pipeline demonstrates the complete architectural lifecycle: *Geometry Foundation → Synthetic Data Simulation → Live Data Integration → Real-time Telemetry Visualization*.

The project visualises a **"Viral Inference Surge"** — a dynamic stress-test scenario where a sudden 500% spike in LLM requests triggers a sequential ramp-up of cooling and power systems across a high-density data hall.

> **Why GB203, not the flagship?** The **RTX PRO 4500** delivers **17.9 TFLOPS per $1,000** — the best efficiency ratio at this tier. Across a 16-rack cluster, this translates to **$1.58M saved** versus the RTX PRO 5000 72GB, with no compromise on the architecture: the 4U chassis accepts a drop-in upgrade the moment VRAM requirements scale. *(The RTX PRO 6000's 600W TDP requires a different node class entirely.)*
>
> **Why 3 GPUs, not 4?** The node requires a 400G ConnectX-7 NIC for RDMA. On the 7-slot WRX90E motherboard, three dual-slot GPUs + one NIC perfectly maxes out the physical PCIe layout without bottlenecking the network card.
>
> → [📚 Knowledge Base Hub (Index)](./docs/knowledge_base/README.md) · [Architecture & Physics](./docs/knowledge_base/main_concept.md) · [Hardware Specification](./docs/knowledge_base/hardware_specification.md)

Unlike traditional linear animation, this ecosystem is a **State Machine**. It simulates the facility's physical response in real-time based on normalised telemetry data.

> [!NOTE]
> Synthetic Data Generation for Sim-to-Real: No real data center required. All metrics (GPU temps, fan RPMs, power draw) are generated procedurally by the Data Provider module to create high-quality demonstration data. This proves the full pipeline end-to-end before physical deployment.
> **Want a real Digital Twin?** The `Data Provider` exposes a standard interface — swap the synthetic generator for any real monitoring feed (HWiNFO64, Grafana, MQTT, Kafka) and the entire visualization layer works unchanged. This is the designed upgrade path for anyone adapting this Tech Pack to their own infrastructure.

## RTX PRO 4500 Hero Asset

*Procedural modeling & texturing of the Blackwell GB203 node.*

| | | | |
| :---: | :---: | :---: | :---: |
| ![RTX PRO 4500 Blackwell - 01](docs/img/rtx_pro_4500/rtx_pro_4500_-_01.png) | ![RTX PRO 4500 Blackwell - 02](docs/img/rtx_pro_4500/rtx_pro_4500_-_02.png) | ![RTX PRO 4500 Blackwell - 03](docs/img/rtx_pro_4500/rtx_pro_4500_-_07.png) | ![RTX PRO 4500 Blackwell - 04](docs/img/rtx_pro_4500/rtx_pro_4500_-_08.png) |
| *RTX PRO 4500 Blackwell - 01* | *RTX PRO 4500 Blackwell - 02* | *RTX PRO 4500 Blackwell - 03* | *RTX PRO 4500 Blackwell - 04* |

## ConnectX-7 Hero Asset

*Procedural modeling & texturing of the 400G NDR network interface card.*

| | | | |
| :---: | :---: | :---: | :---: |
| ![ConnectX-7 - 01](docs/img/connectx_7/connectx-7_01.png) | ![ConnectX-7 - 04](docs/img/connectx_7/connectx-7_04.png) | ![ConnectX-7 - 07](docs/img/connectx_7/connectx-7_07.png) | ![ConnectX-7 - 08](docs/img/connectx_7/connectx-7_08.png) |
| *ConnectX-7 - 01* | *ConnectX-7 - 04* | *ConnectX-7 - 07* | *ConnectX-7 - 08* |

## ASUS Pro WS WRX90E-SAGE SE Hero Asset

*Procedural modeling & texturing of the WRX90E motherboard.*

| | | | |
| :---: | :---: | :---: | :---: |
| ![ASUS Pro WS WRX90E-SAGE SE - 01](docs/img/ws_wrx90e/ws_wrx90e_01.png) | ![ASUS Pro WS WRX90E-SAGE SE - 03](docs/img/ws_wrx90e/ws_wrx90e_03.png) | ![ASUS Pro WS WRX90E-SAGE SE - 04](docs/img/ws_wrx90e/ws_wrx90e_04.png) | ![ASUS Pro WS WRX90E-SAGE SE - 05](docs/img/ws_wrx90e/ws_wrx90e_05.png) |
| *ASUS Pro WS WRX90E-SAGE SE - 01* | *ASUS Pro WS WRX90E-SAGE SE - 03* | *ASUS Pro WS WRX90E-SAGE SE - 04* | *ASUS Pro WS WRX90E-SAGE SE - 05* |

## Noctua NH-D9 TR5-SP6 Hero Asset

*Procedural modeling & texturing of the 4U Threadripper CPU cooler.*

| | | | |
| :---: | :---: | :---: | :---: |
| ![Noctua NH-D9 - 01](docs/img/cpu_fan/cpu_fan_01.png) | ![Noctua NH-D9 - 03](docs/img/cpu_fan/cpu_fan_03.png) | ![Noctua NH-D9 - 06](docs/img/cpu_fan/cpu_fan_06.png) | ![Noctua NH-D9 - 07](docs/img/cpu_fan/cpu_fan_07.png) |
| *Noctua NH-D9 - 01* | *Noctua NH-D9 - 03* | *Noctua NH-D9 - 06* | *Noctua NH-D9 - 07* |

### Key Features

| Feature | Description |
| :--- | :--- |
| **The Glass Tube (Rack)** | **Sealed Containment:** Racks feature hermetic glass doors and bottom-fed plenums, forcing cold air *through* the nodes. |
| **The Silent Heat (Node)** | **Precision Thermal Modelling:** Tracks waste heat from the **1600W PSU (~84W)** alongside the **3x GB203** array. |
| **Metrics** | Real-time tracking of **PUE** (Facility) and **CEF** (Cooling Efficiency Factor) at the rack level. |
| **Hybrid Visualisation** | Seamless switching between **Photorealistic** (Marketing) and **X-Ray / Fluid Dynamics** (Engineering) modes. |

---

## 🏗️ Architecture

The system follows a strict separation of concerns:

### 1. Geometry Foundation & Production Simulation (SideFX Houdini)

*Geometry authoring, simulation, and USD export.*

Houdini is the closed creative environment of this hybrid pipeline. Houdini project files (`.hip`) are **not distributed** — only the exported outputs are.

* **Geometry**: Server Nodes, Racks, and Data Hall layouts modelled procedurally and exported as USD.
* **Simulation**: CFD thermal and airflow dynamics computed in Houdini, baked to **VDB caches**. Playback and visualisation of these caches happens inside the Omniverse Extension.
* **Output**: Optimised USD assets (`.usda`, `.vdb`) consumed by the App at runtime.

### 2. Interactive Digital Twin Frontend (NVIDIA Omniverse)

*The real-time visualization layer and state machine.*

* **Extension**: `omni.ai.refinery` (Custom Kit App).
* **Logic**: A robust State Machine that listens to the Python Data Provider, dynamically swapping pre-cached USD VariantSets (Pyro sims, vector streamlines, thermal heatmaps) based on the active operational state.
* **UI**: Viewport-embedded HUD (`omni.ui.scene` overlay) for hierarchical LOD navigation (Hall → Rack → Node) and manual stress-test overrides.

---

## 🚦 State Matrix

The Digital Twin operates in one of four discrete states at any given time:

| State | Load | Visual Cues |
| :--- | :--- | :--- |
| **Idle** | 0% | Laminar airflow, cool ambient lighting, minimal power draw. |
| **Nominal** | 25% | Steady-state cooling, efficient PUE, green status LEDs. |
| **Surge** | 50% | Fans ramping up, heat signatures visible on exhaust vents. |
| **Critical** | 85% | Thermal throttling, turbulent airflow (Heat haze), red warning LEDs. |

*The **Viral Inference Surge** scenario drives the transition cascade: `Nominal → Surge → Critical`.*

---

## 🛠️ Usage & Setup

### 1. Environment Setup

The project relies on a specific Conda environment (`case03-env`) to ensure reproducibility.

```bash
# Create and activate environment
conda create -n case03-env python=3.10
conda activate case03-env

# Install dependencies
pip install -r requirements.txt
```

### 2. Asset Hydration

To keep the repository lightweight, heavy binary assets (Textures, VDB Caches) are stored externally.

1. **Download** the Asset Pack: `[LINK_TBD]`
2. **Extract** contents to: `assets/_external/`
3. **Verify** structure:

    ```text
    assets/_external/
    ├── usd/      # Heavy USD Crates
    ├── tex/      # 4K/8K Textures
    └── vdb/      # Simulation Caches
    ```

### 3. Running the App

> *Coming Soon: Instructions for launching the Omniverse Extension*

---

## 📂 Repository Structure

```text
.
├── assets/
│   ├── _external/   # [GIT-IGNORED] Downloaded binary assets
│   └── local/       # Lightweight git-tracked assets (UI icons, scripts)
├── docs/            # Documentation & ADRs
│   ├── knowledge_base/  # Concept, Specs & Engineering Rules
│   │   ├── README.md         # 📚 Knowledge Base Index Hub
│   │   ├── main_concept.md
│   │   ├── hardware_specification.md
│   │   └── usd_architecture/ # Rigid OpenUSD Pipeline Guidelines
│   ├── plans/           # Actionable implementation guides
│   │   └── case 03 - tech debt.md
│   └── adr/             # Architecture Decision Records (e.g., 007 USD Pipeline)
├── src/             # Python source code (Data Provider, Logic)
└── tools/           # Developer scripts (Jira integration, asset validation)
```

## 📜 Technical Stack

* **Python**: 3.10
* **USD**: 23.11+
* **Houdini FX**: 21.0.596
* **NVIDIA Omniverse / Isaac Sim**: 5.1.0

---

## 📜 Changelog

* **2026-01-22:** Initial repository bootstrap. Established Readme-driven structure: Tech Pack, ADR documentation, pre-commit hooks, and `case03-env` constraints.
* **2026-02-01:** Finalized Case 03 core concept (AI Inference Refinery) and hardware specification (Blackwell Rig v1.0).
* **2026-02-09:** Focused development on Hero Asset (Blackwell Rig v1.0), detailing the server front panel and cooler chassis. Implemented external storage strategy (ADR 005).
* **2026-02-16:** Dedicated sprint to Blackwell Rig GB203 detailing. Standardized asset naming conventions and updated cooling concepts (Forced-Flow & Metrics).
* **2026-02-23:** Completed blockout of ConnectX-7 NIC and outer chassis panels. Initiated blockout for RTX PRO 4500 GPUs and ASUS Pro WS WRX90E-SAGE SE motherboard.
* **2026-03-01:** Completed modeling of RTX PRO 4500 Blackwell, baked textures, and successfully exported the USD asset to the `..\assets\_external\usd\rtx_pro_4500` directory.
* **2026-03-02:** Finalized ConnectX-7 & OSFP network architecture documentation, establishing standards for yellow SMF cabling and visual differentiation. Extensively refined the "Forced-Flow" Digital Twin concept, detailing procedural telemetry interpolation (noise-based heatmaps/LEDs), HUD-driven hierarchical LODs (Hall → Rack → Server), and color-coded velocity streamlines. Added rationale for synthetic data generation and documented the Live Mode placeholder for real-world telemetry integration.
* **2026-03-17:** Finalised procedural modelling, UV unwrapping, and texturing of the ConnectX-7 Hero Asset across all Levels of Detail (LOD00, LOD01, LOD02, Proxy), and successfully exported the USD asset to the `..\assets\_external\usd\connectx7` directory. Integrated final high-resolution renders into the documentation to showcase the engineering-grade geometry (PCB components, extruded heatsink fins, OSFP connector).
* **2026-04-06:** Finalised procedural modelling, UV unwrapping, and texturing of the ASUS Pro WS WRX90E-SAGE SE Hero Asset, and successfully exported the USD asset to the `..\assets\_external\usd\ws_wrx90e` directory. Integrated final high-resolution renders into the documentation to showcase the engineering-grade geometry (I/O Bracket, VRM Block, STR5 Socket, RAM Ports).
* **2026-04-09:** Finalised procedural modelling and texturing of the Noctua NH-D9 TR5-SP6 CPU cooler Hero Asset, and successfully exported the USD asset to the `..\assets\_external\usd\cpu_fan` directory. Restructured documentation to establish a unified Hero Asset Gallery and cleansed files of legacy marketing terminology.
