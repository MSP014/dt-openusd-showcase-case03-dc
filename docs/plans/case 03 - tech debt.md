# Case 03 Technical Debt

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

## [SECURITY] Pip 25.3 Vulnerability (CVE-2026-1703)

- **Status:** Mitigation Enforced (Upstream Lock)
- **Severity:** High (Security) / Critical (Dependency Chain)
- **Description:**
  - `case03-env` is running `pip 25.3`, which is flagged for **CVE-2026-1703**.
  - **Constraint:** We CANNOT upgrade to `pip 26.0+` because it breaks `pip-tools` (current version).
- **Action Plan:**
  - [x] **DO NOT UPGRADE PIP** until `pip-tools` releases a compatible fix (ETA Late Feb 2026).
  - [ ] Weekly check for `pip-tools` updates.
  - [ ] Once fixed, upgrade `pip` and `pip-tools` simultaneously.
