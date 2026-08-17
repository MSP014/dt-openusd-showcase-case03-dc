"""
Pure math:

telemetry value
+ scalar range
+ thermal_weight
-> normalized display value

Also includes:

normalization;
clamping;
missing/stale handling;
fixed ranges;
no per-workload remap.

This should remain a dependency-light module that can be tested easily
without Kit.
"""
