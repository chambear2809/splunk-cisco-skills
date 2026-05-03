# Troubleshooting

## No `intersight.*` metrics in Splunk Observability Cloud

1. Confirm the `intersight-otel-collector` pod is running:

```bash
kubectl -n intersight-otel get pods
```

2. Confirm the Secret exists and has the right keys:

```bash
kubectl -n intersight-otel get secret intersight-secret -o jsonpath='{.data}' | jq 'keys'
# expect: ["key", "keyId"]
```

3. Tail the collector logs:

```bash
kubectl -n intersight-otel logs deployment/intersight-otel-collector --tail=200
```

Common errors:

- `unauthenticated: Failed to verify user identity`: wrong API key ID or expired private key. Regenerate via Intersight UI -> Settings -> API Keys.
- `auth: failed to sign JWT`: the private key isn't valid PEM. Verify with `openssl rsa -in /tmp/key.pem -check`.
- `dial tcp <agent>: i/o timeout`: the Intersight collector cannot reach the Splunk OTel agent over OTLP. Check the endpoint URL (`<release>-splunk-otel-collector-agent.splunk-otel.svc.cluster.local:4317`) and confirm port 4317 is exposed on the agent.

## Verify OTLP hand-off to the main collector

```bash
# Run a quick TCP check from inside the intersight-otel collector pod:
kubectl -n intersight-otel exec deployment/intersight-otel-collector -- \
  nc -zv <release>-splunk-otel-collector-agent.splunk-otel.svc.cluster.local 4317
```

If this fails, the OTLP receiver is not enabled on the Splunk OTel agent. Re-enable in the main chart's values:

```yaml
agent:
  config:
    receivers:
      otlp:
        protocols:
          grpc:
            endpoint: 0.0.0.0:4317
    service:
      pipelines:
        metrics:
          receivers: [otlp, ...]    # add otlp to the metrics pipeline
```

Then `helm upgrade` the main chart.

## Metrics arrive but show wrong cluster name

The agent DaemonSet's `resourcedetection` processor adds `k8s.cluster.name` to every metric, including OTLP-received ones from intersight-otel. If the cluster name is wrong, fix it in the main chart's values:

```yaml
clusterName: my-prod-cluster
```

(NOT in the intersight-otel ConfigMap; that ConfigMap doesn't add cluster attributes.)

## Polling is too slow / too fast

The default `collection_interval: 60s` is conservative. For larger fleets (>500 servers), bump to 120s to avoid Intersight API throttling. Intersight's documented rate limit is 1000 requests per 30s per API key.

The receiver paginates inventory queries; for an org with 5000+ servers, expect ~30s of API time per scrape cycle. Increase `collection_interval` accordingly.

## Receiver flooding the OTel agent

If you see `otelcol_exporter_send_failed_metric_points{exporter="signalfx"}` increasing on the main agent, the agent's signalfx exporter is back-pressuring upstream. The Intersight collector's OTLP exporter will retry with exponential backoff. Check the main agent's `memory_limiter` and bump the limit if needed.

## Permission denied on Secret

If the Deployment fails to start with `secret "intersight-secret" not found` or `forbidden`, the ServiceAccount used by the Deployment doesn't have read access. The skill's rendered manifests intentionally don't create a custom ServiceAccount; the default SA in the namespace must have Secret read.

For a hardened RBAC posture, render a custom ServiceAccount + Role + RoleBinding that grants read on `secrets/intersight-secret` only.

## High collector memory usage

If the intersight-otel collector pod is hitting its memory limit (default 500Mi), the cause is usually:

- A large org (10k+ servers) with the default `batch.send_batch_size: 1024`. Bump to 4096 to reduce buffering.
- A long backlog from a paused agent OTLP receiver. Restart the main agent to drain.
- A leaking older receiver version. Pin to v0.149.0+.

## Coordination with cisco-intersight-setup

If you've also run `cisco-intersight-setup` for Splunk Platform integration, both this skill and that skill can use the same Intersight API key (read-only scope, safe to share). Performance impact is minimal: each polls Intersight at ~60s intervals.
