"""Runtime telemetry value models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Mapping

WORKLOAD_MODES = ("Idle", "Nominal", "Surge", "Critical")
HEALTH_STATES = ("OK", "Warning", "Critical", "Unknown")
TELEMETRY_GROUPS = {
    "Node (Blackwell Rig GB203)": (
        "workload_percent",
        "health_state",
    ),
    "CPU (AMD Threadripper PRO 7975WX)": (
        "cpu_temp_c",
        "thermal_headroom_percent",
    ),
    "GPU 1 (NVIDIA RTX PRO 4500 Blackwell)": (
        "gpu_1_temp_c",
        "gpu_1_memory_temp_c",
        "gpu_1_hotspot_temp_c",
        "gpu_1_power_w",
        "gpu_1_fan_rpm",
        "gpu_1_memory_used_gb",
        "gpu_1_memory_util_percent",
    ),
    "GPU 2 (NVIDIA RTX PRO 4500 Blackwell)": (
        "gpu_2_temp_c",
        "gpu_2_memory_temp_c",
        "gpu_2_hotspot_temp_c",
        "gpu_2_power_w",
        "gpu_2_fan_rpm",
        "gpu_2_memory_used_gb",
        "gpu_2_memory_util_percent",
    ),
    "GPU 3 (NVIDIA RTX PRO 4500 Blackwell)": (
        "gpu_3_temp_c",
        "gpu_3_memory_temp_c",
        "gpu_3_hotspot_temp_c",
        "gpu_3_power_w",
        "gpu_3_fan_rpm",
        "gpu_3_memory_used_gb",
        "gpu_3_memory_util_percent",
    ),
    "GPU array (3x NVIDIA RTX PRO 4500 Blackwell)": (
        "gpu_temp_c_max",
        "gpu_memory_temp_c_max",
        "gpu_hotspot_temp_c_max",
        "gpu_power_w_total",
        "gpu_memory_used_gb_total",
    ),
    "Power (PDU + be quiet! Dark Power Pro 13 1600W)": (
        "pdu_outlet_power_w",
        "psu_output_power_estimate_w",
        "cpu_power_w",
        "gpu_power_w_total",
        "platform_residual_power_w",
        "psu_conversion_loss_w",
        "psu_temp_estimate_c",
        "psu_load_percent",
    ),
    "CPU cooling (Noctua NH-D9 TR5-SP6)": (
        "cpu_fan_rpm",
        "cpu_fan_duty_percent",
    ),
    "Front intake (3x ARCTIC BioniX P120)": (
        "front_fan_1_rpm",
        "front_fan_2_rpm",
        "front_fan_3_rpm",
    ),
    "Rear exhaust (2x ARCTIC P8 Max)": (
        "rear_fan_1_rpm",
        "rear_fan_2_rpm",
    ),
    "Airflow (SilverStone RM44)": ("node_airflow_cfm",),
    "Front panel indicators (SilverStone RM44)": (
        "storage_activity_percent",
        "lan_1_activity_percent",
        "lan_2_activity_percent",
    ),
    "Network (NVIDIA ConnectX-7)": (
        "link_state",
        "link_speed_gbps",
        "network_rx_gbps",
        "network_tx_gbps",
        "nic_temp_c",
        "packet_error_rate",
        "rdma_active_sessions",
    ),
    "Limits (Blackwell Rig GB203)": ("throttling_active",),
}
METRIC_UNITS = {
    "workload_percent": "%",
    "health_state": "",
    "cpu_temp_c": "\N{DEGREE SIGN}C",
    "gpu_1_temp_c": "\N{DEGREE SIGN}C",
    "gpu_1_memory_temp_c": "\N{DEGREE SIGN}C",
    "gpu_1_hotspot_temp_c": "\N{DEGREE SIGN}C",
    "gpu_1_power_w": "W",
    "gpu_1_fan_rpm": "RPM",
    "gpu_1_memory_used_gb": "GB",
    "gpu_1_memory_util_percent": "%",
    "gpu_2_temp_c": "\N{DEGREE SIGN}C",
    "gpu_2_memory_temp_c": "\N{DEGREE SIGN}C",
    "gpu_2_hotspot_temp_c": "\N{DEGREE SIGN}C",
    "gpu_2_power_w": "W",
    "gpu_2_fan_rpm": "RPM",
    "gpu_2_memory_used_gb": "GB",
    "gpu_2_memory_util_percent": "%",
    "gpu_3_temp_c": "\N{DEGREE SIGN}C",
    "gpu_3_memory_temp_c": "\N{DEGREE SIGN}C",
    "gpu_3_hotspot_temp_c": "\N{DEGREE SIGN}C",
    "gpu_3_power_w": "W",
    "gpu_3_fan_rpm": "RPM",
    "gpu_3_memory_used_gb": "GB",
    "gpu_3_memory_util_percent": "%",
    "gpu_temp_c_max": "\N{DEGREE SIGN}C",
    "gpu_memory_temp_c_max": "\N{DEGREE SIGN}C",
    "gpu_hotspot_temp_c_max": "\N{DEGREE SIGN}C",
    "thermal_headroom_percent": "%",
    "cpu_power_w": "W",
    "gpu_power_w_total": "W",
    "gpu_memory_used_gb_total": "GB",
    "pdu_outlet_power_w": "W",
    "psu_output_power_estimate_w": "W",
    "platform_residual_power_w": "W",
    "psu_conversion_loss_w": "W",
    "psu_temp_estimate_c": "\N{DEGREE SIGN}C",
    "psu_load_percent": "%",
    "cpu_fan_rpm": "RPM",
    "cpu_fan_duty_percent": "%",
    "front_fan_1_rpm": "RPM",
    "front_fan_2_rpm": "RPM",
    "front_fan_3_rpm": "RPM",
    "rear_fan_1_rpm": "RPM",
    "rear_fan_2_rpm": "RPM",
    "node_airflow_cfm": "CFM",
    "storage_activity_percent": "%",
    "lan_1_activity_percent": "%",
    "lan_2_activity_percent": "%",
    "link_state": "",
    "link_speed_gbps": "Gbps",
    "network_rx_gbps": "Gbps",
    "network_tx_gbps": "Gbps",
    "nic_temp_c": "\N{DEGREE SIGN}C",
    "packet_error_rate": "ppm",
    "rdma_active_sessions": "sessions",
    "throttling_active": "",
}
METRIC_LABELS = {
    "workload_percent": "Workload",
    "health_state": "Health",
    "cpu_temp_c": "CPU temperature",
    "gpu_1_temp_c": "GPU 1 temperature",
    "gpu_1_memory_temp_c": "GPU 1 memory temperature",
    "gpu_1_hotspot_temp_c": "GPU 1 hotspot",
    "gpu_1_power_w": "GPU 1 power",
    "gpu_1_fan_rpm": "GPU 1 blower",
    "gpu_1_memory_used_gb": "GPU 1 memory used",
    "gpu_1_memory_util_percent": "GPU 1 memory utilisation",
    "gpu_2_temp_c": "GPU 2 temperature",
    "gpu_2_memory_temp_c": "GPU 2 memory temperature",
    "gpu_2_hotspot_temp_c": "GPU 2 hotspot",
    "gpu_2_power_w": "GPU 2 power",
    "gpu_2_fan_rpm": "GPU 2 blower",
    "gpu_2_memory_used_gb": "GPU 2 memory used",
    "gpu_2_memory_util_percent": "GPU 2 memory utilisation",
    "gpu_3_temp_c": "GPU 3 temperature",
    "gpu_3_memory_temp_c": "GPU 3 memory temperature",
    "gpu_3_hotspot_temp_c": "GPU 3 hotspot",
    "gpu_3_power_w": "GPU 3 power",
    "gpu_3_fan_rpm": "GPU 3 blower",
    "gpu_3_memory_used_gb": "GPU 3 memory used",
    "gpu_3_memory_util_percent": "GPU 3 memory utilisation",
    "gpu_temp_c_max": "Maximum temperature",
    "gpu_memory_temp_c_max": "Maximum memory temperature",
    "gpu_hotspot_temp_c_max": "Maximum hotspot",
    "thermal_headroom_percent": "Thermal headroom",
    "cpu_power_w": "CPU power",
    "gpu_power_w_total": "Total GPU power",
    "gpu_memory_used_gb_total": "Total GPU memory used",
    "pdu_outlet_power_w": "PDU outlet input",
    "psu_output_power_estimate_w": "Estimated PSU output",
    "platform_residual_power_w": "Platform residual",
    "psu_conversion_loss_w": "PSU conversion loss",
    "psu_temp_estimate_c": "Estimated PSU temperature",
    "psu_load_percent": "PSU load",
    "cpu_fan_rpm": "CPU fan",
    "cpu_fan_duty_percent": "Fan duty",
    "front_fan_1_rpm": "Front fan 1",
    "front_fan_2_rpm": "Front fan 2",
    "front_fan_3_rpm": "Front fan 3",
    "rear_fan_1_rpm": "Rear fan 1",
    "rear_fan_2_rpm": "Rear fan 2",
    "node_airflow_cfm": "Node airflow",
    "storage_activity_percent": "Storage activity",
    "lan_1_activity_percent": "LAN 01 activity",
    "lan_2_activity_percent": "LAN 02 activity",
    "link_state": "Link state",
    "link_speed_gbps": "Link speed",
    "network_rx_gbps": "Receive",
    "network_tx_gbps": "Transmit",
    "nic_temp_c": "NIC temperature",
    "packet_error_rate": "Packet errors",
    "rdma_active_sessions": "RDMA sessions",
    "throttling_active": "Throttling",
}


@dataclass(frozen=True)
class MetricValue:
    """One normalised telemetry value."""

    value: float | bool | str
    unit: str
    quality: str = "synthetic"


@dataclass(frozen=True)
class TelemetrySnapshot:
    """Latest-only telemetry state consumed by the runtime."""

    schema_version: str
    provider_id: str
    provider_type: str
    timestamp: datetime
    operational_state: str
    refresh_interval_s: int
    metrics: Mapping[str, MetricValue]

    @classmethod
    def create(
        cls,
        *,
        schema_version: str,
        provider_id: str,
        provider_type: str,
        timestamp: datetime,
        operational_state: str,
        refresh_interval_s: int,
        metrics: dict[str, MetricValue],
    ) -> "TelemetrySnapshot":
        """Create an immutable snapshot."""

        return cls(
            schema_version=schema_version,
            provider_id=provider_id,
            provider_type=provider_type,
            timestamp=timestamp,
            operational_state=operational_state,
            refresh_interval_s=refresh_interval_s,
            metrics=MappingProxyType(dict(metrics)),
        )
