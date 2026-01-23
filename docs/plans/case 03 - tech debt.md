# Case 03 Technical Debt

*No critical technical debt identified during initial audit by Higgins.*

## [ADR] USD Composition Strategy

- **Status:** Deferred
- **Severity:** Low (Architectural)
- **Description:** ADR 004 (USD Composition) was skipped during initial standardization to focus on baseline stability.
- **Task:** Formalize the USD layering and referencing strategy Once the Omniverse Kit environment is fully stable.

## [PIPELINE] Asset Hydration & Bootstrap

- **Status:** Open
- **Severity:** Medium
- **Description:** Per ADR 005, a mechanism is needed to sync heavy assets into the repository structure.
- **Tasks to Resolve:**
  - Create `tools/bootstrap.py` for directory setup and asset downloading.
  - Upload initial asset packs to external storage and document links in README.
