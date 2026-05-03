# Troubleshooting

This is the umbrella's general troubleshooting reference. For specific deep-dives, see:

- `endpoints-rbac-patch.md` — RBAC issues
- `dual-pipeline-filtering.md` — pipeline / filter issues
- `nim-scrape-modes.md` — NIM scrape issues
- `composition-and-overlay-merge.md` — child composition issues
- `production-troubleshooting-atl-ocp2.md` — full production case study
- `openshift-scc.md` — OpenShift SCC issues
- `workshop-multi-tenant.md` — workshop mode issues

## Children renders fail

If `setup.sh --render` fails with `child renderer returned non-zero`:

```bash
# Re-run with verbose to see which child failed
bash skills/splunk-observability-cisco-ai-pod-integration/scripts/setup.sh \
  --render --verbose --output-dir /tmp/ai-pod-debug
```

The verbose flag surfaces each child's stdout/stderr. Common child failures:

- **GPU child fails on `--enable-dcgm-pod-labels`**: GPU Operator not installed; the renderer can detect this when `--gpu-operator-namespace` is set (auto-detection). Without auto-detection, just renders the patch; you apply it later.
- **Intersight child fails on missing `--namespace`**: Intersight requires the `intersight-otel` namespace name to render Deployment manifests. Default `intersight-otel`; override via spec.
- **Nexus child fails on missing `--ssh-secret-name`**: Nexus requires SSH secret coordinates. Default `cisco-nexus-ssh`; override via spec.

## Composed overlay missing pieces

After `setup.sh --render`, check the composed overlay:

```bash
cat /tmp/ai-pod-rendered/splunk-otel-overlay/values.overlay.yaml | head -100
```

Look for:

- `cisco_os` receiver block (from nexus child)
- `otlp` receiver protocols block (from intersight child) — should be in agent.config.receivers.otlp
- `receiver_creator/dcgm-cisco` (from gpu child)
- `receiver_creator/nim` (from umbrella)
- `rbac.customRules` (from umbrella, when nim_scrape_mode=endpoints)

If any are missing, the child render didn't produce the expected overlay file. Check the child's render output:

```bash
ls /tmp/ai-pod-rendered/child-renders/<child-name>/splunk-otel-overlay/
cat /tmp/ai-pod-rendered/child-renders/<child-name>/splunk-otel-overlay/*.yaml
```

## Helm install fails

```bash
# Always dry-run first
helm upgrade --install splunk-otel-collector splunk-otel-collector-chart/splunk-otel-collector \
  -n splunk-otel --create-namespace \
  -f /tmp/ai-pod-rendered/splunk-otel-overlay/values.overlay.yaml \
  --set splunkObservability.accessToken="$(cat $TOKEN_FILE)" \
  --set splunkObservability.realm="us0" \
  --dry-run --debug 2>&1 | tee /tmp/helm-debug.log
```

Common errors in dry-run output:

- `coalesce.go: warning: cannot overwrite table with non table for ...`: a child's overlay has a structural conflict with the chart's defaults. Check the section in the dry-run output. Usually a `receivers:` vs `receivers: null` collision.
- `validation: error converting YAML to JSON: ...`: the rendered YAML has syntax errors. Re-run `--validate` and check.
- `Error: rendered manifests contain a resource that already exists`: pre-existing CRDs or Secrets. Either delete them or use `--reuse-values`.

## Live cluster: metrics not appearing

After `helm install` succeeds:

1. **Confirm pods are running**:

```bash
kubectl -n splunk-otel get pods
# Expect: agent (DaemonSet, one per node), k8s-cluster-receiver (Deployment, one)
```

2. **Confirm RBAC**:

```bash
for ns in splunk-otel nvidia-gpu-operator nvidia-inference nvidia-nemo intersight-otel; do
  kubectl auth can-i --as system:serviceaccount:splunk-otel:splunk-otel-collector list endpoints -n $ns
done
# Expect all "yes"
```

3. **Confirm collector is exporting**:

```bash
kubectl -n splunk-otel logs daemonset/<release>-splunk-otel-collector-agent --tail=100 \
  | grep -E 'signalfx|signalfx_exporter|export'
# Look for "successfully sent" or "POST" lines.
```

4. **Confirm O11y is receiving**:

In O11y UI, run:

```python
data('sf_internal.collector.points_sent').count().publish()
```

This is the SignalFx exporter's self-metric; if non-zero, metrics are flowing.

## Specific metric missing

If individual metrics are missing (e.g. `nim_request_count` but DCGM metrics are present):

1. **Confirm the source workload is exposing metrics**:

```bash
kubectl -n nvidia-inference port-forward pod/<nim-pod> 8000:8000 &
curl -s localhost:8000/metrics | head -20
# Look for nim_request_count series.
```

2. **Confirm the receiver_creator discovered the workload**:

```bash
kubectl -n splunk-otel logs daemonset/<release>-splunk-otel-collector-agent --tail=300 \
  | grep -E 'started receiver|nim'
# Should show one receiver instance per discovered NIM pod/endpoint.
```

3. **Confirm the metric reached the exporter**:

```bash
# Add a debug exporter temporarily
helm upgrade ... --set agent.config.exporters.debug.verbosity=detailed \
  --set agent.config.service.pipelines.metrics/nvidianim-metrics.exporters="[signalfx, debug]"
# Check the agent logs for the metric in debug output.
```

## High costs in O11y

Run a SignalFlow MTS audit:

```python
data('*', filter=filter('k8s.cluster.name', '${CLUSTER_NAME}'))
  .count_by(['_metric'])
  .top(50)
  .publish()
```

Identify the highest-cardinality metrics. Common offenders:

- `DCGM_FI_DEV_*_BUCKET` series (histograms with hundreds of buckets each)
- `nim_request_duration_seconds_bucket` (histograms)
- `vllm:*_bucket` (histograms)

To reduce, add a filter processor that drops `*_bucket` series:

```yaml
processors:
  filter/no-buckets:
    metrics:
      exclude:
        match_type: regexp
        metric_names: [".*_bucket$"]
```

Add to the AI Pods pipelines.

## When to reach out

If after these steps you still can't get metrics flowing, gather:

1. Output of `setup.sh --render --verbose`.
2. Output of `helm get values splunk-otel-collector -n splunk-otel`.
3. Output of `kubectl -n splunk-otel logs --tail=500 daemonset/<release>-splunk-otel-collector-agent`.
4. Output of `kubectl get clusterrole splunk-otel-collector -o yaml`.
5. Verification of the eight production atl-ocp2 issues (`production-troubleshooting-atl-ocp2.md`).

This is enough for a Splunk support escalation or a focused debug session.
