"""
Tests dependency-light Heatmap scalar mapping.

Covers conversion of runtime telemetry and authored `thermal_weight` into the
normalized scalar used for Heatmap presentation.

Verifies:

- fixed documented scalar ranges;
- normalization and clamping;
- stable mapping across workload states;
- `thermal_weight` remains a dimensionless `[0, 1]` spatial distribution and
  is never interpreted as temperature;
- `temperature_preview` does not participate in runtime scalar calculation;
- telemetry quality, stale state, and unavailable data are handled
  deterministically;
- missing data does not produce fabricated or stale valid-looking Heatmap
  values.

The scalar layer contains presentation mapping only and must not imply that
each surface point represents a measured temperature in degrees Celsius.
"""
