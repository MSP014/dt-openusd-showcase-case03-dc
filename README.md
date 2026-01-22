# Case 03: Data Center (Infrastructure Digital Twin)

> [!WARNING]
> **Work in Progress:** This project is currently under active development. Some links and assets may be placeholders.

---

> **Role:** L1 Digital Twin (Infrastructure Monitoring)
> **Stack:** Houdini, Omniverse (USD/Python), MDL, Jira Integration

---

## 🎯 Technical Highlights

*This setup demonstrates an **L1 Digital Twin**, focusing on the visualization of critical infrastructure parameters (Thermal, Power, Network).*

* **Houdini "Factory":** Procedural generation of racks, cabling, and simulation data mocking.
* **USD Architecture:** Strict Point Instancing strategy (`Zone` -> `Rack` -> `Unit`) for rendering 10,000+ assets in real-time.
* **MDL Visualization:** Custom shaders driving heatmaps and usage LEDs directly from USD attributes.
* **Python Tooling:** Automated layout assembly and sensor data binding.

## 👁️ Visual Proof

> *Placeholders for future GIFs - Replace with actual optimised media*

1. **Thermal Heatmap:** `![Heatmap Demo](docs/img/heatmap_demo.gif)`
2. **USD Composition:** `![Graph](docs/img/composition_graph.png)`
3. **Houdini PDG:** `![PDG Flow](docs/img/houdini_pdg.png)`

## 🏗️ Architecture & Decisions

This project follows a **README-driven structure** to manage the complexity of hybrid Houdini/Omniverse pipelines.

* [**View Architecture Decision Records (ADR)**](docs/adr/) – Design notes on Naming Conventions, Security Guardrails, and Dependency Locking.
* [**View Composition Graph**](docs/composition_graph.mermaid) – Visual breakdown of the USD layering strategy.

---

## 💾 Project Data / Assets

To keep this repository lightweight (GitHub < 1GB), heavy binary assets are stored externally.

* [**Download Heavy Assets (One Drive / S3 Link TBD)**](https://example.com/placeholder)
  * Includes: `*.usd` crates, `*.hip` source files, and high-res textures.

## 🛠️ Setup & Installation

1. **Clone:** `git clone https://github.com/MSP014/dt-omniverse-showreel-case03-dc.git`
2. **Env:** Create conda env: `conda create -n case03-env python=3.10`
3. **Deps:** `pip install -r requirements.txt`
4. **Hooks:** `pre-commit install`

---

## 📜 Changelog

* **2026-01-22:** Initial repository bootstrap. Established **Nvidia Showreel Protocol** (ADRs, Pre-commit, Hybrid Access).
