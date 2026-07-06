# Case 03 Technical Debt

## 1. Unresolved Technical Debt

No open technical debt items are tracked here at this moment.

## 2. Resolved Technical Debt

### [DOCS] Reconcile USD Architecture Docs with Current BMS Direction

- **Status:** Resolved
- **Severity:** Medium (Documentation / Architecture Drift)
- **Description:**
  - ADR007 and `docs/knowledge_base/usd_architecture/` previously described
    the long-term 160-node digital twin target as if it were already a strict
    current implementation contract.
  - That conflicted with the staged Blackwell Monitoring Suite plan, where
    v0.1 starts with a single configured CPU cooler asset preview before
    telemetry, full server loading, cached simulation, workload states, and
    scale navigation.
- **Action Plan:**
  - [x] Finish and accept `docs/plans/case 03 - staged runtime plan.md`.
  - [x] Review all files under `docs/knowledge_base/usd_architecture/` against
        the current asset pipeline and staged runtime direction.
  - [x] Update ADR007 so it clearly separates current accepted pipeline rules
        from long-term digital twin target architecture.
  - [x] Align LOD naming, purpose usage, payload/reference expectations,
        instancing assumptions, material-library assumptions, and telemetry
        language with the current Case 03 implementation plan.
  - [x] Preserve useful guidance, but remove or soften claims that are not yet
        true for the current staged build.
- **Closure Log (2026.07.06):**
  - Rewrote ADR007 as a current-baseline plus long-term-target architecture
    decision.
  - Updated `docs/knowledge_base/main_concept.md` around Blackwell Monitoring
    Suite, v0.1 asset preview, staged runtime growth, and explicit truth
    boundaries.
  - Updated all files under `docs/knowledge_base/usd_architecture/` so they
    distinguish current asset/runtime requirements from future-scale
    recommendations.
  - Removed stale public references to the old extension name, previous
    workload table, previous data-provider module path, and the old hard
    requirement framing around VariantSets, instancing, centralized materials,
    payloads, and telemetry primvars.

### [SECURITY] Pip 25.3 Vulnerability (CVE-2026-1703)

- **Status:** Resolved (Upstream Compatibility Released)
- **Severity:** High (Security) / Critical (Dependency Chain)
- **Description:**
  - Legacy state: `case03-env` ran `pip 25.3`, flagged by **CVE-2026-1703**.
  - Resolution: `pip-tools 7.5.3` provides compatibility with `pip 26.x`, so the lock has been removed.
- **Action Plan:**
  - [x] Keep `pip` pinned below 26.0 until compatible `pip-tools` release lands.
  - [x] Track `pip-tools` releases weekly until compatibility confirmation.
  - [x] Upgrade `pip` and `pip-tools` in `case03-env` once compatibility is confirmed.
  - [x] Rebuild dependency lockfile and run validation checks.
- **Closure Log (2026.05.21):**
  - Upgraded environment tooling to `pip 26.1.1` and `pip-tools 7.5.3`.
  - Recompiled `requirements.txt` from `requirements.in` with `pip-compile --upgrade`.
  - Validation: `pytest` passed (`1 passed`).
