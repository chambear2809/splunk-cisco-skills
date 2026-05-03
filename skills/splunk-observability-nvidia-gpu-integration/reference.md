# Splunk Observability NVIDIA GPU Integration Reference

## Source guidance

- DCGM Exporter Helm chart: `https://nvidia.github.io/dcgm-exporter/helm-charts` -- chart `gpu-helm-charts/dcgm-exporter`.
- NVIDIA GPU Operator: standard install via `gpu-operator/gpu-operator`. Manages DCGM Exporter as a sub-component when `dcgm.enabled: true`.
- Splunk OTel chart's autodetect: `autodetect.prometheus: true` enables `receiver_creator/nvidia` for control-plane metrics. Our skill avoids the collision by using a different receiver_creator name.
- Pod-label gap: documented in `references/dcgm-pod-labels.md` and the GPU Operator GitHub issue tracker (the env vars and required RBAC are well-known).

## Rendered layout

By default, assets are written under `splunk-observability-nvidia-gpu-rendered/`:

- `splunk-otel-overlay/values.overlay.yaml` — agent overlay with `receiver_creator/dcgm-cisco` (parameterized) and `metrics/nvidia-metrics` pipeline.
- `dcgm-pod-labels-patch/` — when `--enable-dcgm-pod-labels`: ClusterRole, ClusterRoleBinding, ServiceAccount automount patch, DaemonSet env patch.
- `dashboards/nvidia-gpu-overview.signalflow.yaml` — 15-chart starter dashboard.
- `detectors/<name>.yaml` — temp ceiling, power floor, utilization regression, energy anomaly.
- `scripts/handoff-base-collector.sh`, `handoff-dashboards.sh`, `handoff-detectors.sh`, `apply-dcgm-pod-labels-patch.sh` (when patch enabled).
- `metadata.json`.

## Setup modes

- `--render` (default), `--validate`, `--dry-run`, `--json`, `--explain`.

## Critical naming + discovery details

### Receiver creator name

The overlay uses `receiver_creator/dcgm-cisco` (parameterized via `--receiver-creator-name`, default `dcgm-cisco`).

**DO NOT** use `receiver_creator/nvidia`. The Splunk OTel chart, when `autodetect.prometheus: true` is set, enables its own `receiver_creator/nvidia` for control-plane metrics. Naming our custom GPU receiver `receiver_creator/nvidia` collides with the chart's autodetect receiver and silently breaks GPU discovery.

The renderer rejects `receiver_creator_name: nvidia` with a clear error.

### Discovery rule

The discovery rule matches BOTH label conventions:

```
type == "pod" && (labels["app"] == "nvidia-dcgm-exporter" || labels["app.kubernetes.io/name"] == "nvidia-dcgm-exporter")
```

- `app=nvidia-dcgm-exporter` — older standalone DCGM Exporter deployments (Helm chart from before the GPU Operator integration).
- `app.kubernetes.io/name=nvidia-dcgm-exporter` — newer GPU Operator deployments (recommended).

Both labels are matched in the same rule so the overlay works regardless of which install path the operator used.

## Filter modes

- `none` (default): unfiltered. All DCGM_FI_* series flow to Splunk Observability Cloud. Best for dashboards that want every metric.
- `strict`: applies a canonical signalfx allow-list of ~15 DCGM_FI_* metrics + extras you list in `spec.filter.extra_metrics`. Best for cardinality control.

## DCGM pod-label gap

NVIDIA GPU Operator does NOT expose pod/namespace labels in DCGM_FI_* metrics by default. To enable them you need:

1. Two env vars on the DCGM Exporter container:
   - `DCGM_EXPORTER_KUBERNETES_ENABLE_POD_LABELS=true`
   - `DCGM_EXPORTER_KUBERNETES_ENABLE_POD_UID=true`
2. A ClusterRole + ClusterRoleBinding granting the DCGM Exporter ServiceAccount get/list/watch on `pods` and `namespaces`.
3. AutoMount ServiceAccountToken on the DCGM Exporter ServiceAccount.
4. A kubelet-path volume mount (often handled by the GPU Operator's ClusterPolicy already).

Pass `--enable-dcgm-pod-labels` and the renderer emits all four pieces under `dcgm-pod-labels-patch/`. Apply with `bash scripts/apply-dcgm-pod-labels-patch.sh` after review.

**GPU Operator users**: the DaemonSet env patch (`04-daemonset-env-patch.yaml`) may be overridden by the operator on the next reconcile. Better to patch the GPU Operator's ClusterPolicy:

```yaml
spec:
  dcgm:
    enabled: true
    env:
      - name: DCGM_EXPORTER_KUBERNETES_ENABLE_POD_LABELS
        value: "true"
      - name: DCGM_EXPORTER_KUBERNETES_ENABLE_POD_UID
        value: "true"
```

The skill does not currently render a ClusterPolicy patch (operator-version-specific); document the operator version and patch manually.

## Hand-offs

- Splunk OTel Collector base install: [splunk-observability-otel-collector-setup](../splunk-observability-otel-collector-setup/SKILL.md).
- Dashboards: [splunk-observability-dashboard-builder](../splunk-observability-dashboard-builder/SKILL.md).
- Detectors: [splunk-observability-native-ops](../splunk-observability-native-ops/SKILL.md).

See `references/dcgm-exporter.md`, `dcgm-pod-labels.md`, `gpu-operator-prereq.md`, `receiver-creator-naming.md`, `dual-label-discovery.md`, `dashboards-catalog.md`, `troubleshooting.md` for details.
