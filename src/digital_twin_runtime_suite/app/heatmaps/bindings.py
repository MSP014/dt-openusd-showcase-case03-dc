"""
Maps semantic thermal targets to existing telemetry metrics.

For example, conceptually:

GPU1 / core     -> gpu_1_temp_c
GPU1 / memory   -> gpu_1_memory_temp_c
GPU1 / hotspot  -> gpu_1_hotspot_temp_c
CPU / ...       -> cpu_temp_c
NIC / ...       -> nic_temp_c
PSU / ...       -> psu_temp_estimate_c

Also handles:

repeated hardware identity;
unavailable binding;
telemetry quality/provenance;
presentation eligibility / X-Ray precedence.

This is also where rules such as the following can be expressed:

GPU shroud
Heatmap-capable = yes
single-server presentation = suppressed by X-Ray
"""
