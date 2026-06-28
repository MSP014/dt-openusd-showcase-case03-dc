# Rack Airflow Budget

This note documents the airflow estimation logic for **Case 03: Forced-Flow Inference Refinery**.

The goal is not CFD-grade physical accuracy. The goal is a physically informed airflow budget that can guide Houdini visual airflow simulation, Omniverse HUD telemetry, rack geometry decisions, and README-level engineering explanation.

The current approach separates two layers:

```text
Houdini simulation layer  = normalised visual airflow
Omniverse telemetry layer = estimated physical airflow values
```

This keeps the visual simulation readable while exposing engineering-style airflow numbers in the final digital twin interface.

## Unit Conversions

```text
1 CFM  = 0.000471947 m3/s
1 m3/h = 0.5886 CFM
```

Useful examples:

```text
1600 CFM  ~= 0.755 m3/s
1800 CFM  ~= 0.850 m3/s

2700 m3/h ~= 1590 CFM
4000 m3/h ~= 2350 CFM
```

## Visual Simulation Baseline

The first Houdini airflow prototype used a normalised through-flow velocity of:

```text
v = 0.16 m/s
```

Approximate RM44 frontal area:

```text
A_server ~= 0.43 m x 0.178 m
A_server ~= 0.0765 m2
```

Volumetric flow through one server at this velocity:

```text
Q_server = v x A
Q_server = 0.16 x 0.0765
Q_server ~= 0.0122 m3/s
Q_server ~= 26 CFM
```

For 10 servers:

```text
10 x 26 CFM ~= 260 CFM
```

Adding a rough 1U switch through-flow gives:

```text
visual baseline rack airflow ~= 265 CFM
```

This value is useful as a **visual Houdini baseline**, but it is too low for a physically plausible high-density AI rack.

## Heat-Based Reality Check

Simplified heat removal estimate:

```text
Power = rho x Cp x Q x deltaT
```

Where:

```text
rho    ~= 1.2 kg/m3
Cp     ~= 1005 J/(kg*K)
Q      = airflow in m3/s
deltaT = air temperature rise in deg C
```

At 265 CFM:

```text
Q ~= 0.125 m3/s
```

For a 12 kW rack:

```text
deltaT = 12000 / (1.2 x 1005 x 0.125)
deltaT ~= 80 deg C
```

This is not acceptable for sustained rack operation. Therefore, 265 CFM is treated as a **visual flow prototype**, not as final physical rack airflow.

## Per-Node Fan-Assisted Airflow

Each RM44 node contains several airflow contributors. They should not be blindly added together because some fans operate in parallel while others operate in series.

### Front Intake: 3x ARCTIC BioniX P120

Manufacturer maximum airflow per fan:

```text
1x BioniX P120 = 67.56 CFM
```

Assumed operating level:

```text
fan state = 75%
```

Estimated intake capacity:

```text
1x P120 at 75% = 67.56 x 0.75
1x P120 at 75% ~= 50.7 CFM

3x P120 at 75% ~= 152 CFM
```

This is the main active intake capacity of one RM44 node.

### Rear Exhaust: 2x ARCTIC P8 Max

Manufacturer maximum airflow per fan:

```text
1x P8 Max = 40 CFM
```

At 75%:

```text
1x P8 Max at 75% = 30 CFM
2x P8 Max at 75% = 60 CFM
```

The P8 Max fans are treated as rear exhaust helpers. They do not define the entire chassis airflow by themselves, but they reduce back-pressure and support front-to-back movement.

### CPU Cooler: Noctua NH-D9 TR5-SP6 4U

The Noctua NH-D9 uses two NF-A9 HS-PWM fans in push/pull configuration through the CPU heatsink.

Push/pull fans in series do not double airflow. They increase pressure and help push air through the heatsink.

Working estimate:

```text
CPU cooler branch ~= 40-50 CFM effective flow
```

In Houdini, this is represented as a local axial velocity helper field between the middle front P120 and the rear P8 exhaust zone.

### GPU Blower Branches

Each RTX PRO 4500 GPU is treated as a local blower/exhaust branch. No reliable public CFM value is assumed for the GPU turbine; GPU airflow is estimated from heat load.

Approximate GPU heat load:

```text
RTX PRO 4500 ~= 200 W
```

Estimated airflow per GPU depending on allowed air temperature rise:

```text
deltaT 20 deg C -> ~17.6 CFM per GPU
deltaT 25 deg C -> ~14.1 CFM per GPU
deltaT 30 deg C -> ~11.7 CFM per GPU
```

Working range:

```text
1 GPU blower branch   ~= 12-18 CFM
3 GPU blower branches ~= 35-55 CFM
```

### PSU Branch

The PSU fan is treated as a separate airflow branch. It does not dominate the chassis flow, but it removes PSU waste heat through its own local path.

Estimated PSU waste heat:

```text
80-100 W
```

Working airflow range:

```text
PSU branch ~= 7-15 CFM
```

## Effective Airflow per RM44 Node

Correct interpretation:

```text
Front P120 fans = main intake capacity
Rear P8 fans    = exhaust support
Noctua cooler   = central pressure / velocity booster
GPU blowers     = local exhaust branches
PSU fan         = local PSU branch
```

Working estimate for one RM44:

```text
Conservative node airflow: 130-150 CFM
Working node airflow:      ~160 CFM
Optimistic node airflow:   180-190 CFM
```

Recommended working value:

```text
effective_node_airflow = 160 CFM
```

For 10 nodes:

```text
10 x 160 CFM = 1600 CFM
```

## NVIDIA Quantum-2 QM9700 Switch

The top-of-rack switch is treated as a 1U airflow-through device.

Known physical data:

```text
Height: 1U / 43.6 mm
Width:  438 mm
Depth:  660.4 mm
```

The QM9700 can be configured with different airflow directions:

```text
P2C = power-to-connector airflow
C2P = connector-to-power airflow
```

For compute racks, the preferred orientation is:

```text
front/cold side = power/intake side
rear/hot side   = OSFP connector side
airflow         = front -> rear
```

This keeps OSFP cabling in the rear hot/cable zone while keeping the front cold plenum visually clean.

Estimated switch airflow contribution:

```text
QM9700 airflow estimate ~= 100-180 CFM
```

## Rack-Level Airflow Demand

Using the working node airflow estimate:

```text
10 nodes x 160 CFM = 1600 CFM
QM9700 estimate    = 100-180 CFM
```

Working rack airflow estimate:

```text
rack airflow demand ~= 1700-1800 CFM
```

This is the useful working range for the Omniverse HUD and engineering telemetry layer.

## JetPanel-Style Active Raised-Floor Tile

The preferred supply concept is an active raised-floor fan tile in the same reference class as the Weiss JetPanel.

Reference specifications:

```text
Panel size:       600 x 600 mm
Thickness:        250 mm without panel
Free surface:     39%
Standard airflow: 2700 m3/h
XL airflow:       4000 m3/h
```

Converted airflow:

```text
2700 m3/h ~= 1590 CFM
4000 m3/h ~= 2350 CFM
```

Comparison against estimated rack demand:

```text
Rack demand:       ~1700-1800 CFM
JetPanel standard: ~1590 CFM
JetPanel XL:       ~2350 CFM
```

Interpretation:

```text
JetPanel standard = near lower bound
JetPanel XL       = better fit with headroom
```

This makes the JetPanel-style active tile plausible for the high-density AI rack supply concept.

Source reference: [Weiss JetPanel](https://weiss-dbs.de/en/product/jetpanel/).

## Current Cooling Architecture

Preferred concept:

```text
active raised-floor fan tile
-> sealed bottom intake plenum
-> clean front cold plenum
-> 10x RM44 mesh intakes
-> internal fan-assisted front-to-back flow
-> rear hot / cable zone
-> hot aisle / return path
```

Advantages:

```text
- easier to model
- cleaner rack geometry
- no active fan module inside the rack U-space
- stronger airflow budget
- better compatibility with a sealed front cold plenum
- cleaner rear-only OSFP cabling strategy
```

## Rack Geometry Assumptions

Current layout:

```text
Rack outer depth:      ~1000 mm
Front cold plenum:     ~200 mm
Equipment envelope:    ~700 mm
Rear service/hot zone: ~100-140 mm
```

The front zone is not a cable zone. It is a clean cold-air buffer:

```text
front plenum = air distribution zone
```

Server fronts are primarily mesh intakes. The switch is oriented so that OSFP networking cables remain in the rear zone.

## Houdini vs Omniverse Representation

The Houdini simulation prioritises readability:

```text
Houdini:
- normalised velocity fields
- readable smoke / streamline motion
- visually stable fan-helper fields
- no CFD-grade physical-accuracy claim
```

The Omniverse layer exposes estimated physical telemetry:

```text
Omniverse HUD:
- node airflow: ~160 CFM
- rack airflow demand: ~1700-1800 CFM
- JetPanel standard: ~1590 CFM
- JetPanel XL: ~2350 CFM
- fan state: 75%
- thermal state: Idle / Nominal / Surge / Critical
```

Recommended public wording:

```text
The Houdini airflow simulation uses normalised velocity fields for visual clarity. Physical airflow values are estimated separately from fan specifications, thermal load, and rack-level flow balance, then exposed in Omniverse as telemetry.
```

## Final Working Values

Recommended values for the current tech pack:

```text
Per RM44 working airflow:  ~160 CFM
10-node airflow demand:    ~1600 CFM
QM9700 switch estimate:    ~100-180 CFM
Total rack airflow demand: ~1700-1800 CFM

JetPanel standard:         ~1590 CFM, near lower bound
JetPanel XL:               ~2350 CFM, preferred airflow ceiling
```

Recommended cooling concept:

```text
Use a JetPanel-style active raised-floor tile as the main cold-air supply source.
Keep Houdini airflow visually normalised.
Show physical airflow estimates in Omniverse HUD.
```
