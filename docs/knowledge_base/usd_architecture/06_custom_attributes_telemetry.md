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

## 4. Runtime Direction

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
