# Vendor Coexistence

Most operators running Splunk APM are moving off or coexisting with one of: Datadog, New Relic, AppDynamics, Dynatrace. Running two APM agents in the same application process is almost always wrong — the two agents instrument the same methods, collide on `JAVA_TOOL_OPTIONS` / `NODE_OPTIONS` / `CORECLR_PROFILER`, and produce duplicate traces. The correct pattern is **single-vendor-per-workload**.

## Detection

`--detect-vendors` scans the target cluster for mutating webhooks matching known vendor prefixes:

| Vendor | Webhook name pattern |
|--------|----------------------|
| Datadog | `datadog-webhook`, `datadogagent-admission` |
| New Relic | `newrelic-metadata-injection`, `newrelic-infrastructure` |
| AppDynamics | `appdynamics-operator` |
| Dynatrace | `dynatrace-webhook`, `dynatrace-oneagent` |

If a match is found and the target workloads overlap with the target namespaces, the preflight catalog emits a warning and adds an exclusion hint to the rendered `preflight-report.md`.

## Collision env vars

If a vendor agent is still injected via the Pod spec (not just via a webhook), the operator's init container and the vendor agent will both set:

| Env | Vendor | Splunk |
|-----|--------|--------|
| `JAVA_TOOL_OPTIONS` | `-javaagent:/dd-java-agent.jar` | `-javaagent:/otel-agent.jar` |
| `NODE_OPTIONS` | `--require=dd-trace/init` | `--require=@splunk/otel/instrument` |
| `PYTHONPATH` | `/dd/pylib` | `/otel/python` |
| `CORECLR_PROFILER` | `{846F5F1C-F9AE-4B07-969E-05C26BC060D8}` (dd-trace-dotnet) | `{918728DD-259F-4A6A-AC2B-B85E1B658318}` (OTel) |

**Only one value can win**, and the second-applied value typically clobbers the first. Preflight also warns when a target workload's existing Pod spec already has these env set (inspection happens at apply time via `apply-annotations.sh`).

## Exclusion

`--exclude-vendor datadog` emits migration guidance in `migration-guide.md` with the exact removal steps per vendor:

### Datadog

1. Remove the `ad.datadoghq.com/app.check_names` / `ad.datadoghq.com/app.instances` annotations.
2. Strip `JAVA_TOOL_OPTIONS=-javaagent:/dd-java-agent.jar` (and similar for Node / Python / .NET).
3. Remove the `dd-java-agent.jar` volume mount.
4. Delete any `DD_*` env vars (`DD_SERVICE`, `DD_ENV`, `DD_VERSION`, `DD_AGENT_HOST`).

### New Relic

1. Remove the `newrelic.com/agent-sidecar-injection: enabled` annotation.
2. Strip `NEW_RELIC_LICENSE_KEY`, `NEW_RELIC_APP_NAME`.
3. Remove the `newrelic-agent` init container (if baked into the Pod spec).

### AppDynamics

1. Remove the `appdynamics.agent.metadataInjector` annotation.
2. Strip `APPDYNAMICS_*` env.
3. Remove the AppD SDK volume mount.

### Dynatrace

1. Remove the `dynatrace.com/inject: true` annotation.
2. Strip `LD_PRELOAD` and `DT_*` env.
3. OneAgent runs node-level, not pod-level — additional cleanup may happen outside the Pod spec.

## Same-cluster coexistence

Running Splunk on some workloads and (say) Datadog on others in the same cluster is fine. Vendor mutating webhooks are namespace-scoped or label-selector-scoped in most cases. `--detect-vendors` specifically flags *per-workload* overlap, not cluster-wide presence.

## Migration advisory

Cutover from a vendor to Splunk is a two-phase process:

1. Annotate the workload for Splunk (`inject-<lang>: "true"`) while the vendor is still injecting — you may see traces on both platforms with `JAVA_TOOL_OPTIONS` / `NODE_OPTIONS` collisions; expect some traces to drop.
2. Strip the vendor injection (remove annotations, env, mounts) and `kubectl rollout restart`. The pods will now emit only to Splunk.

Never do both at once; always phase.
