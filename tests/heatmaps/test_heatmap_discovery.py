"""
Tests Heatmap discovery and validation against the authored USD thermal contract.

Covers discovery of Heatmap-capable primitives through:

- `thermal_zone`;
- `thermal_component`;
- `primvars:thermal_weight`;
- optional `primvars:temperature_preview`.

Verifies that:

- thermal semantics are discovered from authored metadata rather than from
  hard-coded mesh paths where semantic discovery is sufficient;
- `thermal_weight` follows the expected `[0, 1]` contract;
- supported USD interpolation semantics are accepted;
- missing or malformed thermal metadata is reported deterministically;
- `temperature_preview` remains optional authoring/debug data and is not
  required for Heatmap runtime capability;
- repeated hardware primitives retain deterministic identity.
"""
