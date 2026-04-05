# Guideline 02: Instancing Radial Geometry

A jet engine is defined by extreme repetition mapped to radial arrays: hundreds of identical compressor blades, stator vanes, and thousands of identical fasteners.

We must eliminate standard geometry references for these elements and enforce **USD Point Instancing**.

> [!WARNING]
> If you load 300 individual referenced copies of a high-poly turbine blade, the scene will choke. You must instance them.

## 1. Instancing Architecture Contract

Instancing loads a single **Prototype** (the blueprint) into memory once, and generates lightweight **Instances** (pointers) to it.

To execute this correctly for Case 02:

1. **The Prototype:** Store the heavy asset (the blade CAD) under a designated prototype scope (e.g., `/Engine/Prototypes/Blade_HPC_Stage1`).
2. **The Payload:** The heavy geometry Payload must be loaded *inside* this Prototype.
3. **The Instances:** Generate the radial layout points (e.g., `/Engine/Compressor_HPC/Stage1/Blades`). **This** PointInstancer primitive is where the `instanceable = true` flag operates.

### Houdini LOPs Workflow

In Houdini, use the **Instancer LOP**. Feed the single prototype geometry into the first input, and a point cloud representing the radial layout of the specific compressor stage into the second input.

## 2. Material Overrides on Instances (Primvars)

> [!IMPORTANT]
> If we instance 300 blades, they geometrically share the same Prototype and material. Point Instancing does not natively allow direct material changes per-instance.

To visualize dynamic data (e.g., a Thermal Heatmap where tip blades are hotter than root blades), we must use **Primitive Variables (Primvars)**.

* Author `primvars:displayColor` or custom namespace primvars on the instance points in Houdini.
* The Hydra render engine dynamically reads these primvars at render-time and passes them into the shader attached to the Prototype, allowing physically identical instances to render with unique heat gradients.

---

## ✅ Definition of Done (DoD)

* [ ] Mechanical stages with repetitive parts (compressors, turbines) utilize `PointInstancer` primitives.
* [ ] Memory footprint confirms the prototype geometry for a blade is loaded exactly once by the renderer.
* [ ] Thermal heatmaps successfully read `primvars:` data to colorize physically identical radial instances differently.
