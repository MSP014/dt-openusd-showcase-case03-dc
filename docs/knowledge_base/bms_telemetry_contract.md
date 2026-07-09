# Blackwell Monitoring Suite Telemetry Provider Contract

This document defines the telemetry vocabulary for Blackwell Monitoring Suite
(BMS).

The contract has two layers:

- the **Stage 3 synthetic subset**, which is the small node-level data set that
  the current BMS roadmap should implement first;
- the **future live provider superset**, which describes how a real monitoring
  feed could map data from HWiNFO-like tools, NVML, Redfish, IPMI, PMBus,
  smart PDUs, Grafana, MQTT, Kafka, or another monitoring system into BMS.

The synthetic provider proves the runtime interaction model. A live provider
may replace it later without changing the visualisation layer.

## Provider Boundary

BMS should consume telemetry through a provider boundary, not directly from UI
callbacks or hardcoded synthetic values.

Every provider snapshot should preserve the following semantics:

- `schema_version`: telemetry contract version.
- `provider_id`: stable id for the data source.
- `provider_type`: `synthetic`, `nvml`, `hwinfo`, `redfish`, `ipmi`,
  `pmbus`, `pdu`, `grafana`, `mqtt`, `kafka`, or another documented source.
- `timestamp`: BMS receive or generation time.
- `source_timestamp`: source measurement time when available.
- `site_id`, `hall_id`, `rack_id`, `node_id`, `component_id`: topology fields
  when the data source can provide them.
- `quality`: `measured`, `estimated`, `derived`, `synthetic`, `stale`, or
  `unavailable`.
- `unit`: explicit unit for each numeric value.

Providers may omit fields they cannot truthfully supply. Missing data is better
than pretending an estimate is a measured sensor value.

## Stage 3 Synthetic Subset

Stage 3 implements only the first-layer node telemetry set.

| Group | Metrics | Purpose |
| :--- | :--- | :--- |
| State | `timestamp`, `operational_state`, `workload_percent`, `health_state` | Shows whether the node is idle, nominal, surging, or critical, and anchors every value in runtime time. |
| Thermals | `cpu_temp_c`, per-GPU `gpu_temp_c`, `gpu_memory_temp_c`, `gpu_hotspot_temp_c`, node-level maxima, `thermal_headroom_percent` | Provides the heat story for the CPU cooler, each of the three GPUs, memory junctions, hotspots, and remaining safety margin. |
| GPU memory | Per-GPU `gpu_memory_used_gb`, derived utilisation, and node-level total | Shows workload-driven allocation against 32 GB per card and 96 GB across the node. |
| Power | `pdu_outlet_power_w`, derived PSU output, `cpu_power_w`, per-GPU `gpu_power_w`, derived GPU total, platform residual, PSU conversion loss, estimated PSU temperature, PSU load percent | Connects measured or synthetic PDU input to a complete node power and thermal balance without claiming unavailable consumer PSU sensors. |
| Cooling | `cpu_fan_rpm`, `cpu_fan_duty_percent`, per-GPU `gpu_fan_rpm`, three front `front_fan_rpm`, two rear `rear_fan_rpm`, `node_airflow_cfm` | Connects the Noctua cooler, GPU blowers, three ARCTIC BioniX P120 intake fans, and two ARCTIC P8 Max exhaust fans to thermal state and the airflow budget. |
| Network | `link_state`, `link_speed_gbps`, `network_rx_gbps`, `network_tx_gbps`, `nic_temp_c`, `packet_error_rate`, `rdma_active_sessions` | Represents the ConnectX-7 link, asymmetric inference traffic, thermals, quality, and RDMA activity. |
| Limits | `throttling_active` | Gives the operator an intermittent warning when Critical-mode CPU, GPU hotspot, and PSU load pressure produces a throttling episode. |

The Stage 3 UI should not expose the wider live-provider contract unless the
implementation deliberately grows beyond the synthetic node slice.
The three RTX PRO 4500 cards are represented separately. GPU maximum and total
metrics are derived from those component values rather than configured
independently. GPU 1 is nearest the CPU and uses the warmest thermal baseline;
GPU 2 is intermediate; GPU 3 uses the coolest baseline. Each card has
independent bounded jitter. Operator configuration uses one shared GPU baseline
per metric; card-specific variation is owned by provider rules. The provider
also preserves the thermal ordering of GPU 1, GPU 2, and GPU 3 and keeps each
card's hotspot at or above its memory and core temperatures.
Per-GPU power profiles are capped at the workstation card's documented 200 W
total board power, so derived node-level GPU power cannot exceed 600 W.
Per-GPU memory use is capped at the documented 32 GB capacity, so independent
jitter cannot push a card or the derived node total beyond 32 GB or 96 GB.
Critical-mode throttling is stateful rather than independently random on every
tick. CPU temperature, maximum GPU hotspot temperature, and PSU load determine
episode probability; configured active and recovery durations prevent visual
flicker. Other workload modes do not permit synthetic throttling episodes.
The ConnectX-7 profile reports a fixed 400 Gbps negotiated link. Synthetic NIC
temperature remains below the documented 105 C operating/warning boundary, and
RX/TX targets respect the node's documented single-slot PCIe bandwidth trade-off.
Front intake RPM is capped at the BioniX P120's documented 2100 RPM maximum;
rear exhaust RPM is capped at the P8 Max's documented 5000 RPM maximum.

## Future Live Provider Superset

The following fields are the discussion baseline for future live monitoring
adapters. They are not all required for Stage 3.

### Identity and Topology

| Metric | Scope | Notes |
| :--- | :--- | :--- |
| `site_id` | site | Optional site identifier. |
| `hall_id` | hall | Data hall or room id. |
| `rack_id` | rack | Physical or logical rack id. |
| `node_id` | node | Server/node id. |
| `component_id` | component | GPU, CPU, PSU, NIC, fan, drive, sensor, or PDU outlet id. |
| `slot_id` | component | Slot, bay, PCIe, DIMM, PSU, or drive position when available. |

### State and Health

| Metric | Scope | Notes |
| :--- | :--- | :--- |
| `operational_state` | node/rack | `Idle`, `Nominal`, `Surge`, `Critical`, or a documented provider state. |
| `health_state` | component/node/rack | `OK`, `Warning`, `Critical`, `Unknown`, or `Offline`. |
| `workload_percent` | node/rack | BMS workload driver or live utilisation proxy. |
| `uptime_s` | node | Useful for live fleet diagnostics. |
| `maintenance_mode` | node/rack | Prevents false alarm semantics during planned work. |
| `alert_severity` | component/node/rack | Alert severity when provided by the source system. |
| `alert_code` | component/node/rack | Source-specific alert or fault code. |
| `last_update_age_ms` | all | Helps BMS detect stale data. |

### CPU

| Metric | Scope | Notes |
| :--- | :--- | :--- |
| `cpu_temp_c` | node | CPU package or selected CPU thermal sensor. |
| `cpu_package_power_w` | node | CPU package power when measured or estimated. |
| `cpu_util_percent` | node | CPU load for preprocessing/scheduler context. |
| `cpu_throttling_active` | node | Thermal or power throttling flag. |

### GPU

| Metric | Scope | Notes |
| :--- | :--- | :--- |
| `gpu_temp_c` | gpu | Per-GPU temperature. |
| `gpu_temp_c_max` | node | Max GPU temperature across the node. |
| `gpu_memory_temp_c` | gpu | Per-GPU memory junction temperature when available. |
| `gpu_memory_temp_c_max` | node | Node-level max memory temperature. |
| `gpu_hotspot_temp_c` | gpu | Per-GPU hotspot temperature when available. |
| `gpu_hotspot_temp_c_max` | node | Node-level max hotspot temperature. |
| `gpu_power_w` | gpu | Per-GPU power draw. |
| `gpu_power_w_total` | node | Total GPU power draw for the node. |
| `gpu_util_percent` | gpu/node | GPU compute utilisation. |
| `gpu_memory_used_gb` | gpu/node | VRAM used by model/runtime workload. |
| `gpu_fan_rpm` | gpu | GPU blower speed when available. |
| `gpu_throttling_active` | gpu/node | Thermal, power, or reliability limiter. |

### Memory

| Metric | Scope | Notes |
| :--- | :--- | :--- |
| `system_memory_used_gb` | node | Important for model residency and host memory pressure. |
| `system_memory_total_gb` | node | Capacity context. |
| `ecc_error_count` | node/dimm | Server-class reliability signal when available. |
| `memory_bandwidth_gbps` | node | Optional high-signal AI workload diagnostic. |

### Power

| Metric | Scope | Notes |
| :--- | :--- | :--- |
| `pdu_outlet_power_w` | rack/node | Smart PDU outlet input measurement or Stage 3 synthetic stand-in. |
| `psu_output_power_estimate_w` | node | Derived DC output estimate using the documented efficiency assumption. |
| `platform_residual_power_w` | node | Derived remainder after CPU and GPU power; includes motherboard, RAM, NIC, storage, and fans. |
| `psu_conversion_loss_w` | node | Derived difference between PDU input and estimated PSU output. |
| `psu_temp_estimate_c` | psu | Derived thermal-map input based on conversion loss, assumed inlet temperature, and assumed thermal resistance; not a hardware sensor reading. |
| `psu_load_percent` | node | Estimated PSU output divided by rated PSU capacity. |
| `psu_waste_heat_estimate_w` | node | Optional estimated PSU loss term for visual heat contribution. |
| `psu_input_power_w` | psu/node | Only measured when a digital PSU, BMC, PMBus, PDU, or UPS source provides it. |
| `psu_output_power_w` | psu/node | Server-class measured output when available; do not invent for consumer PSU hardware. |
| `psu_temp_c` | psu | Optional server/digital PSU sensor. |
| `psu_fan_rpm` | psu | Optional server/digital PSU sensor. |
| `psu_status` | psu | `OK`, `Warning`, `Failed`, `Absent`, `Unknown`, or provider-specific mapped state. |
| `pdu_outlet_power_w` | rack/node | Smart PDU outlet measurement. |
| `feed_a_power_w` | rack/node | A-feed measurement when available. |
| `feed_b_power_w` | rack/node | B-feed measurement when available. |

### Cooling and Airflow

| Metric | Scope | Notes |
| :--- | :--- | :--- |
| `cpu_fan_rpm` | component/node | First fan-motion target for BMS. |
| `cpu_fan_duty_percent` | component/node | Better UI/control value than RPM alone. |
| `chassis_fan_rpm` | component/node | Optional per-fan or aggregate chassis fan speed. |
| `chassis_fan_duty_percent` | component/node | Aggregate cooling response. |
| `node_airflow_cfm` | node | Estimated physical airflow exposed by BMS. |
| `supply_air_temp_c` | rack/hall | Cold-side inlet or supply temperature. |
| `return_air_temp_c` | rack/hall | Hot-side return temperature. |
| `air_delta_t_c` | rack/hall | Return minus supply temperature. |

### Network

| Metric | Scope | Notes |
| :--- | :--- | :--- |
| `network_rx_gbps` | node/nic/rack | Receive bandwidth. |
| `network_tx_gbps` | node/nic/rack | Transmit bandwidth. |
| `link_state` | nic/switch | Up/down/degraded. |
| `link_speed_gbps` | nic/switch | Negotiated link speed. |
| `packet_error_rate` | nic/switch | Optional quality signal. |
| `rdma_active_sessions` | node/nic | Optional RDMA workload signal. |

### Storage

| Metric | Scope | Notes |
| :--- | :--- | :--- |
| `storage_temp_c` | drive/node | Drive thermal health. |
| `storage_used_percent` | drive/node | Capacity pressure. |
| `storage_read_gbps` | drive/node | Read throughput. |
| `storage_write_gbps` | drive/node | Write throughput. |
| `drive_health_state` | drive | OK/warning/failure state. |

### Rack and Facility

| Metric | Scope | Notes |
| :--- | :--- | :--- |
| `rack_power_kw` | rack | Rack-level power draw. |
| `rack_airflow_demand_cfm` | rack | Current or estimated rack airflow demand. |
| `jetpanel_airflow_cfm` | rack/facility | Raised-floor fan tile supply estimate or measurement. |
| `pue_estimate` | hall/facility | Facility-efficiency estimate. |
| `cef_estimate` | rack/facility | Cooling Efficiency Factor estimate. |

## PSU Measurement Boundary

The current Case 03 node uses a be quiet! Dark Power Pro 13
consumer/workstation PSU. BMS must not imply that this PSU exposes server-class
BMC/IPMI/PMBus telemetry.

For the current synthetic provider:

- use `pdu_outlet_power_w` as the synthetic external input;
- derive estimated PSU output, platform residual, conversion loss, PSU
  temperature, and load percentage from that input and known CPU/GPU
  contributors;
- keep synthetic PDU input high enough to cover CPU power, total GPU power, and
  the configured minimum platform residual;
- calculate `psu_temp_estimate_c` as inlet temperature plus conversion loss
  multiplied by the configured thermal resistance, capped by the configured
  temperature limit;
- use `psu_waste_heat_estimate_w` only if the PSU heat contribution becomes a
  separate visible cue.

For future live providers:

- use `psu_input_power_w`, `psu_output_power_w`, `psu_temp_c`, `psu_fan_rpm`,
  or `psu_status` only when a digital PSU, smart PDU, UPS, branch circuit
  monitor, BMC, Redfish, IPMI, or PMBus source actually supplies them;
- mark derived or estimated values with `quality = estimated` or
  `quality = derived`.

## Implementation Rules

- BMS consumers must tolerate missing optional fields.
- Provider adapters must normalise units before values enter the BMS state
  layer.
- Values that are generated, inferred, or estimated must not be labelled as
  measured.
- A later live provider should map source-specific names into this contract
  rather than leaking HWiNFO, Redfish, Grafana, or MQTT naming directly into UI
  code.
- Stage 3 implements the synthetic subset only; live provider adapters are
  tracked as technical debt until the project reaches real monitoring
  integration work.
