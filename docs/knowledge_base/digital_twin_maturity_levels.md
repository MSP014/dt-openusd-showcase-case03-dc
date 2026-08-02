# Digital Twin Maturity Levels — Classification Framework


**Source:** Academic research (Tao et al.) and industry frameworks
**Date:** 2026-02-01
**Context:** Reference documentation for Case 03 (Data Center) Digital Twin classification
Link: https://ieeexplore.ieee.org/document/9807313

## Overview

Digital Twin maturity levels classify the sophistication and capabilities of a digital twin, progressing from basic descriptive models to highly autonomous and predictive systems. The classification extends from **L0 (static replica)** to **L5 (autonomous co-existence)**, with the core operational levels being L1-L3.

---

## Level Definitions

### L0: No Twin / Static Model

**Descriptor:** Descriptive / Static Replica

**Characteristics:**

- No active digital twin or only a static 3D model
- Describes and depicts the physical entity without real-time data connection
- Measurements are disparate or non-existent
- Sensors are not interconnected

**Use Cases:**

- Visualisation
- Planning and communication
- CAD/BIM models for documentation
- Geometry and material representation

**Key Limitation:** No dynamic behaviour or connection to the physical world.

---

### L1: Status / Reflecting the Real with the Virtual

**Descriptor:** Informative (Real-Time Data) / Connected - Manual

**Characteristics:**

- Real-time data capture from sensors
- Replicates the real-time state and changes in the physical entity
- Continuous monitoring of asset condition and performance
- Primary function: **"What is happening right now?"**

**Use Cases:**

- Real-time status dashboards
- Condition monitoring
- Performance tracking
- Asset visibility
- **FUI/HUD overlays for real-time telemetry**

**Data Flow:** Physical Asset → Sensors → Digital Twin (Visualisation)

**Key Capability:** Reflects current conditions dynamically.

---

### L2: Controlling the Real with the Virtual

**Descriptor:** Informative (Real-Time + Historical Data) / Connected - Supervisory / Decision Support

**Characteristics:**

- Real-time data + historical data or benchmarks
- Can indirectly control the physical entity's operations
- Enables informed decision-making and analysis
- Captures and estimates effects of real-world events using historical data
- Primary function: **"What should I do about it?"**

**Use Cases:**

- Predictive maintenance (early stage)
- Asset optimisation
- Decision support systems
- Supervisory control (operator-in-the-loop)

**Data Flow:** Physical Asset ↔ Digital Twin ↔ Operator (Decision Support)

**Key Capability:** Supports operational decisions through analysis and recommendations.

---

### L3: Anticipating the Real with the Virtual

**Descriptor:** Predictive / Forecasting

**Characteristics:**

- Forecasts future state and operational processes
- Couples real-time + historical data with ML or physical process-based models
- Predicts future behaviour and performance
- Primary function: **"What will happen next?"**

**Data Flow:** Physical Asset → Digital Twin → ML/Simulation Models → Predictions → Operator

**Key Capability:** Predictive analytics and future state forecasting.

---

## Case 03 (Data Center) — Classification Justification

**Classified Level:** **L1 (Informative / Connected)**

### Scenario

Visualisation of a high-load AI Inference Farm cluster. The digital twin displays critical infrastructure parameters: Power consumption (active load), Cooling efficiency (temperature hot/cold aisles), and Network throughput.

### L1 Characteristics Present

- ✅ **Asset Visibility:** Detailed "SimReady" representation of server racks, cabling, and cooling units.
- ✅ **Condition Monitoring:** Visualising temperature spikes ("Hot Spots") when a compute load increases.
- ✅ **Reflecting the Real:** The environment reacts to the simulated workload (servers light up, fans spin up).
- ✅ **Primary function:** Answers "Is the system stable under this render load?"

### Why Not L0?

It connects the visual state of the server LEDs and heat haze to simulated data streams (Simulated "Inference Surge").

### Why Not L2?

L2 implies active control (e.g., the twin automatically adjusting the cooling system based on data). Case 03 visualises the *reaction* of the cooling system, but for the purpose of this Showreel, it remains a monitoring tool (L1).

---

## Project Focus Areas

1. **Photo-realism:** "SimReady" assets (USD) that look indistinguishable from real hardware.
2. **Data-Driven Animation:** Using Python to drive thousands of LED indicators based on a CSV resource log.
3. **Infrastructure Visualization:** Translating invisible metrics (Airflow, Power) into visible cues.

---

## References

1. Tao et al. — Digital Twin Maturity Framework
2. [Digital Twin Atlas](https://digital-twin-atlas.com/)
3. NVIDIA "Omniverse Digital Twin" Whitepapers

---

**Document Status:** Knowledge Base Entry
**Last Updated:** 2026-02-01
**Maintained by:** Case 03 Engineering
