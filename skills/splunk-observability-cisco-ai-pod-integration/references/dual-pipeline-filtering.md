# Dual-pipeline filtering

The umbrella renders TWO metrics pipelines in the OTel collector: a filtered one for general telemetry and unfiltered ones for AI/ML specific metrics. This annex explains the pattern and why it matters.

## The problem with single-pipeline filtering

The Splunk OTel collector chart's default metrics pipeline includes a `filter/exclude_metrics` processor that drops several "noisy" or "high-cost" metric names to reduce O11y MTS quota consumption. The default exclude list includes:

- Several `k8s.*` cAdvisor metrics that overlap with kubelet metrics
- Some `node_*` metrics from Prometheus node-exporter
- A few `apiserver_*` metrics

The exclude list is conservative — it's safe defaults for a generic Kubernetes deployment. However, for AI Pod work, we WANT some metrics that the default would exclude:

- DCGM metrics (NVIDIA GPU): always wanted, never filtered.
- NIM metrics: always wanted, never filtered.
- vLLM metrics: always wanted, never filtered.

If we route DCGM metrics through the chart's default filtered pipeline, some DCGM metrics may be dropped silently (e.g. if `filter/exclude_metrics` adds a regex that matches `DCGM_FI_DEV_FB_*` in a future chart version).

## The solution: dual pipelines

The umbrella renders the OTel agent with two metrics pipelines:

1. **`metrics`** (the default chart pipeline, with filter/exclude): handles k8s metrics, host metrics, kubelet metrics. The chart's default filter applies.
2. **`metrics/cisco-ai-pods`** (custom, no filter): handles DCGM, NIM, vLLM, Milvus, storage, Redfish. Bypasses filter/exclude entirely.

```yaml
service:
  pipelines:
    metrics:
      receivers: [k8s_cluster, kubeletstats, hostmetrics]
      processors: [resourcedetection, k8s_attributes, filter/exclude_metrics, batch]
      exporters: [signalfx]
    metrics/cisco-ai-pods:
      receivers:
        - receiver_creator/dcgm-cisco
        - receiver_creator/milvus
        - receiver_creator/storage
      processors: [resourcedetection, k8s_attributes, batch]   # NO filter
      exporters: [signalfx]
    metrics/nvidianim-metrics:
      receivers:
        - receiver_creator/nim
        - receiver_creator/vllm
      processors: [resourcedetection, k8s_attributes, k8s_attributes/nim, batch]
      exporters: [signalfx]
```

## Why three pipelines instead of two?

The umbrella splits AI/ML metrics into two pipelines because NIM and vLLM benefit from the `k8s_attributes/nim` processor (extracts `app` label as `model_name`) but DCGM and Milvus do NOT. Running them all through the NIM processor would either:

- Pollute non-NIM metrics with empty `model_name` attributes (cardinality waste).
- Or require complex conditional processor logic.

Cleaner: one pipeline for "dcgm + storage + milvus" (no NIM processor), one pipeline for "nim + vllm" (with NIM processor). Three total.

## Cardinality consequence

Routing DCGM through `metrics/cisco-ai-pods` (no filter) does mean: every DCGM metric reaches O11y, including ones the chart's default would drop. This adds ~50-100 MTS per node. For a 10-node cluster, ~500-1000 extra MTS. Within typical org quotas; no concern.

If you're on a tight quota, you can ADD a custom filter processor to `metrics/cisco-ai-pods` that drops a specific set of low-value DCGM metrics (e.g. `DCGM_FI_DEV_NVLINK_*` if you don't have NVLink hardware):

```yaml
processors:
  filter/dcgm-low-value:
    metrics:
      exclude:
        match_type: regexp
        metric_names: ["^DCGM_FI_DEV_NVLINK_.*$"]
service:
  pipelines:
    metrics/cisco-ai-pods:
      processors: [..., filter/dcgm-low-value, batch]
```

## OpenTelemetry pipeline naming convention

OTel pipelines are named `<signal>[/<id>]`:

- `metrics`: the default metrics pipeline.
- `metrics/cisco-ai-pods`: a custom pipeline for AI Pod metrics.
- `metrics/nvidianim-metrics`: a custom pipeline for NIM/vLLM metrics.

The `/<id>` suffix is mandatory for distinguishing multiple pipelines of the same signal type. The IDs are arbitrary identifiers; the umbrella uses descriptive names so the pipeline structure is self-documenting.

## What if you want to add another receiver to a custom pipeline?

Edit the umbrella spec's `extra_receivers:` and `extra_pipelines:` blocks (currently not supported in the spec; hand-edit the rendered overlay). For example, to add a custom Splunk On-Call deeplink receiver:

```yaml
receivers:
  splunk_oncall_deeplink:
    # ...
service:
  pipelines:
    metrics/cisco-ai-pods:
      receivers: [..., splunk_oncall_deeplink]
```

## Anti-patterns

- **Adding all AI/ML metrics to the default `metrics` pipeline**: defeats the purpose; metrics flow through filter/exclude.
- **Disabling filter/exclude entirely**: works but unfilters all the chart-default-noisy metrics too, blowing up MTS budget.
- **Per-metric pipelines**: don't create one pipeline per metric source; the OTel collector's pipeline overhead grows linearly with pipeline count. 3-5 pipelines is fine; 30+ is excessive.

## Production atl-ocp2 evidence

The atl-ocp2 reference values use exactly this pattern:

```yaml
service:
  pipelines:
    metrics: [...]                              # default
    metrics/cisco-ai-pods:                      # DCGM
      receivers: [receiver_creator/dcgm-cisco]
      ...
    metrics/nvidianim-metrics:                  # NIM
      receivers: [receiver_creator/nim]
      ...
```

The umbrella mirrors this exactly. If you change the structure, add a comment explaining why; the dual-pipeline pattern is load-bearing.
