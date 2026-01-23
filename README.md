# Case 03: Data Center (HPC Infrastructure Digital Twin)

> [!WARNING]
> **Work in Progress:** This project is currently under active development. Some links and assets may be placeholders.

---

> **Role:** L1 Digital Twin (Infrastructure Monitoring)
> **Stack:** Houdini, Omniverse (USD/Python), MDL, Jira Integration

---

## 📋 Project Overview

This repository showcases a prototype **High-Performance Computing Infrastructure Digital Twin (Level L1)** demonstrating visualisation of critical operational parameters within data centre environments. The case study focuses on a render farm, presenting real-time monitoring of thermal, power, and cooling system dynamics.

**Key Use Case:**
The digital twin visualises **thermal behaviour of server racks receiving a large render job**. The scenario demonstrates temperature escalation across compute nodes as workload intensifies, followed by stabilisation through active cooling systems. Temperature data drives real-time heatmap shaders and status indicators via HUD/FUI overlays. This exemplifies how L1 Digital Twins translate complex infrastructure telemetry into clear visual narratives for operational awareness.

**Project Focus:**

- **Photorealistic SimReady Assets:** Industry-standard asset quality for professional visualisation
- **Massive Scene Optimisation:** Point Instancing strategy rendering 10,000+ server units in real-time
- **MDL-Driven Visualisation:** Custom shaders binding thermal/power data directly to material properties

---

## 🎯 Technical Highlights

*This setup demonstrates an **L1 Digital Twin**, focusing on the visualization of critical infrastructure parameters (Thermal, Power, Network).*

- **Houdini "Factory":** Procedural generation of racks, cabling, and simulation data mocking.
- **USD Architecture:** Strict Point Instancing strategy (`Zone` -> `Rack` -> `Unit`) for rendering 10,000+ assets in real-time.
- **MDL Visualization:** Custom shaders driving heatmaps and usage LEDs directly from USD attributes.
- **Python Tooling:** Automated layout assembly and sensor data binding.

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
