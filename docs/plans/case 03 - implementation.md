# Case 03: Data Center Digital Twin (L1) — Implementation Plan

**Jira Project**: DC
**Status**: In Progress
**Last Updated**: 2026-02-04

---

## 🧩 EPIC: Architectural Shell (DC-1)

**Status**: 🔄 In Progress | **Priority**: Medium

### 🔄 [DC-10] Blocking - Server Room Layout & Scale

**Status**: 🔄 In Progress | **Priority**: Medium | **Estimate**: 4h

### ⏸️ [DC-11] Modeling - Raised Floor System

**Status**: ⏸️ To Do | **Priority**: Medium | **Estimate**: 4h

### ⏸️ [DC-12] Modeling - Ceiling & Lighting System

**Status**: ⏸️ To Do | **Priority**: Medium | **Estimate**: 4h

### ⏸️ [DC-13] Modeling - Walls, Doors & Details

**Status**: ⏸️ To Do | **Priority**: Medium | **Estimate**: 4h

### ⏸️ [DC-14] LookDev - Basic Architectural Materials

**Status**: ⏸️ To Do | **Priority**: Medium | **Estimate**: 4h

### ⏸️ [DC-15] Lighting - Basic Environment Light

**Status**: ⏸️ To Do | **Priority**: Medium | **Estimate**: 4h

### ✅ [DC-9] Architectural Shell - Refs

**Status**: ✅ Done | **Priority**: Medium | **Estimate**: 2h
**Logged**: 2h

---

## 🧩 EPIC: Core Hardware (DC-2)

**Status**: ⏸️ To Do | **Priority**: Medium

### 🔄 [DC-16] Asset R&D - Blackwell Rig v1.0

**Status**: 🔄 In Progress | **Priority**: Medium | **Estimate**: 1d
**Objective**: Review the Nvidia Datacenter asset library; select specific
  models for racks, servers (1U, 2U, GPU), switches, and PDUs required for the
  scene. Test the import process of the selected Nvidia USD assets into
  Houdini/Solaris (via Reference or Sublayer); validate geometry, hierarchy,
  scale, and identify potential issues (e.g., broken geometry, inconsistent
  naming conventions). Gather references only for understanding typical rack
  configurations or if a custom 'Hero' unit is decided upon.  --- Frozen
  Specifications (Blackwell Rig v1.0):  Chassis: SilverStone RM44 (4U Rackmount)
  GPU: 3x NVIDIA RTX 4500 Blackwell (reduced from 4x to fit NIC) Connectivity:
  1x NVIDIA ConnectX-7 (InfiniBand/RDMA) - Occupies 4th slot Platform: AMD Ryzen
  Threadripper PRO 7975WX + ASUS WRX90E-SAGE SE Ram: 512 GB DDR5 ECC (INT8
  Optimization)Power: 1600W Titanium PSU  Output Artifacts: - Approved Concept:
  docs/knowledge_base/main_concept.md - Hardware List: Validated manually.
**Logged**: 3d 46m

### ⏸️ [DC-17] Server Rack Assembly - Core Hardware

**Status**: ⏸️ To Do | **Priority**: Medium | **Estimate**: 1d
**Objective**: Assemble one or several 'master' rack configurations within
  Solaris, placing the imported server, switch, and PDU assets according to
  reference or typical layouts. Establish the base setup for populating the data
  hall scene with multiple racks.

### ⏸️ [DC-18] LookDev - MaterialX Creation & Assignment - Core Hardware

**Status**: ⏸️ To Do | **Priority**: Medium | **Estimate**: 1d
**Objective**: Develop the necessary library of MaterialX master materials
  (e.g., powder-coated metal, anodised aluminium, matte plastic, copper
  heatsinks, LED emitters). Design and implement a procedural system within
  Solaris to assign these materials to all imported Nvidia geometry (and any
  optional 'Hero' assets), utilising rules based on USD paths and primitive
  names (Assign Material node + Collections).

---

## 🧩 EPIC: Cooling System (DC-3)

**Status**: ⏸️ To Do | **Priority**: Medium

### ⏸️ [DC-19] CRAC Units - Research & References

**Status**: ⏸️ To Do | **Priority**: Medium | **Estimate**: 1d
**Objective**: Gather high-quality reference imagery and technical
  specifications for modern, high-capacity Computer Room Air Conditioner (CRAC)
  units. Focus on form, scale, vents, and connection points for under-floor air
  delivery.

### ⏸️ [DC-20] CRAC Units - Modelling

**Status**: ⏸️ To Do | **Priority**: Medium | **Estimate**: 1d
**Objective**: Model the 'Hero' CRAC units based on the collected references
  (from the task above). Ensure models are optimised but detailed enough for
  medium/close shots.

### ⏸️ [DC-21] Rack Intake & Exhaust System

**Status**: ⏸️ To Do | **Priority**: Medium | **Estimate**: 1d
**Objective**: Design and model the modular components for the Rack Chimney
  architecture. This includes the direct air intake plenum (connecting the
  raised floor to the rack base) and the exhaust system (the top-mounted
  chimney, including the integrated exhaust fan module).

### ⏸️ [DC-22] Main HVAC Ducts

**Status**: ⏸️ To Do | **Priority**: Medium | **Estimate**: 1d
**Objective**: Model the large, primary overhead HVAC (Heating, Ventilation, and
  Air Conditioning) ducts. These are the main trunk lines that collect the hot
  air from the individual rack exhaust systems.

### ⏸️ [DC-23] Cooling System Materials

**Status**: ⏸️ To Do | **Priority**: Medium | **Estimate**: 1d
**Objective**: Create and augment the MaterialX library for all components
  within this epic (CRAC units, intake/exhaust systems, HVAC ducts). Focus on
  industrial painted metal, galvanised steel, and matte plastic for fan blades.

---

## 🧩 EPIC: Power & Cabling System (DC-4)

**Status**: ⏸️ To Do | **Priority**: Medium

### ⏸️ [DC-24] Cable Infrastructure - Research & References

**Status**: ⏸️ To Do | **Priority**: Medium | **Estimate**: 4h
**Objective**: Gather high-quality reference imagery for both power and network
  cabling infrastructure within modern data centres. Focus on identifying types
  of cable trays (e.g., ladder, mesh, basket), overhead mounting solutions, and
  best practices for cable management (bundling, separation of power vs.
  data).Validated the use of overhead track busways (Starline style) with A/B
  feed redundancy as the standard for High-Performance Computing (HPC)
  environments. Gathered key visual references for tap boxes with IR windows and
  technical data (800-1200A, up to 100kW/rack) to ensure authentic FUI
  visualisation.

### ⏸️ [DC-25] Power Distribution Units (PDUs) - Modelling

**Status**: ⏸️ To Do | **Priority**: Medium | **Estimate**: 4h
**Objective**: Model the 'in-rack' vertical PDUs (Power Distribution Units)
  where the servers' power cables will connect. These can be based on the Nvidia
  library assets or modelled as custom 'Hero' assets if required for close-ups.

### ⏸️ [DC-26] Power Cable Trays - Modelling

**Status**: ⏸️ To Do | **Priority**: Medium | **Estimate**: 4h
**Objective**: Design and model the modular tray/conduit system specifically for
  power cables. This infrastructure will run from the main room
  PDUs/distribution panels towards the server racks.

### ⏸️ [DC-27] Network Cable Trays - Modelling

**Status**: ⏸️ To Do | **Priority**: Medium | **Estimate**: 4h
**Objective**: Design and model a separate, parallel tray system for network
  (data) cables. These trays must be physically separate from the power trays
  (from the task above) to realistically prevent electromagnetic interference
  (EMI).

### ⏸️ [DC-28] Procedural Cables creation — Vellum Sim R&D

**Status**: ⏸️ To Do | **Priority**: Medium | **Estimate**: 4h
**Objective**: Conduct initial research and development into the Vellum
  simulation workflow for procedural cable generation. The goal is to establish
  a robust, non-intersecting, and controllable setup that can be applied to both
  power and network cables.

### ⏸️ [DC-29] Procedural Power Cables - Vellum Sim

**Status**: ⏸️ To Do | **Priority**: Medium | **Estimate**: 4h
**Objective**: Execute the pre-defined Vellum simulation (developed in the R&D
  task) to procedurally generate the heavy-duty power cables. These cables must
  realistically run from servers to the in-rack PDUs and populate the main power
  trays.

### ⏸️ [DC-30] Procedural Network Cables - Vellum Sim

**Status**: ⏸️ To Do | **Priority**: Medium | **Estimate**: 4h
**Objective**: Execute the separate Vellum simulation for high-density network
  cables (e.g., fibre optic, Cat6). These cables must realistically populate the
  dedicated network trays and run towards the server and switch ports.

### ⏸️ [DC-31] Power & Cabling System - Materials

**Status**: ⏸️ To Do | **Priority**: Medium | **Estimate**: 4h
**Objective**: Create the complete MaterialX library for all components in this
  epic: various plastic sheathings (e.g., black/red for power; blue/yellow for
  network), and galvanised/painted metal finishes for the cable trays and PDUs.

---

## 📊 Progress Summary

| Epic | Status | Priority | Completion |
| --- | --- | --- | --- |
| Architectural Shell | 🔄 In Progress | Medium | 14% (1/7) |
| Core Hardware | ⏸️ To Do | Medium | 0% (0/3) |
| Cooling System | ⏸️ To Do | Medium | 0% (0/5) |
| Power & Cabling System | ⏸️ To Do | Medium | 0% (0/8) |

---

## 🎯 Next Priorities

1. **DC-10**: Blocking - Server Room Layout & Scale (Priority: Medium)
2. **DC-11**: Modeling - Raised Floor System (Priority: Medium)
3. **DC-12**: Modeling - Ceiling & Lighting System (Priority: Medium)
4. **DC-13**: Modeling - Walls, Doors & Details (Priority: Medium)
5. **DC-14**: LookDev - Basic Architectural Materials (Priority: Medium)
