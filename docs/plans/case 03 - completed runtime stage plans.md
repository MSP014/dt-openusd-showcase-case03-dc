# Case 03 - Completed Runtime Stage Plans

**Status**: Reference
**Last Updated**: 2026-07-10

This document preserves the detailed plans used to deliver completed runtime
stages. The active roadmap and future scope remain in
[Case 03 - Staged Runtime Plan](case%2003%20-%20staged%20runtime%20plan.md).

When another runtime stage is completed, move its detailed plan here without
duplicating cross-stage contracts that still govern active or future work.

---

## Completed Stage Plans

### Stage 1 - Blackwell Monitoring Suite v0.1 Asset Preview Slice

Jira: `DC-40`

Status: implemented locally.

Build the smallest useful app surface: launch Blackwell Monitoring Suite v0.1,
show the RTX viewport, load one configured USD asset from the hydrated asset
package, and show basic load status. The first target asset is the Noctua NH-D9
TR5-SP6 CPU cooler exported at `assets/_external/usd/cpu_fan/cpu_fan.usd`.

Done when the selected asset is visible in the viewport, the load path/result is
visible in status, and the slice does not require a hidden absolute workstation
path.

Implementation notes:

- The app launches through `src/blackwell_monitoring_suite/start_bms.bat` or a
  direct Kit invocation with the BMS `.kit` file.
- The runtime config is `configs/blackwell_monitoring_suite.toml`.
- The extension id is `msp.bw.monitoring`.
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

- The Config panel is docked to the left side of the BMS viewport.
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
  BMS viewport between visible HDRI background and hidden HDRI background while
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
  `docs/knowledge_base/bms_telemetry_contract.md`.
- Keep the future live-provider superset documented there, but do not implement
  real monitoring feed adapters in Stage 3.
- Group Stage 3 telemetry visually by operator meaning, not by raw sensor
  origin.

Stage 3 UI shell decision:

- Keep a single left-docked BMS sidebar so the viewport is only constrained by
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

Future BMS modules should add their sidebar tabs to this registry before
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
- The provider should start producing data as soon as BMS starts, before the
  operator manually loads or changes scene content.
- Containerisation, network transport, credentials, service discovery, and live
  provider adapters remain out of Stage 3 scope.

Stage 3 provider lifecycle:

- Start the synthetic telemetry provider during BMS extension startup, not only
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
| `src/blackwell_monitoring_suite/app/telemetry/__init__.py` | Public package boundary for telemetry provider code. |
| `src/blackwell_monitoring_suite/app/telemetry/model.py` | `TelemetrySnapshot`, metric value model, workload/health constants, and Stage 3 metric ids. |
| `src/blackwell_monitoring_suite/app/telemetry/config.py` | Load and merge `telemetry_provider.toml` with `telemetry_provider.local.toml`. |
| `src/blackwell_monitoring_suite/app/telemetry/provider.py` | Synthetic provider, fixed provider tick, interpolation, jitter, freeze-independent latest snapshot state. |
| `src/blackwell_monitoring_suite/configs/telemetry_provider.toml` | Packaged read-only base targets, ranges, jitter, default mode, and allowed refresh intervals. |
| `tests/test_telemetry_config.py` | Pure-Python tests for provider config loading, override merge, defaults, and invalid values. |
| `tests/test_telemetry_provider.py` | Pure-Python tests for provider snapshots, cadence semantics, mode changes, freeze/resume display behaviour, deterministic seeded output, and range clamping. |

Stage 3 extension integration:

- `src/blackwell_monitoring_suite/ext/msp.bw.monitoring/msp/bw/monitoring/extension.py`
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
- Keep `src/blackwell_monitoring_suite/app/commands.py` focused on Kit/USD
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
  provider module. Do not store telemetry targets in the existing BMS local
  operator override config used for lighting, grid, camera, and look-review
  settings.
- The `Config` tab may expose telemetry provider settings, but persistence must
  go through the provider config path/API, not through the current BMS
  `.local.toml` override.
- Use a read-only packaged base file plus a writable local override, for
  example `telemetry_provider.toml` merged with
  `telemetry_provider.local.toml`.
- The local override should be ignored by git and should contain operator edits
  such as tuned targets or jitter/range changes.
- The provider config file layout should let the telemetry module move later
  into a separate process or container with its own config and without breaking
  the BMS data flow.
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

- Until the BMS shell has a dedicated global mode selector, the first control in
  the `Telemetry` tab should select the global workload mode:
  `Idle`, `Nominal`, `Surge`, or `Critical`.
- This selector is a temporary UI placement decision. The selected mode is still
  global BMS runtime state, not telemetry-tab-local state.
- Stage 3 uses the selected mode to drive synthetic telemetry values.
- Later stages may move the same mode selector into a more global app-level
  control area when scene behaviour, fan motion, overlays, LEDs, or other BMS
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

- Max can launch BMS and switch the left sidebar to the `Telemetry` tab.
- Telemetry values are visible and update without pressing Play in Houdini, Kit
  timeline, or any other DCC timeline.
- Changing the workload mode changes the telemetry targets and values move
  towards the new mode range.
- `Freeze` stops visible telemetry updates and `Resume` continues them.
- Switching between `Telemetry` and `Config` does not resize, overlap, or damage
  the viewport/sidebar layout.

Operator validation on 2026-07-09 confirmed all Stage 3 manual acceptance
items, including mode transitions, independent runtime updates, freeze/resume,
tab switching, config persistence, intermittent throttling, and clean BMS
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
remain in `docs/knowledge_base/bms_telemetry_contract.md`. Stage 3 deliberately
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
  `msp.bw.monitoring`;
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
- server-level fan and blower assets should follow the BMS motion contract
  documented in `src/blackwell_monitoring_suite/README.md`: stable rotating
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
