"""
Responsible only for USD thermal contracts:

- thermal_zone
- thermal_component
- primvars:thermal_weight
- primvars:temperature_preview

Finds heatmap-capable prims, validates metadata/range/interpolation,
and returns a normal internal representation.

It doesn't know anything about telemetry or materials.
"""
