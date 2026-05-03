# Dashboards catalog

The skill ships one starter SignalFlow dashboard at `dashboards/nvidia-gpu-overview.signalflow.yaml`. This annex documents what's in it and how to extend.

## Default dashboard: NVIDIA GPU Overview

| Chart | Metric | Aggregation |
|-------|--------|-------------|
| GPU utilization | `DCGM_FI_DEV_GPU_UTIL` | mean per-GPU |
| Memory utilization | `DCGM_FI_DEV_MEM_COPY_UTIL` | mean per-GPU |
| Frame buffer used (VRAM) | `DCGM_FI_DEV_FB_USED` | mean per-GPU |
| Frame buffer free | `DCGM_FI_DEV_FB_FREE` | mean per-GPU |
| GPU temperature | `DCGM_FI_DEV_GPU_TEMP` | max over time |
| Power usage | `DCGM_FI_DEV_POWER_USAGE` | mean per-GPU |
| SM clock | `DCGM_FI_DEV_SM_CLOCK` | mean per-GPU |
| PCIe replay errors | `DCGM_FI_DEV_PCIE_REPLAY_COUNTER` | sum over time |

All charts filter by `k8s.cluster.name=${CLUSTER_NAME}`. The default group-by is `gpu` (DCGM's GPU index, 0-7 typical).

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

Drop a new YAML file under `dashboards/<name>.signalflow.yaml`. The handoff-dashboards.sh script picks up every `*.signalflow.yaml` and feeds it to `splunk-observability-dashboard-builder`.

## Detector starter

The skill ships one starter detector at `detectors/gpu-temp-critical.yaml` that triggers Critical when `DCGM_FI_DEV_GPU_TEMP > 85°C` for 5 minutes. The threshold is configurable via spec.

## Coordination with cisco-intersight-setup

If the GPUs are in Cisco UCS chassis managed by Intersight, you can deeplink GPU charts to Intersight server views. Use the dashboard-builder skill's `link` field on charts to redirect to Intersight URLs based on `k8s.node.name` -> Intersight server lookup.
