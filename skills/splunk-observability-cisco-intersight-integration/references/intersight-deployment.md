# intersight-otel deployment

The Cisco Intersight integration ships in a **separate Kubernetes namespace** from the main Splunk OTel collector. This annex explains why and how.

## Why a separate namespace + Deployment?

The Cisco Intersight integration is a **single-instance, OAuth2 + JWT polling** workload. Co-locating it with the Splunk OTel collector chart in the same namespace creates several problems:

- The OTel chart's RBAC ClusterRole grants cluster-wide read on pods, services, endpoints, etc. The Intersight integration only needs to talk to Intersight's REST API; it does not need any cluster permissions.
- The OTel chart deploys both an agent DaemonSet (one per node) and a clusterReceiver Deployment. Adding Intersight to the agent DaemonSet would multiply Intersight API calls by node count; adding to the clusterReceiver couples Intersight's OAuth2 lifecycle to the cluster-receiver's restart cycle.
- Intersight credentials are sensitive (private RSA key + key ID = bearer-equivalent). Isolating them in a dedicated namespace allows separate Secret-access RBAC.

The skill therefore renders:

- `manifests/namespace.yaml` — `intersight-otel` namespace (configurable via `spec.namespace`).
- `manifests/intersight-secret.yaml` — placeholder Secret manifest with no values; operator fills in `keyId` and `key` after rendering.
- `manifests/intersight-otel-config.yaml` — ConfigMap with the OTel collector config tuned for Intersight.
- `manifests/intersight-otel-deployment.yaml` — Deployment that mounts the ConfigMap + Secret and runs `otel/opentelemetry-collector-contrib:<version>`.

## Why upstream contrib instead of Splunk distribution?

The Intersight integration uses the upstream `opentelemetry-collector-contrib` image (`otel/opentelemetry-collector-contrib`) instead of the Splunk distribution (`quay.io/signalfx/splunk-otel-collector`) for two reasons:

1. The Cisco Intersight receiver lives in upstream contrib (`receiver/cisco_intersight`); it is not in the Splunk distribution as of v0.149.0.
2. The integration does NOT export to Splunk Observability Cloud directly. It exports OTLP gRPC to the **agent DaemonSet** of the main Splunk OTel collector (running in `splunk-otel` namespace), which then handles all O11y ingest authentication, batching, and retry. The Intersight collector itself never sees the O11y access token.

The hand-off endpoint is `<release>-splunk-otel-collector-agent.<splunk-otel-namespace>.svc.cluster.local:4317`. The agent DaemonSet exposes OTLP gRPC on port 4317 by default in the chart; if you've disabled it, re-enable via `agent.config.receivers.otlp.protocols.grpc` in the main collector's values.yaml.

## Deployment shape

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: intersight-otel-collector
  namespace: intersight-otel
spec:
  replicas: 1                       # Intersight is single-instance; do NOT scale.
  selector: { matchLabels: { app: intersight-otel-collector } }
  template:
    metadata: { labels: { app: intersight-otel-collector } }
    spec:
      containers:
        - name: collector
          image: otel/opentelemetry-collector-contrib:v0.149.0
          args: ["--config=/conf/config.yaml"]
          env:
            - name: INTERSIGHT_KEY_ID
              valueFrom:
                secretKeyRef: { name: intersight-secret, key: keyId }
            - name: INTERSIGHT_KEY
              valueFrom:
                secretKeyRef: { name: intersight-secret, key: key }
          volumeMounts:
            - { name: config, mountPath: /conf }
          resources:
            requests: { cpu: 50m, memory: 100Mi }
            limits: { cpu: 200m, memory: 500Mi }
      volumes:
        - name: config
          configMap: { name: intersight-otel-config }
```

Single replica is intentional: the Intersight receiver maintains state (auth token, paging cursor) per-instance. Two replicas would duplicate metric points and confuse the upstream pipeline.

## ConfigMap shape

```yaml
receivers:
  cisco_intersight:
    collection_interval: 60s
    api_key_id: ${env:INTERSIGHT_KEY_ID}
    api_private_key: ${env:INTERSIGHT_KEY}
    base_url: https://intersight.com    # Override for SaaS-Connected vs SaaS-Only

processors:
  batch:
    timeout: 10s
    send_batch_size: 1024

exporters:
  otlp:
    endpoint: <release>-splunk-otel-collector-agent.splunk-otel.svc.cluster.local:4317
    tls: { insecure: true }            # internal cluster traffic; mTLS is optional

service:
  pipelines:
    metrics:
      receivers: [cisco_intersight]
      processors: [batch]
      exporters: [otlp]
```

## Why hand off OTLP to the main agent?

This pattern (Intersight collector -> OTLP -> Splunk OTel agent) gives you:

- **Centralized credential**: the O11y access token lives only in the Splunk OTel agent's Secret. The Intersight collector never sees it.
- **Centralized retry/batch**: the Splunk OTel agent's signalfx exporter handles O11y back-pressure, retries, and batching. The Intersight collector only needs a fast in-cluster OTLP endpoint.
- **Shared resource attributes**: the agent's `resourcedetection` processor adds k8s/cluster attrs to every metric, including Intersight metrics, before O11y ingest.

This pattern is also documented in the Splunk Observability Cloud OTel quickstart for "external sources" (databases, cloud APIs, etc.).

## Coordination with cisco-intersight-setup

`cisco-intersight-setup` configures the Splunk Add-on for Cisco Intersight (Splunk_TA_Cisco_Intersight). That TA pulls Intersight events + audit + alarm + inventory into Splunk Platform. This skill pulls **metrics** into Splunk Observability Cloud. Both are complementary:

- `cisco-intersight-setup` -> events, audit, alarm, inventory in Splunk Platform.
- `splunk-observability-cisco-intersight-integration` -> compute infrastructure metrics in Splunk Observability Cloud.

Both skills can use the same Intersight OAuth2 client; the API key has read-only scope, so duplicating it across both is safe.
