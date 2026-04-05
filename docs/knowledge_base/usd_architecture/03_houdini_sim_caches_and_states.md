# Guideline 03: Houdini Simulation Caches and States

A static jet engine is just a CAD model. To achieve the "Digital Twin" capability (Case 02), we must integrate heavy Houdini simulation caches (VDB volumes, geometry sequences) representing physical phenomena (thermodynamics, fluid flow).

These caches must switch dynamically based on the 4 engine regimes:

- **Idle**
- **Takeoff**
- **Cruise**
- **Maximum Thrust**

## 1. Rule of Segregation

Never mix static mechanical geometry with dynamic simulation caches in the same USD file.

- **Mechanical Assembly:** `/Engine/Combustion_Chamber` (Payload)
- **Simulation Data:** `/Engine/Simulations/Combustion_Flame` (Payload)

This ensures the mechanical team and FX team can work independently without locking files.

## 2. Managing Simulation States (VariantSets)

The 4 engine regimes are handled via a USD **VariantSet** applied to the `/Engine/Simulations` hierarchy.

1. **VariantSet Name:** `EngineRegime`
2. **Variants:** `Idle`, `Takeoff`, `Cruise`, `MaxThrust`.

By switching the `EngineRegime` variant at the top level, all child simulation caches (flames, exhaust, airflow) will automatically swap their active payloads to the correct simulation sequence.

## 3. Handling Time-Varying Data

Heavy VDB sequences (e.g., a 200-frame Takeoff flame sequence) must be managed using USD **Value Clips**.

- Do **not** author 200 individual frame payloads.
- Use Houdini's USD ROP to stitch the `.vdb` frames into a lightweight topology/manifest file and point a Value Clip at the sequence.

---

## ✅ Definition of Done (DoD)

- [ ] Combustion and exhaust simulations are separated from mechanical geometry.
- [ ] An `EngineRegime` VariantSet exists at the `/Engine/Simulations` root level to toggle states.
- [ ] VDB sequences are written using Value Clips to prevent monolithic file sizes and RAM exhaustion.
