# Guideline 06: Custom Attributes and Telemetry

Telemetry is a future Blackwell Monitoring Suite capability. It is not required
for the v0.1 CPU cooler asset preview.

## 1. Current Baseline

Current assets should have stable hierarchy and readable prim paths so future
runtime code can attach behavior or read state deliberately.

No asset is required to carry telemetry primvars until the Synthetic Telemetry,
Telemetry Driven Motion, workload preview, or scale navigation stages need
them.

## 2. Future Telemetry Schema Direction

When telemetry becomes runtime scope, use a versioned schema that can be read by
Kit Python, USD tooling, and shaders where appropriate.

Candidate fields:

- `primvars:telemetry:schemaVersion` = `"1.0"`;
- `primvars:server:id`;
- `primvars:telemetry:tempC`;
- `primvars:telemetry:powerW`;
- future fields for fan duty, airflow, workload, health, or LED behavior when
  the runtime actually consumes them.

The final schema should be documented before Stage 3 or Stage 7 depends on it.

## 3. Houdini Authoring Direction

When telemetry attributes are authored in Houdini:

- write them as USD-readable primvars or documented custom attributes;
- keep interpolation and scope explicit;
- avoid one-off Python tagging after export when the data can be generated
  procedurally during asset build;
- validate the exported data with `pxr` or Omniverse before wiring runtime UI
  to it.

If a future stage needs placeholder values at export time, author static values
only. Do not animate these attributes in Houdini for BMS runtime behaviour.

Example placeholder intent:

```c
// SOP or LOP wrangle intent: static export value, overwritten at runtime.
f@telemetry:tempC = 20.0;
```

## 4. Addressable Thermal Components

Every object that needs an independent telemetry value must have a unique USD
path. In Houdini, create stable `name` values or explicit hierarchy before
export, especially for repeated parts such as GPU dies, VRAM chips, VRMs,
capacitors, inductors, and fan blades.

When a heat-significant surface needs a visible thermal gradient, give that
surface enough topology for interpolation. A single large polygon can only show
a flat value. For later heatmap stages, chip top faces may need a small polygon
grid so centre-hot and edge-cool values can interpolate cleanly.

Aggregate telemetry values can still map to multiple visual prims. For example,
a provider may report one `gpu_01_vram_tempC` value while the runtime
distributes it across `VRAM_01`, `VRAM_02`, and similar prims with stable
per-chip offsets. Those offsets should use deterministic seeds so the visual
state does not flicker frame to frame.

## 5. Fan RPM and Visual Rotation

Fans should be exported as static, independently addressable prims with pivots
centred on their rotation axes. Blackwell Monitoring Suite can then drive
rotation from telemetry while keeping the visual motion readable.

The preferred export shape is a rotating blade or blower mesh under its own
stable parent `Xform`, with that parent origin placed on the physical rotation
axis. At runtime BMS validates the mesh topology first: high-valence hub poles
define the rotation axis, and the authored parent `Xform` is used directly only
when that axis passes close to the parent's local origin. If the authored origin
is missing or off-axis, BMS falls back to a non-destructive Session Layer pivot
stack around the topology-resolved axis. This keeps corrected Houdini exports
cheap to animate while preserving compatibility with older component assets.

True fan RPM is data, not necessarily the displayed angular speed. At 30 or 60
FPS, physically accurate RPM can create strobing, stationary-looking blades, or
backwards apparent motion. The runtime may clamp or remap RPM to a pleasing
visual speed, add phase offsets between repeated fans, or use motion blur while
still preserving the real telemetry value for UI and state logic.

## 6. Runtime Direction

Blackwell Monitoring Suite should treat telemetry as runtime data, not as a DCC
timeline.

The first telemetry target is simple:

- generate values while the app is running;
- display or log those values in the UI;
- then drive CPU cooler fan motion from those values.

Only later stages should map telemetry to heatmaps, LEDs, cached simulation
states, or data hall scale.

## Definition of Done

- v0.1 does not require telemetry attributes.
- Before telemetry UI ships, the schema is documented and inspectable.
- Runtime code reads telemetry through a clear data provider boundary rather
  than hardcoded UI callbacks.
