# AI Pod dashboards catalog

The umbrella ships an aggregated dashboard set composed of the children's dashboards plus AI-Pod-specific overview dashboards.

## Composed children dashboards

The umbrella's `dashboards/` directory contains:

- `cisco-nexus-overview.signalflow.yaml` (from nexus child)
- `cisco-intersight-overview.signalflow.yaml` (from intersight child)
- `nvidia-gpu-overview.signalflow.yaml` (from gpu child)

Each is identical to its child's version; the umbrella just collects them in one place for unified handoff.

## AI-Pod-specific overview dashboards

The umbrella adds:

### `ai-pod-end-to-end-overview.signalflow.yaml`

A single-pane dashboard combining the most critical AI Pod metrics:

| Chart | Source |
|-------|--------|
| GPU utilization (avg) | DCGM (gpu child) |
| GPU memory (used vs free) | DCGM (gpu child) |
| NIM request rate | NIM scrape (umbrella) |
| NIM token throughput | NIM scrape (umbrella) |
| NIM p95 latency | NIM scrape (umbrella) |
| vLLM KV cache usage | vLLM scrape (umbrella) |
| Network errors (Nexus) | cisco_os (nexus child) |
| Server power (Intersight) | Intersight (intersight child) |

Filters: `k8s.cluster.name=${CLUSTER_NAME}`. Optional: `model_name=${MODEL_NAME}` to scope to a single model.

### `ai-pod-model-comparison.signalflow.yaml`

Compares NIM models side-by-side:

```python
# Throughput per model
data('nim_request_count').sum_by(['model_name']).rate('1m').publish('throughput')

# Latency per model
data('nim_request_duration_seconds_bucket')
  .percentile(95)
  .sum_by(['model_name'])
  .publish('p95_latency')

# Tokens per second per model
(data('nim_token_count_output').rate('1s')).sum_by(['model_name']).publish('tps')
```

Useful for A/B comparing model variants (e.g. `llama-3.1-70b` vs `llama-3.1-405b`).

### `ai-pod-storage-health.signalflow.yaml`

Storage subsystem health:

| Chart | Metric |
|-------|--------|
| Trident allocated capacity | `trident_volume_allocated_bytes` |
| Trident operation latency | `trident_op_duration_seconds` |
| Portworx cluster status | `px_cluster_status` |
| Portworx volume IOPS | `px_volume_iops` |
| Portworx volume latency | `px_volume_latency_us` |

Only renders if at least one of `storage.trident.enabled` or `storage.portworx.enabled` is true.

### `ai-pod-bmc-health.signalflow.yaml`

Hardware health from Redfish:

| Chart | Metric |
|-------|--------|
| Server temperature (avg/max) | `redfish_temperature_celsius` |
| Fan RPM (per fan) | `redfish_fan_rpm` |
| PSU input power | `redfish_psu_input_watts` |
| Memory health | `redfish_memory_health` |
| Drive health | `redfish_drive_health` |

Only renders if `redfish.enabled` is true.

## Detector starters

The umbrella ships a small detector pack:

- `detectors/gpu-temp-critical.yaml`: Critical when any GPU > 85°C for 5 minutes.
- `detectors/nim-latency-elevated.yaml`: Major when NIM p95 latency > 500ms for 10 minutes.
- `detectors/nim-error-rate.yaml`: Major when NIM error rate > 1% for 5 minutes.
- `detectors/storage-volume-near-full.yaml`: Major when Trident volume allocation > 80%.

Apply via `handoff-detectors.sh`.

## Dashboard apply

```bash
bash scripts/handoff-dashboards.sh
# Then manually:
for spec in ./rendered/dashboards/*.signalflow.yaml; do
    bash skills/splunk-observability-dashboard-builder/scripts/setup.sh \
      --render --apply --realm $REALM --spec $spec --token-file $O11Y_API_TOKEN_FILE
done
```

The dashboard-builder skill handles deduplication if you've already applied a dashboard before.

## Adding custom dashboards

Drop a new YAML under `dashboards/<name>.signalflow.yaml` (in the umbrella's spec or after rendering). The handoff script picks up all files matching `*.signalflow.yaml`.

If you want the new dashboard to ALSO be picked up on the next umbrella render, add it to a custom `dashboards_extra:` list in the spec; the renderer will copy it through. (Currently not supported; hand-copy after each render.)

## SignalFlow validation

Each dashboard's SignalFlow program is validated by the dashboard-builder skill on `--render`. If a metric name is misspelled or the filter syntax is wrong, validation fails before any API call. This is a hard guarantee: the umbrella's render+validate pipeline will never produce a dashboard that fails to load in O11y.

## Coordination with other skills

- The umbrella's dashboards rely on metric names produced by the OTel collector overlay. If you significantly modify the overlay (renaming receiver_creators, adding processors that drop metrics), some dashboards may go blank. Re-render the umbrella after major overlay changes.
- The umbrella's detectors integrate with `splunk-observability-native-ops` (which manages detectors as code). The detector specs in `detectors/*.yaml` are in native-ops format.
