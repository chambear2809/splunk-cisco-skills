# AI Pod dashboards catalog

The umbrella ships an aggregated dashboard set composed of the children's dashboards plus AI-Pod-specific overview dashboards.

## Composed children dashboards

The Nexus, Intersight, and NVIDIA GPU dashboards remain under each child's
`child-renders/<skill>/dashboards/` directory. The rendered
`scripts/handoff-dashboards.sh` prints each child's dashboard handoff before it
prints the commands for the umbrella-owned dashboards below; it does not copy
the child dashboards into the umbrella's top-level `dashboards/` directory.

## AI-Pod-specific overview dashboards

The umbrella adds:

### `ai-pod-llm-inference.signalflow.yaml`

NIM and vLLM inference telemetry, including active and waiting requests,
time-to-first-token, time per output token, end-to-end request latency, prompt
and generation tokens, vLLM KV-cache usage, and request success/failure counts.

### `ai-pod-vector-db.signalflow.yaml`

Milvus proxy, QueryCoord, and RootCoord telemetry, including cache hits,
request counts, collection and DDL activity, DML channels, and proxy queue
latency.

### `ai-pod-storage.signalflow.yaml`

NetApp Trident and Pure Portworx storage telemetry, including volume count and
allocated bytes, operation duration count, cluster CPU, online/offline nodes,
and volume read/write latency.

All three dashboard specs are rendered. Each contains a dashboard variable and
SignalFlow filter for the concrete `cluster_name` selected during the umbrella
render; the handoff does not rely on placeholder substitution.

## Detector starters

The umbrella ships these detector specs:

- `detectors/vllm-error-rate.yaml`: Major when the rate of
  `vllm:request_failure_total` exceeds 5.
- `detectors/nim-ttft-regression.yaml`: Warning when p95
  `time_to_first_token_seconds` exceeds 1 second.
- `detectors/milvus-query-latency.yaml`: Major when p95
  `milvus_proxy_req_in_queue_latency` exceeds 1000 ms.
- `detectors/portworx-node-offline.yaml`: Critical when
  `px_cluster_status_nodes_offline` is above zero.
- `detectors/trident-allocation-pressure.yaml`: informational delta-based
  baseline for `trident_volume_allocated_bytes`.

The rendered `scripts/handoff-detectors.sh` prints the child and umbrella
commands for review; execute the printed commands to apply them.

## Dashboard apply

```bash
bash splunk-observability-cisco-ai-pod-rendered/scripts/handoff-dashboards.sh

# After reviewing the printed commands, apply the umbrella-owned specs:
for spec in splunk-observability-cisco-ai-pod-rendered/dashboards/*.signalflow.yaml; do
    bash skills/splunk-observability-dashboard-builder/scripts/setup.sh \
      --render --apply --realm "$REALM" --spec "$spec" \
      --token-file "$O11Y_API_TOKEN_FILE"
done
```

Dashboard Builder creates a new dashboard group, charts, and dashboard on each
default apply. Re-running the loop therefore creates duplicates. Updating an
existing dashboard requires adding its `dashboard.id` and every chart's
`chart_id` to the spec, then applying with `--update-existing`; it does not
reconcile objects by name.

## Adding custom dashboards

After rendering, place a reviewed custom spec under
`splunk-observability-cisco-ai-pod-rendered/dashboards/<name>.signalflow.yaml`.
The handoff script includes every `*.signalflow.yaml` in that directory. The
current umbrella spec has no `dashboards_extra` input, so preserve custom files
outside the generated tree and copy them in after each render.

## SignalFlow validation

The umbrella validator checks the composed collector overlay, child renders,
required files, and secret safety. It does not call the dashboard-builder for
the top-level dashboard specs. The dashboard-builder performs its own
validation when an operator runs the reviewed commands emitted by
`scripts/handoff-dashboards.sh`; complete that step before applying a dashboard.

## Coordination with other skills

- The umbrella's dashboards rely on metric names produced by the OTel collector overlay. If you significantly modify the overlay (renaming receiver_creators, adding processors that drop metrics), some dashboards may go blank. Re-render the umbrella after major overlay changes.
- The umbrella's detectors integrate with `splunk-observability-native-ops` (which manages detectors as code). The detector specs in `detectors/*.yaml` are in native-ops format.
