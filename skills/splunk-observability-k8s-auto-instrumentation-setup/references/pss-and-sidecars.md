# Pod Security Standards and Sidecars

## Pod Security Standards (PSS)

Kubernetes 1.25+ replaced PodSecurityPolicy with Pod Security Standards, enforced at the namespace level via the label `pod-security.kubernetes.io/enforce`. Valid values are `privileged` (no restrictions), `baseline` (blocks elevated privilege), and `restricted` (tightly sandboxed).

Operator-driven auto-instrumentation is mostly PSS-neutral (the operator injects an init container that copies agent files into a shared volume and is not privileged). The exceptions:

| Path | PSS requirement | Reason |
|------|-----------------|--------|
| Go auto-instrumentation | `privileged` only | Uses eBPF; needs capabilities beyond `restricted`. |
| OBI DaemonSet (`--enable-obi`) | `privileged` only | eBPF + hostPath + `SYS_ADMIN`. |
| Any other language | `baseline` or `restricted` | Safe. Init container runs with default securityContext. |

### Fail-render guards

The preflight catalog refuses render when any of:

1. A workload in a `restricted` or `baseline` namespace is annotated with `inject-go`.
2. `--enable-obi` is set and a target namespace is `restricted`/`baseline` (unless `pss_overrides[].acknowledged: true` is present for that namespace).

### Overrides

When you've already exempted a namespace (e.g. via an `exemptions:` block in `PodSecurityConfiguration`), declare it in the spec so render passes:

```yaml
pss_overrides:
  - namespace: prod-go
    enforce: restricted
    acknowledged: true
    rationale: "Namespace is exempted at the admission-controller layer."
```

## Istio and sidecar injection ordering

Istio automatic sidecar injection also uses a mutating webhook. When both the OpenTelemetry Operator's webhook and Istio's webhook target the same Pod template, the order is determined by the `reinvocationPolicy` field on each webhook:

- OpenTelemetry Operator: `reinvocationPolicy: Never` (default in the operator chart).
- Istio: `reinvocationPolicy: IfNeeded` (default in istio-system).

The result is a Pod spec with:

1. `istio-init` / `istio-proxy` sidecar containers injected by Istio.
2. `opentelemetry-auto-instrumentation` init container injected by the operator.

### Preflight warning

In an `istio-injection=enabled` namespace, the operator's init container will instrument **every** container in the Pod by default, including `istio-proxy`. This is almost always wrong (istio-proxy is not your application code). The preflight catalog warns when a target namespace has `istio-injection=enabled` but the workload annotation lacks `container-names=`. The fix:

```yaml
annotations:
  instrumentation.opentelemetry.io/inject-java: "true"
  instrumentation.opentelemetry.io/container-names: "app"   # only the app container, not istio-proxy
```

### Deeper nuance

- `container-names` accepts multiple comma-separated names if your Pod has a sidecar you DO want instrumented (e.g. an envoy worker container that's not istio-proxy).
- Istio's outbound traffic capture interacts with OTLP export. If your CR endpoint is `http://$(SPLUNK_OTEL_AGENT):4317`, traffic stays on-node and Istio does not touch it. If the endpoint is a gateway Service DNS, Istio sidecars intercept; you may need an Istio `ServiceEntry` for the gateway.
