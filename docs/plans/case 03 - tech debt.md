# Case 03 Technical Debt

## 1. Unresolved Technical Debt

### [TOOLING] Evaluate NVIDIA Agent Skills for Case 03 Development

- **Status:** Deferred
- **Severity:** Low (Developer Workflow / Optional Capability)
- **Description:**
  - The project currently uses local NVIDIA USD Code, Kit, and OmniUI MCP
    servers through the repository helpers under `tools/mcp/`.
  - The official [NVIDIA Agent Skills](https://github.com/NVIDIA/skills)
    catalog is a separate capability layer and has not been evaluated or
    integrated into the Case 03 development workflow.
  - The currently relevant candidates appear to be
    `omniverse-usd-performance-tuning`, `omniverse-realtime-viewer`, and,
    conditionally, `omniverse-cad-to-simready`.
- **Why Deferred:**
  - Active DTRS runtime milestones are the current priority, and the existing
    MCP-backed workflow already covers active USD, Kit, and OmniUI development
    needs.
  - Installing skills without reviewing their triggers, workflow assumptions,
    overlap, and maintenance model could create ambiguous guidance without
    adding immediate project value.
- **Action Plan:**
  - [ ] Read the candidate `SKILL.md`, skill card, benchmark, references, and
        declared boundaries.
  - [ ] Compare each candidate with the existing MCP helper workflow and
        current Case 03 project conventions.
  - [ ] Select only skills that add a distinct, relevant capability; do not
        install the entire NVIDIA catalog by default.
  - [ ] Define routing and ownership where an official skill overlaps USD,
        Kit, OmniUI, performance, or asset-preparation guidance.
  - [ ] Install selected skills for the intended agent scope and validate them
        on a bounded Case 03 task.
  - [ ] Document the chosen update, provenance, and signature-verification
        process without making Agent Skills a DTRS runtime dependency.

### [RUNTIME] Investigate Kit-CAE VTI Origin Loss and Retire Compatibility Shim

- **Status:** Open
- **Severity:** Low (Upstream Compatibility / Regression Risk)
- **Description:**
  - A VTI with a valid non-zero header origin currently imports into the
    Kit-CAE/DTRS stage with `ImageDataAPI.origin=(0,0,0)`.
  - DTRS restores the authoritative VTI header origin through a session-layer
    opinion before creating dataset bounding-box and Flow objects. The source
    VTI and authored USD asset remain unmodified.
- **Why Deferred:**
  - The compatibility layer is narrow, reversible, and has passed the static
    VTI-to-Flow proof. Patching the upstream importer during active Stage 6
    delivery would turn a bounded integration repair into unrelated R&D.
- **Action Plan:**
  - [ ] Build a minimal VTI-only reproducer outside DTRS.
  - [ ] Determine whether origin loss occurs in the importer, USD authoring, or
        composition.
  - [ ] Check the behaviour against a newer Kit-CAE version when available.
  - [ ] Remove the DTRS session-layer shim if upstream behaviour is fixed.
  - [ ] Retain a regression check that VTI header origin equals composed
        `ImageDataAPI.origin`.

### [RUNTIME] Retire the Rejected RTX/IndeX Airflow Playback Route

- **Status:** Deferred until the replacement airflow route is accepted
- **Severity:** Low (Runtime Cleanup / Scope Control)
- **Description:**
  - Stage 6 established that direct `OpenVDBAsset` playback through RTX/NVIDIA
    IndeX is not viable for the interactive DTRS target. The final fast-path
    test remained near 2-3 FPS, while the same DTRS scene without airflow holds
    67-69 FPS.
  - The current DTRS app still contains the IndeX dependency, VDB cache
    configuration, cache controls, and session-layer authoring code so the
    failed route remains reproducible while the Flow or hybrid replacement is
    being proven.
- **Why Deferred:**
  - Removing the route before a replacement passes would erase a useful
    comparison point and add cleanup churn during the active Stage 6 spike.
  - The Houdini density VDB remains valid offline cinematic evidence and is not
    part of this cleanup.
- **Action Plan:**
  - [ ] Accept a replacement interactive airflow route.
  - [ ] Remove `omni.rtx.index_composite` from the DTRS app dependencies.
  - [ ] Remove the direct VDB cache config, UI controls, controller code, and
        focused tests.
  - [ ] Retain the measured result in the Stage 6 plan and keep the offline
        Houdini density VDB evidence intact.

### [RUNTIME] Further Decompose Flow Lifecycle Orchestration

- **Status:** Closed (2026-07-27)
- **Severity:** Low (Navigation / Maintenance Cost)
- **Resolution:**
  - `app/flow/runtime.py` was reduced from 3,243 to approximately 1,360 lines.
  - Temporal proof/authoring, performance sampling, and deep Kit-CAE
    diagnostics now live in `temporal.py`, `performance.py`, and
    `diagnostics.py` mixin owners respectively.
  - `RuntimeController` remains the stable command facade; Attach/Detach,
    re-attach safety, and existing focused tests retain their contracts.

### [RUNTIME] Backfill UI Control Contract Tests for Existing DTRS Controls

- **Status:** Open
- **Severity:** Medium (Test Coverage / UI Regression Risk)
- **Description:**
  - New stateful DTRS UI controls should be covered by focused behavioural tests
    before manual Kit validation is treated as sufficient.
  - The expected contract is one happy-path test plus representative edge cases
    for controls that change application state, trigger runtime commands,
    persist configuration, or author USD/session-layer opinions.
  - The Stage 17 View tab server enclosure controls now follow this pattern,
    but older controls were introduced before the rule existed.
- **Context:**
  - Fast unit tests should cover pure-Python seams such as UI model state
    extraction, command payload construction, config merge behaviour, and USD
    session-layer authoring helpers.
  - Manual Kit checks should remain focused on visual polish, docking, viewport
    framing, renderer behaviour, and interaction feel.
- **Why Deferred:**
  - Backfilling every existing OmniUI control during the current screenshot
    polish slice would expand scope beyond the server-view controls.
  - Some controls need small test seams before they can be covered without
    launching Kit.
- **Action Plan:**
  - [ ] Inventory existing DTRS interactive controls by side effect.
  - [ ] Add behavioural contract tests for asset load controls.
  - [ ] Add behavioural contract tests for lighting controls.
  - [ ] Add behavioural contract tests for grid and camera controls.
  - [ ] Add behavioural contract tests for airflow cache controls.
  - [ ] Add behavioural contract tests for telemetry workload, refresh, and
        freeze controls.
  - [ ] Keep visual-only Kit checks separate from fast unit tests.

### [RUNTIME] Backfill Unit Tests for Existing DTRS Runtime Modules

- **Status:** Open
- **Severity:** Medium (Test Coverage / Runtime Stability)
- **Description:**
  - Stage 1 and Stage 2 established the first working DTRS runtime surface:
    configured asset loading, review lighting, HDRI visibility, grid controls,
    camera persistence, local override config, and docked OmniUI controls.
  - Those modules were validated manually in Kit, but they do not yet have the
    same style of focused unit-test coverage now planned for the Stage 3
    telemetry provider.
  - This creates regression risk as the sidebar, telemetry provider, runtime
    state, and future scene behaviours start sharing the same app surface.
- **Context:**
  - Stage 3 should add tests for the new synthetic data provider immediately.
  - Backfilling tests for older DTRS runtime modules is useful, but doing all of
    it inside Stage 3 would expand the slice beyond synthetic telemetry.
- **Why Deferred:**
  - The immediate Stage 3 delivery should stay focused on the telemetry provider
    boundary and Telemetry tab.
  - Existing DTRS features need careful test seams because some behaviours depend
    on Kit, USD stage state, local config files, or manual viewport interaction.
- **Action Plan:**
  - [ ] Identify testable pure-Python seams in `RuntimeConfig` and
        `RuntimeController`.
  - [ ] Add focused tests for local override merge/persistence behaviour.
  - [ ] Add tests for lighting, grid, and camera config serialisation helpers.
  - [ ] Add tests for missing asset/HDRI/config error handling where it can be
        exercised without launching Kit.
  - [ ] Keep Kit/viewport integration checks separate from fast unit tests.

### [RUNTIME] Live Monitoring Feed Provider Integration

- **Status:** Open
- **Severity:** Medium (Architecture / Integration)
- **Description:**
  - Case 03 intentionally ships with `SyntheticTelemetryProvider`. It is a
    valid demonstration and simulation source, not a temporary stub to remove.
  - `TelemetrySnapshot` defines the normalised telemetry model, but the runtime
    currently constructs the synthetic provider directly. A common provider
    interface, source adapters, provider factory, and production connectors are
    not implemented.
- **Context:**
  - The active Stage 3 scope remains the first-layer node telemetry subset
    documented in `docs/knowledge_base/dtrs_telemetry_contract.md`.
  - The current Case 03 node uses a consumer/workstation PSU, so PSU contribution
    is represented as `psu_load_estimate_w` in Stage 3. Server-class PSU
    measurements such as input/output power, status, temperature, or PSU fan RPM
    are valid only when future hardware or external monitoring feeds actually
    provide them.
- **Why Deferred:**
  - Full production adapters for Grafana, Prometheus, Kafka, MQTT, and similar
    systems are not required for the Case 03 PoC. They introduce credentials,
    authentication, polling versus streaming, reconnects, network topology,
    source schemas, security, retry/backoff, and vendor-specific APIs.
  - A single substitution proof is more valuable here than several incomplete
    vendor integrations.
- **Future Implementation Plan:**
  - [ ] Define an explicit provider interface or `Protocol` that returns the
        same normalised `TelemetrySnapshot`. DTRS consumers must not know the
        source of the data.
  - [ ] Keep `SyntheticTelemetryProvider` as one complete implementation of
        that contract for autonomous Case 03 demonstration and simulation.
  - [ ] Add one minimal reference external provider, such as
        `JsonTelemetryProvider` or `RecordedTelemetryProvider`, using a JSON
        fixture or replay stream. It must map external telemetry into
        `TelemetrySnapshot` and leave the visualisation layer unchanged.
  - [ ] Select the provider through configuration and a factory, rather than
        hard-wiring `SyntheticTelemetryProvider(...)` in the extension.
  - [ ] Make source adapters responsible for source metric-name mapping to DTRS
        metric IDs, unit normalisation, receive and source timestamps, topology
        mapping, missing or malformed data, stale data, and quality semantics:
        `measured`, `estimated`, `derived`, `synthetic`, `stale`, `unavailable`.
        Source-specific naming must not leak into UI or visualisation code.
  - [ ] Add contract tests proving `SyntheticTelemetryProvider` and the
        reference provider both return `TelemetrySnapshot`, and that the same
        DTRS consumer works with both.

## 2. Resolved Technical Debt

### [DEPENDENCY] Removed `omni.cae.testing` Runtime Dependency

- **Status:** Resolved
- **Severity:** Low (Runtime Dependency / Packaging)
- **Resolution:**
  - Streamlines diagnostic pruning removed the isolated reproducer and shipping
    `.kit` dependency on `omni.cae.testing`.
  - Repository tracing found no remaining runtime owner.
  - User-run clean DTRS startup reached `app ready` and `RTX ready` without
    loading `omni.cae.testing`; DTRS, Flow, Smoke, and X-Ray startup remained
    available.

### [DOCS] Reconcile USD Architecture Docs with Current DTRS Direction

- **Status:** Resolved
- **Severity:** Medium (Documentation / Architecture Drift)
- **Description:**
  - ADR007 and `docs/knowledge_base/usd_architecture/` previously described
    the long-term 160-node digital twin target as if it were already a strict
    current implementation contract.
  - That conflicted with the staged Digital Twin Runtime Suite plan, where
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
  - Updated `docs/knowledge_base/main_concept.md` around Digital Twin Runtime Suite, v0.1 asset preview, staged runtime growth, and explicit truth
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
