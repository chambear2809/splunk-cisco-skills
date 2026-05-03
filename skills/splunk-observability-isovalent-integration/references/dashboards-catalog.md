# Dashboards catalog

The skill ships token-scrubbed re-exports of the canonical Cilium and Hubble dashboards from the Isovalent_Splunk_o11y reference repo. This annex documents what the dashboards expect (so you can adapt them to your environment without breaking the SignalFlow programs).

## Source dashboards

The reference repo at `/Users/alecchamberlain/Documents/GitHub/Isovalent_Splunk_o11y/examples/` ships:

- `Cilium by Isovalent.json` — Cilium agent + Hubble metrics dashboard.
- `Hubble by Isovalent.json` — Hubble flow metrics dashboard (DNS, HTTP, drops).

Pass `--dashboards-source /Users/alecchamberlain/Documents/GitHub/Isovalent_Splunk_o11y/examples/` to the skill to copy + scrub these into the rendered output.

**Do NOT** copy from `/Users/alecchamberlain/Documents/GitHub/Isovalent_Splunk_o11y/values/*.yaml`. The explore subagent confirmed these files have contained plaintext `accessToken` material; even if they don't right now, they're the wrong source for dashboard JSON anyway.

## Cilium dashboard expectations

The Cilium dashboard pivots on `cilium_*` metric series. Key charts:

| Chart | Metric | Notes |
|-------|--------|-------|
| Endpoint state | `cilium_endpoint_state` | Counts endpoints in each state (regenerating, ready, etc.) |
| Errors and warnings | `cilium_errors_warnings_total` | Detector candidate: spike in errors |
| BPF map operations | `cilium_bpf_map_ops_total` | Useful for tracking policy churn |
| API rate limit | `cilium_api_limiter_processed_requests_total` | Spike indicates policy storm |
| L7 policy verdicts | `cilium_policy_l7_total` | Required for Hubble L7 visibility |
| IP address usage | `cilium_ip_addresses` | IPAM exhaustion early warning |
| K8s events | `cilium_kubernetes_events_total` | Cilium's own view of cluster events |

All charts filter by `k8s.cluster.name` so multi-cluster dashboards work without modification.

## Hubble dashboard expectations

The Hubble dashboard pivots on `hubble_*` metric series. Key charts:

| Chart | Metric | Notes |
|-------|--------|-------|
| DNS queries | `hubble_dns_queries_total` | Cardinality scales with namespace count |
| DNS responses | `hubble_dns_responses_total` | Compare with queries to find drops |
| Drops | `hubble_drop_total` | Detector candidate: spike in drops |
| Flows processed | `hubble_flows_processed_total` | Total flow throughput |
| HTTP request duration (histogram) | `hubble_http_request_duration_seconds_bucket` | Latency analysis; needs L7 visibility enabled |
| HTTP requests | `hubble_http_requests_total` | Needs L7 visibility enabled |
| ICMP | `hubble_icmp_total` | ICMP flow counts |
| Policy verdicts | `hubble_policy_verdicts_total` | Allowed vs denied flows |
| TCP flags | `hubble_tcp_flags_total` | TCP flow shape (SYN, FIN, RST, ...) |

For L7 visibility (HTTP, gRPC, Kafka), the Cilium configuration must enable the L7 proxy (`cilium.l7Proxy.enabled: true` in `cisco-isovalent-platform-setup` cilium values). Without it, the L7 charts will be empty.

## Adapting per cluster

The dashboards filter by `k8s.cluster.name` (set via the OTel collector's `clusterName` value, which this skill's overlay sets from `spec.cluster_name`). When you import the dashboards via `splunk-observability-dashboard-builder`:

- Pass `--filter k8s.cluster.name=<your-cluster-name>` to limit each chart to a specific cluster.
- Or leave the filter open to see all clusters in the same dashboard (useful for multi-cluster dashboards).

## Adding custom charts

If you need a chart not in the standard Cilium / Hubble dashboards, drop a custom SignalFlow program into `dashboards/<custom>.signalflow.yaml`:

```yaml
name: "My custom Cilium chart"
description: "Detect cilium_endpoint_regeneration_count anomaly"
charts:
  - name: "Endpoint regeneration rate"
    description: "Rate of endpoint regenerations per minute"
    program_text: |
      data('cilium_endpoint_regeneration_count')
        .rate('1m')
        .publish(label='regen_rate')
    publish_label: regen_rate
filters:
  - property: k8s.cluster.name
    value: ${CLUSTER_NAME}
```

Then `bash splunk-observability-isovalent-rendered/scripts/handoff-dashboards.sh` will pick up the new YAML and import it via the dashboard-builder skill.

## Tetragon dashboards

The reference repo does not ship a Tetragon-only dashboard (Tetragon's primary surface is Splunk Platform via `cisco_isovalent` index, not O11y dashboards). If you want O11y dashboards over `tetragon_*` series:

| Chart | Metric |
|-------|--------|
| Total events rate | `tetragon_events_total` (rate) |
| DNS query rate | `tetragon_dns_total` (rate) |
| HTTP response rate | `tetragon_http_response_total` (rate) |
| TCP retransmits | `tetragon_socket_stats_retransmitsegs_total` (rate) |
| Network connect/close rate | `tetragon_network_connect_total`, `tetragon_network_close_total` (rates) |

These are present in the metric allow-list by default; you just need to author the dashboard JSON.
