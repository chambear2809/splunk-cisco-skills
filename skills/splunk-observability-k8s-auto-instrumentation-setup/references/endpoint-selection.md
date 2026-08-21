# Endpoint Selection

The Instrumentation CR emits one endpoint at the top level and optionally per-language overrides. Picking the right endpoint depends on three dimensions: protocol (gRPC vs HTTP), port, and whether the base collector runs agent-per-node or gateway-only.

## gRPC (4317) vs HTTP (4318)

All Splunk language SDKs support both. Defaults:

| Language | Default chosen here | Notes |
|----------|---------------------|-------|
| Java | `grpc` 4317 | Both work |
| Node.js | `grpc` 4317 | Both work |
| Python | `http` 4318 (recommended) | gRPC support in `opentelemetry-python` has historically been less robust; use HTTP unless you have a strong reason |
| .NET | `http` 4318 (recommended) | `OpenTelemetry.Exporter.OpenTelemetryProtocol` HTTP is more common |
| Go | `grpc` 4317 | eBPF path; gRPC default |
| Apache HTTPD | `grpc` 4317 | |
| Nginx | `grpc` 4317 | |

Use `--per-language-endpoint python=http://$(SPLUNK_OTEL_AGENT):4318` to override.

## Agent DaemonSet vs gateway

### Default: agent DaemonSet

```
http://$(SPLUNK_OTEL_AGENT):4317
```

`$(SPLUNK_OTEL_AGENT)` is an env var the base collector chart injects into every instrumented pod. It expands to the node-local agent's Pod IP. Zero-hop network: traffic stays on the node, which minimizes latency and network egress cost.

### Gateway-only

```
http://<release>-splunk-otel-collector.<base-namespace>.svc.cluster.local:4317
```

The gateway Service has no `-gateway` suffix. Chart `0.158.0` names the gateway
workload and its Service after the release only (`component: otel-collector`),
and Helm collapses the name when the release is already called
`splunk-otel-collector` — which is this repository's default release name. So
with the default release the gateway Service is simply `splunk-otel-collector`,
and with release `my-release` it is `my-release-splunk-otel-collector`. Confirm
with `kubectl -n <base-namespace> get svc -l component=otel-collector` before
committing an endpoint.

Required when:

- `--distribution eks/fargate` — no DaemonSet possible.
- You disabled the agent DaemonSet in the base collector chart values.
- You run a multi-tenant cluster where the gateway is in a different namespace with tighter RBAC.

Use `--gateway-endpoint http://splunk-otel-collector.splunk-otel.svc.cluster.local:4317`.

## Running in a different namespace

If the Instrumentation CR is in `splunk-otel` but the annotated pods live in `payments`, DNS resolution still works because `$(SPLUNK_OTEL_AGENT)` is a pod-local env var, not a DNS name. Network path: pod -> node IP -> local agent on 4317.

## Gateway Service DNS format

| Distribution | Gateway Service DNS |
|--------------|---------------------|
| EKS / GKE / AKS / generic | `<release>-splunk-otel-collector.<ns>.svc.cluster.local:4317` |
| OpenShift | Same as above; Service type defaults to ClusterIP |
| EKS Fargate | Same; ensure Fargate profile includes the gateway namespace |

## TLS

The rendered endpoint is `http://` by default. If you have configured TLS on the base collector OTLP receiver, override with `https://<host>:4317` and ensure the application's runtime trusts the CA.

## HTTP endpoint details

When switching a language to HTTP/4318, the SDK sends OTLP/HTTP to:

- Traces: `/v1/traces`
- Metrics: `/v1/metrics`
- Logs: `/v1/logs`

The Splunk OTel Collector exposes all three by default on port 4318.

## Metrics endpoint (SignalFx protocol)

`SPLUNK_METRICS_ENDPOINT` (runtime metrics) is a SEPARATE endpoint on port 9943 (SignalFx protocol, not OTLP):

```
http://$(SPLUNK_OTEL_AGENT):9943/v2/datapoint
```

This is only read by Java and Node.js runtime metrics. If you use gateway-only, override to `http://<release>-splunk-otel-collector.<ns>.svc.cluster.local:9943/v2/datapoint`.

Chart `0.158.0` is the first audited chart whose gateway Service actually
publishes port `9943`; chart `0.154.0` exposed only `4317`, `4318`, `4320`,
`6060`, `9411`, `14250`, and `14268` on that Service, so a gateway-only
`SPLUNK_METRICS_ENDPOINT` override could not connect before this upgrade.
