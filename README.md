# Case 03: Data Center (HPC Infrastructure Digital Twin)

> [!WARNING]
> **Work in Progress:** This project is currently under active development. Some links and assets may be placeholders.

---

> **Role:** L1 Digital Twin (Infrastructure Monitoring)
> **Stack:** Houdini, Omniverse (USD/Python), MDL, Jira Integration

---

## 📋 Project Overview

This repository showcases a prototype **AI Inference Refinery (Level L1 Digital Twin)** demonstrating the visualisation of high-performance computing infrastructure within the Armenian tech ecosystem. The case study focuses on an **Inference Farm** hosting NVIDIA's **Nemotron-3** flagship models.

**Key Use Case:**
The digital twin visualises a **"Viral Inference Surge"** — a sudden spike in global requests. The scenario demonstrates the **sequential activation of 160 nodes** as the load balancer scales resources in real-time. Temperature escalation, airflow dynamics, and distributed data flows (RDMA) drive real-time heatmap shaders and HUD/FUI overlays.

**Project Focus:**

- **Photorealistic SimReady Assets:** Industry-standard asset quality for professional visualisation
- **Massive Scene Optimisation:** Point Instancing strategy rendering 10,000+ server units in real-time
- **MDL-Driven Visualisation:** Custom shaders binding thermal/power data directly to material properties

---

## 🎯 Technical Highlights

*This setup demonstrates an **L1 Digital Twin**, focusing on the visualization of critical infrastructure parameters (Thermal, Power, Network).*

- **Hero Asset**: **Blackwell Rig v1.0** (4U custom nodes featuring SilverStone RM44 chassis and 4x RTX PRO 4500 Blackwell GPUs).
- **Houdini "Refinery"**: Procedural rack generation and cascading airflow/thermal simulation prep.
- **USD Architecture**: Point Instancing strategy rendering **640 GPUs** across 16 racks in real-time.
- **MDL Visualization**: Custom shaders driving heatmaps and RDMA data-flow "pulses" directly from USD attributes.

## 👁️ Visual Proof

> *Placeholders for future GIFs - Replace with actual optimised media*

1. **Thermal Heatmap:** `![Heatmap Demo](docs/img/heatmap_demo.gif)`
2. **USD Composition:** `![Graph](docs/img/composition_graph.png)`
3. **Houdini PDG:** `![PDG Flow](docs/img/houdini_pdg.png)`

## 🏗️ Architecture & Decisions

This project follows a **README-driven structure** to manage the complexity of hybrid Houdini/Omniverse pipelines.

- [**View Architecture Decision Records (ADR)**](docs/adr/) – Design notes on Naming Conventions, Security Guardrails, and Dependency Locking.

## 📂 Repository Structure

```text
.
├── docs/        # ADRs and knowledge base
│   ├── plans/   # Implementation plans & tech debt
├── src/         # Core logic and scripts
├── tests/       # Validation and testing suite
└── tools/       # Internal pipeline utilities
```

- [**View Composition Graph**](docs/composition_graph.mermaid) – Visual breakdown of the USD layering strategy.

---

## 💾 Project Data / Assets

To keep this repository lightweight (GitHub < 1GB), heavy binary assets are stored externally.

- [**Download Heavy Assets (One Drive / S3 Link TBD)**](https://example.com/placeholder)
  - Includes: `*.usd` crates, `*.hip` source files, and high-res textures.

## 🛠️ Setup & Installation

1. **Clone:** `git clone https://github.com/MSP014/dt-omniverse-showreel-case03-dc.git`
2. **Env:** Create conda env: `conda create -n case03-env python=3.10`
3. **Deps:** `pip install -r requirements.txt`
4. **Hooks:** `pre-commit install`

---

## 📜 Changelog

- **2026-01-22:** Initial repository bootstrap. Established **Nvidia Showreel Protocol** (ADRs, Pre-commit, Hybrid Access).
