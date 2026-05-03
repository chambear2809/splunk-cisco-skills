# Troubleshooting

## No `DCGM_FI_DEV_*` metrics in Splunk Observability Cloud

### Step 1: Confirm the GPU Operator is healthy

```bash
kubectl -n nvidia-gpu-operator get pods
```

Look for any `CrashLoopBackOff`, `ImagePullBackOff`, or `Init:0/N` pods. The DCGM Exporter cannot start until the driver and device plugin are healthy.

### Step 2: Confirm DCGM Exporter is exposing metrics

```bash
kubectl -n nvidia-gpu-operator port-forward svc/nvidia-dcgm-exporter 9400:9400 &
curl -s localhost:9400/metrics | head -20
# Should show DCGM_FI_DEV_*  metric points.
```

If `curl` returns no output or 404, DCGM Exporter is broken; check its logs:

```bash
kubectl -n nvidia-gpu-operator logs daemonset/nvidia-dcgm-exporter --tail=200
```

### Step 3: Confirm the OTel agent has RBAC to discover endpoints

This is the #1 production issue. The Splunk OTel agent needs cluster-wide endpoint list permission. Confirm:

```bash
kubectl auth can-i --as system:serviceaccount:splunk-otel:splunk-otel-collector \
  list endpoints -n nvidia-gpu-operator
# Expected: yes
```

If `no`, the GPU integration skill's overlay didn't apply, OR the chart was deployed with `--reuse-values` and the new RBAC isn't merged. Re-render and re-deploy:

```bash
bash skills/splunk-observability-nvidia-gpu-integration/scripts/setup.sh \
  --render --output-dir ./gpu-rendered
helm upgrade --install splunk-otel-collector splunk-otel-collector-chart/splunk-otel-collector \
  -n splunk-otel \
  -f ./gpu-rendered/splunk-otel-overlay/values.overlay.yaml \
  --reuse-values \
  --set splunkObservability.accessToken="$(cat $TOKEN_FILE)"
```

Verify after upgrade:

```bash
kubectl get clusterrole splunk-otel-collector -o yaml | grep -A 2 endpoints
```

### Step 4: Confirm the receiver_creator is discovering pods

```bash
kubectl -n splunk-otel logs daemonset/<release>-splunk-otel-collector-agent --tail=100 \
  | grep -E 'dcgm-cisco|forbidden|nvidia-dcgm-exporter'
```

Look for:

- `started receiver dcgm-cisco/...`: discovery succeeded, scrape underway.
- `forbidden: endpoints is forbidden`: RBAC is missing (see Step 3).
- `no targets`: discovery rule didn't match any pods. Verify pod labels:

```bash
kubectl -n nvidia-gpu-operator get pods -l app.kubernetes.io/name=nvidia-dcgm-exporter --show-labels
```

### Step 5: Confirm metrics arrive in O11y

In the O11y UI, run a SignalFlow query:

```python
data('DCGM_FI_DEV_GPU_UTIL').count().publish('count')
```

If the count is 0, metrics aren't reaching O11y. Check the agent's signalfx exporter:

```bash
kubectl -n splunk-otel logs daemonset/<release>-splunk-otel-collector-agent --tail=100 \
  | grep -E 'signalfx|exporter'
```

## Pod labels missing

If `data('DCGM_FI_DEV_GPU_UTIL').count_by(['pod'])` shows no `pod` dimension, the pod-labels patch wasn't applied. See `dcgm-pod-labels.md`.

## High MTS quota consumption

DCGM emits ~20 metrics per GPU. With 8 GPUs per node and 10 nodes, that's 1600 metric streams (MTS). With `--enable-dcgm-pod-labels` and 100 pods using GPUs, the cardinality balloons to 160k MTS.

To reduce:

- Increase `scrape_interval: 30s` (default 10s) — reduces MTS-update rate but not MTS count.
- Use `filter/exclude_metrics` processor on the dedicated pipeline to drop low-value DCGM fields.
- Pin labels by adding a `transform` processor to drop labels you don't query (e.g. `Hostname` if you have `k8s.node.name`).

## Receiver_creator collision with chart autodetection

If you see DUPLICATE metrics (each GPU showing up twice), the chart's `receiver_creator/nvidia` is running alongside our `receiver_creator/dcgm-cisco`. Either:

- Disable the chart's autodiscovery: set `agent.config.receivers.receiver_creator/nvidia: null` in the values overlay.
- Or accept the duplication and SignalFlow-filter on `_otel_pipeline` to deduplicate.

See `receiver-creator-naming.md` for full context.

## Coordination with the AI Pod umbrella

If you're using the `splunk-observability-cisco-ai-pod-integration` umbrella, this GPU skill's overlay is automatically merged in. Don't run the GPU skill's setup.sh standalone after the umbrella; the umbrella's render is the canonical state.

## DCGM versioning

DCGM Exporter has had several breaking metric renames over the years:

- v3.x renamed `DCGM_FI_DEV_GPU_UTIL` from older `nvidia_gpu_duty_cycle`.
- v3.3.x added pod label support.
- v3.4.x changed the default CSV.

Pin to a specific GPU Operator chart version (e.g. nvidia/gpu-operator==24.6.0) for reproducibility. The skill works against any v3.x DCGM Exporter; if you upgrade, double-check the metric names.
