# DTRS Heatmap Contract

## Thermal metadata

Heatmap capability is catalogued from authored server-stage thermal metadata.
Each catalogued target has a semantic component, a telemetry binding, and an
authored `thermal_weight`. Capability remains catalog metadata even when a
target is temporarily excluded from the Heatmap presentation.

`thermal_weight` is an authored spatial distribution. It is not a measured
per-vertex temperature.

## Telemetry binding and scalar mapping

The semantic target resolves only to a documented canonical telemetry metric.
DTRS applies the existing telemetry Celsius value, authored calibration delta,
temperature offset, and `thermal_weight` to produce the presentation scalar.
The 2 Hz retarget cadence and 2.0-second smoothing contract are unchanged.

## Global Celsius palette

Applied settings resolve one global Celsius scale for the selected Heatmap
composition. The configured clamp range and ordered palette stops map each
component scalar to its material colour. Calibration and palette are settings
contracts; workload changes do not rewrite them.

## Heatmap and X-Ray precedence

Heatmap owns its selected targets. If a selected Heatmap target is also in a
Heatmap X-Ray overlay group, it is excluded from that temporary X-Ray binding.
Other group members remain X-Ray candidates. This is presentation precedence
only: it never changes thermal metadata or Heatmap capability.

Manual X-Ray selection is retained while Heatmap owns its temporary overlay;
ordinary X-Ray material Apply changes Fresnel values without replacing the
Heatmap exclusions or temporary owner.

## Dynamic runtime update path

Activation creates the Heatmap MDL graph, bindings, named dynamic texture, and
material-key texel indices once. At the existing 2 Hz cadence, DTRS updates
only R32 texture pixel data. It performs no periodic USD, `UsdShade` shader
input, primvar, material recreation, or binding mutation.

## Scope and non-goals

This is a telemetry-driven engineering visualization for one server. It is not
validated CFD and does not claim measured per-vertex temperature. Rack and
data-hall Heatmaps are future scope.
