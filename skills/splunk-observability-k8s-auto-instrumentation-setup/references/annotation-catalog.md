# Annotation Catalog

Every annotation below is placed at `spec.template.metadata.annotations` on a `Deployment`, `StatefulSet`, or `DaemonSet` (or at `metadata.annotations` on a `Namespace`). This skill's strategic-merge patches target only the pod-template annotation path; see [annotation-surgery.md](annotation-surgery.md) for the mechanics.

## Language-select annotations

| Annotation | Value | Effect |
|------------|-------|--------|
| `instrumentation.opentelemetry.io/inject-java` | `"true"` | Inject Java SDK via the default CR |
| `instrumentation.opentelemetry.io/inject-java` | `"<ns>/<crname>"` | Inject using the specific CR |
| `instrumentation.opentelemetry.io/inject-java` | `"false"` | Explicit opt-out for this pod |
| `instrumentation.opentelemetry.io/inject-nodejs` | same shape | Node.js |
| `instrumentation.opentelemetry.io/inject-python` | same shape | Python |
| `instrumentation.opentelemetry.io/inject-dotnet` | same shape | .NET (Linux only) |
| `instrumentation.opentelemetry.io/inject-go` | same shape + requires target-exe below | Go (eBPF) |
| `instrumentation.opentelemetry.io/inject-apache-httpd` | same shape | Apache HTTPD (`mod_otel_apache.so`) |
| `instrumentation.opentelemetry.io/inject-nginx` | same shape | Nginx (`otel_ngx_module.so`) |
| `instrumentation.opentelemetry.io/inject-sdk` | same shape | Env-only; language-agnostic |

## Container selection

| Annotation | Value |
|------------|-------|
| `instrumentation.opentelemetry.io/container-names` | Comma-separated list of container names to instrument (e.g. `"app,worker"`). Required in Istio-enabled namespaces so the sidecar proxy container is skipped. |

## Language-specific overrides

| Annotation | Language | Value |
|------------|----------|-------|
| `instrumentation.opentelemetry.io/otel-dotnet-auto-runtime` | .NET | `linux-x64` (default) or `linux-musl-x64` (Alpine) |
| `instrumentation.opentelemetry.io/otel-go-auto-target-exe` | Go | Absolute path to the compiled binary to instrument. Mandatory for Go. |

## Namespace-level opt-in

Set any of the `inject-<lang>` annotations on a `Namespace` object to auto-instrument every pod created in that namespace. Annotated workloads can still opt out per-pod with `"false"`.

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: dev-java-services
  annotations:
    instrumentation.opentelemetry.io/inject-java: "true"
```

## Ordering and precedence

1. Pod-template annotation with an explicit `"false"` wins (pod is not instrumented).
2. Otherwise a pod-template annotation with `<ns>/<name>` selects a specific CR.
3. Otherwise a pod-template annotation with `"true"` uses the default CR (same namespace as the pod, named in chart values).
4. Otherwise, if the namespace has an `inject-<lang>` annotation, that applies.
5. Otherwise the pod is not instrumented.

## Opt-out recipes

- Instrument every pod in a namespace except one: namespace annotation `inject-java: "true"` + the target pod's workload template annotation `inject-java: "false"`.
- Temporarily disable instrumentation for debugging: patch the pod template with `"false"`, `kubectl rollout restart`, then re-patch with `"true"` when done.
