# Receiver creator naming: `dcgm-cisco`, NOT `nvidia`

The skill renders its DCGM scraper as `receiver_creator/dcgm-cisco`. This name is intentional and **must NOT** be changed to `receiver_creator/nvidia`. This annex explains why.

## The problem

The Splunk OTel collector chart (`splunk-otel-collector-chart`) ships with an autodetect feature that scans the cluster for known workloads and auto-configures Prometheus scrapers. When `autodetect.prometheus: true` (the chart default), the chart auto-creates several `receiver_creator/<name>` instances, including:

- `receiver_creator/nvidia` — auto-discovers and scrapes NVIDIA DCGM Exporter.

The auto-discovery default for `receiver_creator/nvidia` is functional but limited:

- It uses a single-label match (`app.kubernetes.io/name: nvidia-dcgm-exporter`); some GPU Operator versions only set `app: nvidia-dcgm-exporter`.
- It applies the chart's standard `filter/exclude_metrics` processor pipeline, which drops several DCGM metrics by default to reduce MTS quota.
- It runs in the standard metrics pipeline, mixing DCGM metrics with k8s metrics under the same processor chain.

If our skill renders `receiver_creator/nvidia`, it **collides** with the chart's autodetected one, and the Helm merge produces an undefined behavior — typically the chart's version wins, our config is silently dropped, and we lose dual-label discovery + dedicated pipeline + custom metric set.

## The fix

We rename our scraper to `receiver_creator/dcgm-cisco`. This is a unique name not used by the chart's autodetection, so:

- Both scrapers can coexist in the rendered values.yaml.
- Our `receiver_creator/dcgm-cisco` runs alongside the chart's `receiver_creator/nvidia` (if not disabled).
- We can give our scraper its own dedicated pipeline (`metrics/cisco-ai-pods` or `metrics/nvidia-metrics`) without filter/exclude processing.

## What the production atl-ocp2 deployment does

The production `6-splunk-otel-collector-values.yaml` from `otel-gruve` uses exactly this pattern:

```yaml
agent:
  config:
    receivers:
      receiver_creator/dcgm-cisco:        # <-- custom name, not 'nvidia'
        watch_observers: [k8s_observer]
        receivers:
          prometheus_simple:
            rule: type == "pod" && (labels["app"] == "nvidia-dcgm-exporter" || labels["app.kubernetes.io/name"] == "nvidia-dcgm-exporter")
            config:
              metrics_path: /metrics
              endpoint: '`endpoint`:9400'
              collection_interval: 10s
    service:
      pipelines:
        metrics/cisco-ai-pods:            # dedicated pipeline
          receivers: [receiver_creator/dcgm-cisco]
          processors: [batch]             # NO filter/exclude
          exporters: [signalfx]
```

The skill mirrors this exactly.

## What about disabling the chart's autodetection?

You could set:

```yaml
autodetect:
  prometheus: false
```

This disables the chart's auto-prometheus discovery (including `receiver_creator/nvidia`). However:

- It also disables auto-discovery for other Prometheus sources (Istio, etcd, calico, CoreDNS, etc.) that the chart's autodetection finds.
- It's a coarse-grained switch; you lose autodetection for ALL prometheus sources.

The cleaner approach is to keep `autodetect.prometheus: true` (default), let the chart auto-create `receiver_creator/nvidia`, and add OUR custom-named scraper alongside. The two scrapers will both ingest DCGM metrics; you'll see slight duplication (same metric, two pipelines). The duplication is intentional and well-bounded; you can SignalFlow-deduplicate by filtering on `_otel_pipeline` or by disabling one or the other in your specific dashboard query.

If duplication bothers you, the safest way to deduplicate is to suppress the chart's auto-receiver via `agent.config.receivers.receiver_creator/nvidia: null`. This nulls the chart's auto-config without disabling all autodetection.

## Anti-patterns to avoid

- **`receiver_creator/nvidia` in our skill**: collides with chart auto, breaks merge.
- **`receiver_creator/dcgm`**: this name is also used by some upstream contrib examples; possible collision if the chart adds it later. Use `dcgm-cisco` for safety (the `-cisco` suffix is unique to AI Pod work).
- **Renaming after deploy**: if you've already deployed with `receiver_creator/nvidia` and want to rename, plan for a brief metric gap (the existing pipeline drains, the new one starts; ~10-30s of missing data on the rename).

## Test coverage

`tests/test_splunk_observability_nvidia_gpu_integration.py::test_receiver_creator_name_is_never_nvidia` enforces the no-`nvidia` rule on every render. If anyone changes the renderer to use `receiver_creator/nvidia`, the test fails.
