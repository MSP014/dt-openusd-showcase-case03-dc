"""
Tests Heatmap runtime orchestration and lifecycle behavior.

Covers the runtime path from semantic discovery and telemetry binding through
scalar mapping and Heatmap presentation.

Verifies:

- Heatmap enable/disable and telemetry refresh behavior;
- workload changes update presentation through the existing telemetry path;
- metric or thermal-view changes remove previous Heatmap state cleanly;
- authored production asset layers are not modified;
- cleanup removes only Heatmap-owned runtime state;
- stage reload reconstructs Heatmap runtime state correctly;
- single-server X-Ray precedence is respected for dual-purpose geometry;
- Heatmap capability remains intact when presentation is suppressed by X-Ray;
- Heatmap can coexist with Stage 7 Engineering X-Ray and Stage 9 Streamlines
  without corrupting their runtime or presentation state;
- shutdown leaves no stale Heatmap presentation state.
"""
