# Dual-label discovery rule

The skill's discovery rule matches DCGM Exporter pods on **either** of two labels:

```yaml
rule: type == "pod" && (labels["app"] == "nvidia-dcgm-exporter" || labels["app.kubernetes.io/name"] == "nvidia-dcgm-exporter")
```

This annex explains why both labels are needed.

## The problem

The NVIDIA GPU Operator has shipped multiple versions over time, each labeling the DCGM Exporter pods slightly differently:

| GPU Operator version | Pod label set |
|---|---|
| v1.x - v22.x | `app: nvidia-dcgm-exporter` only |
| v23.x - v24.0 | `app: nvidia-dcgm-exporter` + `app.kubernetes.io/name: nvidia-dcgm-exporter` (both) |
| v24.1+ | `app.kubernetes.io/name: nvidia-dcgm-exporter` only (newer convention; deprecating `app`) |

A discovery rule that matches only `app` will miss v24.1+ deployments. A rule that matches only `app.kubernetes.io/name` will miss pre-v23 deployments.

The skill's dual-label OR-rule covers all versions.

## The rule in detail

```yaml
receiver_creator/dcgm-cisco:
  watch_observers: [k8s_observer]
  receivers:
    prometheus_simple:
      rule: type == "pod" && (labels["app"] == "nvidia-dcgm-exporter" || labels["app.kubernetes.io/name"] == "nvidia-dcgm-exporter")
      config:
        metrics_path: /metrics
        endpoint: '`endpoint`:9400'
        collection_interval: 10s
```

Breakdown:

- `type == "pod"`: only match Pod-typed observers (not Service, Node, etc.).
- `labels["app"] == "nvidia-dcgm-exporter"`: match the legacy label.
- `labels["app.kubernetes.io/name"] == "nvidia-dcgm-exporter"`: match the modern label.
- `||`: OR — match either label. Both being present (v23.x intermediate releases) is fine; the receiver_creator deduplicates by pod identity.
- `endpoint: '`endpoint`:9400'`: receiver_creator substitutes the discovered pod's IP into the literal backtick-marked `endpoint` token. The result is a per-pod scrape target like `10.244.1.5:9400`.

## What if a third labeling convention appears?

The receiver_creator rule is plain expression syntax; you can extend it:

```yaml
rule: type == "pod" && (
  labels["app"] == "nvidia-dcgm-exporter" ||
  labels["app.kubernetes.io/name"] == "nvidia-dcgm-exporter" ||
  labels["component"] == "dcgm-exporter"
)
```

The skill does not currently render the three-way variant; hand-edit if needed.

## Test coverage

The skill's test `test_dual_label_discovery_rule` asserts that both `labels["app"]` and `labels["app.kubernetes.io/name"]` appear in the rule, with `||` between them, regardless of YAML formatting (the test collapses whitespace before substring check).

## Anti-patterns

- **`labels["app.kubernetes.io/name"] == "dcgm-exporter"`** (without the `nvidia-` prefix): this matches OpenTelemetry's own DCGM exporter or AMD's GPU exporter. The receiver would scrape the wrong endpoint and produce nonsensical NVIDIA metric data.
- **`labels["app"] =~ "dcgm"`** (regex match): receiver_creator rules don't support regex on labels. Use exact-match `==`.
- **Using a Service rule (`type == "service"`)** instead of pod rule: theoretically valid, but loses per-pod identity. With Service rule, you only get one scrape per Service, even though there are N pods behind it. Use pod rule.

## Verification

After deploy, check the agent log for discovery hits:

```bash
kubectl -n splunk-otel logs daemonset/<release>-splunk-otel-collector-agent --tail=100 \
  | grep -E 'dcgm-cisco|prometheus_simple'
```

Expected: messages indicating a new receiver instance was started for each DCGM pod.

In O11y, confirm metrics appear:

```python
data('DCGM_FI_DEV_GPU_UTIL').count_by(['k8s.pod.name']).publish('discovered_pods')
```

The series count should equal the number of DCGM Exporter pods (= number of GPU nodes).
