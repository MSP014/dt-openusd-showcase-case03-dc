# Case 03 - Completed Runtime Stage Plans


**Status**: Reference
**Last Updated**: 2026-08-15

This document preserves the detailed plans used to deliver completed runtime
stages. The active roadmap and future scope remain in
[Case 03 - Staged Runtime Plan](case%2003%20-%20staged%20runtime%20plan.md).

When another runtime stage is completed, move its detailed plan here without
duplicating cross-stage contracts that still govern active or future work.

---

## Completed Stage Plans

### Stage 1 - Digital Twin Runtime Suite v0.1 Asset Preview Slice

Jira: `DC-40`

Status: implemented locally.

Build the smallest useful app surface: launch Digital Twin Runtime Suite v0.1,
show the RTX viewport, load one configured USD asset from the hydrated asset
package, and show basic load status. The first target asset is the Noctua NH-D9
TR5-SP6 CPU cooler exported at `assets/_external/usd/cpu_fan/cpu_fan.usd`.

Done when the selected asset is visible in the viewport, the load path/result is
visible in status, and the slice does not require a hidden absolute workstation
path.

Implementation notes:

- The app launches through `src/digital_twin_runtime_suite/start_dtrs.bat` or a
  direct Kit invocation with the DTRS `.kit` file.
- The runtime config is `configs/digital_twin_runtime_suite.toml`.
- The extension id is `msp.dtrs`.
- The current default asset is `usd/cpu_fan/cpu_fan.usd` under the hydrated
  external asset package.
- Runtime review camera and light helpers are created in the session layer so
  the hydrated asset is not modified.

### Stage 2 - Look Review Slice

Jira: `DC-41`

Status: implemented locally.

Add review lighting for the selected asset: a Config panel Lighting section,
default Kloofendal HDRI from the hydrated asset package, minimum
exposure/intensity controls, dome XYZ rotation, and clear lighting status.

Done when the selected asset can be viewed under the chosen lighting preset, the
operator can adjust exposure/intensity and dome rotation, and the operator can
see whether the preset loaded successfully.

Implementation notes:

- The Config panel is docked to the left side of the DTRS viewport.
- Lighting settings can be applied and saved into the local ignored runtime
  override config.
- The review key light can be enabled or disabled and has its own intensity
  control.
- The review grid can be enabled or disabled, with configurable step and line
  width.
- Camera position can be saved, restored, and reset for repeatable look review.
- HDRI background visibility can be toggled while preserving DomeLight-based
  lighting, using Kit/RTX DomeLight `visibleInPrimaryRay` visibility.
- Operator validation confirmed that the `Show HDRI` control switches the live
  DTRS viewport between visible HDRI background and hidden HDRI background while
  keeping the asset lit.

### Stage 3 - Synthetic Telemetry Slice

Jira: `DC-42`

Status: implemented locally.

Add a minimal synthetic telemetry source that runs with the application. This is
not DCC timeline playback; it is runtime data produced or received while the app
is open.

Done when changing telemetry values are visible in the app and are independent
of pressing Play in Houdini or another DCC.

Stage 3 telemetry scope:

- Implement the first-layer node telemetry subset defined in
  `docs/knowledge_base/dtrs_telemetry_contract.md`.
- Keep the future live-provider superset documented there, but do not implement
  real monitoring feed adapters in Stage 3.
- Group Stage 3 telemetry visually by operator meaning, not by raw sensor
  origin.

Stage 3 UI shell decision:

- Keep a single left-docked DTRS sidebar so the viewport is only constrained by
  one stable panel width.
- Convert the current `Config` panel content into a `Config` tab inside that
  sidebar.
- Add a sibling `Telemetry` tab for synthetic Stage 3 runtime values.
- Implement the tabs as an internal OmniUI switcher over content frames, not as
  multiple independent docked windows, unless a later UX pass deliberately
  chooses native Kit dock tabs.
- The selected tab may change, but both tabs should occupy the same sidebar
  footprint and must not cause extra viewport shrinkage.

Left sidebar tab registry:

| Order | Tab | Stage | Purpose |
| :--- | :--- | :--- | :--- |
| 1 | `Telemetry` | Stage 3 | Primary runtime monitoring surface for synthetic telemetry values. |
| 2 | `Config` | Stage 2 / Stage 3 | Operator controls for asset loading, lighting, grid, camera, and local runtime settings. |

Future DTRS modules should add their sidebar tabs to this registry before
implementation so the left-slot navigation remains deliberate as the app grows.

Stage 3 runtime snapshot model:

- Use a latest-only in-memory `TelemetrySnapshot` produced by the synthetic
  provider.
- Do not add a database, persistent telemetry store, or historical buffer in
  Stage 3.
- The telemetry UI reads the latest snapshot; future scene behaviours should
  read the same snapshot rather than duplicating generator logic.
- Each snapshot contains the current timestamp, selected operational state,
  refresh interval, and current metric values.
- Each metric value carries its unit and an explicit quality marker. Provider
  source values use `quality = synthetic`; aggregates, balances, utilisation,
  thermal headroom, and other calculated values use `quality = derived`.
  This distinction lets a future live provider replace synthetic sources
  without presenting calculations as measured sensors or forcing UI rewrites.
- Default refresh interval is 1 second. The Telemetry tab may expose a
  `1 / 5 / 10 / 30 s` refresh selector so the operator can reduce update
  frequency if needed.
- Timestamp display is part of the synthetic live-monitoring illusion, but the
  Stage 3 implementation only needs the current snapshot, not stored time
  series data.

Stage 3 data provider boundary:

- Implement the synthetic telemetry provider as a separate application module,
  not as inline UI callback logic.
- Stage 3 keeps the provider in the same Kit application process, but the module
  should be shaped so it can later move behind a process or container boundary.
- UI code should consume provider snapshots through a small provider/state API,
  not by reaching into generator internals.
- The provider should start producing data as soon as DTRS starts, before the
  operator manually loads or changes scene content.
- Containerisation, network transport, credentials, service discovery, and live
  provider adapters remain out of Stage 3 scope.

Stage 3 provider lifecycle:

- Start the synthetic telemetry provider during DTRS extension startup, not only
  after the operator loads the asset.
- Keep the provider running while the application is open so the `Telemetry`
  tab has data immediately and remains independent from asset reloads.
- Asset loading may subscribe scene behaviour to the latest provider snapshot,
  but it must not be the source of provider lifetime.
- Stop provider update tasks cleanly during extension shutdown so Kit does not
  leave orphaned async tasks, callbacks, or timers.
- Provider shutdown should be idempotent so repeated shutdown or failed startup
  paths do not raise extra errors.

Stage 3 Kit runtime guardrails:

- Do not run the telemetry provider through unmanaged `threading.Thread`
  workers, orphan timers, or callbacks that cannot be cancelled.
- Prefer a Kit-compatible async/update-loop integration with explicit stored
  task/subscription handles owned by the extension or runtime controller.
- Cancel or unsubscribe those handles during extension shutdown and tolerate
  repeated start/stop calls without raising follow-on errors.
- Keep provider configuration path resolution behind a resolver/API boundary
  instead of hardcoding paths relative to the current working directory or Kit
  install layout.
- Treat the provider's packaged base config as read-only; operator changes must
  go to a local override file, not back into the packaged default file.

Stage 3 implementation map:

| Path | Purpose |
| :--- | :--- |
| `src/digital_twin_runtime_suite/app/telemetry/__init__.py` | Public package boundary for telemetry provider code. |
| `src/digital_twin_runtime_suite/app/telemetry/model.py` | `TelemetrySnapshot`, metric value model, workload/health constants, and Stage 3 metric ids. |
| `src/digital_twin_runtime_suite/app/telemetry/config.py` | Load and merge `telemetry_provider.toml` with `telemetry_provider.local.toml`. |
| `src/digital_twin_runtime_suite/app/telemetry/provider.py` | Synthetic provider, fixed provider tick, interpolation, jitter, freeze-independent latest snapshot state. |
| `configs/telemetry_provider.toml` | Read-only base targets, ranges, jitter, default mode, and allowed refresh intervals. |
| `tests/test_telemetry_config.py` | Pure-Python tests for provider config loading, override merge, defaults, and invalid values. |
| `tests/test_telemetry_provider.py` | Pure-Python tests for provider snapshots, cadence semantics, mode changes, freeze/resume display behaviour, deterministic seeded output, and range clamping. |

Stage 3 extension integration:

- `src/digital_twin_runtime_suite/ext/msp.dtrs/msp/dtrs/extension.py`
  remains the Kit extension entry point for this slice.
- Add provider startup/shutdown ownership to `on_startup` and `on_shutdown`,
  storing task/subscription handles as explicit extension fields.
- Convert the current monolithic left panel into a shared sidebar with an
  internal `Telemetry` / `Config` tab switcher.
- Move the current asset, lighting, grid, and camera controls into a
  `_build_config_tab()` helper without changing their runtime behaviour.
- Add `_build_telemetry_tab()` for read-only latest snapshot values, workload
  mode selector, refresh interval selector, and `Freeze` / `Resume`.
- Keep UI refresh separate from provider tick: the Telemetry tab samples the
  latest snapshot at the selected UI refresh interval.
- Keep `src/digital_twin_runtime_suite/app/commands.py` focused on Kit/USD
  runtime commands; do not place synthetic telemetry generator logic there.
- Keep the telemetry provider independent from asset loading. Loading an asset
  may later subscribe scene behaviour to telemetry, but asset load must not own
  provider lifetime.

Stage 3 provider testing:

- Add focused unit tests for the synthetic data provider module as part of
  Stage 3.
- Tests cover the happy path and boundary cases including invalid workload
  mode, unsupported refresh interval, freeze/resume behaviour, timestamp
  monotonicity after resume, metric unit/quality presence, expected metric keys,
  value clamping, deterministic seeded output, GPU ordering and capacity,
  derived metric consistency, node power balance, and intermittent throttling.
- Keep these tests independent of Kit UI so the provider boundary remains
  portable and can later move behind a process or container boundary.

Stage 3 generator behaviour:

- Stage 3 workload mode switching is manual. The operator selects `Idle`,
  `Nominal`, `Surge`, or `Critical`; automatic state cycling is out of scope
  for this slice.
- The selected mode defines target values for each synthetic metric.
- When the selected mode changes, metric values should move smoothly towards the
  new targets instead of jumping instantly.
- The provider may add bounded jitter around the current mode target so the
  telemetry reads as live data without becoming noisy or distracting.
- Provider cadence is driven by Kit runtime/app update time or another
  monotonic runtime clock, not by Houdini or DCC timeline playback.
- Provider state progression should run at its own fixed cadence, initially
  around 1 Hz, so interpolation and jitter remain predictable.
- The UI refresh selector controls how often the Telemetry tab samples the
  latest provider snapshot; it must not slow the provider's internal state
  progression.
- The UI timestamp may use wall-clock time for live-monitoring readability, but
  generator progression must not depend on DCC playback state.
- When `Freeze` is active, the provider should continue running and producing
  latest snapshots, but the UI should keep displaying the frozen snapshot until
  `Resume` is clicked.
- `throttling_active` is generated as a stateful Critical-mode episode rather
  than a static mode flag or per-tick random flicker. Episode probability is
  driven by CPU temperature, maximum GPU hotspot temperature, and PSU load;
  configured active and recovery durations keep the signal intermittent.

Stage 3 telemetry provider config:

- Generated metric baselines and safe ranges are config-driven. Aggregates and
  physically linked values are calculated by provider rules so operator edits
  cannot create contradictory GPU totals, thermal ordering, memory capacity,
  or node power balance.
- Add a separate telemetry provider config file owned by the telemetry/data
  provider module. Do not store telemetry targets in the existing DTRS local
  operator override config used for lighting, grid, camera, and look-review
  settings.
- The `Config` tab may expose telemetry provider settings, but persistence must
  go through the provider config path/API, not through the current DTRS
  `.local.toml` override.
- Use a read-only packaged base file plus a writable local override, for
  example `telemetry_provider.toml` merged with
  `telemetry_provider.local.toml`.
- The local override should be ignored by git and should contain operator edits
  such as tuned targets or jitter/range changes.
- The provider config file layout should let the telemetry module move later
  into a separate process or container with its own config and without breaking
  the DTRS data flow.
- The config should define global telemetry defaults such as default workload
  mode, default refresh interval, and allowed refresh intervals.
- The config should define per-mode targets for `Idle`, `Nominal`, `Surge`, and
  `Critical`, grouped by the Stage 3 telemetry groups.
- Numeric metrics should support `target`, `jitter`, `min`, and `max`.
- String state metrics support direct per-mode values. The Critical-mode
  `throttling_allowed` boolean is a provider gate; the displayed
  `throttling_active` value is calculated by the stateful throttling model.
- Initial values may be rough but plausible; tuning after runtime inspection is
  expected.

Temporary workload mode control:

- Until the DTRS shell has a dedicated global mode selector, the first control in
  the `Telemetry` tab should select the global workload mode:
  `Idle`, `Nominal`, `Surge`, or `Critical`.
- This selector is a temporary UI placement decision. The selected mode is still
  global DTRS runtime state, not telemetry-tab-local state.
- Stage 3 uses the selected mode to drive synthetic telemetry values.
- Later stages may move the same mode selector into a more global app-level
  control area when scene behaviour, fan motion, overlays, LEDs, or other DTRS
  modules need the same state.
- The Telemetry tab should include a `Freeze` toggle. When active, the provider
  keeps the current snapshot visible and pauses displayed updates so the
  operator can capture a stable UI frame. The same control should switch its
  label to `Resume` while frozen and resume normal updates when clicked again.

Stage 3 telemetry UI acceptance:

- The `Telemetry` tab is read-only for displayed telemetry values in Stage 3.
- The first implementation shows current values from the latest
  `TelemetrySnapshot` only.
- Do not add charts, history, sparklines, min/max columns, averages, trend
  buffers, or telemetry persistence in this slice.
- The top of the tab should expose the temporary workload mode selector,
  refresh interval selector, and `Freeze` / `Resume` control.
- Show a timestamp at the top of the telemetry view as `Last update` while
  running and as `Frozen at` while the view is frozen.
- Present metric values by operator meaning and identified hardware: node,
  CPU, each GPU, GPU array summary, power, CPU cooling, front intake, rear
  exhaust, airflow, network, and limits.
- Each visible metric row or compact card should show a human-readable label,
  current value, and unit.
- Metric `quality` is part of the runtime snapshot contract, but does not need
  to be prominent in the first UI. Synthetic source and derived value quality
  may remain hidden until a later detail or diagnostics surface.
- Use health/state colour only for high-level status readability: neutral/OK for
  normal state, amber for warning or degraded state, and red for critical state.
- Surface `throttling_active = true` as a clear warning indicator, row, or badge.

Stage 3 explicit non-goals:

- No charts, sparklines, trend lines, historical tables, or min/max/average
  sensor history.
- No telemetry storage beyond the latest in-memory snapshot needed by the UI and
  future scene consumers.
- No telemetry-driven fan motion or animated hardware behaviour; that starts in
  Stage 4.
- No live monitoring source, external feed adapter, network transport, or
  containerised provider runtime.
- No general alert or rule engine. `health_state` remains a direct mode value;
  the provider only owns the bounded CPU/GPU/PSU pressure model needed to
  generate intermittent `throttling_active` episodes.

Stage 3 manual validation:

- Max can launch DTRS and switch the left sidebar to the `Telemetry` tab.
- Telemetry values are visible and update without pressing Play in Houdini, Kit
  timeline, or any other DCC timeline.
- Changing the workload mode changes the telemetry targets and values move
  towards the new mode range.
- `Freeze` stops visible telemetry updates and `Resume` continues them.
- Switching between `Telemetry` and `Config` does not resize, overlap, or damage
  the viewport/sidebar layout.

Operator validation on 2026-07-09 confirmed all Stage 3 manual acceptance
items, including mode transitions, independent runtime updates, freeze/resume,
tab switching, config persistence, intermittent throttling, and clean DTRS
restart/shutdown behaviour.

First-layer node telemetry groups:

| Group | Metrics | Purpose |
| :--- | :--- | :--- |
| Node | `timestamp`, `operational_state`, `workload_percent`, `health_state` | Anchors the snapshot in runtime time and shows the selected workload and node health. |
| CPU | `cpu_temp_c`, derived `thermal_headroom_percent`, `cpu_power_w` | Connects CPU workload, package power, temperature, and remaining thermal margin. |
| GPU 1 / 2 / 3 | Per-GPU temperature, memory temperature, hotspot, power, blower RPM, allocated memory, and derived memory utilisation | Represents all three RTX PRO 4500 cards separately with independent jitter and provider-owned positional thermal bias. |
| GPU array | Maximum GPU, memory, and hotspot temperatures; total GPU power; total allocated GPU memory | Derives node-level GPU summaries from the three component values. |
| Power | `pdu_outlet_power_w`, `psu_output_power_estimate_w`, `cpu_power_w`, `gpu_power_w_total`, `platform_residual_power_w`, `psu_conversion_loss_w`, `psu_temp_estimate_c`, `psu_load_percent` | Balances synthetic PDU input, estimated PSU output, measured-class component contributors, platform remainder, conversion loss, thermal estimate, and PSU capacity without claiming unavailable consumer PSU sensors. |
| CPU cooling | `cpu_fan_rpm`, `cpu_fan_duty_percent` | Connects CPU thermal state to the Noctua cooler response. |
| Front intake | Three independent `front_fan_rpm` channels | Represents the three ARCTIC BioniX P120 front-intake fans. |
| Rear exhaust | Two independent `rear_fan_rpm` channels | Represents the two ARCTIC P8 Max rear-exhaust fans. |
| Airflow | `node_airflow_cfm` | Exposes the current node airflow estimate without inventing unsupported intake/exhaust measurements. |
| Network | `link_state`, `link_speed_gbps`, RX/TX throughput, `nic_temp_c`, packet error rate, and active RDMA sessions | Represents the NVIDIA ConnectX-7 link and workload-driven network activity. |
| Limits | `throttling_active` | Shows intermittent Critical-mode throttling episodes driven by CPU, GPU hotspot, and PSU load pressure. |

Deferred rack/facility telemetry fields and the extended live-provider contract
remain in `docs/knowledge_base/dtrs_telemetry_contract.md`. Stage 3 deliberately
expanded the node slice to cover the installed GPUs, cooling fans, PSU/PDU
balance, and ConnectX-7 NIC, but it does not expose rack or facility telemetry.

The current Case 03 node uses a consumer/workstation PSU. Stage 3 therefore
uses synthetic `pdu_outlet_power_w` as the external input and derives PSU
output, platform residual, conversion loss, load percentage, and estimated
temperature. These estimates remain distinct from direct PSU sensor readings.
Server-class PSU fields are reserved for future live providers that can supply
them through a digital PSU, smart PDU, UPS, branch circuit monitor, BMC,
Redfish, IPMI, or PMBus source.

### Stage 4 - Telemetry Driven Motion Slice

Jira: `DC-43`

Connect the synthetic telemetry snapshot to visible scene behaviour. The first
motion target is the Noctua CPU cooler fan: the sidebar keeps reporting the
realistic `cpu_fan_rpm`, while the viewport rotates the fan blades from the same
live telemetry signal.

Scope:

- create a small generic rotation-motion controller owned by
  `msp.dtrs`;
- update it once per Kit frame from `app.next_update_async()`, not only at the
  slower telemetry UI refresh interval;
- use `SyntheticTelemetryProvider.latest_snapshot.metrics["cpu_fan_rpm"]` as
  the input signal;
- keep the UI Freeze action display-only: frozen telemetry rows must not pause
  the provider or the fan motion.

Runtime motion discovery:

- do not rely on Houdini SOP nulls alone being preserved as usable USD runtime
  controls. The preferred exported contract is a rotating mesh under a stable
  parent `Xform` whose local origin lies on the physical rotation axis;
- the first target mesh is
  `/cpu_fan/geo/render/cpu_cooler/cpu_fan/blades/blades`;
- build edge adjacency from `faceVertexCounts` and `faceVertexIndices`;
- use the mesh bounds only as a coarse search window. A seven-blade impeller is
  not symmetric enough for the bounding-box centre to be a valid pivot;
- find high-valence pole candidates near the hub. Most fan and blower meshes in
  this project originate from 32- or 64-sided cylinders, so centre-pole
  candidates should have at least 32 edge-connected neighbours;
- score candidates by valence, distance from the coarse centre, and neighbour
  distance distribution, then cluster the best candidates into the front/back
  hub centres;
- derive the rotation axis from the front/back hub-centre line and the pivot
  from their midpoint or shared centre line;
- prefer direct rotation on the authored parent `Xform` when the topology
  result validates that the resolved axis passes close to the parent's local
  origin. For a local `Z` axis, the resolved pivot must have near-zero `X` and
  `Y`; the `Z` coordinate may differ because all points on that line share the
  same rotation axis;
- when the authored parent origin is missing or off-axis, fall back to a
  Session Layer pivot stack shaped as
  `translate(pivot) -> rotate(axis) -> translate(-pivot)`;
- cache the resolved pivot and axis per prim path. Recompute only when the
  stage, asset, or prim identity changes.

For the current Noctua fan, the validated mesh-local result is a local Z-axis
with the hub line near `(0.0, 0.0, z)` after the corrected export. Earlier
exports produced the same physical axis with an offset mesh-local pivot; this
remains the fallback case and test fixture. The runtime transform must be
authored as a non-destructive Session Layer override on the existing rotating
prim or its nearest suitable `Xform`, so the referenced USD files and root layer
stay clean.

Scalability and level of detail:

- topology discovery is acceptable for a hero component or a hero server because
  it runs on load or asset reload and then caches the pivot/axis per prim path;
- a full server may animate all meaningful visible rotating parts: CPU fan,
  front intake fans, rear exhaust fans, GPU blowers, and the PSU fan;
- server-level fan and blower assets should follow the DTRS motion contract
  documented in `src/digital_twin_runtime_suite/README.md`: stable rotating
  parent `Xform` first, topology-validated axis discovery, Session Layer pivot
  stack only as fallback;
- rack and data-hall views should not animate hidden server internals. At those
  scales, motion should be gated by visibility, selected asset, camera distance,
  and scene detail mode;
- for a full server room, the fallback presentation can animate only
  front-facing fans on nearby or highlighted servers, with distant racks staying
  static or using aggregate visual cues.

Timing:

- measure frame deltas with monotonic time;
- clamp a single frame delta to about `0.1` seconds to avoid a large jump after
  focus loss, reload, or a temporary stall;
- accumulate the angle modulo 360 degrees;
- reset or reacquire stage and prim state on asset reload or stage close.

Display mapping:

The telemetry RPM remains physically plausible for the hardware config: Idle
`650-900`, Nominal `1000-1380`, Surge `1500-1950`, Critical `2050-2300`. The
viewport should not use those RPM values directly, because a seven-blade fan
sampled by an interactive viewport can alias, appear frozen, or reverse. Stage
4 should map telemetry RPM to a labelled presentation speed range that remains
visually readable, responds to jitter and interpolation, and keeps the four
workload modes distinct. This mapping is a display device, not a new telemetry
value. The current first-pass presentation range is `40-360 RPM`: fast enough
to read as an active fan in the viewport, but still below the first seven-blade
stroboscopic stop point at 50 FPS (`~429 RPM`).

Stage 4 deliberately does not lock the whole Kit render loop to 50 FPS. The
simulation/cache cadence belongs to Stage 6: cached playback should map elapsed
seconds to authored time codes, and deterministic capture can request a fixed
capture rate when needed. The fan controller should be robust to variable
interactive frame rate.

Failure behaviour:

- missing stage, missing prim, invalid mesh path, or incompatible xform stack
  must not crash the telemetry loop;
- warnings should be one-shot or rate-limited;
- extension shutdown should stop the controller and remove or neutralise the
  runtime session override when the stage is still available.

Automated checks:

- telemetry RPM to presentation speed mapping, including clamp boundaries;
- angle increment, wraparound, and `dt` clamp;
- controller reset or reacquire behaviour;
- topology-based pivot and axis discovery, including the Noctua 7-blade mesh
  fixture;
- high-valence candidate filtering for 32- and 64-sided cylinder-derived hubs;
- session-layer authoring helper does not target the root layer;
- missing prim or stale stage is handled without repeated errors.

Manual checks:

- load the Noctua NH-D9 TR5-SP6 asset and confirm continuous blade rotation;
- confirm the runtime-resolved pivot matches the known Noctua centre closely
  enough to avoid visible orbiting or wobble;
- switch Idle, Nominal, Surge, and Critical and confirm the visual speed changes
  smoothly with telemetry interpolation;
- click Freeze and confirm the UI rows freeze while fan motion continues;
- reload the asset and confirm rotation resumes without a visible jump;
- confirm the source USD and root layer are not dirtied by runtime motion.

Done when the CPU fan rotates from live telemetry, survives reload and
shutdown, keeps authored USD assets clean, and has focused tests for the
controller logic and edge cases.

### Stage 5 - Server Review Slice

Jira: `DC-44`

Status: implemented and accepted.

Release track: `0.3.0` (released on Stage 5 completion).

Move from the single hardware asset to the full server or Blackwell Rig scene.
Keep the controls minimal: load, focus/navigation, status, and any lighting
control already proven in earlier slices.

Stage 5 has an asset-readiness gate. Each server component must progress through
the same states in order:

`Topology fixed` -> `USD exported` -> `Static preflight passed` ->
`RTX passed` -> `Runtime contract passed` -> `Composition ready`.

| Asset | Final state | Note |
| :--- | :--- | :--- |
| `cpu_fan` | Composition ready | Topology repair, re-export, static checks, RTX review, and runtime fan binding complete. |
| `ws_wrx90e` | Composition ready | Topology repair, hierarchy correction, pivot-normalised re-export, and NVMe fan binding complete. |
| `rm44` | Composition ready | Topology repair, re-export, RTX review, and open-chassis presentation complete. |
| `rtx_pro_4500` | Composition ready | Topology and pivot-normalised blower re-export complete; all three GPU blower bindings validated. |
| `connectx7` | Composition ready | Topology, material compatibility, and re-export work complete. |
| `psu` | Composition ready | Topology repair, pivot-normalised re-export, and PSU fan binding complete. |
| `ram` | Composition ready | Topology repair and re-export complete. |
| `bionix_p120` | Composition ready | Re-export and three front-intake fan bindings complete. |
| `p8_max` | Composition ready | Re-export and two rear-exhaust fan bindings complete. |
| `cables` | Composition ready | Topology, connector, material compatibility, and re-export work complete. |

Canonical server-stage contract:

- Houdini/Solaris exports a static server composition with the root
  `/blackwell_rig` `Xform` at the world origin and set as `defaultPrim`.
- The stable path under the hydrated asset root is
  `usd/Blackwell_Rig_server_assembly.usd`.
- The stage preserves the Houdini-exported `metersPerUnit = 1.0` and
  `upAxis = "Y"`; DTRS does not convert or repair units or orientation.
- Existing Houdini references compose the component entry points, and Stage 5
  loads the complete server assembly eagerly. Payload-based selective loading
  is outside Stage 5 and remains a later rack/data-hall decision.
- Component and texture dependencies use relative paths only.
- The static composition excludes VDB layers, workload-specific visual state,
  and authored timeline animation.

Static preflight contract:

- Run the standard OpenUSD `usdchecker` against each corrected component export
  and the canonical server stage before RTX review.
- Keep any Case 03-specific preflight supplement deliberately small. It should
  check unresolved component and texture dependencies, absolute paths,
  `defaultPrim`, `metersPerUnit`, `upAxis`, configured chassis cover paths,
  configured fan targets, and accidental VDB or authored time-sample content.
- Do not build a separate general-purpose validation framework for Stage 5.
- A static preflight pass proves structural USD readiness only. It does not
  prove that holes, complex polygons, normals, or materials render correctly in
  Omniverse; the RTX visual pass remains the topology and rendering authority.

The canonical assembly export passed the Stage 5-specific structural checks:
the root and `defaultPrim` are `/blackwell_rig`, the root is at the world
origin, all 22 component references and asset dependencies resolve, all authored
dependency paths are relative, and no VDB or time-sampled content is present.
After reloading Houdini references and re-exporting the assembly, `simproxy`
content, thumbnail dependency findings, and prim-encapsulation findings are no
longer present. Strict local OpenUSD compliance still reports MaterialX shader
conformance findings from Houdini-authored MaterialX networks. These are
accepted as a documented non-blocking Stage 5 exception because the target
runtime is Omniverse/Kit, where the same materials load and render
successfully. Material authoring cleanup remains deferred to later runtime
material-state stages.

The full assembly passed a clean-start RTX visual load in DTRS on 2026-07-19:
`Blackwell_Rig_server_assembly.usd` opened with `LOAD_ALL` in 0.96 seconds,
framed correctly, and displayed the complete server without unresolved asset,
texture, or material-load errors. Visual inspection from multiple exterior
angles confirmed correct composition and rendering. The integrated Stage 5
motion pass then confirmed all 11 configured fan and blower bindings rotate
correctly without visible orbital offset. One known diagnostic is accepted as a
non-blocking Stage 5 exception: RTX ignores the degenerate motherboard helper
mesh named `connect_rj_45_cable_here`, which produces no visible defect. Helper
mesh cleanup remains deferred.

For the fan-motion review pass, DTRS applies a reversible session-layer chassis
presentation override: `open_chassis = true` hides the full `top` and `side`
cover subtrees in both the `render` and `proxy` branches. This leaves the
Houdini-authored server assembly complete and untouched; the same runtime
mechanism restores `inherited` visibility when the enclosure is closed. The
current debug configuration therefore hides the rack ears along with the side
panels. Their final presentation policy remains open. A visible
front-of-application controller for opening and closing these panels is
deferred to Stage 17 UI refinement rather than being treated as an already
shipped Stage 5 control. The former camera-aware opacity-fading concept was
later cancelled; Stage 5 remains a deliberately static review presentation
while server fan motion is proved.

Stage 5 fan motion reuses the
[Stage 4 DTRS motion contract](case%2003%20-%20completed%20runtime%20stage%20plans.md#stage-4---telemetry-driven-motion-slice)
rather than inventing per-part exceptions: CPU cooler fans, front intake fans,
rear exhaust fans, GPU blowers, and the PSU fan each expose a stable rotating
parent `Xform` whose local origin lies on the rotation axis, with
topology-validated pivot-stack fallback for older or imperfect exports. Every
supported fan binding explicitly declares `rotation_target_path`,
`rotation_axis`, `pivot_mode`, and `metric_id` in configuration. Discovery may
find and validate candidate fan prims beneath stable component roots by the
`blades` name or name substring, but it must not infer the rotation axis. Stage
5 uses `authored_origin` for corrected exports and keeps the Stage 4 topology
resolver as a fallback for older or imperfect assets.

Delivered Stage 5 fan bindings:

- CPU cooler: rotate
  `/blackwell_rig/cpu_cooler/geo/render/cpu_cooler/cpu_fan/blades` around axis
  `Z`.
- RTX PRO 4500 blowers: rotate each
  `/blackwell_rig/compute/gpu_*/geo/render/RTX4500/blower` around axis `X` using
  its authored local origin. Rotating the hidden `blower_base` with the blades,
  ring, and shaft is an accepted simplification.
- PSU fan: rotate
  `/blackwell_rig/power/psu/geo/render/psu/cooling/blades` around axis `X`.
- Motherboard NVMe fan: rotate
  `/blackwell_rig/motherboard/geo/render/ws_wrx90e/nvme_b/nvme_fan` around axis
  `Y`.
- Front BioniX P120 fans: rotate each
  `/blackwell_rig/fans/p120_*/geo/render/bionix_p120/blades` around axis `Z`.
- Rear P8 Max fans: rotate each
  `/blackwell_rig/fans/p8_*/geo/render/p8_max/p8_max_blades` around axis `Z`.

The runtime-contract check confirms that each configured target exists and can
complete a test rotation around its declared axis without visible orbital
offset. Stage 5 accepts two telemetry simplifications: the PSU fan is driven by
derived `psu_load_percent` and mapped to visual RPM, while the motherboard NVMe
fan currently shares `cpu_fan_rpm` with the CPU cooler. Dedicated channels may
replace those mappings in a later telemetry refinement pass.

Done when the server scene loads reproducibly, remains stable in the RTX
viewport, all supported fan motion matches telemetry speed, and the scene can
be reviewed without manual USD edits.

Stage 5 was accepted on 2026-07-19 and `DC-44` was moved to Done. The delivery
commit is `d4331db` (`Deliver Stage 5 full-server DTRS review`).

### Stage 6 - Cached Simulation Playback Slice

Jira: `DC-45`

Status: implemented and accepted on 2026-07-27.

Release track: `0.4.0` (released with Stage 7; Stage 8 has no separate bump).

Stage 6 delivers an honest runtime airflow visualisation from an externally
produced Houdini velocity field. DTRS does not claim to generate the source
simulation live. The completed runtime route is:

```text
Houdini airflow simulation
  -> manifest-driven temporal VTI velocity dataset
  -> Kit-CAE CaeDataSet / PointData/vel
  -> CAE velocity / NanoVDB bridge
  -> one NVIDIA Flow DataSetEmitter and FlowSimulation
  -> real-time volumetric smoke tracer
```

Delivered runtime contract:

- Dataset discovery is driven by `manifest.toml` beneath
  `assets/_external/airflow_datasets/`, selected by manifest `scope` and
  `state`, rather than by hardcoded folder names or VTI path arrays.
- The accepted server / load_normal dataset has 80 unique VTI samples at a
  source step of 10 frames and 50 source FPS. DTRS derives a 0.2 second / 5 Hz
  runtime cadence and a 16 second loop from that manifest.
- The VTI -> Kit-CAE -> Flow route validates VTI metadata, the manifest grid,
  temporal consistency, origin compatibility, and DataSetEmitter readiness.
  The narrow DTRS session-layer origin workaround preserves source VTI and
  authored server USD unchanged.
- `SMOKE_ONLY` remains the tracer contract: smoke is transported by imported
  VTI velocity; fuel, temperature, burn, combustion, buoyancy, and collision
  behaviour are not enabled by Stage 6.
- Cloud rendering exposes persistent, Apply-based operator tuning for
  appearance, dynamics, raymarch quality, vorticity, velocity multiplier, time
  scale, and smoke colour. Pending dropdown or colour edits do not mutate Flow
  before Apply succeeds.
- The persistent emitter layout exposes columns, rows, depth, size, horizontal
  margin, and vertical margin. It rebuilds only tracer emitters, keeps helper
  geometry hidden, and retains imported VTI as the sole velocity source.
- All operator overrides use the existing local runtime TOML with validation,
  peer-preserving round trips, and atomic replacement.

Validation and acceptance evidence:

- Generic temporal proof records `N` unique assets and hashes, `N - 1` forward
  transitions, one loop closure, continuous timeline, validated origin/grid,
  and zero Flow resets. The accepted 80-sample dataset therefore proves 79
  forward transitions and one loop transition.
- Focused pure-Python tests cover manifest discovery and validation, temporal
  timing, smoke tuning, transport scale, emitter layout, local override
  persistence, and Flow no-reset semantics. The Stage 6 suite passed with 145
  tests; flake8 and `git diff --check` also passed.
- Manual Kit acceptance covered Attach, Play, temporal advancement, smoke and
  layout Apply operations, Pause/Play, Detach, re-Attach, restart persistence,
  and fixed-camera FPS comparison on the RTX 3080.

The smoke presentation was tuned interactively through the shipped controls.
Vorticity masks remain an internal implementation detail: further mask tuning
was deliberately excluded because no remaining FPS budget justified it. The
runtime exposes vorticity enable/strength but does not add a second user-facing
mask control.

Historical direct OpenVDB/RTX-IndeX and early diagnostic Flow experiments are
closed evidence routes. They do not describe the shipped Stage 6 runtime path.

#### Post-acceptance hotfix - responsive VTI Attach (completed)

This post-acceptance Stage 6 hotfix resolved the measured interaction defect
without reopening the delivered simulation contract or beginning Stage 7.

Implemented behaviour:

- VTI-only metadata preflight runs outside the Kit update thread and reports
  plain-data progress safely back to the Kit coroutine. UI, telemetry, fan
  motion, and viewport navigation remain responsive while it runs.
- The one-line status panel reports preparation progress as `VTI N/80`; temporal
  USD `fileNames` samples are authored in bounded main-thread batches that yield
  control to Kit between batches.
- Initial VTI import and Flow readiness complete before Attach succeeds. The
  full temporal proof runs afterwards as a cancellable background task, with its
  progress exposed in the status panel and periodic performance logs.
- Session-local preflight and temporal-proof receipts retain only plain data.
  Their signature covers the manifest, ordered VTI samples, resolved paths,
  file sizes, `mtime_ns`, velocity field name, and validation-contract version.
- An ordinary Detach preserves successful receipts. Config reload and extension
  shutdown clear them; a changed dataset receives a cache miss or invalidation.
  Every Attach still creates fresh Kit-CAE/Flow runtime prims and confirms
  initial Flow readiness.
- Persistent validation cache across DTRS launches is intentionally not
  implemented. Workload-dataset switching remains Stage 8 scope.

Focused automated coverage validates receipt reuse/invalidation, temporal
progress, cancellation, stale-generation protection, and reload lifecycle
boundaries. Manual Kit validation confirmed responsive Attach, cache reuse,
background proof completion, cancellation, Detach, and re-Attach.

### Stage 7 - Engineering X-Ray Visual Mode Slice

Jira: `DC-48`

Status: COMPLETE / VALIDATED.

#### Stage 7.0 - Material recovery and temporary normal-map tuning

0. Record this agreed plan before implementation of the X-Ray Visual Mode slice.
1. During USD preflight, inspect only materials bound to server meshes. Where a Houdini-exported MaterialX texture map is present but the bound `UsdPreviewSurface` omits the equivalent renderer-facing input, create the missing connection in the session layer. Support base colour, roughness, metallic, normal, opacity and emission maps; never fabricate a map that the asset does not contain.
2. Keep the master USD untouched. Log every actual repair with the asset id, material path, map role, texture filename and repaired `UsdPreviewSurface` input. Re-running preflight must not duplicate a repair or its log entry.
3. In `View`, add a permanent `Server Appearance` section. Move the existing `Server enclosure` controls inside it and add a permanent `Materials` subsection.
4. Inside `Materials`, add only one temporary debug subsection: `Normal Map Scale`. Its single control adjusts the `scale` input of renderer-facing normal-map texture nodes after the material-recovery pass has connected them.
5. After the intended normal-map values are established, remove or hide only the `Normal Map Scale` debug subsection; retain `Materials`.
6. Cover the material repair and normal-map scale control with focused automated tests, then perform scoped Kit validation.


#### Stage 7.1 - Engineering X-Ray Visual Mode Slice

> [!NOTE] COMPLETE / VALIDATED
> Stage 7.1 delivered the production Custom MDL Fresnel implementation,
> config-driven target selection, reversible Session Layer bindings, live
> ReviewCamera response, and accepted combined X-Ray + Flow validation. The
> rejected Surface Falloff investigation remains recorded below as historical
> implementation evidence.

Release: `0.4.0`.

Introduce a manually controlled, reversible runtime visual override that lets
the operator inspect internal server components and simulation layers through
otherwise occluding chassis geometry.

Required scope:

- expose Engineering X-Ray target selection, an `Apply` action, and visible
  applied or error status;
- apply runtime or Session Layer overrides without editing authored USD assets
  or MDL sources;
- restore the original presentation when a target is unchecked and `Apply` is
  pressed, on stage reload, and on application startup;
- initially target the outer chassis and other documented occluding components,
  including the SilverStone RM44 walls and covers;
- keep production X-Ray operator values applied only by `Apply`, while the
  production material receives the current ReviewCamera position through the
  established live synchronisation path;
- author a dedicated runtime-only material override or material binding for
  the selected logical asset. Do not mutate a shared Houdini-authored chassis
  material;
  validate the chosen Omniverse renderer material path before depending on
  smooth opacity in RTX;
- retain `Server Enclosure` as the sole owner of top-cover and panel visibility;
  X-Ray must leave existing visibility choices intact, including when a
  material reaches zero opacity;
- establish an override boundary that later LED, heatmap, and other material
  states can compose with instead of silently replacing.

Current production contract — material and Session Layer:

- retain Houdini-authored materials and bindings unchanged;
- define available logical target groups and their explicit render subtrees in
  project configuration. The production set covers the RM44 chassis, front and
  rear fans, CPU-cooler fans, GPU shrouds with blower/power/cables, and PSU
  enclosure subtrees;
- let the X-Ray UI own the transient selected-group set. All checkboxes start
  OFF after startup or config reload, while Fresnel parameters persist locally;
- author the project-owned Custom MDL Fresnel material only through Session
  Layer `material:binding` opinions on resolved Mesh prims, never blindly on a
  parent Xform or into authored asset layers;
- on deselection, OFF, stage reload, and shutdown, remove only X-Ray-owned
  binding property specs so the weaker authored or prior Session opinion
  recomposes naturally. OFF must never bind a guessed original material;
- use one shared Fresnel/NdotV mask for Base Color, Glossy Roughness, Opacity,
  and Emission. The material receives live ReviewCamera world position through
  its `camera_position` input;
- preserve `Server Enclosure` as the sole owner of chassis visibility. X-Ray
  changes material bindings and parameters only;
- give the chassis target priority over telemetry LED appearance while active.
  Telemetry state continues advancing, and removal reapplies its current state;
- keep runtime material and binding opinions under the transient DTRS runtime
  namespace; validate lifecycle restoration and combined Flow compatibility
  before accepting production changes.

Surface Falloff investigation outcome — rejected implementation path:

- The proposed graph was `Part A` (transparent-facing) and `Part B`
  (coloured/emissive hologram edge) through
  `nvidia::core_definitions::surface_falloff`, with
  `facing_weight`, `edge_weight`, and `blend_bias` controlling the
  view-dependent blend.
- DTRS validated the surrounding runtime architecture: all 44 chassis meshes
  received the intended Session Layer binding; the material terminal and
  `base`/`blend` connections were composed correctly; Sdr registry types and
  material-struct metadata matched the registered MDL definition; and the
  Neuray renderer-side call contained the expected material references and
  scalar values.
- In the strongest DTRS control, both inputs referenced the same opaque yellow
  Part A material, with `facing_weight = 1.0`, `edge_weight = 1.0`, and
  `blend_bias = 5.0`. Neuray confirmed the same Part A call, yellow diffuse
  colour `(1.0, 1.0, 0.0)`, and disabled opacity, while RTX rendered an
  incorrect grey result. The defect is therefore below DTRS USD/MDL graph
  authoring.
- The failure was independently reproduced in a clean standalone Kit 110.1
  Material Graph scene, without DTRS, Python, Session Layers, runtime
  `UsdShade` authoring, chassis geometry, or DTRS bindings. `Part A` and
  `Part B` connected directly to Material Output rendered correctly, but
  `A/A` and `A/B` through Surface Falloff did not. RTX Real-Time 2.0 produced a
  black/dark result; RTX Interactive (Path Tracing) removed that artifact but
  still failed to evaluate Blend Material correctly.
- A minimal reproduction scene and screenshots were submitted to the NVIDIA
  Developer Forums under `Omniverse → Core Platform → RTX Renderer`. Do not
  resume debugging or artist-tuning this Surface Falloff graph unless NVIDIA
  provides new information or a fix.
- `nvidia::core_definitions::apply_colorfalloff_v2` was separately observed to
  work view-dependently in RTX Interactive but to be effectively ignored in
  RTX Real-Time 2.0. This is a related renderer-mode observation, not a proven
  replacement or the next implementation decision.
Custom MDL validation outcome:

- `DTRS_Fresnel_Test.mdl` is the selected project-owned replacement path.
  Its view-angle mask is conceptually derived from `N = state::normal()`,
  `P = state::position()`, `V = camera_position - P`,
  `NdotV = abs(dot(N, V))`, and `raw_edge = 1 - NdotV`, then remapped through
  Edge Center, Edge Softness, and Edge Sharpness.
- The permanent semantic contract is `mask = 0` for the facing surface and
  `mask = 1` for the grazing / silhouette edge. `state::direction()` was
  rejected for this route; the current material explicitly receives the
  ReviewCamera world position through its `camera_position` input.
- One project-owned camera-reactive NdotV mask drives all tested material
  channels:

  ```text
                          ┌→ Base Color
                          ├→ Roughness
  ReviewCamera → NdotV ───┼→ Opacity
       mask               │
                          └→ Emission
  ```

  Edge Center, Edge Softness, and Edge Sharpness remain the shared shape
  controls for all four consumers.

#### Custom MDL X-Ray material phases

Phase 1 — Base-colour view-angle proof — VALIDATED

- The project-owned custom MDL material is evaluated on isolated Cube and
  smooth Sphere probe geometry.
- The same controllable NdotV mask drives interpolation between Facing Color
  and Edge Color.
- Edge Center, Edge Softness, and Edge Sharpness have been manually validated.
- ReviewCamera world position is synchronised live into the MDL
  `camera_position` input while the probe is active.
- The mask follows camera movement without requiring Apply or rebuild.
- Probe creation, parameter updates, cleanup, camera preservation, and live
  camera synchronisation are covered by focused tests and manual Kit
  validation.

Phase 2 — Controllable opacity — VALIDATED

Opacity is remapped between independently controllable artist endpoints,
rather than driven directly by the `0..1` mask output:

```text
final_opacity =
    facing_opacity * (1 - mask)
  + edge_opacity   * mask
```

Facing Opacity and Edge Opacity are manually validated in production and remain
independently controllable.

Final Probe control pass — Fresnel-driven Glossy Roughness — VALIDATED

- Facing Roughness and Edge Roughness are independent `0..1` artist controls
  that use the same shared mask:

  ```text
  final_roughness =
      facing_roughness * (1 - mask)
    + edge_roughness   * mask
  ```

- The endpoints are authored, persisted, and covered by focused tests. They
  safely clamp in the custom MDL and do not alter Color, Opacity, Emission,
  Emission Scale, Fresnel shape controls, camera input, live synchronisation,
  or the performance sampler.
- The initial `df::diffuse_reflection_bsdf` Oren–Nayar route was rejected
  because it did not provide PBR-style environment/specular reflections. The
  corrected material layers a fixed-strength GGX microfacet reflection over a
  simple diffuse base, with `final_roughness` driving the isotropic GGX
  `roughness_u` and `roughness_v` inputs.
- Facing / Edge Roughness, shared Fresnel-mask interpolation, glossy/specular
  reflection response, reversed endpoint relationship, and live ReviewCamera
  response are all manually validated in production.

Phase 3 — Controllable emission — VALIDATED

Emission uses the same mask:

```text
artist_emission =
    facing_emission * (1 - mask)
  + edge_emission   * mask
```

Manual isolation proved both directions: strong Facing Emission makes the
facing region emissive, while strong Edge Emission makes the grazing region
emissive. Early apparently ineffective values were an intensity-scale and
HDRI/exposure calibration issue, not a Fresnel-routing or MDL surface-emission
failure.

The material additionally applies `final_emission = artist_emission *
emission_scale`. Facing / Edge Emission define relative artistic balance;
Emission Scale defines global strength against HDRI/exposure. Emission Scale is
an artist-facing presentation control, not a calibrated physical unit.

The production Fresnel parameter set persists through the local `.local.toml`
override: Facing Color, Edge Color, Edge Center, Edge Softness, Edge Sharpness,
Facing Roughness, Edge Roughness, Facing Opacity, Edge Opacity, Facing
Emission, Edge Emission, and Emission Scale. Only operator values persist;
runtime material bindings remain transient and are not reconstructed at startup.

ReviewCamera position is synchronised live into the production custom MDL, so
Base Color, Glossy Roughness, Opacity, and Emission follow the current view
without Apply. HUD-backed production sampling uses the established Stage 6
viewport-statistics source and reports FPS, frame time, GPU memory, and process
memory every 10 seconds.

Phase 4.0 — Production X-Ray binding / ownership lifecycle — VALIDATED

With Fabric Scene Delegate disabled (`/app/useFabricSceneDelegate=false`),
manual validation confirmed repeated X-Ray cycles: ON bound the temporary
lifecycle control
material to 40/40 static chassis targets and 4/4 telemetry LED targets; OFF
restored baseline material bindings for all 40 static targets, left zero
X-Ray-owned bindings, and resumed LED appearance from current telemetry state.
No green fallback state, Reload Config, or restart was required.

FSD limitation: in the tested Case 03 / current Kit environment, the same
lifecycle is problematic specifically with Fabric Scene Delegate enabled:
USD lifecycle PASS, Fabric binding PASS, viewport rollback FAIL. Launching
with `--/app/useFabricSceneDelegate=0` restores correctly. Treat this as a
tested FSD runtime limitation; a minimal standalone reproduction and potential
NVIDIA bug report are deferred to later work. Do not investigate FSD further in
this phase.

Phase 4.1A — X-Ray subsystem refactor — VALIDATED

The validated binding lifecycle, material construction, and ReviewCamera
synchronisation now have clear ownership boundaries before production shading
becomes more complex. This was a behaviour-preserving refactor only.

Phase 4.1B.1 — Production Fresnel material integration — VALIDATED

The temporary `XRayLifecycleControl` payload now uses the validated
project-owned custom Fresnel MDL. Manual validation confirmed live ReviewCamera
response and preserved production ON/OFF restoration.

Phase 4.1B.2 — Remove obsolete Part A controls — VALIDATED

Phase 4.1B.3 — Move Fresnel controls from Debug to X-Ray — VALIDATED

Phase 4.1B.4 — Remove Debug Fresnel probe + cleanup — VALIDATED

Phase 4.1B — COMPLETE

Phase 4.2A — Multi-target X-Ray selection — VALIDATED

Phase 4.2B — Visual Fresnel tuning — VALIDATED

Phase 4.2C — Production defaults — VALIDATED

Phase 4.2D — Performance acceptance — VALIDATED

Phase 4.2 — COMPLETE

Phase 4.3A — Final code/documentation review — VALIDATED

Phase 4.3 — COMPLETE

Phase 4.2A adds independently selectable production asset groups while keeping
the Fresnel payload, Session Layer lifecycle, and telemetry ownership contract
unchanged. Visual tuning follows only after target selection is validated.

Phase 4.2D manual acceptance validated combined RTX Flow and X-Ray operation
on the tested RTX 3080: typical Flow plus X-Ray ran at approximately 25–27 FPS,
and Flow plus all X-Ray targets at approximately 20–25+ FPS. Flow resets,
temporal playback, and the X-Ray lifecycle all passed.

Phase 2 passed before Phase 3. The binding/ownership prerequisite is now
validated; the production Fresnel material and its operator controls are now
integrated on the RM44 chassis.

- The isolated custom-material proof is complete for Base Color, Glossy
  Roughness, Opacity, Emission, Emission Scale, and live ReviewCamera
  synchronisation; its project-owned MDL is now the production X-Ray payload.
- Stage 7.1 architecture remains valid: UI/config persistence, logical target
  selection, Session Layer runtime binding, reversible material override, and
  `Server Enclosure` visibility ownership. The custom shader proof and the
  production binding lifecycle are validated; Fresnel controls are owned by
  production X-Ray.

Implementation notes:

- NVIDIA documents `core_definitions::surface_falloff` as an MDL material
  modifier with `base`, `blend`, `facing_weight`, `edge_weight`, and
  `blend_bias` inputs, but it is no longer a viable Stage 7.1 implementation
  candidate in the tested Kit/RTX stack (see investigation outcome above);
- for OmniSurface, the candidate facing material must explicitly enable opacity
  and use `geometry_opacity`; `0.0` is invisible to camera rays and `1.0` is
  fully opaque. Opacity is the preferred candidate mechanism for the fade;
  specular transmission is not a substitute for this visibility control;
- an emissive edge treatment is technically supported, but it must remain
  restrained. RTX Interactive path tracing can require a higher sample budget
  to control emissive noise;
- material binding is applied to a prim through `UsdShade.MaterialBindingAPI`.
  The eventual runtime inspection must record the effective binding target and
  winning binding for each proposed X-Ray panel;
- static runtime-dependency check confirmed that DTRS includes
  `omni.hydra.rtx`, which resolves the MDL runtime through
  `omni.mdl.neuraylib` and `omni.kit.usd.mdl`. The resolving Kit release bundles
  `nvidia::core_definitions::surface_falloff` and OmniSurface MDL modules;
  adding the Material Graph editor UI extension is neither required nor
  appropriate for the operator-facing application;
- Focused automated coverage and manual Kit validation cover Session Layer
  lifecycle restoration, production Custom MDL Base Color, Opacity, Emission,
  artist-facing Emission Scale, Glossy Roughness, and live camera-reactive
  mask. Production full-server integration, combined Flow compatibility, and
  accepted RTX 3080 performance are validated.

Done when Engineering X-Ray can be enabled and disabled reproducibly through
the target checkbox and `Apply`, uses a validated alternative view-dependent
shader, restores the original material presentation by removing its own Session
Layer binding opinions, does not change `Server Enclosure` visibility choices,
persists its operator settings locally without auto-applying after startup or
stage reload, reveals the documented internal review targets, and does not dirty
authored assets.

### Stage 8 - Workload-to-Cache State Binding Slice

Jira: `DC-46`

Status: COMPLETE / ACCEPTED EVIDENCE.

Stage 8 binds the existing `Idle`, `Nominal`, `Surge`, and `Critical` semantic
workload state to the corresponding Houdini-authored temporal airflow family.
It introduces no second workload model and retains the Stage 6 Flow lifecycle.

#### Public claim evidence

> The same workload state drives telemetry, hardware behaviour, and selection
> of the corresponding Houdini-authored temporal airflow dataset, with
> manifest-driven validation and phase-preserving runtime switching.

| Claim clause | Concrete evidence |
|---|---|
| Semantic workload drives telemetry | The Telemetry Workload control calls `SyntheticTelemetryProvider.set_mode`; the controller consumes that provider mode through the workload-binding boundary. |
| Semantic workload drives hardware behaviour | The telemetry snapshot supplies CPU/GPU/front/rear fan RPM metrics to the existing motion bindings; telemetry and motion tests cover the fan metric route. |
| Semantic workload selects authored airflow | `SimulationCacheConfig` holds the explicit mapping to `server/load_idle`, `server/load_normal`, `server/load_surge`, and `server/load_critical`; Attach and transitions resolve through `workload_binding`, then manifest discovery. |
| Manifest-driven validation and reuse | Dataset identity is manifest `scope/state`, not a directory name. `airflow_validation` validates the discovered sequence and `SessionValidationCache` reuses matching receipts using manifest, selector, field, and VTI filesystem identity. |
| Phase-preserving runtime switching | The attached transition resolves normalized discrete phase, retargets the live temporal source at a sample boundary, verifies native consumption and the direct-Attach runtime contract, then commits without Detach, Attach, reset, or rebuild. Focused regressions cover phase mapping, runtime-contract gating, playback intent, failure semantics, and latest-request-wins races. |

#### Completion record

- Steps 1-16 are complete: registry and explicit mapping; workload-binding
  ownership; workload-resolved Attach; sequential/pre-emptible validation;
  in-place retarget proof; attached transitions; truthful failure semantics;
  family compatibility; supersession; signature/reload semantics; focused
  coverage; prepared Kit matrix; and accepted existing latency evidence.
- Existing Kit logs measured cached `REQUEST -> COMMIT` at approximately
  `0.98-1.63 s`, next-boundary wait at approximately `50-63 ms`, and cached
  Attach at approximately `4.0 s`; no latency-driven architecture change is
  required for the showcase.
- The full manual visual matrix prepared for Step 15 is deferred to Stage 9,
  where visual inspection is already required. This does not invalidate the
  bounded public claim above: its telemetry/hardware route, manifest selection,
  validation, and phase-preserving switching all have code, focused-regression,
  and existing runtime-log evidence. The deferred matrix remains an integration
  visual check, not a known Stage 8 defect.
- Final focused and full automated regression suite: `286 passed`; no known
  blocking Stage 8 defect.

Stage 9 - Server Velocity Trail Foundation Slice is the next active stage.

#### Historical implementation plan ✅

Jira: `DC-46`

Release: no separate bump. DTRS remains `0.4.0`; the next feature milestone is
`0.5.0` after Stage 10.

Status: COMPLETE / archived on 2026-08-15. The detailed Stage 8 completion
record is in [Completed Runtime Stage Plans](case%2003%20-%20completed%20runtime%20stage%20plans.md#stage-8---workload-to-cache-state-binding-slice).

#### Stage 8 implementation plan

1. ✅ **Complete (2026-08-14).** Preserve this accepted contract as the
   implementation baseline. The `0.4.0` documentation drift is resolved, the
   Stage 7 checkpoint record is retained, and `0.5.0` remains the Stage-10
   feature milestone.
2. ✅ **Complete (2026-08-14).** Airflow selection now uses a manifest-driven dataset registry
   below `assets/_external/airflow_datasets/`. Runtime identity is manifest
   `scope/state`, never a directory name. The expected server family is
   `load_idle`, `load_normal`, `load_surge`, and `load_critical`; numbered
   folders remain filesystem organisation only.
3. ✅ **Complete (2026-08-14).** Added and log the explicit config-backed mapping: `Idle -> server/load_idle`,
   `Nominal -> server/load_normal`, `Surge -> server/load_surge`, and
   `Critical -> server/load_critical`. Do not derive names with string rules
   such as `"load_" + mode.lower()`.
4. ✅ **Complete (2026-08-14).** Simulation Cache owns workload-to-airflow binding;
   Telemetry remains the owner of the semantic workload state; airflow is its
   consumer. The existing Workload selector remains the sole operator-facing
   selector.
4.5. ✅ **Complete (2026-08-14).** Extracted workload-to-airflow runtime
   coordination into `app/workload_binding/`; `RuntimeController` remains the
   public lifecycle facade, while no Flow lifecycle behaviour changes.
5. ✅ **Complete (2026-08-14).** Retired the single `server/load_normal` selector as the Attach runtime source of truth. It may remain as a Stage 6-compatible default where that
   reduces regression risk, but the active selector must derive from the
   current workload mapping. Nominal therefore preserves the existing happy
   path naturally.
6. ✅ **Complete (2026-08-14).** Added one sequential background validation
   coordinator. At launch Flow stays detached while telemetry, fans, and other
   systems work normally. It validates the current workload dataset first, then
   the remaining unvalidated family members; never runs four heavyweight VTI
   checks concurrently; reuses matching `SessionValidationCache` receipts;
   isolates failures through three bounded retry passes; and cancels
   cooperatively on extension shutdown.
7. ✅ **Complete (2026-08-14).** Give visible simulation priority during manual
   Attach through the single workload-binding validation coordinator. A matching
   active job is promoted and reused; a different background job is cancelled,
   safely requeued with its attempt preserved, then resumed after the Attach
   attempt. Attach-priority failures retry immediately within the existing
   three-attempt bound; cancelled jobs cannot store stale receipts or emit a
   false PASS.
8. ✅ **Complete (2026-08-15).** The isolated Kit-CAE hot-switch spike proved
   that an existing temporal `FieldArray.fileNames` source can be retargeted in
   place, then refreshed through `omni.cae.viz.Controller.sync_active_controller`,
   while preserving the Flow simulation, smoke state, timeline, and runtime
   objects. The temporary spike UI, one-shot state, diagnostics, and
   Normal-to-Critical special case were removed. The neutral
   `flow.temporal.retarget_kit_cae_temporal_source_in_place()` primitive retains
   session-layer authoring, readback, and active-controller refresh for Step 9.
9. ✅ **Complete (2026-08-15).** Implemented attached workload transitions as pending,
   sample-boundary, phase-preserving retargets. Validate the target, wait for
   the next VTI sample boundary, retarget the velocity source at the
   corresponding sample index, and clear the pending state. Do not detach,
   rebuild Flow, erase smoke, or restart at frame 1001 unless the spike proves
   that the local runtime requires the smallest such fallback.
10. ✅ **Complete (2026-08-15).** Truthful
    failure semantics: a failed or absent cache never rolls telemetry back;
    telemetry, fans, LEDs, and other workload consumers remain in the requested
    state; airflow remains on the previous safe dataset or detached; pending is
    cleared; and the UI status plus structured `FAILED` log report the exact
    failure. Kit acceptance remains the next runtime check.
11. ✅ **Complete (2026-08-15).** Validate the four datasets as one compatible
    simulation family from their manifests and existing preflight receipts, with
    no additional VTI scan. The check covers velocity field identity and
    PointData association, component/type structure, dimensions/grid, origin,
    spacing, bounds, equal loop duration, and valid temporal sample structure.
    Different rate, source-frame step, and sample count are allowed; normalized
    discrete phase mapping is required and interpolation remains forbidden.
12. ✅ **Complete (2026-08-15).** Pending transitions are cancellable through
    generation-based supersession: the latest workload request wins, old
    transitions cannot commit after supersession, and no Detach/Reset/rebuild
    is introduced. Focused async barrier races and the rapid
    `Surge -> Critical -> Idle` sequence are regression-covered; Kit acceptance
    remains the final runtime confirmation.
13. ✅ **Complete (2026-08-15).** `SessionValidationCache` signatures cover
    the validation contract version, resolved dataset identity, full manifest,
    ordered VTI path/size/mtime metadata, and selected velocity field. Config
    Reload resets transient runtime/transition/coordinator state without
    clearing matching receipts; changed validation inputs acquire a new
    signature automatically, while runtime-only settings preserve reuse.
    VTI change detection is deliberately filesystem-identity based
    (ordered path/size/mtime), not a runtime byte hash: the authored Houdini
    export contract treats a re-export as a metadata-changing operation. A
    future strict byte-level guarantee belongs in an export-authored manifest
    dataset digest, not in startup-time hashing of multi-GiB VTI assets.
14. ✅ **Complete (2026-08-15).** Focused Stage 8 coverage reuses the Stage 6/7
    suites and proves four semantic states, mapping/discovery, invalid data,
    detached changes, validation arbitration, receipt/cache reload semantics,
    normalized phase mapping, truthful failure, and latest-request-wins races.
    Added playback-intent boundaries prove that paused transitions wait without
    altering playback and cannot resume after supersession; playing transitions
    do not introduce an artificial pause.
15. ✅ **Implementation/testing prerequisites DONE (2026-08-15).** Conduct Kit
    acceptance as a runtime transition matrix. For each workload, prove workload
    -> telemetry -> fans -> manifest -> VTI sequence -> Flow; then cover ordered
    transitions, Play/Pause, detached changes, missing cache, rapid changes,
    validation plus Attach, config reload, and combined Flow plus X-Ray. Check
    explicitly for stale emitters, callbacks, and temporal jobs. Manual Kit
    acceptance remains outstanding.


##### Step 15 — Kit runtime transition acceptance checklist (prepared 2026-08-15)

Run in one DTRS process. Record only actual defects.

| Section | Operator action | Required evidence |
|---|---|---|
| Per-workload chain | For each `Idle`, `Nominal`, `Surge`, `Critical`, select workload detached, Attach, Play, then Detach. | Telemetry and fan/RPM UI agree; mapping and Attach-selector logs name the matching `server/load_*`; active selector and live VTI family agree. |
| Ordered transitions | `Idle -> Nominal -> Surge -> Critical`, then reverse. | One `REQUEST -> READY -> RETARGET -> CONSUMED -> COMMIT`; pending cleared, target family live, runtime contract match, zero resets. |
| Playback | Transition Playing; Pause and request target; Resume; change workload detached. | Playing remains Playing; no paused retarget before Resume; Detached never auto-Attaches. |
| Validation/cache/reload | Observe startup, cached Attach, natural MISS if encountered, then Config Reload. | Sequential validation, cached `Preflight: REUSED`, normal MISS validation, reload retains matching receipts. |
| Rapid requests | Attached + Playing: `Surge -> Critical -> Idle`. | Earlier transitions `SUPERSEDED`; only Idle commits; no late stale commit. |
| Flow + X-Ray | Attach, enable/toggle X-Ray, transition workload. | Flow remains attached, target family commits, X-Ray lifecycle is clean, no reset/rebuild evidence. |

After each section inspect `/DTRS_KitCAE`: exactly one current
`DataSetEmitter` and `FlowSimulation` while attached, neither after Detach.
Duplicate lifecycle/proof output, a non-empty terminal pending selector, or
validation work surviving shutdown/reload are defects.

16. ✅ **Complete (2026-08-15).** Existing Kit logs provide sufficient latency
    evidence; no new benchmark was run. Cached workload `REQUEST -> COMMIT`
    measured approximately `0.98–1.63 s` (typically `1.1–1.3 s`); cached
    `READY -> RETARGET` waited roughly `50–63 ms` for the next boundary on the
    recorded 5 Hz datasets. Cached Attach with a background-validation receipt
    took approximately `4.0 s` from `PRE_ATTACH` to `FLOW_ATTACHED`: preflight
    was `REUSED`/HIT/`0 ms`, while initial VTI import was about `250 ms`,
    temporal USD authoring about `656 ms`, and initial Flow readiness about
    `2.98 s`. Background preflight ran outside the interactive path at roughly
    `38–42 s` per dataset. No dedicated timing was collected for unvalidated
    interactive switching or Attach without a receipt; those paths remain
    functionally covered by Stage 8 tests. The observed cached runtime latency
    is responsive enough for the DTRS showcase, so no latency-driven
    architecture change or optimisation is required.
17. ✅ **Complete (2026-08-15).** The public claim is supported by the recorded
    implementation, focused regressions, and existing Kit runtime evidence:
    "The same workload state drives telemetry, hardware behaviour, and
    selection of the corresponding Houdini-authored temporal airflow dataset,
    with manifest-driven validation and phase-preserving runtime switching."
    Stage 8 closure is recorded in the completed-stage archive; `DC-46` is
    Done; Stage 9 is the next active slice. The Step 15 visual matrix remains
    deferred to Stage 9 as additional integration evidence, not a Stage 8
    blocking defect.

##### Stage 08 — Workload-to-Cache Binding Contract

**Jira:** `DC-46`

**Purpose:** Bind the existing semantic workload state to real Houdini-authored
temporal VTI airflow datasets without creating a second workload model or
breaking the Stage 6 Flow lifecycle.

1. **Single workload source.** `Idle`, `Nominal`, `Surge`, and `Critical`
   remain Telemetry-owned semantic state. The Telemetry UI changes that state;
   it is not a second Flow owner. Stage 8 adds no Airflow Mode, percentage
   selector, or persisted Flow-only workload state.
2. **Manifest identity.** Datasets below `assets/_external/airflow_datasets`
   are found by manifest `(scope, state)`, never directory name. The explicit
   mapping is `Idle -> server/load_idle`, `Nominal -> server/load_normal`,
   `Surge -> server/load_surge`, and `Critical -> server/load_critical`; it is
   never derived by string construction.
3. **Telemetry/Flow independence.** A workload request changes telemetry,
   fans, LEDs, and other workload consumers even when the corresponding Flow
   dataset is absent or invalid. Flow is an asynchronous visual consumer.
4. **Truthful failure.** Failure retains the last safe attached airflow where
   possible, or Detached state otherwise; it never rolls telemetry back. UI and
   logs expose requested workload, active airflow, exact reason, and cleared
   pending state.
5. **Startup/background validation.** Flow starts Detached. One sequential
   worker preflights current workload first, then the remaining datasets; it
   never constructs active Flow and does not run heavyweight VTI checks in
   parallel.
6. **Attach priority.** Manual Attach promotes or reuses validation for the
   matching target, otherwise safely pre-empts/requeues background work without
   consuming an attempt, then resumes it after Attach.
7. **Session receipts.** Successful plain-data preflight receipts are reusable
   within a process. Their signature covers validation contract, selector,
   full manifest, selected field, and ordered VTI filesystem identity.
8. **Config Reload.** Reload resets transient runtime/transition/coordinator
   state but preserves a receipt when its signature still matches; changed
   validation inputs naturally make old receipts inapplicable.
9. **Family compatibility.** Hot switching requires compatible velocity-field
   structure, grid/dimensions, origin, spacing, bounds/coordinate contract,
   equal loop duration, and valid temporal metadata. Different sample rates
   and counts are allowed; interpolation is forbidden.
10. **Phase-preserving switching.** Attached workload change validates target,
    waits for a sample boundary, maps normalized discrete phase to target, and
    retargets in place. Existing smoke, Flow runtime, and playback intent are
    preserved where supported; no Detach/Attach/rebuild/reset fallback is
    introduced without a proven runtime limitation.
11. **Live proof.** Background preflight is not live Flow proof. Commit occurs
    only after target source consumption, payload/operator update, direct-Attach
    runtime-contract match including velocityScale, zero resets, and timeline
    continuity.
12. **Cancellable transitions.** Latest workload request wins. A superseded
    generation cannot commit after validation, boundary, retarget, consumption,
    or any terminal state mutation.
13. **Non-goals.** No parallel workload model, four concurrent simulations,
    velocity blending/interpolation, predictive CFD, Stage 7 lifecycle change,
    heavyweight VTI assets in Git, or speculative optimisation.

**Done criteria:** the four explicit manifest-backed mappings, independent
telemetry, cached validation, safe Attach priority, truthful failure, compatible
phase-preserving transition, supersession, Config Reload semantics, and Stage
6/7 regression safety are all implemented and covered by runtime evidence and
focused tests.




### Stage 9 - Server Velocity Trail Foundation Slice

Jira: `DC-49`

**Status:** ✅ Complete / PASS-CLOSED
**Completed:** 2026-08-20
**Target release milestone:** `0.5.0` after Stage 10 completion; Stage 9 does not
produce a separate public version bump.

Stage 9 adds the production server-scale Streamlines path to Digital Twin
Runtime Suite.

The stage started as a bounded Kit-CAE feasibility investigation and finished as
a reusable cached visualization subsystem integrated with workload state,
Visualization Mode, X-Ray, production material presentation, lifecycle cleanup,
and normal DTRS UI.

The final feature visualizes the existing Houdini-authored airflow velocity
field. Streamlines are instantaneous integral curves of the selected velocity
state; they are not particles, pathlines, interpolated simulation states, or a
second smoke simulation.

The authoritative data chain remains:

```text
Telemetry Workload
-> Airflow Dataset Registry
-> authoritative manifest-backed AirflowDataset
-> Houdini-authored VTI velocity field
-> Flow / Smoke consumer
   or
-> derived Streamlines cache
-> static BasisCurves snapshots
-> cached presentation
```

Houdini-authored VTI remains authoritative simulation data. Streamlines caches
are derived visualization artifacts.

The preferred production Streamlines path performs no runtime VTI import,
Kit-CAE Streamlines execution, RuntimePreview rebuild, or geometry recomputation
solely to present already-valid cached Streamlines.

`/app/useFabricSceneDelegate = false` remains part of the accepted runtime
configuration because the tested Fabric Scene Delegate path breaks Engineering
X-Ray viewport rollback in this application.

---

#### Phase 1 - Static source and Kit-CAE operator proof ✅

The first proof established that one manifest-selected Houdini VTI sample can be
validated, imported with the existing spatial-registration contract, and
consumed directly by Kit-CAE Streamlines without creating Flow, smoke emitters,
or a temporal simulation.

The implementation uses the installed Kit-CAE API:

```python
from omni.cae.data.commands import execute_command
from omni.cae.schema import viz as cae_viz
```

A DTRS-owned seed source is related to the Kit-CAE Streamlines operator and the
configured velocity field is consumed directly.

A controlled `standard` versus `nanovdb` comparison selected `standard` as the
sole production Streamlines operator:

| Evidence | Standard | NanoVDB |
| :--- | ---: | ---: |
| Median rebuild | 63 ms | 94 ms |
| Steady FPS median | 49.8 | 48.9 |
| GPU memory | 4.0 GiB | 4.1 GiB |
| Geometry | 256 curves / 51,200 points | 256 curves / 51,200 points |

No material visual-quality or stability advantage justified retaining NanoVDB
in production.

Canonical cleanup was also proven across rerun, deterministic failure rollback,
configuration reload, stage reopen, shutdown, restart, and repeated cleanup.
Accepted lifecycle evidence included zero stale relationships, remaining layer
specs, duplicate prims, and pending tasks.

**Phase 1 result:** a validated Houdini VTI can produce correctly registered
server-scale Kit-CAE Streamlines through a clean, idempotent DTRS-owned runtime
path.

---

#### Phase 2 - Temporal feasibility and runtime-recompute fallback ✅

Phase 2 measured whether the Kit-CAE Streamlines consumer could be rebuilt
directly at the source dataset cadence.

The representative Nominal dataset contained 80 real manifest samples at 5 Hz.
Exact source selection and final-to-first loop mapping worked correctly, but
explicit Streamlines consumer reconstruction was far too expensive for
production 5 Hz presentation.

Representative measured evidence:

```text
source cadence                 5 Hz / 200 ms
median operator rebuild        1204 ms
median total visible update    2547 ms
5 Hz deadlines missed          10 / 10
maximum queue depth            8
sustained FPS median           7.0
```

A bounded time-based scheduler subsequently established a viable explicit
runtime-recompute fallback:

```text
presentation period            2.6 s
presentation cadence           0.384615 Hz
missed deadlines               0
max pending requests           0
loop wrap                      PASS
exact source mapping           PASS
same-source sample             NO_OP
interpolation                  NONE
cleanup                        CLEAN
```

The source clock and presentation clock were therefore separated.

At every presentation point the resolver selects:

```text
current normalized loop phase
-> latest real manifest sample at-or-before that phase
```

No interpolation, averaging, or synthetic velocity states are created.

**Phase 2 result:** direct runtime recomputation is functionally correct but too
expensive for the preferred production path. The accepted `2.6 s` recompute
route remains an explicit fallback, not the normal presentation scheduler.

---

#### Phase 2.5 - Precomputed Streamlines cache feasibility ✅

Phase 2.5 established Streamlines cache semantics.

The authoritative VTI dataset and derived Streamlines cache remain distinct.
Each cached state preserves the identity of the real source manifest sample,
including workload, dataset, source VTI, source time, timecode, Streamlines
settings, and generated geometry.

Early cached playback was substantially cheaper than runtime recomputation but
still did not initially sustain full 5 Hz presentation:

| Diagnostic cache | Median visible switch |
| :--- | ---: |
| 256 curves | 891 ms |
| 128 curves | 469 ms |

Further density reduction was rejected because the predicted geometry required
for 200 ms switching would materially damage Streamlines readability.

The important architectural result was therefore retained even though this
early renderer path missed the 5 Hz objective:

```text
authoritative VTI
-> offline / explicit Kit-CAE generation
-> persisted derived Streamlines cache
-> runtime cached presentation
```

Cache failure never authorizes automatic rebuild or silent runtime recomputation.

**Phase 2.5 result:** precomputed caches became the preferred production
direction; the Phase 2 runtime-recompute route remained the explicit fallback.

---

#### Phase 2.75 - Streamlines runtime decomposition ✅

After the surviving architecture was known, the Streamlines runtime was
decomposed by actual responsibility rather than by speculative module symmetry.

Cache construction, cache validation, temporal resolution, runtime presentation,
Kit-CAE ownership, cleanup, and the explicit recompute fallback were separated
behind the public `RuntimeController` facade.

The rejected full-5-Hz experimental harness was removed from the shipping
runtime while the accepted fallback and lifecycle contracts remained
executable.

**Phase 2.75 result:** production cache ownership and explicit recompute fallback
became separate readable runtime responsibilities before shared airflow-state
integration began.

---

#### Phase 3 - Production Streamlines cache architecture ✅

Phase 3 converted the feasibility work into the production Streamlines data and
runtime contract.

It established three deliberately independent concepts:

```text
authoritative source timeline
derived Streamlines cache
runtime presentation timeline
```

Source cadence does not determine cache identity, and presentation cadence does
not determine cache contents.

##### 3.1 - Authoritative dataset and full-manifest cache fidelity ✅

The existing Airflow Dataset Registry remains the only owner of
`manifest.toml` discovery and parsing.

Streamlines consumes resolved `AirflowDataset` objects rather than discovering
or interpreting dataset directories independently.

For every real authoritative manifest sample, a valid cache contains exactly one
corresponding derived Streamlines state.

Production logic is not tied to the current `80 samples / 5 Hz / 0.2 s`
dataset shape.

Cache validation distinguishes source identity, manifest timing, schema, and
geometry-affecting Streamlines settings. Presentation-only configuration is
excluded from cache identity.

##### 3.2 - Production cached playback and presentation cadence ✅

Production cached playback resolves directly from the current logical phase:

```text
normalized phase
-> latest real cached source state at-or-before phase
-> same state = NO_OP
-> otherwise present selected cached state
```

The accepted production presentation period is:

```text
200 ms / 5 Hz
```

Accepted representative evidence for the production cached path included:

```text
median cached switch       16 ms
maximum cached switch      78 ms
missed deadlines           0
backlog                    0
minimum FPS                41.9
loop wrap                  PASS
runtime Kit-CAE            0
RuntimePreview rebuilds    0
VTI presentation imports   0
```

Changing the presentation period does not invalidate a cache.

##### 3.3 - Consumer-neutral airflow state ✅

Workload and logical temporal state were moved behind a consumer-neutral airflow
owner.

Flow and Streamlines consume the same logical state through different runtime
paths:

```text
shared logical airflow state
├─> temporal VTI -> RTX Flow / Smoke
└─> validated Streamlines cache -> cached Streamlines presentation
```

A live imported VTI prim is therefore not itself the authoritative airflow
state.

Existing Flow Attach, Detach, workload switching, supersession, rollback, and
logical phase behaviour remained intact after the ownership change.

##### 3.4 - Workload-aware Streamlines cache ownership ✅

Streamlines cache identity was generalized from the initial Nominal-only proof
to workload/dataset-aware ownership.

The production workload set is:

- Idle;
- Nominal;
- Surge;
- Critical.

Expected cache artifacts can be classified without building them as:

- `VALID`;
- `MISSING`;
- `STALE`;
- `INCOMPATIBLE`.

Startup and normal cache discovery never trigger an expensive rebuild
automatically.

##### 3.5 - Production cache generation contract ✅

The production cache contract persists:

- exact source-sample identity;
- real source timing and timecode;
- Streamlines geometry;
- geometry-affecting settings identity;
- raw per-vertex `primvars:dtrs:speed`.

Missing or stale workload caches remain explicit maintenance conditions rather
than runtime recompute triggers.

##### 3.6 - Final Phase 3 architecture gate ✅

The final Phase 3 acceptance proved:

- one authoritative manifest-backed dataset system;
- derived workload-owned Streamlines caches;
- exact source-state preservation;
- independent source/cache/presentation timing;
- cache-independent presentation configuration;
- explicit-only runtime recompute fallback;
- no runtime Kit-CAE or VTI work in preferred cached presentation;
- idempotent cleanup;
- no regression to Flow Attach or workload transitions.

The temporary Phase 3 acceptance workflows were retired after the gate passed.

---

#### Phase 4 - Production modes and presentation ✅

Phase 4 integrated the accepted Streamlines architecture into ordinary DTRS
operation.

Streamlines ceased to be a diagnostic subsystem and became a normal production
Visualization Mode over the same logical airflow state used by Smoke.

##### 4.1 - Transactional Visualization Mode state ✅

Visualization Mode became explicit DTRS application state rather than a UI-only
selection.

Mode transitions preserve:

- workload identity;
- dataset identity;
- normalized logical airflow phase.

The previous valid presentation remains committed until the requested
replacement proves readiness.

A failed or superseded transition cannot silently commit stale work.

A significant Normal-mode regression was discovered during this phase:
approximately 1 Hz UI readiness polling was strongly validating and hashing a
large Streamlines `.usdc` artifact synchronously on the Kit main thread.

Observed Normal performance fell from the earlier baseline to approximately
`36.6 avg / 30.9 min FPS`.

Strong cache provenance validation was moved to a deduplicated background
receipt owner, while the UI became a cheap projection of validation state.

Manual post-repair Normal validation recovered to approximately 85 FPS with
smooth fan animation and no recurring readiness stalls.

##### 4.2 - Smoke <-> Streamlines transactions and rollback ✅

Smoke and Streamlines became transactional presentation consumers over shared
airflow state.

Preferred Streamlines activation performs:

```text
cache build                0
runtime Kit-CAE            0
RuntimePreview rebuild     0
VTI presentation import    0
```

Returning to Smoke reuses an already-valid Flow source where possible and
reconstructs it only when genuinely required.

Failed transitions preserve or restore the previously proven presentation
rather than leaving the viewport blank or silently changing workload state.

##### Pre-4.3 - Peer Visualization Mode activation ✅

Normal, Smoke, Streamlines, and the existing Heatmap/X-Ray preview were made
independent peer presentation choices.

In particular, direct:

```text
Normal -> Streamlines
```

works without first constructing or attaching Flow.

The source mode now provides cleanup and rollback context only; it is not an
activation prerequisite for a healthy target mode.

##### 4.3 - Workload-aware Streamlines runtime ✅

While Streamlines is active, workload selection resolves the matching persisted
cache directly.

The accepted workload transition path is:

```text
requested workload
-> authoritative AirflowDataset
-> expected workload/profile cache
-> require VALID cache
-> preserve shared logical airflow phase
-> resolve target real cached state
-> prepare and prove target presentation
-> commit workload
```

No Streamlines workload change requires Flow Attach, VTI import, cache build, or
runtime Kit-CAE execution.

The production sequence:

```text
Nominal -> Idle -> Surge -> Critical -> Nominal
```

passed with exact workload/cache identity, phase-preserving selection, one
visible presentation, one scheduler, and clean return to Normal.

---

##### 4.4 - Final production Streamlines presentation ✅

Phase 4.4 froze the production geometry, solved the renderer-specific temporal
presentation problem, introduced velocity-driven material styling, proved X-Ray
coexistence, and removed obsolete Stage 9 diagnostic interaction from the
normal product UI.

###### 4.4.0 - Final production geometry profiles ✅

Two production profiles were retained because they communicate different useful
views of the same physical source data.

| Profile | Production settings |
| :--- | :--- |
| **Volume Coverage** | 24 sections × 256 seeds = 6144 curves; Max Steps 20; Cell Step Scale `1.0x`; effective DAV `0.01 / 0.2 / 0.5` |
| **Global Flow Path** | 256 front-intake seeds; Max Steps 200; Cell Step Scale `2.0x`; effective DAV `0.02 / 0.4 / 1.0` |

Both profiles use the accepted standard Kit-CAE operator and the same
authoritative VTI source contract.

Volume Coverage is the clean-session default; Global Flow Path provides a
longer intake-to-exhaust engineering read.

Cache ownership therefore became:

```text
4 workloads × 2 profiles = 8 production caches
```

A full production-cache matrix exposed an important validation gap: seven newly
built caches were structurally valid but temporally degenerate, while the
previously proven Nominal / Volume Coverage cache contained real temporal
variation.

The defect was traced to cache generation: the disposable Kit-CAE Streamlines
operator was not explicitly locked to each selected manifest time context
before execution.

The generator was corrected and temporal-liveness validation was added so a
structurally valid but temporally static cache cannot be accepted as
matrix-ready.

The defective seven caches were rebuilt; the already-good Nominal / Volume
Coverage cache was retained.

The final 8/8 cache matrix passed technical and explicit manual viewport
acceptance for both profile directions and all workloads.

###### 4.4B - Renderer temporal playback investigation ✅

The persisted caches contained real temporal Streamlines variation, but the
initially expected USD renderer route did not display internal time-sampled
geometry deformation reliably in the installed Kit/RTX stack.

The investigation separated cache correctness from renderer behaviour.

Rejected approaches included:

1. variable-topology time-sampled `BasisCurves` — RTX topology/point-count
   failures and corrupted geometry;
2. constant-topology time-sampled `BasisCurves.points` — correct changing source
   hashes but visually static/flickering output;
3. explicit per-tick Python point updates — prohibitively slow and capable of
   triggering RTX Device Lost;
4. prebaked time-sampled tube `UsdGeomMesh` — correct source variation but
   visually static deformation;
5. transform and real-curve A/B probes — proved that renderer transform updates
   worked and that consecutive cached Streamlines genuinely had different
   shapes.

The decisive experiment materialized every temporal state as immutable static
`BasisCurves` and switched only visibility.

Two-state, ten-state, and complete full-density loop tests all succeeded.

The accepted production renderer representation is:

```text
VALID persisted Streamlines cache
-> one immutable static BasisCurves snapshot per real manifest state
-> CachedPlaybackScheduler resolves the current real state
-> exactly one snapshot visible
-> temporal playback by visibility-only switching
```

This is strictly a renderer-presentation workaround.

It does not change Streamlines semantics and performs no interpolation, synthetic
state generation, Mesh conversion, runtime Streamlines recomputation, VTI
presentation import, or per-tick point-array copying.

The current Nominal / Volume Coverage 80-state production instance passed the
complete 5 Hz loop including `79 -> 0` wrap, one scheduler, one visible snapshot,
zero backlog, clean Normal teardown, and clean re-entry.

###### 4.4.1 - Production velocity presentation ✅

Persisted:

```text
primvars:dtrs:speed
```

is the production velocity-presentation source.

The value is preserved on every static runtime snapshot and is consumed without
returning to VTI or recomputing Streamlines.

One shared physical presentation scale is used across all workloads and both
profiles. Individual workloads, profiles, and frames are never normalized to
their own dynamic min/max.

The accepted production scale is derived from persisted **Volume Coverage**
evidence across the four workloads using the final p05/p95 contract. Global
Flow Path does not own a separate scale.

The accepted validation run produced:

```text
speed_min = p05 = 0.0404622073
speed_max = p95 = 0.55668432
units     = source velocity units
```

These values are evidence for the accepted cache set rather than architecture
constants: a successful production cache-set Build / Validate action recalculates
the shared range from persisted Volume Coverage evidence and stores the accepted
presentation values in the local runtime override.

Values outside the accepted range clamp rather than dynamically rescaling the
palette.

The production palette is:

```text
low speed
deep blue-violet
-> cyan / blue
-> green
-> yellow / orange
-> red
high speed
```

The same physical `dtrs:speed` therefore retains the same colour meaning when
workload, profile, or temporal state changes.

The production material also exposes presentation-only:

- Opacity;
- Emission;
- Lighting Influence.

`Apply Material Settings` applies the active material and persists the latest
successful values to the local runtime override.

Material changes do not affect cache identity, cache validity, snapshot
geometry, playback cadence, or scheduler ownership.

Manual velocity-presentation acceptance passed for:

- Idle / Volume Coverage;
- Nominal / Volume Coverage;
- Surge / Volume Coverage;
- Critical / Volume Coverage;
- Critical / Global Flow Path.

The gate required explicit human confirmation that velocity colour was actually
readable in the viewport; backend hashes or material state alone were not
treated as visual evidence.

The temporary `PHASE_4_4B_VELOCITY_PRESENTATION` acceptance workflow was retired
after the pass.

###### 4.4.2 - Presentation ownership ✅

The final Streamlines subsystem preserves a strict ownership boundary:

| Owner | Responsibility |
| :--- | :--- |
| `speed.py` | Raw persisted speed identity and validation |
| `speed_distribution.py` | Persisted statistical/scale evidence |
| `presentation.py` | Pure physical-speed-to-visual mapping |
| `snapshot_runtime.py` | Static snapshot geometry and persisted speed preservation |
| `presentation_runtime.py` | Kit/USD/MDL material state |
| cache owners | Cache identity, construction and validation |
| playback owners | Cached-state scheduling and selection |
| workload/profile transition owners | Transactional presentation switching |
| `runtime.py` | Thin composition facade |

Palette and material policy do not leak into cache generation, playback
scheduling, or workload state machines.

Presentation-only changes cannot alter persisted cache identity or trigger
recomputation.

###### 4.4.3 - Streamlines + X-Ray coexistence ✅

X-Ray remains an independently owned presentation system.

`Streamlines + X-Ray` is supported as a dedicated combined visualization state
without merging the two lifecycle owners.

Accepted behaviour includes:

- Streamlines playback continues while X-Ray is active;
- X-Ray does not reset logical airflow phase;
- one Streamlines scheduler remains active;
- workload switching preserves the active X-Ray state;
- Streamlines cleanup does not remove X-Ray-owned bindings;
- X-Ray cleanup does not remove Streamlines geometry/material state;
- repeated mode changes do not accumulate presentation ownership.

The final mixed-mode DTRS run also confirmed successful transitions among
Streamlines, Streamlines + X-Ray, Smoke, Heatmap preview, and Normal with clean
lifecycle handoff.

On the reference RTX 3080, sustained Streamlines + X-Ray operation in the final
manual run settled around approximately 25–26 FPS after transition
initialization.

###### 4.4.4 - Production Stage 9 UI ✅

Streamlines is presented as an ordinary production visualization mode rather
than a development subsystem.

Normal controls expose only the product-relevant state:

- visualization selection;
- workload;
- Streamlines profile;
- material presentation settings;
- concise transition/error status.

Explicit cache Build / Validate and validation-receipt controls remain
intentional developer/maintenance tooling.

Obsolete feasibility probes, benchmarks, cache sanity controls, and completed
Stage/Phase acceptance controls were removed from normal operation.

Normal production diagnostics remain enabled, including:

- Dataset Registry discovery;
- Workload Cache Mapping;
- background Airflow validation;
- Streamlines cache validation/reuse;
- runtime transition failures.

Removing temporary Stage 9 acceptance output did not suppress these production
diagnostics.

###### 4.4.5-4.4.6 - Focused verification and real Kit acceptance ✅

Focused tests cover:

- workload-independent physical velocity mapping;
- deterministic clamping;
- malformed persisted speed rejection;
- cache/presentation independence;
- workload/profile continuity;
- one-scheduler ownership;
- X-Ray isolation;
- repeated lifecycle cleanup;
- stale asynchronous work losing commit authority.

Renderer-visible behaviour was additionally accepted through real DTRS manual
validation.

The temporary cache-matrix, velocity-presentation, and other Phase 4.4 guided
acceptance workflows were retired after their respective gates passed.

**Phase 4.4 result:** DTRS has final server-scale Streamlines geometry, an
accepted cached snapshot renderer path, shared velocity-driven presentation,
two production profiles, eight independently validated production caches,
X-Ray coexistence, and normal product UI.

---

##### 4.5 - Production acceptance matrix ✅

The final production acceptance exercised the complete user-facing architecture
rather than earlier feasibility harnesses.

Accepted behaviour covered:

```text
Attach
-> Smoke
-> Streamlines
-> workload changes
-> Streamlines + X-Ray
-> logical loop behaviour
-> repeated primary-mode changes
-> Smoke
-> Streamlines
-> Normal / Detach cleanup
```

Across the accepted routes:

- one authoritative workload and logical airflow state remained in control;
- preferred Streamlines presentation performed zero runtime Kit-CAE execution;
- no VTI import occurred solely for Streamlines presentation;
- no automatic Streamlines cache rebuild occurred;
- workload selection remained phase-based rather than index-based;
- one Streamlines scheduler remained active while Streamlines owned presentation;
- returning to other modes removed Streamlines scheduler ownership cleanly;
- X-Ray bindings were applied and removed independently;
- Flow could be reconstructed when genuinely required for Smoke;
- repeated mixed-mode cycles did not accumulate stale presentation state.

The final runtime smoke/X-Ray/Streamlines regression completed cleanly on the
reference RTX 3080.

**Phase 4.5 result:** the Stage 9 architecture behaves as a production runtime
interaction rather than as a collection of independent development proofs.

---

##### 4.6 - Code readability and Stage 9 closure ✅

The final readability pass removed obsolete Stage 9 experimental and acceptance
surfaces rather than performing another broad refactor.

A first-time technical reader should be able to identify these ownership
boundaries directly from the repository:

```text
Airflow Dataset Registry
    -> authoritative AirflowDataset

Shared logical airflow state
    -> workload + normalized phase

Flow
    -> authoritative VTI
    -> RTX Flow / Smoke

Streamlines cache
    -> derived persisted geometry + dtrs:speed

Snapshot runtime
    -> immutable static BasisCurves states

CachedPlaybackScheduler
    -> exact cached-state selection
    -> visibility-only playback

Presentation runtime
    -> shared velocity material

X-Ray runtime
    -> independent presentation overlay
```

`extension.py` remains a lifecycle/composition root rather than accumulating
feature-specific Streamlines orchestration.

Normal airflow diagnostics remain enabled after removal of obsolete Stage 9
acceptance/debug output.

**Phase 4 / Stage 9 gate: PASS.**

---

#### Final Stage 9 production contract

The completed production Streamlines architecture is:

```text
Houdini-authored manifest-backed VTI
            |
            +-> Flow consumer -> Smoke
            |
            +-> explicit Kit-CAE cache generation
                    |
                    v
            workload/profile Streamlines cache
                    |
                    v
            immutable static BasisCurves snapshots
                    |
                    v
            CachedPlaybackScheduler @ accepted 200 ms
                    |
                    +-> persisted dtrs:speed
                    |       |
                    |       v
                    |   shared velocity material
                    |
                    +-> optional independent X-Ray overlay
```

Production invariants:

- Houdini VTI remains authoritative simulation data.
- Streamlines caches remain derived visualization data.
- Every real source state represented by a cache remains tied to its exact
  manifest identity.
- Cached presentation never invents intermediate velocity states.
- Preferred playback performs no runtime Streamlines recomputation.
- Cache failure never silently triggers rebuild or fallback.
- Workload and Visualization Mode remain independent state dimensions.
- Workload/profile transitions preserve one shared physical velocity-presentation
  contract.
- Streamlines and X-Ray retain separate lifecycle ownership.
- Presentation settings do not affect cache identity.
- Cleanup remains idempotent across mode switching, Normal, Detach, reload, and
  shutdown.

The explicit `2.6 s` runtime-recompute path remains available as a proven
fallback but is not the preferred production presentation path.

---

#### Deliberate limitations and non-claims

Stage 9 does **not** claim:

- validated engineering CFD;
- live sensor-driven airflow physics;
- runtime Kit-CAE Streamlines recomputation during preferred playback;
- interpolated or synthetic velocity states;
- particle/pathline simulation;
- Rack- or Data-Hall-scale Streamlines.

The current airflow is a presentation-oriented visualization derived from the
authored Houdini velocity fields.

Stage 10 supersedes the former Heatmap preview with the accepted production
thermal presentation contract.

Higher sample-count snapshot residency remains a future characterization topic,
not a reopened Stage 9 requirement.

Animated Streaks were deliberately excluded from the Stage 9 completion
contract because the accepted geometry, temporal snapshot playback, and
velocity colour presentation already provide the required directional and
magnitude readability.

---

#### Completion statement

Stage 9 is complete when DTRS can:

```text
use one authoritative manifest-backed airflow state
-> present Smoke
-> switch directly to validated cached Streamlines
-> select Idle / Nominal / Surge / Critical
-> select Volume Coverage / Global Flow Path
-> preserve logical temporal phase
-> visualize persisted physical speed consistently
-> combine Streamlines with X-Ray
-> return to another visualization mode
-> clean owned runtime state
```

without hidden Streamlines recomputation, automatic cache rebuild, VTI import
solely for cached presentation, workload-state corruption, duplicate scheduler
ownership, or presentation lifecycle accumulation.

**Status: ✅ PASS/CLOSED.**

## Stage 10 - Production Heatmaps

**Status:** PASS/CLOSED
**Completed:** 2026-08-23
**Release:** `0.5.0`

Stage 10 delivers the single-server Heatmap production presentation. Applied
settings preserve the authored thermal metadata and calibration contract;
dynamic telemetry updates use the named runtime texture rather than periodic
USD material mutation. Heatmap owns selected geometry while X-Ray excludes
only conflicting shroud/blower targets, preserving unrelated GPU geometry and
manual X-Ray selection.

Manual Kit acceptance on the reference RTX 3080 passed visual Heatmap/X-Ray
composition, Nominal/Surge/Critical workload response, per-GPU Housing
precedence, mode handoffs, and stable interactive performance without periodic
fan stalls or resource accumulation.

## Cancelled Runtime Features

### Camera-aware chassis Auto fade

Cancelled after Stage 7 validation. The former Stage 17 proposal would have
made chassis presentation camera-dependent through automatic opacity fading.
The production Custom MDL Fresnel X-Ray material provides the intended
inspectability more elegantly while preserving the established ownership
boundary: X-Ray changes material bindings only, and Server Enclosure remains
the sole owner of chassis visibility.

`Open` and `Closed` chassis-presentation visibility controls remain a separate
future Stage 17 concern. Auto fade is not a future requirement and must not be
reintroduced as part of X-Ray or camera-navigation work.


### Stage 10 - Server Heatmap Slice

Checkpoint preflight: before implementation, verify that Stage 9 ends at a
clean Git checkpoint commit. If it does not, create that checkpoint first.

Jira: `DC-50`

Release track: `0.5.0` (released on Stage 10 completion).


Prove a reusable telemetry-driven Heatmap against the full server at
single-server detail level before adding rack or data-hall scale.

Preparatory package structure has already been created to reserve the Heatmap
subsystem boundary before implementation begins.

Prepared runtime package:

`src/digital_twin_runtime_suite/app/heatmaps/`

- `__init__.py`
- `bindings.py`
- `diagnostics.py`
- `discovery.py`
- `material.py`
- `runtime.py`
- `scalar.py`

Prepared test package:

`tests/heatmaps/`

- `test_heatmap_bindings.py`
- `test_heatmap_discovery.py`
- `test_heatmap_runtime.py`
- `test_heatmap_scalar.py`

These files currently contain package/module placeholders and responsibility
descriptions only. They do not constitute Stage 10 implementation and may be
refined as the runtime architecture is proven. `__init__.py` is intentionally
left without a predefined public API.


#### Thermal contract

Use the thermal metadata already authored in Houdini and transported through
USD:

- `thermal_zone` - semantic thermal region;
- `thermal_component` - component role inside that region;
- `primvars:thermal_weight` - dimensionless authored spatial distribution from
  relatively colder to hotter areas;
- `primvars:temperature_preview` - optional Houdini authoring/debug data only.

`thermal_weight` is not temperature and must never be interpreted as degrees
Celsius. Runtime thermal values come from the existing DTRS telemetry
provider. Heatmap combines documented telemetry with the authored
`thermal_weight` distribution to produce the visual result.

Only documented telemetry may drive Heatmap regions. Missing measurements must
remain unavailable rather than being invented. Preserve the existing telemetry
quality semantics (`measured`, `estimated`, `derived`, `synthetic`, `stale`,
`unavailable`).

Stage 10 uses one documented absolute temperature scale in degrees Celsius for
the complete server. The same temperature must always map to the same colour,
regardless of workload, component family, or thermal zone. Do not apply
per-workload, per-component, or per-region normalization to this Celsius
scalar.

Heatmap temperatures are a derived spatial interpolation, not a claim that
each rendered vertex has a physical temperature sensor. Runtime normalises the
observed authored weights across each discovered asset/zone/component group to
`[0, 1]`; it then calculates:

```text
delta_min_celsius = -Delta
delta_max_celsius = +Delta

display_temperature_celsius = component_telemetry_celsius
    + TemperatureOffset
    + lerp(
        delta_min_celsius,
        delta_max_celsius,
        normalized_thermal_weight
      )
```

`component_telemetry_celsius` is the source temperature for the exact telemetry
identity, such as GPU 1. Delta and Temperature Offset are persisted by
asset/zone/component and are independent of workload. A normalized weight of
`0` resolves to the lower delta endpoint; `1` resolves to the upper endpoint.
The derived display temperature then uses the one server-wide Celsius scale
above. `scalar.py` owns this Celsius calculation; `palette.py` owns clamping,
active stops, and colour interpolation.

The input telemetry quality remains visible. The resulting field must be
described in the UI, legend, and diagnostics as a derived spatial
interpolation from component telemetry and Houdini-authored thermal metadata,
never as direct per-part measurement.

Phase 10.3 provides one settings-driven Heatmap harness, initially OFF. Its
Test/Restore controls own only Heatmap Session opinions. Reload returns the
normal scene and repopulates persisted Heatmap settings; production lifecycle
composition and X-Ray precedence remain deliberately deferred to Phase 10.4.

Rack and data-hall Heatmap behavior is outside Stage 10.


### Implementation sequence

#### Phase 10.0 - Asset preflight ✅

- inspect the production server USD used by DTRS;
- verify `thermal_zone`, `thermal_component`, `thermal_weight`, and optional
  `temperature_preview`;
- verify `thermal_weight` range and usable USD interpolation;
- identify dual-purpose X-Ray/Heatmap geometry.

Gate: production USD proves the expected thermal metadata contract.

result=PASS
thermal_targets=1148
valid_targets=1148
malformed_targets=0
review_targets=0
thermal_weight_range=[0, 1]
xray_overlaps=42


#### Phase 10.1 - Discovery and telemetry binding ✅

- create a reusable semantic registry of Heatmap-capable primitives;
- discover targets from thermal metadata rather than hard-coded mesh paths
  where semantic discovery is sufficient;
- preserve deterministic identity for repeated hardware such as GPU 1/2/3;
- map documented telemetry metrics to compatible thermal zones/components;
- mark regions without truthful telemetry as unavailable;
- keep presentation policy separate from Heatmap capability.

Gate: DTRS can deterministically resolve:

`primitive -> thermal semantics -> telemetry binding/unavailable ->
presentation policy`

without rendering yet.


#### Phase 10.2 - Scalar mapping foundation ✅

- implement the one fixed documented server-wide Celsius scale, clamping,
  colour mapping, quality handling, and missing-data behavior;
- preserve the same-temperature-to-same-colour Celsius-scalar contract without
  per-workload, per-component, or per-region scalar normalization;
- implement the telemetry-anchored derived spatial interpolation defined in
  the thermal contract; do not claim measured temperature at every surface
  point;
- keep `temperature_preview` outside the runtime calculation;
- cover the mapping logic with focused tests;
- implement the reusable Heatmap renderer and prove the complete path on a
  representative non-uniform target:

`TelemetrySnapshot -> semantic binding -> scalar mapping ->
thermal_weight -> visible Heatmap`

- apply runtime presentation without modifying authored asset layers;
- prove clean enable/disable and appearance restoration.

Gate: one production target works end-to-end in Kit before expanding coverage.


#### Phase 10.3 - Generic settings-driven Heatmaps ✅

- persist Isolation, Calibration, and Color Scale in
  `configs/heatmap_settings.toml` without changing telemetry provider config;
- build a stage-driven catalog for the generic Isolation union and dynamic
  calibration controls; all enabled selectors are the full-server case;
- support independent GPU Internals and Housing selectors plus arbitrary
  combinations, exact Session restoration, and generic presentation plans;
- apply candidate settings transactionally while Heatmaps are active, with an
  explicit previous-presentation rollback result on failure;
- retain the 2 Hz presentation cadence, 2.0-second smoothing, and one global
  absolute Celsius scale;
- configure a 2-to-6-stop palette with post-scalar clamp in `palette.py`;
- keep Test/Restore as a development harness, initially OFF after startup or
  reload. No Heatmap lifecycle or X-Ray composition is added in this phase.

Gate: the generic settings path works from one selected target through all
selectors against the production server, without a Vertical Slice or FullServer
runtime mode.


#### Phase 10.4 - Composition and lifecycle ✅

- require every Heatmap activation to apply the Engineering X-Ray presentation;
- do not implement a standalone non-X-Ray Heatmap mode;
- enforce single-server X-Ray precedence on dual-purpose geometry, especially
  the GPU enclosure/shroud;
- ensure suppression affects presentation only and does not remove thermal
  capability or metadata;
- add only the necessary runtime controls, legend, quality/missing-data state,
  and diagnostics;
- verify clean behavior across metric changes, workload changes,
  enable/disable, stage reload, and shutdown;
- remove only Heatmap-owned runtime state and restore the correct authored or
  higher-priority presentation.

Gate: Heatmap always owns its X-Ray presentation, and Heatmap/Streamlines
transitions leave exactly one healthy primary presentation without stale or
corrupted state.


#### Phase 10.5 - Acceptance and release ✅

- run focused Heatmap tests and the full DTRS test suite;
- perform Kit-side acceptance against the production server stage;
- document the thermal metadata contract, telemetry binding, scalar mapping,
  X-Ray precedence, and rack/data-hall boundary;
- record acceptance evidence;
- close `DC-50`;
- create the Stage 10 checkpoint;
- release DTRS `0.5.0`.


#### Post-acceptance Heatmap performance fix - periodic viewport stalls

**Symptom.** With Heatmap enabled, fan animation regularly appeared to stop:
`spins -> freezes -> spins`. Fan controllers continued to update each Kit
frame, so the defect was a brief viewport/update-loop stall rather than an RPM
calculation error. Average FPS could remain acceptable; fan motion made each
periodic main-loop stall conspicuous.

**Diagnosis.** Heatmap presentation ran at its preserved 2 Hz cadence through
the smoother, presentation update, material telemetry update, and then a
USD/UsdShade mutation consumed by Hydra/RTX. The decisive A/B left Heatmap
materials, bindings, Isolation, X-Ray composition, scheduler, and ownership
active, but suppressed only periodic dynamic presentation writes:

- dynamic presentation ON: regular fan stalls;
- `Freeze Heatmap Presentation`: stalls disappeared completely.

This isolated the defect to dynamic Heatmap presentation, not fan motion,
Streamlines, X-Ray, or static Heatmap composition.

**Rejected approaches.** The shader-input path was batched by precomputing
changes, skipping unchanged values, using one Session edit target and one
`Sdf.ChangeBlock`, reusing inputs, and avoiding periodic `CreateInput()`. It
did not remove the stalls. A `primvar` / `scene::data_lookup_float` experiment
was substantially worse: geometry/Hydra dirtying reduced the viewport to about
1-2 FPS. That experiment was fully reverted.

**Root cause and fix.** USD/UsdShade had been used as transport for frequently
changing telemetry. Even a small material mutation could invalidate
Hydra/RTX work and occupy a later Kit frame for hundreds of milliseconds. Fan
motion was not the defect; it exposed the defect.

The final production path creates and binds the Heatmap MDL/material graph and
one compact named dynamic GPU texture at activation. Each periodic update now
applies existing smoothing, calibration, and palette semantics, then uploads
only texture pixel data; MDL reads the current texel value. No periodic
`UsdShade` input set, USD primvar set, material recreation, or rebinding is
performed. USD remains the transport for structural/static presentation state.

**Result.** Regular fan-animation freezes disappeared while live thermal colours
continued to respond to telemetry. Production Heatmap + X-Ray remained
interactive on the reference RTX 3080 (approximately 30 FPS in the observed
view), without changing the 2 Hz cadence, 2 s smoothing, or fan-motion logic.


### Stage 10 Acceptance

Stage 10 is complete when:

1. Production USD thermal metadata is discovered and validated correctly.

2. `thermal_weight` remains an authored `[0, 1]` spatial distribution and
   `temperature_preview` remains authoring/debug data only.

3. Documented DTRS telemetry drives the correct thermal regions through the
   defined derived spatial interpolation and one deterministic server-wide
   Celsius mapping. Delta and Temperature Offset are persisted calibration,
   while normalized authored weight supplies the spatial distribution.

4. Telemetry quality, stale state, and missing data are represented truthfully;
   unavailable component temperatures are not invented.

5. Repeated hardware resolves to the correct telemetry identity.

6. Workload changes alter runtime thermal presentation without changing the
   authored thermal distribution.

7. Isolation, calibration, and palette settings persist independently of the
   telemetry provider; Test uses applied settings rather than an unsaved draft.

8. Test/Restore leave authored layers and exact prior Session opinions intact.
   Reload returns Heatmaps to OFF and reloads persisted settings. Production
   lifecycle composition and Heatmap/X-Ray precedence are validated as part
   of the completed Phase 10.4 contract.

9. Enable/disable and metric changes leave no stale Heatmap harness state and
   do not modify production asset layers.

10. The implementation is reusable and subsystem-owned, with rack/data-hall
    Heatmap behavior explicitly left outside Stage 10.


Done when the full server can present a stable, readable telemetry-driven
Heatmap over Houdini-authored thermal distributions without inventing
measurements or implying validated thermal simulation.
