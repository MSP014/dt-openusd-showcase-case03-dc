# Case 03: Blackwell Monitoring Suite Concept

> **Philosophy:** Reproducible Tech Pack - a staged Houdini/OpenUSD to
> Omniverse runtime project that demonstrates authored hardware assets,
> hydrated USD packaging, synthetic telemetry, cached engineering
> visualization, and interactive review inside Blackwell Monitoring Suite.

## 1. Current Truth Boundary

Blackwell Monitoring Suite is the public application name for the Case 03
runtime.

The current implementation path is staged:

1. **v0.1 Asset Preview:** launch the Kit application, read runtime config,
   resolve `assets/_external/`, load the Noctua NH-D9 TR5-SP6 CPU cooler USD,
   and show load/render/runtime status.
2. **Look Review:** add lighting and exposure controls for asset review.
3. **Synthetic Telemetry:** generate runtime telemetry while the app is open.
4. **Telemetry Driven Motion:** drive CPU cooler fan motion from telemetry.
5. **Server Review:** load the full Blackwell Rig/server scene.
6. **Cached Simulation Playback:** enable real exported airflow or thermal
   cache layers.
7. **Manual Workload State Preview:** expose `25%`, `50%`, `75%`, and `96%`
   preview states only when real USD/material/cache/runtime hooks exist.
8. **Scale Navigation:** navigate deliberately between server, rack, and data
   hall scales.

Anything beyond the active stage is target architecture, not completed runtime
behavior.

## 2. High-Level Concept

**Project:** Blackwell Monitoring Suite, an Omniverse Kit application for the
Case 03 Data Center showreel.

**Mission:** demonstrate a controlled review surface for a Blackwell-based data
center digital-twin concept, starting from real authored hardware assets and
growing toward telemetry-driven operational visualization.

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

- Rack-scale views aggregate node behavior into intake, exhaust, pressure, and
  cooling-effort stories.
- Full rack behavior is future scope until the server scene and rack assets are
  stable in the runtime.

### Level Hall

- Data hall views are the highest abstraction level.
- Hall-scale PUE, facility airflow, row-level status, and macro thermal cues
  remain target architecture until the staged runtime reaches scale navigation.

## 4. Operational States

The long-term state model is:

| State | Demo Load | Description | Visual Cues |
| :--- | :--- | :--- | :--- |
| **Idle** | 25% | Low active service state | Low RPM, calm airflow, cool lighting. |
| **Nominal** | 50% | Routine inference | Steady cooling, stable LEDs, balanced thermal profile. |
| **Surge** | 75% | High traffic | Fans ramp up, visible heat buildup, stronger airflow. |
| **Critical** | 96% | Inference surge / stress preview | Maximum cooling response, warning LEDs, aggressive thermal cues. |

These states are planned manual preview states until the runtime connects them
to real USD variants, material overrides, cached simulation layers, or live
telemetry hooks.

## 5. Visual Modes

Long-term visual modes may include:

- **Photoreal / Review:** conventional PBR asset review.
- **Engineering X-Ray:** transparent or simplified geometry with thermal
  overlays.
- **Velocity / Streamlines:** cached or generated airflow vectors and
  qualitative airflow paths.
- **Telemetry HUD:** compact status panels for selected hardware or scene
  scale.

These modes are not v0.1 requirements. v0.1 only needs the CPU cooler asset
preview and reliable runtime status.

## 6. Runtime Architecture

### Layer 1: Houdini/OpenUSD Asset Factory

Houdini remains responsible for modeling, UVs, materials, normals, LOD cleanup,
and exported USD composition. Blackwell Monitoring Suite does not repair
geometry at runtime.

### Layer 2: Hydrated Asset Package

Heavy runtime assets live under `assets/_external/` and are hydrated outside
Git:

- USD assets;
- textures;
- HDRIs;
- VDBs and future cached simulation layers;
- any other heavy runtime package assets.

Runtime paths must be relative or explicitly configurable.

### Layer 3: Blackwell Monitoring Suite Runtime

The runtime is a standalone Omniverse Kit application:

- app title: `Blackwell Monitoring Suite`;
- first extension id: `msp.bw.monitoring`;
- source root: `src/blackwell_monitoring_suite/`;
- v0.1 config: `configs/blackwell_monitoring_suite.v0.1.toml`;
- first asset id: `noctua_nh_d9_tr5_sp6`;
- first USD asset path under asset root: `usd/cpu_fan/cpu_fan.usd`.

Runtime behavior is added in stages. Commands and shared state should stay
separate from button callbacks so a future external control surface can drive
the same operations without replacing the Kit viewer.

### Layer 4: Future Control and Packaging

A React/FastAPI control surface, package wrapper, container, streaming setup,
or cloud deployment may become useful later. They are not part of the current
staged build.

The current priority is path-portable local Kit runtime first, package-ready
later.

## 7. Synthetic Telemetry Direction

Synthetic telemetry exists because there is no live data center telemetry
source for the showreel. The goal is to prove the interaction model:

- telemetry values update while the app is running;
- fan RPM, temperatures, power draw, LEDs, heatmaps, and airflow visuals can be
  driven from data instead of a DCC timeline;
- a future live provider can replace the demo provider without changing the
  presentation layer.

This is a direction for Stage 3 and later, not v0.1.

## 8. Simulation Direction

Houdini-solved airflow and thermal caches are controlled demonstration inputs,
not validated CFD benchmarks.

Future cache layers may include:

- VDB density or temperature fields;
- BasisCurves streamlines;
- material overrides for thermal states;
- state-specific visual layers for workload previews.

No runtime stage should claim cached simulation playback until real exported
cache assets exist and Blackwell Monitoring Suite can load or enable them.

## 9. USD Architecture Boundary

ADR007 and `docs/knowledge_base/usd_architecture/` define the current USD
baseline and future target architecture. They no longer mean that every asset
must already implement the final server/rack/data hall contract.

Current assets should prioritize:

- stable relative paths;
- readable prim hierarchy;
- clean UVs and normals for Omniverse;
- disabled or deferred unvalidated LOD variants;
- hydrated asset package compatibility;
- runtime-addressable parts where future behavior needs them.

Future large-scale assets may add payloads, references, instancing, material
libraries, telemetry primvars, and cached state variants as the staged runtime
reaches those needs.

## 10. Implementation Notes

- Stage 1 should not implement cameras, scene groups, diagnostics, telemetry,
  workload states, server/rack/data hall navigation, or built-in media tools.
- The first practical runtime behavior target after telemetry exists is CPU
  cooler fan motion.
- The CPU cooler USD currently exposes a named fan blade prim at
  `/cpu_fan/geo/render/cpu_cooler/cpu_fan/blades/blades`; pivot and rotation
  axis should be checked during Stage 4 implementation.
- Public documentation should describe the staged Blackwell Monitoring Suite
  direction, not local template paths or workstation-only workflows.
