# Case 03 Technical Debt

## [SECURITY] Pip 25.3 Vulnerability (CVE-2026-1703)

- **Status:** Mitigation Enforced (Upstream Lock)
- **Severity:** High (Security) / Critical (Dependency Chain)
- **Description:**
  - `case03-env` is running `pip 25.3`, which is flagged for **CVE-2026-1703**.
  - **Constraint:** We CANNOT upgrade to `pip 26.0+` because it breaks `pip-tools` (current version).
- **Action Plan:**
  - [x] **DO NOT UPGRADE PIP** until `pip-tools` releases a compatible fix (ETA Late March 2026).
  - [ ] **Weekly check for `pip-tools` updates** (Last Check: 2026.04.29).
    - *Rule: If the current date is more than 7 days past the Last Check date, run `pip index versions pip-tools`. If no update >= 26.0 compatibility is available, update the Last Check date here to today.*
  - [ ] Once fixed, upgrade `pip` and `pip-tools` simultaneously.
