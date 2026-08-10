# Digital Twin Runtime Suite

> [!WARNING]
> **Work in Progress:** This project is currently under active development. Some links and assets may be placeholders.

---

## 📋 Project Overview

**Digital Twin Runtime Suite** is an interactive Omniverse application and the
third project in a broader four-case technical showreel. It presents a
high-density Blackwell inference data hall through hydrated OpenUSD assets,
synthetic telemetry, and staged runtime capabilities.

A **Reproducible Tech Pack** demonstrating a portfolio-grade **L1 Digital Twin** visualisation prototype of an AI Inference Farm.
The current repository exercises authored geometry and Houdini velocity-field
export in a runnable Omniverse application with asset review, look-review
controls, config-driven synthetic telemetry, and a bounded Kit-CAE/Flow temporal
proof. Further telemetry-to-airflow state binding and scale navigation remain
staged runtime work.

The project visualises a **"Viral Inference Surge"** — a dynamic stress-test scenario where a sudden 500% spike in LLM requests triggers a sequential ramp-up of cooling and power systems across a high-density data hall.

> **Why GB203, not the flagship?** The project uses an internal scenario analysis: **17.9 TFLOPS per $1,000** and **$1.58M saved** across a 16-rack cluster versus the RTX PRO 5000 72GB. These are design-time planning estimates, not vendor pricing or a current market quote. The 4U chassis preserves a bounded three-GPU plus ConnectX-7 layout for the current DTRS reference node.
>
> **Why 3 GPUs, not 4?** The node requires a 400G ConnectX-7 NIC for RDMA. On the 7-slot WRX90E motherboard, three dual-slot GPUs + one NIC perfectly maxes out the physical PCIe layout without bottlenecking the network card.
>
> → [📚 Knowledge Base Hub (Index)](./docs/knowledge_base/README.md) · [Architecture & Physics](./docs/knowledge_base/main_concept.md) · [Hardware Specification](./docs/knowledge_base/hardware_specification.md)

Unlike traditional linear animation, this ecosystem is structured as a **State Machine**. Runtime telemetry already drives interactive visual responses, while telemetry-to-airflow cache selection, streamlines, heatmaps, lighting, and HUD cues remain staged extensions rather than fixed-shot animation.

> [!NOTE]
> Synthetic Data Generation for Sim-to-Real: No real data centre required. All metrics (GPU temps, fan RPMs, power draw) are generated procedurally by the Data Provider module to create high-quality demonstration data. This proves the full pipeline end-to-end before physical deployment.
> **External telemetry ready by design.** DTRS currently ships with a synthetic telemetry provider. Its normalised telemetry model and planned provider boundary allow future source-specific adapters to map systems such as Grafana, Prometheus, MQTT, Kafka, NVML, Redfish, or other monitoring feeds into the same DTRS data model. Production connectors for those systems are intentionally outside the current Case 03 scope.

## Digital Twin Runtime Suite 0.4.0 Runtime Preview

*Omniverse full-server runtime review with live synthetic node telemetry,
persistent enclosure and airflow controls, and manifest-driven Houdini VTI
velocity playback through Kit-CAE and NVIDIA Flow.*

| Airflow controls | Attached airflow review |
| :---: | :---: |
| ![Digital Twin Runtime Suite 0.4.0 - Airflow controls](docs/img/dtrs_0.4.0/dtrs_0.4.0_01.png) | ![Digital Twin Runtime Suite 0.4.0 - Attached airflow review](docs/img/dtrs_0.4.0/dtrs_0.4.0_02.png) |
| *View tab with persistent enclosure, airflow-cache, smoke-tuning, colour, and transport controls* | *Manifest-selected `server / load_normal` velocity field driving volumetric smoke through the open server* |

| Runtime configuration | Telemetry overview |
| :---: | :---: |
| ![Digital Twin Runtime Suite 0.4.0 - Runtime configuration](docs/img/dtrs_0.4.0/dtrs_0.4.0_03.png) | ![Digital Twin Runtime Suite 0.4.0 - Telemetry overview](docs/img/dtrs_0.4.0/dtrs_0.4.0_04.png) |
| *Config tab with runtime asset, lighting, grid, camera, and telemetry-provider controls* | *Full-server telemetry hierarchy with a live synthetic Nominal workload state* |

→ [Watch the Digital Twin Runtime Suite preview](https://youtu.be/BeOx61VVE4I)

→ [Watch the Blackwell Rig server assembly preview](https://youtu.be/W5ttjDyuSXk)

### Runtime Performance & Rendering Trade-offs

The Digital Twin Runtime Suite is developed and validated on an NVIDIA GeForce RTX 3080 12GB and is designed primarily as an **interactive technical visualisation**, rather than an offline cinematic renderer.

Higher-fidelity RTX rendering modes are available within Omniverse, but were intentionally not used as the runtime baseline because their additional GPU cost would compromise interactive inspection of telemetry, animated components and volumetric flow.

The current rendering configuration therefore prioritises **runtime responsiveness, simulation readability and functional interaction** over maximum image fidelity.

Performance figures are hardware- and scene-dependent and will continue to be profiled as the application evolves.

## Blackwell Rig Airflow Simulation Preview

*Technical viewport preview of the 4U Blackwell Rig GB203 node used as the first airflow layout review pass.*

The current simulation pass turns the hero server from a static hardware model into a reviewable airflow volume: chassis intake, rear exhaust, GPU bodies, CPU cooler, PSU mass, cable bundles, and internal obstructions are all represented inside the same simulation domain.

These Houdini-solved airflow caches are physically inspired, presentation-grade qualitative proxies, not validated CFD results or a certified CFD validation study. They provide the Demo Mode input for the runtime contract: a controlled, reproducible source for previewing how the node responds across telemetry-driven states under local hardware and demonstration constraints. The goal is to make intake paths, component occlusion, recirculation zones, heat-source proxies, and operational state changes legible.

DTRS discovers the external VTI dataset from its manifest and maps its samples
to Kit-CAE and NVIDIA Flow at the source-defined cadence. The current
`server / load_normal` fixture contains 80 samples at 5 Hz; its structured
`PointData/vel` field updates native runtime smoke/advection in one continuous
Flow simulation while preserving the full server presentation.

The Flow consumer is intentionally separated from source selection. This PoC
proves VTI temporal substitution inside the runtime; it does not yet implement
telemetry-to-cache state binding or an external live feed.

→ [Watch the Houdini airflow simulation preview](https://youtu.be/lDswlLGkTQ8)

→ See also: [Rack Airflow Budget](./docs/knowledge_base/rack_airflow_budget.md)

| | | | |
| :---: | :---: | :---: | :---: |
| ![Blackwell Rig airflow simulation preview - 01](docs/img/previews/option.1.A.1150.png) | ![Blackwell Rig airflow simulation preview - 02](docs/img/previews/option.1.B.1150.png) | ![Blackwell Rig airflow simulation preview - 03](docs/img/previews/option.1.C.1150.png) | ![Blackwell Rig airflow simulation preview - 04](docs/img/previews/option.1.D.1150.png) |
| *Simulation domain / intake view* | *Internal airflow obstruction pass* | *Rear exhaust and fan interaction* | *Cable-side airflow review* |

The streamline visualisation pass exposes the velocity-field behaviour more directly, showing the fan-driven flow paths, cooler interactions, exhaust directionality, and turbulence around internal cable and component obstructions.

| | | | |
| :---: | :---: | :---: | :---: |
| ![Blackwell Rig airflow streamline preview - 01](docs/img/previews/option.0.0051.A.1124.png) | ![Blackwell Rig airflow streamline preview - 02](docs/img/previews/option.0.0051.B.1124.png) | ![Blackwell Rig airflow streamline preview - 03](docs/img/previews/option.0.0051.C.1124.png) | ![Blackwell Rig airflow streamline preview - 04](docs/img/previews/option.0.0051.D.1124.png) |
| *Velocity field overview* | *CPU cooler and rear fan flow paths* | *Rear exhaust directionality* | *Cable-side turbulence and intake/exhaust flow* |

## RTX PRO 4500 Hero Asset

*Procedural modelling & texturing of the Blackwell GB203 node.*

| | | | |
| :---: | :---: | :---: | :---: |
| ![RTX PRO 4500 Blackwell - 01](docs/img/rtx_pro_4500/rtx_pro_4500_-_01.png) | ![RTX PRO 4500 Blackwell - 02](docs/img/rtx_pro_4500/rtx_pro_4500_-_02.png) | ![RTX PRO 4500 Blackwell - 03](docs/img/rtx_pro_4500/rtx_pro_4500_-_07.png) | ![RTX PRO 4500 Blackwell - 04](docs/img/rtx_pro_4500/rtx_pro_4500_-_08.png) |
| *RTX PRO 4500 Blackwell - 01* | *RTX PRO 4500 Blackwell - 02* | *RTX PRO 4500 Blackwell - 03* | *RTX PRO 4500 Blackwell - 04* |

## ConnectX-7 Hero Asset

*Procedural modelling & texturing of the 400G NDR network interface card.*

| | | | |
| :---: | :---: | :---: | :---: |
| ![ConnectX-7 - 01](docs/img/connectx_7/connectx-7_01.png) | ![ConnectX-7 - 02](docs/img/connectx_7/connectx-7_04.png) | ![ConnectX-7 - 03](docs/img/connectx_7/connectx-7_07.png) | ![ConnectX-7 - 04](docs/img/connectx_7/connectx-7_08.png) |
| *ConnectX-7 - 01* | *ConnectX-7 - 02* | *ConnectX-7 - 03* | *ConnectX-7 - 04* |

## ASUS Pro WS WRX90E-SAGE SE Hero Asset

*Procedural modelling & texturing of the WRX90E motherboard.*

| | | | |
| :---: | :---: | :---: | :---: |
| ![ASUS Pro WS WRX90E-SAGE SE - 01](docs/img/ws_wrx90e/ws_wrx90e_01.png) | ![ASUS Pro WS WRX90E-SAGE SE - 02](docs/img/ws_wrx90e/ws_wrx90e_03.png) | ![ASUS Pro WS WRX90E-SAGE SE - 03](docs/img/ws_wrx90e/ws_wrx90e_04.png) | ![ASUS Pro WS WRX90E-SAGE SE - 04](docs/img/ws_wrx90e/ws_wrx90e_05.png) |
| *ASUS Pro WS WRX90E-SAGE SE - 01* | *ASUS Pro WS WRX90E-SAGE SE - 02* | *ASUS Pro WS WRX90E-SAGE SE - 03* | *ASUS Pro WS WRX90E-SAGE SE - 04* |

## Noctua NH-D9 TR5-SP6 Hero Asset

*Procedural modelling & texturing of the 4U Threadripper CPU cooler.*

| | | | |
| :---: | :---: | :---: | :---: |
| ![Noctua NH-D9 - 01](docs/img/cpu_fan/cpu_fan_01.png) | ![Noctua NH-D9 - 02](docs/img/cpu_fan/cpu_fan_03.png) | ![Noctua NH-D9 - 03](docs/img/cpu_fan/cpu_fan_06.png) | ![Noctua NH-D9 - 04](docs/img/cpu_fan/cpu_fan_07.png) |
| *Noctua NH-D9 - 01* | *Noctua NH-D9 - 02* | *Noctua NH-D9 - 03* | *Noctua NH-D9 - 04* |

## be quiet! Dark Power Pro 13 1600W Hero Asset

*Procedural modelling & texturing of the Titanium 1600W PSU.*

| | | | |
| :---: | :---: | :---: | :---: |
| ![be quiet! Dark Power Pro 13 - 01](docs/img/psu/psu_01.png) | ![be quiet! Dark Power Pro 13 - 02](docs/img/psu/psu_03.png) | ![be quiet! Dark Power Pro 13 - 03](docs/img/psu/psu_05.png) | ![be quiet! Dark Power Pro 13 - 04](docs/img/psu/psu_06.png) |
| *be quiet! Dark Power Pro 13 - 01* | *be quiet! Dark Power Pro 13 - 02* | *be quiet! Dark Power Pro 13 - 03* | *be quiet! Dark Power Pro 13 - 04* |

## SilverStone RM44 Chassis Hero Asset

*Procedural modelling & texturing of the 4U industrial server chassis.*

| | | | |
| :---: | :---: | :---: | :---: |
| ![SilverStone RM44 - 01](docs/img/chassis_rm44/rm44_01.png) | ![SilverStone RM44 - 02](docs/img/chassis_rm44/rm44_02.png) | ![SilverStone RM44 - 03](docs/img/chassis_rm44/rm44_03.png) | ![SilverStone RM44 - 04](docs/img/chassis_rm44/rm44_04.png) |
| *SilverStone RM44 - 01* | *SilverStone RM44 - 02* | *SilverStone RM44 - 03* | *SilverStone RM44 - 04* |

### Key Features

| Feature | Description |
| :--- | :--- |
| **The Glass Tube (Rack)** | **Sealed Containment:** Racks feature hermetic glass doors and bottom-fed plenums, forcing cold air *through* the nodes. |
| **The Silent Heat (Node)** | **Thermal Behaviour Visualisation:** Represents estimated waste heat from the **1600W PSU (~84W)** alongside the **3x GB203** array. |
| **Metrics** | Real-time tracking of **PUE** (Facility) and **CEF** (Cooling Efficiency Factor) at the rack level. |
| **Hybrid Visualisation** | The runtime includes a non-persistent Custom MDL Fresnel probe for Engineering X-Ray material review; a Flow view remains planned. |

---

## 🏗️ Architecture

The system follows a strict separation of concerns:

### 1. Geometry Foundation & Production Simulation (SideFX Houdini)

*Geometry authoring, simulation, and USD export.*

Houdini is the closed creative environment of this hybrid pipeline. Houdini project files (`.hip`) are **not distributed** — only the exported outputs are.

* **Geometry**: Server Nodes, Racks, and Data Hall layouts modelled procedurally and exported as USD.
* **Simulation**: Houdini-based volumetric airflow and thermal-behaviour approximation, exported as resampled VTI vector-field fixtures for the current Kit-CAE/Flow runtime.
* **Output**: Optimised USD assets and temporal VTI velocity datasets prepared for Digital Twin Runtime Suite.

### 2. Interactive Digital Twin Frontend (NVIDIA Omniverse)

*The real-time visualisation layer and state machine.*

* **Application**: **Digital Twin Runtime Suite**.
* **Extension**: `msp.dtrs`.
* **Logic**: A State Machine that consumes the Python Data Provider and drives current node presentation controls. Telemetry-to-cache state binding, vector streamlines, and thermal heatmaps remain later staged visual layers.
* **UI**: OmniUI sidebar with `Telemetry`, `View`, and `Config` tabs, plus runtime status and performance overlays. Hierarchical Hall/Rack/Node navigation and a viewport HUD remain future work.

---

## 🚦 State Matrix

The planned runtime operates in one of four synthetic workload states. These
are demo/monitoring loads, not literal power-off percentages; even the minimum
operational state keeps the server active.

| State | Synthetic Load | Visual Cues |
| :--- | :--- | :--- |
| **Idle** | 25% | Minimum operational baseline, low-intensity airflow visualisation, cool ambient lighting, low power draw. |
| **Nominal** | 50% | Steady-state cooling, efficient PUE, stable green status LEDs. |
| **Surge** | 75% | Fans ramping up, stronger heat signatures visible on exhaust vents. |
| **Critical** | 96% | Near-saturation load, thermal-risk cues, high-intensity airflow visualisation, red warning LEDs. |

*The **Viral Inference Surge** scenario drives the transition cascade: `Nominal → Surge → Critical`.*

---

## 🛠️ Usage & Setup

### 1. Environment Setup

The `case03-env` Conda environment supports current Case 03 tooling and
pure-Python validation. It is not required to launch Digital Twin Runtime Suite,
which runs inside Omniverse Kit's Python environment.

```bash
# Create and activate environment
conda create -n case03-env python=3.11.15
conda activate case03-env

# Install dependencies
pip install -r requirements.txt
```

### 2. External Data Hydration

Large binary dependencies are distributed separately from the Git repository.

Two external packages are used:

1. **Production Asset Pack — Google Drive**
   - USD assets
   - textures
   - HDRI environments

2. **Airflow Runtime Dataset — Hugging Face**
   - manifest-driven temporal VTI velocity fields
   - current dataset: `server / load_normal`
   - 80 samples at 5 Hz

1. Download and extract the Production Asset Pack directly into
   `assets/_external/`, preserving its `usd/`, `tex/`, and `hdri/` directories.
2. Download the Airflow Runtime Dataset and place its `airflow_datasets/`
   directory directly under `assets/_external/` without renaming its internal
   folders.

After hydrating both sources, the expected structure is:

```text
assets/_external/
├── airflow_datasets/
├── hdri/
├── tex/
└── usd/
```

- [Production Asset Pack on Google Drive](https://drive.google.com/drive/folders/1qV2-NQr9HLf-maKPOiB4z9TwodqvK_sh?usp=sharing)
- [Airflow Runtime Dataset on Hugging Face](https://huggingface.co/datasets/MaxSpeLL/dt-openusd-showcase-case03-airflow)



### 3. Running the App

Digital Twin Runtime Suite v0.4.0 launches as a dedicated Omniverse Kit
application config. The quickest local launch path is:

```powershell
.\src\digital_twin_runtime_suite\start_dtrs.bat
```

Use `.\src\digital_twin_runtime_suite\start_dtrs.bat --check` to verify the
resolved Kit paths without launching the app.

The launcher uses `DTRS_KIT_RELEASE` or `KIT_RELEASE` when either environment
variable is set. If neither is set, it searches the current drive for a built
Kit App Template release directory.

For an explicit manual launch, point `$kitRelease` at a built Omniverse Kit App
Template release directory:

```powershell
$kitRelease = "path\to\kit-app-template\_build\windows-x86_64\release"
$kitCaeRelease = "path\to\kit-cae\_build\windows-x86_64\release"
& "$kitRelease\kit\kit.exe" `
  ".\src\digital_twin_runtime_suite\apps\digital_twin_runtime_suite.kit" `
  --ext-folder "$kitRelease\exts" `
  --ext-folder "$kitRelease\extscache" `
  --ext-folder "$kitRelease\apps" `
  --ext-folder "$kitCaeRelease\exts"
```

The current runtime reads `configs/digital_twin_runtime_suite.toml`,
resolves the hydrated asset package under `assets/_external/`, opens the
configured Blackwell Rig GB203 server assembly in the RTX viewport, and
applies its configured presentation, lighting, telemetry, and airflow runtime
settings.

Lighting uses the Config panel in the Kit UI. Its default HDRI is
`assets/_external/hdri/kloofendal_48d_partly_cloudy_puresky_4k.exr`; exposure,
intensity, and dome XYZ rotation are runtime controls applied through a
transient `/DTRS_Runtime/Lighting` session-layer setup. The HDRI background can
be hidden from the primary viewport while preserving its lighting contribution.

The current runtime includes the synthetic node telemetry provider, telemetry-
driven fan motion across the complete server, persistent enclosure presentation,
and the Kit-CAE/Flow airflow review path. Telemetry updates independently
from the Kit timeline, exposes latest-snapshot thermal, power, cooling, and
limit values, and supports manual workload targets plus display freeze/resume.
The Config tab can tune provider cadence and per-mode metric targets through a
separate local telemetry override. The View tab owns the enclosure, airflow,
smoke, transport, and emitter-layout controls.

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
├── src/             # Digital Twin Runtime Suite runtime source
└── tools/           # Developer scripts (Jira integration, asset validation)
```

## 📜 Technical Stack

- **Python**: 3.11.15
- **Houdini**: 21.0.729 (PDG, Pyro, Fluid)
- **Nvidia Omniverse**: 110.1.2
- **Conda**: Environment isolation (`case03-env`)

---

## 📜 Changelog

* **Week of 20 July, 2026:** Advanced Digital Twin Runtime Suite v0.4.0 into an interactive full-server presentation layer with server enclosure visibility controls, hinged front-panel animation, QLED CPU-temperature display, front-panel activity indicators, focused UI-control tests, and refreshed runtime screenshots.
* **Week of 13 July, 2026:** Completed topology repairs across the Blackwell Rig component set, delivered the Digital Twin Runtime Suite 0.3 full-server review candidate with static USD preflight and 11 config-backed fan bindings, clarified the qualitative airflow visualisation boundary, and defined a staged licensing and distribution plan for the public Asset Pack.
* **Week of 6 July, 2026:** Delivered Digital Twin Runtime Suite 0.1 through its first three runtime slices, combining Omniverse asset and look review with config-driven synthetic telemetry, validated workload states, hardware-aware power and thermal modelling, focused provider tests, and public runtime evidence.
* **Week of 29 June, 2026:** Advanced Case 03 from node-scale airflow proof toward rack-level production planning, added Omniverse MCP helper tooling, clarified the visualisation contract, and migrated the project baseline to Python 3.11.15.
* **Week of 22 June, 2026:** Added the first Blackwell Rig airflow simulation preview, turning the 4U node into a reviewable airflow volume with chassis intake, rear exhaust, GPU/CPU/PSU massing, cable obstructions, viewport review frames, and a linked video preview. Successfully exported the single-node Blackwell Rig airflow simulation cache to the `..\assets\_external\vdb\server_airflow_vdb` directory and the USD wrapper to the `..\assets\_external\usd\server_airflow_v001` directory. Published the external Asset Pack via Google Drive.
* **Week of 15 June, 2026:** Closed the Blackwell Rig core hardware phase, advanced node-level Houdini airflow simulation work, and documented a path-portable runtime packaging guardrail for future viewer delivery.
* **2026-01-22:** Initial repository bootstrap. Established Readme-driven structure: Tech Pack, ADR documentation, pre-commit hooks, and `case03-env` constraints.
* **2026-02-01:** Finalized Case 03 core concept (AI Inference Refinery) and hardware specification (Blackwell Rig v1.0).
* **2026-02-09:** Focused development on Hero Asset (Blackwell Rig v1.0), detailing the server front panel and cooler chassis. Implemented external storage strategy (ADR 005).
* **2026-02-16:** Dedicated sprint to Blackwell Rig GB203 detailing. Standardized asset naming conventions and updated cooling concepts (Forced-Flow & Metrics).
* **2026-02-23:** Completed blockout of ConnectX-7 NIC and outer chassis panels. Initiated blockout for RTX PRO 4500 GPUs and ASUS Pro WS WRX90E-SAGE SE motherboard.
* **2026-03-01:** Completed modelling of RTX PRO 4500 Blackwell, baked textures, and successfully exported the USD asset to the `..\assets\_external\usd\rtx_pro_4500` directory.
* **2026-03-02:** Finalized ConnectX-7 & OSFP network architecture documentation, establishing standards for yellow SMF cabling and visual differentiation. Extensively refined the "Forced-Flow" Digital Twin concept, detailing procedural telemetry interpolation (noise-based heatmaps/LEDs), HUD-driven hierarchical LODs (Hall → Rack → Server), and color-coded velocity streamlines. Added rationale for synthetic data generation and documented the Live Mode placeholder for real-world telemetry integration.
* **2026-03-17:** Finalised procedural modelling, UV unwrapping, and texturing of the ConnectX-7 Hero Asset across all Levels of Detail (LOD00, LOD01, LOD02, Proxy), and successfully exported the USD asset to the `..\assets\_external\usd\connectx7` directory. Integrated final high-resolution renders into the documentation to showcase the engineering-grade geometry (PCB components, extruded heatsink fins, OSFP connector).
* **2026-04-06:** Finalised procedural modelling, UV unwrapping, and texturing of the ASUS Pro WS WRX90E-SAGE SE Hero Asset, and successfully exported the USD asset to the `..\assets\_external\usd\ws_wrx90e` directory. Integrated final high-resolution renders into the documentation to showcase the engineering-grade geometry (I/O Bracket, VRM Block, STR5 Socket, RAM Ports).
* **2026-04-09:** Finalised procedural modelling and texturing of the Noctua NH-D9 TR5-SP6 CPU cooler Hero Asset, and successfully exported the USD asset to the `..\assets\_external\usd\cpu_fan` directory. Restructured documentation to establish a unified Hero Asset Gallery and cleansed files of legacy marketing terminology.
* **2026-04-29:** Finalised procedural modelling and texturing of the be quiet! Dark Power Pro 13 1600W PSU Hero Asset, and successfully exported the USD asset to the `..\assets\_external\usd\psu` directory. Integrated final high-resolution renders into the documentation to showcase the engineering-grade geometry (LOD 00, LOD 01, and internals).
* **2026-05-17:** Finalised procedural modelling and texturing of the SilverStone RM44 server chassis Hero Asset, and successfully exported the USD asset to the `..\assets\_external\usd\rm44` directory. Integrated final high-resolution renders showcasing the engineering-grade geometry (front mesh panel, internal drive cages, motherboard tray, and rear I/O layout) into the documentation.
* **2026-06-07:** Finalised the Blackwell Rig internal cabling pass, including routed PSU/GPU/fan/header cable bundles, colour-coded ties, and braided material treatment for the main high-current runs. Successfully exported the completed cabling asset to the `..\assets\_external\usd\cables` directory.
