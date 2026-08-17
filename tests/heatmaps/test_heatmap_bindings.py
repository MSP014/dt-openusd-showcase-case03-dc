"""
Tests semantic binding between Heatmap-capable USD regions and DTRS telemetry.

Covers:

- mapping `thermal_zone` / `thermal_component` semantics to documented
  telemetry metrics;
- repeated hardware identity, including independent GPU instances;
- unavailable bindings when no truthful telemetry source exists;
- preservation of telemetry quality and provenance;
- separation between Heatmap capability and presentation eligibility;
- single-server X-Ray precedence for dual-purpose geometry such as the GPU
  enclosure/shroud.

Bindings must never invent component temperatures merely because authored
Heatmap metadata exists on a primitive.
"""
