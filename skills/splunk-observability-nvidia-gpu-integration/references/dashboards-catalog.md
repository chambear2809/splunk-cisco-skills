# Dashboards catalog

The skill ships one starter SignalFlow dashboard at `dashboards/nvidia-gpu-overview.signalflow.yaml`. This annex documents what's in it and how to extend.

## Default dashboard: NVIDIA GPU Overview

| Chart | Metric |
|-------|--------|
| GPU utilization | `DCGM_FI_DEV_GPU_UTIL` |
| Memory copy utilization | `DCGM_FI_DEV_MEM_COPY_UTIL` |
| Frame buffer used/free | `DCGM_FI_DEV_FB_USED`, `DCGM_FI_DEV_FB_FREE` |
| GPU and memory temperature | `DCGM_FI_DEV_GPU_TEMP`, `DCGM_FI_DEV_MEMORY_TEMP` |
| Power and total energy | `DCGM_FI_DEV_POWER_USAGE`, `DCGM_FI_DEV_TOTAL_ENERGY_CONSUMPTION` |
| SM and memory clocks | `DCGM_FI_DEV_SM_CLOCK`, `DCGM_FI_DEV_MEM_CLOCK` |
| PCIe receive/transmit bytes | `DCGM_FI_PROF_PCIE_RX_BYTES`, `DCGM_FI_PROF_PCIE_TX_BYTES` |
| Tensor, DRAM, and graphics activity | `DCGM_FI_PROF_PIPE_TENSOR_ACTIVE`, `DCGM_FI_PROF_DRAM_ACTIVE`, `DCGM_FI_PROF_GR_ENGINE_ACTIVE` |

The renderer writes a complete
`splunk-observability-dashboard-builder/v1` spec. Every chart filters on the
concrete `k8s.cluster.name` selected during render, and the dashboard includes
the same value as a restricted cluster variable. The starter programs publish
the raw metric streams; they do not impose a default GPU group-by.

## Per-workload extensions (requires `--enable-dcgm-pod-labels`)

If you've applied the pod-labels patch (see `dcgm-pod-labels.md`), DCGM metrics include `pod`, `namespace`, `container` labels. This unlocks per-workload charts:

### NIM model GPU consumption

```python
data('DCGM_FI_DEV_GPU_UTIL', filter=filter('namespace', 'nvidia-inference'))
  .sum_by(['pod'])
  .publish('per_nim_util')
```

### Training job efficiency

```python
data('DCGM_FI_DEV_GPU_UTIL', filter=filter('namespace', 'training'))
  .mean_by(['pod'])
  .timeshift('1h')
  .publish('training_util_baseline')
```

### Idle GPU waste

```python
(100 - data('DCGM_FI_DEV_GPU_UTIL').max())
  .publish('gpu_idle_pct')
```

## Common production dashboards

### MIG (Multi-Instance GPU) view

If you've enabled MIG via the GPU Operator, DCGM emits per-instance metrics with a `GPU_I_ID` label. Group by it:

```python
data('DCGM_FI_DEV_GPU_UTIL').sum_by(['gpu', 'GPU_I_ID']).publish('mig_util')
```

### NVLink saturation

```python
data('DCGM_FI_DEV_NVLINK_BANDWIDTH_TOTAL')
  .sum_by(['gpu'])
  .publish('nvlink_throughput')
```

Compare against the GPU's max NVLink bandwidth (e.g. 600GB/s for H100 NVLink 4) to detect saturation.

### Power efficiency (perf-per-watt)

```python
util = data('DCGM_FI_DEV_GPU_UTIL').mean_by(['gpu'])
power = data('DCGM_FI_DEV_POWER_USAGE').mean_by(['gpu'])
(util / power).publish('perf_per_watt')
```

Useful for capacity planning and identifying "lazy" GPUs (low util, high power).

## Adding charts

Start from the rendered v1 spec or Dashboard Builder example, preserve the
required group/dashboard/chart structure, and assign a non-overlapping layout.
The handoff script includes every `*.signalflow.yaml` in the directory.

## Detector starter

The skill renders three starter Native Ops v1 detector specs: GPU temperature
ceiling (Major), power floor (Warning), and low utilization (Info). A fourth
energy-delta detector is rendered only when
`energy_consumption_joules_anomaly` is greater than zero. Thresholds are
configurable in the skill spec; no lasting duration is added implicitly.

## Coordination with cisco-intersight-setup

If the GPUs are in Cisco UCS chassis managed by Intersight, design deep links
only through a verified dashboard capability. The current classic Dashboard
Builder renderer does not accept a generic `link` field on charts.
