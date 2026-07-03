# Case 03: Rack Modeling Plan

## Purpose

This plan defines the modelling order for the first compute rack asset in Case 03.

The rack cabinet should be built as a reusable assembly asset first. Compute and central-network racks should reuse the same cabinet assembly with different equipment population, airflow, power, and cabling variants.

The goal is to build the rack as an engineering container for airflow, power, cabling, and service access before spending time on small mechanical details. Micro-detail is only promoted when it is visible in planned shots, supports the forced-flow story, or can be reused procedurally across many racks.

## Modelling Rule

The reusable rail latch module is complete enough for the rack blockout and can be reused procedurally. Freeze further rail-latch micro-detail work until the full rack reads correctly as:

```text
rack frame
-> U-space equipment stack
-> front cold plenum
-> bottom raised-floor intake
-> rear hot / cable zone
-> top power and network exits
```

Every added detail should pass at least one of these tests:

- [ ] Visible in rack-scale or close-up shots.
- [ ] Explains airflow, power, cabling, serviceability, or containment.
- [ ] Repeats across the 16 compute racks or central network rack.
- [ ] Helps the asset look like an engineered data-centre object rather than a decorative cabinet.

## Geometry Datum / Coordinate Lock

Lock the rack coordinate system before adding more enclosure detail.

- [ ] Define the external cabinet envelope as approximately 600 x 1999 x 1000 mm.
- [ ] Define the raised-floor top surface as the facility floor datum.
- [ ] Define the bottom cabinet margin as a structural base plinth / pressure box, not as additional rack U-space.
- [ ] Define the raised 42U mounting envelope as the internal rack datum.
- [ ] Define U1 as the bottom intake plenum / air guide interface.
- [ ] Define U2-U41 as the 10x 4U Blackwell Rig GB203 node stack.
- [ ] Define U42 as the NVIDIA Quantum-2 QM9700 leaf switch slot.
- [ ] Keep the 42U mounting-post core lifted inside the outer cabinet envelope, currently by approximately 85 mm.
- [ ] Keep all rack U-number markings tied to the mounting-post datum, not to the outer cabinet floor.

U-numbering rule:

```text
Rack rails carry U-space markings: U1 ... U42.
Server labels are separate logical node IDs and can be added later as quiet labels or HUD data.
```

Working mapping:

```text
U1       = bottom intake guide
U2-U5    = Node 01
U6-U9    = Node 02
U10-U13  = Node 03
U14-U17  = Node 04
U18-U21  = Node 05
U22-U25  = Node 06
U26-U29  = Node 07
U30-U33  = Node 08
U34-U37  = Node 09
U38-U41  = Node 10
U42      = Leaf 01 / QM9700
```

## Current Production Checklist

This is the short operational checklist for the current modelling pass. Update it as the rack moves forward.

Immediate next steps:

- [x] Lock the geometry datum and U-space coordinate system.
- [x] Finish the reusable rail latch detail.
- [ ] Build the inner cabinet skeleton / support frame.
- [ ] Add attachment brackets between the inner skeleton and the 19-inch mounting-post core.
- [ ] Add door and side-panel mounting edges on the cabinet skeleton.
- [ ] Add procedural U-number markings on the front mounting posts.
- [ ] Build the glass front door proxy.
- [ ] Add the door gasket / sealing lip.
- [ ] Add side baffles for the front cold plenum.
- [ ] Convert the bottom blockout into a structural base plinth / pressure box.
- [ ] Add the internal turning vane and wide outlet into the front cold plenum.
- [ ] Add the raised-floor fragment with JetPanel-style tile.
- [ ] Add rear vertical 0U PDU proxy strips.
- [ ] Build the QM9700 medium-detail rack model.
- [ ] Block the rear top OSFP cable throat.
- [ ] Block the sloped rear/top hot-air capture hood.

## Visibility / Stop Gate

Run this gate before promoting any small mechanical detail.

- [ ] Review the rack from the front hero angle.
- [ ] Review the rack from the rear service angle.
- [ ] Review the rack from the side / airflow cutaway angle.
- [ ] Mark visible silhouette gaps.
- [ ] Mark visible airflow, power, and cable-story gaps.
- [ ] Promote only details that are visible, reusable, or required for the engineering story.
- [ ] Defer invisible micro-mechanics.

## Proxy-First Detail Budget

Keep these elements as proxy geometry until a planned shot proves they need more detail.

- [ ] Door hinges.
- [ ] Door locks.
- [ ] Side-panel mounts.
- [ ] Exact panel fasteners.
- [ ] Detailed chimney / hood mounting hardware.
- [ ] Dense cable-management hardware.
- [ ] Detailed PDU internals.
- [ ] Full internal sliding-rail mechanics.

## Phase 01: Rack Coordinate Blockout

Block the rack as a measurable engineering volume.

- [x] 42U rack bounding box.
- [x] Front/cold side and rear/hot side orientation markers.
- [x] External cabinet envelope datum.
- [x] Raised-floor top datum.
- [x] Internal 42U mounting-envelope datum.
- [ ] U1-U42 coordinate labels tied to the mounting-post core.
- [x] Internal depth zones:
  - [x] Glass door zone.
  - [x] Front cold plenum.
  - [x] Equipment envelope.
  - [x] Rear hot / cable zone.
- [x] U-space grid:
  - [x] Bottom 1U intake plenum.
  - [x] 10x 4U Blackwell Rig GB203 nodes.
  - [x] Top 1U NVIDIA Quantum-2 QM9700 leaf switch placeholder.
- [x] Simple proxy boxes for servers and switch.

Acceptance check:

```text
The rack silhouette, occupied U-space, U1 start point, front side, rear side, and airflow direction are readable without any small details.
```

## Phase 02: Structural Rack Frame

Build the reusable rack skeleton.

- [x] Four vertical structural posts.
- [x] Top and bottom frame members.
- [x] Front and rear 19-inch mounting posts.
- [ ] Inner cabinet skeleton / support frame for doors, panels, and the mounting-post core.
- [ ] Door and side-panel mounting edges on the cabinet skeleton.
- [ ] Cross members or adjustable brackets that attach the mounting posts to the outer rack frame.
- [ ] Basic bevels on major frame members.

Do not model every stamped hole, screw, or bracket variant yet. The frame should first prove scale, proportions, mounting logic, and where the door, panels, and 19-inch mounting-post core attach.

## Phase 03: Equipment Fit

Populate the rack with proxy/detail assets at the correct scale.

- [x] 10x RM44 server nodes in 4U slots.
- [x] 1x QM9700 leaf switch placeholder in the top 1U slot.
- [ ] QM9700 medium-detail rack model.
- [x] Sliding rail base assemblies for each server.
- [x] Reusable rail latch final detail.
- [ ] Procedural U-number markings on front mounting rails.
- [ ] Minimal rack screws or cage-nut hints only where visible.

Acceptance check:

```text
The 42U layout matches the hardware specification, U-space labels match the internal mounting datum, and the server/switch stack looks mechanically mountable.
```

## Phase 04: Cold Plenum Containment System

This is the most important rack-specific airflow block.

Model the forced-flow containment as a system, not as isolated decorative panels.

- [ ] Glass front door.
- [ ] Door gasket / sealing lip around the front door.
- [ ] Front cold plenum between the glass door and server/switch intake faces.
- [ ] Primary partition / baffle panels separating the cold plenum from bypass paths.
- [ ] Side sealing strips along rack posts.
- [ ] Server-face perimeter sealing around intake faces.
- [ ] Blanking / sealing strips around gaps where air could bypass server intakes.
- [ ] Bottom 1U intake guide tied into the cold plenum.

Purpose:

```text
Cold air from the raised-floor fan tile must be forced into the front cold plenum and then through the server and switch intake faces, not around them.
```

## Phase 05: Bottom 1U Intake Plenum

Model the bottom rack interface as a passive air guide and pressure box.

- [x] Bottom 1U plenum / air guide box blockout.
- [x] 42U rail/server core lifted by approximately 85 mm inside the 2000 mm outer cabinet envelope.
- [ ] Structural base plinth below the 42U mounting envelope.
- [ ] Base pressure box using the lower cabinet margin, not only the visible 1U slot.
- [ ] Clear boundary between the base pressure box and U1 intake guide.
- [ ] Intake opening aligned to the raised-floor fan tile below.
- [ ] Internal deflector surface that turns vertical supply airflow upward along the glass door.
- [ ] Wide outlet into the front cold plenum to avoid a narrow high-velocity nozzle.
- [ ] Sealed side edges so the bottom intake does not leak directly into the rear hot/cable zone.

Constraint:

```text
No active fan module lives inside this rack space. The active fan is part of the raised-floor tile system.

The visible bottom 1U is the rack U-space airflow interface. The larger lower cabinet margin acts as a structural base plinth / pressure box so the JetPanel supply is not forced through a narrow slot.

U1 remains part of the 42U mounting envelope. The lower pressure-box volume below it is part of the cabinet base, not an extra rack unit.
```

## Phase 06: Raised-Floor Fragment

Even the first single-rack prototype needs a floor fragment so the bottom airflow source is understandable.

- [ ] 600 x 600 mm raised-floor tile grid.
- [ ] JetPanel-style active fan tile under the rack cold-side footprint.
- [ ] Solid steel floor tiles around the rack.
- [ ] Optional perforated ventilation tile nearby for context.
- [ ] Pedestals at grid intersections.
- [ ] C-profile / stringer support grid.
- [ ] Short underfloor plenum volume or cutaway.
- [ ] Rack feet / levelling feet / floor contact points.

Acceptance check:

```text
The viewer can understand why cold air enters the rack from below.
```

## Phase 07: Rear Hot / Cable Zone

Build the rear side as a serviceable hot-air and cabling volume.

- [ ] Rear hot/cable clearance behind the servers and QM9700 exhausts.
- [ ] Rear frame / service posts.
- [ ] Clear exhaust paths from server and QM9700 outlets into the rear hot/cable clearance.
- [ ] Sealed rear access panel forming the rear boundary of the hot/cable zone.
- [ ] Rear service-access clearance reserved for the sealed rear access panel.

Do not model the rear hot/cable clearance as a separate solid object. It is the space preserved between the equipment exhausts and the sealed rear access panel.

Acceptance check:

```text
The rear side preserves readable hot/cable clearance behind the equipment and routes hot air toward the upper rear/top return hood, while the sealed rear access panel still reads as removable service access to rear cabling.
```

## Phase 08: Power System

Model the rack-level power distribution called out in the hardware specification.

- [ ] 2x rear vertical 0U PDU strips.
- [ ] C19 outlet pattern on each PDU.
- [ ] Alternating server power allocation:
  - [ ] Odd nodes to Feed A / left PDU.
  - [ ] Even nodes to Feed B / right PDU.
- [ ] QM9700 PSU 1 to Feed A and PSU 2 to Feed B.
- [ ] Thick three-phase power cables exiting upward from the PDUs.
- [ ] Short overhead power tray segment above the rack.

Purpose:

```text
The rear view should show that rack power is deliberate, balanced, and routed out of the rack envelope.
```

## Phase 09: Network Cabling

Model the rear OSFP / InfiniBand story as a visible engineering feature.

- [ ] QM9700 OSFP connector side in the rear hot/cable zone.
- [ ] 10 downlinks from the leaf switch to the server NICs.
- [ ] Uplinks from the leaf switch toward the overhead network tray.
- [ ] Rear top OSFP cable throat behind the QM9700.
- [ ] Bend-radius clearance for the uplink bundle before it enters the overhead network tray.
- [ ] Cable radius guides near the switch and rear posts.
- [ ] Cable combs / cable fingers for organised routing.
- [ ] Separate network tray from power tray.
- [ ] Cable bundle density that reads at rack scale.

Do not model every cable with full manual precision. Prioritise bend radius, routing logic, bundle density, and separation from power.

The top rear area should be treated as a dense OSFP cable exit zone, not as spare service space. The hot-air capture geometry must leave this cable throat readable and physically plausible.

## Phase 10: Removable Panels and Doors

Add the serviceable outer enclosure.

- [ ] Two removable side panels.
- [ ] Sealed rear access panel.
- [ ] Top panel.
- [ ] Top panel boundary compatible with the Phase 11 rear/top return hood.
- [ ] Simple handles and locks.
- [ ] Grounding / bonding straps on door and removable panels.
- [ ] Panel seams and captive-fastener pattern.

Keep door hardware simpler than the airflow sealing and serviceability features.

## Phase 11: Top Return / Hot-Air Capture

Only model this after the rear hot/cable zone is blocked.

- [ ] Rear/top hot-air capture interface.
- [ ] Capture opening split across the upper rear panel and rear portion of the top panel.
- [ ] Sloped rear/top return hood, not a direct vertical chimney through the top panel.
- [ ] Short transition piece over or behind the rear hot zone.
- [ ] Clearance between the sloped hood and the OSFP cable throat.
- [ ] Connection logic toward hot aisle or overhead return path.

Constraint:

```text
Do not add a top exhaust turbine unless the architecture changes. Heat leaves through equipment airflow into the rear hot/cable zone and then into the room return path.

Do not route the hot-air hood through the same physical space needed by the QM9700 rear OSFP cable bundle. Use a rear/top sloped capture shape so cable management and hot-air return can coexist.
```

## Phase 12: Detail Pass

Promote small details only after the full rack reads correctly.

- [x] Final rail latch detail.
- [ ] Refined visible captive fasteners.
- [ ] Small mounting brackets.
- [ ] Refined visible panel seams.
- [ ] Labels.
- [ ] Refined U-number marking materials or typography if visible in close-up.
- [ ] Rubber sealing strips.
- [ ] Braided grounding strap.
- [ ] Cable tie points.
- [ ] Small bevel and thickness variation on panels.

Skip or defer:

- [ ] Full internal sliding-rail mechanics.
- [ ] Every screw on every panel.
- [ ] Exact geometry for every cable.
- [ ] All stamped holes that are not visible in planned views.
- [ ] Full chimney geometry before the hot-aisle / return-air layout is blocked.

## Phase 13: Material and Look Development

Assign materials after major geometry is stable.

- [ ] Painted black rack frame.
- [ ] Brushed or galvanised rail metal.
- [ ] Dark rubber gaskets and sealing strips.
- [ ] Slightly tinted glass door.
- [ ] Blue-tinted cold plenum accent only where it helps explain airflow.
- [ ] Distinct cable materials for power, OSFP / InfiniBand, and management wiring.
- [ ] Raised-floor materials:
  - [ ] Powder-coated steel panel.
  - [ ] Perforated ventilation tile.
  - [ ] JetPanel-style active tile.
  - [ ] Darker underfloor plenum.

## Phase 14: Rack Asset Boundary and LODs

Build the compute rack as one top-level assembly asset with internal component structure and three levels of detail.

The rack should follow the same component-asset pattern used for the server internals:

```text
LOD00 = hero / service close-up
LOD01 = rack-level and row-level shots
LOD02 = data-hall scale and background racks
```

Asset boundary:

- [ ] Treat the complete compute rack as a single top-level rack assembly asset.
- [ ] Keep RM44 server nodes as referenced component assets inside the rack assembly.
- [ ] Keep the QM9700 switch as a referenced component asset once the medium-detail switch model exists.
- [ ] Keep raised-floor tiles and JetPanel modules as separate floor-system assets, not baked into the rack asset.
- [ ] Keep rack-specific parts as child components inside the rack asset:
  - [ ] structural frame;
  - [ ] mounting posts and rails;
  - [ ] cold plenum containment;
  - [ ] bottom 1U intake guide;
  - [ ] doors and removable panels;
  - [ ] rear PDU strips;
  - [ ] rack-local cable guides and cable bundles.

LOD targets:

- [ ] LOD00 includes full rack frame, rails, latches, sealing details, doors, panels, PDU strips, cable guides, and visible cable bundles.
- [ ] LOD01 keeps the readable rack structure, server/switch stack, door/panel silhouettes, PDU strips, and simplified cable bundles.
- [ ] LOD02 keeps the rack silhouette, front/rear orientation, server stack rhythm, glass/cold-side hint, top switch hint, and simplified rear cable mass only if visible.
- [ ] Define visibility rules for small details that disappear between LOD00 and LOD01.
- [ ] Define proxy or texture-based replacements for dense perforation, screws, latches, and cable bundles in LOD02.

Do not split every rack part into separate top-level assets. Only promote a subpart to a separate asset when it is reused independently across racks, rack types, or floor systems.

## Phase 15: Proceduralisation

Convert the rack into a reusable asset system.

- [ ] Rack frame as reusable base asset.
- [ ] Server slot instancing.
- [ ] Rail and latch instancing.
- [ ] PDU outlet pattern generation.
- [ ] Cable bundle generation.
- [ ] Raised-floor tile scatter from a 600 x 600 mm grid mask.
- [ ] JetPanel placement under compute racks.
- [ ] Variants:
  - [ ] Compute rack.
  - [ ] Central network rack.
  - [ ] Open service view.
  - [ ] Hero exterior view.

## Priority Summary

Critical path:

```text
rack frame
-> U-space equipment fit
-> cold plenum containment
-> bottom 1U intake
-> raised-floor fragment
-> rear PDU and cable zone
```

Second pass:

```text
removable panels
-> doors and gaskets
-> overhead power/network exits
-> rear/top sloped hot-air capture
-> reusable detail kit
```

Defer until visible:

```text
deep sliding-rail mechanics
-> dense screw detail
-> exact individual cable geometry
-> full return duct beyond the rack hood
-> panel micro-stamping
```
