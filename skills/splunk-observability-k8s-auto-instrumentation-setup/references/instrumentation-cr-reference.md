# Instrumentation CR Reference

The OpenTelemetry Operator `Instrumentation` custom resource (apiVersion `opentelemetry.io/v1alpha1`, kind `Instrumentation`) is the declarative contract between the operator's mutating webhook and the application pods it injects. This skill emits one or more `Instrumentation` CRs per render and binds each annotated workload to exactly one CR.

## Top-level spec fields this skill emits

| Field | Purpose | Notes |
|-------|---------|-------|
| `spec.exporter.endpoint` | OTLP endpoint used by every language agent in this CR | Default `http://$(SPLUNK_OTEL_AGENT):4317`; gateway endpoint required on EKS Fargate |
| `spec.propagators` | List of W3C / legacy propagators enabled in every language SDK | `tracecontext`, `baggage`, `b3`, `b3multi`, `jaeger`, `xray`, `ottrace`, `none` |
| `spec.sampler.type` | Sampler enum | `parentbased_always_on` (default), `parentbased_traceidratio`, etc. |
| `spec.sampler.argument` | Sampler tuning (ratio for `*_traceidratio`) | |
| `spec.env` | CR-wide env vars applied to every language block | Skill always adds `OTEL_RESOURCE_ATTRIBUTES` |
| `spec.defaults.useLabelsForResourceAttributes` | Copy pod labels to resource attributes | Enable to pick up `app`, `app.kubernetes.io/name`, `version`, `instance` |

## Per-language blocks

Each block has the same sub-structure: `image`, `env`, and `resourceRequirements` (optional).

### Java (`spec.java`)

```yaml
java:
  image: ghcr.io/signalfx/splunk-otel-java/splunk-otel-java@sha256:812ad3b45675ef90043020c10e9ed21a3f11ba0903a848e78e3fe71654ae622c
  env:
  - name: OTEL_EXPORTER_OTLP_ENDPOINT
    value: http://$(SPLUNK_OTEL_AGENT):4317
  - name: SPLUNK_PROFILER_ENABLED
    value: "true"
  - name: SPLUNK_PROFILER_MEMORY_ENABLED
    value: "true"
  - name: SPLUNK_METRICS_ENABLED
    value: "true"
  - name: SPLUNK_METRICS_ENDPOINT
    value: http://$(SPLUNK_OTEL_AGENT):9943/v2/datapoint
  resourceRequirements:
    limits: { cpu: "500m", memory: "128Mi" }
    requests: { cpu: "50m", memory: "64Mi" }
```

AlwaysOn Profiling requires JDK 8u262+; Oracle JDK 8 and IBM J9 are unsupported. Runtime metrics uses the agent's 9943/v2/datapoint SignalFx-protocol endpoint.

### Node.js (`spec.nodejs`)

```yaml
nodejs:
  image: ghcr.io/signalfx/splunk-otel-js/splunk-otel-js@sha256:55f93be18e545d98a981bba124fe94a02fdbbb88f1fc471aa08793f7ccba4d78
  env:
  - name: OTEL_EXPORTER_OTLP_ENDPOINT
    value: http://$(SPLUNK_OTEL_AGENT):4317
  - name: SPLUNK_PROFILER_ENABLED
    value: "true"
  - name: SPLUNK_METRICS_ENABLED
    value: "true"
```

Node supports profiling + runtime metrics. For custom npm paths use the `NODE_PATH` / `NODE_OPTIONS` env overrides.

### Python (`spec.python`)

```yaml
python:
  image: quay.io/signalfx/splunk-otel-instrumentation-python@sha256:d488c507e0cacc64b81423b96f6e53b30f2602a0e4bcc614658182f6aa13d5b4
  env:
  - name: OTEL_EXPORTER_OTLP_ENDPOINT
    value: http://$(SPLUNK_OTEL_AGENT):4318   # HTTP/4318 recommended
```

Python's auto-instrumentation uses `PYTHONPATH` to load `opentelemetry-bootstrap` before the application. The Splunk image bundles both glibc and musl builds; Alpine workloads Just Work.

### .NET (`spec.dotnet`)

```yaml
dotnet:
  image: ghcr.io/signalfx/splunk-otel-dotnet/splunk-otel-dotnet@sha256:1b8d96528c8138ef40a20fa0a58db423d653a9bcb7e1fa0fa5ecb83293b8e5bc
  env:
  - name: OTEL_EXPORTER_OTLP_ENDPOINT
    value: http://$(SPLUNK_OTEL_AGENT):4318
  - name: CORECLR_ENABLE_PROFILING
    value: "1"
  - name: CORECLR_PROFILER
    value: "{918728DD-259F-4A6A-AC2B-B85E1B658318}"
```

Linux-only (AMD64 only). Alpine/musl needs the workload annotation `instrumentation.opentelemetry.io/otel-dotnet-auto-runtime: linux-musl-x64`. .NET Framework is explicitly not supported — preflight refuses.

### Go (`spec.go`)

```yaml
go:
  image: ghcr.io/open-telemetry/opentelemetry-go-instrumentation/autoinstrumentation-go@sha256:664715c04cb854ffdbb920ea1289a86b0717f39e46b18e6584caa9e1f2e4d83f
  env:
  - name: OTEL_EXPORTER_OTLP_ENDPOINT
    value: http://$(SPLUNK_OTEL_AGENT):4317
```

Go uses eBPF, NOT bytecode rewriting — it requires an explicit target binary on every annotated workload via `instrumentation.opentelemetry.io/otel-go-auto-target-exe: /path/to/binary`. Preflight refuses render when that annotation is missing. Go also requires privileged init-container permissions, so PSS `restricted`/`baseline` namespaces are refused.

### Apache HTTPD (`spec.apacheHttpd`)

```yaml
apacheHttpd:
  image: ghcr.io/open-telemetry/opentelemetry-operator/autoinstrumentation-apache-httpd@sha256:a86df0699bf53228588d8e08dbd95e763b7bb377a02fe1d9e68806ef954d04f8
  configPath: /usr/local/apache2/conf
  version: "2.4"
```

The operator mounts `mod_otel_apache.so` into the Apache container and injects a `LoadModule` directive into the config file at `configPath`. The `version` field picks the right module binary.

### Nginx (`spec.nginx`)

```yaml
nginx:
  image: registry.example.test/reviewed-nginx-instrumentation@sha256:<64-hex-digest>
  configFile: /etc/nginx/nginx.conf
```

Works like the Apache block but injects an `otel_ngx_module.so` directive into `configFile`.

Nginx has no default because the repository's audited chart-0.158.0 image
ledger contains no Nginx entry. Rendering Nginx therefore fails closed unless
the operator supplies a reviewed digest-pinned override.

## Image immutability

The concrete defaults above come from the base Collector skill's audited
Kubernetes image ledger. Tags are deliberately omitted: `latest` and version
tags can both move. Every custom override must match
`<registry>/<repository>[:tag]@sha256:<64 lowercase hex>`; a tag without a
digest is a preflight failure. Updating a default requires updating the shared
source evidence and regression fixtures in the same review.


## Cross-namespace CR reference

Pod annotations may use `instrumentation.opentelemetry.io/inject-java: "splunk-otel/splunk-otel-prod"` to select a specific CR across namespaces. The operator looks up the Instrumentation CR by `<namespace>/<name>` from the annotation value. This is how multi-CR multi-env setups route workloads to different samplers / images.

## Immutability

Changes to CR `image`, `env`, and `resourceRequirements` do NOT automatically restart pods. The new settings take effect only on next pod restart. This skill's `apply-annotations.sh` triggers `kubectl rollout restart` explicitly; if you hand-edit a CR and want changes applied to already-running workloads, run `kubectl -n <ns> rollout restart <kind>/<name>` for each.

## Duplicate CRs

Two CRs with the same `metadata.namespace + metadata.name` are rejected by the API server. The preflight catalog also refuses render on duplicates from the spec so authoring errors surface early.

## Feature gates

Multiple named Instrumentation resources require no overlay-specific feature
gate. Each workload is bound explicitly to `<namespace>/<name>`. Operator chart
installation/tuning remains owned by the base collector skill; this overlay
fails closed if legacy operator-control inputs are supplied rather than
claiming to apply them.

## Source references

- `github.com/open-telemetry/opentelemetry-operator` — upstream CRD.
- `github.com/signalfx/splunk-otel-collector-chart` — `instrumentation:` block.
- Splunk Observability Cloud docs: per-language SDK image catalog and AlwaysOn Profiling env wiring.
