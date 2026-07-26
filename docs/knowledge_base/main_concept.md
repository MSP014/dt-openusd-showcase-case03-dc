# Case 03: Digital Twin Runtime Suite Concept

> **Philosophy:** Reproducible Tech Pack - a Houdini/OpenUSD-to-Omniverse
> runtime project that demonstrates authored hardware assets, hydrated USD
> packaging, synthetic telemetry, qualitative engineering visualisation, and
> interactive review inside Digital Twin Runtime Suite.

## 1. Current Product Boundary

Digital Twin Runtime Suite (DTRS) is the public Omniverse Kit application for
the Case 03 runtime. Its configured default asset is the complete **Blackwell
Rig GB203** server assembly, loaded from the hydrated external asset package.

The current runtime provides:

- full-server RTX viewport review with persistent enclosure, lighting, grid,
  and camera controls;
- a synthetic node telemetry provider with selectable workload modes and
  telemetry-driven fan motion across the server;
- manifest-driven temporal VTI velocity playback through Kit-CAE and NVIDIA
  Flow for the selected airflow dataset;
- operator controls for Cloud smoke appearance, transport, and procedural
  intake-emitter layout, persisted as local runtime overrides;
- temporal, spatial, and lifecycle checks for the VTI-to-Kit-CAE-to-Flow path.

The current airflow visualisation is a qualitative technical-review tool. The
Houdini-solved velocity fields are controlled demonstration inputs, not a
validated CFD benchmark or a certified thermal result.

The following remain future work rather than current product behaviour:

- live telemetry adapters and automatic telemetry-to-dataset state binding;
- Engineering X-Ray, vector streamlines, and thermal heatmaps;
- rack- and hall-scale runtime navigation;
- external web control surfaces, streaming, containers, and cloud deployment.

## 2. High-Level Concept

**Project:** Digital Twin Runtime Suite, an Omniverse Kit application for the
Case 03 Data Center showreel.

**Mission:** demonstrate a controlled review surface for a Blackwell-based data
center digital-twin concept, grounded in authored hardware assets and extended
with telemetry and airflow visualisation where those signals make the system
more legible.

**Engineering logic:** the scene is treated as an air-energy system. Hardware,
cooling, airflow paths, power draw, and workload states are designed to read as
one coherent system rather than a static render.

## 3. Ecosystem Scales

### Level Node: Blackwell Rig GB203

- **Base unit:** custom 4U node based on SilverStone RM44 chassis.
- **Configuration:** AMD Threadripper PRO 7975WX, WRX90 platform, 3x NVIDIA
  RTX PRO 4500 Blackwell GPUs, ConnectX-7 networking, and high-airflow cooling.
- **Dynamics:** chassis fans, CPU cooler, GPU blowers, and PSU cooling are
  modeled as runtime-readable components where practical.
- **Thermal logic:** the PSU is treated as an active heat source so future
  visual states can show realistic heat contributors instead of only GPU heat.

### RTX PRO 4500 Hero Asset

Procedural modeling and texturing of the Blackwell GB203 node remains a major
showreel proof point.

| | | | |
| :---: | :---: | :---: | :---: |
| ![RTX PRO 4500 Blackwell - 01](../img/rtx_pro_4500/rtx_pro_4500_-_01.png) | ![RTX PRO 4500 Blackwell - 02](../img/rtx_pro_4500/rtx_pro_4500_-_02.png) | ![RTX PRO 4500 Blackwell - 03](../img/rtx_pro_4500/rtx_pro_4500_-_07.png) | ![RTX PRO 4500 Blackwell - 04](../img/rtx_pro_4500/rtx_pro_4500_-_08.png) |
| *RTX PRO 4500 Blackwell - 01* | *RTX PRO 4500 Blackwell - 02* | *RTX PRO 4500 Blackwell - 03* | *RTX PRO 4500 Blackwell - 04* |

### Level Rack

- Rack-scale views aggregate node behaviour into intake, exhaust, pressure,
  and cooling-effort stories.
- Full rack behaviour is future scope; DTRS currently operates at node scale.

### Level Hall

- Data hall views are the highest abstraction level.
- Hall-scale PUE, facility airflow, row-level status, and macro thermal cues
  remain target architecture rather than current runtime behaviour.

## 4. Operational States

DTRS currently provides synthetic workload selection for telemetry review. The
long-term state model keeps four presentation targets:

| State | Demo Load | Intended Visual Cues |
| :--- | :--- | :--- |
| **Idle** | 25% | Low cooling demand and calm airflow. |
| **Nominal** | 50% | Steady cooling and balanced thermal presentation. |
| **Surge** | 75% | Higher cooling demand and stronger airflow. |
| **Critical** | 96% | Maximum cooling response and thermal-risk cues. |

The workload target currently drives the synthetic telemetry model. Dedicated
USD variants, material overrides, state-specific airflow datasets, heatmaps,
and automatic visual-state transitions are separate future integrations.

## 5. Visual Presentation

The current viewport is a standard full-server engineering review surface with
enclosure, lighting, grid, camera, telemetry, and airflow controls.

Future presentation capabilities may include:

- **Engineering X-Ray:** transparent or simplified geometry with technical
  overlays;
- **Velocity / Streamlines:** generated vector geometry or qualitative airflow
  paths;
- **Telemetry HUD:** compact in-viewport status panels for selected hardware
  or scene scale.

These capabilities are not current DTRS modes.

## 6. Runtime Architecture

### Layer 1: Houdini/OpenUSD Asset Factory

Houdini remains responsible for modeling, UVs, materials, normals, LOD cleanup,
velocity-field generation, and exported USD composition. DTRS does not repair
geometry or re-simulate airflow at runtime.

### Layer 2: Hydrated Asset Package

Heavy runtime assets live under `assets/_external/` and are hydrated outside
Git:

- USD assets;
- textures;
- HDRIs;
- portable `airflow_datasets/` trees containing a `manifest.toml` and temporal
  VTI velocity samples;
- other future heavy runtime package assets.

Runtime paths must be relative or explicitly configurable. Dataset selection is
by manifest identity (`scope` and `state`), never by numbered directory names
or a hardcoded VTI path list.

### Layer 3: Digital Twin Runtime Suite Runtime

The runtime is a standalone Omniverse Kit application:

- app title: `Digital Twin Runtime Suite`;
- extension id: `msp.dtrs`;
- source root: `src/digital_twin_runtime_suite/`;
- runtime config: `configs/digital_twin_runtime_suite.toml`;
- default asset id: `blackwell_rig_gb203`;
- default USD asset path: `usd/Blackwell_Rig_server_assembly.usd`.

Runtime commands remain separate from OmniUI button callbacks so the same
operations can later be driven by another control surface without replacing the
Kit viewer.

### Airflow and Flow Navigation

| Module | Ownership |
| --- | --- |
| `app/airflow_dataset.py` | Manifest discovery, VTI sample ordering, and portable dataset validation. |
| `app/flow/runtime.py` | Attach, Detach, lifecycle, callback coordination, and re-attach safety. |
| `app/flow/temporal.py` | Manifest-derived temporal VTI cadence, source switching, and loop proof. |
| `app/flow/validation.py` | VTI metadata, CAE payload, origin, grid, and spatial validation. |
| `app/flow/diagnostics.py` | Optional Flow diagnostics, render probes, and spatial-sanity helpers. |
| `app/flow/smoke.py` | Intake tracers, Cloud rendering, emitter layout, and smoke-tuning authoring. |
| `app/flow/performance.py` | FPS and memory sample contracts and aggregation. |

### Runtime Performance & Rendering Trade-offs

DTRS is developed and validated on an NVIDIA GeForce RTX 3080 12GB as an
interactive technical visualisation, rather than an offline cinematic renderer.
The baseline prioritises responsive telemetry inspection, animated components,
readable volumetric flow, and functional interaction over the additional GPU
cost of higher-fidelity RTX rendering modes. Performance remains hardware- and
scene-dependent and will continue to be profiled as the runtime evolves.

### Layer 4: Future Control and Packaging

A React/FastAPI control surface, package wrapper, container, streaming setup,
or cloud deployment may become useful later. The current priority is a
path-portable local Kit runtime first and package-ready deployment later.

## 7. Synthetic Telemetry Direction

Synthetic telemetry is used because the showreel has no live data-center
telemetry source. It provides a normalized runtime signal for workload, thermal,
power, cooling, and limit presentation while keeping the current application
self-contained.

The current provider updates while the app is running and drives configured fan
motion. Future source-specific adapters can be validated against the same
normalized model without exposing source-specific schemas to the presentation
layer. Live telemetry ingestion, thermal heatmaps, and automatic airflow-cache
selection are not implemented yet.

## 8. Simulation Direction

Houdini-solved airflow is exported as temporal VTI velocity data. DTRS discovers
the selected dataset from its manifest, validates its temporal and spatial
contract, and maps the samples to Kit-CAE and NVIDIA Flow at the source-defined
cadence.

The current Flow path uses the imported VTI vector field as the velocity source
for a continuous smoke-only technical visualisation. Operator tuning changes
presentation and transport behaviour without modifying the source VTI files.

Future simulation layers may include:

- density or temperature volumes;
- BasisCurves streamlines;
- material overrides for thermal states;
- state-specific visual layers for workload previews.

Those additions must be described as runtime behaviour only after their assets,
data contract, and DTRS integration exist.

## 9. USD Architecture Boundary

ADR007 and `docs/knowledge_base/usd_architecture/` define the current USD
baseline and future target architecture. They do not mean that every asset must
already implement the final server, rack, and data-hall contract.

Current assets should prioritize:

- stable relative paths;
- readable prim hierarchy;
- clean UVs and normals for Omniverse;
- disabled or deferred unvalidated LOD variants;
- hydrated asset package compatibility;
- runtime-addressable parts where behaviour needs them.

Future large-scale assets may add payloads, references, instancing, material
libraries, telemetry primvars, and cached state variants when the runtime needs
them.

## 10. Documentation Boundary

Public documentation describes the current DTRS runtime and clearly labels
target architecture as future work. It must not depend on local template paths,
workstation-only workflows, fixed dataset file counts, or undocumented runtime
assumptions.
