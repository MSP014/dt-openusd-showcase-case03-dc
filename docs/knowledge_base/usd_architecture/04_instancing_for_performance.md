# Guideline 04: Instancing for Performance

Instancing is a future-scale optimization for repeated servers, racks, and
other high-count assets. It is not required for Blackwell Monitoring Suite v0.1.

## 1. Current Baseline

The v0.1 CPU cooler asset preview should prioritize correctness, readable
hierarchy, path portability, and stable rendering in Omniverse.

Do not introduce instancing until the scene scale makes it necessary.

## 2. Future Instancing Target

When Case 03 reaches rack and data hall scale, repeated server nodes should be
composed with USD instancing or point instancing where it meaningfully reduces
memory and scene load cost.

Recommended structure:

1. **Prototype:** shared heavy asset under a stable prototype scope, such as
   `/World/Prototypes/Server_GB203`.
2. **Payload:** heavy geometry loaded inside the prototype when lazy loading is
   useful.
3. **Instances:** layout pointers under rows/racks/nodes with
   `instanceable = true` on the pointers, not the prototype asset.

## 3. Per-Instance Visual Data

If repeated instances need unique visual state, such as heatmap color or
workload status, use runtime-readable data bindings rather than duplicating
geometry.

Candidate approaches:

- primvars on instance points;
- authored per-instance attributes;
- material parameters driven by runtime state;
- external telemetry mapping in Blackwell Monitoring Suite.

The exact approach becomes mandatory only when workload, telemetry, or scale
navigation stages need it.

## 4. Simulation Data

Do not instance volatile simulation data blindly. Airflow, heat, smoke, and
streamline caches may need unique layers per rack, state, or scene scale.

## Definition of Done

- v0.1 does not add instancing just for architecture purity.
- Future repeated server/rack layout proves memory benefit before instancing is
  treated as mandatory.
- Instance-specific visual state has a documented data path before it appears
  in the runtime.
