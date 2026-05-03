# NIM + vLLM + Milvus scrape catalog

The umbrella adds Prometheus scrape jobs for AI inference workloads. This annex lists each scrape target and what it produces.

## NVIDIA NIM (NVIDIA Inference Microservices)

NIM containers expose Prometheus metrics on port 8000 at `/metrics`. The umbrella discovers them via two modes (see `nim-scrape-modes.md`); both produce the same metric set:

| Metric | Description | Used in dashboard |
|--------|-------------|-------------------|
| `nim_request_count` | Total inference requests | Throughput chart |
| `nim_request_duration_seconds` | Request latency histogram | Latency p50/p95/p99 |
| `nim_active_requests` | Currently in-flight requests | Concurrency chart |
| `nim_token_count_input` | Input tokens | Token throughput |
| `nim_token_count_output` | Output tokens | Token throughput |
| `nim_kv_cache_usage` | KV cache utilization | Memory pressure |
| `nim_model_load_seconds` | Model load time | Cold-start metric |

### `k8s_attributes/nim` processor

The umbrella adds a custom k8s_attributes processor that extracts the `app` label from each NIM pod and surfaces it as a `model_name` resource attribute. This lets you filter dashboards by `model_name` instead of having to remember which `app` label maps to which model:

```yaml
k8s_attributes/nim:
  passthrough: false
  pod_association:
    - sources:
        - { from: resource_attribute, name: k8s.pod.name }
        - { from: resource_attribute, name: k8s.namespace.name }
  extract:
    metadata: [k8s.namespace.name, k8s.pod.name, k8s.node.name]
    labels:
      - { tag_name: model_name, key: app, from: pod }
```

Then SignalFlow:

```python
data('nim_request_count', filter=filter('model_name', 'llama-3.1-70b')).publish()
```

## vLLM

vLLM (Very Large Language Model serving framework) exposes the same Prometheus metric format as NIM (similar interfaces). The umbrella discovers vLLM pods on port 8000 with label `app: vllm` (or app.kubernetes.io/name=vllm).

| Metric | Description |
|--------|-------------|
| `vllm:num_requests_running` | Currently running requests |
| `vllm:num_requests_swapped` | Swapped requests (KV cache eviction) |
| `vllm:gpu_cache_usage_perc` | GPU KV cache utilization |
| `vllm:cpu_cache_usage_perc` | CPU KV cache utilization |
| `vllm:e2e_request_latency_seconds` | End-to-end request latency |
| `vllm:request_prompt_tokens` | Prompt tokens per request |
| `vllm:request_generation_tokens` | Generated tokens per request |

Note the `vllm:` namespace prefix (with colon). SignalFlow handles this fine, but the colon is unusual; older Prometheus tooling may sanitize it to underscore. The OTel Prometheus receiver passes through the `:` literally.

## Milvus (vector database)

Milvus exposes Prometheus metrics on port 9091. The umbrella discovers Milvus pods with label `app.kubernetes.io/name: milvus`:

| Metric | Description |
|--------|-------------|
| `milvus_proxy_req_count` | Proxy request count |
| `milvus_proxy_req_latency_bucket` | Proxy request latency histogram |
| `milvus_querynode_load_segment_latency_bucket` | Segment load latency |
| `milvus_querynode_search_latency_bucket` | Search latency histogram |
| `milvus_querynode_collection_num` | Number of collections per QueryNode |
| `milvus_datanode_flush_buffer_op_count` | Flush operation count |

Milvus has many internal components (proxy, query node, data node, index node, etc.), each exposing its own metrics. The umbrella scrapes all of them through the single Service endpoint.

## NetApp Trident

Trident exposes Prometheus metrics on port 17001. Discovery rule:

```yaml
rule: type == "pod" && labels["app"] == "trident-controller"
endpoint: '`endpoint`:17001'
```

| Metric | Description |
|--------|-------------|
| `trident_volume_count` | Number of provisioned volumes |
| `trident_node_count` | Number of nodes registered |
| `trident_volume_allocated_bytes` | Total allocated bytes |
| `trident_op_duration_seconds` | Operation latency histogram |

## Pure Portworx

Portworx exposes Prometheus metrics on port 17018. Discovery rule:

```yaml
rule: type == "pod" && labels["name"] == "portworx"
endpoint: '`endpoint`:17018'
```

| Metric | Description |
|--------|-------------|
| `px_cluster_status` | Cluster health (1 = healthy) |
| `px_volume_iops` | IOPS per volume |
| `px_volume_latency_us` | Volume latency in microseconds |
| `px_disk_used_bytes` | Disk used per node |

## Redfish

Redfish exporter (e.g. `mrlhansen/redfish_exporter`) exposes hardware health metrics on port 9610. Discovery is service-based, not pod-based, since the exporter polls remote BMCs.

| Metric | Description |
|--------|-------------|
| `redfish_health` | Sensor health (1 = OK) |
| `redfish_temperature_celsius` | Per-sensor temperature |
| `redfish_fan_rpm` | Per-fan RPM |
| `redfish_psu_input_watts` | PSU input power |
| `redfish_memory_health` | Memory health |

## Disabling specific scrape jobs

To disable a scrape, set its `enabled: false` in the spec:

```yaml
nim:
  enabled: false           # do not scrape NIM
vllm:
  enabled: true
milvus:
  enabled: false           # do not scrape Milvus
storage:
  trident:
    enabled: false
  portworx:
    enabled: true
redfish:
  enabled: false
```

The umbrella renders only the enabled scrape jobs.

## Cardinality budget

Each NIM model = ~7 metrics × N replicas. With 5 NIM models × 3 replicas each = 105 series per scrape. Add vLLM, Milvus, Trident, Portworx, Redfish and the cardinality budget reaches ~500-1000 MTS for a typical AI Pod cluster. Within Splunk Observability Cloud's per-org MTS quotas (1M default).

If you're cardinality-constrained, drop the histogram metrics first (`*_bucket` series are large): use a `filter/exclude_metrics` processor to drop them in the dedicated AI Pod pipeline.
