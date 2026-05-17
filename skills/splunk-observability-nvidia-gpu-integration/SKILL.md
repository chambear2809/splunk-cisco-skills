---
name: splunk-observability-nvidia-gpu-integration
description: >-
  Render NVIDIA GPU telemetry from DCGM Exporter into Splunk Observability
  Cloud. Uses receiver_creator/dcgm-cisco to avoid chart autodetect collisions,
  matches both common DCGM labels, defaults to an unfiltered NVIDIA metrics
  pipeline, optionally patches DCGM pod labels, and emits dashboard, detector,
  base-collector, and apply handoffs. Use when the user asks to send NVIDIA GPU,
  DCGM, DCGM Exporter, GPU Operator, DGX, AI Pod, or CUDA workload telemetry to
  Splunk Observability Cloud, configure receiver_creator/dcgm-cisco, enable
  per-pod DCGM labels, or render GPU dashboards and detectors.
---

# Splunk Observability NVIDIA GPU Integration

This is a **standalone reusable skill** for NVIDIA GPU telemetry (DCGM Exporter) in Splunk Observability Cloud. It is **independent of the AI Pod** umbrella — works for NVIDIA DGX clusters, AI Pods, generic K8s + GPUs, anywhere DCGM Exporter is installed.

## Critical naming + discovery details

- **Receiver name `receiver_creator/dcgm-cisco`** (parameterized via `--receiver-creator-name`, default `dcgm-cisco`). Explicitly NOT `receiver_creator/nvidia` — that name collides with the Splunk OTel chart's autodetect receiver_creator when `autodetect.prometheus: true` is set, and the collision silently breaks GPU discovery.
- **Discovery rule matches both label conventions**: `app=nvidia-dcgm-exporter` (older standalone deployments) AND `app.kubernetes.io/name=nvidia-dcgm-exporter` (newer GPU Operator deployments).
- **Default unfiltered pipeline**: `metrics/nvidia-metrics` ships all DCGM_FI_* series so dashboards have everything. Pass `--filter strict` to enable the canonical signalfx allow-list when cardinality control is critical.

## What it renders

- `splunk-otel-overlay/values.overlay.yaml` — `agent.config.receivers.receiver_creator/dcgm-cisco` parent (`watch_observers: [k8s_observer]`) owning `prometheus/dcgm-cisco` child (port 9400). Discovery rule with the dual-label match. Plus the `metrics/nvidia-metrics` pipeline (unfiltered by default).
- `dcgm-pod-labels-patch/` — when `--enable-dcgm-pod-labels`: env-var patch (`DCGM_EXPORTER_KUBERNETES_ENABLE_POD_LABELS=true`, `DCGM_EXPORTER_KUBERNETES_ENABLE_POD_UID=true`), ClusterRole + ClusterRoleBinding for the DCGM ServiceAccount, AutoMount ServiceAccountToken, kubelet-path volume mount.
- `dashboards/<name>.signalflow.yaml` — GPU utilization, memory used/free, GPU temp, power, SM/MEM clocks, PCIe TX/RX, total energy, profiling DRAM/GR engine/PIPE tensor activity.
- `detectors/<name>.yaml` — GPU temp ceiling, GPU power floor, GPU utilization regression, energy consumption anomaly.
- `scripts/setup.sh`, `render_assets.py`, `validate.sh`, `handoff-base-collector.sh`, `handoff-dashboards.sh`, `handoff-detectors.sh`, `apply-dcgm-pod-labels-patch.sh`.
- `metadata.json`.

## Prerequisites surfaced as preflight checks (not installed)

- **NVIDIA GPU Operator** or standalone **DCGM Exporter**: install via `helm repo add gpu-helm-charts https://nvidia.github.io/dcgm-exporter/helm-charts` then `helm install --generate-name gpu-helm-charts/dcgm-exporter`. The receiver_creator pattern relies on the standard pod label `app=nvidia-dcgm-exporter` (or `app.kubernetes.io/name=nvidia-dcgm-exporter`).

## Safety Rules

- O11y token via `--o11y-token-file` (chmod 600 enforced; passed through to base collector). Reject `--o11y-token`, `--access-token`, `--token`, `--bearer-token`, `--api-token`, `--sf-token`.

## Primary Workflow

1. Verify DCGM Exporter is installed and pods carry the standard label:

   ```bash
   kubectl get pods -A -l app=nvidia-dcgm-exporter -o wide
   # OR (newer GPU Operator):
   kubectl get pods -A -l app.kubernetes.io/name=nvidia-dcgm-exporter -o wide
   ```

2. Render:

   ```bash
   bash skills/splunk-observability-nvidia-gpu-integration/scripts/setup.sh \
     --render --validate \
     --realm us0 \
     --cluster-name lab-cluster \
     --output-dir splunk-observability-nvidia-gpu-rendered
   ```

3. (Optional) When you need pod/namespace labels in DCGM_FI_* metrics — they are NOT exposed by GPU Operator by default — render the patch:

   ```bash
   bash skills/splunk-observability-nvidia-gpu-integration/scripts/setup.sh \
     --render --enable-dcgm-pod-labels \
     --output-dir splunk-observability-nvidia-gpu-rendered
   ```

   Then apply: `kubectl apply -f splunk-observability-nvidia-gpu-rendered/dcgm-pod-labels-patch/`.

4. Hand off:

   ```bash
   bash splunk-observability-nvidia-gpu-rendered/scripts/handoff-base-collector.sh
   bash splunk-observability-nvidia-gpu-rendered/scripts/handoff-dashboards.sh
   bash splunk-observability-nvidia-gpu-rendered/scripts/handoff-detectors.sh
   ```

## Hand-offs

- Splunk OTel Collector base install: [splunk-observability-otel-collector-setup](../splunk-observability-otel-collector-setup/SKILL.md).
- Dashboards: [splunk-observability-dashboard-builder](../splunk-observability-dashboard-builder/SKILL.md).
- Detectors: [splunk-observability-native-ops](../splunk-observability-native-ops/SKILL.md).

## Validation

```bash
bash skills/splunk-observability-nvidia-gpu-integration/scripts/validate.sh
```

Static checks: receiver_creator name not equal to `receiver_creator/nvidia`, dual-label rule present, allow-list opt-in shape. With `--live`: DCGM Exporter pod presence, optional SignalFlow probe for `DCGM_FI_DEV_GPU_UTIL` series.

See `reference.md` and `references/dcgm-exporter.md`, `dcgm-pod-labels.md`, `gpu-operator-prereq.md`, `receiver-creator-naming.md`, `dual-label-discovery.md`, `dashboards-catalog.md`, `troubleshooting.md` for details.
