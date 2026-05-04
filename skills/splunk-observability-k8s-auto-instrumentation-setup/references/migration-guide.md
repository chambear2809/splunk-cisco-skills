# Migration Guide

## From SignalFx Smart Agent auto-instrumentation

The SignalFx Smart Agent (deprecated) used a per-host daemon and language-specific libraries that injected themselves via `LD_PRELOAD` or `JAVA_TOOL_OPTIONS`. Migrating to operator-driven auto-instrumentation:

1. Verify the base `splunk-otel-collector` chart is installed with the operator + CRDs.
2. Identify workloads currently managed by Smart Agent. The telltale signs:
   - `SIGNALFX_*` env on the Pod spec.
   - `JAVA_TOOL_OPTIONS=-javaagent:/signalfx-java-tracing.jar`.
   - `NODE_OPTIONS=--require=signalfx-tracing`.
   - A `smart-agent` init container or sidecar.
3. Render this skill with the same workloads annotated:
   ```bash
   bash skills/splunk-observability-k8s-auto-instrumentation-setup/scripts/setup.sh \
     --render --languages java,nodejs,python \
     --annotate-workload Deployment/prod/payments-api=java \
     --realm us0 --cluster-name prod --deployment-environment prod
   ```
4. Apply CRs but NOT annotations yet.
5. Strip Smart Agent env and mounts from the workloads (hand-edit, or via your CD pipeline).
6. Apply the operator annotations and restart.
7. Validate traces now land under the new `service.name` (derived from pod labels unless overridden).

## From a manual OTel SDK

If your apps already call `opentelemetry-sdk` directly:

- Use `inject-sdk` (not a language-specific `inject-java`). That path only sets env vars (endpoint, resource attrs, propagators) without injecting an agent binary — your existing SDK code keeps working.
- Or, if you want the operator to own the SDK entirely: remove the manual `OpenTelemetrySdk.builder(...)` calls, then use `inject-java` (or the language's own annotation).

## From another APM vendor

See [vendor-coexistence.md](vendor-coexistence.md) for per-vendor env/mount/annotation removal steps. Never run two APM agents on the same workload.

Phased approach:

1. Pick one non-critical workload as a pilot.
2. Annotate it for Splunk while the vendor is still injecting (brief period of collisions; expect dropped traces).
3. Strip vendor injection.
4. `kubectl rollout restart`.
5. Verify traces land only in Splunk APM.
6. Repeat for the next workload.

## Per-language collision env

Before you annotate, check the target workload for these existing env vars:

```bash
kubectl -n <ns> get <kind>/<name> -o jsonpath='{.spec.template.spec.containers[*].env}' | tr ',' '\n' | grep -E 'JAVA_TOOL_OPTIONS|NODE_OPTIONS|PYTHONPATH|CORECLR_PROFILER|OTEL_'
```

If any of those are set, the operator's injection will fight with them. Resolution:

- If the value is another vendor's agent: follow the vendor removal steps in `vendor-coexistence.md`.
- If the value is a manual OTel SDK: switch to `inject-sdk` instead of `inject-<lang>`.
- If the value is an unrelated OTel env set by platform tooling: merge it into `extra_env` in this skill's spec so the final env is a strict superset.

## Service-name continuity

When migrating, `service.name` is the trace's primary identity in APM. Default source:

- `app.kubernetes.io/name` label if `useLabelsForResourceAttributes: true`, else
- `app` label, else
- workload name.

If your vendor used a different service-name convention, set it explicitly via `extra_resource_attrs.service.name` per workload, or via `OTEL_SERVICE_NAME` env.

## Metrics and profiling carry-over

- Runtime metrics in Smart Agent correspond to `SPLUNK_METRICS_ENABLED=true` here.
- Smart Agent Java profiling corresponds to `SPLUNK_PROFILER_ENABLED=true`.

The landing location in APM is the same, so dashboards and detectors typically continue to work.
