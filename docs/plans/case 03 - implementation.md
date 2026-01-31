# Case 03: Data Center (L1) — Implementation Plan

**Jira Project**: DC
**Status**: In Progress
**Last Updated**: 2026-02-01

---

## 🧩 EPIC: Architectural Shell (DC-1)

**Status**: 🔄 In Progress

### ⏸️ [DC-12] Modeling - Ceiling & Lighting System

**Status**: To Do
**Estimate**: 4h
**Objective**: Model the ceiling structure (grid/panels) and the primary lighting fixture placement (overhead LED strips).
**Definition of Done**:

- Ceiling geometry matches reference scale.
- Lighting fixtures placed in logical array.
- USD export ready for assembly.

### ⏸️ [DC-13] Modeling - Walls, Doors & Details

**Status**: To Do
**Estimate**: 4h
**Objective**: Model the perimeter walls, access doors, and structural columns. Include basic architectural detailing (baseboards, trims, vents).
**Definition of Done**:

- Watertight geometry for walls/doors.
- Pivot points set correctly for doors.
- Scale valid for 4U rack placement.

### ⏸️ [DC-14] LookDev - Basic Architectural Materials

**Status**: To Do
**Estimate**: 4h
**Objective**: Create and assign basic architectural shaders (Paint, Concrete, Plastic, Glass) for the shell.
**Definition of Done**:

- MaterialX/MDL shaders created.
- Textures (tileable) assigned correctly.
- Test render in Karma/Omniverse matches reference mood.

### ⏸️ [DC-15] Lighting - Basic Environment Light

**Status**: To Do
**Estimate**: 4h
**Objective**: Setup the base HDRI and key lighting for the data hall to establish the visual baseline.
**Definition of Done**:

- HDRI environment map configured.
- Exposure balanced for standard EV.

---

## 🧩 EPIC: Core Hardware (DC-2)

**Status**: 🔄 In Progress

### ⏸️ [DC-16] Asset R&D - Blackwell Rig v1.0 (SilverStone RM44)

**Status**: To Do
**Estimate**: 8h
**Objective**: Review standard asset library and assemble the custom "Blackwell Rig v1.0".
**Frozen Specifications**:

1. **Chassis**: SilverStone RM44 (4U Rackmount)
2. **GPU**: 3x NVIDIA RTX 4500 Ada/Blackwell
3. **Connectivity**: 1x NVIDIA ConnectX-7 (InfiniBand/RDMA)
4. **Platform**: AMD Ryzen Threadripper PRO 7975WX
5. **Ram**: 512 GB DDR5 ECC (INT8 Optimization)
6. **Power**: 1600W Titanium PSU

**Definition of Done**:

- Assets imported and verified in Houdini/Solaris.
- Geometry clean, scale accurate.
- "Hero" rig assembly saved as USD.

### ⏸️ [DC-17] Server Rack Assembly - Core Hardware

**Status**: To Do
**Estimate**: 8h
**Objective**: Assemble one 'master' rack configuration within Solaris (10x nodes/rack), placing the imported server, switch, and PDU assets.
**Definition of Done**:

- Procedural assembly setup (Point Instancing).
- Rack populated with 10x Blackwell Rigs + Switches/PDUs.
- Optimised for instancing (Scenegraph).

### ⏸️ [DC-18] LookDev - MaterialX Creation & Assignment

**Status**: To Do
**Estimate**: 8h
**Objective**: Develop library of MaterialX master materials (powder-coated metal, matte plastic, copper, LED emitters) and assign via procedural rules.
**Definition of Done**:

- Material library created.
- Procedural assignment rules (Collections) working.
- Render validation in Karma/Omniverse.

### ⏸️ [DC-19] CRAC Units - Research & References

**Status**: To Do
**Estimate**: 4h
**Objective**: Research Computer Room Air Conditioning (CRAC) units suitable for the scale.
**Definition of Done**:

- Reference board compiled.
- Model selected/approved.

### ⏸️ [DC-20] CRAC Units - Modelling

**Status**: To Do
**Estimate**: 4h
**Objective**: Model the CRAC units based on selected reference.
**Definition of Done**:

- Geometry modelled and UV mapped.
- Ready for texturing.
