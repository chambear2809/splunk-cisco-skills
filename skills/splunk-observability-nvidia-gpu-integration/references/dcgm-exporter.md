# NVIDIA DCGM Exporter

The skill scrapes Prometheus metrics from the NVIDIA Data Center GPU Manager (DCGM) Exporter, deployed by the NVIDIA GPU Operator.

## What is DCGM?

DCGM is NVIDIA's official tool for monitoring datacenter GPUs. It exposes hundreds of metrics: utilization, memory, temperature, power, ECC errors, NVLink, processes, MIG (Multi-Instance GPU), and more. The full canonical metric list lives at https://docs.nvidia.com/datacenter/dcgm/latest/dcgm-api/group__dcgmFieldIdentifiers.html.

The DCGM Exporter packages DCGM as a Prometheus exporter. It runs as a DaemonSet (one pod per GPU node) on port `9400` (default) and exposes metrics at `/metrics`.

## Required GPU Operator settings

The skill assumes the NVIDIA GPU Operator is installed and DCGM Exporter is enabled. Minimum required:

```yaml
# Helm values for nvidia/gpu-operator chart
dcgmExporter:
  enabled: true
  serviceMonitor:
    enabled: false               # we use receiver_creator, not Prometheus Operator
```

Confirm:

```bash
kubectl -n nvidia-gpu-operator get daemonset nvidia-dcgm-exporter
kubectl -n nvidia-gpu-operator get svc nvidia-dcgm-exporter
```

The Service exposes port 9400 with selector `app: nvidia-dcgm-exporter` and label `app.kubernetes.io/name: nvidia-dcgm-exporter`. The skill's discovery rule matches on either label (see `dual-label-discovery.md`).

## Default DCGM Exporter metrics enabled

The GPU Operator's default DCGM CSV (`/etc/dcgm-exporter/dcp-metrics-included.csv`) includes:

| Metric | Description | Unit |
|--------|-------------|------|
| `DCGM_FI_DEV_SM_CLOCK` | SM clock frequency | MHz |
| `DCGM_FI_DEV_MEM_CLOCK` | Memory clock frequency | MHz |
| `DCGM_FI_DEV_GPU_TEMP` | GPU temperature | °C |
| `DCGM_FI_DEV_POWER_USAGE` | Power usage | W |
| `DCGM_FI_DEV_GPU_UTIL` | GPU utilization | % |
| `DCGM_FI_DEV_MEM_COPY_UTIL` | Memory copy utilization | % |
| `DCGM_FI_DEV_FB_FREE` | Frame buffer (VRAM) free | MiB |
| `DCGM_FI_DEV_FB_USED` | Frame buffer (VRAM) used | MiB |
| `DCGM_FI_DEV_PCIE_REPLAY_COUNTER` | PCIe replay errors | count |
| `DCGM_FI_DEV_NVLINK_BANDWIDTH_TOTAL` | NVLink bandwidth | MB/s |

The skill ingests all of these. The OTel Prometheus receiver maps each `DCGM_FI_*` metric name to a SignalFx series with the same name; SignalFlow charts reference them directly (e.g. `data('DCGM_FI_DEV_GPU_UTIL')`).

## Custom metrics CSV

If your team needs additional metrics (e.g. MIG-specific metrics), modify the GPU Operator's DCGM CSV ConfigMap:

```bash
kubectl -n nvidia-gpu-operator edit configmap default-mappings-config
```

Add lines like:

```
DCGM_FI_DEV_GPU_UTIL_MIG, gauge, GPU utilization per MIG instance
```

After editing, restart the DCGM Exporter DaemonSet:

```bash
kubectl -n nvidia-gpu-operator rollout restart daemonset/nvidia-dcgm-exporter
```

The skill's receiver_creator will scrape the new metrics on the next collection cycle without overlay changes.

## Sampling rate

The skill defaults to `scrape_interval: 10s`. Lower if you need higher-resolution charts (5s); higher (30s) for very large GPU fleets to reduce O11y MTS quota consumption.

DCGM Exporter itself updates its internal cache on a configurable interval (default 30s in the GPU Operator). If you set the OTel scrape_interval lower than DCGM's update interval, you'll see duplicate metric points (same value scraped twice). For the cleanest data, align them:

- OTel scrape_interval: 10s
- DCGM Exporter `--collectors=10s` (set via GPU Operator values)

## Pod-label gap

DCGM Exporter v3.3.x and earlier does NOT include pod-level labels (`pod`, `namespace`, `container`) on metrics by default. The result: metrics are correctly attributed to the GPU but cannot be cross-joined with the workload (NIM model name, vLLM replica, training job). See `dcgm-pod-labels.md` for the fix.
