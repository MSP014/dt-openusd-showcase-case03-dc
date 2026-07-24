# Case 03 Technical Debt

## 1. Unresolved Technical Debt

### [RUNTIME] Investigate Kit-CAE VTI Origin Loss and Retire Compatibility Shim

- **Status:** Open
- **Severity:** Low (Upstream Compatibility / Regression Risk)
- **Description:**
  - A VTI with a valid non-zero header origin currently imports into the
    Kit-CAE/BMS stage with `ImageDataAPI.origin=(0,0,0)`.
  - BMS restores the authoritative VTI header origin through a session-layer
    opinion before creating dataset bounding-box and Flow objects. The source
    VTI and authored USD asset remain unmodified.
- **Why Deferred:**
  - The compatibility layer is narrow, reversible, and has passed the static
    VTI-to-Flow proof. Patching the upstream importer during active Stage 6
    delivery would turn a bounded integration repair into unrelated R&D.
- **Action Plan:**
  - [ ] Build a minimal VTI-only reproducer outside BMS.
  - [ ] Determine whether origin loss occurs in the importer, USD authoring, or
        composition.
  - [ ] Check the behaviour against a newer Kit-CAE version when available.
  - [ ] Remove the BMS session-layer shim if upstream behaviour is fixed.
  - [ ] Retain a regression check that VTI header origin equals composed
        `ImageDataAPI.origin`.

### [RUNTIME] Retire the Rejected RTX/IndeX Airflow Playback Route

- **Status:** Deferred until the replacement airflow route is accepted
- **Severity:** Low (Runtime Cleanup / Scope Control)
- **Description:**
  - Stage 6 established that direct `OpenVDBAsset` playback through RTX/NVIDIA
    IndeX is not viable for the interactive BMS target. The final fast-path
    test remained near 2-3 FPS, while the same BMS scene without airflow holds
    67-69 FPS.
  - The current BMS app still contains the IndeX dependency, VDB cache
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
  - [ ] Remove `omni.rtx.index_composite` from the BMS app dependencies.
  - [ ] Remove the direct VDB cache config, UI controls, controller code, and
        focused tests.
  - [ ] Retain the measured result in the Stage 6 plan and keep the offline
        Houdini density VDB evidence intact.

### [RUNTIME] Backfill UI Control Contract Tests for Existing BMS Controls

- **Status:** Open
- **Severity:** Medium (Test Coverage / UI Regression Risk)
- **Description:**
  - New stateful BMS UI controls should be covered by focused behavioural tests
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
  - [ ] Inventory existing BMS interactive controls by side effect.
  - [ ] Add behavioural contract tests for asset load controls.
  - [ ] Add behavioural contract tests for lighting controls.
  - [ ] Add behavioural contract tests for grid and camera controls.
  - [ ] Add behavioural contract tests for airflow cache controls.
  - [ ] Add behavioural contract tests for telemetry workload, refresh, and
        freeze controls.
  - [ ] Keep visual-only Kit checks separate from fast unit tests.

### [RUNTIME] Backfill Unit Tests for Existing BMS Runtime Modules

- **Status:** Open
- **Severity:** Medium (Test Coverage / Runtime Stability)
- **Description:**
  - Stage 1 and Stage 2 established the first working BMS runtime surface:
    configured asset loading, review lighting, HDRI visibility, grid controls,
    camera persistence, local override config, and docked OmniUI controls.
  - Those modules were validated manually in Kit, but they do not yet have the
    same style of focused unit-test coverage now planned for the Stage 3
    telemetry provider.
  - This creates regression risk as the sidebar, telemetry provider, runtime
    state, and future scene behaviours start sharing the same app surface.
- **Context:**
  - Stage 3 should add tests for the new synthetic data provider immediately.
  - Backfilling tests for older BMS runtime modules is useful, but doing all of
    it inside Stage 3 would expand the slice beyond synthetic telemetry.
- **Why Deferred:**
  - The immediate Stage 3 delivery should stay focused on the telemetry provider
    boundary and Telemetry tab.
  - Existing BMS features need careful test seams because some behaviours depend
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
  - Blackwell Monitoring Suite intentionally starts Stage 3 with a synthetic
    telemetry provider. This proves that telemetry values update inside the Kit
    runtime without depending on Houdini playback or a real data centre.
  - The broader product concept still includes a future provider boundary where
    a real monitoring feed can replace the synthetic generator. Possible
    sources include HWiNFO-like local sensors, NVIDIA/NVML, Redfish, IPMI,
    PMBus, smart PDUs, UPS or branch-circuit monitors, Grafana, MQTT, Kafka, or
    another monitoring system.
  - This is technical debt because the provider contract should exist before
    Stage 3 hardcodes UI assumptions, but implementing real adapters now would
    expand scope into hardware access, credentials, polling cadence, stale data,
    source-specific naming, unit normalisation, topology mapping, and measured
    versus estimated value semantics.
- **Context:**
  - The active Stage 3 scope remains the first-layer node telemetry subset
    documented in `docs/knowledge_base/bms_telemetry_contract.md`.
  - The future live-provider superset is documented now so the synthetic
    provider, UI, and data model do not paint BMS into a toy-only corner.
  - The current Case 03 node uses a consumer/workstation PSU, so PSU contribution
    is represented as `psu_load_estimate_w` in Stage 3. Server-class PSU
    measurements such as input/output power, status, temperature, or PSU fan RPM
    are valid only when future hardware or external monitoring feeds actually
    provide them.
- **Why Deferred:**
  - Stage 3 only needs changing synthetic values visible in BMS.
  - Real provider adapters require access to actual monitoring systems and a
    security/credential boundary that does not exist in the current local Kit
    slice.
  - Deferring implementation protects the roadmap while preserving a clear
    architecture path for future live-mode work.
- **Action Plan:**
  - [x] Document the Stage 3 synthetic subset and future live-provider superset.
  - [ ] Keep Stage 3 implementation behind a provider boundary.
  - [ ] Add source, unit, timestamp, topology, and data-quality semantics to the
        runtime telemetry model.
  - [ ] Add live provider adapters only when a real source and validation path
        are selected.
  - [ ] Ensure live adapters degrade safely when sensors are missing, stale, or
        estimated.

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
