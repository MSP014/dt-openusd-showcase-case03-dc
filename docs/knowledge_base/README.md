# Knowledge Base: "Forced-Flow" Inference Refinery

> [!NOTE]
> This directory serves as the **Single Source of Truth (SSOT)** for all engineering and conceptual documentation regarding the Case 03 Digital Twin.

## 🧠 Core Documentation

The overarching mechanics, definitions, and logics of the Digital Twin.

* **[Digital Twin Main Concept](./main_concept.md)**
  The foundational design document. Explains the "Forced-Flow" aerodynamic logic, the Procedural Telemetry system (Noise/Grades), and the hierarchical HUD-driven Level of Detail (LOD) visualization.
* **[Hardware Specification](./hardware_specification.md)**
  Power loads, dimensional guidelines, and Cooling Efficiency Factors (CEF) calculations defining the physical constraints of the 16-rack layout.
* **[Digital Twin Maturity Levels](./digital_twin_maturity_levels.md)**
  Strategic justification identifying this project precisely as a **Level 1** Digital Twin. *(Includes authoritative PDF reference).*

---

## 🏗️ USD Architecture & Pipeline Contract

Strict engineering guidelines for translating the concept into NVIDIA Omniverse via SideFX Houdini.

* **[📂 usd_architecture/](./usd_architecture/)**
  Contains sequentially numbered mandates (`00` to `06`). It thoroughly dictates asset handling, metadata (`Kinds`, `Purpose`, `LODs`), instancing laws, and how to format Python-queryable `primvars` (the data backbone of the twin). **No asset enters the pipeline without passing these contracts.**

---

## ⚙️ Hardware Reference Inventory

Detailed operational and dimensional reference hubs for the specific physical components being simulated.

> [!IMPORTANT]
> **To preserve a clean repository**, source working files (like `.hip`, `.ae`, or external heavy assets) and raw reference scraping folders (like `/refs`) are strictly **git-ignored** per the project limits. The folders below contain the curated MarkDown data and specs intended for version control.

* **[📂 rtx_pro_4500_blackwell/](./rtx_pro_4500_blackwell/)**
  The hero asset. Architecture specs for the GB203 die, blower turbine speeds, and internal motherboard configurations.
* **[📂 pro_ws_wrx90e-sage_se/](./pro_ws_wrx90e-sage_se/)**
  The baseline 4U motherboard framework (ASUS).
* **[📂 nvidia_connectx-7/](./nvidia_connectx-7/)**
  Network topography specifications, detailing the OSFP transceiver architecture and DR4 cabling utilized for inter-rack linking.
* **[📂 noctua_nh-d9/](./noctua_nh-d9/)**
  Dimensional specs for the 4U active CPU extraction towers.
