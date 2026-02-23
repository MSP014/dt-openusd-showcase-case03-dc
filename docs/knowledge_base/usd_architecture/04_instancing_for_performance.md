# Protocol 04: Instancing for Performance

When assembling highly repetitive architecture (e.g., 160 GB203 server nodes inside identical 42U racks), we must eliminate standard geometry references and enforce **USD Instancing**.

> [!WARNING]
> Without instancing, a Digital Twin datacenter will quickly choke both RAM and GPU memory.

## 1. Instancing Architecture Contract

Instancing is USD's solution to repetitive loading. It loads a single **Prototype** (the blueprint) and generates 160 lightweight **Instances** (pointers) to it.

To execute this correctly, adhere to this hierarchy:

1. **The Prototype:** Store the heavy asset (the Component USD) under a designated prototype scope (e.g., `/World/Prototypes/Server_GB203`).
2. **The Payload:** The heavy geometry Payload must be loaded *inside* this Prototype.
3. **The Instances:** Generate the 160 layout pointers (e.g., `/World/Row_A/Rack_1/Server_...`). **This** is where the `instanceable = true` flag is placed. Never place it on the Prototype itself.

## 2. Material Overrides on Instances (Primvars)
>
> [!IMPORTANT]
> If we instance 160 servers, they geometrically share the same Prototype and material. Point Instancing does not natively allow direct material changes per-instance.

To visualize dynamic data (e.g., a Thermal Heatmap where Server A glows red and Server B stays blue), we must use **Primitive Variables (Primvars)**.

* Author `primvars:displayColor` or custom namespace primvars on the instance points in Houdini.
* The Hydra render engine dynamically reads these primvars at render-time and passes them into the shader attached to the Prototype, allowing identical instances to render with unique visual states.

## 3. Dynamic Simulation Restriction

If simulating airflow VDBs, exhaust particulate matter, or dynamic heat fields, each rack has a unique thermal profile. **Do not instance volatile simulation data.** Treat fluid/gas dynamics as unique Per-Asset logic.

---

## ✅ Definition of Done (DoD)

- [ ] The `instanceable=true` tag is verified on all 160 Server Reference pointers, not the Prototype.
* [ ] Memory footprint confirms prototype geometry is loaded exactly once by the renderer.
* [ ] Heatmap visualizers successfully read `primvars:` data to colorize physically identical instances differently.
