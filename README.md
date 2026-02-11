# Case 03: Data Center (AI Inference Refinery)

> [!NOTE]
> **Status:** Active Prototype (Internal Beta)
> **Stack:** NVIDIA Omniverse Kit (Python) + SideFX Houdini (Solaris)

---

## 📋 Project Overview

A **Reproducible Tech Pack** demonstrating an **L1 Digital Twin** of an AI Inference Farm.
The project visualises a **"Viral Inference Surge"** — a dynamic scenario where a sudden 500% spike in AI model requests triggers a sequential ramp-up of cooling and power systems across a high-density data hall.

Unlike traditional linear animation, this ecosystem is a **State Machine**. It simulates the facility's response in real-time based on normalised telemetry data.

### Key Features

| Feature | Description |
| :--- | :--- |
| **3x4 Simulation Matrix** | 4 Operational States (Idle, Nominal, Surge, Critical) across 3 Levels of Detail (Node, Rack, Room). |
| **Hybrid Visualisation** | Seamless switching between **Photorealistic** (Marketing) and **X-Ray / CFD** (Engineering) modes. |
| **Hero Asset** | **Blackwell Rig GB203** (Custom 4U Inference Node featuring 3x NVIDIA RTX PRO 4500 (GB203) GPUs). |
| **Data-Driven** | All visual cues (Fan RPM, LEDs, Heatmaps) are driven by a decoupled Data Provider, not keyframes. |

---

## 🏗️ Architecture

The system follows a strict separation of concerns:

### 1. The Factory (SideFX Houdini)

*Generates the static and dynamic assets.*

- **Solaris/PDG**: Procedural assembly of Racks and Room layouts.
- **Simulation**: Pre-calculated CFD caches (VDB) for airflow and thermodynamics.
- **Output**: Optimised USD assets (`.usd`, `.vdb`, `.bgeo`).

### 2. The App (Nvidia Omniverse)

*Runs the runtime logic and visualisation.*

- **Extension**: `omni.ai.refinery` (Custom Kit App).
- **Logic**: Listens to the Data Provider and swaps USD VariantSets based on the current State.
- **UI**: Custom Control Panel for manual state override.

---

## 🚦 state Matrix

The Digital Twin operates in one of four discrete states at any given time:

| State | Load | Visual Cues |
| :--- | :--- | :--- |
| **Idle** | 0% | Laminar airflow, cool ambient lighting, minimal power draw. |
| **Nominal** | 25% | Steady-state cooling, efficient PUE, green status LEDs. |
| **Surge** | 50% | Fans ramping up, heat signatures visible on exhaust vents. |
| **Critical** | 85% | Thermal throttling, turbulent airflow (Heat haze), red warning LEDs. |

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
│   ├── main_concept.md  # Detailed Architecture & Implementation Plan
│   └── adr/             # Architecture Decision Records
├── src/             # Python source code (Data Provider, Logic)
└── tools/           # Pipeline utilities (Jira Sync, Asset Validation)
```

## 📜 License & Protocol

This project adheres to the **Nvidia Showreel Protocol**.

- **Documentation**: British English (en-GB).
- **Code**: Python 3.10 / USD 23.11+.
